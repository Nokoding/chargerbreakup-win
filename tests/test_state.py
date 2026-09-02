import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import pytest

from chargerwin.events import Disconnected, Escalated, Reconnected
from chargerwin.state import (
    STREAK_WINDOW_SECONDS,
    State,
    StateStore,
    day_key,
    default_state_dir,
    week_key,
)
from tests.conftest import TZ, at


def connected_state() -> State:
    return State(connected=True)


# ----- observe -------------------------------------------------------------


def test_fresh_state_first_observation_is_silent_resync():
    s = State()
    assert s.observe(False, at(10)) is None
    assert s.connected is False
    assert s.disconnected_at == at(10)
    assert (s.today_count, s.total_count) == (0, 0)


def test_same_status_twice_is_not_an_event():
    s = connected_state()
    assert s.observe(True, at(10)) is None
    assert isinstance(s.observe(False, at(10)), Disconnected)
    assert s.observe(False, at(10, 5)) is None
    assert s.today_count == 1
    assert s.disconnected_at == at(10)


def test_disconnect_counts_and_marks_time():
    s = connected_state()
    event = s.observe(False, at(10))
    assert event == Disconnected()
    assert (s.today_count, s.weekly_count, s.total_count, s.toggle_streak) == (1, 1, 1, 1)
    assert s.connected is False
    assert s.disconnected_at == at(10)
    assert s.last_disconnect_at == at(10)
    assert s.escalations_fired == []


def test_reconnect_reports_absence_and_updates_records():
    s = connected_state()
    s.observe(False, at(10))
    event = s.observe(True, at(10, 30))
    assert event == Reconnected(absence_seconds=1800.0)
    assert s.connected is True
    assert s.disconnected_at is None
    assert s.longest_absence_seconds == 1800.0
    assert s.absence_count == 1
    assert s.average_away_seconds == 1800.0


def test_longest_and_average_over_several_absences():
    s = connected_state()
    s.observe(False, at(10))
    s.observe(True, at(10, 10))  # 600
    s.observe(False, at(11))
    s.observe(True, at(11, 30))  # 1800
    s.observe(False, at(12))
    s.observe(True, at(12, 5))  # 300
    assert s.longest_absence_seconds == 1800.0
    assert s.absence_count == 3
    assert s.average_away_seconds == pytest.approx(900.0)


def test_reconnect_without_known_disconnect_time_is_zero_absence():
    s = State(connected=False, disconnected_at=None)
    event = s.observe(True, at(10))
    assert event == Reconnected(absence_seconds=0.0)
    assert s.absence_count == 0


def test_clock_stepping_backwards_clamps_absence_to_zero():
    s = connected_state()
    s.observe(False, at(10))
    event = s.observe(True, at(9, 50))
    assert event.absence_seconds == 0.0
    assert s.longest_absence_seconds == 0.0


def test_naive_datetime_rejected():
    s = connected_state()
    with pytest.raises(ValueError):
        s.observe(False, datetime(2026, 9, 2, 10, 0))


# ----- calendar --------------------------------------------------------------


def test_day_and_week_keys():
    assert day_key(at(23, 59)) == "2026-09-02"
    assert week_key(at()) == "2026-W36"
    assert week_key(at(day=7)) == "2026-W37"  # Monday 7 September starts a new ISO week


def test_today_count_resets_at_local_midnight_weekly_does_not():
    s = connected_state()
    s.observe(False, at(23, 50))
    s.observe(True, at(23, 55))
    s.observe(False, at(0, 5, day=3))
    assert s.today_count == 1
    assert s.weekly_count == 2
    assert s.total_count == 2


def test_weekly_count_resets_on_new_iso_week():
    s = connected_state()
    s.observe(False, at(10, day=5))  # Saturday
    s.observe(True, at(11, day=5))
    s.observe(False, at(10, day=6))  # Sunday, same ISO week
    s.observe(True, at(11, day=6))
    assert s.weekly_count == 2
    s.observe(False, at(10, day=7))  # Monday, new ISO week
    assert s.weekly_count == 1
    assert s.today_count == 1
    assert s.total_count == 3


