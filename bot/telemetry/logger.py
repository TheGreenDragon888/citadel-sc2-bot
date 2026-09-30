"""Per-game metrics (DESIGN.md §8), kept in memory and logged to stdout.

M1 records the economy snapshots the acceptance test needs (probes at 6:00) plus a few §8
metrics that come for free. M3 adds scout records (every scouting task a unit was given, and
how it ended) and the §8 "first enemy aggression time". Writing them to ./data/logs is M5.
"""

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from ares.consts import WORKER_TYPES
from loguru import logger

from sc2.ids.unit_typeid import UnitTypeId

from bot.constants import (
    AGGRESSION_RADIUS,
    AGGRESSION_WORKERS,
    CANNON_RUSH_RADIUS,
    METRIC_TIMES_S,
    SCOUT_LOSS_CHECK_S,
)

if TYPE_CHECKING:
    from ares import AresBot


def _mmss(seconds: float) -> str:
    return f"{int(seconds) // 60}:{int(seconds) % 60:02d}"


# enemy units that don't count as aggression near our bases (§8 first aggression)
NOT_AGGRESSION: frozenset[UnitTypeId] = WORKER_TYPES | frozenset(
    {
        UnitTypeId.OVERLORD, UnitTypeId.OVERLORDTRANSPORT, UnitTypeId.OVERSEER,
        UnitTypeId.OBSERVER, UnitTypeId.OBSERVERSIEGEMODE, UnitTypeId.LARVA, UnitTypeId.EGG,
        UnitTypeId.CHANGELING, UnitTypeId.CHANGELINGMARINE, UnitTypeId.CHANGELINGMARINESHIELD,
        UnitTypeId.CHANGELINGZERGLING, UnitTypeId.CHANGELINGZERGLINGWINGS,
        UnitTypeId.CHANGELINGZEALOT,
    }
)


@dataclass
class ScoutRecord:
    """One scouting task given to one unit (M3 metric). A unit counts as a scout from the moment
    it gets the task until the task ends: `outcome` is "lost" if it died meanwhile."""

    tag: int
    unit_type: str
    task: str
    started_at: float
    ended_at: Optional[float] = None
    outcome: str = ""  # "", "done", "home", "lost", "expired" (a hallucination timing out)


