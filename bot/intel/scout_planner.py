"""Per-matchup scouting schedule (DESIGN.md §4.3). Runs every `MACRO_EVERY_STEPS` (§3 step 4).

`ScoutPlanner` decides when each scouting task starts and with which unit, steps the running
tasks (scout_tasks.py), and hands units back when their task ends. Order of authority (§3):
Defense > Scouting, so the defense code's probes (DEFENDING) and pinned units are never taken,
and a probe scout comes home when a rush needs it there.

Probe scouts (§4.3 common rows):
- Main probe: the opener's `worker_scout` probe, taken over as soon as the build runner sends it
  (role `BUILD_RUNNER_SCOUT` → `SCOUTING`) and driven by `MainProbeTask`; with no such probe by
  `MAIN_PROBE_FALLBACK_S`, the planner picks one. One that came home (or died) before the enemy
  main was scouted is replaced `MAIN_PROBE_RETRIES` times once no rush flag is active.
- Patrol probe: between `PATROL_FROM_S` and `PATROL_START_UNTIL_S` when the scouted enemy main
  has no Barracks/Gateway ("fewer structures than expected", T/P), or on §4.4 row 3's
  Forge-first flag until `PATROL_FORGE_UNTIL_S`.

Units stay under a task's control until it ends; `tags` lists them so the army leaves them
alone.
"""

import math
from typing import TYPE_CHECKING, Optional

from ares.consts import UnitRole
from loguru import logger
from sc2.data import Race
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit

from bot.constants import (
    MAIN_LAP_POINTS,
    MAIN_LAP_RADII,
    MAIN_PROBE_FALLBACK_S,
    MAIN_PROBE_RETRIES,
    MAIN_PROBE_RETRY_UNTIL_S,
    MAIN_RADIUS,
    PATROL_FORGE_UNTIL_S,
    PATROL_FROM_S,
    PATROL_MAIN_EDGE,
    PATROL_NATURAL_RADIUS,
    PATROL_POINTS,
    PATROL_START_UNTIL_S,
    PROXY_RING_POINTS,
    PROXY_RING_RADIUS,
    PROXY_SPOT_MIN_FROM_NATURAL,
    PROXY_SPOT_RADIUS,
    PROXY_SPOT_SPACING,
    SAME_LEVEL_Z,
)
from bot.geometry import in_map
from bot.intel.detectors import MAIN_PRODUCTION
from bot.intel.scout_tasks import MainProbeTask, Mover, PatrolProbeTask, ScoutTask
from bot.intel.threat_flags import FlagStore, Threat

if TYPE_CHECKING:
    from ares import AresBot

    from bot.intel.detectors import Detectors
    from bot.telemetry.logger import Telemetry

# rushes that need every probe at home: no probe scout leaves while one is active
PROBES_STAY_HOME: frozenset[Threat] = frozenset({Threat.WORKER_RUSH, Threat.POOL_12})


def _ring(centre: Point2, radius: float, count: int) -> list[Point2]:
    return [
        Point2((centre.x + radius * math.cos(2 * math.pi * k / count), centre.y + radius * math.sin(2 * math.pi * k / count)))
        for k in range(count)
    ]


