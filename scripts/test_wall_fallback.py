"""Force the §4.8 ramp wall fallback on a pool map and check it (DESIGN.md §4.8).

No pool map needs the fallback (every spawn passes python-sc2's wall helpers), so this test
fakes the failure:

- `--case ramp`: `main_base_ramp.protoss_wall_buildings` is emptied before Citadel's
  `on_start`, the value python-sc2 returns for ramps it can't wall.
- `--case choke`: the "ramp top too far from start" limit is lowered below the real distance,
  so Citadel uses the nearest map-analyzer choke instead of the ramp (§4.8.3).

At `--check-at` game seconds it records where the opener's Pylon/Gateway/Core went, the
Shield Battery near the choke and the holding unit, then plays the game out vs the built-in
AI and prints PASS/FAIL per check. The bot keeps its normal opener selection but does not
write ./data.

    poetry run python scripts/test_wall_fallback.py --case ramp
    poetry run python scripts/test_wall_fallback.py --case choke --map TorchesAIE_v4 --race Zerg
"""

import argparse
import os
import sys
from pathlib import Path
from typing import Optional

ROOT: Path = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

import run  # noqa: E402,F401  (puts ares-sc2 on sys.path)
from sc2 import maps  # noqa: E402
from sc2.data import Difficulty, Race, Result  # noqa: E402
from sc2.ids.unit_typeid import UnitTypeId  # noqa: E402
from sc2.main import run_game  # noqa: E402
from sc2.player import Bot, Computer  # noqa: E402
from sc2.position import Point2  # noqa: E402

import bot.defense.wall_fallback as wall_fallback  # noqa: E402
from bot.constants import WALL_BATTERY_MAX_DIST  # noqa: E402
from bot.main import CitadelBot  # noqa: E402

HOLD_TOLERANCE: float = 1.5


class ForcedFallbackBot(CitadelBot):
    case: str = "ramp"
    check_at: float = 300.0

    def __init__(self):
        super().__init__()
        self.real_wall: list[Point2] = []
        self.report: Optional[dict] = None
        self.start_error: Optional[str] = None

    async def on_before_start(self) -> None:
        await super().on_before_start()
        self.config["UseData"] = False  # don't let test games change opener selection

    async def on_start(self) -> None:
        ramp = self.main_base_ramp
        self.real_wall = [ramp.protoss_wall_pylon, *ramp.protoss_wall_buildings]
        if self.case == "ramp":
            ramp.protoss_wall_buildings = frozenset()
        else:
            wall_fallback.WALL_RAMP_MAX_DIST = 5.0
        try:
            await super().on_start()
        except Exception as e:
            self.start_error = repr(e)
            raise

    async def on_step(self, iteration: int) -> None:
        await super().on_step(iteration)
        if self.report is None and self.time >= self.check_at:
            self.report = self._report()

    def _report(self) -> dict:
        choke = self.wall.choke
        start_z = self.get_terrain_z_height(self.start_location)
        gateways = self.structures.filter(lambda s: s.type_id in (UnitTypeId.GATEWAY, UnitTypeId.WARPGATE))
        opener_structures = {
            "PYLON": [s.position for s in self.structures(UnitTypeId.PYLON)],
            "GATEWAY": [s.position for s in gateways],
            "CYBERNETICSCORE": [s.position for s in self.structures(UnitTypeId.CYBERNETICSCORE)],
        }
        on_real_wall = [
            (name, p.rounded)
            for name, positions in opener_structures.items()
            for p in positions
            if any(p.distance_to(w) < 1.0 for w in self.real_wall)
        ]
        batteries = [
            (b.position, b.distance_to(choke), abs(self.get_terrain_z_height(b) - start_z))
            for b in self.structures(UnitTypeId.SHIELDBATTERY)
        ]
        holder = self.units.find_by_tag(self.wall.holder_tag) if self.wall.holder_tag else None
        return {
            "time": self.time_formatted,
            "wall_ok": self.wall_ok,
            "reason": self.wall.reason,
            "choke": choke.rounded,
            "hold_point": self.wall.hold_point.rounded,
            "gateway_core": [
                (n, p.rounded, round(p.distance_to(choke), 1))
                for n in ("GATEWAY", "CYBERNETICSCORE")
                for p in opener_structures[n][:1]
            ],
            "on_real_wall": on_real_wall,
            "batteries": [(p.rounded, round(d, 1), round(dz, 2)) for p, d, dz in batteries],
            "holder": (holder.type_id.name, round(holder.distance_to(self.wall.hold_point), 1))
            if holder
            else None,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=["ramp", "choke"], default="ramp")
    parser.add_argument("--map", default="PylonAIE_v4")
    parser.add_argument("--race", choices=["Terran", "Zerg", "Protoss"], default="Terran")
    parser.add_argument("--difficulty", default="Medium")
    parser.add_argument("--check-at", type=float, default=300.0)
    args = parser.parse_args()

    ForcedFallbackBot.case = args.case
    ForcedFallbackBot.check_at = args.check_at
    bot = ForcedFallbackBot()
    result = run_game(
        maps.get(args.map),
        [Bot(Race.Protoss, bot, "Citadel"), Computer(Race[args.race], Difficulty[args.difficulty])],
        realtime=False,
    )
    r = bot.report or {}
    print(f"\n=== wall fallback test: case={args.case} map={args.map} vs {args.race} {args.difficulty} ===")
    for key, value in r.items():
        print(f"  {key}: {value}")
    near = [b for b in r.get("batteries", []) if b[1] <= WALL_BATTERY_MAX_DIST and b[2] < 0.5]
    holder = r.get("holder")
    checks = [
        ("no crash in on_start", bot.start_error is None),
        ("wall_ok is False", r.get("wall_ok") is False),
        ("opener Gateway and Core were built", len(r.get("gateway_core", [])) == 2),
        # ares's in-base layout can include a tile that is also a wall spot; a wall needs both
        (
            "no wall formed (Gateway and Core not both on python-sc2's wall spots)",
            len({name for name, _ in r.get("on_real_wall", []) if name != "PYLON"}) < 2,
        ),
        (f"a Shield Battery within {WALL_BATTERY_MAX_DIST:g} of the choke, on the main's level", bool(near)),
        (f"a Zealot/Adept holding within {HOLD_TOLERANCE} of the hold point", holder is not None and holder[1] <= HOLD_TOLERANCE),
        ("game won", result == Result.Victory),
    ]
    for name, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    print(f"  result: {result.name if isinstance(result, Result) else result}")
    return 0 if all(ok for _, ok in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
