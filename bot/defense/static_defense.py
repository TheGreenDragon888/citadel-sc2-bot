"""Shield Batteries and other structures a DefensePlan asks for (DESIGN.md §3
`defense/static_defense.py`, §4.2).

- Main batteries go within `MAIN_BATTERY_RAMP_DIST` of the ramp top on the main's level, behind
  the ramp holder (§4.2 12-pool, proxy); a Pylon near the ramp powers them if nothing does.
  Workers are sent directly (`mediator.build_with_specific_worker`), like wall_fallback.py.
- Natural batteries use ares's static-defence placement at the natural, with a Pylon there first.
- `gateways_needed`: more Gateways at the main through ares's BuildStructure.
- A finished enemy Cannon's range is taken out of ares's placement table
  (`mediator.get_placements_dict`, entries marked unavailable, restored when the Cannon dies), so
  new buildings go down out of its range (§4.2 cannon rush). Our Nexus at the natural is
  cancelled while under construction if a finished Cannon covers it.
"""

from typing import TYPE_CHECKING, Optional

from ares.behaviors.macro import BuildStructure
from ares.consts import BUILDING_SIZE_ENUM_TO_RADIUS, ID, TARGET
from ares.dicts.structure_to_building_size import STRUCTURE_TO_BUILDING_SIZE
from cython_extensions import cy_pylon_matrix_covers
from loguru import logger
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.constants import (
    CANNON_COVER_EXTRA,
    MAIN_BATTERY_RAMP_DIST,
    ORDER_REFRESH_S,
    SAME_LEVEL_Z,
)

if TYPE_CHECKING:
    from ares import AresBot
    from ares.behaviors.behavior import Behavior

    from bot.defense.defense_planner import DefensePlan, DefensePlanner

NAT_RADIUS: float = 14.0  # structures this close to the natural spot are "at the natural"
SEARCH_RADIUS: int = 4
ORDER_RETRY_S: float = 20.0  # a worker sent to build that hasn't started by then may be re-sent