class ScoutPlanner:
    def __init__(self, bot: "AresBot", detectors: "Detectors", flags: FlagStore, telemetry: "Telemetry"):
        self.bot = bot
        self.detectors = detectors
        self.flags = flags
        self.telemetry = telemetry
        self.mover = Mover(bot)
        self.tasks: dict[int, ScoutTask] = {}
        self.main_probes_started: int = 0
        self.main_probe_killed_before_main_at: Optional[float] = None
        self.patrol_started: bool = False
        self._lap: Optional[list[Point2]] = None
        self._proxy_spots: Optional[list[Point2]] = None
        self._patrol: Optional[list[Point2]] = None

    @property
    def tags(self) -> set[int]:
        return set(self.tasks)

    # -- per step --------------------------------------------------------------------------------

    def step(self) -> None:
        bot = self.bot
        self._take_build_runner_scouts()
        self._schedule_probes()
        for tag, task in list(self.tasks.items()):
            unit = bot.unit_tag_dict.get(tag)
            if unit is None:
                continue  # dead ones are removed in on_unit_destroyed
            result = task.step(unit)
            if result is not None:
                self._finish(task, unit, *result)

    def on_unit_destroyed(self, tag: int) -> None:
        task = self.tasks.pop(tag, None)
        if task is not None:
            task.on_lost()

    # -- starting and ending tasks ---------------------------------------------------------------

    def _start(self, task: ScoutTask, unit: Unit) -> None:
        self.tasks[task.tag] = task
        if unit.type_id == UnitTypeId.PROBE:
            self.bot.mediator.assign_role(tag=unit.tag, role=UnitRole.SCOUTING)
        self.telemetry.scout_started(unit.tag, unit.type_id, task.name)

    def _finish(self, task: ScoutTask, unit: Unit, outcome: str, why: str) -> None:
        self.tasks.pop(task.tag, None)
        if task.releases_to_mining:
            self.bot.mediator.assign_role(tag=unit.tag, role=UnitRole.GATHERING)
        self.telemetry.scout_ended(unit.tag, outcome, why)

    def _free_probe(self) -> Optional[Unit]:
        return self.bot.mediator.select_worker(target_position=self.bot.mediator.get_own_nat)

    def _probes_needed_home(self) -> bool:
        return bool(PROBES_STAY_HOME & self.flags.active_threats())

    def _main_probe_active(self) -> bool:
        return any(isinstance(t, MainProbeTask) for t in self.tasks.values())

    def _take_build_runner_scouts(self) -> None:
        mediator = self.bot.mediator
        for probe in mediator.get_units_from_role(role=UnitRole.BUILD_RUNNER_SCOUT, unit_type=UnitTypeId.PROBE):
            if self.main_probes_started == 0 and not self._probes_needed_home():
                self._start_main_probe(probe, "the opener's worker_scout")
            else:
                mediator.assign_role(tag=probe.tag, role=UnitRole.GATHERING)

    def _start_main_probe(self, probe: Unit, why: str) -> None:
        self.main_probes_started += 1
        logger.info(f"SCOUT main probe {probe.tag} ({why}) at {self.bot.time_formatted}")
        self._start(MainProbeTask(self, probe.tag), probe)

    def _schedule_probes(self) -> None:
        bot = self.bot
        now = bot.time
        if self._probes_needed_home():
            return
        detectors = self.detectors
        if self.main_probes_started == 0:
            if now >= MAIN_PROBE_FALLBACK_S and (probe := self._free_probe()) is not None:
                self._start_main_probe(probe, "no opener scout")
        elif (
            detectors.main_scouted_at is None
            and not self._main_probe_active()
            and self.main_probes_started <= MAIN_PROBE_RETRIES
            and now < MAIN_PROBE_RETRY_UNTIL_S
            and (probe := self._free_probe()) is not None
        ):
            self._start_main_probe(probe, "the enemy main is still unscouted")
        if not self.patrol_started:
            why = None
            if PATROL_FROM_S <= now <= PATROL_START_UNTIL_S and self._main_looks_light():
                why = "the enemy main has no Barracks/Gateway"
            elif now <= PATROL_FORGE_UNTIL_S and self.flags.get(Threat.CANNON_RUSH, "forge_first") is not None:
                why = "Forge before Gateway"
            if why is not None and (probe := self._free_probe()) is not None:
                self.patrol_started = True
                logger.info(f"SCOUT patrol probe {probe.tag} at {bot.time_formatted}: {why}")
                self._start(PatrolProbeTask(self, probe.tag, why), probe)

    def main_probe_lost(self, task: MainProbeTask) -> None:
        if not task.reached_main and self.main_probe_killed_before_main_at is None:
            self.main_probe_killed_before_main_at = self.bot.time
            logger.info(f"SCOUT main probe killed before reaching the enemy main at {self.bot.time_formatted}")
            self.detectors.scout_killed()  # §4.4 row 15

    # -- places --------------------------------------------------------------------------------

    def _same_level_pathable(self, point: Point2, level_of: Point2) -> bool:
        bot = self.bot
        return (
            in_map(bot, point)
            and bot.in_pathing_grid(point)
            and abs(bot.get_terrain_z_height(point) - bot.get_terrain_z_height(level_of)) < SAME_LEVEL_Z
        )

    def in_enemy_main(self, point: Point2) -> bool:
        enemy_main = self.bot.enemy_start_locations[0]
        return point.distance_to(enemy_main) < MAIN_RADIUS and self._same_level_pathable(point, enemy_main)

    def main_lap_points(self) -> list[Point2]:
        """A lap around the enemy main on its level, starting at the side nearest its ramp."""
        if self._lap is None:
            bot = self.bot
            enemy_main = bot.enemy_start_locations[0]
            points = []
            for k in range(MAIN_LAP_POINTS):
                angle = 2 * math.pi * k / MAIN_LAP_POINTS
                for radius in MAIN_LAP_RADII:
                    p = Point2((enemy_main.x + radius * math.cos(angle), enemy_main.y + radius * math.sin(angle)))
                    if self._same_level_pathable(p, enemy_main):
                        points.append(p)
                        break
            if points:
                entry = bot.mediator.get_enemy_ramp.top_center
                first = min(range(len(points)), key=lambda i: points[i].distance_to(entry))
                points = points[first:] + points[:first]
            self._lap = points
        return self._lap

    def proxy_spots(self) -> list[Point2]:
        """§4.3 likely proxy spots: map-analyzer region centres, expansion locations and a ring
        around our natural, within `PROXY_SPOT_RADIUS` of our natural, outside our main."""
        if self._proxy_spots is None:
            bot = self.bot
            nat: Point2 = bot.mediator.get_own_nat
            candidates: list[Point2] = [Point2(r.center) for r in bot.mediator.get_map_data_object.regions.values()]
            candidates += list(bot.expansion_locations_list)
            candidates += _ring(nat, PROXY_RING_RADIUS, PROXY_RING_POINTS)
            spots: list[Point2] = []
            for c in candidates:
                if not (PROXY_SPOT_MIN_FROM_NATURAL <= c.distance_to(nat) <= PROXY_SPOT_RADIUS):
                    continue
                if not in_map(bot, c) or not bot.in_pathing_grid(c) or self._in_our_main(c):
                    continue
                if any(c.distance_to(s) < PROXY_SPOT_SPACING for s in spots):
                    continue
                spots.append(c)
            self._proxy_spots = spots
            logger.info(f"SCOUT {len(spots)} proxy spots within {PROXY_SPOT_RADIUS:g} of our natural")
        return self._proxy_spots

    def patrol_points(self) -> list[Point2]:
        """§4.3 second probe: our natural's perimeter and our main's edge."""
        if self._patrol is None:
            bot = self.bot
            nat: Point2 = bot.mediator.get_own_nat
            points = [p for p in _ring(nat, PATROL_NATURAL_RADIUS, PATROL_POINTS) if in_map(bot, p) and bot.in_pathing_grid(p)]
            points += [
                p for p in _ring(bot.start_location, PATROL_MAIN_EDGE, PATROL_POINTS)
                if self._same_level_pathable(p, bot.start_location)
            ]
            self._patrol = points
        return self._patrol

    def _in_our_main(self, point: Point2) -> bool:
        start = self.bot.start_location
        return point.distance_to(start) < MAIN_RADIUS and self._same_level_pathable(point, start)

    def _main_looks_light(self) -> bool:
        """§4.3 "the enemy main showed fewer structures than expected": scouted, and no
        Barracks (T) / Gateway (P) in it."""
        bot = self.bot
        detectors = self.detectors
        race = bot.enemy_race
        if detectors.main_scouted_at is None or race not in (Race.Terran, Race.Protoss):
            return False
        enemy_main = bot.enemy_start_locations[0]
        return not any(
            s.type_id in MAIN_PRODUCTION[race] and s.distance_to(enemy_main) < MAIN_RADIUS for s in bot.enemy_structures
        )
