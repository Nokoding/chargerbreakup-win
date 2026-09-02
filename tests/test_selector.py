import logging
import random
from collections import Counter

import pytest

from chargerwin.groups import INTENSITIES, RAPID_GROUPS, REQUIRED_GROUPS
from chargerwin.selector import Request, fallback_chain, immediate_pool, pool_key, select
from tests.conftest import make_pack

TOD = "afternoon"


def req(group, tod=TOD, absence=0.0):
    return Request(group=group, time_of_day=tod, absence_seconds=absence)


def groups_in(chain):
    return [[g for g, _ in pool] for pool in chain]


# ----- chains ----------------------------------------------------------------


def test_immediate_chain_is_the_merged_pool():
    assert groups_in(fallback_chain(req("immediate", "late_night"))) == [["immediate", "immediate_late_night"]]
    assert groups_in(fallback_chain(req("immediate_morning", "morning"))) == [["immediate", "immediate_morning"]]


def test_immediate_pool_weights_time_specific_lines_twice():
    assert immediate_pool("evening") == (("immediate", 1), ("immediate_evening", 2))
    with pytest.raises(ValueError):
        immediate_pool("midnight")


def test_escalation_chain_walks_down_and_never_reaches_immediate():
    assert groups_in(fallback_chain(req("escalation_60"))) == [["escalation_60"], ["escalation_30"], ["escalation_10"]]
    assert groups_in(fallback_chain(req("escalation_10"))) == [["escalation_10"]]


def test_rapid_chain_walks_down_then_immediate_pool():
    chain = groups_in(fallback_chain(req("rapid_6_through_9", "morning")))
    assert chain == [
        ["rapid_6_through_9"],
        ["rapid_5"],
        ["rapid_4"],
        ["rapid_3"],
        ["rapid_2"],
        ["immediate", "immediate_morning"],
    ]
    assert groups_in(fallback_chain(req("rapid_2"))) == [["rapid_2"], ["immediate", f"immediate_{TOD}"]]
    assert groups_in(fallback_chain(req("rapid_21_plus")))[0] == ["rapid_21_plus"]
    assert len(fallback_chain(req("rapid_21_plus"))) == len(RAPID_GROUPS) + 1


def test_reunion_chain_walks_toward_shorter_absences():
    assert groups_in(fallback_chain(req("reunion_over_60"))) == [
        ["reunion_over_60"],
        ["reunion_5_through_60"],
        ["reunion_under_5"],
    ]
    assert groups_in(fallback_chain(req("reunion_under_5"))) == [["reunion_under_5"]]


def test_rapid_reunion_falls_back_to_the_duration_group():
    assert groups_in(fallback_chain(req("rapid_reunion", absence=1200))) == [
        ["rapid_reunion"],
        ["reunion_5_through_60"],
        ["reunion_under_5"],
    ]
    assert groups_in(fallback_chain(req("rapid_reunion", absence=30))) == [["rapid_reunion"], ["reunion_under_5"]]


def test_battery_groups_have_no_fallback():
    assert groups_in(fallback_chain(req("connected_drain"))) == [["connected_drain"]]


def test_unknown_group_raises():
    with pytest.raises(ValueError):
        fallback_chain(req("nope"))


def test_pool_key_is_first_group():
    assert pool_key(immediate_pool("evening")) == "immediate"


# ----- selection -------------------------------------------------------------


def test_exact_group_wins(rng):
    pack = make_pack({"medium": {"rapid_3": 3, "immediate": 3}})
    sel = select(pack, "medium", req("rapid_3"), rng)
    assert sel.group == "rapid_3"
    assert sel.intensity == "medium"
    assert sel.pool_key == "rapid_3"
    assert sel.requested_group == "rapid_3"
    assert sel.line.id.startswith("medium.rapid_3.")


