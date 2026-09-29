"""Scouting (DESIGN.md §4.3). M2 has only the part the detectors need; M3 builds the rest.

`NaturalScout`: ares's `worker_scout` step circles the enemy main once and ares then returns the
idle probe to mining (docs/VERIFY_NOTES.md §11.4, `ares-sc2/src/ares/main.py:419-429`). When that
happens before the no-natural deadline, this takes the probe back (role SCOUTING), walks it to a
spot `NAT_SCOUT_STANDOFF` from the enemy natural toward the map centre, and keeps it there
until the detectors have what they need from the natural (§4.2 no-natural and "Pool before
the natural Hatchery"), then sends it home to mine. It leaves early below
`NAT_SCOUT_RETREAT_HP` of its HP+shield.
"""

from typing import TYPE_CHECKING, Optional

from ares.consts import UnitRole
from loguru import logger
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.constants import NAT_SCOUT_RETREAT_HP, NAT_SCOUT_STANDOFF, NO_NATURAL_GIVE_UP_S, ORDER_REFRESH_S

if TYPE_CHECKING:
    from ares import AresBot

    from bot.intel.detectors import Detectors


class NaturalScout:
    def __init__(self, bot: "AresBot", detectors: "Detectors"):
        self.bot = bot
        self.detectors = detectors
        self.tag: Optional[int] = None
        self.taken: bool = False
        self.done: bool = False
        self._last_order: float = -ORDER_REFRESH_S

    def update(self) -> None:
        if self.done:
            return
        bot = self.bot
        mediator = bot.mediator
        scouts = mediator.get_units_from_role(role=UnitRole.BUILD_RUNNER_SCOUT, unit_type=UnitTypeId.PROBE)
        if scouts:
            self.tag = scouts.first.tag  # ares still has it on its lap
            return
        if self.tag is None:
            return
        probe = bot.unit_tag_dict.get(self.tag)
        if probe is None:
            logger.info(f"SCOUT probe lost at {bot.time_formatted}")
            self.done = True
            return
        deadline = self.detectors.no_natural_deadline() + NO_NATURAL_GIVE_UP_S
        if self.detectors.natural_resolved or bot.time > deadline:
            self._release(probe, "natural check done" if self.detectors.natural_resolved else "past the deadline")
            return
        if probe.shield_health_percentage < NAT_SCOUT_RETREAT_HP:
            self._release(probe, f"HP+shield at {probe.shield_health_percentage:.0%}")
            return
        if not self.taken:
            self.taken = True
            mediator.assign_role(tag=probe.tag, role=UnitRole.SCOUTING)
            logger.info(f"SCOUT probe {probe.tag} to the enemy natural at {bot.time_formatted}")
        spot: Point2 = mediator.get_enemy_nat.towards(bot.game_info.map_center, NAT_SCOUT_STANDOFF)
        if probe.distance_to(spot) > 2 and bot.time - self._last_order >= ORDER_REFRESH_S:
            probe.move(spot)
            self._last_order = bot.time

    def _release(self, probe, why: str) -> None:
        self.done = True
        if self.taken:
            self.bot.mediator.assign_role(tag=probe.tag, role=UnitRole.GATHERING)
            logger.info(f"SCOUT probe back to mining at {self.bot.time_formatted}: {why}")
