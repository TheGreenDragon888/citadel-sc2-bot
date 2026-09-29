"""Play N local games of Citadel against the built-in AI and print a win/loss summary.

Games always run with realtime=False. Run from anywhere; paths resolve to the repo root.

Examples:
    poetry run python scripts/run_matches.py --games 10 --difficulty Hard --race Terran --map PylonAIE_v4
    poetry run python scripts/run_matches.py --map all --games 1 --difficulty VeryHard --build Rush
    poetry run python scripts/run_matches.py --map all --total 10 --race Terran Zerg Protoss Random
    poetry run python scripts/run_matches.py --opener B_PvZ --race Zerg --map PylonAIE_v4 --time-limit 420
"""

import argparse
import os
import random
import statistics
import sys
import time
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
from sc2.main import run_game  # noqa: E402
from sc2.player import Bot, Computer  # noqa: E402

from bot.constants import LADDER_TIE_GAME_SECONDS, M1_PROBES_AT_6_MIN  # noqa: E402
from bot.main import CitadelBot  # noqa: E402

CRASH: str = "Crash"
BUILDS_FILE: Path = ROOT / "protoss_builds.yml"
PROBES_AT_S: int = 360  # the "probes by 6:00" check


class TrackedCitadelBot(CitadelBot):
    """CitadelBot with bookkeeping for this script; bot behaviour is unchanged.

    - python-sc2 turns an exception in `on_start` into a plain Defeat, so record it here.
      Exceptions in `on_step` propagate out of `run_game` and are caught by the caller.
    - `forced_opener` (test only) narrows every `BuildChoices` list in protoss_builds.yml to
      one build after ares has loaded the file, so ares's own selection picks it.
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
        default=[Race.Random.name],
        help="built-in AI race; several values are cycled game by game (default Random)",
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
    if args.opener is not None:
        builds = yaml.safe_load(BUILDS_FILE.read_text())["Builds"]
        if args.opener not in builds:
            parser.error(f"--opener must be one of: {', '.join(builds)}")
    return args


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


def main() -> int:
    args = parse_args()
    bot_name, bot_race = run.load_bot_config()
    difficulty = Difficulty[args.difficulty]
    ai_build = AIBuild[args.build]
    schedule = build_schedule(args.map, args.games, args.total)
    races = list(islice(cycle(Race[r] for r in args.race), len(schedule)))
    if args.replays is not None:
        args.replays.mkdir(parents=True, exist_ok=True)
    opponent = f"{'/'.join(args.race)} {difficulty.name} {ai_build.name}"

    rows = []
    for i, (map_name, opp_race) in enumerate(zip(schedule, races), start=1):
        print(
            f"\n=== Game {i}/{len(schedule)}: {bot_name} vs {opp_race.name} {difficulty.name} "
            f"{ai_build.name} on {map_name} ==="
        )
        bot = TrackedCitadelBot(forced_opener=args.opener)
        replay: Optional[str] = None
        if args.replays is not None:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            replay = str(
                (args.replays / f"{stamp}_{map_name}_{opp_race.name}_{difficulty.name}_{i}.SC2Replay").resolve()
            )
        started = time.perf_counter()
        error: Optional[str] = None
        try:
            result = run_game(
                maps.get(map_name),
                [Bot(bot_race, bot, bot_name), Computer(opp_race, difficulty, ai_build=ai_build)],
                realtime=False,
                save_replay_as=replay,
                game_time_limit=args.time_limit,
            )
            outcome = result.name if isinstance(result, Result) else str(result)
        except Exception as e:
            outcome, error = CRASH, repr(e)
        if bot.start_error is not None:
            outcome, error = CRASH, f"on_start: {bot.start_error}"
        # `state` only exists once the first observation arrived
        game_seconds = bot.time if getattr(bot, "state", None) is not None else None
        telemetry = getattr(bot, "telemetry", None)
        snap = telemetry.snapshots.get(PROBES_AT_S) if telemetry is not None else None
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
                "game_s": game_seconds,
                "real_s": time.perf_counter() - started,
                "error": error,
            }
        )

    counts = Counter(row["outcome"] for row in rows)
    decided = counts[Result.Victory.name] + counts[Result.Defeat.name] + counts[Result.Tie.name]
    win_rate = 100 * counts[Result.Victory.name] / decided if decided else 0.0

    def cell(value) -> str:
        return "-" if value is None else str(value)

    print(f"\n=== Summary: {bot_name} vs {opponent}, realtime=False ===")
    print(
        f"{'#':>3}  {'map':<18} {'vs':<8} {'opener':<15} {'wall_ok':<7} "
        f"{'probes@6':>8} {'bases@6':>7}  {'result':<8} {'game':>6} {'real':>7}"
    )
    for r in rows:
        line = (
            f"{r['i']:>3}  {r['map']:<18} {r['race']:<8} {r['opener']:<15} {cell(r['wall_ok']):<7} "
            f"{cell(r['probes6']):>8} {cell(r['bases6']):>7}  {r['outcome']:<8} "
            f"{format_game_time(r['game_s']):>6} {r['real_s']:>6.0f}s"
        )
        print(line + (f"  {r['error']}" if r["error"] else ""))
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
    return 1 if counts[CRASH] else 0


if __name__ == "__main__":
    sys.exit(main())
