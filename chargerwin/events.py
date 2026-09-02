"""Events produced by the state machine.

Each event carries only what cannot be derived from the state afterwards.
Everything else (counts, streaks) is read from the State when rendering.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Disconnected:
    """The AC adapter was just unplugged."""


@dataclass(frozen=True)
class Reconnected:
    """The AC adapter was just plugged back in."""

    absence_seconds: float


@dataclass(frozen=True)
class Escalated:
    """Still unplugged after one of the escalation thresholds."""

    minutes: int
    absence_seconds: float


Event = Disconnected | Reconnected | Escalated
