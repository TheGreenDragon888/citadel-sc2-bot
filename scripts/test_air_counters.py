"""M7 E0 staged test: which equal-value groups beat capital ships (docs/M7_PLAN.md E0, D13).

    poetry run python scripts/test_air_counters.py [--case tempest|battlecruiser|broodlord|voidray|all]
        [--candidate NAME|all] [--runs 5] [--map PylonAIE_v4]

Each game (realtime=False) is Citadel against `StagedEnemy`, both sides with every upgrade
(`client.debug_upgrade()` twice each; the enemy plays the case's race). Setup with debug commands
(dev only; scripts/ is not in the ladder zip): a Nexus of ours at our natural, then our candidate
group at the army's defensive position and the enemy group ENEMY_DIST toward the enemy main, which
then comes at us:

- `tempest` (P): TEMPEST_COUNT Tempests that kite (step back while their weapon reloads);
- `battlecruiser` (T): BC_COUNT Battlecruisers;
- `broodlord` (Z): BROODLORD_COUNT Brood Lords and as many Corruptors;
- `voidray` (P, D13): VOIDRAY_COUNT Void Rays.

Our candidates get the enemy group's game-data value (minerals + gas), whole units only:
`voidray`, `tempest`, `stalker` (Blink micro off), `blink_stalker`, `stalker_voidray` and
`stalker_tempest` (half the value each). No Archons (D10).

The test measures the fight, not the decision to take it: home defense is forced to engage
(`army.home_engages` patched to True), so our units fight with Citadel's micro (kiting, Blink, the
E3 Tempest / Void Ray targeting). Each game is watched WATCH_S or until one side has nothing left.
Per game: the winner (the side with units left; at the time limit, the side that lost the smaller
share of its value), value killed and lost. The summary per case ranks the candidates by wins, then
by value traded (killed / lost). Results go to VERIFY_NOTES and set the E3 capital-air shares.
"""

import argparse
import os
import sys
from pathlib import Path
from statistics import mean
from typing import Optional

ROOT: Path = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

import run  # noqa: E402,F401  (puts ares-sc2 on sys.path)
from sc2.bot_ai import BotAI  # noqa: E402
from sc2.data import Race  # noqa: E402
from sc2.ids.unit_typeid import UnitTypeId  # noqa: E402
from sc2.player import Bot  # noqa: E402
from sc2.position import Point2  # noqa: E402

import bot.army.army as army_module  # noqa: E402
from bot.main import CitadelBot  # noqa: E402
from scripts.run_matches import run_bot_game  # noqa: E402

OWN, ENEMY = 1, 2
TEMPEST_COUNT: int = 6
BC_COUNT: int = 4
BROODLORD_COUNT: int = 4
VOIDRAY_COUNT: int = 8
ENEMY_DIST: float = 22.0
SETTLE_STEPS: int = 24
UPGRADE_STEPS: int = 8
WATCH_S: float = 120.0
TIME_LIMIT_S: int = 6 * 60
TRADED_CAP: float = 99.0  # value killed / lost, capped (a flawless win would divide by 0)
CASES: dict[str, tuple[Race, list[tuple[UnitTypeId, int]]]] = {
    "tempest": (Race.Protoss, [(UnitTypeId.TEMPEST, TEMPEST_COUNT)]),
    "battlecruiser": (Race.Terran, [(UnitTypeId.BATTLECRUISER, BC_COUNT)]),
    "broodlord": (Race.Zerg, [(UnitTypeId.BROODLORD, BROODLORD_COUNT), (UnitTypeId.CORRUPTOR, BROODLORD_COUNT)]),
    "voidray": (Race.Protoss, [(UnitTypeId.VOIDRAY, VOIDRAY_COUNT)]),
}
# candidate -> (unit type, share of the value)
CANDIDATES: dict[str, list[tuple[UnitTypeId, float]]] = {
    "voidray": [(UnitTypeId.VOIDRAY, 1.0)],
    "tempest": [(UnitTypeId.TEMPEST, 1.0)],
    "stalker": [(UnitTypeId.STALKER, 1.0)],
    "blink_stalker": [(UnitTypeId.STALKER, 1.0)],
    "stalker_voidray": [(UnitTypeId.STALKER, 0.5), (UnitTypeId.VOIDRAY, 0.5)],
    "stalker_tempest": [(UnitTypeId.STALKER, 0.5), (UnitTypeId.TEMPEST, 0.5)],
}


