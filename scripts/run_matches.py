"""Play N local games of Citadel against the built-in AI and print a win/loss summary.

Games always run with realtime=False. Run from anywhere; paths resolve to the repo root.

Examples:
    poetry run python scripts/run_matches.py --games 10 --difficulty Hard --race Terran --map PylonAIE_v4
    poetry run python scripts/run_matches.py --map all --games 1 --difficulty VeryHard --build Rush
    poetry run python scripts/run_matches.py --map all --total 10 --race Terran Zerg Protoss Random
    poetry run python scripts/run_matches.py --opener B_PvZ --race Zerg --map PylonAIE_v4 --time-limit 420
    poetry run python scripts/run_matches.py --opponent cannon_rush --map all --total 10

`--opponent` plays one of the scripted cheese bots in scripts/test_bots/ instead of the built-in
AI (M2 acceptance: >= 8/10 wins against each).

M3 columns: `scouts` is scouting tasks lost before 4:00 / tasks given (Telemetry scout records);
`flag` (with --opponent) is the M3 "correct flag" check (scripts/m3_checks.py): the bot's expected
threat raised by its deadline and no threat outside its allowed list.

M4 columns: `engage` is launches/retreats/recalls of the main attack (§4.5.2); `value` is army
value lost/killed (§8); `step` is mean/p99/max step ms (§6). The summary ends with the M4 line:
wins per opponent race against the built-in AI (user decision: >= 7/10 VeryHard for each race).
"""

import argparse
import asyncio
import os
import random
import statistics
import sys
import time
import traceback
from collections import Counter
from datetime import datetime
from itertools import cycle, islice
from pathlib import Path
from typing import List, Optional

import yaml

ROOT: Path = Path(__file__).resolve().parent.parent
# run.py resolves config.yml and the ares-sc2 import paths relative to the working directory
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

import run  # noqa: E402  (also puts ares-sc2 on sys.path)
from sc2 import maps  # noqa: E402
from sc2.data import AIBuild, Difficulty, Race, Result  # noqa: E402
from sc2.main import _host_game, _join_game, run_game  # noqa: E402
from sc2.portconfig import Portconfig  # noqa: E402
from sc2.player import Bot, Computer  # noqa: E402

from bot.constants import (  # noqa: E402
    LADDER_TIE_GAME_SECONDS,
    M1_PROBES_AT_6_MIN,
    M3_FLAG_RATE,
    M3_SCOUT_SAFE_RATE,
    SCOUT_LOSS_CHECK_S,
)
from bot.main import CitadelBot  # noqa: E402
from scripts.m3_checks import flag_check  # noqa: E402
from scripts.test_bots import TEST_BOTS  # noqa: E402

M2_WIN_RATE: float = 0.8  # M2 acceptance: >= 8/10 against each cheese bot
M4_WIN_RATE: float = 0.7  # M4 acceptance (user decision): >= 7/10 VeryHard wins for each race

CRASH: str = "Crash"
BUILDS_FILE: Path = ROOT / "protoss_builds.yml"
PROBES_AT_S: int = 360  # the "probes by 6:00" check


