"""Citadel's own threat detectors for M2 (DESIGN.md §4.2, §4.4).

Runs every intel tick, after the ares bridge. Each detector raises a ThreatFlag through the
shared `FlagStore` (§5); `expiry_context()` gives the store what it needs to expire them,
including the §5 phase rules.

| source | threat | evidence | trigger |
|---|---|---|---|
| worker_rush | WORKER_RUSH | UNIT | >= WORKER_RUSH_MIN_WORKERS enemy workers within WORKER_RUSH_RADIUS of our main before WORKER_RUSH_UNTIL_S (§4.2 backup) |
| cannon_structures | CANNON_RUSH | STRUCTURE | enemy Pylon/Forge/Photon Cannon within CANNON_RUSH_RADIUS of our main or natural before CANNON_RUSH_UNTIL_S |
| cannon_probe | CANNON_RUSH | UNIT | an enemy probe inside our main for CANNON_PROBE_LINGER_S between CANNON_PROBE_FROM_S and CANNON_PROBE_UNTIL_S |
| early_pool | POOL_12 | STRUCTURE | Spawning Pool started before the natural Hatchery (start times from build progress and game-data build times; a Pool started by EARLY_POOL_CERTAIN_S needs no natural check) |
| early_lings | POOL_12 | UNIT | Zerglings seen before EARLY_LINGS_UNTIL_S |
| proxy_missing | PROXY | STRUCTURE | once the enemy main is scouted, not before PROXY_CHECK_FROM_S: no Barracks (T) / Gateway (P) there, or Terran SCVs <= PROXY_TERRAN_MAX_SCVS, or Protoss probes >= PROXY_PROTOSS_WORKERS_SHORT short of expected (§4.4 rows 7, 10) |
| proxy_structure | PROXY | STRUCTURE | an enemy production structure > PROXY_FAR_FROM_MAIN from the enemy main before PROXY_DETECT_UNTIL_S |
| no_natural | ONE_BASE_ALLIN | STRUCTURE | no natural townhall by NO_NATURAL_DEADLINE_S, plus >= NO_NATURAL_MIN_GAS gas or >= NO_NATURAL_MIN_PRODUCTION production structures |

"Missing structure" flags have no tags or positions, so they expire only by their phase rule.
"""

import math
from typing import TYPE_CHECKING, Callable, Optional

from loguru import logger
from sc2.data import Race
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit

from bot.constants import (
    BRIDGE_HOME_RADIUS,
    CANNON_PROBE_FROM_S,
    CANNON_PROBE_LINGER_S,
    CANNON_PROBE_UNTIL_S,
    CANNON_RUSH_PHASE_END_S,
    CANNON_RUSH_PHASE_RADIUS,
    CANNON_RUSH_RADIUS,
    CANNON_RUSH_UNTIL_S,
    EARLY_LINGS_UNTIL_S,
    EARLY_POOL_CERTAIN_S,
    MAIN_RADIUS,
    MAIN_SAMPLE_STEP,
    MAIN_SCOUTED_FRACTION,
    NATURAL_TOWNHALL_RADIUS,
    NO_NATURAL_DEADLINE_S,
    NO_NATURAL_GIVE_UP_S,
    NO_NATURAL_MIN_GAS,
    NO_NATURAL_MIN_PRODUCTION,
    NO_NATURAL_SEEN_GRACE_S,
    ONE_BASE_PHASE_ARMY_SUPPLY,
    ONE_BASE_PHASE_BATTERIES,
    ONE_BASE_PHASE_END_S,
    POOL_12_PHASE_END_S,
    PROXY_CHECK_FROM_S,
    PROXY_DETECT_UNTIL_S,
    PROXY_FAR_FROM_MAIN,
    PROXY_NEAR_ENEMY_TOWNHALL,
    PROXY_PHASE_END_S,
    PROXY_PROTOSS_WORKERS_SHORT,
    PROXY_TERRAN_MAX_SCVS,
    SAME_LEVEL_Z,
    WORKER_RUSH_CONFIRM_MIN,
    WORKER_RUSH_MIN_WORKERS,
    WORKER_RUSH_RADIUS,
    WORKER_RUSH_UNTIL_S,
)
from bot.intel.threat_flags import Evidence, ExpiryContext, FlagStore, Threat

