"""Scouting tasks (DESIGN.md §4.3), run by `ScoutPlanner` (scout_planner.py).

One task drives one unit, found by its tag each step. `step(unit)` returns None while the task
goes on, or `(outcome, why)` when it is over; the planner then hands the unit back (probes to
mining) and records the outcome. A unit killed during its task is recorded as lost by
`Telemetry`.

Every scout follows §4.3's common rules through `Mover`: it paths with
`mediator.find_path_next_point` on the ground or air grid (which routes around enemy
influence), steps out of danger with ares's `KeepUnitSafe`, and heads home below
`SCOUT_RETREAT_HP` of its HP+shield.

| task | unit | route |
|---|---|---|
| `MainProbeTask` | probe | the enemy main (a lap on its level), the enemy natural until the detectors are done with it, the likely proxy spots near our natural, home. Comes home at once on WORKER_RUSH (before reaching the enemy main) or POOL_12; searches the proxy spots at once on PROXY |
| `PatrolProbeTask` | probe | our natural's perimeter and our main's edge, `PATROL_LOOPS` times, home |
"""

from typing import TYPE_CHECKING, Iterable, Optional

from ares.behaviors.combat.individual import KeepUnitSafe
from loguru import logger
from sc2.position import Point2
from sc2.unit import Unit

from bot.constants import (
    MAIN_LAP_MAX_S,
    MAIN_PROBE_TO_MAIN_S,
    NAT_SCOUT_STANDOFF,
    NO_NATURAL_GIVE_UP_S,
    PATROL_LOOPS,
    SCOUT_HOME_RADIUS,
    SCOUT_HOME_TOWNHALL_RADIUS,
    SCOUT_REORDER_DIST,
    SCOUT_RETREAT_HP,
    SCOUT_WAYPOINT_TIMEOUT_S,
)
from bot.intel.threat_flags import Threat

if TYPE_CHECKING:
    from ares import AresBot

    from bot.intel.scout_planner import ScoutPlanner

Result = Optional[tuple[str, str]]


class Mover:
    """§4.3 movement for scouts: danger-aware paths, `KeepUnitSafe`, no repeated identical orders."""

    def __init__(self, bot: "AresBot"):
        self.bot = bot

    def grid(self, unit: Unit):
        mediator = self.bot.mediator
        return mediator.get_air_grid if unit.is_flying else mediator.get_ground_grid

    def is_safe(self, unit: Unit) -> bool:
        return self.bot.mediator.is_position_safe(grid=self.grid(unit), position=unit.position)

    def keep_safe(self, unit: Unit) -> bool:
        """Step out of danger; True if the unit was in danger (and was given an order)."""
        bot = self.bot
        return KeepUnitSafe(unit=unit, grid=self.grid(unit)).execute(bot, bot.config, bot.mediator)

    def path_to(self, unit: Unit, target: Point2) -> None:
        """The next point on a path that avoids enemy influence (a straight move when no danger
        is near, `ares-sc2/src/ares/managers/path_manager.py:328`)."""
        point = self.bot.mediator.find_path_next_point(start=unit.position, target=target, grid=self.grid(unit))
        self.move(unit, point)

    def scout_to(self, unit: Unit, target: Point2) -> None:
        """Out of danger first, then toward `target`."""
        if not self.keep_safe(unit):
            self.path_to(unit, target)

    @staticmethod
    def move(unit: Unit, point: Point2) -> None:
        current = unit.order_target
        if isinstance(current, Point2) and current.distance_to(point) < SCOUT_REORDER_DIST:
            return
        unit.move(point)


class Waypoints:
    """Points to see, in order. A point is done once it is in vision (the scout needn't stand on
    it) or `SCOUT_WAYPOINT_TIMEOUT_S` after the scout set off for it."""

    def __init__(self, points: Iterable[Point2]):
        self.points: list[Point2] = list(points)
        self.index: int = 0
        self._since: Optional[float] = None

    def current(self, bot: "AresBot") -> Optional[Point2]:
        now = bot.time
        while self.index < len(self.points):
            point = self.points[self.index]
            if self._since is None:
                self._since = now
            if bot.is_visible(point) or now - self._since > SCOUT_WAYPOINT_TIMEOUT_S:
                self.index += 1
                self._since = None
                continue
            return point
        return None


def nearest_neighbour_order(start: Point2, points: Iterable[Point2]) -> list[Point2]:
    left = list(points)
    order: list[Point2] = []
    here = start
    while left:
        nxt = min(left, key=lambda p: p.distance_to(here))
        left.remove(nxt)
        order.append(nxt)
        here = nxt
    return order


class ScoutTask:
    name: str = "scout"
    releases_to_mining: bool = False

    def __init__(self, planner: "ScoutPlanner", tag: int):
        self.planner = planner
        self.bot = planner.bot
        self.tag = tag
        self.started_at: float = self.bot.time

    def step(self, unit: Unit) -> Result:
        raise NotImplementedError

    def on_lost(self) -> None:
        """The unit died during the task."""


