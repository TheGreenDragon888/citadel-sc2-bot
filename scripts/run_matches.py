"""Play N local games of Citadel against the built-in AI and print a win/loss summary.

Games always run with realtime=False. Run from anywhere; paths resolve to the repo root.

Examples:
    poetry run python scripts/run_matches.py --games 10 --difficulty Hard --race Terran --map PylonAIE_v4
    poetry run python scripts/run_matches.py --map all --games 1 --difficulty VeryHard --build Rush
    poetry run python scripts/run_matches.py --games 5 --race Random --map random --replays replays
"""

import argparse
import os
import random
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import List, Optional

ROOT: Path = Path(__file__).resolve().parent.parent
# run.py resolves config.yml and the ares-sc2 import paths relative to the working directory
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

import run  # noqa: E402  (also puts ares-sc2 on sys.path)
from sc2 import maps  # noqa: E402
from sc2.data import AIBuild, Difficulty, Race, Result  # noqa: E402
from sc2.main import run_game  # noqa: E402
from sc2.player import Bot, Computer  # noqa: E402

from bot.constants import LADDER_TIE_GAME_SECONDS  # noqa: E402
from bot.main import CitadelBot  # noqa: E402

CRASH: str = "Crash"


class TrackedCitadelBot(CitadelBot):
    """CitadelBot with crash bookkeeping for this script; bot behaviour is unchanged.

    python-sc2 turns an exception in `on_start` into a plain Defeat, so record it here.
    Exceptions in `on_step` propagate out of `run_game` and are caught by the caller.
    """

    start_error: Optional[str] = None

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
        "--difficulty",
        choices=[d.name for d in Difficulty],
        default=Difficulty.Medium.name,
        help="built-in AI difficulty (default Medium)",
    )
    parser.add_argument(
        "--race",
        choices=[r.name for r in Race if r != Race.NoRace],
        default=Race.Random.name,
        help="built-in AI race (default Random)",
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
    return args


def build_schedule(map_args: List[str], games: int) -> List[str]:
    """Map name for every game to play, in order."""
    if map_args == ["random"]:
        return [random.choice(run.POOL_MAPS) for _ in range(games)]
    names: List[str] = []
    for name in map_args:
        names.extend(run.POOL_MAPS if name == "all" else [name])
    for name in names:
        maps.get(name)  # fail fast (KeyError) if a map file is missing
    return [name for name in names for _ in range(games)]


def format_game_time(seconds: Optional[float]) -> str:
    if seconds is None:
        return "--:--"
    return f"{int(seconds // 60):02d}:{int(seconds % 60):02d}"


def main() -> int:
    args = parse_args()
    bot_name, bot_race = run.load_bot_config()
    difficulty = Difficulty[args.difficulty]
    opp_race = Race[args.race]
    ai_build = AIBuild[args.build]
    schedule = build_schedule(args.map, args.games)
    if args.replays is not None:
        args.replays.mkdir(parents=True, exist_ok=True)
    opponent = f"{opp_race.name} {difficulty.name} {ai_build.name}"

    rows = []
    for i, map_name in enumerate(schedule, start=1):
        print(f"\n=== Game {i}/{len(schedule)}: {bot_name} vs {opponent} on {map_name} ===")
        bot = TrackedCitadelBot()
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
        rows.append((i, map_name, outcome, game_seconds, time.perf_counter() - started, error))

    counts = Counter(row[2] for row in rows)
    decided = counts[Result.Victory.name] + counts[Result.Defeat.name] + counts[Result.Tie.name]
    win_rate = 100 * counts[Result.Victory.name] / decided if decided else 0.0

    print(f"\n=== Summary: {bot_name} vs {opponent}, realtime=False ===")
    print(f"{'#':>3}  {'map':<20} {'result':<9} {'game':>6} {'wall':>8}")
    for i, map_name, outcome, game_seconds, wall, error in rows:
        line = f"{i:>3}  {map_name:<20} {outcome:<9} {format_game_time(game_seconds):>6} {wall:>7.1f}s"
        print(line + (f"  {error}" if error else ""))
    print(
        f"Wins {counts[Result.Victory.name]}  Losses {counts[Result.Defeat.name]}  "
        f"Ties {counts[Result.Tie.name]}  Crashes {counts[CRASH]}  "
        f"Other {len(rows) - decided - counts[CRASH]}  |  "
        f"win rate {win_rate:.1f}% of {decided} decided games"
    )
    return 1 if counts[CRASH] else 0


if __name__ == "__main__":
    sys.exit(main())
