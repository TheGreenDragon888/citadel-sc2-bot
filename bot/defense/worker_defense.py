"""Probe pulls and last-moment cancels (DESIGN.md §3 `defense/worker_defense.py`, §4.2).

Runs every step. Pulled probes get ares's DEFENDING role, so ares's Mining behavior leaves them
alone; released probes go back to GATHERING. Only GATHERING probes are ever pulled (not
builders or the scout). Orders are re-issued only when the target changes (§6 APM).

- Worker rush (WORKER_RUSH active, more than WORKER_RUSH_END_AT enemy workers near our bases):
  all probes but WORKER_RUSH_KEEP_MINING fight, healthiest first; a probe below
  WORKER_RUSH_SWAP_HP HP+shield goes back to mining and a fresh one takes its place. Each hits
  the lowest HP+shield enemy worker in reach, otherwise the nearest.
- Cannon rush (CANNON_RUSH active): 3 probes per unfinished enemy Pylon, 4 per unfinished
  Cannon, 1 per enemy probe near our bases (2 at most), CANNON_PULL_MAX in all. Targets a
  finished Cannon can hit are skipped; finished Pylons and Cannons are left alone, and once any
  Cannon near our bases has finished, only enemy probes are still chased (§4.2 "If a Cannon
  completes: stop the probe attack").
- Zerglings in a mineral line (POOL_12 active): LING_DEFENSE_PROBES_PER_LING probes per
  Zergling within LING_DEFENSE_RADIUS of a mineral line, no chasing beyond it.
- `on_structure_damaged`: cancels our unfinished structure once its HP falls below
  max(CANCEL_HEALTH_MIN, CANCEL_HEALTH_FRACTION x max HP). ares has this rule but never calls it
  (its hub's `on_unit_took_damage` is empty, `ares-sc2/src/ares/managers/hub.py:306`).
"""

from typing import TYPE_CHECKING

from ares.consts import UnitRole
from loguru import logger
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit

from bot.constants import (
    BRIDGE_HOME_RADIUS,
    CANCEL_HEALTH_FRACTION,
    CANCEL_HEALTH_MIN,
    CANNON_PROBES_ON_PROBES_MAX,
    CANNON_PROBES_PER_CANNON,
    CANNON_PROBES_PER_ENEMY_PROBE,
    CANNON_PROBES_PER_PYLON,
    CANNON_PULL_MAX,
    CANNON_RUSH_RADIUS,
    LING_DEFENSE_MAX,
    LING_DEFENSE_PROBES_PER_LING,
    LING_DEFENSE_RADIUS,
    WORKER_RUSH_END_AT,
    WORKER_RUSH_KEEP_MINING,
    WORKER_RUSH_SWAP_HP,
)
from bot.intel.threat_flags import Threat

if TYPE_CHECKING:
    from ares import AresBot

    from bot.defense.defense_planner import DefensePlan, DefensePlanner

WORKERS: frozenset[UnitTypeId] = frozenset({UnitTypeId.PROBE, UnitTypeId.SCV, UnitTypeId.DRONE})


def hp(unit: Unit) -> float:
    return unit.health + unit.shield