class ProbeTask(ScoutTask):
    """A probe scout: goes home when hurt, and ends once home (then it mines again)."""

    releases_to_mining = True

    def __init__(self, planner: "ScoutPlanner", tag: int):
        super().__init__(planner, tag)
        self.phase: str = ""
        self.home_why: str = ""

    def go_home(self, why: str) -> None:
        if self.phase != "home":
            self.phase = "home"
            self.home_why = why
            logger.info(f"SCOUT {self.name} {self.tag} going home at {self.bot.time_formatted}: {why}")

    def is_home(self, unit: Unit) -> bool:
        bot = self.bot
        return unit.distance_to(bot.start_location) < SCOUT_HOME_RADIUS or any(
            th.distance_to(unit) < SCOUT_HOME_TOWNHALL_RADIUS for th in bot.townhalls
        )

    def home_step(self, unit: Unit) -> Result:
        if self.is_home(unit):
            return "home", self.home_why
        self.planner.mover.path_to(unit, self.bot.start_location)
        return None

    def hurt(self, unit: Unit) -> bool:
        if unit.shield_health_percentage < SCOUT_RETREAT_HP:
            self.go_home(f"HP+shield at {unit.shield_health_percentage:.0%}")
            return True
        return False


class MainProbeTask(ProbeTask):
    """§4.3 common row 1: enemy main, natural, proxy spots, home."""

    name = "main_probe"

    def __init__(self, planner: "ScoutPlanner", tag: int):
        super().__init__(planner, tag)
        self.phase = "to_main"
        self.reached_main: bool = False
        self.lap = Waypoints(planner.main_lap_points())
        self.lap_started_at: Optional[float] = None
        self.sweep: Optional[Waypoints] = None

    def on_lost(self) -> None:
        self.planner.main_probe_lost(self)

    def step(self, unit: Unit) -> Result:
        planner = self.planner
        bot = self.bot
        mover = planner.mover
        active = planner.flags.active_threats()
        if not self.reached_main and planner.in_enemy_main(unit.position):
            self.reached_main = True
            logger.info(f"SCOUT {self.name} {self.tag} reached the enemy main at {bot.time_formatted}")
        if self.phase != "home" and not self.hurt(unit):
            if Threat.POOL_12 in active:
                self.go_home("12-pool: home before the Zerglings")
            elif Threat.WORKER_RUSH in active and not self.reached_main:
                self.go_home("worker rush: needed at home")
        if self.phase == "to_main":
            # a wall can keep it out (Terran depots): then it looks from where it got to
            if self.reached_main or bot.time - self.started_at > MAIN_PROBE_TO_MAIN_S:
                self.phase = "lap"
                self.lap_started_at = bot.time
            else:
                mover.path_to(unit, self.lap.points[0] if self.lap.points else bot.enemy_start_locations[0])
        if self.phase == "lap":
            point = self.lap.current(bot)
            if point is None or Threat.PROXY in active or bot.time - self.lap_started_at > MAIN_LAP_MAX_S:
                self.phase = "natural"
            else:
                mover.scout_to(unit, point)
        if self.phase == "natural":
            detectors = planner.detectors
            deadline = detectors.no_natural_deadline() + NO_NATURAL_GIVE_UP_S
            if Threat.PROXY in active or detectors.natural_resolved or bot.time > deadline:
                why = "PROXY flag" if Threat.PROXY in active else (
                    "natural check done" if detectors.natural_resolved else "past the no-natural deadline"
                )
                self.phase = "sweep"
                self.sweep = Waypoints(nearest_neighbour_order(unit.position, planner.proxy_spots()))
                logger.info(
                    f"SCOUT {self.name} {self.tag} to {len(self.sweep.points)} proxy spots at "
                    f"{bot.time_formatted} ({why})"
                )
            else:
                spot = bot.mediator.get_enemy_nat.towards(bot.game_info.map_center, NAT_SCOUT_STANDOFF)
                mover.scout_to(unit, spot)
        if self.phase == "sweep":
            point = self.sweep.current(bot)
            if point is None:
                self.go_home("proxy spots checked")
            else:
                mover.scout_to(unit, point)
        if self.phase == "home":
            return self.home_step(unit)
        return None


class PatrolProbeTask(ProbeTask):
    """§4.3 common row 2: our natural's perimeter and our main's edge (cannon-rush Pylons,
    proxies)."""

    name = "patrol_probe"

    def __init__(self, planner: "ScoutPlanner", tag: int, why: str):
        super().__init__(planner, tag)
        self.phase = "patrol"
        self.why = why
        points = planner.patrol_points()
        self.route = Waypoints(nearest_neighbour_order(self.bot.start_location, points) * PATROL_LOOPS)

    def step(self, unit: Unit) -> Result:
        if self.phase != "home" and not self.hurt(unit):
            point = self.route.current(self.bot)
            if point is None:
                self.go_home("patrol done")
            else:
                self.planner.mover.scout_to(unit, point)
        if self.phase == "home":
            return self.home_step(unit)
        return None