class StaticDefense:
    def __init__(self, bot: "AresBot", planner: "DefensePlanner"):
        self.bot = bot
        self.planner = planner
        self._last_main_order: float = -ORDER_RETRY_S
        self._blocked: dict[int, list[tuple]] = {}  # cannon tag -> placements we made unavailable

    # -- per defense tick ------------------------------------------------------------------------

    def step(self, plan: "DefensePlan") -> None:
        """Direct actions: main batteries, cancelling the natural, cannon-range placements."""
        self._block_cannon_range()
        self._retarget_builds_in_cannon_range()
        if plan.batteries_needed.get("main", 0):
            self._main_batteries(plan.batteries_needed["main"])
        if plan.cancel_natural:
            self._cancel_natural()

    def behaviors(self, plan: "DefensePlan") -> list["Behavior"]:
        """ares behaviors for the defense MacroPlan: natural batteries (and their Pylon), and
        extra Gateways."""
        bot = self.bot
        out: list["Behavior"] = []
        need_nat = plan.batteries_needed.get("natural", 0)
        if need_nat and bot.tech_requirement_progress(UnitTypeId.SHIELDBATTERY) >= 1:
            nat: Point2 = bot.mediator.get_own_nat
            pylons = [p for p in bot.mediator.get_own_structures_dict[UnitTypeId.PYLON] if p.distance_to(nat) < NAT_RADIUS]
            if not pylons:
                if not bot.not_started_but_in_building_tracker(UnitTypeId.PYLON) and bot.can_afford(UnitTypeId.PYLON):
                    out.append(BuildStructure(nat, UnitTypeId.PYLON, find_alternative=False))
            elif self._count_near(UnitTypeId.SHIELDBATTERY, nat, NAT_RADIUS) < need_nat and bot.can_afford(UnitTypeId.SHIELDBATTERY):
                out.append(BuildStructure(nat, UnitTypeId.SHIELDBATTERY, static_defence=True, find_alternative=False))
        if plan.gateways_needed:
            gates = (
                len(bot.mediator.get_own_structures_dict[UnitTypeId.GATEWAY])
                + len(bot.mediator.get_own_structures_dict[UnitTypeId.WARPGATE])
                + bot.mediator.get_building_counter[UnitTypeId.GATEWAY]
            )
            if gates < plan.gateways_needed and bot.can_afford(UnitTypeId.GATEWAY):
                out.append(BuildStructure(bot.start_location, UnitTypeId.GATEWAY))
        return out

    # -- main batteries near the ramp ----------------------------------------------------------------

    def _count_near(self, type_id: UnitTypeId, point: Point2, radius: float) -> int:
        return sum(1 for s in self.bot.mediator.get_own_structures_dict[type_id] if s.distance_to(point) <= radius)

    def _same_level(self, point: Point2) -> bool:
        bot = self.bot
        return abs(bot.get_terrain_z_height(point) - bot.get_terrain_z_height(bot.start_location)) < SAME_LEVEL_Z

    def _candidates(self, around: Point2, anchor: Point2, type_id: UnitTypeId) -> list[Point2]:
        """Placeable spots on the main's level within MAIN_BATTERY_RAMP_DIST of `anchor`,
        nearest to `around` first."""
        bot = self.bot
        cx, cy = round(around.x), round(around.y)
        out = []
        for dx in range(-SEARCH_RADIUS, SEARCH_RADIUS + 1):
            for dy in range(-SEARCH_RADIUS, SEARCH_RADIUS + 1):
                p = Point2((cx + dx, cy + dy))
                if (
                    p.distance_to(anchor) <= MAIN_BATTERY_RAMP_DIST
                    and self._same_level(p)
                    and bot.mediator.can_place_structure(position=p, structure_type=type_id)
                    and not self.planner.cannon_covers(p, 1.0)
                ):
                    out.append(p)
        return sorted(out, key=lambda p: p.distance_to(around))

    def _main_batteries(self, wanted: int) -> None:
        bot = self.bot
        if bot.tech_requirement_progress(UnitTypeId.SHIELDBATTERY) < 1:
            return
        if bot.time - self._last_main_order < ORDER_RETRY_S:
            return
        ramp_top: Point2 = bot.main_base_ramp.top_center
        have = self._count_near(UnitTypeId.SHIELDBATTERY, ramp_top, MAIN_BATTERY_RAMP_DIST + 1)
        if have >= wanted:
            return
        pylons = bot.mediator.get_own_structures_dict[UnitTypeId.PYLON]
        height = bot.game_info.terrain_height.data_numpy
        behind = ramp_top.towards(bot.start_location, 3.0)
        powered = [
            p for p in self._candidates(behind, ramp_top, UnitTypeId.SHIELDBATTERY)
            if cy_pylon_matrix_covers(p, pylons, height, pylon_build_progress=1.0)
        ]
        if powered:
            if bot.can_afford(UnitTypeId.SHIELDBATTERY) and self._order(UnitTypeId.SHIELDBATTERY, powered[0]):
                self._last_main_order = bot.time
                logger.info(f"DEFENSE Shield Battery in the main at {powered[0].rounded}, {bot.time_formatted}")
            return
        if any(not p.is_ready and p.distance_to(ramp_top) < MAIN_BATTERY_RAMP_DIST + 3 for p in pylons):
            return  # its Pylon is on the way
        spots = self._candidates(ramp_top.towards(bot.start_location, 4.5), ramp_top, UnitTypeId.PYLON)
        if spots and bot.can_afford(UnitTypeId.PYLON) and self._order(UnitTypeId.PYLON, spots[0]):
            self._last_main_order = bot.time
            logger.info(f"DEFENSE Pylon for the main battery at {spots[0].rounded}, {bot.time_formatted}")

    def _order(self, type_id: UnitTypeId, pos: Point2) -> bool:
        mediator = self.bot.mediator
        worker = mediator.select_worker(target_position=pos, force_close=True)
        if worker is None:
            return False
        return bool(mediator.build_with_specific_worker(worker=worker, structure_type=type_id, pos=pos))

    # -- cannon rush ---------------------------------------------------------------------------------

    def _cancel_natural(self) -> None:
        bot = self.bot
        nat = bot.mediator.get_own_nat
        for th in bot.townhalls:
            if th.distance_to(nat) < 3 and not th.is_ready:
                logger.info(f"DEFENSE cancelling the natural Nexus at {bot.time_formatted}: a finished Cannon covers it")
                th(AbilityId.CANCEL_BUILDINPROGRESS)

    def _retarget_builds_in_cannon_range(self) -> None:
        """A build order placed before an enemy Cannon was seen can point into its range; ares
        would keep sending probes there. Give it a new ares placement instead, as ares itself
        does for a blocked spot (`building_manager.py:383-390`)."""
        bot = self.bot
        cannons = [c for c in bot.enemy_structures if c.type_id == UnitTypeId.PHOTONCANNON]
        if not cannons:
            return
        for info in bot.mediator.get_building_tracker_dict.values():
            target = info.get(TARGET)
            structure_id = info.get(ID)
            if not isinstance(target, Point2) or structure_id not in STRUCTURE_TO_BUILDING_SIZE:
                continue
            radius = BUILDING_SIZE_ENUM_TO_RADIUS[STRUCTURE_TO_BUILDING_SIZE[structure_id]]
            if not any(target.distance_to(c) <= c.ground_range + c.radius + radius + CANNON_COVER_EXTRA for c in cannons):
                continue
            new = bot.mediator.request_building_placement(base_location=bot.start_location, structure_type=structure_id)
            if new is not None:
                info[TARGET] = new
                logger.info(
                    f"DEFENSE {structure_id.name} order moved from {target.rounded} to {new.rounded}: "
                    f"an enemy Cannon covers it ({bot.time_formatted})"
                )

    def _block_cannon_range(self) -> None:
        bot = self.bot
        cannons = {c.tag: c for c in bot.enemy_structures if c.type_id == UnitTypeId.PHOTONCANNON}
        placements: dict = bot.mediator.get_placements_dict
        # restore spots of cannons that are gone
        for tag in [t for t in self._blocked if t not in cannons]:
            for base, size, pos in self._blocked.pop(tag):
                info = placements.get(base, {}).get(size, {}).get(pos)
                if info is not None and not info.get("building_tag"):
                    info["available"] = True
        for tag, cannon in cannons.items():
            if tag in self._blocked:
                continue
            reach = cannon.ground_range + cannon.radius + CANNON_COVER_EXTRA
            blocked = []
            for base, sizes in placements.items():
                if base.distance_to(cannon) > 40:
                    continue
                for size, spots in sizes.items():
                    radius = BUILDING_SIZE_ENUM_TO_RADIUS[size]
                    for pos, info in spots.items():
                        if info.get("available") and pos.distance_to(cannon) <= reach + radius:
                            info["available"] = False
                            blocked.append((base, size, pos))
            self._blocked[tag] = blocked
            if blocked:
                logger.info(
                    f"DEFENSE {len(blocked)} building spots in range of the enemy Cannon at "
                    f"{cannon.position.rounded} marked unavailable"
                )
