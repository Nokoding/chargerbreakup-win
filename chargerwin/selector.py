"""Line selection with the fallback chain and the no-immediate-repeat rule.

A Request names the exact group the event calls for. The selector turns it
into an ordered list of candidate pools (fallback_chain), then walks:

    for each intensity, current first then lower ones:
        for each pool in the chain:
            flatten the pool's groups into weighted candidates
            skip if empty
            drop the last line played from this pool (if >1 candidate)
            weighted random draw -> done

If nothing matches at any intensity it logs a warning and returns None.
Silence beats a wrong-tone line; the validator makes this unreachable for
required groups.

Pools: most groups are a pool of one. The immediate pool merges `immediate`
(weight 1 per line) with `immediate_<time_of_day>` (weight 2 per line).
Weights are per line, so one late-night line in a pack of ten generic
lines gets 2/12 of the draws, not two thirds of them.

Chains (nearest lower populated group first):
- immediate*         -> [immediate pool]
- escalation_N       -> lower escalations. Never immediate: a "you just
                        unplugged" line is the wrong tone half an hour in.
- rapid_N            -> lower rapids -> immediate pool (still a disconnect
                        moment, so the tone is right).
- reunion_X          -> shorter reunions.
- rapid_reunion      -> the duration-keyed reunion chain.
- battery groups     -> that group only.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from typing import Mapping

from .groups import (
    BATTERY_GROUPS,
    ESCALATION_GROUPS,
    IMMEDIATE,
    IMMEDIATE_BY_TIME,
    RAPID_GROUPS,
    RAPID_REUNION,
    REUNION_GROUPS,
    lower_intensities,
    reunion_group_for,
)
from .packs import Line, Pack

log = logging.getLogger(__name__)

TIME_SPECIFIC_WEIGHT = 2
GENERIC_WEIGHT = 1

# A pool is an ordered tuple of (group, per-line weight). Its key, used for
# last-played tracking, is the first group's name.
Pool = tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class Request:
    group: str
    time_of_day: str
    absence_seconds: float = 0.0  # used for rapid_reunion fallback


@dataclass(frozen=True)
class Selection:
    line: Line
    group: str  # group the line actually came from
    intensity: str  # intensity the line actually came from
    pool_key: str  # key under which last-played is tracked
    requested_group: str


def immediate_pool(time_of_day: str) -> Pool:
    if time_of_day not in IMMEDIATE_BY_TIME:
        raise ValueError(f"unknown time of day {time_of_day!r}")
    return ((IMMEDIATE, GENERIC_WEIGHT), (IMMEDIATE_BY_TIME[time_of_day], TIME_SPECIFIC_WEIGHT))


def _single(group: str) -> Pool:
    return ((group, GENERIC_WEIGHT),)


def _descending(ordered: tuple[str, ...], group: str) -> list[Pool]:
    index = ordered.index(group)
    return [_single(g) for g in reversed(ordered[: index + 1])]


def fallback_chain(request: Request) -> list[Pool]:
    group = request.group
    if group == IMMEDIATE or group in IMMEDIATE_BY_TIME.values():
        return [immediate_pool(request.time_of_day)]
    if group in ESCALATION_GROUPS:
        return _descending(ESCALATION_GROUPS, group)
    if group in RAPID_GROUPS:
        return _descending(RAPID_GROUPS, group) + [immediate_pool(request.time_of_day)]
    if group in REUNION_GROUPS:
        return _descending(REUNION_GROUPS, group)
    if group == RAPID_REUNION:
        duration = Request(reunion_group_for(request.absence_seconds), request.time_of_day)
        return [_single(RAPID_REUNION)] + fallback_chain(duration)
    if group in BATTERY_GROUPS:
        return [_single(group)]
    raise ValueError(f"unknown group {group!r}")


def pool_key(pool: Pool) -> str:
    return pool[0][0]


def select(
    pack: Pack,
    intensity: str,
    request: Request,
    rng: random.Random,
    last_played: Mapping[str, str] | None = None,
) -> Selection | None:
    last_played = last_played or {}
    chain = fallback_chain(request)
    for level in lower_intensities(intensity):
        for pool in chain:
            candidates: list[tuple[Line, int, str]] = [
                (line, weight, group) for group, weight in pool for line in pack.lines(level, group)
            ]
            if not candidates:
                continue
            key = pool_key(pool)
            if len(candidates) > 1:
                skip = last_played.get(key)
                candidates = [c for c in candidates if c[0].id != skip] or candidates
            line, _, group = rng.choices(candidates, weights=[c[1] for c in candidates], k=1)[0]
            return Selection(line=line, group=group, intensity=level, pool_key=key, requested_group=request.group)
    log.warning(
        "pack %r has no line for %s at %s or any lower intensity; staying silent",
        pack.id,
        request.group,
        intensity,
    )
    return None
