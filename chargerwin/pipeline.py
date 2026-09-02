"""Glue from an Event to the rendered text that should be spoken.

    event = state.observe(plugged, now)        # or state.due_escalation(now)
    reaction = react(event, state, pack, intensity, now, rng, battery)
    if reaction: speak(reaction.text)

react() is the only place that knows how events map to groups and how the
State turns into template values. It records the played line id in
state.last_played; the caller persists the State.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime

from .events import Disconnected, Escalated, Event, Reconnected
from .groups import IMMEDIATE, RAPID_REUNION, RAPID_REUNION_MIN_STREAK, rapid_group_for, reunion_group_for
from .packs import Pack
from .selector import Request, Selection, select
from .state import State
from .timeofday import time_of_day
from .variables import Values, render


@dataclass(frozen=True)
class Reaction:
    selection: Selection
    text: str  # rendered, ready to speak
    values: dict[str, str]


def request_for(event: Event, state: State, now: datetime) -> Request:
    tod = time_of_day(now)
    if isinstance(event, Disconnected):
        return Request(rapid_group_for(state.today_count) or IMMEDIATE, tod)
    if isinstance(event, Escalated):
        return Request(f"escalation_{event.minutes}", tod, event.absence_seconds)
    if isinstance(event, Reconnected):
        if state.toggle_streak >= RAPID_REUNION_MIN_STREAK:
            return Request(RAPID_REUNION, tod, event.absence_seconds)
        return Request(reunion_group_for(event.absence_seconds), tod, event.absence_seconds)
    raise TypeError(f"unknown event {event!r}")


def values_for(event: Event, state: State, now: datetime, battery_percent: int | None) -> Values:
    """Template values as of just after `event` was applied to `state`.
    absence_seconds is 0 on a disconnect, elapsed-so-far on an escalation and
    the completed absence on a reunion."""
    absence = 0.0 if isinstance(event, Disconnected) else event.absence_seconds
    return Values(
        battery_percent=battery_percent,
        absence_seconds=absence,
        today_count=state.today_count,
        weekly_count=state.weekly_count,
        total_count=state.total_count,
        longest_absence_seconds=state.longest_absence_seconds,
        average_away_seconds=state.average_away_seconds,
        local_time=now,
        toggle_count=state.toggle_streak,
    )


def react(
    event: Event,
    state: State,
    pack: Pack,
    intensity: str,
    now: datetime,
    rng: random.Random,
    battery_percent: int | None = None,
) -> Reaction | None:
    request = request_for(event, state, now)
    selection = select(pack, intensity, request, rng, state.last_played)
    if selection is None:
        return None
    state.last_played[selection.pool_key] = selection.line.id
    values = values_for(event, state, now, battery_percent).as_strings()
    return Reaction(selection=selection, text=render(selection.line.text, values), values=values)
