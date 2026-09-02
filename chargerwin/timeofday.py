"""Time-of-day windows. Late night 22:00-04:59, morning 05:00-11:59,
afternoon 12:00-16:59, evening 17:00-21:59."""

from __future__ import annotations

from datetime import datetime


def time_of_day(now: datetime) -> str:
    h = now.hour
    if h >= 22 or h < 5:
        return "late_night"
    if h < 12:
        return "morning"
    if h < 17:
        return "afternoon"
    return "evening"
