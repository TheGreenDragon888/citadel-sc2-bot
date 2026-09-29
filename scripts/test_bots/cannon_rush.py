"""Cannon rush modelled on sharpy-sc2's SharpCannons (DESIGN.md §4.2, §8).

- A probe leaves at 0:00 for the opponent's base; a Pylon and a Forge go down at home.
- The rusher builds a Pylon at the target, then Photon Cannons in its power field once the
  Forge is done, then creeps forward with another Pylon and more Cannons.
- Variants (random unless given): `natural` covers the opponent's natural townhall spot;
  `main` goes behind the opponent's main mineral line.
- If the rusher dies, another probe takes over. After `CANNONS_BEFORE_GATES` Cannons have
  finished (or at `GATES_AT_S`), it adds Gateways and a Cybernetics Core and sends Zealots and
  Stalkers in groups of `ATTACK_GROUP`.
"""

from typing import Optional

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit

from scripts.test_bots.common import CheeseBot

VARIANTS: tuple[str, ...] = ("natural", "main")
WORKER_TARGET: int = 18
MAX_RUSH_PYLONS: int = 3
MAX_CANNONS: int = 8
CANNONS_PER_PYLON: int = 3
CANNONS_BEFORE_GATES: int = 4
GATES_AT_S: float = 240.0
MAX_GATES: int = 3
ATTACK_GROUP: int = 6
PYLON_POWER: float = 6.0  # a little inside the 6.5 power radius
BUILD_ABILITIES = {AbilityId.PROTOSSBUILD_PYLON, AbilityId.PROTOSSBUILD_PHOTONCANNON}


