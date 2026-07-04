"""Collector daemon — orchestrates the poll loop.

Runs the FlowWriter poll cycle on a configurable interval
in a background thread.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from vexilla.store import Database

logger = logging.getLogger(__name__)


class CollectorDaemon:
    """Background collector that polls /proc/net, conntrack, and DNS.

    Also handles hourly aggregation backfill and daily pruning.
    Designed to run as a background thread within vexilla serve.
    """

    def __init__(
        self,
        db: Database,
        poll_interval: float = 2.0,
        retention_days: int = 30,
    ) -> None:
        self._db = db
        self._poll_interval = poll_interval
        self._retention_days = retention_days
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._writer: Optional["FlowWriter"] = None
        self._last_prune_time: float = 0.0
        self._prune_interval: float = 86400.0  # once per day

    def start(self) -> None:
        """Start the collector loop in a background thread."""
        if self._thread is not None and self._thread.is_alive():
            logger.warning("Collector already running")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="vexilla-collector",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "Collector started (poll every %.1fs)", self._poll_interval
        )

    def stop(self, timeout: float = 5.0) -> None:
        """Signal the collector to stop and wait for it."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            logger.info("Collector stopped")

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ── Stats / health ────────────────────────────────────────────

    @property
    def poll_count(self) -> int:
        return self._poll_count

    # ── Internals ─────────────────────────────────────────────────

    def _run_loop(self) -> None:
        """Main poll loop."""
        # Lazy import to avoid circular dependency
        from vexilla.collector.writer import FlowWriter

        self._writer = FlowWriter(self._db)
        self._poll_count = 0

        # Backfill any aggregates that were missed during downtime
        try:
            self._db.fill_missing_aggregates()
        except Exception:
            logger.exception("Aggregation backfill failed")

        logger.info("Collector loop started")

        while not self._stop_event.is_set():
            try:
                self._writer.poll()
                self._poll_count += 1

                # Periodic maintenance
                if self._poll_count % 30 == 0:
                    pass  # just a heartbeat marker
                    logger.debug(
                        "Collector: %d polls completed", self._poll_count
                    )

                # Daily prune check
                now = time.monotonic()
                if now - self._last_prune_time > self._prune_interval:
                    try:
                        result = self._db.prune(self._retention_days)
                        self._last_prune_time = now
                        if any(v > 0 for v in result.values()):
                            logger.info("Prune: %s", result)
                    except Exception:
                        logger.exception("Prune cycle failed")
            except Exception:
                logger.exception("Collector poll cycle failed")

            # Wait for the poll interval or stop signal
            self._stop_event.wait(self._poll_interval)

        logger.info("Collector loop ended (%d polls)", self._poll_count)
