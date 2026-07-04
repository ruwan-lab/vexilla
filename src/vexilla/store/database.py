"""Database — create, migrate, and access the runtime SQLite store.

Schema is the contract (see docs/data-model.md). Do not deviate.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

# ── Full schema from docs/data-model.md ────────────────────────────

CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS app (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    exe_path     TEXT,
    first_seen   INTEGER NOT NULL,
    last_seen    INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_app_name ON app(name);

CREATE TABLE IF NOT EXISTS endpoint (
    id           INTEGER PRIMARY KEY,
    ip           TEXT NOT NULL,
    domain       TEXT,
    name_source  TEXT,
    first_seen   INTEGER NOT NULL,
    last_seen    INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_endpoint_ip ON endpoint(ip);

CREATE TABLE IF NOT EXISTS flow (
    id             INTEGER PRIMARY KEY,
    app_id         INTEGER NOT NULL REFERENCES app(id),
    endpoint_id    INTEGER NOT NULL REFERENCES endpoint(id),
    protocol       TEXT NOT NULL,
    remote_port    INTEGER NOT NULL,
    bytes_sent     INTEGER NOT NULL DEFAULT 0,
    bytes_recv     INTEGER NOT NULL DEFAULT 0,
    is_background  INTEGER NOT NULL DEFAULT 0,
    started_at     INTEGER NOT NULL,
    last_seen      INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_flow_app   ON flow(app_id, last_seen);
CREATE INDEX IF NOT EXISTS idx_flow_ep    ON flow(endpoint_id, last_seen);
CREATE INDEX IF NOT EXISTS idx_flow_time  ON flow(last_seen);

CREATE TABLE IF NOT EXISTS dns_cache (
    id           INTEGER PRIMARY KEY,
    ip           TEXT NOT NULL,
    domain       TEXT NOT NULL,
    observed_at  INTEGER NOT NULL,
    ttl          INTEGER,
    UNIQUE(ip, domain)
);

CREATE INDEX IF NOT EXISTS idx_dns_ip ON dns_cache(ip);

CREATE TABLE IF NOT EXISTS agg_hourly (
    id            INTEGER PRIMARY KEY,
    hour_start    INTEGER NOT NULL,
    app_id        INTEGER REFERENCES app(id),
    endpoint_id   INTEGER REFERENCES endpoint(id),
    bytes_sent    INTEGER NOT NULL DEFAULT 0,
    bytes_recv    INTEGER NOT NULL DEFAULT 0,
    conn_count    INTEGER NOT NULL DEFAULT 0,
    bg_bytes      INTEGER NOT NULL DEFAULT 0,
    UNIQUE(hour_start, app_id, endpoint_id)
);

CREATE INDEX IF NOT EXISTS idx_agg_hour ON agg_hourly(hour_start);

CREATE TABLE IF NOT EXISTS insight (
    id            INTEGER PRIMARY KEY,
    kind          TEXT NOT NULL,
    severity      TEXT NOT NULL,
    app_id        INTEGER REFERENCES app(id),
    endpoint_id   INTEGER REFERENCES endpoint(id),
    title         TEXT NOT NULL,
    body          TEXT NOT NULL,
    suggestion    TEXT,
    evidence      TEXT,
    created_at    INTEGER NOT NULL,
    dismissed     INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_insight_created ON insight(created_at, dismissed);

CREATE TABLE IF NOT EXISTS summary (
    id            INTEGER PRIMARY KEY,
    day_start     INTEGER NOT NULL UNIQUE,
    text          TEXT NOT NULL,
    stats_json    TEXT NOT NULL,
    generated_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS setting (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schema_meta (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);
"""


