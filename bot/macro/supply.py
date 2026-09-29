"""Pylon timing after the opener (DESIGN.md §3 `macro/supply.py`).

During the opener the ares build runner builds Pylons itself (`AutoSupplyAtSupply` in
protoss_builds.yml). Afterwards Citadel does it, not ares's `AutoSupply`: that behavior asks
for up to half as many Pylons in progress as there are production structures but only ever
sends one worker at a time, and it returns True the whole time, which stops every behavior after
it in a MacroPlan. In M1 test games that froze probes and production from about 7:00.

Here the wanted headroom is `SUPPLY_BUFFER_PER_PRODUCER` supply per Nexus and production
structure (`SUPPLY_MIN_BUFFER` at least). Supply that Pylons under construction will add counts
toward it, and so does a Nexus under construction that finishes sooner than a new Pylon would
(supply provided and build times come from game data). The behavior returns True
(holding the rest of the plan) only while the headroom is below half and the Pylon it needs
can't be afforded yet.

ares only offers the Pylon spots it worked out at the start of the game, so a bot held to one
base runs out of them (a cannon-rush test game sat at 62/70 supply for 96 s). When ares has no
spot, `_fallback_spot` looks for a free 2x2 tile on the level of one of our bases, away from its
mineral line, the main ramp and enemy Cannons, and sends a probe there directly.
"""

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from ares.behaviors.macro import BuildStructure
from ares.consts import ALL_PRODUCTION_STRUCTURES, ID, TIME_ORDER_COMMENCED
from loguru import logger
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.constants import (
    MAIN_RADIUS,
    PYLON_FALLBACK_CANNON_CLEARANCE,
    PYLON_FALLBACK_MINERAL_CLEARANCE,
    PYLON_FALLBACK_RAMP_CLEARANCE,
    PYLON_STUCK_S,
    SAME_LEVEL_Z,
    SUPPLY_BUFFER_PER_PRODUCER,
    SUPPLY_MAX_PYLONS_AT_ONCE,
    SUPPLY_MIN_BUFFER,
)

if TYPE_CHECKING:
    from ares import AresBot
    from ares.managers.manager_mediator import ManagerMediator

SUPPLY_CAP_MAX: int = 200  # the game's supply limit


def _food_provided(bot: "AresBot", type_id: UnitTypeId) -> float:
    return bot.game_data.units[type_id.value]._proto.food_provided


@dataclass
class PylonTiming:
    # False: ares places Pylons at our main only (its other bases may be outside a held wall)
    other_bases: bool = True

    def execute(self, ai: "AresBot", config: dict, mediator: "ManagerMediator") -> bool:
        if ai.supply_cap >= SUPPLY_CAP_MAX:
            return False
        producers = len(ai.townhalls.ready) + len(
            ai.structures.filter(lambda s: s.type_id in ALL_PRODUCTION_STRUCTURES and s.is_ready)
        )
        buffer = max(SUPPLY_MIN_BUFFER, SUPPLY_BUFFER_PER_PRODUCER * producers)
        pylon_food = _food_provided(ai, UnitTypeId.PYLON)
        # a Nexus under construction only helps if it finishes before a Pylon ordered now would
        pylon_time = ai.game_data.units[UnitTypeId.PYLON.value].cost.time
        nexus_time = ai.game_data.units[UnitTypeId.NEXUS.value].cost.time
        nexuses_soon = [
            th for th in ai.townhalls.not_ready if (1 - th.build_progress) * nexus_time <= pylon_time
        ]
        coming = ai.structure_pending(UnitTypeId.PYLON) * pylon_food + len(
            nexuses_soon
        ) * _food_provided(ai, UnitTypeId.NEXUS)
        headroom = ai.supply_left + coming
        # the cap can't pass 200, so don't plan headroom beyond it
        buffer = min(buffer, SUPPLY_CAP_MAX - ai.supply_used)
        if headroom >= buffer:
            return False
        wanted = min(math.ceil((buffer - headroom) / pylon_food), SUPPLY_MAX_PYLONS_AT_ONCE)
        # a Pylon order that hasn't started after PYLON_STUCK_S is not counted as on its way:
        # ares keeps such orders for up to 120 s (building_manager.py:67), e.g. when enemy
        # Cannons cover the spot
        stuck = sum(
            1
            for info in mediator.get_building_tracker_dict.values()
            if info[ID] == UnitTypeId.PYLON and ai.time - info[TIME_ORDER_COMMENCED] > PYLON_STUCK_S
        )
        on_route = ai.not_started_but_in_building_tracker(UnitTypeId.PYLON) - stuck
        if on_route < wanted:
            placed = BuildStructure(
                ai.start_location, UnitTypeId.PYLON, max_on_route=wanted + stuck,
                find_alternative=self.other_bases,
            ).execute(ai, config, mediator)
            if not placed and ai.can_afford(UnitTypeId.PYLON):
                spot = _fallback_spot(ai, main_only=not self.other_bases)
                if spot is not None and (worker := mediator.select_worker(target_position=spot, force_close=True)):
                    mediator.build_with_specific_worker(worker=worker, structure_type=UnitTypeId.PYLON, pos=spot)
        return headroom < buffer / 2 and not ai.can_afford(UnitTypeId.PYLON)


FALLBACK_SCAN_EVERY_S: float = 2.0  # the search is a few thousand tile checks; not every tick
_last_scan: dict[int, float] = {}  # id(bot) -> game time of the last search


def _fallback_spot(ai: "AresBot", main_only: bool = False) -> Optional[Point2]:
    """A free Pylon spot on the level of one of our ready bases (or the main only), nearest
    the base first."""
    if ai.time - _last_scan.get(id(ai), -FALLBACK_SCAN_EVERY_S) < FALLBACK_SCAN_EVERY_S:
        return None
    _last_scan[id(ai)] = ai.time
    mediator = ai.mediator
    ramp = ai.main_base_ramp.top_center
    cannons = [s for s in ai.enemy_structures if s.type_id == UnitTypeId.PHOTONCANNON]
    bases = sorted(ai.townhalls.ready, key=lambda t: t.distance_to(ai.start_location))
    for th in bases[:1] if main_only else bases:
        z = ai.get_terrain_z_height(th)
        minerals = ai.mineral_field.closer_than(12, th)
        cx, cy = round(th.position.x), round(th.position.y)
        r = int(MAIN_RADIUS)
        candidates = sorted(
            (Point2((cx + dx, cy + dy)) for dx in range(-r, r + 1) for dy in range(-r, r + 1)),
            key=lambda p: p.distance_to(th),
        )
        for p in candidates:
            if (
                p.distance_to(th) < 5
                or abs(ai.get_terrain_z_height(p) - z) >= SAME_LEVEL_Z
                or p.distance_to(ramp) < PYLON_FALLBACK_RAMP_CLEARANCE
                or any(p.distance_to(m) < PYLON_FALLBACK_MINERAL_CLEARANCE for m in minerals)
                or any(p.distance_to(c) < PYLON_FALLBACK_CANNON_CLEARANCE for c in cannons)
                or not mediator.can_place_structure(position=p, structure_type=UnitTypeId.PYLON)
            ):
                continue
            logger.info(f"SUPPLY Pylon at {p.rounded}: ares has no Pylon spot left ({ai.time_formatted})")
            return p
    return None


def supply_behavior(bot: "AresBot", other_bases: bool = True) -> PylonTiming:
    """Pylons go in the main (another base when it's full, if `other_bases`), where they also
    power production."""
    return PylonTiming(other_bases=other_bases)
