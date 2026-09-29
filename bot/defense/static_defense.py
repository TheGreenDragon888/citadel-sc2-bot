"""Shield Batteries and other structures a DefensePlan asks for (DESIGN.md §3
`defense/static_defense.py`, §4.2).

- Main batteries go within `MAIN_BATTERY_RAMP_DIST` of the ramp top on the main's level, behind
  the ramp holder (§4.2 12-pool, proxy); a Pylon near the ramp powers them if nothing does.
  Workers are sent directly (`mediator.build_with_specific_worker`), like wall_fallback.py.
- Natural batteries use ares's static-defence placement at the natural, with a Pylon there first.
- `gateways_needed`: more Gateways at the main through ares's BuildStructure.
- A finished enemy Cannon's range is taken out of ares's placement table
  (`mediator.get_placements_dict`, entries marked unavailable, restored when the Cannon dies), so
  new buildings go down out of its range (§4.2 cannon rush); build orders already aimed there
  are moved, and Nexus orders dropped (also while the plan holds expansions). Our Nexus at the
  natural is cancelled while under construction if a finished Cannon covers it.
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
    BUILDER_DANGER_RADIUS,
    CANNON_COVER_EXTRA,
    DEFENSE_ORDER_RETRY_S,
    MAIN_BATTERY_RAMP_DIST,
    MAIN_BATTERY_SEARCH_RADIUS,
    NATURAL_RADIUS,
    RAMP_CORRIDOR_HALF_WIDTH,
    RAMP_CORRIDOR_LENGTH,
    SAME_LEVEL_Z,
)
from bot.geometry import in_map
from bot.macro.production import reserve_for

if TYPE_CHECKING:
    from ares import AresBot
    from ares.behaviors.behavior import Behavior

    from bot.defense.defense_planner import DefensePlan, DefensePlanner

# enemy structures that make a spot deadly for a builder (on_worker_died)
STATIC_DEFENSE: frozenset[UnitTypeId] = frozenset(
    {UnitTypeId.PHOTONCANNON, UnitTypeId.BUNKER, UnitTypeId.SPINECRAWLER, UnitTypeId.PLANETARYFORTRESS}
)


class StaticDefense:
    def __init__(self, bot: "AresBot", planner: "DefensePlanner"):
        self.bot = bot
        self.planner = planner
        self._last_main_order: float = -DEFENSE_ORDER_RETRY_S
        self._blocked: dict[int, list[tuple]] = {}  # cannon tag -> placements we made unavailable
        self._blocked_at: dict[int, Point2] = {}  # cannon tag -> its position

    # -- per defense tick ------------------------------------------------------------------------

    def step(self, plan: "DefensePlan") -> None:
        """Direct actions: main batteries, cancelling the natural, cannon-range placements."""
        self._block_cannon_range()
        self._retarget_builds(plan)
        if plan.batteries_needed.get("main", 0) and not self._reserve_unmet(plan):
            self._main_batteries(plan.batteries_needed["main"])
        if plan.cancel_natural:
            self._cancel_natural()

    def behaviors(self, plan: "DefensePlan") -> list["Behavior"]:
        """ares behaviors for the defense MacroPlan: natural batteries (and their Pylon), and
        extra Gateways."""
        bot = self.bot
        out: list["Behavior"] = []
        need_nat = plan.batteries_needed.get("natural", 0)
        # while our unit holds the wall gap no probe gets out to the natural
        if need_nat and not plan.hold_wall_gap and bot.tech_requirement_progress(UnitTypeId.SHIELDBATTERY) >= 1:
            nat: Point2 = bot.mediator.get_own_nat
            pylons = [p for p in bot.mediator.get_own_structures_dict[UnitTypeId.PYLON] if p.distance_to(nat) < NATURAL_RADIUS]
            if not pylons:
                if not bot.not_started_but_in_building_tracker(UnitTypeId.PYLON) and bot.can_afford(UnitTypeId.PYLON):
                    out.append(BuildStructure(nat, UnitTypeId.PYLON, find_alternative=False))
            elif self._count_near(UnitTypeId.SHIELDBATTERY, nat, NATURAL_RADIUS) < need_nat and bot.can_afford(UnitTypeId.SHIELDBATTERY):
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

    def _reserve_unmet(self, plan: "DefensePlan") -> bool:
        """The plan's reserve holds the MacroPlan (`ReserveForUnit`): direct Battery/Pylon orders
        wait too."""
        reserve = reserve_for(self.bot, plan)
        return reserve is not None and reserve.holds(self.bot, self.bot.mediator)

    def _count_near(self, type_id: UnitTypeId, point: Point2, radius: float) -> int:
        return sum(1 for s in self.bot.mediator.get_own_structures_dict[type_id] if s.distance_to(point) <= radius)

    def _same_level(self, point: Point2) -> bool:
        bot = self.bot
        return abs(bot.get_terrain_z_height(point) - bot.get_terrain_z_height(bot.start_location)) < SAME_LEVEL_Z

    def _ramp_corridors(self) -> list[tuple[Point2, Point2]]:
        """Paths from the ramp top (and the wall gap) into the main that must stay open: a
        Battery right behind the gap sealed the ramp in a 12-pool test game."""
        bot = self.bot
        ramp = bot.main_base_ramp
        entries = [ramp.top_center]
        gap = getattr(bot, "wall", None) and bot.wall.gap
        if gap is not None:
            entries.append(gap)
        return [(e, e.towards(bot.start_location, RAMP_CORRIDOR_LENGTH)) for e in entries]

    @staticmethod
    def _distance_to_segment(p: Point2, a: Point2, b: Point2) -> float:
        ab = b - a
        length2 = ab.x ** 2 + ab.y ** 2
        if length2 == 0:
            return p.distance_to(a)
        t = max(0.0, min(1.0, ((p.x - a.x) * ab.x + (p.y - a.y) * ab.y) / length2))
        return p.distance_to(Point2((a.x + t * ab.x, a.y + t * ab.y)))

    def _candidates(self, around: Point2, anchor: Point2, type_id: UnitTypeId) -> list[Point2]:
        """Placeable spots on the main's level within MAIN_BATTERY_RAMP_DIST of `anchor`, clear
        of the ramp corridors, nearest to `around` first."""
        bot = self.bot
        size = BUILDING_SIZE_ENUM_TO_RADIUS[STRUCTURE_TO_BUILDING_SIZE[type_id]]
        corridors = self._ramp_corridors()
        cx, cy = round(around.x), round(around.y)
        out = []
        for dx in range(-MAIN_BATTERY_SEARCH_RADIUS, MAIN_BATTERY_SEARCH_RADIUS + 1):
            for dy in range(-MAIN_BATTERY_SEARCH_RADIUS, MAIN_BATTERY_SEARCH_RADIUS + 1):
                p = Point2((cx + dx, cy + dy))
                if (
                    in_map(bot, p)
                    and p.distance_to(anchor) <= MAIN_BATTERY_RAMP_DIST
                    and all(self._distance_to_segment(p, a, b) >= RAMP_CORRIDOR_HALF_WIDTH + size for a, b in corridors)
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
        if bot.time - self._last_main_order < DEFENSE_ORDER_RETRY_S:
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

    def _retarget_builds(self, plan: "DefensePlan") -> None:
        """Fix build orders the plan or an enemy Cannon has made pointless; ares would keep them
        (and a probe on them) for up to 120 s (`building_manager.py:67`).

        - A spot an enemy Cannon covers (placed before the Cannon was seen) gets a new ares
          placement, as ares itself does for a blocked spot (`building_manager.py:369-377`).
        - A Nexus order there, or any Nexus order while the plan forbids expanding, is dropped:
          with no target ares removes the order and returns the probe to mining
          (`building_manager.py:254-257`).
        """
        bot = self.bot
        cannons = [c for c in bot.enemy_structures if c.type_id == UnitTypeId.PHOTONCANNON]
        for info in bot.mediator.get_building_tracker_dict.values():
            target = info.get(TARGET)
            structure_id = info.get(ID)
            if not isinstance(target, Point2) or structure_id not in STRUCTURE_TO_BUILDING_SIZE:
                continue
            radius = BUILDING_SIZE_ENUM_TO_RADIUS[STRUCTURE_TO_BUILDING_SIZE[structure_id]]
            covered = any(
                target.distance_to(c) <= c.ground_range + c.radius + radius + CANNON_COVER_EXTRA for c in cannons
            )
            if structure_id == UnitTypeId.NEXUS:
                if covered or not plan.allow_expand:
                    info[TARGET] = None
                    logger.info(
                        f"DEFENSE Nexus order at {target.rounded} dropped: "
                        f"{'an enemy Cannon covers it' if covered else 'the plan holds expansions'} ({bot.time_formatted})"
                    )
                continue
            if not covered:
                continue
            new = bot.mediator.request_building_placement(base_location=bot.start_location, structure_type=structure_id)
            if new is not None:
                info[TARGET] = new
                logger.info(
                    f"DEFENSE {structure_id.name} order moved from {target.rounded} to {new.rounded}: "
                    f"an enemy Cannon covers it ({bot.time_formatted})"
                )

    def on_worker_died(self, tag: int, died_at: Point2) -> None:
        """A builder died near enemy static defense or enemy units (around its target or where
        it fell): drop its order (no target, which ares removes) instead of ares sending the
        next probe the same way (`building_manager.py:393-411`; a natural-cannon test game lost
        a probe every few seconds that way). With static defense near the target the spot is
        also taken out of ares's placement table, since that danger stays; otherwise it isn't,
        as units move on (a ramp or wall spot must stay usable). Any other builder death is
        left to ares."""
        bot = self.bot
        info = bot.mediator.get_building_tracker_dict.get(tag)
        if info is None or not isinstance(info.get(TARGET), Point2):
            return
        target: Point2 = info[TARGET]

        def near(u) -> bool:
            return u.distance_to(target) < BUILDER_DANGER_RADIUS or u.distance_to(died_at) < BUILDER_DANGER_RADIUS

        static = [s for s in bot.enemy_structures if s.type_id in STATIC_DEFENSE and near(s)]
        units = [u for u in bot.enemy_units if near(u)]
        if not static and not units:
            return
        info[TARGET] = None
        if info[ID] == UnitTypeId.NEXUS:
            self.planner.expansion_failed()
        blocked = 0
        if any(s.distance_to(target) < BUILDER_DANGER_RADIUS for s in static):
            for sizes in bot.mediator.get_placements_dict.values():
                for spots in sizes.values():
                    spot = spots.get(target)
                    if spot is not None and spot.get("available"):
                        spot["available"] = False
                        blocked += 1
        cause = f"enemy {static[0].type_id.name}" if static else f"{len(units)} enemy units"
        logger.info(
            f"DEFENSE builder for {info[ID].name} died on its way to {target.rounded} near {cause} "
            f"({bot.time_formatted}): order dropped{', spot blocked' if blocked else ''}"
        )

    def _block_cannon_range(self) -> None:
        bot = self.bot
        cannons = {c.tag: c for c in bot.enemy_structures if c.type_id == UnitTypeId.PHOTONCANNON}
        placements: dict = bot.mediator.get_placements_dict
        # restore spots of cannons that are gone: not listed, and their spot in vision (a
        # Cannon can drop out of the list for a step while it is fogged)
        gone = [t for t in self._blocked if t not in cannons and bot.is_visible(self._blocked_at[t])]
        for tag in gone:
            self._blocked_at.pop(tag)
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
            self._blocked_at[tag] = cannon.position
            if blocked:
                logger.info(
                    f"DEFENSE {len(blocked)} building spots in range of the enemy Cannon at "
                    f"{cannon.position.rounded} marked unavailable"
                )
