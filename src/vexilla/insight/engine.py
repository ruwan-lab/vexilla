"""InsightEngine — orchestrates enrichment, heuristic evaluation, and insight storage.

Runs on a configurable schedule (default every 60 s).
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

from vexilla.insight.heuristics import (
    background_spike,
    beaconing,
    heavy_background_app,
    new_domain,
    tracker,
    unnamed_endpoint_volume,
)
from vexilla.insight.models import Insight
from vexilla.insight.templates import daily_summary_text, empty_summary_text
from vexilla.kb.reader import KbReader
from vexilla.store import Database

logger = logging.getLogger(__name__)

# Minimum interval between summary regenerations (seconds).
SUMMARY_COOLDOWN = 3600  # 1 hour


class InsightEngine:
    """Evaluates heuristics against recent data and writes insight rows.

    Uses the store database directly (reads flows/agg_hourly, writes insight/summary).
    """

    def __init__(
        self,
        db: Database,
        kb: Optional[KbReader] = None,
        insight_interval: float = 60.0,
    ) -> None:
        self._db = db
        self._kb = kb or KbReader()
        self._insight_interval = insight_interval
        self._last_summary_time: float = 0.0
        self._last_insight_scan: int = 0  # timestamp of last insight scan

    @property
    def insight_interval(self) -> float:
        return self._insight_interval

    def run(self) -> None:
        """Run one insight evaluation cycle.

        1. Read recent flow/aggregate data
        2. Enrich domains from KB
        3. Evaluate all heuristics
        4. Write new insight rows
        5. Regenerate daily summary if stale
        """
        now = int(time.time())
        new_insights: list[Insight] = []

        # Get all apps with recent activity
        apps = self._db.execute(
            """SELECT DISTINCT f.app_id, a.name, a.exe_path
               FROM flow f JOIN app a ON f.app_id = a.id
               WHERE f.last_seen >= ?""",
            (now - 3600,),
        ).fetchall()

        for app_row in apps:
            app_id = app_row[0]
            app_name = app_row[1]

            # Get unique endpoints this app contacted recently
            endpoints = self._db.execute(
                """SELECT DISTINCT f.endpoint_id, e.ip, e.domain
                   FROM flow f JOIN endpoint e ON f.endpoint_id = e.id
                   WHERE f.app_id = ? AND f.last_seen >= ?""",
                (app_id, now - 86400),
            ).fetchall()

            today_bg_bytes = 0
            latest_bg_bytes = 0

            for ep_row in endpoints:
                ep_id = ep_row[0]
                ip = ep_row[1]
                domain = ep_row[2] or ip

                # KB enrichment
                kb_info = self._kb.lookup(domain)

                # Get aggregate totals for this (app, endpoint)
                agg_totals = self._db.execute(
                    """SELECT COALESCE(SUM(bytes_sent + bytes_recv), 0),
                              COALESCE(SUM(conn_count), 0),
                              COALESCE(SUM(bg_bytes), 0)
                       FROM agg_hourly
                       WHERE app_id = ? AND endpoint_id = ?
                         AND hour_start >= ?""",
                    (app_id, ep_id, self._today_start()),
                ).fetchone()

                total_bytes = agg_totals[0] if agg_totals else 0
                conn_count = agg_totals[1] if agg_totals else 0
                ep_bg_bytes = agg_totals[2] if agg_totals else 0

                today_bg_bytes += ep_bg_bytes

                # ── Check heuristics ──────────────────────────────

                # 1. New domain
                insight = new_domain(
                    app_name, domain, app_id, ep_id, self._db, kb_info
                )
                if insight and not self._insight_exists(insight):
                    new_insights.append(insight)

                # 2. Tracker
                insight = tracker(app_name, domain, app_id, ep_id, kb_info, conn_count)
                if insight and not self._insight_exists(insight):
                    new_insights.append(insight)

                # 3. Beaconing (needs time-gap analysis on recent flows)
                gaps = self._get_time_gaps(app_id, ep_id, 30)
                insight = beaconing(app_name, domain, app_id, ep_id, gaps)
                if insight and not self._insight_exists(insight):
                    new_insights.append(insight)

                # 6. Unnamed endpoint volume
                if domain == ip or not domain or domain == "(unknown)":
                    insight = unnamed_endpoint_volume(
                        app_name, ip, ep_id, total_bytes
                    )
                    if insight and not self._insight_exists(insight):
                        new_insights.append(insight)

            # 4. Background spike (per-app, per-hour)
            latest_hour = (now // 3600) * 3600
            hourly_bg = self._db.execute(
                """SELECT COALESCE(SUM(bg_bytes), 0)
                   FROM agg_hourly
                   WHERE app_id = ? AND hour_start = ?""",
                (app_id, latest_hour),
            ).fetchone()
            if hourly_bg:
                bg_val = hourly_bg[0]
                if bg_val > 0:
                    insight = background_spike(app_name, app_id, bg_val, self._db)
                    if insight and not self._insight_exists(insight):
                        new_insights.append(insight)

            # 5. Heavy background app
            insight = heavy_background_app(app_name, app_id, today_bg_bytes)
            if insight and not self._insight_exists(insight):
                new_insights.append(insight)

        # Write new insights
        for ins in new_insights:
            try:
                self._db.execute(
                    """INSERT INTO insight
                       (kind, severity, app_id, endpoint_id,
                        title, body, suggestion, evidence, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        ins.kind,
                        ins.severity,
                        ins.app_id,
                        ins.endpoint_id,
                        ins.title,
                        ins.body,
                        ins.suggestion,
                        ins.evidence_json(),
                        ins.created_at,
                    ),
                )
                logger.debug("Created insight: %s — %s", ins.kind, ins.title)
            except Exception as exc:
                logger.warning("Failed to write insight: %s", exc)

        try:
            self._db._get_conn().commit()
        except Exception:
            pass

        if new_insights:
            logger.info("Created %d new insight(s)", len(new_insights))

        # Regenerate daily summary if stale
        self._regenerate_summary(now)

        self._last_insight_scan = now

    # ── Summary generation ─────────────────────────────────────────

    def _regenerate_summary(self, now: int) -> None:
        """Regenerate the daily summary if stale or if new insights exist."""
        if time.monotonic() - self._last_summary_time < SUMMARY_COOLDOWN:
            return

        day_start = self._today_start()

        # Aggregate today's stats from agg_hourly
        row = self._db.execute(
            """SELECT COUNT(DISTINCT app_id), COUNT(DISTINCT endpoint_id),
                      COALESCE(SUM(bytes_sent + bytes_recv), 0),
                      COALESCE(SUM(bg_bytes), 0)
               FROM agg_hourly WHERE hour_start >= ?""",
            (day_start,),
        ).fetchone()

        app_count = row[0] or 0
        domain_count = row[1] or 0
        total_bytes = row[2] or 0
        bg_bytes = row[3] or 0

        # Top app
        top_row = self._db.execute(
            """SELECT a.name, SUM(ag.bytes_sent + ag.bytes_recv)
               FROM agg_hourly ag JOIN app a ON ag.app_id = a.id
               WHERE ag.hour_start >= ?
               GROUP BY a.id ORDER BY 2 DESC LIMIT 1""",
            (day_start,),
        ).fetchone()

        top_app_name = top_row[0] if top_row else None
        top_app_mb = (top_row[1] or 0) / 1048576 if top_row else 0.0

        # Tracker count (we don't have KB in agg, so approximate from insight)
        tracker_count = self._db.execute(
            """SELECT COUNT(*) FROM insight
               WHERE kind = 'tracker' AND created_at >= ?""",
            (day_start,),
        ).fetchone()[0]

        # Flag count
        flag_count = self._db.execute(
            "SELECT COUNT(*) FROM insight WHERE dismissed = 0 AND created_at >= ?",
            (day_start,),
        ).fetchone()[0]

        # Build text
        if app_count == 0:
            text = empty_summary_text()
        else:
            text = daily_summary_text(
                app_count=app_count,
                domain_count=domain_count,
                total_mb=total_bytes / 1048576,
                bg_mb=bg_bytes / 1048576,
                top_app_name=top_app_name,
                top_app_mb=top_app_mb,
                tracker_count=tracker_count,
                flag_count=flag_count,
            )

        stats_json = json.dumps(
            {
                "app_count": app_count,
                "domain_count": domain_count,
                "total_bytes": total_bytes,
                "bg_bytes": bg_bytes,
                "top_app": top_app_name,
                "tracker_count": tracker_count,
                "flag_count": flag_count,
            }
        )

        # Upsert the summary row
        self._db.execute(
            """INSERT INTO summary (day_start, text, stats_json, generated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(day_start) DO UPDATE SET
                   text = excluded.text,
                   stats_json = excluded.stats_json,
                   generated_at = excluded.generated_at""",
            (day_start, text, stats_json, now),
        )
        self._db._get_conn().commit()
        self._last_summary_time = time.monotonic()
        logger.info("Summary regenerated for day %d", day_start)

    # ── Helpers ───────────────────────────────────────────────────

    def _insight_exists(self, insight: Insight) -> bool:
        """Check if a similar insight was already created recently."""
        hour_ago = insight.created_at - 3600
        row = self._db.execute(
            """SELECT COUNT(*) FROM insight
               WHERE kind = ? AND app_id IS ? AND endpoint_id IS ?
                 AND created_at >= ?""",
            (insight.kind, insight.app_id, insight.endpoint_id, hour_ago),
        ).fetchone()
        return row is not None and row[0] > 0

    def _get_time_gaps(
        self, app_id: int, endpoint_id: int, max_samples: int = 30
    ) -> list[float]:
        """Get time gaps between consecutive connections for beaconing detection."""
        rows = self._db.execute(
            """SELECT last_seen FROM flow
               WHERE app_id = ? AND endpoint_id = ?
               ORDER BY last_seen DESC LIMIT ?""",
            (app_id, endpoint_id, max_samples),
        ).fetchall()

        if len(rows) < 2:
            return []

        timestamps = sorted(r[0] for r in rows)
        gaps = []
        for i in range(1, len(timestamps)):
            gap = timestamps[i] - timestamps[i - 1]
            if gap > 0:
                gaps.append(float(gap))

        return gaps

    @staticmethod
    def _today_start() -> int:
        now = time.time()
        return int(now - now % 86400)
