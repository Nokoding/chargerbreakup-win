import copy
import json

import pytest

from chargerwin.groups import ALL_GROUPS, REQUIRED_GROUPS
from chargerwin.packs import Pack, find_pack, load_pack, packs_dir
from chargerwin.validate import PackError, validate_pack_dict


@pytest.fixture
def data():
    with (packs_dir() / "field_notes.json").open(encoding="utf-8") as fh:
        return json.load(fh)


def errors_for(data):
    return validate_pack_dict(data)


def test_sample_pack_is_valid(data):
    assert errors_for(data) == []
    assert data["id"] == "field_notes"


def test_every_required_group_present_at_every_intensity(data):
    for intensity in ("mild", "medium", "intense"):
        for group in REQUIRED_GROUPS:
            assert len(data["intensities"][intensity][group]) >= 2, (intensity, group)


def test_missing_required_group(data):
    del data["intensities"]["mild"]["rapid_3"]
    errs = errors_for(data)
    assert len(errs) == 1
    assert "mild: required group 'rapid_3'" in errs[0]


def test_required_group_with_one_line(data):
    data["intensities"]["intense"]["reunion_over_60"] = data["intensities"]["intense"]["reunion_over_60"][:1]
    assert any("required group 'reunion_over_60' needs at least 2 lines (has 1)" in e for e in errors_for(data))


def test_required_group_empty_list(data):
    data["intensities"]["medium"]["immediate"] = []
    assert any("required group 'immediate'" in e for e in errors_for(data))


def test_optional_group_may_be_absent_or_empty(data):
    data["intensities"]["mild"]["escalation_10"] = []
    assert errors_for(data) == []


def test_optional_group_with_one_line_is_an_error(data):
    data["intensities"]["mild"]["escalation_10"] = [{"id": "mild.escalation_10.1", "text": "Ten minutes."}]
    errs = errors_for(data)
    assert len(errs) == 1
    assert "mild/escalation_10: a present group needs at least 2 lines (has 1)" in errs[0]


def test_optional_group_with_two_lines_ok(data):
    data["intensities"]["mild"]["escalation_10"] = [
        {"id": "mild.escalation_10.1", "text": "Ten minutes."},
        {"id": "mild.escalation_10.2", "text": "Ten minutes, still."},
    ]
    assert errors_for(data) == []


def test_unknown_group_is_an_error(data):
    data["intensities"]["mild"]["imediate"] = copy.deepcopy(data["intensities"]["mild"]["immediate"])
    errs = errors_for(data)
    assert any("unknown group 'imediate'" in e for e in errs)


def test_battery_groups_are_snake_case(data):
    good = [{"id": "g1", "text": "a"}, {"id": "g2", "text": "b"}]
    data["intensities"]["mild"]["connected_drain"] = good
    assert errors_for(data) == []
    data["intensities"]["mild"]["connectedDrain"] = copy.deepcopy(good)
    assert any("unknown group 'connectedDrain'" in e for e in errors_for(data))


def test_all_groups_accepted(data):
    for group in ALL_GROUPS:
        data["intensities"]["mild"].setdefault(
            group, [{"id": f"x.{group}.1", "text": f"{group} one"}, {"id": f"x.{group}.2", "text": f"{group} two"}]
        )
    assert errors_for(data) == []


def test_missing_and_unknown_intensity(data):
    data["intensities"]["spicy"] = data["intensities"].pop("intense")
    errs = errors_for(data)
    assert any("unknown intensity 'spicy'" in e for e in errs)
    assert any("missing intensity 'intense'" in e for e in errs)


def test_duplicate_id_anywhere_in_pack(data):
    data["intensities"]["intense"]["rapid_10"][0]["id"] = data["intensities"]["mild"]["immediate"][0]["id"]
    errs = errors_for(data)
    assert len(errs) == 1
    assert "duplicate id 'mild.immediate.1'" in errs[0]
    assert "also at mild/immediate[0]" in errs[0]


def test_duplicate_text_ignores_case_and_whitespace(data):
    original = data["intensities"]["mild"]["immediate"][0]["text"]
    data["intensities"]["intense"]["rapid_10"][1]["text"] = "  " + original.upper().replace(" ", "   ")
    errs = errors_for(data)
    assert len(errs) == 1
    assert "duplicate text" in errs[0]


def test_unknown_variable(data):
    data["intensities"]["mild"]["immediate"][0]["text"] = "Battery at {{battery}} percent."
    errs = errors_for(data)
    assert len(errs) == 1
    assert "unknown variable {{battery}}" in errs[0]


@pytest.mark.parametrize("text", ["{{battery_percent}", "{battery_percent}}", "oops {", "oops }"])
def test_stray_braces(data, text):
    data["intensities"]["mild"]["immediate"][0]["text"] = text
    assert any("stray brace" in e for e in errors_for(data))


def test_line_over_cap_after_rendering(data):
    data["intensities"]["mild"]["immediate"][0]["text"] = "x" * 150 + " {{absence_human}}"
    errs = errors_for(data)
    assert len(errs) == 1
    assert "170 chars after rendering, cap is 160" in errs[0]


def test_raw_over_cap_but_rendered_under_is_fine(data):
    text = "{{battery_percent}}" * 8 + "x" * 100
    assert len(text) > 160
    data["intensities"]["mild"]["immediate"][0]["text"] = text
    assert errors_for(data) == []


