from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest

from chargerwin.groups import INTENSITIES
from chargerwin.packs import Line, Pack, load_pack, packs_dir

# A fixed non-UTC zone so tests catch any code that confuses wall-clock
# time with UTC.
TZ = timezone(timedelta(hours=-5))


def at(hour: int = 12, minute: int = 0, day: int = 2, month: int = 9, year: int = 2026, second: int = 0) -> datetime:
    """Aware datetime in TZ. Defaults to 2 September 2026, a Wednesday.
    Minutes and seconds may overflow (minute=90 is an hour and a half in)."""
    return datetime(year, month, day, tzinfo=TZ) + timedelta(hours=hour, minutes=minute, seconds=second)


def make_pack(spec: dict[str, dict[str, list[str] | int]], pack_id: str = "test") -> Pack:
    """Build a Pack without validation so tests can leave groups empty.

    spec = {intensity: {group: [text, ...] or number_of_lines}}
    Line ids are "<intensity>.<group>.<n>".
    """
    intensities: dict[str, dict[str, list[Line]]] = {i: {} for i in INTENSITIES}
    for intensity, groups in spec.items():
        for group, lines in groups.items():
            if isinstance(lines, int):
                lines = [f"{group} line {n}" for n in range(1, lines + 1)]
            intensities[intensity][group] = [
                Line(id=f"{intensity}.{group}.{n}", text=text) for n, text in enumerate(lines, 1)
            ]
    return Pack(id=pack_id, name="Test pack", intensities=intensities)


@pytest.fixture
def rng() -> random.Random:
    return random.Random(1234)


@pytest.fixture(scope="session")
def sample_pack() -> Pack:
    return load_pack(packs_dir() / "field_notes.json")
