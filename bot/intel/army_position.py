"""ARMY_OUT_OF_POSITION (DESIGN.md §4.4 row 17, §4.6 conditions 1-2): §3's "out-of-position"
detector, in its own file because it needs path lengths.

The remembered enemy army is ares's army cache (`mediator.get_cached_enemy_army`: every enemy
unit seen and not known dead), as for §4.7 in M4; the 30 s unit memory is too short for a
whole-army count (docs/VERIFY_NOTES.md §11.2). Each cached unit is the observation from the last
step it was visible, so `unit.age` is the time since it was last seen (`unit_cache_manager.py`
`store_enemy_unit`, M5 findings).

The army is out of position when
1. its value (fighting units: no workers, structures, Overlords or Observers) is at least
   OUT_OF_POSITION_MIN_VALUE, and at least OUT_OF_POSITION_FRESH_FRACTION of that value was seen
   within OUT_OF_POSITION_FRESH_S; and
2. the value-weighted centre of the freshly seen units is at least OUT_OF_POSITION_PATH (ground
   path) from every known enemy townhall (the enemy start location if none is known yet).
Path lengths: a path is never shorter than the straight line, so only townhalls closer than
OUT_OF_POSITION_PATH in a straight line are pathed (`mediator.find_raw_path` on ares's clean ground
grid), cached per OUT_OF_POSITION_PATH_CELL cell.

Each evaluation that finds it out of position raises or re-confirms the UNIT flag (15 s TTL, §5).
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Iterable, Optional

from ares.consts import TOWNHALL_TYPES
from sc2.position import Point2
from sc2.unit import Unit

from bot.army.engagement import is_fighter
from bot.constants import (
    OUT_OF_POSITION_FRESH_FRACTION,
    OUT_OF_POSITION_FRESH_S,
    OUT_OF_POSITION_MIN_VALUE,
    OUT_OF_POSITION_PATH,
    OUT_OF_POSITION_PATH_CACHE_MAX,
    OUT_OF_POSITION_PATH_CELL,
)
from bot.intel.threat_flags import Evidence, FlagStore, Threat

if TYPE_CHECKING:
    from ares import AresBot

SOURCE: str = "army_position"


def weighted_center(points: Iterable[tuple[Point2, float]]) -> Optional[Point2]:
    """Value-weighted centre of (position, value) pairs (plain centre if every value is 0)."""
    pairs = list(points)
    if not pairs:
        return None
    total = sum(v for _, v in pairs)
    if total <= 0:
        return Point2.center([p for p, _ in pairs])
    return Point2((sum(p.x * v for p, v in pairs) / total, sum(p.y * v for p, v in pairs) / total))


@dataclass
class ArmyReading:
    """One evaluation of the remembered enemy army."""

    time: float
    total_value: float = 0.0
    fresh_value: float = 0.0
    center: Optional[Point2] = None  # value-weighted centre of the freshly seen units
    base_distance: Optional[float] = None  # ground path from `center` to the nearest known enemy townhall
    out: bool = False
    why: str = ""
    fresh_tags: set[int] = field(default_factory=set)

    @property
    def fresh_fraction(self) -> float:
        return self.fresh_value / self.total_value if self.total_value > 0 else 0.0


class ArmyPosition:
    def __init__(self, bot: "AresBot", flags: Optional[FlagStore]):
        self.bot = bot
        self.flags = flags
        self._paths: dict[tuple[int, int, int, int], float] = {}
        self.path_queries: int = 0
        self.last: Optional[ArmyReading] = None

    # -- the remembered army ---------------------------------------------------------------------

    def value(self, unit: Unit) -> float:
        cost = self.bot.calculate_unit_value(unit.type_id)
        return cost.minerals + cost.vespene

    def remembered(self) -> list[Unit]:
        """The remembered enemy army: fighting units in ares's army cache."""
        return [u for u in self.bot.mediator.get_cached_enemy_army if is_fighter(u)]

    def center_of(self, tags: set[int]) -> Optional[Point2]:
        """Value-weighted centre of the remembered units with these tags (last known positions;
        only the freshly seen ones if any are)."""
        units = [u for u in self.remembered() if u.tag in tags]
        fresh = [u for u in units if u.age <= OUT_OF_POSITION_FRESH_S]
        return weighted_center((u.position, self.value(u)) for u in (fresh or units))

    def value_near(self, point: Point2, radius: float) -> float:
        return sum(self.value(u) for u in self.remembered() if u.position.distance_to(point) <= radius)

    # -- bases and paths -------------------------------------------------------------------------

    def enemy_bases(self) -> list[Point2]:
        """Known enemy townhalls (snapshots included), else the enemy start location."""
        bot = self.bot
        bases = [s.position for s in bot.enemy_structures if s.type_id in TOWNHALL_TYPES]
        return bases or [bot.enemy_start_locations[0]]

    def path_distance(self, start: Point2, goal: Point2, exact: bool = False) -> float:
        """Ground path length, or the straight line where that already decides (>= OUT_OF_POSITION_PATH;
        `exact` always paths) or where there is no ground path (an air army over unpathable ground)."""
        straight = start.distance_to(goal)
        if straight >= OUT_OF_POSITION_PATH and not exact:
            return straight
        cell = OUT_OF_POSITION_PATH_CELL
        key = (int(start.x // cell), int(start.y // cell), int(goal.x), int(goal.y))
        cached = self._paths.get(key)
        if cached is not None:
            return cached
        if len(self._paths) >= OUT_OF_POSITION_PATH_CACHE_MAX:
            self._paths.clear()
        self.path_queries += 1
        path = self.bot.mediator.find_raw_path(
            start=start, target=goal, grid=self.bot.mediator.get_cached_ground_grid, sensitivity=1
        )
        length = straight
        if path:
            length, prev = 0.0, start
            for p in path:
                length += prev.distance_to(p)
                prev = p
            length = max(length, straight)
        self._paths[key] = length
        return length

    # -- evaluation ------------------------------------------------------------------------------

    def update(self) -> ArmyReading:
        bot = self.bot
        now = bot.time
        reading = ArmyReading(time=now)
        units = self.remembered()
        fresh = [u for u in units if u.age <= OUT_OF_POSITION_FRESH_S]
        reading.total_value = sum(self.value(u) for u in units)
        reading.fresh_value = sum(self.value(u) for u in fresh)
        reading.fresh_tags = {u.tag for u in fresh}
        reading.center = weighted_center((u.position, self.value(u)) for u in fresh)
        self.last = reading
        if reading.total_value < OUT_OF_POSITION_MIN_VALUE:
            reading.why = f"army value {reading.total_value:.0f} < {OUT_OF_POSITION_MIN_VALUE:g}"
            return reading
        if reading.fresh_fraction < OUT_OF_POSITION_FRESH_FRACTION:
            reading.why = f"only {reading.fresh_fraction:.0%} seen within {OUT_OF_POSITION_FRESH_S:g} s"
            return reading
        reading.base_distance = min(self.path_distance(reading.center, b) for b in self.enemy_bases())
        if reading.base_distance < OUT_OF_POSITION_PATH:
            reading.why = f"centre {reading.base_distance:.0f} from an enemy base"
            return reading
        reading.out = True
        reading.why = (
            f"army value {reading.total_value:.0f} ({reading.fresh_fraction:.0%} seen within "
            f"{OUT_OF_POSITION_FRESH_S:g} s), centre {reading.center.rounded} is "
            f"{reading.base_distance:.0f} from the nearest enemy base"
        )
        if self.flags is not None:
            # re-confirmed while it holds; no positions, which would pile up on every confirmation
            self.flags.raise_flag(Threat.ARMY_OUT_OF_POSITION, Evidence.UNIT, SOURCE, now, reading.why)
        return reading