def test_roll_calendar_on_read_resets_stale_today_count():
    s = connected_state()
    s.observe(False, at(23, 50))
    s.roll_calendar(at(0, 1, day=3))
    assert s.today_count == 0
    assert s.connected is False  # the absence itself continues across midnight


# ----- streak ----------------------------------------------------------------


def test_streak_grows_within_window_and_resets_outside():
    s = connected_state()
    s.observe(False, at(10, 0))
    s.observe(True, at(10, 1))
    s.observe(False, at(10, 5))
    assert s.toggle_streak == 2
    s.observe(True, at(10, 6))
    s.observe(False, at(10, 8))
    assert s.toggle_streak == 3
    s.observe(True, at(10, 9))
    s.observe(False, at(10, 30))  # 22 minutes after the previous disconnect
    assert s.toggle_streak == 1


def test_streak_window_boundary_is_inclusive():
    s = connected_state()
    s.observe(False, at(10, 0))
    s.observe(True, at(10, 1))
    s.observe(False, at(10, 0, second=STREAK_WINDOW_SECONDS))
    assert s.toggle_streak == 2
    s.observe(True, at(10, 11))
    s.observe(False, at(10, 10, second=STREAK_WINDOW_SECONDS + 1))
    assert s.toggle_streak == 1


# ----- escalation ------------------------------------------------------------


def test_escalations_fire_once_each_in_order():
    s = connected_state()
    s.observe(False, at(10))
    assert s.due_escalation(at(10, 5)) is None
    assert s.due_escalation(at(10, 10)) == Escalated(minutes=10, absence_seconds=600.0)
    assert s.due_escalation(at(10, 11)) is None
    assert s.due_escalation(at(10, 30)) == Escalated(minutes=30, absence_seconds=1800.0)
    assert s.due_escalation(at(10, 59)) is None
    assert s.due_escalation(at(11, 0)) == Escalated(minutes=60, absence_seconds=3600.0)
    assert s.due_escalation(at(13, 0)) is None
    assert s.escalations_fired == [10, 30, 60]


def test_waking_from_sleep_fires_only_the_highest_crossed_threshold():
    s = connected_state()
    s.observe(False, at(10))
    assert s.due_escalation(at(10, 45)) == Escalated(minutes=30, absence_seconds=2700.0)
    assert s.escalations_fired == [10, 30]
    assert s.due_escalation(at(10, 46)) is None
    assert s.due_escalation(at(11, 5)).minutes == 60


def test_no_escalation_while_connected_or_unknown():
    assert connected_state().due_escalation(at(10)) is None
    assert State().due_escalation(at(10)) is None


def test_reconnect_clears_escalations_and_new_disconnect_starts_over():
    s = connected_state()
    s.observe(False, at(10))
    s.due_escalation(at(10, 30))
    s.observe(True, at(10, 31))
    assert s.escalations_fired == []
    s.observe(False, at(11))
    assert s.due_escalation(at(11, 5)) is None
    assert s.due_escalation(at(11, 10)).minutes == 10


# ----- resync ----------------------------------------------------------------


def test_resync_keeps_disconnect_time_when_still_unplugged():
    s = connected_state()
    s.observe(False, at(10))
    s.due_escalation(at(10, 10))
    s.resync(False, at(10, 20))
    assert s.disconnected_at == at(10)
    assert s.escalations_fired == [10]
    assert s.due_escalation(at(10, 30)).minutes == 30


def test_resync_to_unplugged_from_connected_starts_the_clock_now_silently():
    s = connected_state()
    s.resync(False, at(10))
    assert s.connected is False
    assert s.disconnected_at == at(10)
    assert (s.today_count, s.total_count) == (0, 0)


