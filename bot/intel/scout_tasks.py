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
| `MainProbeTask` | probe | past the enemy natural, the enemy main (a lap on its level), the enemy natural until the detectors are done with it, the likely proxy spots near our natural, home. Comes home at once on WORKER_RUSH (before reaching the enemy main) or POOL_12; searches the proxy spots at once on PROXY |
| `PatrolProbeTask` | probe | our natural's perimeter and our main's edge, `PATROL_LOOPS` times, home |
| `LookTask` | any | see each point in turn (probes: expansion checks, stale evidence; Stalker poke; Observer checks), then back |
| `AdeptShadeTask` | Adept | the bottom of the enemy main ramp, a shade up into the main, cancelled before it ends, back |
| `OracleTask` | Oracle | over the enemy natural, main and third; Revelation on a clump; Drones only with no Queen/Spore near |
| `PostTask` | Observer | sits at a watch post until a time (or for good), backing off when detected |
| `PhoenixTask` | hallucinated Phoenix | over the enemy main and natural, then away; ends when the hallucination does |

Combat and support units end their task back at our natural, where the army takes them again.
"""

from typing import TYPE_CHECKING, Iterable, Optional

from ares.behaviors.combat.individual import KeepUnitSafe
from loguru import logger
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit

from bot.constants import (
    CANNON_NEARLY_DONE,
    OBSERVER_DETECTED_BACKOFF,
    ORACLE_BEAM_MIN_ENERGY,
    ORACLE_CLUMP_RADIUS,
    ORACLE_DRONE_RANGE,
    ORACLE_DRONE_SAFE_RADIUS,
    ORACLE_HARASS_MAX_S,
    ORACLE_REVELATION_MIN_UNITS,
    SHADE_CANCEL_S,
    SHADE_CAST_DIST,
    SHADE_CAST_MAX_DIST,
    SHADE_WAIT_S,
    UNIT_SCOUT_HOME_RADIUS,
    MAIN_LAP_MAX_S,
    MAIN_PROBE_TO_MAIN_S,
    NAT_SCOUT_STANDOFF,
    NO_NATURAL_GIVE_UP_S,
    PATROL_LOOPS,
    SCOUT_HOME_RADIUS,
    SCOUT_HOME_TOWNHALL_RADIUS,
    SCOUT_REORDER_DIST,
    SCOUT_RETREAT_HP,
    SCOUT_STATIC_MARGIN,
    SCOUT_STATIC_STEP,
    SCOUT_WAYPOINT_TIMEOUT_S,
)
from bot.intel.threat_flags import Threat

if TYPE_CHECKING:
    from ares import AresBot

    from bot.intel.scout_planner import ScoutPlanner

Result = Optional[tuple[str, str]]

GROUND_STATIC_DEFENSE: frozenset[UnitTypeId] = frozenset(
    {UnitTypeId.PHOTONCANNON, UnitTypeId.BUNKER, UnitTypeId.SPINECRAWLER, UnitTypeId.PLANETARYFORTRESS}
)
AIR_STATIC_DEFENSE: frozenset[UnitTypeId] = frozenset(
    {UnitTypeId.PHOTONCANNON, UnitTypeId.BUNKER, UnitTypeId.MISSILETURRET, UnitTypeId.SPORECRAWLER}
)


class Mover:
    """§4.3 movement for scouts: danger-aware paths, `KeepUnitSafe`, no repeated identical orders."""

    def __init__(self, bot: "AresBot"):
        self.bot = bot

    def grid(self, unit: Unit):
        mediator = self.bot.mediator
        return mediator.get_air_grid if unit.is_flying else mediator.get_ground_grid

    def is_safe(self, unit: Unit) -> bool:
        return self.bot.mediator.is_position_safe(grid=self.grid(unit), position=unit.position)

    def static_threat(self, point: Point2, flying: bool = False) -> Optional[Unit]:
        """An enemy static defense (finished or nearly) that could hit `point`, with a margin.
        Its range comes from game data (`air_range`/`ground_range`)."""
        types = AIR_STATIC_DEFENSE if flying else GROUND_STATIC_DEFENSE
        for s in self.bot.enemy_structures:
            if s.type_id not in types or s.build_progress < CANNON_NEARLY_DONE:
                continue
            reach = (s.air_range if flying else s.ground_range) or 7.0  # a Bunker's weapon is its cargo's
            if s.distance_to(point) <= reach + s.radius + SCOUT_STATIC_MARGIN:
                return s
        return None

    def avoid_static(self, unit: Unit) -> bool:
        """Step straight away from enemy static defense in reach; True if it did."""
        threat = self.static_threat(unit.position, unit.is_flying)
        if threat is None:
            return False
        self.move(unit, unit.position.towards(threat.position, -SCOUT_STATIC_STEP))
        return True

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
        if not self.avoid_static(unit) and not self.keep_safe(unit):
            self.path_to(unit, target)

    def go_to(self, unit: Unit, target: Point2) -> None:
        """Toward `target` on a danger-aware path, but never into static defense's reach (a
        scout going home waits outside Cannons covering the way instead of walking past them)."""
        if not self.avoid_static(unit):
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
        self.planner.mover.go_to(unit, self.bot.start_location)
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
        # the enemy natural first: it is on the way, and §4.4 row 3 and the Pool-before-Hatchery
        # check need to know whether a townhall is there when the main's structures are seen
        self.phase = "to_natural"
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
        if self.phase == "to_natural":
            nat: Point2 = bot.mediator.get_enemy_nat
            if self.reached_main or bot.is_visible(nat) or bot.time - self.started_at > MAIN_PROBE_TO_MAIN_S:
                self.phase = "to_main"
            else:
                mover.path_to(unit, nat.towards(bot.game_info.map_center, NAT_SCOUT_STANDOFF))
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
                if planner.cannon_rush_found():
                    self.go_home(f"{why}; the proxy spots are next to the rush Cannons")
                self.sweep = Waypoints(nearest_neighbour_order(unit.position, planner.proxy_spots()))
                if self.phase == "sweep":
                    logger.info(
                        f"SCOUT {self.name} {self.tag} to {len(self.sweep.points)} proxy spots at "
                        f"{bot.time_formatted} ({why})"
                    )
            else:
                spot = bot.mediator.get_enemy_nat.towards(bot.game_info.map_center, NAT_SCOUT_STANDOFF)
                mover.scout_to(unit, spot)
        if self.phase == "sweep" and self.sweep is not None:
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
            if self.planner.cannon_rush_found() or self.planner.flags.get(Threat.PROXY, "proxy_structure"):
                self.go_home("found the rush structures")
            elif point is None:
                self.go_home("patrol done")
            else:
                self.planner.mover.scout_to(unit, point)
        if self.phase == "home":
            return self.home_step(unit)
        return None


# -- combat and support units ------------------------------------------------------------------


class UnitTask(ScoutTask):
    """A non-probe scout: goes back to our natural when hurt or done; the army then has it."""

    def __init__(self, planner: "ScoutPlanner", tag: int):
        super().__init__(planner, tag)
        self.back: bool = False
        self.why: str = ""

    def go_back(self, why: str) -> None:
        if not self.back:
            self.back = True
            self.why = why
            logger.info(f"SCOUT {self.name} {self.tag} coming back at {self.bot.time_formatted}: {why}")

    def hurt(self, unit: Unit) -> bool:
        if unit.shield_health_percentage < SCOUT_RETREAT_HP:
            self.go_back(f"HP+shield at {unit.shield_health_percentage:.0%}")
            return True
        return False

    def back_step(self, unit: Unit) -> Result:
        home = self.planner.home_point()
        if unit.distance_to(home) < UNIT_SCOUT_HOME_RADIUS:
            return "done", self.why
        self.planner.mover.go_to(unit, home)
        return None

    def detected_backoff(self, unit: Unit) -> bool:
        """An Observer that the enemy detects moves back toward our natural."""
        if unit.type_id == UnitTypeId.OBSERVER and self.bot.mediator.get_is_detected(unit=unit):
            self.planner.mover.move(unit, unit.position.towards(self.planner.home_point(), OBSERVER_DETECTED_BACKOFF))
            return True
        return False


class LookTask(UnitTask):
    """See each point in turn (from a safe distance if need be), then come back. Probes use
    `ProbeLookTask`."""

    def __init__(self, planner: "ScoutPlanner", tag: int, name: str, points: Iterable[Point2]):
        super().__init__(planner, tag)
        self.name = name
        self.route = Waypoints(points)

    def step(self, unit: Unit) -> Result:
        if not self.back and not self.hurt(unit):
            point = self.route.current(self.bot)
            if point is None:
                self.go_back("seen")
            elif not self.detected_backoff(unit):
                self.planner.mover.scout_to(unit, point)
        if self.back:
            return self.back_step(unit)
        return None


class ProbeLookTask(ProbeTask):
    """A probe seeing each point in turn, then home to mine (expansion checks, stale evidence)."""

    def __init__(self, planner: "ScoutPlanner", tag: int, name: str, points: Iterable[Point2]):
        super().__init__(planner, tag)
        self.name = name
        self.phase = "look"
        self.route = Waypoints(points)

    def step(self, unit: Unit) -> Result:
        if self.phase != "home" and not self.hurt(unit):
            if self.planner.probes_needed_home():
                self.go_home("a rush needs the probes")
            elif (point := self.route.current(self.bot)) is None:
                self.go_home("seen")
            else:
                self.planner.mover.scout_to(unit, point)
        if self.phase == "home":
            return self.home_step(unit)
        return None


class AdeptShadeTask(UnitTask):
    """§4.3 PvT/PvZ: an Adept shade into the enemy main."""

    name = "adept_shade"

    def __init__(self, planner: "ScoutPlanner", tag: int, target: Point2):
        super().__init__(planner, tag)
        self.target = target
        self.phase: str = "approach"
        self.waiting_since: Optional[float] = None
        self.cast_at: Optional[float] = None
        self.shade_tag: Optional[int] = None

    def step(self, unit: Unit) -> Result:
        bot = self.bot
        mover = self.planner.mover
        if not self.back and self.phase != "shade" and self.hurt(unit):
            pass
        elif not self.back:
            staging: Point2 = bot.mediator.get_enemy_ramp.bottom_center
            if self.phase == "approach":
                dist = unit.distance_to(staging)
                if dist <= SHADE_CAST_DIST or (dist <= SHADE_CAST_MAX_DIST and not mover.is_safe(unit)):
                    self.phase = "cast"
                    self.waiting_since = bot.time
                else:
                    mover.scout_to(unit, staging)
            if self.phase == "cast":
                if AbilityId.ADEPTPHASESHIFT_ADEPTPHASESHIFT in unit.abilities:
                    unit(AbilityId.ADEPTPHASESHIFT_ADEPTPHASESHIFT, self.target)
                    self.phase = "shade"
                    self.cast_at = bot.time
                elif bot.time - self.waiting_since > SHADE_WAIT_S:
                    self.go_back("shade not ready")
                else:
                    mover.keep_safe(unit)
            elif self.phase == "shade":
                self._shade_step(unit)
        if self.back:
            return self.back_step(unit)
        return None

    def _shade_step(self, unit: Unit) -> None:
        bot = self.bot
        if self.shade_tag is None:
            shades = bot.units(UnitTypeId.ADEPTPHASESHIFT)
            if shades:
                self.shade_tag = shades.closest_to(unit).tag
        shade = bot.unit_tag_dict.get(self.shade_tag) if self.shade_tag is not None else None
        if bot.time - self.cast_at >= SHADE_CANCEL_S:
            if shade is not None:
                unit(AbilityId.CANCEL_ADEPTPHASESHIFT)  # the Adept stays where it is
            self.go_back("shade done")
            return
        if shade is not None:
            # into the main, past the townhall (vision on the production behind it)
            self.planner.mover.move(shade, self.target.towards(shade.position, -6))
        self.planner.mover.keep_safe(unit)


class OracleTask(UnitTask):
    """§4.3 PvZ Oracle: over the enemy natural, main and third; Revelation on the largest clump;
    Drones only while no Queen or Spore is within ORACLE_DRONE_SAFE_RADIUS."""

    name = "oracle"
    ANTI_AIR_GUARDS: frozenset = frozenset({UnitTypeId.QUEEN, UnitTypeId.SPORECRAWLER})

    def __init__(self, planner: "ScoutPlanner", tag: int, points: Iterable[Point2]):
        super().__init__(planner, tag)
        self.route = Waypoints(points)
        self.revealed: bool = False
        self.beam_since: Optional[float] = None

    def step(self, unit: Unit) -> Result:
        bot = self.bot
        if self.back or self.hurt(unit):
            self._beam_off(unit)
            return self.back_step(unit)
        enemies = [e for e in bot.enemy_units if not e.is_memory and e.distance_to(unit) < 14]
        self._revelation(unit, enemies)
        if self._drones(unit, enemies):
            return None
        point = self.route.current(bot)
        if point is None:
            self.go_back("route done")
            return self.back_step(unit)
        self.planner.mover.scout_to(unit, point)
        return None

    def _revelation(self, unit: Unit, enemies: list[Unit]) -> None:
        if self.revealed or AbilityId.ORACLEREVELATION_ORACLEREVELATION not in unit.abilities:
            return
        ground = [e for e in enemies if not e.is_structure]
        best = max(ground, key=lambda e: sum(1 for o in ground if o.distance_to(e) < ORACLE_CLUMP_RADIUS), default=None)
        if best is not None and sum(1 for o in ground if o.distance_to(best) < ORACLE_CLUMP_RADIUS) >= ORACLE_REVELATION_MIN_UNITS:
            unit(AbilityId.ORACLEREVELATION_ORACLEREVELATION, best.position)
            self.revealed = True
            logger.info(f"SCOUT oracle Revelation at {best.position.rounded} ({self.bot.time_formatted})")

    def _drones(self, unit: Unit, enemies: list[Unit]) -> bool:
        """True while it is busy with Drones."""
        now = self.bot.time
        guarded = any(e.type_id in self.ANTI_AIR_GUARDS and e.distance_to(unit) < ORACLE_DRONE_SAFE_RADIUS for e in enemies)
        drones = [e for e in enemies if e.type_id == UnitTypeId.DRONE and e.distance_to(unit) < ORACLE_DRONE_RANGE]
        if guarded or not drones or (self.beam_since is not None and now - self.beam_since > ORACLE_HARASS_MAX_S):
            self._beam_off(unit)
            return False
        if self.beam_since is None:
            if unit.energy < ORACLE_BEAM_MIN_ENERGY or AbilityId.BEHAVIOR_PULSARBEAMON not in unit.abilities:
                return False
            unit(AbilityId.BEHAVIOR_PULSARBEAMON)
            self.beam_since = now
            logger.info(f"SCOUT oracle beam on at {self.bot.time_formatted}: {len(drones)} Drones, no Queen/Spore near")
            return True
        target = min(drones, key=lambda d: d.distance_to(unit))
        if unit.order_target != target.tag:
            unit.attack(target)
        return True

    def _beam_off(self, unit: Unit) -> None:
        if AbilityId.BEHAVIOR_PULSARBEAMOFF in unit.abilities:
            unit(AbilityId.BEHAVIOR_PULSARBEAMOFF)


class PostTask(UnitTask):
    """An Observer at a watch post until `until` (None: for good), backing off when detected."""

    def __init__(self, planner: "ScoutPlanner", tag: int, name: str, post: Point2, until: Optional[float]):
        super().__init__(planner, tag)
        self.name = name
        self.post = post
        self.until = until

    def step(self, unit: Unit) -> Result:
        if self.until is not None and self.bot.time >= self.until:
            return "done", "post time over"
        if self.hurt(unit) or self.back:
            return self.back_step(unit)
        if not self.detected_backoff(unit):
            self.planner.mover.scout_to(unit, self.post)
        return None


class PhoenixTask(ScoutTask):
    """§4.3 hallucinated Phoenix: over the enemy main and natural, then away. Hallucinations get
    no orders of their own (VERIFY_NOTES M3), so each point is ordered explicitly. It ends when the
    hallucination does (~43 s), recorded as "expired"."""

    name = "hallucinated_phoenix"

    def __init__(self, planner: "ScoutPlanner", tag: int, points: Iterable[Point2]):
        super().__init__(planner, tag)
        self.route = Waypoints(points)

    def step(self, unit: Unit) -> Result:
        point = self.route.current(self.bot)
        if point is None:
            point = self.planner.home_point()
        self.planner.mover.path_to(unit, point)
        return None
