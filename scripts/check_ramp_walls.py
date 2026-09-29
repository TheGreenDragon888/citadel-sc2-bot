"""Check python-sc2's Protoss ramp-wall helpers on both spawns of every pool map (§4.8, §12 Q6).

Each game has two plain python-sc2 players (no ares), so each spawn computes its own
`main_base_ramp`. Both leave on their first step; python-sc2 then reports the game as an
AssertionError, which is expected and ignored. Prints one RESULT line per spawn.

    poetry run python scripts/check_ramp_walls.py
"""

import os
import sys
from pathlib import Path

ROOT: Path = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

import run  # noqa: E402
from sc2 import maps  # noqa: E402
from sc2.bot_ai import BotAI  # noqa: E402
from sc2.data import Race  # noqa: E402
from sc2.main import run_game  # noqa: E402
from sc2.player import Bot  # noqa: E402

from bot.constants import WALL_RAMP_MAX_DIST  # noqa: E402

RESULTS: list[dict] = []


class WallProbe(BotAI):
    async def on_start(self) -> None:
        ramp = self.main_base_ramp
        row = {
            "map": self.game_info.map_name,
            "start": tuple(round(v, 1) for v in self.start_location),
            "upper": len(ramp.upper),
            "top_dist": round(self.start_location.distance_to(ramp.top_center), 1),
        }
        for name in ("protoss_wall_pylon", "protoss_wall_buildings", "protoss_wall_warpin"):
            try:
                value = getattr(ramp, name)
                row[name] = len(value) if name == "protoss_wall_buildings" else (value is not None)
            except Exception as e:  # python-sc2 raises on some ramp shapes
                row[name] = f"raises {type(e).__name__}"
        buildings = row["protoss_wall_buildings"]
        row["wall_ok"] = (
            row["protoss_wall_pylon"] is True
            and isinstance(buildings, int)
            and buildings >= 2
            and row["protoss_wall_warpin"] is True
            and row["top_dist"] <= WALL_RAMP_MAX_DIST
        )
        RESULTS.append(row)
        await self.client.leave()

    async def on_step(self, iteration: int) -> None:
        pass


def main() -> int:
    for map_name in run.POOL_MAPS:
        try:
            run_game(
                maps.get(map_name),
                [Bot(Race.Protoss, WallProbe()), Bot(Race.Protoss, WallProbe())],
                realtime=False,
            )
        except AssertionError:
            pass  # both players left; see the module docstring
    print("\nRESULT map | spawn | ramp upper points | start->ramp top | pylon | buildings | warp-in | wall_ok")
    for r in RESULTS:
        print(
            f"RESULT {r['map']} | {r['start']} | {r['upper']} | {r['top_dist']} | "
            f"{r['protoss_wall_pylon']} | {r['protoss_wall_buildings']} | "
            f"{r['protoss_wall_warpin']} | {r['wall_ok']}"
        )
    return 0 if len(RESULTS) == 2 * len(run.POOL_MAPS) else 1


if __name__ == "__main__":
    sys.exit(main())