def test_escalation_stays_silent_rather_than_using_immediate(rng, caplog):
    pack = make_pack({"medium": {"immediate": 3, "immediate_afternoon": 3}})
    with caplog.at_level(logging.WARNING):
        assert select(pack, "medium", req("escalation_10"), rng) is None
        assert select(pack, "medium", req("escalation_60"), rng) is None
    assert "staying silent" in caplog.text
    assert "escalation_60" in caplog.text


def test_escalation_falls_to_nearest_lower_populated(rng):
    pack = make_pack({"medium": {"escalation_10": 2, "escalation_30": 2}})
    assert select(pack, "medium", req("escalation_60"), rng).group == "escalation_30"
    pack = make_pack({"medium": {"escalation_10": 2}})
    assert select(pack, "medium", req("escalation_60"), rng).group == "escalation_10"


def test_rapid_falls_to_nearest_lower_then_immediate(rng):
    pack = make_pack({"medium": {"rapid_3": 2, "rapid_10": 2, "immediate": 2}})
    assert select(pack, "medium", req("rapid_2"), rng).group == "immediate"
    assert select(pack, "medium", req("rapid_4"), rng).group == "rapid_3"
    assert select(pack, "medium", req("rapid_6_through_9"), rng).group == "rapid_3"
    assert select(pack, "medium", req("rapid_10"), rng).group == "rapid_10"
    assert select(pack, "medium", req("rapid_21_plus"), rng).group == "rapid_10"


def test_reunion_falls_toward_shorter(rng):
    pack = make_pack({"medium": {"reunion_under_5": 2}})
    sel = select(pack, "medium", req("reunion_over_60"), rng)
    assert sel.group == "reunion_under_5"
    assert sel.requested_group == "reunion_over_60"
    pack = make_pack({"medium": {"reunion_under_5": 2, "reunion_5_through_60": 2}})
    assert select(pack, "medium", req("reunion_over_60"), rng).group == "reunion_5_through_60"


def test_rapid_reunion_uses_duration_fallback(rng):
    pack = make_pack({"medium": {"reunion_under_5": 2, "reunion_5_through_60": 2}})
    assert select(pack, "medium", req("rapid_reunion", absence=900), rng).group == "reunion_5_through_60"
    pack = make_pack({"medium": {"rapid_reunion": 2, "reunion_under_5": 2}})
    assert select(pack, "medium", req("rapid_reunion", absence=900), rng).group == "rapid_reunion"


def test_lower_intensity_fallback(rng):
    pack = make_pack({"medium": {"immediate": 2}})
    sel = select(pack, "intense", req("immediate"), rng)
    assert sel.intensity == "medium"
    assert sel.group == "immediate"


def test_never_falls_upward_in_intensity(rng, caplog):
    pack = make_pack({"intense": {"immediate": 2}})
    with caplog.at_level(logging.WARNING):
        assert select(pack, "mild", req("immediate"), rng) is None
        assert select(pack, "medium", req("immediate"), rng) is None
    assert "any lower intensity" in caplog.text


def test_whole_chain_runs_at_current_intensity_before_dropping():
    # intense has a fallback group; medium has the exact group. Exact match at a
    # lower intensity must not beat a fallback at the current intensity.
    pack = make_pack({"intense": {"escalation_30": 2}, "medium": {"escalation_60": 2}})
    sel = select(pack, "intense", req("escalation_60"), random.Random(1))
    assert (sel.intensity, sel.group) == ("intense", "escalation_30")


def test_lower_intensity_walks_its_whole_chain_too():
    pack = make_pack({"mild": {"escalation_10": 2}})
    sel = select(pack, "intense", req("escalation_60"), random.Random(1))
    assert (sel.intensity, sel.group) == ("mild", "escalation_10")


def test_immediate_pool_merges_time_of_day_two_to_one():
    pack = make_pack({"medium": {"immediate": 1, "immediate_late_night": 1}})
    rng = random.Random(7)
    counts = Counter(select(pack, "medium", req("immediate", "late_night"), rng).group for _ in range(3000))
    share = counts["immediate_late_night"] / 3000
    assert 0.62 < share < 0.72, counts