class CannonRushBot(CheeseBot):
    name = "cannon_rush"

    def __init__(self, seed=None, variant=None):
        super().__init__(seed, variant)
        self.rusher_tag: Optional[int] = None
        self.rush_pylons: list[Point2] = []  # positions where rush pylons were placed
        self.target: Optional[Point2] = None  # what the cannons should cover
        self.approach: Optional[Point2] = None  # where the first pylon goes

    async def on_start(self) -> None:
        self.client.game_step = 2
        if self.variant not in VARIANTS:
            self.variant = self.rng.choice(VARIANTS)
        if self.variant == "natural":
            self.target = self.their_natural
            # between the natural townhall spot and the opponent's main ramp side
            self.approach = self.target.towards(self.game_info.map_center, 7)
        else:
            line = self.their_mineral_line()
            self.target = line
            # behind the mineral line, away from the townhall
            self.approach = line.towards(self.their_main, -3.5)
        rusher = self.workers.closest_to(self.approach)
        self.rusher_tag = rusher.tag
        rusher.move(self.approach)
        await self.chat_send(f"cannon rush: {self.variant}")

    # -- helpers -------------------------------------------------------------------------------

    def busy_tags(self) -> set[int]:
        return {self.rusher_tag} if self.rusher_tag else set()

    def rusher(self) -> Optional[Unit]:
        unit = self.workers.find_by_tag(self.rusher_tag) if self.rusher_tag else None
        if unit is None and self.workers:
            unit = self.workers.closest_to(self.approach)
            self.rusher_tag = unit.tag
            unit.move(self.approach)
        return unit

    def rush_structures(self, type_id: UnitTypeId):
        return self.structures(type_id).filter(lambda s: s.distance_to(self.target) < 25)

    async def powered_spot(self, near: Point2) -> Optional[Point2]:
        pylons = self.rush_structures(UnitTypeId.PYLON).ready
        if not pylons:
            return None
        for _ in range(6):
            p = await self.find_placement(UnitTypeId.PHOTONCANNON, near, max_distance=4, placement_step=1)
            if p is not None and any(p.distance_to(py) <= PYLON_POWER for py in pylons):
                return p
            near = pylons.closest_to(near).position.towards(near, 2)
        return None

    # -- step ----------------------------------------------------------------------------------

    async def on_step(self, iteration: int) -> None:
        await self.macro_basics(WORKER_TARGET)
        rusher = self.rusher()
        forge_done = self.structures(UnitTypeId.FORGE).ready.exists
        cannons = self.rush_structures(UnitTypeId.PHOTONCANNON)
        home_pylons = self.structures(UnitTypeId.PYLON).filter(lambda s: s.distance_to(self.start_location) < 20)

        # home: a Pylon, then the Forge, then Pylons for supply
        if not home_pylons and not self.already_pending(UnitTypeId.PYLON) and self.can_afford(UnitTypeId.PYLON):
            await self.build(UnitTypeId.PYLON, near=self.start_location.towards(self.game_info.map_center, 6))
        elif home_pylons.ready and not self.structures(UnitTypeId.FORGE) and not self.already_pending(UnitTypeId.FORGE) and self.can_afford(UnitTypeId.FORGE):
            await self.build(UnitTypeId.FORGE, near=home_pylons.ready.first.position.towards(self.start_location, 2))
        elif self.supply_left < 3 and self.supply_cap < 200 and not self.already_pending(UnitTypeId.PYLON) and self.can_afford(UnitTypeId.PYLON) and home_pylons:
            await self.build(UnitTypeId.PYLON, near=self.start_location.towards(self.game_info.map_center, 8))

        # the rush
        if rusher is not None:
            await self.rush(rusher, forge_done, cannons)

        # the follow-up
        finished = cannons.ready.amount
        if finished >= CANNONS_BEFORE_GATES or self.time > GATES_AT_S:
            await self.gateway_play(home_pylons)

    async def rush(self, rusher: Unit, forge_done: bool, cannons) -> None:
        pylons = self.rush_structures(UnitTypeId.PYLON)
        if rusher.distance_to(self.approach) > 12 and not pylons:
            if rusher.is_idle or not rusher.is_moving:
                rusher.move(self.approach)
            return
        if rusher.orders and rusher.orders[0].ability.id in BUILD_ABILITIES:
            return
        # next pylon: the first at the approach point, later ones creep toward the target
        need_pylon = not pylons or (
            forge_done
            and len(pylons) < MAX_RUSH_PYLONS
            and cannons.amount >= CANNONS_PER_PYLON * len(pylons)
        )
        if need_pylon and not self.already_pending(UnitTypeId.PYLON) and self.can_afford(UnitTypeId.PYLON):
            anchor = pylons.closest_to(self.target).position.towards(self.target, 4) if pylons else self.approach
            p = await self.find_placement(UnitTypeId.PYLON, anchor, max_distance=6, placement_step=1)
            if p is not None:
                rusher.build(UnitTypeId.PYLON, p)
                return
        if forge_done and cannons.amount < MAX_CANNONS and self.can_afford(UnitTypeId.PHOTONCANNON):
            aim = self.target if self.variant == "main" else self.target.towards(self.approach, 3)
            p = await self.powered_spot(aim)
            if p is not None:
                rusher.build(UnitTypeId.PHOTONCANNON, p)
                return
        # waiting: stay near the pylons, out of the way
        if rusher.is_idle and pylons:
            rusher.move(pylons.closest_to(rusher).position.towards(self.target, -2))

    async def gateway_play(self, home_pylons) -> None:
        ready_pylons = home_pylons.ready
        if not ready_pylons:
            return
        gates = self.structures(UnitTypeId.GATEWAY)
        if gates.amount < MAX_GATES and self.can_afford(UnitTypeId.GATEWAY) and not self.already_pending(UnitTypeId.GATEWAY):
            await self.build(UnitTypeId.GATEWAY, near=ready_pylons.random.position, placement_step=3)
        if gates.ready and not self.structures(UnitTypeId.CYBERNETICSCORE) and not self.already_pending(UnitTypeId.CYBERNETICSCORE) and self.can_afford(UnitTypeId.CYBERNETICSCORE):
            await self.build(UnitTypeId.CYBERNETICSCORE, near=ready_pylons.random.position, placement_step=3)
        if self.structures(UnitTypeId.CYBERNETICSCORE) and self.gas_buildings.amount + self.already_pending(UnitTypeId.ASSIMILATOR) < 2 and self.can_afford(UnitTypeId.ASSIMILATOR):
            for geyser in self.vespene_geyser.closer_than(10, self.start_location):
                if not self.gas_buildings.closer_than(1, geyser):
                    await self.build(UnitTypeId.ASSIMILATOR, near=geyser)
                    break
        core_ready = self.structures(UnitTypeId.CYBERNETICSCORE).ready.exists
        for gate in gates.ready.idle:
            unit = UnitTypeId.STALKER if core_ready and self.can_afford(UnitTypeId.STALKER) else UnitTypeId.ZEALOT
            if self.can_afford(unit) and self.supply_left >= 2:
                gate.train(unit)
        army = self.units.of_type({UnitTypeId.ZEALOT, UnitTypeId.STALKER})
        idle = army.idle
        if len(idle) >= ATTACK_GROUP or (army and army.filter(lambda u: u.is_attacking)):
            for unit in idle:
                unit.attack(self.their_main)
