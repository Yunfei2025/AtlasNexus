"""Simple trading-hours-aware scheduler for periodic refresh & intraday runs.

Uses :mod:`threading` to avoid adding a heavy dependency like APScheduler.
The scheduler runs a loop that:
  1. Checks whether the current time falls within a trading window.
  2. If yes, executes the refresh (or intraday) pipeline.
  3. Sleeps for ``interval_seconds`` before repeating.

Usage from CLI::

    python main.py scheduler --interval 300 --start-hour 9 --end-hour 16
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime
from pathlib import Path
from typing import Callable

from engine.context import build_run_config, RunConfig
from settings.general import TradingHoursConfig

logger = logging.getLogger(__name__)


class TradingHoursScheduler:
    """Run a callable on a fixed interval during trading hours."""

    def __init__(
        self,
        *,
        pipeline_fn: Callable[[RunConfig], object],
        project_root: Path,
        interval_seconds: int = 300,
        start_hour: int = TradingHoursConfig.START_HOUR,
        end_hour: int = TradingHoursConfig.END_HOUR,
        start_minute: int = 0,
        end_minute: int = 30,
        weekdays_only: bool = True,
    ) -> None:
        self.pipeline_fn = pipeline_fn
        self.project_root = project_root
        self.interval = interval_seconds
        self.start_hour = start_hour
        self.start_minute = start_minute
        self.end_hour = end_hour
        self.end_minute = end_minute
        self.weekdays_only = weekdays_only

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._run_count = 0

    # ── public API ────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the scheduler loop in a background thread."""
        if self._thread and self._thread.is_alive():
            logger.warning("Scheduler already running")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="scheduler")
        self._thread.start()
        logger.info(
            "Scheduler started: interval=%ds  window=%02d:%02d–%02d:%02d",
            self.interval, self.start_hour, self.start_minute,
            self.end_hour, self.end_minute,
        )

    def stop(self) -> None:
        """Signal the loop to stop and wait for the thread to finish."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=self.interval + 5)
        logger.info("Scheduler stopped after %d runs", self._run_count)

    def run_blocking(self) -> None:
        """Run the scheduler loop in the current thread (blocks until stopped)."""
        logger.info(
            "Scheduler running (blocking): interval=%ds  window=%02d:%02d–%02d:%02d",
            self.interval, self.start_hour, self.start_minute,
            self.end_hour, self.end_minute,
        )
        try:
            self._loop()
        except KeyboardInterrupt:
            logger.info("Scheduler interrupted by user")
        finally:
            logger.info("Scheduler exited after %d runs", self._run_count)

    # ── internals ─────────────────────────────────────────────────────

    def _is_trading_time(self, now: datetime | None = None) -> bool:
        now = now or datetime.now()
        if self.weekdays_only and now.weekday() >= 5:  # Sat=5, Sun=6
            return False
        current_minutes = now.hour * 60 + now.minute
        start_minutes = self.start_hour * 60 + self.start_minute
        end_minutes = self.end_hour * 60 + self.end_minute
        return start_minutes <= current_minutes < end_minutes

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            if self._is_trading_time():
                self._run_once()
            else:
                logger.debug("Outside trading hours — sleeping %ds", self.interval)
            self._stop_event.wait(timeout=self.interval)

    def _run_once(self) -> None:
        self._run_count += 1
        cfg = build_run_config(
            project_root=self.project_root,
            mode="refresh",
            asof=date.today(),
        )
        logger.info("Scheduler tick #%d — run_id=%s", self._run_count, cfg.run_id)
        try:
            self.pipeline_fn(cfg)
        except Exception:
            logger.exception("Pipeline execution failed on tick #%d", self._run_count)
