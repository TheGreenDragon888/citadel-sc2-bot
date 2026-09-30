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

Unit scouts (§4.3 per-matchup rows; combat units only while no M2 defense threat is active):
- PvT: an Adept shade into the main at Core + ADEPT_SCOUT_AFTER_CORE_S; the first Observer at
  Robo + OBSERVER_AFTER_ROBO_S on the path between the enemy natural and ours until 6:00.
- PvZ: an Adept shade at ADEPT_SCOUT_PVZ_S; the opener's Oracle at ORACLE_SCOUT_S.
- PvP: a Stalker poke at the enemy natural at Core + STALKER_POKE_AFTER_CORE_S; the first
  Observer outside the enemy natural choke once the Robo is done, until 6:00; a second one at
  home once a Twilight Council is seen.
- Hallucinated Phoenix (only with an existing Sentry, user decision) at HALLUCINATION_AT_S, and
  whenever the enemy main has gone unseen long enough after HALLUCINATION_FROM_S.
- §4.4 row 15: while UNKNOWN_AGGRO is active and the enemy main unscouted, the first Adept (a
  shade) or Stalker goes to look.
- From EXPANSION_CHECK_FROM_S, every EXPANSION_CHECK_EVERY_S: a free Observer, else a probe,
  visits the expansion locations not seen for EXPANSION_FRESH_S.
- §5 re-scout trigger: stale STRUCTURE evidence (`FlagStore.stale`) is looked at by a free
  Observer, or by a probe when it is on our side of the map; an enemy main unseen for
  MAIN_STALE_S after MAIN_STALE_FROM_S by a free Observer (or a Phoenix, above).
From OBSERVER_POST_UNTIL_S one Observer is left to the army, which moves it with the army (§4.3
"From 6:00 Observer travels with the army").

