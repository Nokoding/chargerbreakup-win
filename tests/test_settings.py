from __future__ import annotations

import json

from chargerwin.settings import DEFAULT_PACK, Settings, SettingsStore


def test_defaults_when_no_file(tmp_path):
    assert SettingsStore(tmp_path).load() == Settings()


def test_roundtrip(tmp_path):
    store = SettingsStore(tmp_path)
    store.save(Settings(intensity="intense", muted=True, pack_id="other"))
    loaded = store.load()
    assert (loaded.intensity, loaded.muted, loaded.pack_id) == ("intense", True, "other")


def test_corrupt_file_falls_back_instead_of_crashing(tmp_path):
    """The app must still start and still talk with a mangled settings file."""
    (tmp_path / "settings.json").write_text("{ not json")
    assert SettingsStore(tmp_path).load() == Settings()


def test_unknown_intensity_is_clamped(tmp_path):
    (tmp_path / "settings.json").write_text(json.dumps({"intensity": "nuclear"}))
    assert SettingsStore(tmp_path).load().intensity == Settings().intensity


def test_unknown_keys_are_ignored(tmp_path):
    """Settings are hand-editable, and a stale key from an older build must
    not become an unexpected keyword argument."""
    (tmp_path / "settings.json").write_text(json.dumps({"intensity": "mild", "legacy_option": 1}))
    assert SettingsStore(tmp_path).load().intensity == "mild"


def test_empty_pack_id_falls_back(tmp_path):
    (tmp_path / "settings.json").write_text(json.dumps({"pack_id": ""}))
    assert SettingsStore(tmp_path).load().pack_id == DEFAULT_PACK


def test_save_is_atomic_and_leaves_no_temp_file(tmp_path):
    SettingsStore(tmp_path).save(Settings())
    assert [p.name for p in tmp_path.iterdir()] == ["settings.json"]


def test_save_creates_the_directory(tmp_path):
    store = SettingsStore(tmp_path / "nested" / "deeper")
    store.save(Settings())
    assert store.load() == Settings()
