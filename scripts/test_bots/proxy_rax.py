"""Proxy Barracks Marine rush (DESIGN.md §4.2; like sharpy-sc2's RustyMarines).

Two SCVs leave at 0:00 for a hidden spot near the opponent's natural (their third base, or a
point toward the map centre; random unless given as the variant `third`/`center`) and build
`RAX` Barracks there as soon as each is affordable. A Supply Depot goes down at home. Marines
come from every Barracks; the first `FIRST_WAVE` attack together and later ones stream in. SCVs
go to 16. The builders return home to mine once the Barracks are placed.
"""

from typing import Optional

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit

from scripts.test_bots.common import CheeseBot

VARIANTS: tuple[str, ...] = ("third", "center")
RAX: int = 2
EXTRA_RAX_AT_S: float = 150.0  # a third Barracks at home when affordable after this
WORKER_TARGET: int = 16
SCVS_BEFORE_RAX: int = 13
FIRST_WAVE: int = 4
BUILDERS: int = 2


class ProxyRaxBot(CheeseBot):
    name = "proxy_rax"

    def __init__(self, seed=None, variant=None):
        super().__init__(seed, variant)
        self.proxy: Optional[Point2] = None
        self.builders: set[int] = set()
        self.wave_sent: bool = False

    async def on_start(self) -> None:
        self.client.game_step = 2
        if self.variant not in VARIANTS:
            self.variant = self.rng.choice(VARIANTS)
        nat = self.their_natural
        if self.variant == "third":
            self.proxy = self.their_third().towards(nat, 4)
        else:
            self.proxy = nat.towards(self.game_info.map_center, 30)
        self.proxy = await self.find_placement(UnitTypeId.BARRACKS, self.proxy, max_distance=15, placement_step=2) or self.proxy
        for worker in self.workers.closest_n_units(self.proxy, BUILDERS):
            self.builders.add(worker.tag)
            worker.move(self.proxy)

    def busy_tags(self) -> set[int]:
        return set(self.builders)

    async def on_step(self, iteration: int) -> None:
        builders = self.workers.tags_in(self.builders)
        proxy_rax = self.structures(UnitTypeId.BARRACKS).filter(lambda s: s.distance_to(self.proxy) < 20)
        placed = len(proxy_rax) + sum(1 for w in builders if self.ordered_rax(w))
        # the Barracks come first: SCVs stop at SCVS_BEFORE_RAX until both are placed
        await self.macro_basics(WORKER_TARGET if placed >= RAX else SCVS_BEFORE_RAX)

        # proxy barracks
        if placed < RAX and self.can_afford(UnitTypeId.BARRACKS):
            idle_builder = next((w for w in builders if not self.ordered_rax(w) and not w.is_constructing_scv), None)
            if idle_builder is not None:
                p = await self.find_placement(UnitTypeId.BARRACKS, self.proxy, max_distance=12, placement_step=3)
                if p is not None:
                    idle_builder.build(UnitTypeId.BARRACKS, p)
        elif placed >= RAX:
            for w in builders:
                if w.is_idle:
                    self.builders.discard(w.tag)  # mine_idle sends it home to mine
        for w in builders:
            if w.is_idle and w.distance_to(self.proxy) > 6 and placed < RAX:
                w.move(self.proxy)

        # home: supply, an extra barracks later
        depots = self.structures(UnitTypeId.SUPPLYDEPOT)
        if placed >= RAX and self.supply_left < 3 and self.supply_cap < 200 and not self.already_pending(UnitTypeId.SUPPLYDEPOT) and self.can_afford(UnitTypeId.SUPPLYDEPOT):
            await self.build(UnitTypeId.SUPPLYDEPOT, near=self.start_location.towards(self.game_info.map_center, 7 + 2 * len(depots)), placement_step=2)
        if (
            self.time > EXTRA_RAX_AT_S
            and len(self.structures(UnitTypeId.BARRACKS)) + self.already_pending(UnitTypeId.BARRACKS) < RAX + 1
            and not proxy_rax.not_ready
            and self.can_afford(UnitTypeId.BARRACKS)
            and depots.ready
        ):
            await self.build(UnitTypeId.BARRACKS, near=self.start_location.towards(self.game_info.map_center, 9), placement_step=3)

        for rax in self.structures(UnitTypeId.BARRACKS).ready.idle:
            if self.can_afford(UnitTypeId.MARINE) and self.supply_left >= 1:
                rax.train(UnitTypeId.MARINE)
        self.attack()

    @staticmethod
    def ordered_rax(worker: Unit) -> bool:
        return any(o.ability.exact_id == AbilityId.TERRANBUILD_BARRACKS for o in worker.orders)

    def attack(self) -> None:
        marines = self.units(UnitTypeId.MARINE)
        if not marines:
            return
        if not self.wave_sent and len(marines) >= FIRST_WAVE:
            self.wave_sent = True
        target = self.their_main
        for marine in marines:
            if self.wave_sent:
                if marine.is_idle:
                    enemies = self.enemy_units.not_flying.closer_than(12, marine) or self.enemy_structures.closer_than(12, marine)
                    marine.attack(enemies.closest_to(marine).position if enemies else target)
            elif marine.is_idle and marine.distance_to(self.proxy) > 5:
                marine.move(self.proxy)
