"""Command line entry point.

    chargerwin --simulate unplug|plug|tick [--now ISO] [--state-dir DIR]
               [--pack ID|PATH] [--intensity mild|medium|intense]
               [--battery N] [--seed N] [-v]
    chargerwin --validate [PACK ...]

Running with no action prints usage and exits 2: the tray app is build
step 5 and does not exist yet.
"""

from __future__ import annotations

import argparse
import logging
import random
import sys
from datetime import datetime
from pathlib import Path

from . import __version__
from .groups import DEFAULT_INTENSITY, INTENSITIES
from .packs import find_pack, list_packs, load_pack, packs_dir
from .pipeline import react
from .power import FakePowerSource
from .state import State, StateStore, default_state_dir
from .timeofday import time_of_day
from .validate import PackError
from .variables import humanize_seconds

DEFAULT_PACK = "field_notes"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chargerwin",
        description="Speaks a line when the charger is plugged or unplugged.",
    )
    parser.add_argument("--version", action="version", version=f"chargerwin {__version__}")
    action = parser.add_argument_group("actions")
    action.add_argument(
        "--simulate",
        choices=("plug", "unplug", "tick"),
        help="drive the pipeline with a fake power source and print the line. "
        "'tick' fires whatever escalation is due for the current absence.",
    )
    action.add_argument(
        "--tray",
        action="store_true",
        help="run the tray app (Windows; elsewhere the icon needs a display and audio stays silent)",
    )
    action.add_argument(
        "--watch",
        action="store_true",
        help="listen for real power events and print them, without a tray icon. Windows only; "
        "the quickest way to check the power hook on its own.",
    )
    action.add_argument(
        "--warm",
        action="store_true",
        help="render missing audio into the cache and exit. Safe to re-run: only missing lines cost anything.",
    )
    action.add_argument(
        "--validate",
        nargs="*",
        metavar="PACK",
        help="validate pack files (ids or paths); with no argument, every pack in the packs directory",
    )
    sim = parser.add_argument_group("simulation options")
    sim.add_argument("--now", help="clock override, ISO 8601 (naive values are local time)")
    sim.add_argument("--state-dir", help="directory holding state.json (default: platform data dir)")
    sim.add_argument("--pack", default=DEFAULT_PACK, help=f"pack id or path (default: {DEFAULT_PACK})")
    sim.add_argument("--intensity", choices=INTENSITIES, default=DEFAULT_INTENSITY)
    sim.add_argument("--battery", type=int, help="battery percent reported by the fake source (default 50)")
    sim.add_argument("--seed", type=int, help="seed the random draw for a repeatable line")
    audio = parser.add_argument_group("audio options")
    audio.add_argument("--cache-dir", help="directory holding rendered wavs (default: <state-dir>/audio-cache)")
    audio.add_argument(
        "--engine",
        default=None,
        help="tts engine used to render: 'sapi' (Windows default) or 'fake' (silent wavs, for dev)",
    )
    audio.add_argument("--force", action="store_true", help="with --warm, re-render lines that are already cached")
    sim.add_argument(
        "--tick-seconds",
        type=float,
        default=60.0,
        help="how often to check for a due escalation while unplugged (default: 60)",
    )
    audio.add_argument(
        "--play",
        action="store_true",
        help="with --simulate, also play the cached wav for the chosen line (silent if not yet rendered)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    return parser


def parse_now(value: str | None) -> datetime:
    if value is None:
        return datetime.now().astimezone()
    dt = datetime.fromisoformat(value)
    return dt.astimezone() if dt.tzinfo is None else dt


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    if args.validate is not None:
        return run_validate(args.validate)
    if args.warm:
        return run_warm(args)
    if args.watch:
        return run_watch(args)
    if args.tray:
        return run_tray(args)
    if args.simulate:
        return run_simulate(args)
    parser.print_usage()
    print("Nothing to do. Try --tray, --warm, --simulate or --validate.")
    return 2


def build_app(args):
    """An App configured from the CLI flags, overriding saved settings."""
    from .app import App

    app = App(
        state_dir=Path(args.state_dir) if args.state_dir else None,
        cache_dir=Path(args.cache_dir) if args.cache_dir else None,
        pack=find_pack(args.pack),
        rng=random.Random(args.seed) if args.seed is not None else None,
    )
    # Flags win over settings.json for this run, without persisting.
    app.settings.intensity = args.intensity
    if args.engine:
        app.settings.tts_engine = args.engine
        from .voice import VoiceCache, renderer_for

        app.speaker.cache = VoiceCache(app.cache_dir, app.pack.id, renderer_for(app.pack, args.engine))
    return app


def run_warm(args) -> int:
    app = build_app(args)
    cache = app.speaker.cache
    print(f"rendering {app.pack.id} at {app.settings.intensity} with '{cache.renderer.key}' into {cache.root}")
    try:
        count = cache.warm(app.pack, [app.settings.intensity], force=args.force)
    except ImportError as exc:
        print(f"engine '{cache.renderer.key}' is unavailable here: {exc}")
        print("Use --engine fake for a silent cache, or run this on Windows for SAPI.")
        return 1
    print(f"rendered {count} line(s); cache now holds {len(list(cache.root.glob('*.wav')))}")
    return 0


def run_watch(args) -> int:
    """The power hook with no tray: the smallest thing that proves step 6."""
    import time

    app = build_app(args)

    def report(reaction, event_name: str) -> None:
        now = parse_now(None)
        stamp = now.strftime("%H:%M:%S")
        if reaction is None:
            print(f"[{stamp}] {event_name}: no line (silent)")
        else:
            sel = reaction.selection
            print(f"[{stamp}] {event_name} -> {sel.intensity}/{sel.group} [{sel.line.id}]")
            print(f"          {reaction.text}")
        print(f"          {describe(app.state, now)}")

    app.on_reaction = report
    if not app.start_power_watch(interval=args.tick_seconds):
        print("power hook unavailable here (Windows only).", file=sys.stderr)
        return 1
    print(f"listening for power events; ticking every {args.tick_seconds:g}s. Ctrl-C to quit.")
    print(f"[start] {describe(app.state, parse_now(None))}")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        app.stop_power_watch()
        print("\nstopped.")
    return 0


def run_tray(args) -> int:
    app = build_app(args)
    missing = app.speaker.cache.warm(app.pack, [app.settings.intensity])
    if missing:
        print(f"rendered {missing} missing line(s)")
    if app.start_power_watch(interval=args.tick_seconds):
        print("power hook listening.")
    else:
        print("power hook unavailable; the tray still works but nothing fires automatically.")
    print(f"chargerwin tray: {app.pack.id} at {app.settings.intensity}. Ctrl-C to quit.")
    try:
        app.tray.run()
    except KeyboardInterrupt:
        app.quit()
    except Exception as exc:
        app.stop_power_watch()
        # Not just ImportError: pystray picks a backend at import time, so on a
        # machine where it is installed but there is no display it raises the
        # backend's own error (Xlib.error.DisplayNameError on Linux). Catching
        # ImportError alone let that reach the user as a raw traceback.
        print(f"tray unavailable: {type(exc).__name__}: {exc}", file=sys.stderr)
        print("Needs pystray, Pillow and a desktop session. Use --simulate to test the pipeline.")
        return 1
    return 0


def run_validate(targets: list[str]) -> int:
    paths = [Path(t) if t.endswith(".json") else packs_dir() / f"{t}.json" for t in targets] or list_packs()
    if not paths:
        print(f"no packs found in {packs_dir()}")
        return 1
    failures = 0
    for path in paths:
        try:
            pack = load_pack(path)
        except (PackError, OSError) as exc:
            failures += 1
            print(f"FAIL {path}\n{exc}")
            continue
        print(f"OK   {path} ({pack.id}: {pack.line_count()} lines)")
    return 1 if failures else 0


def run_simulate(args: argparse.Namespace) -> int:
    try:
        now = parse_now(args.now)
    except ValueError as exc:
        print(f"bad --now value: {exc}", file=sys.stderr)
        return 2
    try:
        pack = find_pack(args.pack)
    except PackError as exc:
        print(exc, file=sys.stderr)
        return 1

    store = StateStore(Path(args.state_dir) if args.state_dir else None)
    state = store.load()
    source = FakePowerSource(battery_percent=args.battery if args.battery is not None else 50)
    rng = random.Random(args.seed)

    if args.simulate == "tick":
        event = state.due_escalation(now)
        if event is None:
            store.save(state)
            print(f"[tick] nothing due: {describe(state, now)}")
            return 0
    else:
        plugged = args.simulate == "plug"
        source.set(plugged=plugged)
        if state.connected is None:
            # First ever run: assume we were in the opposite state so the
            # simulated event actually happens.
            state.resync(not plugged, now)
        event = state.observe(source.status().plugged, now)
        if event is None:
            store.save(state)
            print(f"[{args.simulate}] no change, already {'plugged in' if plugged else 'unplugged'}; nothing to say")
            return 0

    reaction = react(event, state, pack, args.intensity, now, rng, source.status().battery_percent)
    store.save(state)
    stamp = now.strftime("%Y-%m-%d %H:%M")
    if reaction is None:
        print(f"[{args.simulate}] {stamp} {time_of_day(now)} -> silence (no line for this event at {args.intensity})")
        return 0
    sel = reaction.selection
    requested = "" if sel.requested_group == sel.group else f" (requested {sel.requested_group})"
    print(f"[{args.simulate}] {stamp} {time_of_day(now)} -> {sel.intensity}/{sel.group}{requested} [{sel.line.id}]")
    print(reaction.text)
    if args.play:
        print(f"[audio] {play_reaction(args, pack, reaction)}")
    print(f"[state] {describe(state, now)}")
    return 0


def play_reaction(args, pack, reaction) -> str:
    """Play the cached wav for a simulated line. Reports what happened rather
    than raising: --simulate exists to show the line, and a missing cache
    should not fail the run."""
    from .audio import select_player
    from .voice import VoiceCache, renderer_for

    cache_dir = Path(args.cache_dir) if args.cache_dir else default_state_dir() / "audio-cache"
    if args.state_dir and not args.cache_dir:
        cache_dir = Path(args.state_dir) / "audio-cache"
    cache = VoiceCache(cache_dir, pack.id, renderer_for(pack, args.engine or "sapi"))
    path = cache.lookup(reaction.selection.line.id)
    if path is None:
        return f"no cached wav for {reaction.selection.line.id}; run --warm first"
    player = select_player()
    player.play(path)
    return f"played {path} via {type(player).__name__}"


def describe(state: State, now: datetime) -> str:
    if state.connected is False:
        status = f"unplugged for {humanize_seconds(state.absence_seconds(now))}, escalations fired {state.escalations_fired}"
    else:
        status = "plugged in"
    return f"today={state.today_count} streak={state.toggle_streak} week={state.weekly_count} total={state.total_count}, {status}"