def test_resync_to_connected_clears_absence_without_counting():
    s = connected_state()
    s.observe(False, at(10))
    s.resync(True, at(12))
    assert s.connected is True
    assert s.disconnected_at is None
    assert s.absence_count == 0
    assert s.longest_absence_seconds == 0.0


# ----- serialization ---------------------------------------------------------


def test_round_trip_through_dict():
    s = connected_state()
    s.observe(False, at(10))
    s.observe(True, at(10, 20))
    s.observe(False, at(10, 25))
    s.due_escalation(at(10, 40))
    s.last_played["immediate"] = "x.immediate.1"
    restored = State.from_dict(json.loads(json.dumps(s.to_dict())))
    assert restored == s
    assert restored.disconnected_at.tzinfo is not None


def test_from_dict_tolerates_missing_and_unknown_keys():
    assert State.from_dict({}) == State()
    assert State.from_dict({"schema_version": 1, "future_field": 1, "today_count": 4}).today_count == 4


@pytest.mark.parametrize(
    "data",
    [
        [],
        {"schema_version": 99},
        {"connected": "yes"},
        {"escalations_fired": {}},
        {"last_played": []},
        {"disconnected_at": "2026-09-02T10:00:00"},  # naive
        {"disconnected_at": "not a date"},
    ],
)
def test_from_dict_rejects_bad_data(data):
    with pytest.raises(ValueError):
        State.from_dict(data)


# ----- store -----------------------------------------------------------------


def test_store_missing_file_is_fresh(tmp_path):
    store = StateStore(tmp_path / "nested" / "dir")
    assert store.load() == State()


def test_store_save_and_load(tmp_path):
    store = StateStore(tmp_path)
    s = connected_state()
    s.observe(False, at(10))
    store.save(s)
    assert store.path.exists()
    assert not store.path.with_suffix(".json.tmp").exists()
    assert store.load() == s
    assert json.loads(store.path.read_text())["schema_version"] == 1


def test_store_creates_directory(tmp_path):
    store = StateStore(tmp_path / "a" / "b")
    store.save(State())
    assert store.path.exists()


def test_store_corrupt_file_is_backed_up_and_warned(tmp_path, caplog):
    store = StateStore(tmp_path)
    store.path.write_text("{not json")
    with caplog.at_level(logging.WARNING):
        assert store.load() == State()
    assert "starting fresh" in caplog.text
    assert not store.path.exists()
    assert (tmp_path / "state.json.corrupt").read_text() == "{not json"


def test_store_future_schema_is_treated_as_unreadable(tmp_path):
    store = StateStore(tmp_path)
    store.path.write_text(json.dumps({"schema_version": 42}))
    assert store.load() == State()
    assert (tmp_path / "state.json.corrupt").exists()


def test_default_dir_env_override(monkeypatch):
    monkeypatch.setenv("CHARGERWIN_HOME", "/somewhere/else")
    assert default_state_dir() == Path("/somewhere/else")


def test_default_dir_windows_appdata(monkeypatch):
    monkeypatch.delenv("CHARGERWIN_HOME", raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", r"C:\Users\x\AppData\Roaming")
    assert default_state_dir() == Path(r"C:\Users\x\AppData\Roaming") / "chargerwin"


def test_default_dir_xdg(monkeypatch, tmp_path):
    monkeypatch.delenv("CHARGERWIN_HOME", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert default_state_dir() == tmp_path / "chargerwin"
    monkeypatch.delenv("XDG_DATA_HOME")
    assert default_state_dir() == Path.home() / ".local" / "share" / "chargerwin"


def test_store_default_dir_used_when_none_given(monkeypatch, tmp_path):
    monkeypatch.setenv("CHARGERWIN_HOME", str(tmp_path))
    assert StateStore().path == tmp_path / "state.json"


def test_absence_seconds_helper():
    s = connected_state()
    assert s.absence_seconds(at(10)) == 0.0
    s.observe(False, at(10))
    assert s.absence_seconds(at(10, 2)) == 120.0
    assert s.absence_seconds(at(9)) == 0.0
