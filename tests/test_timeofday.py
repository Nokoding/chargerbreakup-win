import pytest

from chargerwin.timeofday import time_of_day
from tests.conftest import at


@pytest.mark.parametrize(
    "hour,minute,expected",
    [
        (22, 0, "late_night"),
        (23, 59, "late_night"),
        (0, 0, "late_night"),
        (4, 59, "late_night"),
        (5, 0, "morning"),
        (11, 59, "morning"),
        (12, 0, "afternoon"),
        (16, 59, "afternoon"),
        (17, 0, "evening"),
        (21, 59, "evening"),
    ],
)
def test_windows(hour, minute, expected):
    assert time_of_day(at(hour, minute)) == expected
