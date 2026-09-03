import random

import pytest

from chargerwin.events import Disconnected, Escalated, Reconnected
from chargerwin.groups import MAX_LINE_CHARS
from chargerwin.pipeline import react, request_for, values_for
from chargerwin.state import State
from chargerwin.variables import WORST_CASE, render
from tests.conftest import at, make_pack


def unplug(state, when):
    return state.observe(False, when)


def plug(state, when):
    return state.observe(True, when)


def toggle_n_times(state, n, start_hour=9):
    """n disconnects, each 2 minutes after the previous reconnect, starting at start_hour."""
    event = None
    for i in range(n):
        minute = i * 4
        event = unplug(state, at(start_hour, minute))
        if i < n - 1:
            plug(state, at(start_hour, minute + 2))
    return event


# ----- request mapping -------------------------------------------------------


def test_first_disconnect_requests_immediate_with_time_of_day():
    s = State(connected=True)
    event = unplug(s, at(2, 10))
    r = request_for(event, s, at(2, 10))
    assert (r.group, r.time_of_day) == ("immediate", "late_night")


@pytest.mark.parametrize(
    "n,group",
    [(2, "rapid_2"), (3, "rapid_3"), (4, "rapid_4"), (5, "rapid_5"), (6, "rapid_6_through_9"), (9, "rapid_6_through_9"),
     (10, "rapid_10"), (11, "rapid_11_through_19"), (19, "rapid_11_through_19"), (20, "rapid_20"), (21, "rapid_21_plus"), (40, "rapid_21_plus")],
)
def test_nth_disconnect_requests_rapid_group(n, group):
    s = State(connected=True)
    event = toggle_n_times(s, n)
    assert s.today_count == n
    assert request_for(event, s, at(9)).group == group


def test_escalation_requests_its_group():
    s = State(connected=True)
    unplug(s, at(10))
    event = s.due_escalation(at(10, 30))
    r = request_for(event, s, at(10, 30))
    assert r.group == "escalation_30"
    assert r.absence_seconds == 1800


@pytest.mark.parametrize("minutes,group", [(1, "reunion_under_5"), (4.99, "reunion_under_5"), (5, "reunion_5_through_60"), (59, "reunion_5_through_60"), (60, "reunion_over_60"), (600, "reunion_over_60")])
def test_reunion_requests_by_duration(minutes, group):
    s = State(connected=True)
    unplug(s, at(8))
    event = plug(s, at(8, 0, second=int(minutes * 60)))
    assert request_for(event, s, at(9)).group == group


def test_reconnect_during_a_streak_requests_rapid_reunion():
    s = State(connected=True)
    toggle_n_times(s, 3)
    assert s.toggle_streak == 3
    event = plug(s, at(9, 9))
    r = request_for(event, s, at(9, 9))
    assert r.group == "rapid_reunion"
    assert r.absence_seconds == 60


def test_reconnect_with_short_streak_uses_duration_group():
    s = State(connected=True)
    toggle_n_times(s, 2)
    event = plug(s, at(9, 5))
    assert request_for(event, s, at(9, 5)).group == "reunion_under_5"


def test_unknown_event_type_rejected():
    with pytest.raises(TypeError):
        request_for(object(), State(), at())  # type: ignore[arg-type]


# ----- values ----------------------------------------------------------------


def test_values_absence_semantics_per_event():
    s = State(connected=True)
    assert values_for(Disconnected(), s, at(), 40).absence_seconds == 0
    assert values_for(Escalated(minutes=30, absence_seconds=1801), s, at(), 40).absence_seconds == 1801
    assert values_for(Reconnected(absence_seconds=77), s, at(), 40).absence_seconds == 77


def test_values_reflect_state_after_event():
    s = State(connected=True)
    unplug(s, at(10))
    plug(s, at(10, 5))
    event = unplug(s, at(10, 8))  # within the streak window
    v = values_for(event, s, at(10, 8), 33)
    assert (v.today_count, v.weekly_count, v.total_count, v.toggle_count) == (2, 2, 2, 2)
    assert v.longest_absence_seconds == 300
    assert v.average_away_seconds == 300
    assert v.battery_percent == 33
    assert v.local_time == at(10, 8)


# ----- react end to end with the sample pack -------------------------------