def test_line_exactly_at_cap_is_fine(data):
    data["intensities"]["mild"]["immediate"][0]["text"] = "x" * 160
    assert errors_for(data) == []
    data["intensities"]["mild"]["immediate"][0]["text"] = "x" * 161
    assert len(errors_for(data)) == 1


@pytest.mark.parametrize(
    "mutate,fragment",
    [
        (lambda d: d.pop("id"), "'id' must be a non-empty string"),
        (lambda d: d.__setitem__("name", ""), "'name' must be a non-empty string"),
        (lambda d: d.__setitem__("summary", 3), "'summary' must be a string"),
        (lambda d: d.__setitem__("schema_version", 2), "unsupported schema_version 2"),
        (lambda d: d.__setitem__("voice", "loud"), "'voice' must be an object"),
        (lambda d: d["voice"].__setitem__("rate", 9), "voice.rate"),
        (lambda d: d["voice"].__setitem__("volume", -1), "voice.volume"),
        (lambda d: d["voice"].__setitem__("preferred_voice", 5), "voice.preferred_voice"),
        (lambda d: d.__setitem__("intensities", []), "'intensities' must be an object"),
        (lambda d: d["intensities"].__setitem__("mild", []), "mild: must be an object keyed by group"),
        (lambda d: d["intensities"]["mild"].__setitem__("immediate", "nope"), "mild/immediate: must be a list"),
        (lambda d: d["intensities"]["mild"]["immediate"].__setitem__(0, "nope"), "must be an object with 'id' and 'text'"),
        (lambda d: d["intensities"]["mild"]["immediate"][0].__setitem__("id", 7), "'id' must be a non-empty string"),
        (lambda d: d["intensities"]["mild"]["immediate"][0].__setitem__("text", "  "), "'text' must be a non-empty string"),
    ],
)
def test_structural_errors(data, mutate, fragment):
    mutate(data)
    assert any(fragment in e for e in errors_for(data)), errors_for(data)


def test_not_an_object():
    assert validate_pack_dict([1, 2]) == ["pack must be a JSON object"]


def test_errors_are_collected_not_short_circuited(data):
    del data["intensities"]["mild"]["rapid_3"]
    data["intensities"]["medium"]["immediate"][0]["text"] = "{{nope}}"
    data["intensities"]["intense"]["rapid_10"][0]["id"] = "mild.immediate.1"
    errs = errors_for(data)
    assert len(errs) == 3


def test_pack_from_dict_raises_pack_error_listing_everything(data):
    del data["intensities"]["mild"]["rapid_3"]
    data["intensities"]["medium"]["immediate"][0]["text"] = "{{nope}}"
    with pytest.raises(PackError) as info:
        Pack.from_dict(data)
    assert info.value.pack_id == "field_notes"
    assert len(info.value.errors) == 2
    assert "2 problem(s)" in str(info.value)


def test_pack_from_dict_builds_model(data):
    pack = Pack.from_dict(data)
    assert pack.id == "field_notes"
    assert pack.voice.rate == 0.9
    assert pack.voice.preferred_voice is None
    assert pack.line_count() == 81
    assert pack.lines("mild", "immediate")[0].id == "mild.immediate.1"
    assert pack.lines("mild", "escalation_10") == []
    assert pack.lines("nope", "immediate") == []


def test_load_pack_bad_json(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{")
    with pytest.raises(PackError) as info:
        load_pack(path)
    assert "not valid JSON" in str(info.value)


def test_find_pack_by_id_and_by_path(tmp_path, data):
    assert find_pack("field_notes").id == "field_notes"
    path = tmp_path / "copy.json"
    path.write_text(json.dumps(data))
    assert find_pack(str(path)).id == "field_notes"
    assert find_pack("copy", tmp_path).id == "field_notes"


def test_find_pack_missing_lists_available(tmp_path):
    with pytest.raises(PackError) as info:
        find_pack("nope")
    assert "available: field_notes" in str(info.value)
    with pytest.raises(PackError) as info:
        find_pack("nope", tmp_path / "empty")
    assert "available: none" in str(info.value)


def test_packs_dir_when_frozen(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr("sys._MEIPASS", str(tmp_path), raising=False)
    assert packs_dir() == tmp_path / "packs"


def test_lower_intensities_rejects_unknown():
    from chargerwin.groups import lower_intensities

    assert lower_intensities("intense") == ["intense", "medium", "mild"]
    assert lower_intensities("mild") == ["mild"]
    with pytest.raises(ValueError):
        lower_intensities("nuclear")


def test_every_firing_escalation_has_guaranteed_content():
    """A threshold that fires must have a group the validator forces packs to
    populate, otherwise the escalation happens and nothing is said.

    This is exactly how escalation_10 shipped broken: it fired at ten minutes,
    was not in REQUIRED_GROUPS, and escalations do not fall back to immediate,
    so the first escalation a user heard was silence. Ten minutes was then cut
    from the cadence. If a threshold is ever added back, this fails until its
    group is required too.
    """
    from chargerwin.groups import ESCALATION_MINUTES, REQUIRED_GROUPS

    for minutes in ESCALATION_MINUTES:
        assert f"escalation_{minutes}" in REQUIRED_GROUPS


def test_retired_escalation_group_is_still_a_valid_name():
    """escalation_10 no longer fires, but a pack defining it must stay valid so
    re-adding the cadence later is additive rather than a migration."""
    from chargerwin.groups import ALL_GROUPS, ESCALATION_MINUTES

    assert "escalation_10" in ALL_GROUPS
    assert 10 not in ESCALATION_MINUTES