class TrackedCitadelBot(CitadelBot):
    """CitadelBot with bookkeeping for this script; bot behaviour is unchanged.

    - python-sc2 turns an exception in `on_start` into a plain Defeat, so record it here.
      Exceptions in `on_step` propagate out of `run_game` and are caught by the caller.
    - `forced_opener` (test only) narrows every `BuildChoices` list in protoss_builds.yml to
      one build after ares has loaded the file, so ares's own selection picks it. Those games
      don't write ./data, so they don't change later opener selection.
    """

    start_error: Optional[str] = None

    def __init__(self, forced_opener: Optional[str] = None):
        super().__init__()
        self.forced_opener = forced_opener

    async def on_before_start(self) -> None:
        await super().on_before_start()
        if self.forced_opener is not None:
            for choice in self.config["BuildChoices"].values():
                choice["Cycle"] = [self.forced_opener]
            self.config["UseData"] = False

    async def on_start(self) -> None:
        try:
            await super().on_start()
        except Exception as e:
            self.start_error = repr(e)
            raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Play Citadel vs the built-in AI (realtime=False) and summarise results."
    )
    parser.add_argument("--games", type=int, default=1, help="games per map (default 1)")
    parser.add_argument(
        "--total",
        type=int,
        default=None,
        help="play exactly this many games, cycling through the --map list (overrides --games)",
    )
    parser.add_argument(
        "--difficulty",
        choices=[d.name for d in Difficulty],
        default=Difficulty.Medium.name,
        help="built-in AI difficulty (default Medium)",
    )
    parser.add_argument(
        "--race",
        nargs="+",
        choices=[r.name for r in Race if r != Race.NoRace],
        default=None,
        help="opponent race; several values are cycled game by game "
        "(default Random for the built-in AI, the bot's own races for --opponent)",
    )
    parser.add_argument(
        "--opponent",
        choices=sorted(TEST_BOTS),
        default=None,
        help="play this scripted cheese bot (scripts/test_bots/) instead of the built-in AI",
    )
    parser.add_argument(
        "--variant", default=None, help="--opponent variant (default: random per game where the bot has variants)"
    )
    parser.add_argument("--seed", type=int, default=None, help="seed for the --opponent bot's random choices")
    parser.add_argument(
        "--start",
        type=int,
        default=1,
        help="first game number to play (default 1); games keep their map and seed, so a batch cut "
        "short can be finished with the same arguments and --start",
    )
    parser.add_argument(
        "--build",
        choices=[b.name for b in AIBuild],
        default=AIBuild.RandomBuild.name,
        help="built-in AI build (default RandomBuild)",
    )
    parser.add_argument(
        "--map",
        nargs="+",
        default=["random"],
        help="one or more map names, `all` for every pool map, "
        "or `random` for a random pool map each game (default random)",
    )
    parser.add_argument(
        "--opener",
        default=None,
        help="force this protoss_builds.yml build for every game (test only)",
    )
    parser.add_argument(
        "--time-limit",
        type=int,
        default=LADDER_TIE_GAME_SECONDS,
        help=f"game seconds before a game is declared a Tie "
        f"(default {LADDER_TIE_GAME_SECONDS}, the ladder's 60:00 rule)",
    )
    parser.add_argument(
        "--replays", type=Path, default=None, help="folder to save a replay of every game"
    )
    args = parser.parse_args()
    if args.games < 1:
        parser.error("--games must be at least 1")
    if args.total is not None and args.total < 1:
        parser.error("--total must be at least 1")
    if args.race is None:
        args.race = [r.name for r in TEST_BOTS[args.opponent][1]] if args.opponent else [Race.Random.name]
    if args.opener is not None:
        builds = yaml.safe_load(BUILDS_FILE.read_text())["Builds"]
        if args.opener not in builds:
            parser.error(f"--opener must be one of: {', '.join(builds)}")
    return args


def run_bot_game(map_name: str, players: list, replay: Optional[str], time_limit: int) -> tuple[Result, Optional[str]]:
    """Bot vs bot. python-sc2's `run_game` turns an exception on either side into a bare
    AssertionError, so host and join here to keep both. Returns Citadel's result and the
    opponent bot's error, if any; Citadel's own exception is raised."""
    portconfig = Portconfig()

    async def host_and_join():
        return await asyncio.gather(
            _host_game(
                maps.get(map_name), players, realtime=False, portconfig=portconfig,
                save_replay_as=replay, game_time_limit=time_limit,
            ),
            _join_game(players, realtime=False, portconfig=portconfig, game_time_limit=time_limit),
            return_exceptions=True,
        )

    ours, theirs = asyncio.run(host_and_join())
    if isinstance(ours, BaseException):
        raise ours
    return ours, (repr(theirs) if isinstance(theirs, BaseException) else None)


def build_schedule(map_args: List[str], games: int, total: Optional[int]) -> List[str]:
    """Map name for every game to play, in order."""
    count = total if total is not None else games
    if map_args == ["random"]:
        return [random.choice(run.POOL_MAPS) for _ in range(count)]
    names: List[str] = []
    for name in map_args:
        names.extend(run.POOL_MAPS if name == "all" else [name])
    for name in names:
        maps.get(name)  # fail fast (KeyError) if a map file is missing
    if total is not None:
        return list(islice(cycle(names), total))
    return [name for name in names for _ in range(games)]


def format_game_time(seconds: Optional[float]) -> str:
    if seconds is None:
        return "--:--"
    return f"{int(seconds // 60):02d}:{int(seconds % 60):02d}"


def cell(value) -> str:
    return "-" if value is None else str(value)


def format_row(r: dict) -> str:
    """One game's summary row (also printed as `ROW ...` right after the game)."""
    line = (
        f"{r['i']:>3}  {r['map']:<18} {r['race']:<8} {r['opener']:<15} {cell(r['wall_ok']):<7} "
        f"{cell(r['probes6']):>8} {cell(r['bases6']):>7}  {r['outcome']:<8} "
        f"{format_game_time(r['game_s']):>6} {r['real_s']:>6.0f}s"
    )
    if r["variant"]:
        line += f"  variant={r['variant']}"
    if r["engage"] is not None:
        line += f"  engage={r['engage']} value={r['value']} step={r['step']}"
    if r["scout_tasks"] is not None:
        line += f"  scouts={r['scouts_lost']}/{r['scout_tasks']}"
    if r["flag_ok"] is not None:
        line += f"  flag={'ok' if r['flag_ok'] else 'MISS'} ({r['flag_why']})"
    line += f"  flags={r['flags'] or '-'}"
    return line + (f"  {r['error']}" if r["error"] else "")


