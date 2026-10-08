"""M4 in-game check of Citadel's fight evaluation (bot/army/engagement.py, DESIGN.md §4.5.2).

Plays one local game (realtime=False) as a bare AresBot (no Citadel logic, so nothing moves the
spawned units) driven by python-sc2 debug commands. Dev-only (scripts/ is not in the ladder zip):

    poetry run python scripts/test_engagement.py [--map PylonAIE_v4]

Spawns our Stalkers (and two powered Cannons of ours) and, ARMY_SEPARATION away, an enemy group
of Stalkers, Zealots, powered Photon Cannons, a Shield Battery, Probes and an Observer. Then for
each scenario prints the most common level of REPEATS calls (and the range) from:
- `Engagement.level` (our HP+shields, defender set: user decisions for M4), and
- ares's `mediator.can_win_fight` with its default arguments, for comparison.
Finally it checks `Engagement.attack_inputs` (the §4.5.2 enemy side): workers, the Observer and
the Pylon left out; Stalkers, Zealots, Cannons and the Battery in.

M7 C5: out-ranged scenarios (Tempests, Void Rays vs Zealots, Carriers), printed with the raw
simulator level and the out-range penalty; the penalty itself is checked (EXPECT_PENALTY).

Exit code 1 if an expectation in EXPECT fails.
"""

import argparse
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Callable, List, Optional, Tuple

ROOT: Path = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

import run  # noqa: E402,F401  (puts ares-sc2 on sys.path)
from ares import AresBot  # noqa: E402
from sc2 import maps  # noqa: E402
from sc2.data import Difficulty, Race  # noqa: E402
from sc2.ids.unit_typeid import UnitTypeId  # noqa: E402
from sc2.main import run_game  # noqa: E402
from sc2.player import Bot, Computer  # noqa: E402
from sc2.position import Point2  # noqa: E402
from sc2.unit import Unit  # noqa: E402
from sc2.units import Units  # noqa: E402

from bot.army.engagement import ENEMY_DEFENDS, WE_DEFEND, Engagement  # noqa: E402

OWN, ENEMY = 1, 2  # debug_create_unit owner ids
ARMY_SEPARATION: float = 30.0  # far outside every weapon and vision range; the simulator ignores positions
ARENA_HALF_SIZE: int = 6
CANNON_OFFSETS: List[Tuple[int, int]] = [(3, 0), (-3, 0), (0, 3), (0, -3), (3, 3), (-3, -3)]
REPEATS: int = 20
PHASE_TIMEOUT_LOOPS: int = 22 * 30

# scenario -> (lowest, highest) acceptable most-common Citadel level
EXPECT: dict[str, Tuple[int, int]] = {
    "6 Stalkers vs nothing": (10, 10),
    "6 Stalkers vs 6 Stalkers": (4, 6),  # an even fight
    "6 Stalkers vs 3 Cannons (attacking)": (0, 6),  # a costly fight: at best a narrow win
    "6 Stalkers vs 6 Cannons (attacking)": (0, 4),  # a loss (ares: VICTORY_EMPHATIC)
    "12 Stalkers vs 3 Cannons (attacking)": (6, 10),  # a clear win: scales with army size
}
# M7 C5: scenario -> expected out-range penalty (levels)
EXPECT_PENALTY: dict[str, int] = {
    "6 Stalkers vs 6 Stalkers": 0,
    "30 Stalkers + 4 Colossi vs 8 Tempests + 4 Zealots": 4,  # ~89% of the value out-ranges them
    "12 Zealots vs 8 Tempests": 4,  # none of ours can hit them
    "12 Stalkers vs 4 Void Rays": 0,
}
# Printed only: Void Rays and Carriers have no weapon in this game data (VERIFY_NOTES "M7 findings"),
# so neither the simulator nor the penalty sees them; these rows show that gap.


