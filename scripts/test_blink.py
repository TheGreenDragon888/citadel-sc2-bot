"""M7 staged test: Blink Stalkers (docs/M7_PLAN.md K2; DESIGN.md §4.5.3).

    poetry run python scripts/test_blink.py [--case tempest|stalker|all] [--map PylonAIE_v4]

Each case is played twice, both with every upgrade (`client.debug_upgrade()` twice: Blink, +2
weapons and armour), once with Citadel's Blink micro and once with it switched off (no Stalker
counts as Blink-ready), each in its own local game
(realtime=False) of Citadel against `StagedEnemy`. Setup with debug commands (dev only; scripts/
is not in the ladder zip): a Nexus of ours at our natural, so the army's defensive position is the
natural moved toward the enemy; then our Stalkers there and the enemy group toward the enemy main.

- `tempest`: TEMPEST_STALKERS Stalkers against TEMPEST_COUNT Tempests on hold position
  TEMPEST_DIST from the defensive position, near enough to be a home threat home defense engages.
  Blink-in onto the Tempests is the rule under test.
- `stalker`: STALKER_STALKERS Stalkers against as many enemy Stalkers that attack-move onto the
  defensive position. Blink-back on low shields is the rule under test.

Each game is watched WATCH_S, or until one side has nothing left. Reported per game: blinks by kind
(back/in/finish), our units lost, enemy units killed, and the value traded (killed / lost, game-data
costs). FAIL if the Blink game of a case has no blink of the kind under test. The value comparison
with the no-Blink game is reported, not checked (one game each).
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
from sc2.ids.unit_typeid import UnitTypeId  # noqa: E402
from sc2.player import Bot  # noqa: E402
from sc2.position import Point2  # noqa: E402

from bot.constants import HOLD_ENGAGE_RADIUS  # noqa: E402
from bot.main import CitadelBot  # noqa: E402
from scripts.run_matches import run_bot_game  # noqa: E402

OWN, ENEMY = 1, 2
CASES = ("tempest", "stalker")
TEMPEST_STALKERS: int = 16
TEMPEST_COUNT: int = 3
TEMPEST_DIST: float = HOLD_ENGAGE_RADIUS + 0.5  # as test_outranged.py: a home threat (within ARMY_DEFEND_RADIUS of the natural)
STALKER_STALKERS: int = 10
STALKER_DIST: float = 20.0
SETTLE_STEPS: int = 24  # after our Nexus exists (the anchor moves to the natural)
UPGRADE_STEPS: int = 8  # after debug_upgrade, before the units spawn
WATCH_S: float = 45.0
TIME_LIMIT_S: int = 4 * 60
KIND_UNDER_TEST: dict[str, str] = {"tempest": "in", "stalker": "back"}


class StagedEnemy(BotAI):
    """Holds its Tempests in place; its Stalkers attack-move to `attack_point` once it is set."""

    def __init__(self) -> None:
        super().__init__()
        self.held: set[int] = set()
        self.attack_point: Optional[Point2] = None
        self.sent: set[int] = set()

    async def on_step(self, iteration: int) -> None:
        for t in self.units(UnitTypeId.TEMPEST):
            if t.tag not in self.held:
                t.hold_position()
                self.held.add(t.tag)
        if self.attack_point is not None:
            for s in self.units(UnitTypeId.STALKER):
                if s.tag not in self.sent:
                    s.attack(self.attack_point)
                    self.sent.add(s.tag)


class StagedCitadel(CitadelBot):
    def __init__(self, case: str, blink: bool, enemy: StagedEnemy):
        super().__init__()
        self.case, self.with_blink, self.enemy_bot = case, blink, enemy
        self.phase = "nexus"
        self.finished = False
        self.mark: int = 0
        self.watch_from: Optional[float] = None
        self.ours: set[int] = set()
        self.theirs: set[int] = set()
        self.lost: dict[int, UnitTypeId] = {}
        self.killed: dict[int, UnitTypeId] = {}
        self.result: dict = {}
        self.enemy_type = UnitTypeId.TEMPEST if case == "tempest" else UnitTypeId.STALKER

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
            if iteration >= self.mark + SETTLE_STEPS:
                await self.client.debug_upgrade()
                await self.client.debug_upgrade()
                if not self.with_blink:
                    self.army.blink.refresh = lambda stalkers: None  # the micro never sees a ready Stalker
                self.mark, self.phase = iteration, "upgrade"
            return
        if self.phase == "upgrade":
            if iteration >= self.mark + UPGRADE_STEPS:
                await self.spawn()
                self.phase = "spawned"
            return
        if self.phase == "spawned":
            mine = self.units(UnitTypeId.STALKER)
            # the enemy's units straight from its bot object (both bots run in this process), so fog
            # doesn't matter
            theirs = self.enemy_bot.units(self.enemy_type)
            want_mine = TEMPEST_STALKERS if self.case == "tempest" else STALKER_STALKERS
            want_theirs = TEMPEST_COUNT if self.case == "tempest" else STALKER_STALKERS
            if len(mine) >= want_mine and len(theirs) >= want_theirs:
                self.ours = {u.tag for u in mine}
                self.theirs = {u.tag for u in theirs}
                if self.case == "stalker":
                    self.enemy_bot.attack_point = self.army.anchor
                self.watch_from = self.time
                self.phase = "watch"
            return
        self.watch()
        if not (self.ours - set(self.lost)) or not (self.theirs - set(self.killed)) or self.time - self.watch_from >= WATCH_S:
            self.judge()
            await self.end()

    async def spawn(self) -> None:
        anchor = self.army.anchor
        toward = self.enemy_start_locations[0]
        if self.case == "tempest":
            spot = anchor.towards(toward, TEMPEST_DIST)
            await self.client.debug_create_unit(
                [[UnitTypeId.STALKER, TEMPEST_STALKERS, anchor, OWN], [UnitTypeId.TEMPEST, TEMPEST_COUNT, spot, ENEMY]]
            )
        else:
            spot = anchor.towards(toward, STALKER_DIST)
            await self.client.debug_create_unit(
                [[UnitTypeId.STALKER, STALKER_STALKERS, anchor, OWN], [UnitTypeId.STALKER, STALKER_STALKERS, spot, ENEMY]]
            )
        self.log(f"setup ({'Blink' if self.with_blink else 'no Blink'}): our Stalkers at {anchor.rounded}, enemy at {spot.rounded}")

    def watch(self) -> None:
        live_own = {u.tag: u.type_id for u in self.units}
        for tag in self.ours:
            if tag not in live_own and tag not in self.lost:
                self.lost[tag] = UnitTypeId.STALKER
        live_enemy = {u.tag for u in self.enemy_bot.units}
        for tag in self.theirs:
            if tag not in live_enemy and tag not in self.killed:
                self.killed[tag] = self.enemy_type

    def value(self, types: dict[int, UnitTypeId]) -> float:
        total = 0.0
        for t in types.values():
            cost = self.calculate_unit_value(t)
            total += cost.minerals + cost.vespene
        return total

    def judge(self) -> None:
        lost, killed = self.value(self.lost), self.value(self.killed)
        self.result = {
            "blinks": dict(self.army.blink.counts),
            "lost": len(self.lost), "killed": len(self.killed),
            "value_lost": lost, "value_killed": killed,
            "traded": killed / lost if lost else float("inf"),
            "seconds": round(self.time - self.watch_from, 1),
        }
        self.log(f"result: {self.result}")

    async def end(self) -> None:
        if not self.finished:
            self.finished = True
            await self.client.leave()


def play(case: str, blink: bool, map_name: str) -> dict:
    enemy = StagedEnemy()
    ours = StagedCitadel(case, blink, enemy)
    print(f"\n=== case {case} ({'Blink' if blink else 'no Blink'}) on {map_name} ===", flush=True)
    try:
        run_bot_game(map_name, [Bot(Race.Protoss, ours, "Citadel"), Bot(Race.Protoss, enemy, "StagedEnemy")], None, TIME_LIMIT_S)
    except Exception as e:  # noqa: BLE001
        if not ours.finished:
            print(f"CHECK case {case}: game error {e!r}")
            return {}
        print(f"CHECK case {case}: (connection closed after leaving: {e!r})")
    if not ours.result and ours.watch_from is not None:
        ours.judge()
    return ours.result


def run_case(case: str, map_name: str) -> bool:
    with_blink = play(case, True, map_name)
    without = play(case, False, map_name)
    kind = KIND_UNDER_TEST[case]
    blinked = with_blink.get("blinks", {}).get(kind, 0)
    ok = bool(with_blink) and bool(without) and blinked > 0
    print(f"CHECK {case}: {'PASS' if blinked > 0 else 'FAIL'}  the Blink game blinked '{kind}' ({with_blink.get('blinks')})")
    for name, r in (("Blink", with_blink), ("no Blink", without)):
        if r:
            print(
                f"CHECK {case}: {name:<8} lost {r['lost']} (value {r['value_lost']:.0f}), killed {r['killed']} "
                f"(value {r['value_killed']:.0f}), traded {r['traded']:.2f} in {r['seconds']} s"
            )
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
