"""M7 staged test: High Templar, Psionic Storm and Archon morphs (docs/M7_PLAN.md K3).

    poetry run python scripts/test_templar.py [--case storm|own_units|morph_spent|morph_excess|morph_all|all]
        [--map PylonAIE_v4]

Each case is one local game (realtime=False) of Citadel against `StagedEnemy`, with every upgrade
(`client.debug_upgrade()` twice, so Storm is researched). Setup with debug commands (dev only;
scripts/ is not in the ladder zip): a Nexus of ours at our natural, so the army's defensive position
is the natural moved toward the enemy; then the units there (Zerglings after SPAWN_AFTER_S).

- `storm` (vs Zerg): STORM_STALKERS Stalkers and STORM_TEMPLAR Templar at full energy against
  STORM_LINGS Zerglings and STORM_HYDRAS Hydralisks that attack-move onto them. PASS: at least one
  Storm, and none of them with our units inside when it appears.
- `own_units` (vs Zerg): OWN_ZEALOTS Zealots spawned on top of OWN_LINGS Zerglings (they brawl in one
  clump) and OWN_TEMPLAR Templar at full energy next to it. PASS: no Storm with our units inside when
  it appears.
- `morph_spent` (vs Zerg): TEMPLAR_MAX_CASTERS Templar, two of them at SPENT_ENERGY. PASS: one Archon,
  not before TEMPLAR_MORPH_AFTER_S, and the two full Templar are still Templar.
- `morph_excess` (vs Zerg): TEMPLAR_MAX_CASTERS + 2 Templar at full energy. PASS: one Archon and
  TEMPLAR_MAX_CASTERS Templar left.
- `morph_all` (vs Protoss, no Storm research there): MORPH_ALL Templar. PASS: MORPH_ALL / 2 Archons.

"Our units inside" is our units within the Storm effect's radius (game data) of its spot on the first
step the effect is seen. Also reported per Storm: the enemy units inside it at any step while it lasts.
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
from sc2.bot_ai import BotAI  # noqa: E402
from sc2.data import Race  # noqa: E402
from sc2.ids.effect_id import EffectId  # noqa: E402
from sc2.ids.unit_typeid import UnitTypeId  # noqa: E402
from sc2.player import Bot  # noqa: E402
from sc2.position import Point2  # noqa: E402

from bot.constants import TEMPLAR_MAX_CASTERS, TEMPLAR_MORPH_AFTER_S  # noqa: E402
from bot.main import CitadelBot  # noqa: E402
from scripts.run_matches import run_bot_game  # noqa: E402

OWN, ENEMY = 1, 2
CASES = ("storm", "own_units", "morph_spent", "morph_excess", "morph_all")
STORM_STALKERS: int = 6
STORM_TEMPLAR: int = 2
STORM_LINGS: int = 16
STORM_HYDRAS: int = 8
STORM_DIST: float = 20.0
OWN_ZEALOTS: int = 8
OWN_LINGS: int = 16
OWN_TEMPLAR: int = 2
OWN_TEMPLAR_OFFSET: float = 5.0
SPENT_ENERGY: float = 10.0
MORPH_ALL: int = 4
FULL_ENERGY: float = 200.0  # above any Templar's maximum; the game caps it
ENERGY: int = 1  # debug_set_unit_value: 1 energy, 2 life, 3 shields (VERIFY_NOTES "M7 findings")
SETTLE_STEPS: int = 24
# Zerglings are spawned after ares's ling-rush window (`intel_manager.py:_check_for_enemy_rush`, 3:00)
# and Citadel's early-ling one, so no 12-pool plan pulls the army back to the main ramp
SPAWN_AFTER_S: float = 200.0
UPGRADE_STEPS: int = 8
WATCH_S: dict[str, float] = {
    "storm": 40.0, "own_units": 30.0, "morph_spent": TEMPLAR_MORPH_AFTER_S + 30.0, "morph_excess": 30.0,
    "morph_all": 30.0,
}
TIME_LIMIT_S: int = 5 * 60
ENEMY_RACE: dict[str, Race] = {case: Race.Zerg for case in CASES} | {"morph_all": Race.Protoss}


class StagedEnemy(BotAI):
    """Its units attack-move to `attack_point` once it is set."""

    def __init__(self) -> None:
        super().__init__()
        self.attack_point: Optional[Point2] = None
        self.sent: set[int] = set()

    async def on_step(self, iteration: int) -> None:
        if self.attack_point is None:
            return
        for u in self.units.of_type({UnitTypeId.ZERGLING, UnitTypeId.HYDRALISK}):
            if u.tag not in self.sent:
                u.attack(self.attack_point)
                self.sent.add(u.tag)


class StagedCitadel(CitadelBot):
    def __init__(self, case: str, enemy: StagedEnemy):
        super().__init__()
        self.case, self.enemy_bot = case, enemy
        self.phase = "nexus"
        self.finished = False
        self.mark: int = 0
        self.watch_from: Optional[float] = None
        self.storm_spots: set[Point2] = set()
        self.storms: list[dict] = []  # each new Storm: when, our units and enemy units inside
        self.hit: dict[Point2, set[int]] = {}  # Storm spot -> enemy tags inside it at some step
        self.archons_at: list[float] = []  # watch seconds at which each Archon was first seen
        self.archon_tags: set[int] = set()
        self.full_tags: set[int] = set()  # morph_spent: the Templar left at full energy
        self.result: dict = {}

    def log(self, text: str) -> None:
        print(f"CHECK [{self.time_formatted}] {text}", flush=True)

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
            late_enough = self.case not in ("storm", "own_units") or self.time >= SPAWN_AFTER_S
            if iteration >= self.mark + SETTLE_STEPS and late_enough:
                await self.client.debug_upgrade()
                await self.client.debug_upgrade()
                self.mark, self.phase = iteration, "upgrade"
            return
        if self.phase == "upgrade":
            if iteration >= self.mark + UPGRADE_STEPS:
                await self.spawn()
                self.phase = "spawned"
            return
        if self.phase == "spawned":
            templar = self.units(UnitTypeId.HIGHTEMPLAR)
            if len(templar) >= self.templar_count():
                await self.set_energy(templar)
                if self.case == "storm":
                    self.enemy_bot.attack_point = self.army.anchor
                self.watch_from = self.time
                self.phase = "watch"
            return
        self.watch()
        if self.time - self.watch_from >= WATCH_S[self.case] or self.done_early():
            self.judge()
            await self.end()

    def templar_count(self) -> int:
        return {
            "storm": STORM_TEMPLAR, "own_units": OWN_TEMPLAR, "morph_spent": TEMPLAR_MAX_CASTERS,
            "morph_excess": TEMPLAR_MAX_CASTERS + 2, "morph_all": MORPH_ALL,
        }[self.case]

    async def spawn(self) -> None:
        anchor = self.army.anchor
        toward = self.enemy_start_locations[0]
        n = self.templar_count()
        if self.case == "storm":
            spot = anchor.towards(toward, STORM_DIST)
            await self.client.debug_create_unit([
                [UnitTypeId.STALKER, STORM_STALKERS, anchor, OWN], [UnitTypeId.HIGHTEMPLAR, n, anchor, OWN],
                [UnitTypeId.ZERGLING, STORM_LINGS, spot, ENEMY], [UnitTypeId.HYDRALISK, STORM_HYDRAS, spot, ENEMY],
            ])
        elif self.case == "own_units":
            spot = anchor.towards(toward, OWN_TEMPLAR_OFFSET)
            await self.client.debug_create_unit([
                [UnitTypeId.ZEALOT, OWN_ZEALOTS, spot, OWN], [UnitTypeId.ZERGLING, OWN_LINGS, spot, ENEMY],
                [UnitTypeId.HIGHTEMPLAR, n, anchor, OWN],
            ])
        else:
            spot = anchor
            await self.client.debug_create_unit([[UnitTypeId.HIGHTEMPLAR, n, anchor, OWN]])
        self.log(f"setup {self.case}: anchor {anchor.rounded}, enemy at {spot.rounded}")

    async def set_energy(self, templar) -> None:
        tags = [u.tag for u in templar]
        await self.client.debug_set_unit_value(tags, ENERGY, FULL_ENERGY)
        if self.case == "morph_spent":
            spent = tags[:2]
            await self.client.debug_set_unit_value(spent, ENERGY, SPENT_ENERGY)
            self.full_tags = set(tags[2:])
        self.log(f"{len(tags)} Templar ready")

    def watch(self) -> None:
        now = self.time - self.watch_from
        spots: set[Point2] = set()
        for effect in self.state.effects:
            if effect.id != EffectId.PSISTORMPERSISTENT or not effect.is_mine:
                continue
            for p in effect.positions:
                spots.add(p)
                theirs = {u.tag for u in self.enemy_bot.units if u.distance_to(p) <= effect.radius + u.radius}
                if p in self.storm_spots:
                    self.hit[p] |= theirs
                    continue
                ours = [u for u in self.units if u.distance_to(p) <= effect.radius + u.radius]
                self.hit[p] = set(theirs)
                self.storms.append({"t": round(now, 1), "ours": len(ours), "theirs": len(theirs), "spot": p})
                self.log(f"Storm at {p.rounded}: {len(theirs)} enemy units inside, {len(ours)} of ours"
                         + (f" ({', '.join(u.type_id.name for u in ours)})" if ours else ""))
        for p in self.storm_spots - spots:
            self.log(f"Storm at {p.rounded} over: {len(self.hit.get(p, ()))} enemy units were inside at some point")
        self.storm_spots = spots
        for archon in self.units(UnitTypeId.ARCHON):
            if archon.tag not in self.archon_tags:
                self.archon_tags.add(archon.tag)
                self.archons_at.append(round(now, 1))
                self.log(f"Archon {len(self.archon_tags)} at +{now:.1f} s")

    def done_early(self) -> bool:
        if self.case == "morph_all":
            return len(self.archons_at) >= MORPH_ALL // 2 and not self.units(UnitTypeId.HIGHTEMPLAR)
        return False

    def judge(self) -> None:
        templar_left = {u.tag for u in self.units(UnitTypeId.HIGHTEMPLAR)}
        storms_on_us = sum(1 for s in self.storms if s["ours"])
        if self.case == "storm":
            ok = bool(self.storms) and not storms_on_us
            hit = sum(len(t) for t in self.hit.values())
            why = f"{len(self.storms)} Storms, {storms_on_us} with our units inside; {hit} enemy units inside them in all"
        elif self.case == "own_units":
            ok = not storms_on_us
            why = f"{len(self.storms)} Storms, {storms_on_us} with our units inside"
        elif self.case == "morph_spent":
            first = self.archons_at[0] if self.archons_at else None
            ok = (
                len(self.archons_at) == 1 and first is not None and first >= TEMPLAR_MORPH_AFTER_S
                and self.full_tags <= templar_left
            )
            why = f"Archons at {self.archons_at} s (after {TEMPLAR_MORPH_AFTER_S:.0f}), full Templar left {len(self.full_tags & templar_left)}/{len(self.full_tags)}"
        elif self.case == "morph_excess":
            ok = len(self.archons_at) == 1 and len(templar_left) == TEMPLAR_MAX_CASTERS
            why = f"Archons at {self.archons_at} s, {len(templar_left)} Templar left"
        else:
            ok = len(self.archons_at) == MORPH_ALL // 2 and not templar_left
            why = f"Archons at {self.archons_at} s, {len(templar_left)} Templar left"
        self.result = {
            "ok": ok, "why": why, "storms": self.storms, "archons_at": self.archons_at,
            "counted": dict(self.army.templar.counts),
        }
        self.log(f"result {self.case}: {'PASS' if ok else 'FAIL'}  {why}; Citadel counted {self.army.templar.counts}")

    async def end(self) -> None:
        if not self.finished:
            self.finished = True
            await self.client.leave()


def run_case(case: str, map_name: str) -> bool:
    enemy = StagedEnemy()
    ours = StagedCitadel(case, enemy)
    race = ENEMY_RACE[case]
    print(f"\n=== case {case} (vs {race.name}) on {map_name} ===", flush=True)
    try:
        run_bot_game(map_name, [Bot(Race.Protoss, ours, "Citadel"), Bot(race, enemy, "StagedEnemy")], None, TIME_LIMIT_S)
    except Exception as e:  # noqa: BLE001
        if not ours.finished:
            print(f"CHECK case {case}: game error {e!r}")
            return False
        print(f"CHECK case {case}: (connection closed after leaving: {e!r})")
    if not ours.result and ours.watch_from is not None:
        ours.judge()
    ok = bool(ours.result.get("ok"))
    print(f"CHECK case {case}: {'PASS' if ok else 'FAIL'}", flush=True)
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--case", choices=CASES + ("all",), default="all")
    parser.add_argument("--map", default="PylonAIE_v4")
    args = parser.parse_args()
    cases = CASES if args.case == "all" else (args.case,)
    results = {case: run_case(case, args.map) for case in cases}
    print("\n" + "\n".join(f"CHECK SUMMARY {case}: {'PASS' if ok else 'FAIL'}" for case, ok in results.items()))
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
