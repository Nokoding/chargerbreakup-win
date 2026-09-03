from __future__ import annotations

import random

import pytest

from chargerwin.app import App, Speaker
from chargerwin.audio import NullPlayer
from chargerwin.packs import packs_dir
from chargerwin.pipeline import react
from chargerwin.state import State
from chargerwin.voice import FakeRenderer, VoiceCache
from conftest import at, make_pack


@pytest.fixture
def app(tmp_path, sample_pack):
    a = App(
        state_dir=tmp_path / "state",
        cache_dir=tmp_path / "cache",
        pack=sample_pack,
        player=NullPlayer(),
        rng=random.Random(7),
    )
    a.speaker.cache = VoiceCache(tmp_path / "cache", sample_pack.id, FakeRenderer())
    return a


def test_speaker_plays_the_cached_wav_for_the_chosen_line(tmp_path, sample_pack):
    cache = VoiceCache(tmp_path, sample_pack.id, FakeRenderer())
    cache.warm(sample_pack, ["medium"])
    player = NullPlayer()
    speaker = Speaker(cache, player)
    state = State(connected=True)
    event = state.observe(False, at(10))
    reaction = react(event, state, sample_pack, "medium", at(10), random.Random(1))
    played = speaker.speak(reaction)
    assert played is not None and played.name == f"{reaction.selection.line.id}.wav"
    assert player.played == [played]


def test_speaker_is_silent_when_muted(tmp_path, sample_pack):
    cache = VoiceCache(tmp_path, sample_pack.id, FakeRenderer())
    cache.warm(sample_pack, ["medium"])
    player = NullPlayer()
    speaker = Speaker(cache, player, muted=True)
    state = State(connected=True)
    reaction = react(state.observe(False, at(10)), state, sample_pack, "medium", at(10), random.Random(1))
    assert speaker.speak(reaction) is None and player.played == []


def test_speaker_handles_a_cache_miss_without_raising(tmp_path, sample_pack):
    """A miss must be silence, not a stall or a crash on the event path."""
    player = NullPlayer()
    speaker = Speaker(VoiceCache(tmp_path, sample_pack.id, FakeRenderer()), player)
    state = State(connected=True)
    reaction = react(state.observe(False, at(10)), state, sample_pack, "medium", at(10), random.Random(1))
    assert speaker.speak(reaction) is None and player.played == []


def test_speaker_ignores_a_silent_reaction(tmp_path, sample_pack):
    speaker = Speaker(VoiceCache(tmp_path, "x", FakeRenderer()), NullPlayer())
    assert speaker.speak(None) is None


def test_the_first_reading_adopts_silently(app):
    """Starting the app while already unplugged must not announce it."""
    app.warm_cache()
    assert app.on_power_status(plugged=False) is None
    assert app.speaker.player.played == []
    assert app.state.today_count == 0


def test_resync_adopts_without_counting(app):
    app.resync(plugged=False)
    assert app.state.connected is False and app.state.today_count == 0


def test_app_speaks_on_unplug_and_persists_state(app):
    app.warm_cache()
    app.resync(plugged=True)
    reaction = app.on_power_status(plugged=False, battery_percent=42)
    assert reaction is not None
    assert app.speaker.player.played  # something reached playback
    assert app.state_store.load().today_count == 1


def test_app_says_nothing_when_the_status_has_not_changed(app):
    app.warm_cache()
    app.resync(plugged=True)
    app.on_power_status(plugged=False)
    app.speaker.player.played.clear()
    assert app.on_power_status(plugged=False) is None
    assert app.speaker.player.played == []


def test_set_intensity_persists(app):
    app.set_intensity("intense")
    assert app.settings_store.load().intensity == "intense"


def test_toggle_mute_persists_and_reaches_the_speaker(app):
    app.toggle_mute()
    assert app.settings.muted is True
    assert app.speaker.muted is True
    assert app.settings_store.load().muted is True
    app.toggle_mute()
    assert app.speaker.muted is False


def test_say_something_does_not_move_the_counters(app):
    """Asking for a demo line is not a disconnect. It does still record the
    line as last played, which is wanted: the demo should not immediately
    repeat the line a real event just used."""
    app.warm_cache()
    app.resync(plugged=True)
    counters = lambda: (app.state.today_count, app.state.total_count, app.state.connected)
    before = counters()
    assert app.say_something() is not None
    assert counters() == before


def test_menu_reflects_live_state(app):
    app.resync(plugged=True)
    app.on_power_status(plugged=False)
    labels = [i.label for i in app.menu()]
    assert labels[0].startswith("Unplugged")


def test_warm_cache_only_renders_the_active_intensity(app):
    """Rendering all three at startup is three times the work for lines the
    user will not hear until they change intensity."""
    rendered = app.warm_cache()
    ids = {line.id for group in app.pack.intensities["medium"].values() for line in group}
    assert rendered == len(ids)


def test_app_defaults_to_a_real_player_off_windows(tmp_path, sample_pack):
    a = App(state_dir=tmp_path, cache_dir=tmp_path / "c", pack=sample_pack)
    assert isinstance(a.speaker.player, NullPlayer)
