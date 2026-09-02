"""Reaction-group vocabulary and the numeric thresholds that map onto it.

This is the single place that knows which group names exist and how counts
and durations map to them. The pack validator, the selector and the
pipeline all import from here. Adding a group means adding it here (and,
if it should be mandatory, to REQUIRED_GROUPS); nothing else needs to
change.
"""

from __future__ import annotations

INTENSITIES: tuple[str, ...] = ("mild", "medium", "intense")
DEFAULT_INTENSITY = "medium"

TIMES_OF_DAY: tuple[str, ...] = ("late_night", "morning", "afternoon", "evening")

IMMEDIATE = "immediate"
IMMEDIATE_BY_TIME: dict[str, str] = {tod: f"immediate_{tod}" for tod in TIMES_OF_DAY}

# Minutes after a disconnect at which an escalation fires if still unplugged.
ESCALATION_MINUTES: tuple[int, ...] = (10, 30, 60)
ESCALATION_GROUPS: tuple[str, ...] = tuple(f"escalation_{m}" for m in ESCALATION_MINUTES)

# Ordered from fewest disconnects to most. Fallback walks toward the front.
RAPID_GROUPS: tuple[str, ...] = (
    "rapid_2",
    "rapid_3",
    "rapid_4",
    "rapid_5",
    "rapid_6_through_9",
    "rapid_10",
    "rapid_11_through_19",
    "rapid_20",
    "rapid_21_plus",
)

# Ordered from shortest absence to longest. Fallback walks toward the front.
REUNION_GROUPS: tuple[str, ...] = (
    "reunion_under_5",
    "reunion_5_through_60",
    "reunion_over_60",
)
RAPID_REUNION = "rapid_reunion"

# Battery-insight groups. Not event driven; no trigger is defined for them yet.
BATTERY_GROUPS: tuple[str, ...] = (
    "healthy",
    "degraded",
    "connected_drain",
    "new_adapter",
    "insufficient_evidence",
)

DISCONNECT_GROUPS: tuple[str, ...] = (
    IMMEDIATE,
    *IMMEDIATE_BY_TIME.values(),
    *ESCALATION_GROUPS,
    *RAPID_GROUPS,
)
RECONNECT_GROUPS: tuple[str, ...] = (*REUNION_GROUPS, RAPID_REUNION)
ALL_GROUPS: tuple[str, ...] = DISCONNECT_GROUPS + RECONNECT_GROUPS + BATTERY_GROUPS

# v1 ships these. A pack is invalid unless each intensity has at least
# MIN_LINES_PER_GROUP lines in every one of them.
REQUIRED_GROUPS: tuple[str, ...] = (
    "immediate",
    "immediate_late_night",
    "escalation_30",
    "escalation_60",
    "rapid_3",
    "rapid_10",
    "reunion_under_5",
    "reunion_5_through_60",
    "reunion_over_60",
)

MIN_LINES_PER_GROUP = 2
MAX_LINE_CHARS = 160

# Reunion boundaries, in seconds.
REUNION_SHORT_SECONDS = 5 * 60
REUNION_LONG_SECONDS = 60 * 60

# A reconnect counts as a "rapid reunion" when the toggle streak is at least
# this long, i.e. this is the third (or later) quick disconnect in a row.
RAPID_REUNION_MIN_STREAK = 3


def rapid_group_for(today_count: int) -> str | None:
    """Group for the Nth disconnect of the day, or None for a first disconnect."""
    n = today_count
    if n < 2:
        return None
    if n <= 5:
        return f"rapid_{n}"
    if n <= 9:
        return "rapid_6_through_9"
    if n == 10:
        return "rapid_10"
    if n <= 19:
        return "rapid_11_through_19"
    if n == 20:
        return "rapid_20"
    return "rapid_21_plus"


def reunion_group_for(absence_seconds: float) -> str:
    """Duration-keyed reunion group. Boundaries: under 5 min, 5 to 60 min, 60+."""
    if absence_seconds < REUNION_SHORT_SECONDS:
        return "reunion_under_5"
    if absence_seconds < REUNION_LONG_SECONDS:
        return "reunion_5_through_60"
    return "reunion_over_60"


def lower_intensities(intensity: str) -> list[str]:
    """Intensities to fall back through, starting with `intensity` itself."""
    if intensity not in INTENSITIES:
        raise ValueError(f"unknown intensity {intensity!r}")
    i = INTENSITIES.index(intensity)
    return list(reversed(INTENSITIES[: i + 1]))
