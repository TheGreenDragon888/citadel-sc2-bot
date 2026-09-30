"""M4 staged test of the §4.7 structure hunt (bot/army/endgame.py), with shortened thresholds.

Plays one local game (realtime=False) of Citadel against the built-in Terran AI, with debug
commands (dev-only; scripts/ is not in the ladder zip):

    poetry run python scripts/test_endgame.py [--map PylonAIE_v4]

Setup, at the start of the game:
- two enemy structures are created far from both mains and from every expansion: a Supply Depot
  on the ground and a lifted Barracks (BARRACKSFLYING) over pathable ground elsewhere;
- every other enemy unit and structure is killed, so those two are all the enemy has;
- we get 12 Stalkers and 2 Observers at our natural.
The end-game thresholds are shortened inside this test only: the hunt may start at
TEST_END_GAME_FROM_S (instead of 40:00) once no enemy structure has been in vision for
TEST_UNSEEN_S, and the attack may launch at TEST_ATTACK_SUPPLY supply used.

PASS: the hunt started, both structures were found, and the game was a Victory before
TEST_TIME_LIMIT_S (the last structure's death ends the game in the same step, so python-sc2
never reports it through on_unit_destroyed; the Victory is the evidence).
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

import bot.army.army as army_module  # noqa: E402
import bot.army.attack_decision as decision_module  # noqa: E402
import bot.army.endgame as endgame_module  # noqa: E402
from bot.main import CitadelBot  # noqa: E402

OWN, ENEMY = 1, 2
TEST_END_GAME_FROM_S: float = 60.0
TEST_UNSEEN_S: float = 10.0
TEST_ATTACK_SUPPLY: int = 20
TEST_TIME_LIMIT_S: int = 15 * 60
MIN_FROM_STARTS: float = 40.0  # hidden structures at least this far from both start locations ...
MIN_FROM_EXPANSIONS: float = 14.0  # ... and from every expansion location
MIN_APART: float = 30.0  # ... and this far from each other
SPOT_STEP: int = 4


def patch_thresholds() -> None:
    endgame_module.END_GAME_FROM_S = TEST_END_GAME_FROM_S
    endgame_module.END_GAME_HUNT_UNSEEN_S = TEST_UNSEEN_S
    decision_module.ATTACK_START_SUPPLY = TEST_ATTACK_SUPPLY
    army_module.ATTACK_START_SUPPLY = TEST_ATTACK_SUPPLY


class EndGameProbe(CitadelBot):
    def __init__(self) -> None:
        super().__init__()
        self.phase: str = "reveal"
        self.hidden: dict[int, str] = {}  # tag -> label
        self.found_at: dict[str, float] = {}
        self.destroyed_at: dict[str, float] = {}
        self.spots: dict[str, Point2] = {}
        self.lines: list[str] = []
        self.doomed: list[int] = []

    def log(self, text: str) -> None:
        line = f"[{self.time_formatted}] {text}"
        self.lines.append(line)
        print(f"CHECK {line}", flush=True)

    def hidden_spots(self) -> tuple[Point2, Point2]:
        area = self.game_info.playable_area
        starts = [self.start_location, self.enemy_start_locations[0]]
        expansions = self.expansion_locations_list
        candidates = []
        for x in range(int(area.x) + 3, int(area.right) - 3, SPOT_STEP):
            for y in range(int(area.y) + 3, int(area.top) - 3, SPOT_STEP):
                p = Point2((x, y))
                if not (self.in_pathing_grid(p) and self.in_placement_grid(p)):
                    continue
                if min(p.distance_to(s) for s in starts) < MIN_FROM_STARTS:
                    continue
                if min(p.distance_to(e) for e in expansions) < MIN_FROM_EXPANSIONS:
                    continue
                candidates.append(p)
        if not candidates:
            raise RuntimeError("no hidden spot on this map")
        # the spot farthest from both starts, then the farthest one from it
        first = max(candidates, key=lambda p: min(p.distance_to(s) for s in starts))
        second = max(
            (p for p in candidates if p.distance_to(first) >= MIN_APART),
            key=lambda p: min(p.distance_to(s) for s in starts),
        )
        return first, second

    async def on_step(self, iteration: int) -> None:
        await super().on_step(iteration)
        if self.phase == "reveal":
            await self.client.debug_show_map()
            self.phase = "kill_units"
        elif self.phase == "kill_units":
            # everything but the structures now; their tags are kept for later
            self.doomed = [s.tag for s in self.enemy_structures if not s.is_snapshot]
            units = [u.tag for u in self.enemy_units if not u.is_memory]
            if not self.doomed:
                return
            await self.client.debug_kill_unit(units)
            await self.client.debug_show_map()  # vision back to normal before anything is hidden
            self.log(f"killed {len(units)} enemy units; {len(self.doomed)} enemy structures to go")
            self.phase = "create"
        elif self.phase == "create":
            ground, air = self.hidden_spots()
            self.spots = {"SUPPLYDEPOT": ground, "BARRACKSFLYING": air}
            nat = self.mediator.get_own_nat
            await self.client.debug_create_unit(
                [
                    [UnitTypeId.SUPPLYDEPOT, 1, ground, ENEMY],
                    [UnitTypeId.BARRACKSFLYING, 1, air, ENEMY],
                    [UnitTypeId.STALKER, 12, nat, OWN],
                    [UnitTypeId.OBSERVER, 2, nat, OWN],
                ]
            )
            self.log(f"hidden SUPPLYDEPOT at {ground.rounded}, BARRACKSFLYING at {air.rounded} (out of vision)")
            self.phase = "kill_structures"
        elif self.phase == "kill_structures":
            await self.client.debug_kill_unit(self.doomed)
            self.log(f"killed the {len(self.doomed)} other enemy structures")
            self.phase = "watch"
        elif self.phase == "watch":
            for s in self.enemy_structures:
                if not s.is_visible or s.type_id not in (UnitTypeId.SUPPLYDEPOT, UnitTypeId.SUPPLYDEPOTLOWERED, UnitTypeId.BARRACKSFLYING, UnitTypeId.BARRACKS):
                    continue
                label = "SUPPLYDEPOT" if s.type_id in (UnitTypeId.SUPPLYDEPOT, UnitTypeId.SUPPLYDEPOTLOWERED) else "BARRACKSFLYING"
                self.hidden[s.tag] = label
                if label not in self.found_at:
                    hunting = self.endgame is not None and self.endgame.hunting
                    self.found_at[label] = self.time
                    self.log(f"{label} found at {s.position.rounded}" + (" (during the hunt)" if hunting else ""))

    async def on_unit_destroyed(self, unit_tag: int) -> None:
        await super().on_unit_destroyed(unit_tag)
        label = self.hidden.get(unit_tag)
        if label and label not in self.destroyed_at:
            self.destroyed_at[label] = self.time
            self.log(f"{label} destroyed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--map", default="PylonAIE_v4")
    args = parser.parse_args()
    patch_thresholds()
    bot = EndGameProbe()
    result = run_game(
        maps.get(args.map),
        [Bot(Race.Protoss, bot), Computer(Race.Terran, Difficulty.VeryEasy)],
        realtime=False,
        game_time_limit=TEST_TIME_LIMIT_S,
    )
    hunts = bot.endgame.hunt_started_at if bot.endgame is not None else []
    print("\n".join(bot.lines))
    print(f"CHECK hunt started at: {[f'{int(t) // 60}:{int(t) % 60:02d}' for t in hunts]}")
    print(f"CHECK result: {result}")
    ok = result == Result.Victory and bool(hunts) and set(bot.found_at) == {"SUPPLYDEPOT", "BARRACKSFLYING"}
    print(f"CHECK RESULT {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
