"""Template variables: `{{name}}` placeholders in pack lines.

Rendering happens at playback with real values. The validator renders with
WORST_CASE values (the widest string each variable can plausibly produce)
to enforce the 160-character cap on rendered text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

VARIABLE_NAMES: tuple[str, ...] = (
    "battery_percent",
    "absence_seconds",
    "absence_human",
    "today_count",
    "weekly_count",
    "total_count",
    "longest_absence_seconds",
    "average_away_seconds",
    "local_time",
    "toggle_count",
)

# Widest realistic rendering of each variable, used by the validator.
WORST_CASE: dict[str, str] = {
    "battery_percent": "100",
    "absence_seconds": "999999",
    "absence_human": "23 hours 59 minutes",
    "today_count": "99",
    "weekly_count": "999",
    "total_count": "99999",
    "longest_absence_seconds": "999999",
    "average_away_seconds": "999999",
    "local_time": "12:59 PM",
    "toggle_count": "99",
}

_PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


class UnknownVariable(KeyError):
    pass


def find_variables(text: str) -> list[str]:
    """Placeholder names in order of appearance, duplicates included."""
    return _PLACEHOLDER.findall(text)


def brace_errors(text: str) -> list[str]:
    """Problems with placeholder syntax: unknown names, stray braces."""
    errors = []
    for name in find_variables(text):
        if name not in VARIABLE_NAMES:
            errors.append(f"unknown variable {{{{{name}}}}}")
    leftover = _PLACEHOLDER.sub("", text)
    if "{{" in leftover or "}}" in leftover or "{" in leftover or "}" in leftover:
        errors.append("stray brace; placeholders must look like {{name}}")
    return errors


def render(text: str, values: dict[str, str]) -> str:
    def sub(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in values:
            raise UnknownVariable(name)
        return values[name]

    return _PLACEHOLDER.sub(sub, text)


def humanize_seconds(seconds: float) -> str:
    """Spoken-friendly duration: '45 seconds', '1 minute', '12 minutes',
    '1 hour 5 minutes', '3 hours', '2 days 4 hours'."""
    s = max(0, int(seconds))
    if s < 60:
        return _plural(s, "second")
    minutes, s = divmod(s, 60)
    if minutes < 60:
        return _plural(minutes, "minute")
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return _join(_plural(hours, "hour"), _plural(minutes, "minute") if minutes else "")
    days, hours = divmod(hours, 24)
    return _join(_plural(days, "day"), _plural(hours, "hour") if hours else "")


def _plural(n: int, unit: str) -> str:
    return f"{n} {unit}" if n == 1 else f"{n} {unit}s"


def _join(a: str, b: str) -> str:
    return f"{a} {b}" if b else a


def format_local_time(now: datetime) -> str:
    """12-hour clock without a leading zero: '2:14 AM', '12:05 PM'."""
    hour = now.hour % 12 or 12
    return f"{hour}:{now.minute:02d} {'AM' if now.hour < 12 else 'PM'}"


@dataclass(frozen=True)
class Values:
    """Everything a line can reference, already typed. Convert with as_strings()."""

    battery_percent: int | None
    absence_seconds: float
    today_count: int
    weekly_count: int
    total_count: int
    longest_absence_seconds: float
    average_away_seconds: float
    local_time: datetime
    toggle_count: int

    def as_strings(self) -> dict[str, str]:
        return {
            "battery_percent": "unknown" if self.battery_percent is None else str(int(self.battery_percent)),
            "absence_seconds": str(int(self.absence_seconds)),
            "absence_human": humanize_seconds(self.absence_seconds),
            "today_count": str(self.today_count),
            "weekly_count": str(self.weekly_count),
            "total_count": str(self.total_count),
            "longest_absence_seconds": str(int(self.longest_absence_seconds)),
            "average_away_seconds": str(int(self.average_away_seconds)),
            "local_time": format_local_time(self.local_time),
            "toggle_count": str(self.toggle_count),
        }
