import pytest

from chargerwin.variables import (
    VARIABLE_NAMES,
    WORST_CASE,
    UnknownVariable,
    Values,
    brace_errors,
    find_variables,
    format_local_time,
    humanize_seconds,
    render,
)
from tests.conftest import at


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (0, "0 seconds"),
        (1, "1 second"),
        (59, "59 seconds"),
        (60, "1 minute"),
        (61, "1 minute"),
        (119, "1 minute"),
        (120, "2 minutes"),
        (3599, "59 minutes"),
        (3600, "1 hour"),
        (3660, "1 hour 1 minute"),
        (7500, "2 hours 5 minutes"),
        (86399, "23 hours 59 minutes"),
        (86400, "1 day"),
        (90000, "1 day 1 hour"),
        (2 * 86400 + 4 * 3600 + 59, "2 days 4 hours"),
        (-50, "0 seconds"),
        (12.9, "12 seconds"),
    ],
)
def test_humanize(seconds, expected):
    assert humanize_seconds(seconds) == expected


@pytest.mark.parametrize(
    "hour,minute,expected",
    [(0, 5, "12:05 AM"), (2, 14, "2:14 AM"), (11, 59, "11:59 AM"), (12, 0, "12:00 PM"), (13, 7, "1:07 PM"), (23, 30, "11:30 PM")],
)
def test_local_time(hour, minute, expected):
    assert format_local_time(at(hour, minute)) == expected


def test_worst_case_covers_every_variable():
    assert set(WORST_CASE) == set(VARIABLE_NAMES)


def test_find_variables_in_order_with_duplicates():
    assert find_variables("{{battery_percent}} and {{ local_time }} and {{battery_percent}}") == [
        "battery_percent",
        "local_time",
        "battery_percent",
    ]


def test_render_substitutes_and_tolerates_spaces():
    out = render("At {{battery_percent}}%, {{ absence_human }}.", {"battery_percent": "42", "absence_human": "3 minutes"})
    assert out == "At 42%, 3 minutes."


def test_render_unknown_variable_raises():
    with pytest.raises(UnknownVariable):
        render("{{nope}}", WORST_CASE)


@pytest.mark.parametrize(
    "text,problem",
    [
        ("{{nope}}", "unknown variable {{nope}}"),
        ("{{battery_percent}", "stray brace"),
        ("{battery_percent}}", "stray brace"),
        ("a { b", "stray brace"),
        ("a } b", "stray brace"),
    ],
)
def test_brace_errors(text, problem):
    assert any(problem in e for e in brace_errors(text))


def test_brace_errors_clean():
    assert brace_errors("{{battery_percent}} percent, {{absence_human}}.") == []


def test_values_as_strings():
    values = Values(
        battery_percent=42,
        absence_seconds=125.7,
        today_count=3,
        weekly_count=7,
        total_count=99,
        longest_absence_seconds=4000.2,
        average_away_seconds=1500.9,
        local_time=at(2, 14),
        toggle_count=2,
    ).as_strings()
    assert values == {
        "battery_percent": "42",
        "absence_seconds": "125",
        "absence_human": "2 minutes",
        "today_count": "3",
        "weekly_count": "7",
        "total_count": "99",
        "longest_absence_seconds": "4000",
        "average_away_seconds": "1500",
        "local_time": "2:14 AM",
        "toggle_count": "2",
    }
    assert set(values) == set(VARIABLE_NAMES)


def test_unknown_battery_renders_as_word():
    values = Values(None, 0, 0, 0, 0, 0, 0, at(), 0).as_strings()
    assert values["battery_percent"] == "unknown"