if TYPE_CHECKING:
    from ares import AresBot

WORKERS: frozenset[UnitTypeId] = frozenset({UnitTypeId.PROBE, UnitTypeId.SCV, UnitTypeId.DRONE})
CANNON_RUSH_TYPES: frozenset[UnitTypeId] = frozenset(
    {UnitTypeId.PYLON, UnitTypeId.FORGE, UnitTypeId.PHOTONCANNON}
)
MAIN_PRODUCTION: dict[Race, frozenset[UnitTypeId]] = {
    Race.Terran: frozenset({UnitTypeId.BARRACKS, UnitTypeId.BARRACKSFLYING}),
    Race.Protoss: frozenset({UnitTypeId.GATEWAY, UnitTypeId.WARPGATE}),
}
PRODUCTION: frozenset[UnitTypeId] = frozenset(
    {
        UnitTypeId.BARRACKS, UnitTypeId.FACTORY, UnitTypeId.STARPORT,
        UnitTypeId.GATEWAY, UnitTypeId.WARPGATE, UnitTypeId.STARGATE, UnitTypeId.ROBOTICSFACILITY,
    }
)
GAS_BUILDINGS: frozenset[UnitTypeId] = frozenset(
    {
        UnitTypeId.ASSIMILATOR, UnitTypeId.ASSIMILATORRICH, UnitTypeId.EXTRACTOR,
        UnitTypeId.EXTRACTORRICH, UnitTypeId.REFINERY, UnitTypeId.REFINERYRICH,
    }
)
TOWNHALLS: frozenset[UnitTypeId] = frozenset(
    {
        UnitTypeId.NEXUS, UnitTypeId.COMMANDCENTER, UnitTypeId.COMMANDCENTERFLYING,
        UnitTypeId.ORBITALCOMMAND, UnitTypeId.ORBITALCOMMANDFLYING, UnitTypeId.PLANETARYFORTRESS,
        UnitTypeId.HATCHERY, UnitTypeId.LAIR, UnitTypeId.HIVE,
    }
)


def _mmss(seconds: float) -> str:
    return f"{int(seconds) // 60}:{int(seconds) % 60:02d}"


