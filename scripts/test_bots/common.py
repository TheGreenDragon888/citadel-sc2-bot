"""Shared helpers for the scripted cheese bots (plain python-sc2, no ares).

These are test opponents for M2 (DESIGN.md §7, §8), written for Citadel because the sharpy-sc2
dummy bots would add a dependency. They live under scripts/, so they are not in the ladder zip.
"""

import random
from collections import Counter
from typing import Optional

from loguru import logger

from sc2.bot_ai import BotAI
from sc2.data import Race
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

WORKER_TYPES: frozenset[UnitTypeId] = frozenset({UnitTypeId.PROBE, UnitTypeId.SCV, UnitTypeId.DRONE})
WORKER_OF_RACE: dict[Race, UnitTypeId] = {
    Race.Protoss: UnitTypeId.PROBE,
    Race.Terran: UnitTypeId.SCV,
    Race.Zerg: UnitTypeId.DRONE,
}


class CheeseBot(BotAI):
    """Base class: a seeded RNG, the opponent's main/natural, and a little shared micro."""

    name: str = "cheese"

    def __init__(self, seed: Optional[int] = None, variant: Optional[str] = None):
        super().__init__()
        self.rng = random.Random(seed)
        self.variant: Optional[str] = variant

    # the opponent (Citadel) -------------------------------------------------------------------

    @property
    def their_main(self) -> Point2:
        return self.enemy_start_locations[0]

    @property
    def their_natural(self) -> Point2:
        main = self.their_main
        others = [p for p in self.expansion_locations_list if p.distance_to(main) > 5]
        return min(others, key=lambda p: p.distance_to(main))

    def their_third(self) -> Point2:
        main, nat = self.their_main, self.their_natural
        others = [p for p in self.expansion_locations_list if p.distance_to(main) > 5 and p.distance_to(nat) > 5]
        return min(others, key=lambda p: p.distance_to(nat))

    def their_mineral_line(self) -> Point2:
        fields = self.mineral_field.closer_than(12, self.their_main)
        if not fields:
            return self.their_main
        return fields.center

    # micro -----------------------------------------------------------------------------------

    @staticmethod
    def hp(unit: Unit) -> float:
        return unit.health + unit.shield

    def enemies_near(self, point: Point2, radius: float, ground_only: bool = True) -> Units:
        return self.enemy_units.filter(
            lambda e: e.distance_to(point) < radius and (not ground_only or not e.is_flying)
        )

    def focus_target(self, unit: Unit, candidates: Units, reach: float = 1.5) -> Optional[Unit]:
        """Lowest HP+shield enemy within weapon range (+`reach`), workers and army before
        structures; None if nothing is in reach."""
        in_reach = candidates.filter(lambda e: unit.distance_to(e) <= unit.radius + e.radius + unit.ground_range + reach)
        if not in_reach:
            return None
        return min(in_reach, key=lambda e: (e.is_structure, self.hp(e)))

    @property
    def worker_kind(self) -> UnitTypeId:
        return WORKER_OF_RACE[self.race]

    async def macro_basics(self, worker_target: int) -> None:
        """Workers up to `worker_target`, idle workers back to mining."""
        kind = self.worker_kind
        if self.townhalls and self.supply_workers + self.already_pending(kind) < worker_target:
            producers = self.larva if self.race == Race.Zerg else self.townhalls.ready.idle
            for producer in producers:
                if self.can_afford(kind) and self.supply_left > 0:
                    producer.train(kind)
                    break
        if self.iteration_mod(8):
            self.mine_idle()
        self.status()

    def busy_tags(self) -> set[int]:
        """Workers the bot is using for something else; `mine_idle` leaves them alone."""
        return set()

    def mine_idle(self) -> None:
        """Idle workers (except `busy_tags`) gather: gas buildings up to 3, else minerals near
        the closest townhall. python-sc2's `distribute_workers` would also grab a waiting
        builder or rusher."""
        if not self.townhalls:
            return
        busy = self.busy_tags()
        for worker in self.workers.idle:
            if worker.tag in busy:
                continue
            gas = [] if getattr(self, "gas_done", False) else [
                g for g in self.gas_buildings.ready if g.assigned_harvesters < g.ideal_harvesters
            ]
            if gas:
                worker.gather(gas[0])
                continue
            th = self.townhalls.closest_to(worker)
            fields = self.mineral_field.closer_than(10, th) or self.mineral_field
            if fields:
                worker.gather(fields.closest_to(th))

    def status(self, every_s: int = 30) -> None:
        """Log what this bot has every `every_s` game seconds (CHEESE lines, for test evidence)."""
        mark = int(self.time) // every_s
        if mark == getattr(self, "_status_mark", -1):
            return
        self._status_mark = mark
        own = Counter(u.type_id.name for u in self.all_own_units)
        near = sum(1 for s in self.structures if s.distance_to(self.their_main) < 40 or s.distance_to(self.their_natural) < 25)
        logger.info(
            f"CHEESE {self.name}{'/' + self.variant if self.variant else ''} t={self.time_formatted} "
            f"structures near opponent={near} own={dict(own)}"
        )

    def iteration_mod(self, n: int) -> bool:
        return int(self.state.game_loop / 2) % n == 0