class Telemetry:
    def __init__(self, bot: "AresBot"):
        self.bot = bot
        self.snapshots: dict[int, dict] = {}
        self.supply_blocked_s: float = 0.0
        self._last_time: float = 0.0
        self._blocked_since: Optional[float] = None
        self.step_count: int = 0
        self.step_total_ms: float = 0.0
        self.step_max_ms: float = 0.0
        self.probes_lost: int = 0
        self.scouts: list[ScoutRecord] = []
        self._active_scouts: dict[int, ScoutRecord] = {}
        self.first_aggression: Optional[tuple[float, str]] = None

    # -- scouts (M3) -----------------------------------------------------------------------------

    def scout_started(self, tag: int, unit_type: UnitTypeId, task: str) -> None:
        if tag in self._active_scouts:
            self.scout_ended(tag, "done")
        record = ScoutRecord(tag, unit_type.name, task, self.bot.time)
        self.scouts.append(record)
        self._active_scouts[tag] = record
        logger.info(f"SCOUT start {task}: {unit_type.name} {tag} at {self.bot.time_formatted}")

    def scout_ended(self, tag: int, outcome: str, why: str = "") -> None:
        record = self._active_scouts.pop(tag, None)
        if record is None:
            return
        record.ended_at = self.bot.time
        record.outcome = outcome
        logger.info(
            f"SCOUT {outcome} {record.task}: {record.unit_type} {tag} at {self.bot.time_formatted}"
            + (f" ({why})" if why else "")
        )

    def scouts_lost_before(self, seconds: float = SCOUT_LOSS_CHECK_S) -> list[ScoutRecord]:
        return [r for r in self.scouts if r.outcome == "lost" and r.ended_at is not None and r.ended_at < seconds]

    def on_own_unit_destroyed(self, unit, role: str = "?") -> None:
        """`unit` is last step's snapshot of our destroyed unit; `role` its ares role."""
        if unit.tag in self._active_scouts:
            self.scout_ended(unit.tag, "expired" if unit.is_hallucination else "lost")
        if unit.type_id != UnitTypeId.PROBE:
            return
        self.probes_lost += 1
        # where probes die, and to what (§8 "army value lost"; M2 defense evidence)
        bot = self.bot
        enemies = [e for e in bot.all_enemy_units if not e.is_memory]
        # plain point distances: `unit` is last step's object, and python-sc2's per-step distance
        # cache (Unit.distance_to) indexes it out of range
        pos = unit.position
        near = min(enemies, key=lambda e: e.position.distance_to(pos), default=None)
        logger.info(
            f"PROBE lost at {pos.rounded} ({bot.time_formatted}, {role}); nearest enemy "
            + (f"{near.type_id.name} at {near.position.distance_to(pos):.1f}" if near is not None else "none seen")
        )

    def record_step_time(self, started: float) -> None:
        """`started` is `time.perf_counter()` at the start of `on_step`."""
        ms = (time.perf_counter() - started) * 1000
        self.step_count += 1
        self.step_total_ms += ms
        self.step_max_ms = max(self.step_max_ms, ms)

    def step(self) -> None:
        bot = self.bot
        now = bot.time
        blocked = bot.supply_left <= 0 and bot.supply_cap < 200
        if blocked:
            self.supply_blocked_s += now - self._last_time
            if self._blocked_since is None:
                self._blocked_since = now
        elif self._blocked_since is not None:
            logger.info(
                f"SUPPLY blocked {_mmss(self._blocked_since)}-{_mmss(now)} "
                f"at {int(bot.supply_used)}/{int(bot.supply_cap)}"
            )
            self._blocked_since = None
        self._last_time = now
        if self.first_aggression is None:
            self._check_aggression()
        for mark in METRIC_TIMES_S:
            if mark not in self.snapshots and now >= mark:
                self._snapshot(mark)

    def _check_aggression(self) -> None:
        """§8 first enemy aggression time."""
        bot = self.bot
        homes = [th.position for th in bot.townhalls]
        if not homes:
            return
        near = [
            e for e in bot.enemy_units
            if not e.is_memory and any(e.distance_to(h) < AGGRESSION_RADIUS for h in homes)
        ]
        what = None
        army = [e for e in near if e.type_id not in NOT_AGGRESSION and not e.is_hallucination]
        workers = [e for e in near if e.type_id in WORKER_TYPES]
        if army:
            what = f"{army[0].type_id.name} near our base"
        elif len(workers) >= AGGRESSION_WORKERS:
            what = f"{len(workers)} enemy workers near our base"
        else:
            spots = homes + [bot.mediator.get_own_nat]
            structure = next(
                (s for s in bot.enemy_structures if any(s.distance_to(p) < CANNON_RUSH_RADIUS for p in spots)), None
            )
            if structure is not None:
                what = f"enemy {structure.type_id.name} near our base"
        if what is not None:
            self.first_aggression = (bot.time, what)
            logger.info(f"METRIC first_aggression t={bot.time_formatted}: {what}")

    def _snapshot(self, mark: int) -> None:
        bot = self.bot
        snap = {
            "probes": len(bot.workers),
            "probes_lost": self.probes_lost,
            "bases": len(bot.ready_townhalls),
            "townhalls": len(bot.townhalls),  # includes ones under construction
            "gas": len(bot.gas_buildings),
            "supply_used": int(bot.supply_used),
            "army_supply": int(bot.supply_army),
            "supply_blocked_s": round(self.supply_blocked_s, 1),
            "minerals": bot.minerals,
            "vespene": bot.vespene,
        }
        self.snapshots[mark] = snap
        fields = " ".join(f"{k}={v}" for k, v in snap.items())
        logger.info(f"METRIC t={_mmss(mark)} {fields}")

    def end_report(self, flags=None) -> None:
        mean = self.step_total_ms / self.step_count if self.step_count else 0.0
        logger.info(
            f"METRIC end t={self.bot.time_formatted} supply_blocked_s={self.supply_blocked_s:.1f} "
            f"steps={self.step_count} step_mean_ms={mean:.1f} step_max_ms={self.step_max_ms:.1f}"
        )
        lost = self.scouts_lost_before()
        logger.info(
            f"METRIC scouts tasks={len(self.scouts)} lost_before_{_mmss(SCOUT_LOSS_CHECK_S)}={len(lost)}"
            + "".join(f" [{r.task} {r.unit_type} {_mmss(r.started_at)}-{_mmss(r.ended_at)}]" for r in lost)
        )
        for r in self.scouts:
            end = f"{r.outcome} {_mmss(r.ended_at)}" if r.ended_at is not None else "active"
            logger.info(f"METRIC scout {r.task} {r.unit_type} {r.tag} {_mmss(r.started_at)}: {end}")
        if self.first_aggression is not None:
            logger.info(f"METRIC first_aggression t={_mmss(self.first_aggression[0])}: {self.first_aggression[1]}")
        # §8: flags with their raise and expire reasons and times
        for r in flags.history if flags is not None else []:
            expired = (
                f"expired {_mmss(r.expired_at)}: {r.expire_reason}" if r.expired_at is not None else "still active"
            )
            logger.info(
                f"METRIC flag {r.threat.name} ({r.source}) raised {_mmss(r.raised_at)}: {r.reason}; {expired}"
            )
