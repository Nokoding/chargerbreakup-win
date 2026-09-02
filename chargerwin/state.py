"""Persistent state and the plug/unplug state machine.

The State is a plain dataclass mutated in place by three operations:

- observe(connected, now): a fresh reading of the AC status. Diffed against
  the last known status; returns Disconnected/Reconnected or None.
- due_escalation(now): called by a timer while unplugged; returns Escalated
  for the highest threshold crossed that has not fired yet, or None.
- resync(connected, now): silent adoption of the real status at startup.
  Never speaks, never touches counters.

All `now` values must be timezone-aware. Timestamps persist as ISO 8601
with offset so the state file stays readable when a user sends it in.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .events import Disconnected, Escalated, Event, Reconnected
from .groups import ESCALATION_MINUTES

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
STATE_FILENAME = "state.json"

# A disconnect within this many seconds of the previous disconnect extends the
# toggle streak; otherwise the streak restarts at 1.
STREAK_WINDOW_SECONDS = 10 * 60


def day_key(now: datetime) -> str:
    return now.date().isoformat()


def week_key(now: datetime) -> str:
    year, week, _ = now.isocalendar()
    return f"{year}-W{week:02d}"


def require_aware(now: datetime) -> datetime:
    if now.tzinfo is None or now.tzinfo.utcoffset(now) is None:
        raise ValueError("now must be a timezone-aware datetime")
    return now


def _seconds_between(earlier: datetime, later: datetime) -> float:
    """Elapsed seconds, clamped at zero so a clock step backwards cannot
    produce a negative absence."""
    return max(0.0, (later - earlier).total_seconds())


@dataclass
class State:
    connected: bool | None = None  # None: never observed
    disconnected_at: datetime | None = None  # set while unplugged
    last_disconnect_at: datetime | None = None  # for the toggle streak
    day_key: str = ""
    today_count: int = 0
    week_key: str = ""
    weekly_count: int = 0
    total_count: int = 0
    toggle_streak: int = 0
    longest_absence_seconds: float = 0.0
    absence_total_seconds: float = 0.0
    absence_count: int = 0
    escalations_fired: list[int] = field(default_factory=list)
    last_played: dict[str, str] = field(default_factory=dict)

    # ----- derived -------------------------------------------------------

    @property
    def average_away_seconds(self) -> float:
        if self.absence_count == 0:
            return 0.0
        return self.absence_total_seconds / self.absence_count

    def absence_seconds(self, now: datetime) -> float:
        """Seconds unplugged so far, or 0 when connected."""
        if self.connected is not False or self.disconnected_at is None:
            return 0.0
        return _seconds_between(self.disconnected_at, require_aware(now))

    # ----- transitions ---------------------------------------------------

    def roll_calendar(self, now: datetime) -> None:
        """Reset the daily and weekly counters when the local day or ISO week
        changes. Safe to call at any time."""
        require_aware(now)
        today = day_key(now)
        if today != self.day_key:
            self.day_key = today
            self.today_count = 0
        week = week_key(now)
        if week != self.week_key:
            self.week_key = week
            self.weekly_count = 0

    def resync(self, connected: bool, now: datetime) -> None:
        """Adopt the real AC status without speaking or counting.

        Used at startup, when the change (if any) happened while the app was
        not running and its timing is unknown. If we already knew we were
        unplugged and still are, keep the original disconnect time so the
        escalation timer carries on where it left off.
        """
        require_aware(now)
        self.roll_calendar(now)
        if connected:
            self.disconnected_at = None
            self.escalations_fired = []
        elif self.connected is not False or self.disconnected_at is None:
            self.disconnected_at = now
            self.escalations_fired = []
        self.connected = connected

    def observe(self, connected: bool, now: datetime) -> Event | None:
        """Diff a fresh AC status against the last known one."""
        require_aware(now)
        self.roll_calendar(now)
        if self.connected is None:
            self.resync(connected, now)
            return None
        if connected == self.connected:
            return None
        if connected:
            return self._reconnect(now)
        return self._disconnect(now)

    def _disconnect(self, now: datetime) -> Disconnected:
        self.today_count += 1
        self.weekly_count += 1
        self.total_count += 1
        if (
            self.last_disconnect_at is not None
            and _seconds_between(self.last_disconnect_at, now) <= STREAK_WINDOW_SECONDS
        ):
            self.toggle_streak += 1
        else:
            self.toggle_streak = 1
        self.disconnected_at = now
        self.last_disconnect_at = now
        self.escalations_fired = []
        self.connected = False
        return Disconnected()

    def _reconnect(self, now: datetime) -> Reconnected:
        absence = 0.0
        if self.disconnected_at is not None:
            absence = _seconds_between(self.disconnected_at, now)
            self.absence_count += 1
            self.absence_total_seconds += absence
            self.longest_absence_seconds = max(self.longest_absence_seconds, absence)
        self.disconnected_at = None
        self.escalations_fired = []
        self.connected = True
        return Reconnected(absence_seconds=absence)

    def due_escalation(self, now: datetime) -> Escalated | None:
        """Highest escalation threshold crossed and not yet fired, or None.

        Every crossed threshold is marked fired at once, so a laptop that
        sleeps through the 10 and 30 minute marks and wakes at 45 says the
        30-minute line once, not three lines in a row.
        """
        require_aware(now)
        self.roll_calendar(now)
        if self.connected is not False or self.disconnected_at is None:
            return None
        elapsed = _seconds_between(self.disconnected_at, now)
        crossed = [m for m in ESCALATION_MINUTES if elapsed >= m * 60]
        pending = [m for m in crossed if m not in self.escalations_fired]
        if not pending:
            return None
        self.escalations_fired = sorted(set(self.escalations_fired) | set(crossed))
        return Escalated(minutes=max(pending), absence_seconds=elapsed)

    # ----- serialization -------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "connected": self.connected,
            "disconnected_at": _iso(self.disconnected_at),
            "last_disconnect_at": _iso(self.last_disconnect_at),
            "day_key": self.day_key,
            "today_count": self.today_count,
            "week_key": self.week_key,
            "weekly_count": self.weekly_count,
            "total_count": self.total_count,
            "toggle_streak": self.toggle_streak,
            "longest_absence_seconds": self.longest_absence_seconds,
            "absence_total_seconds": self.absence_total_seconds,
            "absence_count": self.absence_count,
            "escalations_fired": list(self.escalations_fired),
            "last_played": dict(self.last_played),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "State":
        if not isinstance(data, dict):
            raise ValueError("state must be a JSON object")
        version = data.get("schema_version", SCHEMA_VERSION)
        if not isinstance(version, int) or version > SCHEMA_VERSION:
            raise ValueError(f"unsupported state schema_version {version!r}")
        connected = data.get("connected")
        if connected is not None and not isinstance(connected, bool):
            raise ValueError("connected must be true, false or null")
        fired = data.get("escalations_fired", [])
        last_played = data.get("last_played", {})
        if not isinstance(fired, list) or not isinstance(last_played, dict):
            raise ValueError("escalations_fired must be a list and last_played an object")
        return cls(
            connected=connected,
            disconnected_at=_parse(data.get("disconnected_at")),
            last_disconnect_at=_parse(data.get("last_disconnect_at")),
            day_key=str(data.get("day_key", "")),
            today_count=int(data.get("today_count", 0)),
            week_key=str(data.get("week_key", "")),
            weekly_count=int(data.get("weekly_count", 0)),
            total_count=int(data.get("total_count", 0)),
            toggle_streak=int(data.get("toggle_streak", 0)),
            longest_absence_seconds=float(data.get("longest_absence_seconds", 0.0)),
            absence_total_seconds=float(data.get("absence_total_seconds", 0.0)),
            absence_count=int(data.get("absence_count", 0)),
            escalations_fired=[int(m) for m in fired],
            last_played={str(k): str(v) for k, v in last_played.items()},
        )


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


def _parse(value: Any) -> datetime | None:
    if value is None:
        return None
    dt = datetime.fromisoformat(str(value))
    return require_aware(dt)


# ----- storage -------------------------------------------------------------


def default_state_dir() -> Path:
    """%APPDATA%\\chargerwin on Windows, XDG data dir elsewhere.
    CHARGERWIN_HOME overrides both."""
    override = os.environ.get("CHARGERWIN_HOME")
    if override:
        return Path(override)
    if sys.platform == "win32" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "chargerwin"
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "chargerwin"


class StateStore:
    """Loads and atomically saves the State at `<directory>/state.json`."""

    def __init__(self, directory: Path | None = None):
        self.directory = Path(directory) if directory is not None else default_state_dir()
        self.path = self.directory / STATE_FILENAME

    def load(self) -> State:
        """Missing file: fresh state. Unreadable file: warn, keep a copy as
        state.json.corrupt, start fresh. Never raises at startup."""
        if not self.path.exists():
            return State()
        try:
            with self.path.open("r", encoding="utf-8") as fh:
                return State.from_dict(json.load(fh))
        except (OSError, ValueError, TypeError, KeyError) as exc:
            backup = self.path.with_suffix(".json.corrupt")
            log.warning("state file %s unreadable (%s); starting fresh, copy kept at %s", self.path, exc, backup)
            try:
                os.replace(self.path, backup)
            except OSError:
                pass
            return State()

    def save(self, state: State) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(state.to_dict(), fh, indent=2)
            fh.write("\n")
        os.replace(tmp, self.path)
