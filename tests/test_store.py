"""Tests for store/database.py — aggregation, pruning, query helpers.

Uses an in-memory SQLite database for deterministic testing.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from vexilla.store.database import Database, CREATE_TABLES


@pytest.fixture
def db(tmp_path: Path) -> Database:
    """Create a fresh database in a temp directory."""
    db_path = tmp_path / "test.db"
    db = Database(db_path)
    db.initialize()
    return db


def _insert_test_data(db: Database) -> None:
    """Insert sample app, endpoint, and flow rows."""
    now = int(time.time())
    yesterday = now - 86400
    old = now - 86400 * 60  # 60 days ago (beyond default 30-day retention)

    with db.connect() as conn:
        # App row
        conn.execute(
            "INSERT INTO app (name, exe_path, first_seen, last_seen) VALUES (?, ?, ?, ?)",
            ("test-app", "/usr/bin/test-app", old, now),
        )
        # Endpoint rows
        conn.execute(
            "INSERT INTO endpoint (ip, domain, name_source, first_seen, last_seen) VALUES (?, ?, ?, ?, ?)",
            ("93.184.216.34", "example.com", "dns", old, now),
        )
        conn.execute(
            "INSERT INTO endpoint (ip, domain, name_source, first_seen, last_seen) VALUES (?, ?, ?, ?, ?)",
            ("142.250.80.46", "google.com", "dns", old, now),
        )

        # Recent flow (within retention)
        conn.execute(
            """INSERT INTO flow (app_id, endpoint_id, protocol, remote_port,
                bytes_sent, bytes_recv, is_background, started_at, last_seen)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (1, 1, "tcp", 443, 5000, 10000, 0, yesterday, now),
        )
        # Old flow (beyond retention)
        conn.execute(
            """INSERT INTO flow (app_id, endpoint_id, protocol, remote_port,
                bytes_sent, bytes_recv, is_background, started_at, last_seen)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (1, 2, "tcp", 443, 1000, 2000, 1, old, old),
        )


class TestPrune:
    def test_prune_removes_old_data(self, db: Database):
        _insert_test_data(db)
        assert db.execute("SELECT COUNT(*) FROM flow").fetchone()[0] == 2

        # Prune with 30-day retention
        result = db.prune(retention_days=30)

        # Only the old flow (60 days ago) should be pruned
        remaining = db.execute("SELECT COUNT(*) FROM flow").fetchone()[0]
        assert remaining == 1, f"Expected 1 flow remaining, got {remaining}"
        assert result["flow"] == 1

    def test_prune_nothing_to_delete(self, db: Database):
        _insert_test_data(db)
        result = db.prune(retention_days=90)  # 90-day window covers all data
        assert result["flow"] == 0
        assert result["agg_hourly"] == 0

    def test_prune_orphans_removed(self, db: Database):
        """Orphaned app/endpoint rows are cleaned up."""
        _insert_test_data(db)
        db.prune(retention_days=30)

        # The old endpoint (google.com, only in old flow) should be orphaned
        # The old app row might also be orphaned
        remaining_endpoints = db.execute(
            "SELECT COUNT(*) FROM endpoint"
        ).fetchone()[0]
        # example.com should remain (still referenced), google.com should be gone
        assert remaining_endpoints == 1


class TestAggregation:
    def test_fill_missing_aggregates(self, db: Database):
        _insert_test_data(db)
        # Before aggregation, agg_hourly should be empty
        assert db.execute("SELECT COUNT(*) FROM agg_hourly").fetchone()[0] == 0

        db.fill_missing_aggregates()

        # After aggregation, there should be agg_hourly rows
        count = db.execute("SELECT COUNT(*) FROM agg_hourly").fetchone()[0]
        assert count > 0, "Expected aggregate rows to be created"

    def test_aggregate_values_match(self, db: Database):
        _insert_test_data(db)
        db.fill_missing_aggregates()

        # Check the recent flow (5000 + 10000 = 15000 bytes)
        row = db.execute(
            """SELECT bytes_sent, bytes_recv, conn_count
               FROM agg_hourly
               WHERE app_id = 1 AND endpoint_id = 1"""
        ).fetchone()
        assert row is not None, "Expected agg row for recent flow"
        assert row[0] == 5000  # bytes_sent
        assert row[1] == 10000  # bytes_recv

    def test_idempotent(self, db: Database):
        """fill_missing_aggregates can be called multiple times safely."""
        _insert_test_data(db)
        db.fill_missing_aggregates()
        count_before = db.execute(
            "SELECT COUNT(*) FROM agg_hourly"
        ).fetchone()[0]

        db.fill_missing_aggregates()
        count_after = db.execute(
            "SELECT COUNT(*) FROM agg_hourly"
        ).fetchone()[0]
        assert count_after == count_before


class TestQueryHelpers:
    def test_get_today_summary_empty(self, db: Database):
        """No data → all zeros."""
        summary = db.get_today_summary()
        assert summary["app_count"] == 0
        assert summary["domain_count"] == 0
        assert summary["total_bytes"] == 0

    def test_get_today_summary_with_data(self, db: Database):
        _insert_test_data(db)
        db.fill_missing_aggregates()

        summary = db.get_today_summary()
        # We should have at least the recent flow's data
        assert summary["app_count"] >= 1
        assert summary["total_bytes"] >= 15000  # 5000 sent + 10000 recv

    def test_get_top_apps(self, db: Database):
        _insert_test_data(db)
        db.fill_missing_aggregates()

        top = db.get_top_apps(limit=5)
        assert len(top) >= 1
        assert top[0]["name"] == "test-app"

    def test_get_top_domains(self, db: Database):
        _insert_test_data(db)
        db.fill_missing_aggregates()

        top = db.get_top_domains(limit=5)
        assert len(top) >= 1
