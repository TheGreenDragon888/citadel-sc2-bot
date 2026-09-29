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
"""

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ares.behaviors.macro import BuildStructure
from ares.consts import ALL_PRODUCTION_STRUCTURES
from sc2.ids.unit_typeid import UnitTypeId

from bot.constants import SUPPLY_BUFFER_PER_PRODUCER, SUPPLY_MAX_PYLONS_AT_ONCE, SUPPLY_MIN_BUFFER

if TYPE_CHECKING:
    from ares import AresBot
    from ares.managers.manager_mediator import ManagerMediator

SUPPLY_CAP_MAX: int = 200  # the game's supply limit


def _food_provided(bot: "AresBot", type_id: UnitTypeId) -> float:
    return bot.game_data.units[type_id.value]._proto.food_provided


@dataclass
class PylonTiming:
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
        on_route = ai.not_started_but_in_building_tracker(UnitTypeId.PYLON)
        if on_route < wanted:
            BuildStructure(
                ai.start_location, UnitTypeId.PYLON, max_on_route=wanted
            ).execute(ai, config, mediator)
        return headroom < buffer / 2 and not ai.can_afford(UnitTypeId.PYLON)


def supply_behavior(bot: "AresBot") -> PylonTiming:
    """Pylons go in the main (another base when it's full), where they also power production."""
    return PylonTiming()