Units stay under a task's control until it ends; `tags` lists them so the army leaves them
alone.
"""

import math
from typing import TYPE_CHECKING, Optional

from ares.consts import UnitRole
from loguru import logger
from sc2.data import Race
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit

from bot.constants import (
    ADEPT_SCOUT_AFTER_CORE_S,
    ADEPT_SCOUT_PVZ_S,
    EXPANSION_CHECK_EVERY_S,
    EXPANSION_CHECK_FROM_S,
    EXPANSION_CHECK_MAX,
    EXPANSION_FRESH_S,
    HALLUCINATION_AT_S,
    HALLUCINATION_FROM_S,
    HALLUCINATION_MIN_GAP_S,
    HALLUCINATION_STALE_DEFAULT_S,
    HALLUCINATION_STALE_S,
    HOME_OBSERVER_OFFSET,
    MAIN_LAP_POINTS,
    MAIN_LAP_RADII,
    MAIN_PROBE_FALLBACK_S,
    MAIN_PROBE_RETRIES,
    MAIN_PROBE_RETRY_UNTIL_S,
    MAIN_RADIUS,
    MAIN_STALE_FROM_S,
    MAIN_STALE_S,
    OBSERVER_AFTER_ROBO_S,
    OBSERVER_CHOKE_STANDOFF,
    OBSERVER_PATH_FRACTION,
    OBSERVER_POST_UNTIL_S,
    ORACLE_SCOUT_S,
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
    PHOENIX_AWAY_DIST,
    RESCOUT_PROBE_RADIUS,
    RESCOUT_STALE_S,
    SAME_LEVEL_Z,
    STALKER_POKE_AFTER_CORE_S,
)
from bot.geometry import in_map
from bot.intel.detectors import MAIN_PRODUCTION
from bot.intel.scout_tasks import (
    AdeptShadeTask,
    LookTask,
    MainProbeTask,
    Mover,
    OracleTask,
    PatrolProbeTask,
    PhoenixTask,
    PostTask,
    ProbeLookTask,
    ScoutTask,
    nearest_neighbour_order as nearest_order,
)
from bot.intel.threat_flags import FlagStore, Threat

if TYPE_CHECKING:
    from ares import AresBot

    from bot.intel.detectors import Detectors
    from bot.telemetry.logger import Telemetry

# rushes that need every probe at home: no probe scout leaves while one is active
PROBES_STAY_HOME: frozenset[Threat] = frozenset({Threat.WORKER_RUSH, Threat.POOL_12})
# threats whose plans want every combat unit at home (Defense > Scouting, §3); CANNON_RUSH counts
# unless it comes from §4.4 row 3's Forge-first flag alone
UNITS_STAY_HOME: frozenset[Threat] = frozenset(
    {Threat.WORKER_RUSH, Threat.POOL_12, Threat.PROXY, Threat.ONE_BASE_ALLIN}
)


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
        # unit scouts
        self.pinned: set[int] = set()  # units the defense code holds (never taken)
        self.core_done_at: Optional[float] = None
        self.robo_done_at: Optional[float] = None
        self.sent: set[str] = set()  # one-off tasks already given (by name)
        self._last_expansion_check: float = -EXPANSION_CHECK_EVERY_S
        self._expansion_seen_at: dict[Point2, float] = {}
        self._rescout_sent_at: dict[tuple[Threat, str], float] = {}
        self._main_rescout_at: float = -MAIN_STALE_S
        self._last_hallucination: float = -HALLUCINATION_MIN_GAP_S
        self._phoenix_wanted_since: Optional[float] = None

    @property
    def tags(self) -> set[int]:
        return set(self.tasks)

    # -- per step --------------------------------------------------------------------------------

    def step(self, pinned: set[int]) -> None:
        """`pinned`: units the defense code holds (the wall-gap holder, pulled probes)."""
        bot = self.bot
        self.pinned = pinned
        self._track()
        self._take_build_runner_scouts()
        self._schedule_probes()
        self._schedule_units()
        self._hallucinate()
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

    def probes_needed_home(self) -> bool:
        return bool(PROBES_STAY_HOME & self.flags.active_threats())

    def _units_needed_home(self) -> bool:
        active = self.flags.active_threats()
        if UNITS_STAY_HOME & active:
            return True
        return any(f.threat == Threat.CANNON_RUSH and f.source != "forge_first" for f in self.flags.active())

    def _task_active(self, name: str) -> bool:
        return any(t.name == name for t in self.tasks.values())

    def home_point(self) -> Point2:
        """Where unit scouts come back to: our natural if we have a townhall there, else our main."""
        bot = self.bot
        nat: Point2 = bot.mediator.get_own_nat
        if any(th.distance_to(nat) < 3 for th in bot.townhalls):
            return nat
        return bot.start_location

    def _main_probe_active(self) -> bool:
        return any(isinstance(t, MainProbeTask) for t in self.tasks.values())

    def _take_build_runner_scouts(self) -> None:
        mediator = self.bot.mediator
        for probe in mediator.get_units_from_role(role=UnitRole.BUILD_RUNNER_SCOUT, unit_type=UnitTypeId.PROBE):
            if self.main_probes_started == 0 and not self.probes_needed_home():
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
        if self.probes_needed_home():
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

    # -- unit scouts ----------------------------------------------------------------------------

    def _track(self) -> None:
        bot = self.bot
        now = bot.time
        if self.core_done_at is None and bot.structures(UnitTypeId.CYBERNETICSCORE).ready:
            self.core_done_at = now
        if self.robo_done_at is None and bot.structures(UnitTypeId.ROBOTICSFACILITY).ready:
            self.robo_done_at = now
        for p in bot.expansion_locations_list:
            if bot.is_visible(p):
                self._expansion_seen_at[p] = now

    def _free_units(self, types: frozenset[UnitTypeId]) -> list[Unit]:
        """Ours, ready, not scouting, not held by the defense code; nearest our natural first."""
        nat = self.bot.mediator.get_own_nat
        units = [
            u for u in self.bot.units
            if u.type_id in types and u.is_ready and u.tag not in self.tasks and u.tag not in self.pinned
        ]
        return sorted(units, key=lambda u: u.distance_to(nat))

    def _free_observers(self) -> list[Unit]:
        observers = self._free_units(frozenset({UnitTypeId.OBSERVER}))
        if self.bot.time >= OBSERVER_POST_UNTIL_S:
            observers = observers[1:]  # §4.3: from 6:00 one travels with the army
        return observers

    def _give(self, task: ScoutTask, unit: Unit, why: str) -> None:
        logger.info(f"SCOUT {task.name}: {unit.type_id.name} {unit.tag} at {self.bot.time_formatted} ({why})")
        self._start(task, unit)

    def _schedule_units(self) -> None:
        bot = self.bot
        now = bot.time
        race = bot.enemy_race
        enemy_main: Point2 = bot.enemy_start_locations[0]
        enemy_nat: Point2 = bot.mediator.get_enemy_nat
        own_nat: Point2 = bot.mediator.get_own_nat
        # §4.4 row 15: re-scout with the first unit (Adept/Stalker)
        if (
            "aggro_rescout" not in self.sent
            and self.flags.is_active(Threat.UNKNOWN_AGGRO)
            and self.detectors.main_scouted_at is None
        ):
            units = self._free_units(frozenset({UnitTypeId.ADEPT, UnitTypeId.STALKER}))
            if units:
                self.sent.add("aggro_rescout")
                unit = units[0]
                task = (
                    AdeptShadeTask(self, unit.tag, enemy_main) if unit.type_id == UnitTypeId.ADEPT
                    else LookTask(self, unit.tag, "aggro_rescout", [enemy_nat, bot.mediator.get_enemy_ramp.top_center, enemy_main])
                )
                self._give(task, unit, "UNKNOWN_AGGRO re-scout")
        if not self._units_needed_home():
            core = self.core_done_at
            if "adept_shade" not in self.sent and (
                (race == Race.Terran and core is not None and now >= core + ADEPT_SCOUT_AFTER_CORE_S)
                or (race == Race.Zerg and now >= ADEPT_SCOUT_PVZ_S)
            ):
                if units := self._free_units(frozenset({UnitTypeId.ADEPT})):
                    self.sent.add("adept_shade")
                    self._give(AdeptShadeTask(self, units[0].tag, enemy_main), units[0], f"{race.name} schedule")
            if (
                "stalker_poke" not in self.sent and race == Race.Protoss
                and core is not None and now >= core + STALKER_POKE_AFTER_CORE_S
            ):
                if units := self._free_units(frozenset({UnitTypeId.STALKER})):
                    self.sent.add("stalker_poke")
                    self._give(LookTask(self, units[0].tag, "stalker_poke", [enemy_nat]), units[0], "PvP schedule")
            if "oracle" not in self.sent and race == Race.Zerg and now >= ORACLE_SCOUT_S:
                if units := self._free_units(frozenset({UnitTypeId.ORACLE})):
                    self.sent.add("oracle")
                    route = [enemy_nat, enemy_main, bot.mediator.get_enemy_third]
                    self._give(OracleTask(self, units[0].tag, route), units[0], "PvZ schedule")
        # Observers
        robo = self.robo_done_at
        if "observer_post" not in self.sent and robo is not None and now < OBSERVER_POST_UNTIL_S:
            post = None
            if race == Race.Terran and now >= robo + OBSERVER_AFTER_ROBO_S:
                post = enemy_nat + (own_nat - enemy_nat) * OBSERVER_PATH_FRACTION
            elif race == Race.Protoss:
                post = enemy_nat.towards(own_nat, OBSERVER_CHOKE_STANDOFF)
            if post is not None and (observers := self._free_observers()):
                self.sent.add("observer_post")
                task = PostTask(self, observers[0].tag, "observer_post", post, OBSERVER_POST_UNTIL_S)
                self._give(task, observers[0], f"{race.name} watch post")
        if (
            "home_observer" not in self.sent and race == Race.Protoss
            and any(s.type_id == UnitTypeId.TWILIGHTCOUNCIL for s in bot.enemy_structures)
            and (observers := self._free_observers())
        ):
            self.sent.add("home_observer")
            task = PostTask(self, observers[0].tag, "home_observer", own_nat.towards(bot.start_location, HOME_OBSERVER_OFFSET), None)
            self._give(task, observers[0], "Twilight Council seen")
        self._expansion_checks()
        self._rescouts()

    def _expansion_checks(self) -> None:
        """§4.3: 4:30, then every 60 s, visit each unscouted expansion location."""
        bot = self.bot
        now = bot.time
        if now < EXPANSION_CHECK_FROM_S or now - self._last_expansion_check < EXPANSION_CHECK_EVERY_S:
            return
        if self._task_active("expansion_check"):
            return
        self._last_expansion_check = now
        observers = self._free_observers()
        enemy_main: Point2 = bot.enemy_start_locations[0]
        enemy_nat: Point2 = bot.mediator.get_enemy_nat
        points = [
            p for p, _ in bot.mediator.get_enemy_expansions
            if now - self._expansion_seen_at.get(p, -EXPANSION_FRESH_S) >= EXPANSION_FRESH_S
            and not any(th.distance_to(p) < 8 for th in bot.townhalls)
            # a probe stays out of the enemy main and natural
            and (observers or (p.distance_to(enemy_main) > 8 and p.distance_to(enemy_nat) > 8))
        ][:EXPANSION_CHECK_MAX]
        if not points:
            return
        if observers:
            unit = observers[0]
            task = LookTask(self, unit.tag, "expansion_check", nearest_order(unit.position, points))
        elif not self.probes_needed_home() and (unit := self._free_probe()) is not None:
            task = ProbeLookTask(self, unit.tag, "expansion_check", nearest_order(unit.position, points))
        else:
            return
        self._give(task, unit, f"{len(points)} locations unseen for {EXPANSION_FRESH_S:g} s")

    def _rescouts(self) -> None:
        """§5 re-scout trigger: stale STRUCTURE evidence, and a stale enemy main after 3:00."""
        bot = self.bot
        now = bot.time
        if self._task_active("rescout"):
            return
        own_nat: Point2 = bot.mediator.get_own_nat
        for key, positions in self.flags.stale.items():
            if now - self._rescout_sent_at.get(key, -RESCOUT_STALE_S) < RESCOUT_STALE_S:
                continue
            points = [Point2(p) for p in positions]
            observers = self._free_observers()
            ours = all(p.distance_to(own_nat) < RESCOUT_PROBE_RADIUS for p in points)
            if observers:
                unit = observers[0]
                task = LookTask(self, unit.tag, "rescout", points)
            elif ours and not self.probes_needed_home() and (unit := self._free_probe()) is not None:
                task = ProbeLookTask(self, unit.tag, "rescout", points)
            else:
                continue
            self._rescout_sent_at[key] = now
            self._give(task, unit, f"{key[0].name} ({key[1]}) evidence stale")
            return
        seen = self.detectors.main_seen_at
        if (
            now >= MAIN_STALE_FROM_S
            and (seen is None or now - seen > MAIN_STALE_S)
            and now - self._main_rescout_at >= MAIN_STALE_S
            and (observers := self._free_observers())
        ):
            self._main_rescout_at = now
            task = LookTask(self, observers[0].tag, "rescout", [bot.enemy_start_locations[0]])
            self._give(task, observers[0], "enemy main unseen")

    def _hallucinate(self) -> None:
        """§4.3 hallucination rule; only a Sentry that already exists (user decision)."""
        bot = self.bot
        now = bot.time
        if self._phoenix_wanted_since is not None:
            new = [u for u in bot.units(UnitTypeId.PHOENIX) if u.is_hallucination and u.tag not in self.tasks]
            if new:
                self._phoenix_wanted_since = None
                enemy_nat: Point2 = bot.mediator.get_enemy_nat
                route = [bot.enemy_start_locations[0], enemy_nat, enemy_nat.towards(self.home_point(), PHOENIX_AWAY_DIST)]
                self._give(PhoenixTask(self, new[0].tag, route), new[0], "hallucination")
            elif now - self._phoenix_wanted_since > 2.0:
                self._phoenix_wanted_since = None
            return
        if now - self._last_hallucination < HALLUCINATION_MIN_GAP_S:
            return
        sentries = [s for s in bot.units(UnitTypeId.SENTRY) if AbilityId.HALLUCINATION_PHOENIX in s.abilities]
        if not sentries:
            return
        race = bot.enemy_race.name
        seen = self.detectors.main_seen_at
        stale_after = HALLUCINATION_STALE_S.get(race, HALLUCINATION_STALE_DEFAULT_S)
        why = None
        if race in HALLUCINATION_AT_S and now >= HALLUCINATION_AT_S[race] and "matchup_phoenix" not in self.sent:
            self.sent.add("matchup_phoenix")
            why = f"{race} schedule"
        elif now >= HALLUCINATION_FROM_S and (seen is None or now - seen > stale_after):
            why = f"enemy main unseen for {stale_after:g} s"
        if why is None:
            return
        sentries[0](AbilityId.HALLUCINATION_PHOENIX)
        self._last_hallucination = now
        self._phoenix_wanted_since = now
        logger.info(f"SCOUT Hallucination (Phoenix) at {bot.time_formatted}: {why}")

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