def test_time_weight_is_per_line_not_per_group():
    pack = make_pack({"medium": {"immediate": 10, "immediate_late_night": 1}})
    rng = random.Random(7)
    counts = Counter(select(pack, "medium", req("immediate", "late_night"), rng).group for _ in range(6000))
    share = counts["immediate_late_night"] / 6000
    assert 0.12 < share < 0.22, counts  # expected 2/12


def test_time_of_day_does_not_apply_outside_its_window():
    pack = make_pack({"medium": {"immediate": 1, "immediate_late_night": 1}})
    rng = random.Random(7)
    groups = {select(pack, "medium", req("immediate", "morning"), rng).group for _ in range(200)}
    assert groups == {"immediate"}


def test_immediate_pool_works_when_either_half_is_missing(rng):
    only_generic = make_pack({"medium": {"immediate": 2}})
    assert select(only_generic, "medium", req("immediate", "late_night"), rng).group == "immediate"
    only_time = make_pack({"medium": {"immediate_late_night": 2}})
    sel = select(only_time, "medium", req("immediate", "late_night"), rng)
    assert sel.group == "immediate_late_night"
    assert sel.pool_key == "immediate"


def test_no_immediate_repeat_alternates_with_two_lines():
    pack = make_pack({"medium": {"immediate": 2}})
    rng = random.Random(3)
    last_played = {}
    played = []
    for _ in range(30):
        sel = select(pack, "medium", req("immediate"), rng, last_played)
        last_played[sel.pool_key] = sel.line.id
        played.append(sel.line.id)
    assert all(a != b for a, b in zip(played, played[1:]))
    assert set(played) == {"medium.immediate.1", "medium.immediate.2"}


def test_no_immediate_repeat_with_many_lines():
    pack = make_pack({"medium": {"immediate": 5, "immediate_evening": 3}})
    rng = random.Random(11)
    last_played = {}
    played = []
    for _ in range(300):
        sel = select(pack, "medium", req("immediate", "evening"), rng, last_played)
        last_played[sel.pool_key] = sel.line.id
        played.append(sel.line.id)
    assert all(a != b for a, b in zip(played, played[1:]))
    assert len(set(played)) == 8


def test_single_candidate_repeats_rather_than_going_silent(rng):
    pack = make_pack({"medium": {"reunion_under_5": 1}})
    first = select(pack, "medium", req("reunion_under_5"), rng)
    second = select(pack, "medium", req("reunion_under_5"), rng, {first.pool_key: first.line.id})
    assert second is not None and second.line.id == first.line.id


def test_last_played_is_keyed_by_resolved_pool(rng):
    pack = make_pack({"medium": {"rapid_3": 2, "immediate": 2}})
    sel = select(pack, "medium", req("rapid_4"), rng)
    assert sel.pool_key == "rapid_3"
    # A previous rapid_3 play is excluded even though the request was rapid_4.
    other = select(pack, "medium", req("rapid_4"), rng, {"rapid_3": sel.line.id})
    assert other.line.id != sel.line.id


def test_last_played_for_other_pools_is_ignored(rng):
    pack = make_pack({"medium": {"immediate": 2}})
    sel = select(pack, "medium", req("immediate"), rng, {"rapid_3": "medium.immediate.1", "immediate": "unrelated"})
    assert sel is not None


def test_seeded_rng_is_deterministic():
    pack = make_pack({"medium": {"immediate": 6}})
    a = [select(pack, "medium", req("immediate"), random.Random(99)).line.id for _ in range(5)]
    b = [select(pack, "medium", req("immediate"), random.Random(99)).line.id for _ in range(5)]
    assert a == b


def test_sample_pack_never_goes_silent_for_required_groups(sample_pack, rng):
    for intensity in INTENSITIES:
        for group in REQUIRED_GROUPS:
            for tod in ("late_night", "morning"):
                assert select(sample_pack, intensity, req(group, tod), rng) is not None, (intensity, group)