class StagedEnemy(BotAI):
    """Attack-moves its units to `attack_point` once set; Tempests kite."""

    def __init__(self) -> None:
        super().__init__()
        self.attack_point: Optional[Point2] = None
        self.upgraded = False

    async def on_step(self, iteration: int) -> None:
        if not self.upgraded and iteration >= 2:
            await self.client.debug_upgrade()
            await self.client.debug_upgrade()
            self.upgraded = True
        if self.attack_point is None:
            return
        foes = self.enemy_units
        for u in self.units:
            if u.type_id in (UnitTypeId.OVERLORD, UnitTypeId.DRONE, UnitTypeId.SCV, UnitTypeId.PROBE, UnitTypeId.LARVA):
                continue
            if u.type_id == UnitTypeId.TEMPEST and u.weapon_cooldown > 0 and foes:
                near = foes.closest_to(u)
                if near.distance_to(u) < u.air_range + 2:
                    u.move(u.position.towards(near.position, -4))
                    continue
            if u.is_idle or (u.type_id == UnitTypeId.TEMPEST and u.weapon_cooldown == 0):
                u.attack(foes.closest_to(u) if foes and u.type_id == UnitTypeId.TEMPEST else self.attack_point)


class StagedCitadel(CitadelBot):
    def __init__(self, case: str, candidate: str, enemy: StagedEnemy):
        super().__init__()
        self.case, self.candidate, self.enemy_bot = case, candidate, enemy
        self.phase = "nexus"
        self.finished = False
        self.mark = 0
        self.watch_from: Optional[float] = None
        self.ours: dict[int, UnitTypeId] = {}
        self.theirs: dict[int, UnitTypeId] = {}
        self.result: dict = {}

    def log(self, text: str) -> None:
        print(f"CHECK [{self.time_formatted}] {text}", flush=True)

    def value_of(self, t: UnitTypeId) -> float:
        cost = self.calculate_unit_value(t)
        return float(cost.minerals + cost.vespene)

    async def on_step(self, iteration: int) -> None:
        await super().on_step(iteration)
        if self.finished:
            return
        if self.phase == "nexus":
            if iteration >= 2:
                await self.client.debug_create_unit([[UnitTypeId.NEXUS, 1, self.mediator.get_own_nat, OWN]])
                self.mark, self.phase = iteration, "settle"
            return
        if self.phase == "settle":
            if iteration >= self.mark + SETTLE_STEPS:
                await self.client.debug_upgrade()
                await self.client.debug_upgrade()
                if self.candidate == "stalker":
                    self.army.blink.refresh = lambda stalkers, now: None  # Blink micro off
                self.mark, self.phase = iteration, "upgrade"
            return
        if self.phase == "upgrade":
            if iteration >= self.mark + UPGRADE_STEPS:
                await self.spawn()
                self.phase = "spawned"
            return
        if self.phase == "spawned":
            mine = [u for u in self.units if u.type_id in self.our_types]
            theirs = [u for u in self.enemy_bot.units if u.type_id in self.their_types]
            if len(mine) >= self.our_count and len(theirs) >= self.their_count:
                self.ours = {u.tag: u.type_id for u in mine}
                self.theirs = {u.tag: u.type_id for u in theirs}
                self.enemy_bot.attack_point = self.army.anchor
                self.watch_from = self.time
                self.phase = "watch"
            return
        alive_own = {u.tag for u in self.units}
        alive_enemy = {u.tag for u in self.enemy_bot.units}
        own_left = [t for t in self.ours if t in alive_own]
        enemy_left = [t for t in self.theirs if t in alive_enemy]
        if not own_left or not enemy_left or self.time - self.watch_from >= WATCH_S:
            self.judge(own_left, enemy_left)
            await self.end()

    async def spawn(self) -> None:
        anchor = self.army.anchor
        spot = anchor.towards(self.enemy_start_locations[0], ENEMY_DIST)
        _, enemy_group = CASES[self.case]
        enemy_value = sum(self.value_of(t) * n for t, n in enemy_group)
        ours: list[tuple[UnitTypeId, int]] = []
        for t, share in CANDIDATES[self.candidate]:
            ours.append((t, max(1, int(enemy_value * share // self.value_of(t)))))
        self.our_types = {t for t, _ in ours}
        self.their_types = {t for t, _ in enemy_group}
        self.our_count = sum(n for _, n in ours)
        self.their_count = sum(n for _, n in enemy_group)
        self.our_value = sum(self.value_of(t) * n for t, n in ours)
        self.enemy_value = enemy_value
        await self.client.debug_create_unit(
            [[t, n, anchor, OWN] for t, n in ours] + [[t, n, spot, ENEMY] for t, n in enemy_group]
        )
        self.log(
            f"setup {self.case} vs {self.candidate}: ours {[(t.name, n) for t, n in ours]} ({self.our_value:.0f}), "
            f"theirs {[(t.name, n) for t, n in enemy_group]} ({enemy_value:.0f})"
        )

    def judge(self, own_left: list[int], enemy_left: list[int]) -> None:
        lost = sum(self.value_of(t) for tag, t in self.ours.items() if tag not in own_left)
        killed = sum(self.value_of(t) for tag, t in self.theirs.items() if tag not in enemy_left)
        if not enemy_left and own_left:
            winner = "ours"
        elif not own_left and enemy_left:
            winner = "theirs"
        else:  # both or neither left: the smaller share of value lost
            winner = "ours" if lost / self.our_value < killed / self.enemy_value else "theirs"
        self.result = {
            "winner": winner, "lost": lost, "killed": killed, "seconds": round(self.time - self.watch_from, 1),
            "own_left": len(own_left), "enemy_left": len(enemy_left),
        }
        self.log(f"result {self.case} vs {self.candidate}: {self.result}")

    async def end(self) -> None:
        if not self.finished:
            self.finished = True
            await self.client.leave()


def play(case: str, candidate: str, run_no: int, map_name: str) -> dict:
    race, _ = CASES[case]
    enemy = StagedEnemy()
    ours = StagedCitadel(case, candidate, enemy)
    print(f"\n=== {case} vs {candidate}, run {run_no} on {map_name} ===", flush=True)
    try:
        run_bot_game(map_name, [Bot(Race.Protoss, ours, "Citadel"), Bot(race, enemy, "StagedEnemy")], None, TIME_LIMIT_S, 1000 + run_no)
    except Exception as e:  # noqa: BLE001
        if not ours.finished:
            print(f"CHECK {case} vs {candidate} run {run_no}: game error {e!r}", flush=True)
            return {}
    return ours.result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--case", choices=list(CASES) + ["all"], default="all")
    parser.add_argument("--candidate", choices=list(CANDIDATES) + ["all"], default="all")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--map", default="PylonAIE_v4")
    args = parser.parse_args()
    # the test is about the fight: home defense always engages
    army_module.home_engages = lambda level, needed, engaged, disengage_at: True
    cases = list(CASES) if args.case == "all" else [args.case]
    candidates = list(CANDIDATES) if args.candidate == "all" else [args.candidate]
    table: dict[tuple[str, str], list[dict]] = {}
    for case in cases:
        for candidate in candidates:
            table[(case, candidate)] = [r for n in range(1, args.runs + 1) if (r := play(case, candidate, n, args.map))]
    print()
    for case in cases:
        rows = []
        for candidate in candidates:
            results = table[(case, candidate)]
            if not results:
                rows.append((candidate, 0, 0, 0.0, 0.0))
                continue
            wins = sum(1 for r in results if r["winner"] == "ours")
            traded = mean(min(TRADED_CAP, r["killed"] / max(r["lost"], 1.0)) for r in results)
            rows.append((candidate, wins, len(results), traded, mean(r["seconds"] for r in results)))
        for candidate, wins, n, traded, secs in sorted(rows, key=lambda r: (-r[1], -r[3])):
            print(f"CHECK SUMMARY {case:<13} {candidate:<16} wins {wins}/{n}  traded {traded:6.2f}  mean {secs:5.1f} s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