class EngagementProbe(AresBot):
    def __init__(self) -> None:
        super().__init__()
        self.phase: str = "spawn"
        self.phase_started: int = 0
        self.finished: bool = False
        self.lines: List[str] = []
        self.failures: List[str] = []
        self.engagement: Optional[Engagement] = None
        self.centre: Optional[Point2] = None

    def log(self, text: str) -> None:
        self.lines.append(text)
        print(f"CHECK {text}", flush=True)

    def goto(self, phase: str) -> None:
        self.phase = phase
        self.phase_started = self.state.game_loop

    async def on_step(self, iteration: int) -> None:
        await super().on_step(iteration)
        if not self.finished:
            handler: Callable = getattr(self, f"_{self.phase}")
            await handler()

    def find_arena(self) -> Tuple[Point2, Point2]:
        area = self.game_info.playable_area
        margin = ARENA_HALF_SIZE + 1
        centre = self.game_info.map_center
        span = range(-ARENA_HALF_SIZE, ARENA_HALF_SIZE + 1)
        candidates = sorted(
            (
                Point2((x, y))
                for x in range(int(area.x) + margin, int(area.right) - margin)
                for y in range(int(area.y) + margin, int(area.top) - margin)
            ),
            key=lambda p: p.distance_to(centre),
        )
        for p in candidates:
            own = p.towards(self.start_location, ARMY_SEPARATION)
            if self.in_pathing_grid(own) and all(
                self.in_placement_grid(Point2((p.x + dx, p.y + dy))) for dx in span for dy in span
            ):
                return p, own
        raise RuntimeError("no open area for the arena")

    async def _spawn(self) -> None:
        await self.client.debug_show_map()
        centre, own = self.find_arena()
        self.centre = centre
        behind = own.towards(centre, -4)
        await self.client.debug_create_unit(
            [
                [UnitTypeId.STALKER, 30, own, OWN],
                [UnitTypeId.COLOSSUS, 4, own.towards(centre, -6), OWN],
                [UnitTypeId.ZEALOT, 12, own.towards(centre, -9), OWN],
                [UnitTypeId.PYLON, 1, behind, OWN],
                [UnitTypeId.PHOTONCANNON, 1, behind.offset((2, 2)), OWN],
                [UnitTypeId.PHOTONCANNON, 1, behind.offset((-2, -2)), OWN],
                [UnitTypeId.STALKER, 6, centre.towards(own, 3), ENEMY],
                [UnitTypeId.ZEALOT, 4, centre.towards(own, 4), ENEMY],
                [UnitTypeId.PYLON, 1, centre, ENEMY],
                [UnitTypeId.SHIELDBATTERY, 1, centre.offset((0, -5)), ENEMY],
                [UnitTypeId.PROBE, 4, centre.offset((-5, 0)), ENEMY],
                [UnitTypeId.OBSERVER, 1, centre.offset((5, 5)), ENEMY],
                [UnitTypeId.TEMPEST, 8, centre.towards(own, -6), ENEMY],
                [UnitTypeId.VOIDRAY, 4, centre.towards(own, -8), ENEMY],
                [UnitTypeId.CARRIER, 2, centre.towards(own, -10), ENEMY],
            ]
            + [[UnitTypeId.PHOTONCANNON, 1, centre.offset(o), ENEMY] for o in CANNON_OFFSETS]
        )
        self.goto("evaluate")

    def sample(self, fn: Callable[[], int]) -> Tuple[int, int, int]:
        values = [int(fn()) for _ in range(REPEATS)]
        return Counter(values).most_common(1)[0][0], min(values), max(values)

    async def _evaluate(self) -> None:
        own = self.units(UnitTypeId.STALKER)
        colossi, own_zealots = self.units(UnitTypeId.COLOSSUS), self.units(UnitTypeId.ZEALOT)
        tempests, voidrays = self.enemy_units(UnitTypeId.TEMPEST), self.enemy_units(UnitTypeId.VOIDRAY)
        carriers = self.enemy_units(UnitTypeId.CARRIER)
        own_cannons = self.structures(UnitTypeId.PHOTONCANNON).ready.filter(lambda c: c.is_powered)
        stalkers = self.enemy_units(UnitTypeId.STALKER)
        zealots = self.enemy_units(UnitTypeId.ZEALOT)
        cannons = self.enemy_structures(UnitTypeId.PHOTONCANNON).filter(lambda c: c.is_ready and c.is_powered)
        ready = (
            len(own) == 30 and len(stalkers) == 6 and len(zealots) == 4 and len(cannons) == 6 and len(own_cannons) == 2
            and len(colossi) == 4 and len(own_zealots) == 12 and len(tempests) == 8 and len(voidrays) == 4 and len(carriers) == 2
        )
        if not ready:
            if self.state.game_loop - self.phase_started > PHASE_TIMEOUT_LOOPS:
                self.log(
                    f"TIMEOUT: own {len(own)}, own cannons {len(own_cannons)}, stalkers {len(stalkers)}, "
                    f"zealots {len(zealots)}, cannons {len(cannons)}"
                )
                self.failures.append("setup")
                await self.finish()
            return
        eng = Engagement(self)
        six, twelve, thirty = list(own[:6]), list(own[:12]), list(own)
        cannons = cannons.sorted(lambda c: c.distance_to(own.center))
        scenarios: List[Tuple[str, list, list, int]] = [
            ("6 Stalkers vs nothing", six, [], ENEMY_DEFENDS),
            ("6 Stalkers vs 6 Stalkers", six, list(stalkers), ENEMY_DEFENDS),
            ("6 Stalkers vs 4 Zealots", six, list(zealots), ENEMY_DEFENDS),
            ("6 Stalkers vs 3 Cannons (attacking)", six, list(cannons[:3]), ENEMY_DEFENDS),
            ("6 Stalkers vs 6 Cannons (attacking)", six, list(cannons), ENEMY_DEFENDS),
            ("12 Stalkers vs 3 Cannons (attacking)", twelve, list(cannons[:3]), ENEMY_DEFENDS),
            ("6 Stalkers vs 6 Stalkers (defending)", six, list(stalkers), WE_DEFEND),
            ("6 Stalkers + 2 Cannons vs 6 Stalkers (defending)", six + list(own_cannons), list(stalkers), WE_DEFEND),
            # M7 C5
            ("30 Stalkers + 4 Colossi vs 8 Tempests + 4 Zealots", thirty + list(colossi), list(tempests) + list(zealots), ENEMY_DEFENDS),
            ("30 Stalkers vs 8 Tempests", thirty, list(tempests), ENEMY_DEFENDS),
            ("12 Stalkers vs 8 Tempests", twelve, list(tempests), ENEMY_DEFENDS),
            ("12 Zealots vs 8 Tempests", list(own_zealots), list(tempests), ENEMY_DEFENDS),
            ("12 Zealots vs 4 Void Rays", list(own_zealots), list(voidrays), ENEMY_DEFENDS),
            ("12 Stalkers vs 4 Void Rays", twelve, list(voidrays), ENEMY_DEFENDS),
            ("12 Stalkers vs 2 Carriers (no Interceptors)", twelve, list(carriers), ENEMY_DEFENDS),
        ]
        self.log(f"{'scenario':<52} {'Citadel':>14} {'(raw, penalty)':>15} {'ares can_win_fight':>20}")
        for label, ours, theirs, defender in scenarios:
            mine = self.sample(lambda: eng.level(ours, theirs, defender))
            penalty = eng.last_inputs.penalty if eng.last_inputs is not None else 0
            ares = self.sample(
                lambda: self.mediator.can_win_fight(own_units=Units(ours, self), enemy_units=Units(theirs, self)).value
            )
            self.log(
                f"{label:<52} {mine[0]:>3} ({mine[1]}-{mine[2]}) {f'({mine[0] + penalty}, -{penalty})':>15}"
                f"{'':>6} {ares[0]:>3} ({ares[1]}-{ares[2]})"
            )
            if label in EXPECT:
                low, high = EXPECT[label]
                # M4's expectations are on the simulator's own level (before the M7 penalty)
                if not low <= mine[0] + penalty <= high:
                    self.failures.append(f"{label}: {mine[0] + penalty} not in {low}-{high}")
            if label in EXPECT_PENALTY and penalty != EXPECT_PENALTY[label]:
                self.failures.append(f"{label}: penalty {penalty} != {EXPECT_PENALTY[label]}")
            if label in EXPECT_PENALTY and theirs:
                o, e = ours[0], theirs[0]
                self.log(
                    f"    share {eng.outranged_share(ours, theirs):.2f}; own {o.type_id.name} air={o.can_attack_air} "
                    f"ground={o.can_attack_ground} flying={o.is_flying}; enemy {e.type_id.name} air={e.can_attack_air} "
                    f"ground={e.can_attack_ground} flying={e.is_flying} ranges {e.ground_range}/{e.air_range}"
                )
        # §4.5.2 enemy side: fighters and static defense in, workers/Observer/Pylon out
        found = eng.attack_inputs(own.center, self.centre)
        kinds = Counter(u.type_id.name for u in found)
        self.log(f"attack_inputs from our Stalkers to the enemy group: {dict(sorted(kinds.items()))}")
        want_in = {"STALKER": 6, "ZEALOT": 4, "PHOTONCANNON": 6, "SHIELDBATTERY": 1}
        for name, n in want_in.items():
            if kinds.get(name, 0) != n:
                self.failures.append(f"attack_inputs {name}: {kinds.get(name, 0)} != {n}")
        for name in ("PROBE", "OBSERVER", "PYLON"):
            if kinds.get(name):
                self.failures.append(f"attack_inputs includes {name}")
        self.log(f"simulator calls: {eng.calls}")
        await self.finish()

    async def finish(self) -> None:
        self.finished = True
        self.log("RESULT " + ("PASS" if not self.failures else "FAIL: " + "; ".join(self.failures)))
        await self.client.leave()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--map", default="PylonAIE_v4")
    args = parser.parse_args()
    bot = EngagementProbe()
    run_game(
        maps.get(args.map),
        [Bot(Race.Protoss, bot), Computer(Race.Terran, Difficulty.VeryEasy)],
        realtime=False,
    )
    print("\n".join(bot.lines))
    return 1 if bot.failures or not bot.finished else 0


if __name__ == "__main__":
    sys.exit(main())
