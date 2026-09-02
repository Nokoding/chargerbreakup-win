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
from .state import State, StateStore
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
    if args.simulate:
        return run_simulate(args)
    parser.print_usage()
    print("The tray app is not built yet (build step 5). Use --simulate or --validate.")
    return 2


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
    print(f"[state] {describe(state, now)}")
    return 0


def describe(state: State, now: datetime) -> str:
    if state.connected is False:
        status = f"unplugged for {humanize_seconds(state.absence_seconds(now))}, escalations fired {state.escalations_fired}"
    else:
        status = "plugged in"
    return f"today={state.today_count} streak={state.toggle_streak} week={state.weekly_count} total={state.total_count}, {status}"
