"""Heuristic functions — one per insight kind.

Each is a pure function with signature:
    (heuristic_params) -> Insight | None

Returns None when the heuristic does not fire (normal behavior).
"""

from __future__ import annotations

import statistics
import time
from typing import Any, Optional

from vexilla.insight.models import Insight

# ── Constants ──────────────────────────────────────────────────────

NEW_DOMAIN_DAYS = 14  # days without seeing a domain before it's "new"
SPIKE_FACTOR = 5.0  # multiplier over median hourly background
SPIKE_FLOOR_MB = 20.0
BEACON_MIN_COUNT = 6
BEACON_CV_THRESHOLD = 0.25  # coefficient of variation
HEAVY_BG_MB = 100.0
UNNAMED_THRESHOLD_MB = 50.0

# ── Helpers ────────────────────────────────────────────────────────


def _now() -> int:
    return int(time.time())


def _mb(bytes_val: int) -> float:
    return round(bytes_val / 1048576, 1)


# ═══════════════════════════════════════════════════════════════════
# Heuristics
# ═══════════════════════════════════════════════════════════════════


def new_domain(
    app_name: str,
    domain: str,
    app_id: int,
    endpoint_id: int,
    db,
    kb_info: Any,
) -> Optional[Insight]:
    """An app contacts a domain not seen for this app in new_domain_days."""
    cutoff = _now() - NEW_DOMAIN_DAYS * 86400

    # Check if this app has any recent flow to this endpoint
    row = db.execute(
        """SELECT COUNT(*) FROM flow
           WHERE app_id = ? AND endpoint_id = ? AND last_seen >= ?""",
        (app_id, endpoint_id, cutoff),
    ).fetchone()

    has_prior = row is not None and row[0] > 0
    if has_prior:
        return None

    owner = kb_info.owner if kb_info.kb_hit else ""
    purpose = kb_info.purpose_plain or "a service"
    owner_clause = f" ({owner})" if owner else ""

    evidence = {
        "app": app_name,
        "domain": domain,
        "new_domain_days": NEW_DOMAIN_DAYS,
    }

    return Insight(
        kind="new_domain",
        severity="notice",
        app_id=app_id,
        endpoint_id=endpoint_id,
        title=f"New service contacted — {domain}",
        body=(
            f"{app_name} contacted a new service today: {domain}"
            f"{owner_clause}. It is used for {purpose}."
        ),
        suggestion=kb_info.suggestion,
        evidence=evidence,
        created_at=_now(),
    )


def tracker(
    app_name: str,
    domain: str,
    app_id: int,
    endpoint_id: int,
    kb_info: Any,
    count: int = 1,
    bg_clause: str = "",
) -> Optional[Insight]:
    """Endpoint category is advertising or tracker_analytics."""
    if kb_info.category not in ("advertising", "tracker_analytics"):
        return None

    owner = kb_info.owner or "an unknown company"
    evidence = {
        "app": app_name,
        "domain": domain,
        "category": kb_info.category,
        "count": count,
    }

    return Insight(
        kind="tracker",
        severity="notice",
        app_id=app_id,
        endpoint_id=endpoint_id,
        title=f"Tracker contacted — {domain}",
        body=(
            f"{app_name} talked to {domain}, a {kb_info.category_human} run by"
            f" {owner}, {count} times{bg_clause}."
        ),
        suggestion=kb_info.suggestion
        or "You can reduce this with a tracker-blocking browser extension or DNS blocklist.",
        evidence=evidence,
        created_at=_now(),
    )