def main() -> int:
    args = parse_args()
    bot_name, bot_race = run.load_bot_config()
    difficulty = Difficulty[args.difficulty]
    ai_build = AIBuild[args.build]
    schedule = build_schedule(args.map, args.games, args.total)
    races = list(islice(cycle(Race[r] for r in args.race), len(schedule)))
    if args.replays is not None:
        args.replays.mkdir(parents=True, exist_ok=True)
    if args.opponent:
        opponent = f"{args.opponent} ({'/'.join(args.race)})"
    else:
        opponent = f"{'/'.join(args.race)} {difficulty.name} {ai_build.name}"

    rows = []
    for i, (map_name, opp_race) in enumerate(zip(schedule, races), start=1):
        if i < args.start:
            continue
        if args.opponent:
            bot_class = TEST_BOTS[args.opponent][0]
            seed = None if args.seed is None else args.seed + i
            opponent_bot = bot_class(seed=seed, variant=args.variant)
            opponent_player = Bot(opp_race, opponent_bot, args.opponent)
            label = f"{args.opponent} ({opp_race.name})"
        else:
            opponent_bot = None
            opponent_player = Computer(opp_race, difficulty, ai_build=ai_build)
            label = f"{opp_race.name} {difficulty.name} {ai_build.name}"
        print(f"\n=== Game {i}/{len(schedule)}: {bot_name} vs {label} on {map_name} ===")
        bot = TrackedCitadelBot(forced_opener=args.opener)
        replay: Optional[str] = None
        if args.replays is not None:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            replay = str(
                (args.replays / f"{stamp}_{map_name}_{opp_race.name}_{args.opponent or difficulty.name}_{i}.SC2Replay").resolve()
            )
        started = time.perf_counter()
        error: Optional[str] = None
        try:
            if args.opponent:
                result, opponent_error = run_bot_game(
                    map_name, [Bot(bot_race, bot, bot_name), opponent_player], replay, args.time_limit
                )
                if opponent_error is not None:
                    error = f"opponent bot: {opponent_error}"
            else:
                result = run_game(
                    maps.get(map_name),
                    [Bot(bot_race, bot, bot_name), opponent_player],
                    realtime=False,
                    save_replay_as=replay,
                    game_time_limit=args.time_limit,
                )
            outcome = result.name if isinstance(result, Result) else str(result)
        except Exception as e:
            outcome, error = CRASH, repr(e)
            print(traceback.format_exc())
        if bot.start_error is not None:
            outcome, error = CRASH, f"on_start: {bot.start_error}"
        # `state` only exists once the first observation arrived
        game_seconds = bot.time if getattr(bot, "state", None) is not None else None
        telemetry = getattr(bot, "telemetry", None)
        snap = telemetry.snapshots.get(PROBES_AT_S) if telemetry is not None else None
        flag_store = getattr(bot, "flags", None)
        flags = (
            ",".join(f"{r.threat.name}@{format_game_time(r.raised_at)}" for r in flag_store.history)
            if flag_store is not None
            else ""
        )
        scouts_lost = scout_tasks = None
        task_outcomes: Counter = Counter()
        if telemetry is not None:
            scouts_lost = len(telemetry.scouts_lost_before(SCOUT_LOSS_CHECK_S))
            scout_tasks = len(telemetry.scouts)
            task_outcomes = Counter((r.task, r.outcome or "active") for r in telemetry.scouts)
        army = getattr(bot, "army", None)
        engage = None
        if army is not None:
            actions = Counter(action for _, action, _, _ in army.decisions)
            engage = f"{actions['launch']}/{actions['retreat']}/{actions['recall']}"
        value = step = None
        if telemetry is not None:
            value = f"{telemetry.army_value_lost / 1000:.1f}k/{telemetry.army_value_killed / 1000:.1f}k"
            mean = telemetry.step_total_ms / telemetry.step_count if telemetry.step_count else 0.0
            step = f"{mean:.1f}/{telemetry.step_p99_ms():.0f}/{telemetry.step_max_ms:.0f}"
        flag_ok = flag_why = None
        if args.opponent and flag_store is not None:
            flag_ok, flag_why = flag_check(args.opponent, [(r.threat.name, r.raised_at) for r in flag_store.history])
        rows.append(
            {
                "i": i,
                "map": map_name,
                "race": opp_race.name,
                "opener": bot.opener or "-",
                "wall_ok": getattr(bot, "wall_ok", None),
                "probes6": snap["probes"] if snap else None,
                "bases6": snap["bases"] if snap else None,
                "outcome": outcome,
                "variant": getattr(opponent_bot, "variant", None),
                "flags": flags,
                "scouts_lost": scouts_lost,
                "scout_tasks": scout_tasks,
                "task_outcomes": task_outcomes,
                "engage": engage,
                "value": value,
                "step": step,
                "flag_ok": flag_ok,
                "flag_why": flag_why,
                "game_s": game_seconds,
                "real_s": time.perf_counter() - started,
                "error": error,
            }
        )
        print(f"ROW {format_row(rows[-1])}", flush=True)

    counts = Counter(row["outcome"] for row in rows)
    decided = counts[Result.Victory.name] + counts[Result.Defeat.name] + counts[Result.Tie.name]
    win_rate = 100 * counts[Result.Victory.name] / decided if decided else 0.0

    print(f"\n=== Summary: {bot_name} vs {opponent}, realtime=False ===")
    print(
        f"{'#':>3}  {'map':<18} {'vs':<8} {'opener':<15} {'wall_ok':<7} "
        f"{'probes@6':>8} {'bases@6':>7}  {'result':<8} {'game':>6} {'real':>7}"
    )
    for r in rows:
        print(format_row(r))
    print(
        f"Wins {counts[Result.Victory.name]}/{len(rows)}  Losses {counts[Result.Defeat.name]}  "
        f"Ties {counts[Result.Tie.name]}  Crashes {counts[CRASH]}  "
        f"Other {len(rows) - decided - counts[CRASH]}  |  "
        f"win rate {win_rate:.1f}% of {decided} decided games"
    )
    probes = [r["probes6"] for r in rows if r["probes6"] is not None]
    if probes:
        reached = sum(p >= M1_PROBES_AT_6_MIN for p in probes)
        print(
            f"probes@6:00 >= {M1_PROBES_AT_6_MIN}: {reached}/{len(rows)} games  "
            f"(min {min(probes)}, median {statistics.median(probes):g}, max {max(probes)}; "
            f"{len(rows) - len(probes)} games without a 6:00 snapshot)"
        )
    # M3: scouting tasks and "no scout lost before 4:00"
    outcomes: Counter = Counter()
    for r in rows:
        outcomes.update(r["task_outcomes"])
    if outcomes:
        tasks = sorted({task for task, _ in outcomes})
        print(
            "scout tasks (outcome counts over all games): "
            + "; ".join(
                f"{task} " + ",".join(f"{o}={n}" for (t, o), n in sorted(outcomes.items()) if t == task) for task in tasks
            )
        )
    measured = [r for r in rows if r["scouts_lost"] is not None and r["outcome"] != CRASH]
    if measured:
        safe = sum(r["scouts_lost"] == 0 for r in measured)
        needed = -(-M3_SCOUT_SAFE_RATE * len(rows) // 1)
        print(
            f"M3 no scout lost before {format_game_time(SCOUT_LOSS_CHECK_S)}: {safe}/{len(rows)} games "
            f"(>= {needed:.0f} needed): {'PASS' if safe >= needed else 'FAIL'}"
        )
    if args.opponent:
        correct = sum(bool(r["flag_ok"]) for r in rows)
        needed = -(-M3_FLAG_RATE * len(rows) // 1)
        print(
            f"M3 correct flag vs {args.opponent}: {correct}/{len(rows)} games "
            f"(>= {needed:.0f} needed): {'PASS' if correct >= needed else 'FAIL'}"
        )
        needed = -(-M2_WIN_RATE * len(rows) // 1)
        ok = counts[Result.Victory.name] >= needed and not counts[CRASH]
        print(
            f"M2 acceptance vs {args.opponent}: {counts[Result.Victory.name]}/{len(rows)} wins "
            f"(>= {needed:.0f} needed), {counts[CRASH]} crashes: {'PASS' if ok else 'FAIL'}"
        )
    if not args.opponent:
        # M4: wins per opponent race
        parts = []
        passed = True
        for race in dict.fromkeys(r["race"] for r in rows):
            games = [r for r in rows if r["race"] == race]
            wins = sum(r["outcome"] == Result.Victory.name for r in games)
            needed = -(-M4_WIN_RATE * len(games) // 1)
            passed &= wins >= needed
            parts.append(f"{race} {wins}/{len(games)} (>= {needed:.0f} needed)")
        print(f"M4 wins per race vs {difficulty.name}: {'; '.join(parts)}: {'PASS' if passed and not counts[CRASH] else 'FAIL'}")
    return 1 if counts[CRASH] else 0


if __name__ == "__main__":
    sys.exit(main())
