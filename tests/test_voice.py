from __future__ import annotations

import wave

import pytest

from chargerwin.voice import FakeRenderer, UnsafeLineId, VoiceCache, renderer_for
from conftest import make_pack


def cache(tmp_path, renderer=None):
    return VoiceCache(tmp_path, "test", renderer or FakeRenderer())


def test_warm_renders_every_line_once(tmp_path):
    pack = make_pack({"medium": {"immediate": 3, "reunion_under_5": 2}})
    c = cache(tmp_path)
    assert c.warm(pack, ["medium"]) == 5
    assert c.warm(pack, ["medium"]) == 0  # already cached
    assert c.warm(pack, ["medium"], force=True) == 5


def test_rendered_file_is_a_real_wav(tmp_path):
    pack = make_pack({"medium": {"immediate": 1}})
    c = cache(tmp_path)
    c.warm(pack, ["medium"])
    with wave.open(str(c.path_for("medium.immediate.1")), "rb") as w:
        assert w.getnchannels() == 1


def test_cache_path_is_keyed_by_engine(tmp_path):
    """The whole point of sapi being a placeholder is that it gets replaced.
    A cache keyed on line id alone would serve stale sapi audio forever."""

    class Other(FakeRenderer):
        key = "other"

    a = cache(tmp_path)
    b = cache(tmp_path, Other())
    assert a.path_for("x") != b.path_for("x")
    assert a.renderer.key in str(a.path_for("x"))


def test_lookup_never_renders(tmp_path):
    """The event path must not synthesize. A miss is silence, not a stall."""
    pack = make_pack({"medium": {"immediate": 1}})
    c = cache(tmp_path)
    assert c.lookup("medium.immediate.1") is None
    assert c.renderer.rendered == []
    c.warm(pack, ["medium"])
    assert c.lookup("medium.immediate.1") is not None


@pytest.mark.parametrize("bad", ["../escape", "a/b", "..", "with space", ""])
def test_unsafe_line_ids_are_rejected(tmp_path, bad):
    """Line ids become filenames and packs are data, so a traversal attempt
    must not write outside the cache."""
    with pytest.raises(UnsafeLineId):
        cache(tmp_path).path_for(bad)


def test_lookup_of_an_unsafe_id_is_silent_not_fatal(tmp_path):
    assert cache(tmp_path).lookup("../../etc/passwd") is None


def test_warm_skips_unsafe_ids_but_renders_the_rest(tmp_path):
    from chargerwin.packs import Line, Pack

    pack = Pack(
        id="test",
        name="t",
        intensities={"medium": {"immediate": [Line(id="ok.1", text="fine"), Line(id="../bad", text="no")]}},
    )
    assert cache(tmp_path).warm(pack, ["medium"]) == 1


def test_a_missing_engine_raises_rather_than_reporting_success(tmp_path):
    """Reporting 'rendered 0' for a missing engine is the silent-failure
    shape that shipped the escalation_10 bug."""

    class NoEngine(FakeRenderer):
        key = "absent"

        def render(self, text, out_path):
            raise ImportError("no module named 'pyttsx3'")

    pack = make_pack({"medium": {"immediate": 1}})
    with pytest.raises(ImportError):
        cache(tmp_path, NoEngine()).warm(pack, ["medium"])


def test_a_single_bad_line_does_not_abort_the_batch(tmp_path):
    class Flaky(FakeRenderer):
        key = "flaky"

        def render(self, text, out_path):
            if "2" in text:
                raise OSError("disk full")
            super().render(text, out_path)

    pack = make_pack({"medium": {"immediate": 3}})
    assert cache(tmp_path, Flaky()).warm(pack, ["medium"]) == 2


def test_renderer_for_reads_the_packs_voice_block(sample_pack):
    r = renderer_for(sample_pack, "sapi")
    assert (r.key, r.rate) == ("sapi", sample_pack.voice.rate)
    assert renderer_for(sample_pack, "fake").key == "fake"
    with pytest.raises(ValueError):
        renderer_for(sample_pack, "nope")


def test_sapi_renderer_does_not_import_pyttsx3_until_used(sample_pack):
    """Constructing the app on Linux must not explode; only rendering does."""
    r = renderer_for(sample_pack, "sapi")
    with pytest.raises(ImportError):
        r.render("hello", None)
