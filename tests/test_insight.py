"""Tests for the insight engine — heuristics, templates, and KB reader."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from vexilla.insight.heuristics import (
    background_spike,
    beaconing,
    heavy_background_app,
    new_domain,
    tracker,
    unnamed_endpoint_volume,
    NEW_DOMAIN_DAYS,
    SPIKE_FACTOR,
    SPIKE_FLOOR_MB,
    BEACON_MIN_COUNT,
    BEACON_CV_THRESHOLD,
    HEAVY_BG_MB,
    UNNAMED_THRESHOLD_MB,
)
from vexilla.insight.models import Insight
from vexilla.insight.templates import daily_summary_text, empty_summary_text
from vexilla.kb.reader import KbReader, DomainInfo


# ── Helper: fake KB info ────────────────────────────────────────────


def _kb_info(
    domain: str = "example.com",
    category: str = "cdn",
    kbit: bool = True,
    owner: str = "Example Corp",
) -> DomainInfo:
    return DomainInfo(
        domain=domain,
        owner=owner,
        category=category,
        category_human=category,
        purpose_plain="serves example content",
        privacy_note=None,
        suggestion="No action needed.",
        confidence="high",
        kb_hit=kbit,
    )


def _unknown_kb(domain: str = "unknown.example") -> DomainInfo:
    return DomainInfo(
        domain=domain,
        owner=None,
        category="unrecognized",
        category_human="unrecognized service",
        purpose_plain=None,
        privacy_note=None,
        suggestion=None,
        confidence="low",
        kb_hit=False,
    )


# ═══════════════════════════════════════════════════════════════════
# New domain heuristic
# ═══════════════════════════════════════════════════════════════════


def test_new_domain_fires():
    """First-seen domain for an app."""
    db = MagicMock()
    db.execute.return_value.fetchone.return_value = (0,)
    result = new_domain("firefox", "new-service.example", 1, 1, db, _unknown_kb())
    assert result is not None
    assert result.kind == "new_domain"
    assert result.severity == "notice"
    assert "firefox" in result.body
    assert "new-service.example" in result.title


def test_new_domain_does_not_fire_for_familiar():
    """Domain seen before in the last N days."""
    db = MagicMock()
    db.execute.return_value.fetchone.return_value = (5,)
    result = new_domain("firefox", "example.com", 1, 1, db, _kb_info())
    assert result is None


# ═══════════════════════════════════════════════════════════════════
# Tracker heuristic
# ═══════════════════════════════════════════════════════════════════


def test_tracker_fires():
    """advertising category triggers tracker insight."""
    result = tracker("firefox", "doubleclick.net", 1, 2, _kb_info(category="advertising"), 5)
    assert result is not None
    assert result.kind == "tracker"
    assert result.suggestion is not None


def test_tracker_fires_for_analytics():
    """tracker_analytics category triggers tracker insight."""
    result = tracker("firefox", "google-analytics.com", 1, 2, _kb_info(category="tracker_analytics"), 3)
    assert result is not None


def test_tracker_does_not_fire_for_cdn():
    """CDN category does not trigger tracker."""
    result = tracker("firefox", "cdn.example", 1, 2, _kb_info(category="cdn"), 1)
    assert result is None


# ═══════════════════════════════════════════════════════════════════
# Background spike heuristic
# ═══════════════════════════════════════════════════════════════════


def test_background_spike_fires():
    """High background usage vs median."""
    db = MagicMock()
    # Return high bg values so the spike fires
    db.execute.return_value.fetchall.return_value = [(10485760,)] * 20  # 10 MB each
    bg = int(SPIKE_FLOOR_MB * 1048576 * SPIKE_FACTOR * 2)  # well above threshold
    result = background_spike("slack", 1, bg, db)
    assert result is not None
    assert result.kind == "background_spike"
    assert result.severity == "warning"


def test_background_spike_below_floor():
    """Below the minimum MB threshold does not fire."""
    db = MagicMock()
    db.execute.return_value.fetchall.return_value = [(100,)]
    result = background_spike("slack", 1, 100, db)
    assert result is None


# ═══════════════════════════════════════════════════════════════════
# Beaconing heuristic
# ═══════════════════════════════════════════════════════════════════


def test_beaconing_fires():
    """Regular connections at consistent intervals."""
    gaps = [60.0] * 10  # 10 gaps of 60 seconds = CV of 0
    result = beaconing("firefox", "check.example", 1, 1, gaps)
    assert result is not None
    assert result.kind == "beaconing"


def test_beaconing_needs_minimum():
    """Fewer than minimum connections does not fire."""
    gaps = [60.0] * 2
    result = beaconing("firefox", "check.example", 1, 1, gaps)
    assert result is None


def test_beaconing_high_variation():
    """Irregular intervals do not fire."""
    import random

    gaps = [random.uniform(10, 300) for _ in range(10)]
    result = beaconing("firefox", "check.example", 1, 1, gaps)
    assert result is None


# ═══════════════════════════════════════════════════════════════════
# Heavy background app
# ═══════════════════════════════════════════════════════════════════


def test_heavy_background_fires():
    bg = int(HEAVY_BG_MB * 1048576 * 2)  # 200 MB
    result = heavy_background_app("slack", 1, bg)
    assert result is not None
    assert result.severity == "warning"


def test_heavy_background_below():
    bg = int(HEAVY_BG_MB * 1048576 / 2)  # 50 MB
    result = heavy_background_app("slack", 1, bg)
    assert result is None


# ═══════════════════════════════════════════════════════════════════
# Unnamed endpoint volume
# ═══════════════════════════════════════════════════════════════════


def test_unnamed_fires():
    bytes_val = int(UNNAMED_THRESHOLD_MB * 1048576 * 2)  # 100 MB
    result = unnamed_endpoint_volume("spotify", "1.2.3.4", 1, bytes_val)
    assert result is not None
    assert result.kind == "unnamed_endpoint_volume"


def test_unnamed_below():
    bytes_val = 1024 * 1024  # 1 MB
    result = unnamed_endpoint_volume("spotify", "1.2.3.4", 1, bytes_val)
    assert result is None


# ═══════════════════════════════════════════════════════════════════
# Templates
# ═══════════════════════════════════════════════════════════════════


def test_daily_summary_empty():
    text = daily_summary_text(0, 0, 0, 0, None, 0, 0, 0)
    assert "did not detect" in text


def test_daily_summary_normal():
    text = daily_summary_text(
        app_count=3,
        domain_count=15,
        total_mb=420.5,
        bg_mb=300.2,
        top_app_name="firefox",
        top_app_mb=200.0,
        tracker_count=4,
        flag_count=2,
    )
    assert "3 apps" in text or "3" in text
    assert "firefox" in text
    assert "tracking" in text or "services" in text
    assert "flagged" in text


def test_empty_summary():
    text = empty_summary_text()
    assert "watching" in text


# ═══════════════════════════════════════════════════════════════════
# KB reader
# ═══════════════════════════════════════════════════════════════════


def test_kb_reader_unavailable():
    """Without kb.db, all lookups return unrecognized."""
    kb = KbReader()
    assert not kb.is_available
    info = kb.lookup("example.com")
    assert info.category == "unrecognized"
    assert not info.kb_hit
    assert info.owner is None