class WorkerDefense:
    def __init__(self, bot: "AresBot", planner: "DefensePlanner"):
        self.bot = bot
        self.planner = planner
        self.jobs: dict[int, int] = {}  # our probe tag -> enemy target tag
        self._pull_logged: set[str] = set()

    # -- every step ------------------------------------------------------------------------------

    def step(self, plan: "DefensePlan") -> None:
        bot = self.bot
        wanted: dict[int, int] = {}  # probe tag -> target tag
        if Threat.WORKER_RUSH in plan.active:
            self._worker_rush(wanted)
        if Threat.CANNON_RUSH in plan.active:
            self._cannon_rush(wanted)
        if Threat.POOL_12 in plan.active:
            self._lings_in_mineral_line(wanted)
        # release probes whose job ended
        for tag in [t for t in self.jobs if t not in wanted]:
            self.jobs.pop(tag)
            if bot.unit_tag_dict.get(tag) is not None:
                bot.mediator.assign_role(tag=tag, role=UnitRole.GATHERING)
        for probe_tag, target_tag in wanted.items():
            probe = bot.unit_tag_dict.get(probe_tag)
            target = bot.unit_tag_dict.get(target_tag)
            if probe is None or target is None:
                continue
            if probe_tag not in self.jobs:
                bot.mediator.assign_role(tag=probe_tag, role=UnitRole.DEFENDING)
            self.jobs[probe_tag] = target_tag
            if probe.order_target != target_tag:
                probe.attack(target)

    def _log_once(self, key: str, message: str) -> None:
        if key not in self._pull_logged:
            self._pull_logged.add(key)
            logger.info(f"DEFENSE {message} at {self.bot.time_formatted}")

    def _free_probes(self, wanted: dict[int, int]) -> list[Unit]:
        """Probes we may pull: mining ones and ones already on a defense job, not yet taken."""
        bot = self.bot
        mining = bot.mediator.get_units_from_role(role=UnitRole.GATHERING, unit_type=UnitTypeId.PROBE)
        mine = [p for p in mining if p.tag not in wanted]
        ours = [bot.unit_tag_dict[t] for t in self.jobs if t not in wanted and t in bot.unit_tag_dict]
        return ours + mine

    def _homes(self) -> list[Point2]:
        bot = self.bot
        return [bot.start_location, bot.mediator.get_own_nat] + [th.position for th in bot.townhalls]

    # -- worker rush -------------------------------------------------------------------------------

    def _worker_rush(self, wanted: dict[int, int]) -> None:
        bot = self.bot
        homes = self._homes()
        enemies = [
            e for e in bot.enemy_units
            if e.type_id in WORKERS and not e.is_memory
            and any(e.distance_to(h) < BRIDGE_HOME_RADIUS for h in homes)
        ]
        if len(enemies) <= WORKER_RUSH_END_AT:
            return
        pool = [p for p in self._free_probes(wanted) if hp(p) >= WORKER_RUSH_SWAP_HP]
        total = len(bot.workers)
        pull = max(0, total - WORKER_RUSH_KEEP_MINING)
        # healthiest first; probes already fighting keep their place on ties
        pool.sort(key=lambda p: (-hp(p), p.tag not in self.jobs))
        fighters = pool[:pull]
        self._log_once("worker_rush", f"worker-rush pull: {len(fighters)} probes vs {len(enemies)} enemy workers")
        for probe in fighters:
            wanted[probe.tag] = self._pick_target(probe, enemies).tag

    @staticmethod
    def _pick_target(probe: Unit, enemies: list[Unit]) -> Unit:
        reach = [e for e in enemies if probe.distance_to(e) <= probe.radius + e.radius + probe.ground_range + 0.5]
        if reach:
            return min(reach, key=hp)
        return min(enemies, key=lambda e: probe.distance_to(e))

    # -- cannon rush -------------------------------------------------------------------------------

    def _cannon_rush(self, wanted: dict[int, int]) -> None:
        bot = self.bot
        centres = [bot.start_location, bot.mediator.get_own_nat]
        near = [
            s for s in bot.enemy_structures
            if s.is_visible and any(s.distance_to(c) < CANNON_RUSH_RADIUS for c in centres)
        ]
        slots: list[tuple[Unit, int]] = []
        # §4.2 "If a Cannon completes: stop the probe attack": once any Cannon near our bases is
        # finished, probes leave the structures alone (only the enemy probe is still chased)
        cannon_done = any(s.type_id == UnitTypeId.PHOTONCANNON and s.is_ready for s in near)
        for s in near:
            if cannon_done or s.is_ready or self.planner.cannon_covers(s.position, s.radius):
                continue
            if s.type_id == UnitTypeId.PHOTONCANNON:
                slots.append((s, CANNON_PROBES_PER_CANNON))
            elif s.type_id == UnitTypeId.PYLON:
                slots.append((s, CANNON_PROBES_PER_PYLON))
        # unfinished Cannons first: a finished one is much harder to deal with
        slots.sort(key=lambda t: (t[0].type_id != UnitTypeId.PHOTONCANNON, -t[0].build_progress))
        probes = [
            e for e in bot.enemy_units
            if e.type_id == UnitTypeId.PROBE and not e.is_memory
            and any(e.distance_to(c) < CANNON_RUSH_RADIUS for c in centres)
            and not self.planner.cannon_covers(e.position, 0.5)
        ]
        on_probes = 0
        for e in sorted(probes, key=hp):
            n = min(CANNON_PROBES_PER_ENEMY_PROBE, CANNON_PROBES_ON_PROBES_MAX - on_probes)
            if n <= 0:
                break
            slots.append((e, n))
            on_probes += n
        if not slots:
            return
        free = self._free_probes(wanted)
        used = 0
        for target, count in slots:
            # probes already on this target keep it
            keep = [t for t, tgt in self.jobs.items() if tgt == target.tag and t not in wanted and t in bot.unit_tag_dict][:count]
            for tag in keep:
                wanted[tag] = target.tag
            need = count - len(keep)
            candidates = sorted(
                (p for p in free if p.tag not in wanted), key=lambda p: p.distance_to(target)
            )
            for probe in candidates[: max(0, min(need, CANNON_PULL_MAX - used - len(keep)))]:
                wanted[probe.tag] = target.tag
            used += count
            if used >= CANNON_PULL_MAX:
                break
        self._log_once(
            f"cannon{len(slots)}",
            f"cannon-rush pull: {sum(1 for v in wanted.values())} probes on {len(slots)} targets",
        )

    # -- zerglings in the mineral line ------------------------------------------------------------------

    def _lings_in_mineral_line(self, wanted: dict[int, int]) -> None:
        bot = self.bot
        lines: list[Point2] = []
        for th in bot.townhalls.ready:
            fields = bot.mineral_field.closer_than(10, th)
            if fields:
                lines.append(fields.center.towards(th.position, 2))
        lings = [
            e for e in bot.enemy_units
            if e.type_id == UnitTypeId.ZERGLING and not e.is_memory
            and any(e.distance_to(line) < LING_DEFENSE_RADIUS for line in lines)
        ]
        if not lings:
            return
        count = min(LING_DEFENSE_MAX, LING_DEFENSE_PROBES_PER_LING * len(lings))
        free = [p for p in self._free_probes(wanted) if p.tag not in wanted]
        free.sort(key=lambda p: (-hp(p), min(p.distance_to(z) for z in lings)))
        self._log_once(f"lings{len(lings)}", f"probes vs {len(lings)} Zerglings in the mineral line")
        for probe in free[:count]:
            wanted[probe.tag] = self._pick_target(probe, lings).tag

    # -- cancel structures about to die ------------------------------------------------------------------

    def on_structure_damaged(self, unit: Unit) -> None:
        if not unit.is_structure or unit.is_ready or unit.type_id not in self._cancellable:
            return
        if unit.health < max(CANCEL_HEALTH_MIN, CANCEL_HEALTH_FRACTION * unit.health_max):
            logger.info(
                f"DEFENSE cancelling {unit.type_id.name} at {unit.position.rounded} "
                f"({unit.health:.0f} HP, {unit.build_progress:.0%} built) at {self.bot.time_formatted}"
            )
            unit(AbilityId.CANCEL_BUILDINPROGRESS)

    @property
    def _cancellable(self) -> frozenset[UnitTypeId]:
        # every Protoss structure can be cancelled while under construction
        return frozenset(
            {
                UnitTypeId.NEXUS, UnitTypeId.PYLON, UnitTypeId.ASSIMILATOR, UnitTypeId.GATEWAY,
                UnitTypeId.FORGE, UnitTypeId.CYBERNETICSCORE, UnitTypeId.PHOTONCANNON,
                UnitTypeId.SHIELDBATTERY, UnitTypeId.ROBOTICSFACILITY, UnitTypeId.STARGATE,
                UnitTypeId.TWILIGHTCOUNCIL, UnitTypeId.ROBOTICSBAY, UnitTypeId.FLEETBEACON,
                UnitTypeId.TEMPLARARCHIVE, UnitTypeId.DARKSHRINE,
            }
        )