def test_react_renders_and_records_last_played(sample_pack):
    s = State(connected=True)
    event = unplug(s, at(2, 10))
    reaction = react(event, s, sample_pack, "medium", at(2, 10), random.Random(1), battery_percent=73)
    assert reaction is not None
    assert "{{" not in reaction.text and "}}" not in reaction.text
    assert reaction.selection.group in ("immediate", "immediate_late_night")
    assert reaction.selection.pool_key == "immediate"
    assert s.last_played == {"immediate": reaction.selection.line.id}
    assert reaction.values["battery_percent"] == "73"
    assert reaction.values["local_time"] == "2:10 AM"
    assert reaction.text == render(reaction.selection.line.text, reaction.values)


def test_react_substitutes_real_values():
    pack = make_pack({"medium": {"reunion_5_through_60": ["Gone {{absence_human}} at {{battery_percent}} percent, unplug {{today_count}}.", "other"]}})
    s = State(connected=True)
    unplug(s, at(10))
    event = plug(s, at(10, 20))
    reaction = react(event, s, pack, "medium", at(10, 20), random.Random(0), battery_percent=12)
    assert reaction.text in ("Gone 20 minutes at 12 percent, unplug 1.", "other")


def test_react_rapid_sequence_with_sample_pack(sample_pack):
    s = State(connected=True)
    seen = []
    for i in range(1, 13):
        event = unplug(s, at(9, i * 4))
        reaction = react(event, s, sample_pack, "medium", at(9, i * 4), random.Random(i))
        seen.append((reaction.selection.requested_group, reaction.selection.group))
        plug(s, at(9, i * 4 + 2))
    assert seen[0] == ("immediate", seen[0][1])
    assert seen[0][1] in ("immediate", "immediate_morning")
    assert seen[1] == ("rapid_2", "immediate")
    assert seen[2] == ("rapid_3", "rapid_3")
    assert seen[3] == ("rapid_4", "rapid_3")
    assert seen[8] == ("rapid_6_through_9", "rapid_3")
    assert seen[9] == ("rapid_10", "rapid_10")
    assert seen[11] == ("rapid_11_through_19", "rapid_10")


def test_react_escalations_with_sample_pack(sample_pack):
    s = State(connected=True)
    unplug(s, at(10))
    assert s.due_escalation(at(10, 10)) is None  # 10 minutes no longer escalates
    thirty = s.due_escalation(at(10, 30))
    r30 = react(thirty, s, sample_pack, "medium", at(10, 30), random.Random(1))
    assert r30.selection.group == "escalation_30"
    assert r30.values["absence_human"] == "30 minutes"
    sixty = s.due_escalation(at(11, 0))
    r60 = react(sixty, s, sample_pack, "intense", at(11, 0), random.Random(1))
    assert (r60.selection.group, r60.selection.intensity) == ("escalation_60", "intense")


def test_react_reunions_with_sample_pack(sample_pack):
    for minutes, group in ((2, "reunion_under_5"), (20, "reunion_5_through_60"), (90, "reunion_over_60")):
        s = State(connected=True)
        unplug(s, at(8))
        event = plug(s, at(8, 0, second=minutes * 60))
        reaction = react(event, s, sample_pack, "mild", at(9), random.Random(2))
        assert reaction.selection.group == group


def test_react_returns_none_and_keeps_state_when_silent():
    pack = make_pack({"medium": {"immediate": 2}})
    s = State(connected=True)
    unplug(s, at(10))
    event = s.due_escalation(at(10, 30))
    assert react(event, s, pack, "medium", at(10, 30), random.Random(1)) is None
    assert s.last_played == {}


def test_react_never_repeats_immediately(sample_pack):
    # today_count stays 1, so every draw is from the immediate pool.
    s = State(connected=False, today_count=1)
    ids = []
    for i in range(40):
        reaction = react(Disconnected(), s, sample_pack, "intense", at(14, i), random.Random(i))
        ids.append(reaction.selection.line.id)
    assert all(a != b for a, b in zip(ids, ids[1:]))
    assert len(set(ids)) == 3


def test_every_sample_line_renders_within_cap(sample_pack):
    for intensity, groups in sample_pack.intensities.items():
        for group, lines in groups.items():
            for line in lines:
                assert len(render(line.text, WORST_CASE)) <= MAX_LINE_CHARS, line.id
