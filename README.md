# chargerwin

Windows tray app that speaks a short line when the AC adapter is plugged or
unplugged, escalating the longer you stay unplugged and the more times you
toggle the cable in a day. A Windows take on the idea behind the macOS app
Charger Breakup, with its own packs and lines.

Status: core pipeline, tray icon, audio playback and a pre-rendered speech
cache are built. The core is verified on Windows; the tray and real SAPI
rendering are not yet. The Windows power hook (step 6) is still to come, so
nothing fires automatically yet -- drive it with `--simulate`. See
`CLAUDE.md` for the plan.

## Dev loop (no hardware needed)

```
pip install -r requirements-dev.txt
pytest
python -m chargerwin --validate
python -m chargerwin --simulate unplug --now 2026-09-02T02:10 --state-dir /tmp/cw
python -m chargerwin --simulate tick   --now 2026-09-02T02:41 --state-dir /tmp/cw
python -m chargerwin --simulate plug   --now 2026-09-02T03:30 --state-dir /tmp/cw
```

`--simulate` drives the full pipeline with a fake power source and prints the
line that would be spoken. `--now` sets the clock, `--seed` makes the draw
deterministic, `--state-dir` keeps throwaway runs out of your real counters.

## Audio

Lines are spoken from wavs rendered ahead of time, never synthesized when
the cable moves: a delay after unplugging kills the joke. Render first, then
play.

```
python -m chargerwin --warm                 # render missing lines (Windows SAPI)
python -m chargerwin --warm --engine fake   # silent wavs, for Linux dev
python -m chargerwin --simulate unplug --play
python -m chargerwin --tray                 # tray icon; Windows
```

The cache lives at `<state-dir>/audio-cache/<pack>/<engine>/<line-id>.wav`.
The engine is part of the path, so switching to a better voice later is a
cache miss rather than stale audio. SAPI is the placeholder: it is free,
offline and already a dependency.
