"""Scheduled insight engine runner — runs in a background thread."""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from vexilla.insight.engine import InsightEngine
from vexilla.store import Database

logger = logging.getLogger(__name__)


class InsightScheduler:
    """Runs the insight engine on a configurable interval.

    Typically started alongside the collector daemon.
    """

    def __init__(
        self,
        db: Database,
        kb_path: Optional[str] = None,
        insight_interval: float = 60.0,
    ) -> None:
        self._db = db
        self._insight_interval = insight_interval
        self._kb_path = kb_path
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._engine: Optional[InsightEngine] = None

    def start(self) -> None:
        """Start the insight engine loop in a background thread."""
        if self._thread is not None and self._thread.is_alive():
            logger.warning("Insight scheduler already running")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="vexilla-insight",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "Insight scheduler started (every %.0fs)", self._insight_interval
        )

    def stop(self, timeout: float = 5.0) -> None:
        """Signal the scheduler to stop and wait for it."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            logger.info("Insight scheduler stopped")

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run_loop(self) -> None:
        """Main insight engine loop."""
        from pathlib import Path

        from vexilla.kb.reader import KbReader

        kb_path = Path(self._kb_path) if self._kb_path else None
        kb = KbReader(kb_path)

        self._engine = InsightEngine(
            db=self._db,
            kb=kb,
            insight_interval=self._insight_interval,
        )

        # Run once immediately
        try:
            self._engine.run()
        except Exception:
            logger.exception("Initial insight run failed")

        logger.info("Insight loop started")

        while not self._stop_event.is_set():
            self._stop_event.wait(self._insight_interval)
            if self._stop_event.is_set():
                break

            try:
                self._engine.run()
                logger.debug("Insight engine cycle complete")
            except Exception:
                logger.exception("Insight engine cycle failed")

        logger.info("Insight loop ended")
