"""§4.8 ramp wall fallback.

python-sc2's `main_base_ramp.protoss_wall_pylon` / `protoss_wall_buildings` /
`protoss_wall_warpin` give the ramp wall; on unusual ramps they return None or an empty set, or
raise. ares's placement solver reads the first two unguarded during `AresBot.on_start` and
crashes when there are fewer than two wall buildings (docs/VERIFY_NOTES.md §11.5). So
`WallFallback.prepare` runs before `super().on_start()`:

1. It evaluates the helpers and caches `wall_ok`, logging one `WALL` line per game (§4.8.1, .4).
2. If the wall is not usable, it overrides the helpers' cached values on our own `Ramp` object
   with spots at the map edge that nothing can be built on. ares's solver then runs, finds no
   buildable wall spot, and its own fallback places the opener's `@ ramp` Pylon, Gateway and Core
   in its pre-calculated main-base formation as close to the ramp as it can (§4.8.2). No ares
   code is changed.

After `super().on_start()`, `after_start` picks the defended choke: the ramp top, or the
map-analyzer choke nearest the main when the ramp top is more than `WALL_RAMP_MAX_DIST` from our
start (§4.8.3). While `wall_ok` is False, `step` then:
- builds a Pylon and a Shield Battery within `WALL_BATTERY_MAX_DIST` of that choke, on the
  main's level, once the Cybernetics Core is ready;
- makes the first Zealot or Adept hold position `WALL_HOLD_OFFSET` from the choke toward the
  main until `WALL_HOLD_UNTIL_S`.
"""

from typing import TYPE_CHECKING, Optional

from cython_extensions import cy_pylon_matrix_covers
from loguru import logger
from sc2.game_info import Ramp
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.constants import (
    ORDER_REFRESH_S,
    WALL_BATTERY_MAX_DIST,
    WALL_CHOKE_MIN_DIST,
    WALL_HOLD_OFFSET,
    WALL_HOLD_UNTIL_S,
    WALL_RAMP_MAX_DIST,
)

if TYPE_CHECKING:
    from ares import AresBot

HOLDER_TYPES: frozenset[UnitTypeId] = frozenset({UnitTypeId.ZEALOT, UnitTypeId.ADEPT})
SEARCH_RADIUS: int = 3  # tiles searched around a wanted Pylon/Battery spot
SAME_LEVEL_Z: float = 0.5  # terrain heights closer than this are the same level


