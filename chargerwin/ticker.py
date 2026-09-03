"""Escalation timer.

Escalations are the one thing not driven by a Windows message: nothing
broadcasts "you have now been unplugged for thirty minutes". So a thread
wakes periodically and asks the state whether a threshold has been crossed.

This is not polling the power state, which CLAUDE.md rules out; it is
polling the clock, which is the only way to notice elapsed time. The power
state itself is still purely event driven.

The interval only bounds how late an escalation can be. State.due_escalation
fires every crossed threshold at once, so a laptop asleep through both the
30 and 60 minute marks says one line on wake, not two.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

log = logging.getLogger(__name__)

DEFAULT_INTERVAL_SECONDS = 60.0


class EscalationTicker:
    def __init__(self, on_tick: Callable[[], None], interval: float = DEFAULT_INTERVAL_SECONDS):
        self.on_tick = on_tick
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="chargerwin-ticker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self) -> None:
        # wait() rather than sleep() so stop() takes effect immediately
        # instead of after up to a whole interval.
        while not self._stop.wait(self.interval):
            try:
                self.on_tick()
            except Exception:
                # One bad tick must not end escalations for the session.
                log.warning("escalation tick failed", exc_info=True)
