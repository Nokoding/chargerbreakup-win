import json
from pathlib import Path

import pytest

from chargerwin import __version__
from chargerwin.cli import main, parse_now
from chargerwin.packs import packs_dir


@pytest.fixture
def run(capsys):
    def _run(*args):
        code = main(list(args))
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return _run


@pytest.fixture
def state_dir(tmp_path):
    return str(tmp_path / "state")


def test_no_action_prints_usage_and_exits_2(run):
    code, out, err = run()
    assert code == 2
    assert "Nothing to do" in out


def test_version(capsys):
    with pytest.raises(SystemExit) as info:
        main(["--version"])
    assert info.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_validate_sample_pack(run):
    code, out, _ = run("--validate")
    assert code == 0
    assert "OK" in out and "field_notes: 81 lines" in out


def test_validate_by_id_and_path(run):
    assert run("--validate", "field_notes")[0] == 0
    assert run("--validate", str(packs_dir() / "field_notes.json"))[0] == 0


def test_validate_broken_pack(run, tmp_path):
    path = tmp_path / "bad.json"
    with (packs_dir() / "field_notes.json").open(encoding="utf-8") as fh:
        data = json.load(fh)
    del data["intensities"]["mild"]["rapid_3"]
    data["intensities"]["medium"]["immediate"][0]["text"] = "x" * 200
    path.write_text(json.dumps(data))
    code, out, _ = run("--validate", str(path), "field_notes")
    assert code == 1
    assert "FAIL" in out and "required group 'rapid_3'" in out and "cap is 160" in out
    assert "OK" in out  # the good pack still reported


def test_validate_missing_pack(run, tmp_path):
    code, out, _ = run("--validate", str(tmp_path / "nope.json"))
    assert code == 1
    assert "FAIL" in out


def test_simulate_unplug_on_fresh_state_speaks(run, state_dir):
    code, out, _ = run("--simulate", "unplug", "--now", "2026-09-02T02:10", "--state-dir", state_dir, "--seed", "1")
    assert code == 0
    lines = out.strip().splitlines()
    assert lines[0].startswith("[unplug] 2026-09-02 02:10 late_night -> medium/immediate")
    assert "{{" not in lines[1]
    assert "today=1 streak=1 week=1 total=1, unplugged for 0 seconds" in lines[2]
    state = json.loads((Path(state_dir) / "state.json").read_text())
    assert state["connected"] is False and state["today_count"] == 1


def test_simulate_same_event_twice_reports_no_change(run, state_dir):
    run("--simulate", "unplug", "--now", "2026-09-02T10:00", "--state-dir", state_dir)
    code, out, _ = run("--simulate", "unplug", "--now", "2026-09-02T10:01", "--state-dir", state_dir)
    assert code == 0
    assert "no change, already unplugged" in out


def test_simulate_plug_after_unplug_is_a_reunion(run, state_dir):
    run("--simulate", "unplug", "--now", "2026-09-02T10:00", "--state-dir", state_dir)
    code, out, _ = run("--simulate", "plug", "--now", "2026-09-02T10:20", "--state-dir", state_dir, "--battery", "9")
    assert code == 0
    assert "-> medium/reunion_5_through_60" in out
    assert "plugged in" in out


def test_simulate_plug_on_fresh_state_speaks_too(run, state_dir):
    code, out, _ = run("--simulate", "plug", "--now", "2026-09-02T10:00", "--state-dir", state_dir)
    assert code == 0
    assert "reunion_under_5" in out


def test_simulate_tick_escalates(run, state_dir):
    run("--simulate", "unplug", "--now", "2026-09-02T10:00", "--state-dir", state_dir)
    code, out, _ = run("--simulate", "tick", "--now", "2026-09-02T10:05", "--state-dir", state_dir)
    assert code == 0 and "nothing due" in out and "unplugged for 5 minutes" in out
    code, out, _ = run("--simulate", "tick", "--now", "2026-09-02T10:12", "--state-dir", state_dir)
    assert code == 0 and "nothing due" in out  # 10 minutes is not a threshold
    code, out, _ = run("--simulate", "tick", "--now", "2026-09-02T10:31", "--state-dir", state_dir)
    assert code == 0 and "-> medium/escalation_30" in out and "escalations fired [30]" in out
    code, out, _ = run("--simulate", "tick", "--now", "2026-09-02T10:32", "--state-dir", state_dir)
    assert "nothing due" in out


def test_simulate_tick_while_plugged(run, state_dir):
    code, out, _ = run("--simulate", "tick", "--now", "2026-09-02T10:00", "--state-dir", state_dir)
    assert code == 0 and "nothing due" in out and "plugged in" in out