class WallFallback:
    def __init__(self, bot: "AresBot"):
        self.bot = bot
        self.wall_ok: bool = True
        self.reason: str = ""
        self.ramp_wrong: bool = False
        self.choke: Optional[Point2] = None
        self.hold_point: Optional[Point2] = None
        self.holder_tag: Optional[int] = None
        self.battery_ordered: bool = False
        self.ramp_pylon_ordered: bool = False
        self._last_hold_order: float = -ORDER_REFRESH_S

    # -- before super().on_start() -------------------------------------------------------------

    def prepare(self) -> bool:
        bot = self.bot
        ramp: Ramp = bot.main_base_ramp
        problems: list[str] = []
        pylon, buildings, warpin = None, frozenset(), None
        try:
            pylon = ramp.protoss_wall_pylon
        except Exception as e:
            problems.append(f"protoss_wall_pylon raised {e!r}")
        try:
            buildings = ramp.protoss_wall_buildings
        except Exception as e:
            problems.append(f"protoss_wall_buildings raised {e!r}")
        try:
            warpin = ramp.protoss_wall_warpin
        except Exception as e:
            problems.append(f"protoss_wall_warpin raised {e!r}")
        if pylon is None:
            problems.append("no wall pylon")
        if len(buildings) < 2:
            problems.append(f"{len(buildings)} wall buildings")
        if warpin is None:
            problems.append("no warp-in spot")
        top_dist = bot.start_location.distance_to(ramp.top_center)
        if top_dist > WALL_RAMP_MAX_DIST:
            self.ramp_wrong = True
            problems.append(f"ramp top {top_dist:.1f} from start")

        self.wall_ok = not problems
        self.reason = "; ".join(problems) if problems else "ok"
        logger.info(
            f"WALL map={bot.game_info.map_name} start={bot.start_location.rounded} "
            f"wall_ok={self.wall_ok} ({self.reason})"
        )
        if not self.wall_ok:
            self._make_wall_spots_unusable(ramp)
        return self.wall_ok

    def _make_wall_spots_unusable(self, ramp: Ramp) -> None:
        """Give ares's solver a wall Pylon and two wall buildings on unbuildable map-edge tiles.

        The helpers are `functools.cached_property`, so assigning the attribute replaces the
        cached value on this Ramp object only."""
        grid = self.bot.game_info.placement_grid
        spots: list[Point2] = []
        size = 3
        for x in range(1, grid.width - size, size + 1):
            for y in (1, grid.height - size - 1):
                tiles = [(x + dx, y + dy) for dx in range(size) for dy in range(size)]
                if all(grid[t] == 0 for t in tiles):
                    spots.append(Point2((x + 1.5, y + 1.5)))  # 3x3 centre; 2x2 fits inside too
                if len(spots) == 3:
                    break
            if len(spots) == 3:
                break
        ramp.protoss_wall_pylon = Point2((spots[0].x - 0.5, spots[0].y - 0.5))
        ramp.protoss_wall_buildings = frozenset(spots[1:3])
        ramp.protoss_wall_warpin = None
        logger.info(f"WALL fallback: ares wall spots moved to unbuildable {[s.rounded for s in spots]}")

    # -- after super().on_start() ------------------------------------------------------------

    def after_start(self) -> None:
        bot = self.bot
        choke: Point2 = bot.main_base_ramp.top_center
        if self.ramp_wrong:
            chokes = [
                c.center
                for c in bot.mediator.get_map_data_object.map_chokes
                if c.center.distance_to(bot.start_location) >= WALL_CHOKE_MIN_DIST
            ]
            if chokes:
                choke = min(chokes, key=lambda c: c.distance_to(bot.start_location))
        self.choke = Point2(choke)
        self.hold_point = self.choke.towards(bot.start_location, WALL_HOLD_OFFSET)
        if not self.wall_ok:
            logger.info(
                f"WALL fallback: choke={self.choke.rounded} "
                f"({'map-analyzer choke' if self.ramp_wrong else 'ramp top'}), "
                f"hold point={self.hold_point.rounded}"
            )

    # -- every army tick while the wall is not usable ------------------------------------------

    def step(self) -> Optional[int]:
        """Returns the holding unit's tag (for the army to leave alone), if any."""
        if self.wall_ok:
            return None
        self._build_battery()
        return self._hold()

    def _same_level(self, point: Point2) -> bool:
        bot = self.bot
        return abs(bot.get_terrain_z_height(point) - bot.get_terrain_z_height(bot.start_location)) < SAME_LEVEL_Z

    def _candidates(self, around: Point2, type_id: UnitTypeId) -> list[Point2]:
        """Buildable spots on the main's level near `around`, nearest first (2x2 centres sit on
        whole tiles)."""
        bot = self.bot
        cx, cy = round(around.x), round(around.y)
        out = []
        for dx in range(-SEARCH_RADIUS, SEARCH_RADIUS + 1):
            for dy in range(-SEARCH_RADIUS, SEARCH_RADIUS + 1):
                p = Point2((cx + dx, cy + dy))
                if (
                    p.distance_to(self.choke) <= WALL_BATTERY_MAX_DIST
                    and self._same_level(p)
                    and bot.mediator.can_place_structure(position=p, structure_type=type_id)
                ):
                    out.append(p)
        return sorted(out, key=lambda p: p.distance_to(around))

    def _build_battery(self) -> None:
        bot = self.bot
        if self.battery_ordered or bot.tech_requirement_progress(UnitTypeId.SHIELDBATTERY) < 1:
            return
        near_choke = [
            s
            for s in bot.mediator.get_own_structures_dict[UnitTypeId.SHIELDBATTERY]
            if s.distance_to(self.choke) <= WALL_BATTERY_MAX_DIST
        ]
        if near_choke:
            self.battery_ordered = True
            return
        pylons = bot.mediator.get_own_structures_dict[UnitTypeId.PYLON]
        height = bot.game_info.terrain_height.data_numpy
        powered = [
            p
            for p in self._candidates(self.choke.towards(bot.start_location, 2.5), UnitTypeId.SHIELDBATTERY)
            if cy_pylon_matrix_covers(p, pylons, height, pylon_build_progress=1.0)
        ]
        if powered:
            if bot.can_afford(UnitTypeId.SHIELDBATTERY) and self._order(UnitTypeId.SHIELDBATTERY, powered[0]):
                self.battery_ordered = True
                logger.info(
                    f"WALL fallback: Shield Battery at {powered[0].rounded}, "
                    f"{powered[0].distance_to(self.choke):.1f} from the choke, at {bot.time_formatted}"
                )
            return
        # no powered spot yet: a Pylon near the choke first (unless one is already coming)
        pending = [p for p in pylons if not p.is_ready and p.distance_to(self.choke) <= WALL_BATTERY_MAX_DIST + 2]
        if self.ramp_pylon_ordered and (pending or bot.not_started_but_in_building_tracker(UnitTypeId.PYLON)):
            return
        spots = self._candidates(self.choke.towards(bot.start_location, 4.5), UnitTypeId.PYLON)
        if spots and bot.can_afford(UnitTypeId.PYLON) and self._order(UnitTypeId.PYLON, spots[0]):
            self.ramp_pylon_ordered = True
            logger.info(f"WALL fallback: Pylon for the Battery at {spots[0].rounded}, at {bot.time_formatted}")

    def _order(self, type_id: UnitTypeId, pos: Point2) -> bool:
        mediator = self.bot.mediator
        worker = mediator.select_worker(target_position=pos, force_close=True)
        if worker is None:
            return False
        return bool(mediator.build_with_specific_worker(worker=worker, structure_type=type_id, pos=pos))

    def _hold(self) -> Optional[int]:
        bot = self.bot
        if bot.time > WALL_HOLD_UNTIL_S:
            if self.holder_tag is not None:
                logger.info(f"WALL fallback: holder released at {bot.time_formatted}")
                self.holder_tag = None
            return None
        holder = bot.units.find_by_tag(self.holder_tag) if self.holder_tag is not None else None
        if holder is None:
            candidates = [u for t in HOLDER_TYPES for u in bot.mediator.get_own_army_dict[t]]
            if not candidates:
                self.holder_tag = None
                return None
            holder = min(candidates, key=lambda u: u.distance_to(self.hold_point))
            self.holder_tag = holder.tag
            logger.info(f"WALL fallback: {holder.type_id.name} {holder.tag} holds {self.hold_point.rounded}")
        if (
            holder.distance_to(self.hold_point) > 1.0
            and not holder.is_attacking
            and bot.time - self._last_hold_order >= ORDER_REFRESH_S
        ):
            holder.move(self.hold_point)
            holder.hold_position(queue=True)
            self._last_hold_order = bot.time
        return holder.tag