def background_spike(
    app_name: str,
    app_id: int,
    hourly_bg_bytes: int,
    db,
) -> Optional[Insight]:
    """App's background bytes in last hour >> 7-day hourly background median."""
    bg_mb = _mb(hourly_bg_bytes)
    if bg_mb < SPIKE_FLOOR_MB:
        return None

    now = _now()
    seven_days_ago = now - 7 * 86400

    # Get hourly background medians for the last 7 days
    rows = db.execute(
        """SELECT bg_bytes FROM agg_hourly
           WHERE app_id = ? AND hour_start >= ?
           ORDER BY hour_start""",
        (app_id, seven_days_ago),
    ).fetchall()

    values = [r[0] for r in rows if r[0] > 0]
    if len(values) < 3:
        return None  # not enough history

    median = statistics.median(values)
    if median <= 0:
        return None

    factor = hourly_bg_bytes / median
    if factor < SPIKE_FACTOR:
        return None

    evidence = {
        "app": app_name,
        "hourly_bg_mb": bg_mb,
        "median_bg": _mb(int(median)),
        "factor": round(factor, 1),
        "spike_factor_threshold": SPIKE_FACTOR,
    }

    return Insight(
        kind="background_spike",
        severity="warning",
        app_id=app_id,
        endpoint_id=None,
        title=f"Background data spike — {app_name}",
        body=(
            f"{app_name} used {bg_mb} MB in the background in the last hour"
            f" — about {round(factor)}× its usual."
        ),
        suggestion=f"If you do not need {app_name} running in the background,"
        f" you can quit it or disable its auto-start to save data.",
        evidence=evidence,
        created_at=_now(),
    )


def beaconing(
    app_name: str,
    domain: str,
    app_id: int,
    endpoint_id: int,
    time_gaps: list[float],
) -> Optional[Insight]:
    """Regular periodic connections to the same endpoint."""
    if len(time_gaps) < BEACON_MIN_COUNT:
        return None

    # Coefficient of variation = stddev / mean
    if len(time_gaps) < 2:
        return None

    mean = statistics.mean(time_gaps)
    if mean <= 0:
        return None

    cv = statistics.stdev(time_gaps) / mean
    if cv >= BEACON_CV_THRESHOLD:
        return None

    evidence = {
        "app": app_name,
        "domain": domain,
        "num_connections": len(time_gaps) + 1,
        "interval_seconds": round(mean, 1),
        "cv": round(cv, 3),
        "cv_threshold": BEACON_CV_THRESHOLD,
    }

    return Insight(
        kind="beaconing",
        severity="notice",
        app_id=app_id,
        endpoint_id=endpoint_id,
        title=f"Regular pattern detected — {domain}",
        body=(
            f"{app_name} contacted {domain} on a regular schedule "
            f"(every {round(mean)} seconds on average). This can indicate "
            f"beaconing or periodic check-ins."
        ),
        suggestion="If you do not recognise this service, you can investigate"
        f" what {app_name} uses it for in the app's settings.",
        evidence=evidence,
        created_at=_now(),
    )


def heavy_background_app(
    app_name: str,
    app_id: int,
    today_bg_bytes: int,
) -> Optional[Insight]:
    """App used > heavy_bg_mb while classified background over the day."""
    bg_mb = _mb(today_bg_bytes)
    if bg_mb < HEAVY_BG_MB:
        return None

    evidence = {
        "app": app_name,
        "today_bg_mb": bg_mb,
        "threshold_mb": HEAVY_BG_MB,
    }

    return Insight(
        kind="heavy_background_app",
        severity="warning",
        app_id=app_id,
        endpoint_id=None,
        title=f"Heavy background usage — {app_name}",
        body=(
            f"{app_name} used {bg_mb} MB in the background today."
            f" If you do not need it running, quitting it will save data."
        ),
        suggestion=f"Check {app_name}'s settings for options to reduce"
        f" background activity.",
        evidence=evidence,
        created_at=_now(),
    )


def unnamed_endpoint_volume(
    app_name: str,
    ip: str,
    endpoint_id: int,
    total_bytes: int,
) -> Optional[Insight]:
    """Significant data to an endpoint with no resolvable name."""
    mb = _mb(total_bytes)
    if mb < UNNAMED_THRESHOLD_MB:
        return None

    evidence = {
        "app": app_name,
        "ip": ip,
        "total_mb": mb,
        "threshold_mb": UNNAMED_THRESHOLD_MB,
    }

    return Insight(
        kind="unnamed_endpoint_volume",
        severity="info",
        app_id=None,
        endpoint_id=endpoint_id,
        title=f"Unknown service with notable data — {ip}",
        body=(
            f"{app_name} transferred {mb} MB to {ip}, which could not be"
            f" named. This is often caused by apps using encrypted DNS."
        ),
        suggestion=None,
        evidence=evidence,
        created_at=_now(),
    )