class Database:
    """Thread-safe SQLite store with WAL mode and schema migration."""

    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None

    # ── Lifecycle ───────────────────────────────────────────────────

    def initialize(self) -> None:
        """Open DB, enable WAL, apply schema, verify version."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if self._conn is None:
            self._conn = self._open()
        with self._lock:
            self._conn.executescript(CREATE_TABLES)
            self._ensure_schema_version()
        logger.info("Database ready at %s", self._path)

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
            logger.debug("Database closed")

    @property
    def path(self) -> Path:
        return self._path

    # ── Health ──────────────────────────────────────────────────────

    def is_healthy(self) -> bool:
        """Return True if the database is reachable and schema is current."""
        try:
            row = self._get_conn().execute(
                "SELECT value FROM schema_meta WHERE key = 'version'"
            ).fetchone()
            return row is not None and int(row[0]) == SCHEMA_VERSION
        except Exception:
            return False

    # ── Settings helpers ────────────────────────────────────────────

    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        row = self._get_conn().execute(
            "SELECT value FROM setting WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else default

    def set_setting(self, key: str, value: str) -> None:
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO setting (key, value) VALUES (?, ?)",
            (key, value),
        )
        conn.commit()

    def delete_setting(self, key: str) -> None:
        conn = self._get_conn()
        conn.execute("DELETE FROM setting WHERE key = ?", (key,))
        conn.commit()

    # ── Aggregation ────────────────────────────────────────────────

    def fill_missing_aggregates(self) -> None:
        """Batch-aggregate any flow rows not yet represented in agg_hourly.

        Runs at startup to backfill any hours missed during downtime.
        Uses the flow data to compute per-hour, per-app, per-endpoint
        summaries and inserts/merges them into agg_hourly.
        """
        conn = self._get_conn()
        now = int(__import__("time").time())
        cutoff = now - 86400 * 90  # scan up to 90 days back

        conn.execute(
            """INSERT OR IGNORE INTO agg_hourly
               (hour_start, app_id, endpoint_id,
                bytes_sent, bytes_recv, conn_count, bg_bytes)
               SELECT
                   (f.last_seen / 3600) * 3600,
                   f.app_id,
                   f.endpoint_id,
                   SUM(f.bytes_sent),
                   SUM(f.bytes_recv),
                   COUNT(*),
                   SUM(CASE WHEN f.is_background THEN f.bytes_sent + f.bytes_recv ELSE 0 END)
               FROM flow f
               WHERE f.last_seen >= ?
                 AND NOT EXISTS (
                     SELECT 1 FROM agg_hourly a
                     WHERE a.hour_start = (f.last_seen / 3600) * 3600
                       AND a.app_id = f.app_id
                       AND a.endpoint_id = f.endpoint_id
                 )
               GROUP BY (f.last_seen / 3600) * 3600, f.app_id, f.endpoint_id""",
            (cutoff,),
        )
        conn.commit()
        count = conn.total_changes
        if count:
            logger.info("Filled %d missing aggregate rows", count)

    # ── Retention / pruning ────────────────────────────────────────

    def prune(self, retention_days: int = 30) -> dict[str, int]:
        """Delete data older than retention_days.

        Returns dict of {table: deleted_rows}.
        Returns zero counts when nothing was pruned.
        """
        cutoff = int(__import__("time").time()) - retention_days * 86400
        conn = self._get_conn()

        results: dict[str, int] = {}

        # Prune flow rows (and any orphaned app/endpoint rows)
        cursor = conn.execute("DELETE FROM flow WHERE last_seen < ?", (cutoff,))
        results["flow"] = cursor.rowcount

        cursor = conn.execute("DELETE FROM agg_hourly WHERE hour_start < ?", (cutoff,))
        results["agg_hourly"] = cursor.rowcount

        # Clean orphaned app rows (apps with no flows and no agg_hourly entries)
        cursor = conn.execute(
            """DELETE FROM app WHERE id NOT IN (
                   SELECT DISTINCT app_id FROM flow
                   UNION SELECT DISTINCT app_id FROM agg_hourly WHERE app_id IS NOT NULL
               )"""
        )
        results["app_orphans"] = cursor.rowcount

        # Clean orphaned endpoint rows
        cursor = conn.execute(
            """DELETE FROM endpoint WHERE id NOT IN (
                   SELECT DISTINCT endpoint_id FROM flow
                   UNION SELECT DISTINCT endpoint_id FROM agg_hourly WHERE endpoint_id IS NOT NULL
               )"""
        )
        results["endpoint_orphans"] = cursor.rowcount

        conn.commit()
        total = sum(results.values())
        if total:
            logger.info("Pruned %d rows (retention: %d days)", total, retention_days)
        else:
            logger.debug("Prune: nothing to delete")

        return results

    # ── Query helpers for CLI / API ─────────────────────────────────

    def get_today_summary(self) -> dict:
        """Return a plain summary dict from today's agg_hourly data.

        Returns keys: app_count, domain_count, total_bytes, bg_bytes.
        """
        conn = self._get_conn()
        today_start = self._today_start()

        # Sum aggregates for today
        row = conn.execute(
            """SELECT COUNT(DISTINCT app_id),
                      COUNT(DISTINCT endpoint_id),
                      COALESCE(SUM(bytes_sent + bytes_recv), 0),
                      COALESCE(SUM(bg_bytes), 0)
               FROM agg_hourly WHERE hour_start >= ?""",
            (today_start,),
        ).fetchone()

        return {
            "app_count": row[0] or 0,
            "domain_count": row[1] or 0,
            "total_bytes": row[2] or 0,
            "bg_bytes": row[3] or 0,
        }

    def get_top_apps(self, limit: int = 10, since: int | None = None) -> list[dict]:
        """Top apps by total bytes (sent + recv)."""
        conn = self._get_conn()
        since = since or self._today_start()

        rows = conn.execute(
            """SELECT a.id, a.name, a.exe_path,
                      SUM(ag.bytes_sent + ag.bytes_recv) AS total_bytes,
                      SUM(ag.bg_bytes) AS bg_bytes,
                      COUNT(DISTINCT ag.endpoint_id) AS service_count
               FROM agg_hourly ag
               JOIN app a ON ag.app_id = a.id
               WHERE ag.hour_start >= ?
               GROUP BY a.id
               ORDER BY total_bytes DESC
               LIMIT ?""",
            (since, limit),
        ).fetchall()

        return [
            {
                "id": r[0],
                "name": r[1],
                "exe_path": r[2],
                "total_bytes": r[3] or 0,
                "bg_bytes": r[4] or 0,
                "service_count": r[5] or 0,
            }
            for r in rows
        ]

    def get_top_domains(self, limit: int = 10, since: int | None = None) -> list[dict]:
        """Top endpoints/domains by total bytes."""
        conn = self._get_conn()
        since = since or self._today_start()

        rows = conn.execute(
            """SELECT e.id, e.ip, e.domain, e.name_source,
                      SUM(ag.bytes_sent + ag.bytes_recv) AS total_bytes,
                      SUM(ag.conn_count) AS conn_count,
                      COUNT(DISTINCT ag.app_id) AS app_count
               FROM agg_hourly ag
               JOIN endpoint e ON ag.endpoint_id = e.id
               WHERE ag.hour_start >= ?
               GROUP BY e.id
               ORDER BY total_bytes DESC
               LIMIT ?""",
            (since, limit),
        ).fetchall()

        return [
            {
                "id": r[0],
                "ip": r[1],
                "domain": r[2],
                "name_source": r[3],
                "total_bytes": r[4] or 0,
                "conn_count": r[5] or 0,
                "app_count": r[6] or 0,
            }
            for r in rows
        ]

    def get_flag_count(self) -> int:
        """Number of undismissed insights."""
        row = self._get_conn().execute(
            "SELECT COUNT(*) FROM insight WHERE dismissed = 0"
        ).fetchone()
        return row[0] if row else 0

    @staticmethod
    def _today_start() -> int:
        """Return epoch seconds at the start of today (UTC)."""
        import time

        now = time.time()
        return int(now - now % 86400)

    # ── Low-level access (for collector / insight modules) ──────────

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Yield a connection usable for reads or writes.

        Caller must commit/rollback; nested calls reuse the same connection.
        """
        conn = self._get_conn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self._get_conn().execute(sql, params)

    def executemany(self, sql: str, seq: list[tuple]) -> sqlite3.Cursor:
        return self._get_conn().executemany(sql, seq)

    # ── Internals ───────────────────────────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = self._open()
        return self._conn

    def _open(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self._path), timeout=10.0, check_same_thread=False
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def _ensure_schema_version(self) -> None:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'version'"
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO schema_meta(key, value) VALUES ('version', ?)",
                (str(SCHEMA_VERSION),),
            )
            conn.commit()
            logger.info("Schema initialized at version %d", SCHEMA_VERSION)
        else:
            existing = int(row[0])
            if existing != SCHEMA_VERSION:
                logger.warning(
                    "Schema version mismatch: DB has %d, code expects %d. "
                    "Migration not implemented yet.",
                    existing,
                    SCHEMA_VERSION,
                )