def test_simulate_rapid_sequence(run, state_dir):
    for i in range(3):
        run("--simulate", "unplug", "--now", f"2026-09-02T10:{i * 4:02d}", "--state-dir", state_dir)
        code, out, _ = run("--simulate", "plug", "--now", f"2026-09-02T10:{i * 4 + 2:02d}", "--state-dir", state_dir)
    code, out, _ = run("--simulate", "unplug", "--now", "2026-09-02T10:12", "--state-dir", state_dir, "--intensity", "intense")
    assert "-> intense/rapid_4" not in out
    assert "-> intense/rapid_3 (requested rapid_4)" in out
    assert "today=4 streak=4" in out


def test_simulate_seed_is_repeatable(run, tmp_path):
    outs = []
    for name in ("a", "b"):
        code, out, _ = run("--simulate", "unplug", "--now", "2026-09-02T15:00", "--state-dir", str(tmp_path / name), "--seed", "42")
        outs.append(out)
    assert outs[0] == outs[1]


def test_simulate_bad_now(run, state_dir):
    code, _, err = run("--simulate", "unplug", "--now", "yesterday", "--state-dir", state_dir)
    assert code == 2 and "bad --now" in err


def test_simulate_unknown_pack(run, state_dir):
    code, _, err = run("--simulate", "unplug", "--pack", "nope", "--state-dir", state_dir)
    assert code == 1 and "no pack file" in err


def test_simulate_uses_env_home_when_no_state_dir(run, tmp_path, monkeypatch):
    monkeypatch.setenv("CHARGERWIN_HOME", str(tmp_path))
    code, out, _ = run("--simulate", "unplug", "--now", "2026-09-02T15:00")
    assert code == 0
    assert (tmp_path / "state.json").exists()


def test_parse_now():
    aware = parse_now("2026-09-02T02:10:00+02:00")
    assert aware.utcoffset().total_seconds() == 7200
    naive = parse_now("2026-09-02T02:10")
    assert naive.tzinfo is not None and naive.hour == 2
    assert parse_now(None).tzinfo is not None


def test_validate_with_no_packs_available(run, tmp_path, monkeypatch):
    monkeypatch.setattr("chargerwin.cli.packs_dir", lambda: tmp_path / "empty")
    monkeypatch.setattr("chargerwin.packs.packs_dir", lambda: tmp_path / "empty")
    code, out, _ = run("--validate")
    assert code == 1 and "no packs found" in out


def test_module_entry_point_runs():
    import subprocess
    import sys

    result = subprocess.run([sys.executable, "-m", "chargerwin", "--validate"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


# ----- step 5: audio and tray -------------------------------------------


def test_warm_renders_into_an_engine_keyed_directory(run, state_dir, tmp_path):
    code, out, _ = run("--warm", "--engine", "fake", "--state-dir", state_dir)
    assert code == 0 and "rendered 27 line(s)" in out
    assert "/fake" in out or "\\fake" in out
    code, out, _ = run("--warm", "--engine", "fake", "--state-dir", state_dir)
    assert code == 0 and "rendered 0 line(s)" in out


def test_warm_force_re_renders(run, state_dir):
    run("--warm", "--engine", "fake", "--state-dir", state_dir)
    code, out, _ = run("--warm", "--engine", "fake", "--force", "--state-dir", state_dir)
    assert code == 0 and "rendered 27 line(s)" in out


def test_warm_reports_a_missing_engine_instead_of_claiming_success(run, state_dir):
    """pyttsx3 is not installed in the dev environment. Reporting 'rendered 0'
    and exiting 0 would be the same silent failure that shipped escalation_10."""
    code, out, _ = run("--warm", "--engine", "sapi", "--state-dir", state_dir)
    assert code == 1
    assert "unavailable" in out and "--engine fake" in out


def test_simulate_play_uses_the_cache(run, state_dir):
    run("--warm", "--engine", "fake", "--state-dir", state_dir)
    code, out, _ = run(
        "--simulate", "unplug", "--engine", "fake", "--play", "--seed", "1", "--state-dir", state_dir
    )
    assert code == 0 and "[audio] played" in out and ".wav" in out


def test_simulate_play_on_an_empty_cache_says_so(run, state_dir):
    code, out, _ = run(
        "--simulate", "unplug", "--engine", "fake", "--play", "--seed", "1", "--state-dir", state_dir
    )
    assert code == 0 and "no cached wav" in out and "--warm" in out


def test_tray_reports_a_missing_dependency(run, state_dir):
    """pystray does not install here; the failure must be legible."""
    code, out, _ = run("--tray", "--engine", "fake", "--state-dir", state_dir)
    assert code == 1 and "tray unavailable" in out