class Detectors:
    def __init__(self, bot: "AresBot", flags: FlagStore, override_for: Callable[[Threat, Evidence], bool]):
        """`override_for(threat, evidence_kind)` says whether a new flag ends the ares opener."""
        self.bot = bot
        self.flags = flags
        self.override_for = override_for
        # scouting state
        self._main_samples: Optional[list[Point2]] = None
        self._main_seen: set[int] = set()
        self.main_scouted_at: Optional[float] = None
        self.enemy_workers_in_main: set[int] = set()
        self.natural_seen_at: Optional[float] = None  # last time the enemy natural spot was in vision
        self.natural_townhall_seen_at: Optional[float] = None
        self._probe_in_main_since: dict[int, float] = {}
        # early pool
        self.pool_start: Optional[float] = None
        self.nat_hatch_start: Optional[float] = None
        self._pool_decided: bool = False
        # one-time checks
        self.proxy_checked: bool = False
        self.no_natural_checked: bool = False

    # -- helpers -------------------------------------------------------------------------------

    def _raise(self, threat: Threat, evidence: Evidence, source: str, reason: str, **kw) -> None:
        self.flags.raise_flag(
            threat, evidence, source, self.bot.time, reason,
            override_opener=self.override_for(threat, evidence), **kw,
        )

    def _home_points(self) -> list[Point2]:
        bot = self.bot
        return [bot.start_location, bot.mediator.get_own_nat] + [th.position for th in bot.townhalls]

    def _visible_enemy_units(self, types: frozenset[UnitTypeId]) -> list[Unit]:
        return [u for u in self.bot.enemy_units if u.type_id in types and not u.is_memory]

    def _in_our_main(self, point: Point2) -> bool:
        bot = self.bot
        return (
            point.distance_to(bot.start_location) <= MAIN_RADIUS
            and abs(bot.get_terrain_z_height(point) - bot.get_terrain_z_height(bot.start_location)) < SAME_LEVEL_Z
        )

    def _start_time(self, unit: Unit) -> float:
        """Game second the structure was started, from its build progress (for a finished one,
        the latest it can have started)."""
        build_s = self.bot.game_data.units[unit.type_id.value].cost.time / 22.4
        return self.bot.time - unit.build_progress * build_s

    @property
    def enemy_race(self) -> Race:
        return self.bot.enemy_race

    def no_natural_deadline(self) -> float:
        race = self.enemy_race.name if self.enemy_race in (Race.Terran, Race.Zerg, Race.Protoss) else "Random"
        return NO_NATURAL_DEADLINE_S[race]

    @property
    def natural_resolved(self) -> bool:
        """True once the natural scout has nothing left to learn at the enemy natural."""
        return self.no_natural_checked and (self.enemy_race != Race.Zerg or self._pool_decided or self.pool_start is None)

    # -- per intel tick ------------------------------------------------------------------------

    def update(self) -> None:
        self._track_scouting()
        self._worker_rush()
        self._cannon_rush()
        self._early_pool()
        self._proxy()
        self._no_natural()

    def _track_scouting(self) -> None:
        bot = self.bot
        now = bot.time
        enemy_main: Point2 = bot.enemy_start_locations[0]
        if self._main_samples is None:
            self._main_samples = self._sample_main(enemy_main)
        if self.main_scouted_at is None:
            for i, p in enumerate(self._main_samples):
                if i not in self._main_seen and bot.is_visible(p):
                    self._main_seen.add(i)
            if self._main_samples and len(self._main_seen) >= MAIN_SCOUTED_FRACTION * len(self._main_samples):
                self.main_scouted_at = now
                logger.info(
                    f"SCOUT enemy main scouted at {bot.time_formatted} "
                    f"({len(self._main_seen)}/{len(self._main_samples)} sample points seen)"
                )
        for w in self._visible_enemy_units(WORKERS):
            if w.distance_to(enemy_main) < MAIN_RADIUS:
                self.enemy_workers_in_main.add(w.tag)
        nat: Point2 = bot.mediator.get_enemy_nat
        if bot.is_visible(nat):
            self.natural_seen_at = now
        if any(s.type_id in TOWNHALLS and s.distance_to(nat) < NATURAL_TOWNHALL_RADIUS for s in bot.enemy_structures):
            if self.natural_townhall_seen_at is None:
                logger.info(f"SCOUT enemy natural townhall seen at {bot.time_formatted}")
            self.natural_townhall_seen_at = now

    def _sample_main(self, enemy_main: Point2) -> list[Point2]:
        bot = self.bot
        z = bot.get_terrain_z_height(enemy_main)
        points = []
        steps = int(MAIN_RADIUS // MAIN_SAMPLE_STEP)
        for dx in range(-steps, steps + 1):
            for dy in range(-steps, steps + 1):
                p = Point2((enemy_main.x + dx * MAIN_SAMPLE_STEP, enemy_main.y + dy * MAIN_SAMPLE_STEP))
                if (
                    p.distance_to(enemy_main) <= MAIN_RADIUS
                    and bot.in_pathing_grid(p)
                    and abs(bot.get_terrain_z_height(p) - z) < SAME_LEVEL_Z
                ):
                    points.append(p)
        return points

    # -- WORKER_RUSH ---------------------------------------------------------------------------

    def _worker_rush(self) -> None:
        bot = self.bot
        homes = self._home_points()
        near = [w for w in self._visible_enemy_units(WORKERS) if any(w.distance_to(h) < WORKER_RUSH_RADIUS for h in homes)]
        in_main = [w for w in near if w.distance_to(bot.start_location) < WORKER_RUSH_RADIUS]
        if self.flags.get(Threat.WORKER_RUSH, "worker_rush") is not None:
            if len(near) >= WORKER_RUSH_CONFIRM_MIN:
                self.flags.confirm(Threat.WORKER_RUSH, "worker_rush", bot.time, tags=[w.tag for w in near])
        elif bot.time < WORKER_RUSH_UNTIL_S and len(in_main) >= WORKER_RUSH_MIN_WORKERS:
            self._raise(
                Threat.WORKER_RUSH, Evidence.UNIT, "worker_rush",
                f"{len(in_main)} enemy workers within {WORKER_RUSH_RADIUS:g} of our main",
                tags=[w.tag for w in in_main],
            )

    # -- CANNON_RUSH ---------------------------------------------------------------------------

    def _cannon_rush(self) -> None:
        bot = self.bot
        now = bot.time
        centres = [bot.start_location, bot.mediator.get_own_nat]
        structures = [
            s for s in bot.enemy_structures
            if s.type_id in CANNON_RUSH_TYPES and any(s.distance_to(c) < CANNON_RUSH_RADIUS for c in centres)
        ]
        if structures:
            evidence = {"tags": [s.tag for s in structures], "positions": [s.position for s in structures]}
            if self.flags.get(Threat.CANNON_RUSH, "cannon_structures") is not None:
                self.flags.confirm(Threat.CANNON_RUSH, "cannon_structures", now, **evidence)
            elif now < CANNON_RUSH_UNTIL_S:
                names = ", ".join(sorted({s.type_id.name for s in structures}))
                self._raise(
                    Threat.CANNON_RUSH, Evidence.STRUCTURE, "cannon_structures",
                    f"{len(structures)} enemy {names} within {CANNON_RUSH_RADIUS:g} of our main/natural",
                    **evidence,
                )
        # an enemy probe lingering in our main
        probes = [p for p in self._visible_enemy_units(frozenset({UnitTypeId.PROBE})) if self._in_our_main(p.position)]
        tags = {p.tag for p in probes}
        self._probe_in_main_since = {t: s for t, s in self._probe_in_main_since.items() if t in tags}
        for p in probes:
            self._probe_in_main_since.setdefault(p.tag, now)
        if self.flags.get(Threat.CANNON_RUSH, "cannon_probe") is not None:
            if probes:
                self.flags.confirm(Threat.CANNON_RUSH, "cannon_probe", now, tags=tags)
        elif CANNON_PROBE_FROM_S <= now <= CANNON_PROBE_UNTIL_S:
            lingering = [t for t, since in self._probe_in_main_since.items() if now - since >= CANNON_PROBE_LINGER_S]
            if lingering:
                self._raise(
                    Threat.CANNON_RUSH, Evidence.UNIT, "cannon_probe",
                    f"enemy probe in our main for >= {CANNON_PROBE_LINGER_S:g} s",
                    tags=lingering,
                )

    # -- POOL_12 -------------------------------------------------------------------------------

    def _early_pool(self) -> None:
        bot = self.bot
        now = bot.time
        if self.enemy_race not in (Race.Zerg, Race.Random):
            return
        if self.pool_start is None:
            pools = [s for s in bot.enemy_structures if s.type_id == UnitTypeId.SPAWNINGPOOL]
            if pools:
                self.pool_start = self._start_time(pools[0])
                self._pool_tag, self._pool_pos = pools[0].tag, pools[0].position
                logger.info(f"SCOUT Spawning Pool seen at {bot.time_formatted}, started ~{_mmss(self.pool_start)}")
        if self.nat_hatch_start is None:
            nat = bot.mediator.get_enemy_nat
            hatches = [
                s for s in bot.enemy_structures
                if s.type_id in (UnitTypeId.HATCHERY, UnitTypeId.LAIR, UnitTypeId.HIVE)
                and s.distance_to(nat) < NATURAL_TOWNHALL_RADIUS
            ]
            if hatches:
                self.nat_hatch_start = self._start_time(hatches[0])
                logger.info(f"SCOUT natural Hatchery seen at {bot.time_formatted}, started ~{_mmss(self.nat_hatch_start)}")
        if self.pool_start is not None and not self._pool_decided:
            if self.pool_start <= EARLY_POOL_CERTAIN_S:
                # no natural Hatchery can have started this early, so the Pool came first
                self._pool_decided = True
                self._raise_pool(
                    f"Spawning Pool started ~{_mmss(self.pool_start)}, before any natural Hatchery can start"
                )
            elif self.nat_hatch_start is not None:
                self._pool_decided = True
                if self.pool_start < self.nat_hatch_start:
                    self._raise_pool(f"Spawning Pool started ~{_mmss(self.pool_start)}, natural Hatchery ~{_mmss(self.nat_hatch_start)}")
            elif self.natural_seen_at is not None and self.natural_seen_at > self.pool_start and bot.is_visible(bot.mediator.get_enemy_nat):
                self._pool_decided = True
                self._raise_pool(f"Spawning Pool started ~{_mmss(self.pool_start)}, no natural Hatchery at {bot.time_formatted}")
        # Zerglings seen early
        lings = self._visible_enemy_units(frozenset({UnitTypeId.ZERGLING}))
        if self.flags.get(Threat.POOL_12, "early_lings") is not None:
            homes = self._home_points()
            near = [z for z in lings if any(z.distance_to(h) < 2 * BRIDGE_HOME_RADIUS for h in homes)]
            if near:
                self.flags.confirm(Threat.POOL_12, "early_lings", now)
        elif lings and now < EARLY_LINGS_UNTIL_S:
            self._raise(Threat.POOL_12, Evidence.UNIT, "early_lings", f"{len(lings)} Zerglings seen before {_mmss(EARLY_LINGS_UNTIL_S)}")

    def _raise_pool(self, reason: str) -> None:
        self._raise(
            Threat.POOL_12, Evidence.STRUCTURE, "early_pool", reason,
            tags=[self._pool_tag], positions=[self._pool_pos],
        )

    # -- PROXY ---------------------------------------------------------------------------------

    def _proxy(self) -> None:
        bot = self.bot
        now = bot.time
        race = self.enemy_race
        if (
            not self.proxy_checked
            and race in MAIN_PRODUCTION
            and now >= PROXY_CHECK_FROM_S
            and self.main_scouted_at is not None
        ):
            self.proxy_checked = True
            enemy_main = bot.enemy_start_locations[0]
            in_main = [s for s in bot.enemy_structures if s.type_id in MAIN_PRODUCTION[race] and s.distance_to(enemy_main) < MAIN_RADIUS]
            workers = len(self.enemy_workers_in_main)
            reasons = []
            if not in_main:
                reasons.append(f"no {'Barracks' if race == Race.Terran else 'Gateway'} in the scouted main")
            if race == Race.Terran and workers <= PROXY_TERRAN_MAX_SCVS:
                reasons.append(f"{workers} SCVs seen in the main (<= {PROXY_TERRAN_MAX_SCVS})")
            if race == Race.Protoss:
                build_s = bot.game_data.units[UnitTypeId.PROBE.value].cost.time / 22.4
                # 12 start + one probe per build time since 0:00, less their own scouting probe
                expected = 12 + math.floor(now / build_s) - 1
                if workers <= expected - PROXY_PROTOSS_WORKERS_SHORT:
                    reasons.append(f"{workers} probes seen in the main, expected ~{expected}")
            logger.info(
                f"SCOUT proxy check at {bot.time_formatted}: {len(in_main)} "
                f"{'Barracks' if race == Race.Terran else 'Gateways'} in the main, {workers} workers seen"
            )
            if reasons:
                self._raise(Threat.PROXY, Evidence.STRUCTURE, "proxy_missing", "; ".join(reasons))
        # production structures away from the enemy main
        far = self.far_production()
        if far:
            evidence = {"tags": [s.tag for s in far], "positions": [s.position for s in far]}
            if self.flags.get(Threat.PROXY, "proxy_structure") is not None:
                self.flags.confirm(Threat.PROXY, "proxy_structure", now, **evidence)
            elif now < PROXY_DETECT_UNTIL_S:
                names = ", ".join(sorted({s.type_id.name for s in far}))
                self._raise(
                    Threat.PROXY, Evidence.STRUCTURE, "proxy_structure",
                    f"enemy {names} > {PROXY_FAR_FROM_MAIN:g} from the enemy main", **evidence,
                )

    def far_production(self) -> list[Unit]:
        bot = self.bot
        enemy_main = bot.enemy_start_locations[0]
        townhalls = [s for s in bot.enemy_structures if s.type_id in TOWNHALLS]
        return [
            s for s in bot.enemy_structures
            if s.type_id in PRODUCTION
            and s.distance_to(enemy_main) > PROXY_FAR_FROM_MAIN
            and all(s.distance_to(th) > PROXY_NEAR_ENEMY_TOWNHALL for th in townhalls)
        ]

    # -- ONE_BASE_ALLIN ------------------------------------------------------------------------

    def _no_natural(self) -> None:
        bot = self.bot
        now = bot.time
        if self.no_natural_checked:
            return
        if self.natural_townhall_seen_at is not None:
            self.no_natural_checked = True
            return
        deadline = self.no_natural_deadline()
        if now < deadline:
            return
        seen_recently = self.natural_seen_at is not None and self.natural_seen_at >= deadline - NO_NATURAL_SEEN_GRACE_S
        if not seen_recently:
            if now > deadline + NO_NATURAL_GIVE_UP_S:
                self.no_natural_checked = True
                logger.info(f"SCOUT enemy natural not seen by {bot.time_formatted}: no-natural check skipped")
            return
        self.no_natural_checked = True
        gas = sum(1 for s in bot.enemy_structures if s.type_id in GAS_BUILDINGS)
        production = sum(1 for s in bot.enemy_structures if s.type_id in PRODUCTION)
        logger.info(
            f"SCOUT no natural townhall at {bot.time_formatted} (deadline {_mmss(deadline)}): "
            f"{gas} gas, {production} production structures known"
        )
        if gas >= NO_NATURAL_MIN_GAS or production >= NO_NATURAL_MIN_PRODUCTION:
            self._raise(
                Threat.ONE_BASE_ALLIN, Evidence.STRUCTURE, "no_natural",
                f"no natural townhall by {_mmss(deadline)} with {gas} gas and {production} production structures",
            )

    # -- expiry --------------------------------------------------------------------------------

    def expiry_context(self, army_supply: float) -> ExpiryContext:
        """What `FlagStore.expire` needs, including the §5 phase rules (c)."""
        bot = self.bot
        now = bot.time
        phase: dict[Threat, str] = {}
        # "our townhalls" includes the natural's spot: a natural cancelled under Cannons would
        # otherwise end the flag while the Cannons still stand there (Citadel)
        bases = [th.position for th in bot.townhalls] + [bot.mediator.get_own_nat]
        if now > CANNON_RUSH_PHASE_END_S and not any(
            s.distance_to(b) < CANNON_RUSH_PHASE_RADIUS for s in bot.enemy_structures for b in bases
        ):
            phase[Threat.CANNON_RUSH] = (
                f"time > {_mmss(CANNON_RUSH_PHASE_END_S)}, no enemy structure within "
                f"{CANNON_RUSH_PHASE_RADIUS:g} of our townhalls or natural"
            )
        if now > PROXY_PHASE_END_S and not self.far_production():
            phase[Threat.PROXY] = f"time > {_mmss(PROXY_PHASE_END_S)}, no proxy structure known"
        if self.natural_townhall_seen_at is not None:
            phase[Threat.ONE_BASE_ALLIN] = "enemy natural townhall seen"
        elif now > ONE_BASE_PHASE_END_S:
            batteries = len(bot.mediator.get_own_structures_dict[UnitTypeId.SHIELDBATTERY])
            if batteries >= ONE_BASE_PHASE_BATTERIES and army_supply >= ONE_BASE_PHASE_ARMY_SUPPLY:
                phase[Threat.ONE_BASE_ALLIN] = (
                    f"time > {_mmss(ONE_BASE_PHASE_END_S)} with {batteries} batteries and {army_supply:g} army supply"
                )
        if now > POOL_12_PHASE_END_S:
            phase[Threat.POOL_12] = f"time > {_mmss(POOL_12_PHASE_END_S)}"
        return ExpiryContext(
            is_visible=lambda p: bot.is_visible(Point2(p)),
            visible_enemy_tags={s.tag for s in bot.enemy_structures if s.is_visible},
            phase_over=phase,
        )
