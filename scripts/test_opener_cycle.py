"""Check that protoss_builds.yml is wired to ares's opener selection (DESIGN.md §4.1).

Plays short games vs the built-in Terran AI in which Citadel leaves (a Defeat) once
`--leave-at` game seconds have passed. Before any data exists, ares starts with the first
build in the `Terran` cycle; every loss moves it to the next build (docs/VERIFY_NOTES.md
§11.4), so 3 games should play A_Standard, A2_Safe, A_Standard. Prints the opener of each
game and the data file ares wrote.

The real ./data/None-protoss.json is moved aside first and restored afterwards.

    poetry run python scripts/test_opener_cycle.py
"""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import List

ROOT: Path = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

import run  # noqa: E402,F401  (puts ares-sc2 on sys.path)
from sc2 import maps  # noqa: E402
from sc2.data import Difficulty, Race  # noqa: E402
from sc2.main import run_game  # noqa: E402
from sc2.player import Bot, Computer  # noqa: E402

from bot.main import CitadelBot  # noqa: E402

DATA_FILE: Path = ROOT / "data" / "None-protoss.json"  # opponent_id is None in local games
EXPECTED: List[str] = ["A_Standard", "A2_Safe", "A_Standard"]


class LeavingBot(CitadelBot):
    leave_at: float = 20.0

    async def on_step(self, iteration: int) -> None:
        await super().on_step(iteration)
        if self.time >= self.leave_at:
            await self.client.leave()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--map", default="PylonAIE_v4")
    parser.add_argument("--leave-at", type=float, default=20.0)
    args = parser.parse_args()

    backup = DATA_FILE.with_suffix(".json.bak")
    if DATA_FILE.exists():
        shutil.move(DATA_FILE, backup)
    openers: List[str] = []
    try:
        for i in range(len(EXPECTED)):
            bot = LeavingBot()
            bot.leave_at = args.leave_at
            result = run_game(
                maps.get(args.map),
                [Bot(Race.Protoss, bot, "Citadel"), Computer(Race.Terran, Difficulty.Easy)],
                realtime=False,
            )
            openers.append(bot.opener)
            print(f"GAME {i + 1}: opener={bot.opener} result={result.name}")
        print(f"\n{DATA_FILE.relative_to(ROOT)} after {len(EXPECTED)} games:")
        print(json.dumps(json.loads(DATA_FILE.read_text()), indent=1))
    finally:
        if DATA_FILE.exists():
            DATA_FILE.unlink()
        if backup.exists():
            shutil.move(backup, DATA_FILE)

    ok = openers == EXPECTED
    print(f"\nopeners {openers}, expected {EXPECTED}: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
