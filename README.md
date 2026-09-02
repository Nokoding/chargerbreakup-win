# chargerwin

Windows tray app that speaks a short line when the AC adapter is plugged or
unplugged, escalating the longer you stay unplugged and the more times you
toggle the cable in a day. A Windows take on the idea behind the macOS app
Charger Breakup, with its own packs and lines.

Status: core pipeline (state machine, line selector, pack validator, CLI
simulation) built and tested on Linux. Tray icon, audio, and the Windows
power hook are not built yet. See `CLAUDE.md` for the plan.

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
