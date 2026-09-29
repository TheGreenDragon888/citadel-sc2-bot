"""12-pool Zergling rush (DESIGN.md §4.2).

Spawning Pool at the first 200 minerals, drones to 13, an Extractor for Metabolic Boost
(drones leave gas once 100 gas is mined), one Queen, then Zerglings from every larva. The first
`FIRST_WAVE` Zerglings attack together; later ones join in groups of `REINFORCE_GROUP`. Zerglings
pick workers first when any are in reach.
"""

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId

from scripts.test_bots.common import WORKER_TYPES, CheeseBot

DRONE_TARGET: int = 13
FIRST_WAVE: int = 6
REINFORCE_GROUP: int = 4
QUEENS: int = 1


class TwelvePoolBot(CheeseBot):
    name = "twelve_pool"

    def __init__(self, seed=None, variant=None):
        super().__init__(seed, variant)
        self.first_wave_sent: bool = False
        self.gas_done: bool = False
        self.attackers: set[int] = set()

    async def on_start(self) -> None:
        self.client.game_step = 2

    async def on_step(self, iteration: int) -> None:
        pool = self.structures(UnitTypeId.SPAWNINGPOOL)
        hatch = self.townhalls.first if self.townhalls else None
        if hatch is None:
            return

        if not pool:
            if self.can_afford(UnitTypeId.SPAWNINGPOOL):
                await self.build(UnitTypeId.SPAWNINGPOOL, near=hatch.position.towards(self.game_info.map_center, 6))
            return  # nothing else before the pool

        # overlords, drones, gas, queen, lings
        if self.supply_left < 2 and self.supply_cap < 200 and not self.already_pending(UnitTypeId.OVERLORD):
            if self.can_afford(UnitTypeId.OVERLORD) and self.larva:
                self.larva.first.train(UnitTypeId.OVERLORD)
        if self.supply_workers + self.already_pending(UnitTypeId.DRONE) < DRONE_TARGET and self.larva and self.can_afford(UnitTypeId.DRONE):
            self.larva.first.train(UnitTypeId.DRONE)
        if not self.gas_buildings and not self.already_pending(UnitTypeId.EXTRACTOR) and self.can_afford(UnitTypeId.EXTRACTOR):
            geyser = self.vespene_geyser.closest_to(hatch)
            await self.build(UnitTypeId.EXTRACTOR, near=geyser)
        await self.handle_gas()
        if pool.ready and self.already_pending_upgrade(UpgradeId.ZERGLINGMOVEMENTSPEED) == 0 and self.can_afford(UpgradeId.ZERGLINGMOVEMENTSPEED):
            pool.ready.first.research(UpgradeId.ZERGLINGMOVEMENTSPEED)
        if pool.ready and len(self.units(UnitTypeId.QUEEN)) + self.already_pending(UnitTypeId.QUEEN) < QUEENS:
            if hatch.is_idle and self.can_afford(UnitTypeId.QUEEN):
                hatch.train(UnitTypeId.QUEEN)
        for queen in self.units(UnitTypeId.QUEEN).idle:
            if queen.energy >= 25:
                queen(AbilityId.EFFECT_INJECTLARVA, hatch)
        if pool.ready:
            for larva in self.larva:
                if self.can_afford(UnitTypeId.ZERGLING) and self.supply_left >= 1:
                    larva.train(UnitTypeId.ZERGLING)
        if self.iteration_mod(8):
            self.mine_idle()
        self.status()
        self.attack()

    async def handle_gas(self) -> None:
        extractors = self.gas_buildings.ready
        if not extractors:
            return
        extractor = extractors.first
        if not self.gas_done and (self.vespene >= 100 or self.already_pending_upgrade(UpgradeId.ZERGLINGMOVEMENTSPEED) > 0):
            self.gas_done = True
        if self.gas_done:
            for drone in self.workers.filter(lambda w: w.order_target == extractor.tag or w.is_carrying_vespene):
                drone.gather(self.mineral_field.closest_to(self.start_location))
        elif extractor.assigned_harvesters < 3:
            free = self.workers.filter(lambda w: w.is_gathering and not w.is_carrying_resource)
            if free:
                free.closest_to(extractor).gather(extractor)

    def attack(self) -> None:
        lings = self.units(UnitTypeId.ZERGLING)
        if not lings:
            return
        new = lings.tags_not_in(self.attackers)
        if not self.first_wave_sent:
            if len(new) >= FIRST_WAVE:
                self.first_wave_sent = True
                self.attackers |= set(new.tags)
        elif len(new) >= REINFORCE_GROUP:
            self.attackers |= set(new.tags)
        target = self.their_mineral_line()
        for ling in lings.tags_in(self.attackers):
            workers = self.enemy_units.filter(lambda e: e.type_id in WORKER_TYPES and e.distance_to(ling) < 4)
            if workers:
                if ling.weapon_cooldown == 0:
                    ling.attack(min(workers, key=self.hp))
            elif ling.is_idle:
                ling.attack(self.enemy_structures.closest_to(ling).position if ling.distance_to(target) < 6 and self.enemy_structures else target)
        rally = self.townhalls.first.position.towards(self.game_info.map_center, 5)
        for ling in lings.tags_not_in(self.attackers).idle:
            if ling.distance_to(rally) > 4:
                ling.move(rally)
