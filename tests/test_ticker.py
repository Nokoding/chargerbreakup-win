from __future__ import annotations

import threading
import time

from chargerwin.ticker import EscalationTicker


def test_ticker_fires_repeatedly_and_stops():
    ticks = []
    ticker = EscalationTicker(lambda: ticks.append(1), interval=0.01)
    ticker.start()
    time.sleep(0.08)
    ticker.stop()
    fired = len(ticks)
    assert fired >= 2
    time.sleep(0.05)
    assert len(ticks) == fired  # stopped means stopped


def test_stop_is_immediate_not_after_a_whole_interval():
    """wait() rather than sleep(), so quitting the app is not held up by a
    minute-long timer."""
    ticker = EscalationTicker(lambda: None, interval=30)
    ticker.start()
    started = time.monotonic()
    ticker.stop()
    ticker._thread.join(timeout=2)
    assert not ticker._thread.is_alive()
    assert time.monotonic() - started < 2


def test_a_failing_tick_does_not_end_the_ticker():
    """One bad tick must not silence escalations for the rest of the session."""
    calls = []

    def boom():
        calls.append(1)
        raise RuntimeError("bad tick")

    ticker = EscalationTicker(boom, interval=0.01)
    ticker.start()
    time.sleep(0.06)
    ticker.stop()
    assert len(calls) >= 2


def test_start_is_idempotent():
    ticker = EscalationTicker(lambda: None, interval=10)
    ticker.start()
    first = ticker._thread
    ticker.start()
    assert ticker._thread is first
    ticker.stop()


def test_ticker_thread_is_a_daemon():
    """A stuck ticker must not keep the process alive after the tray quits."""
    ticker = EscalationTicker(lambda: None, interval=10)
    ticker.start()
    assert ticker._thread.daemon
    ticker.stop()
