from __future__ import annotations

from pathlib import Path

from chargerwin.audio import NullPlayer, select_player


def test_null_player_records_instead_of_sounding(tmp_path):
    player = NullPlayer()
    wav = tmp_path / "a.wav"
    player.play(wav)
    assert player.played == [wav]


def test_select_player_is_null_off_windows():
    assert isinstance(select_player("linux"), NullPlayer)


def test_select_player_falls_back_when_winsound_is_missing():
    """On this Linux box the Windows branch is taken and must degrade to
    silence rather than raise: a laptop with a broken audio stack should
    still run the tray."""
    assert isinstance(select_player("win32"), NullPlayer)


def test_winsound_player_ignores_a_missing_file(monkeypatch):
    """Playback must not raise on a cache miss that slipped through."""
    import chargerwin.audio as audio

    calls: list = []

    class FakeWinsound:
        SND_FILENAME = 1
        SND_ASYNC = 2

        def PlaySound(self, path, flags):
            calls.append((path, flags))

    player = object.__new__(audio.WinsoundPlayer)
    player._winsound = FakeWinsound()
    player.play(Path("/definitely/not/here.wav"))
    assert calls == []


def test_winsound_player_survives_a_runtime_error(tmp_path):
    import chargerwin.audio as audio

    class Exploding:
        SND_FILENAME = 1
        SND_ASYNC = 2

        def PlaySound(self, path, flags):
            raise RuntimeError("no audio device")

    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF")
    player = object.__new__(audio.WinsoundPlayer)
    player._winsound = Exploding()
    player.play(wav)  # must not raise
