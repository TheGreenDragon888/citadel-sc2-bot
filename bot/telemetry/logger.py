"""Per-game metrics (DESIGN.md §8), kept in memory, logged to stdout and written to ./data/logs.

M1 records the economy snapshots the acceptance test needs (probes at 6:00) plus a few §8
metrics that come for free. M3 adds scout records (every scouting task a unit was given, and
how it ended) and the §8 "first enemy aggression time". M4 adds the §8 "army value lost vs
killed", the step-time p99 and the EngagementResult of each attack/retreat decision (kept by
bot/army/army.py, reported here).

M5 (§8, §6):
- at the end of the game, one JSON line with every §8 metric (`game_record`) goes to stdout
  (`METRIC game {...}`) and is appended to ./data/logs/games.jsonl, which keeps the last
  GAME_LOG_KEEP games and drops its oldest lines first if ./data would pass DATA_MAX_BYTES (§2);
- a stdout snapshot every TELEMETRY_SNAPSHOT_EVERY_S (§3 step 7), skipped with the 4:00-10:00
  snapshots while the §6 step guard is on;
- startup time and step counts (over STEP_WARN_MS, guard activations, guarded steps).
"""

import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

from ares.consts import WORKER_TYPES
from loguru import logger

from sc2.ids.unit_typeid import UnitTypeId

from bot.army.engagement import is_fighter
from bot.constants import (
    AGGRESSION_RADIUS,
    AGGRESSION_WORKERS,
    CANNON_RUSH_RADIUS,
    DATA_MAX_BYTES,
    GAME_LOG_FILE,
    GAME_LOG_KEEP,
    GAME_LOG_MAX_EVENTS,
    LADDER_TIE_GAME_SECONDS,
    LOGS_SUBDIR,
    LOST_FAR_DISTANCE,
    METRIC_TIMES_S,
    SCOUT_LOSS_CHECK_S,
    TELEMETRY_SNAPSHOT_EVERY_S,
)
from bot.data_files import data_path, data_size, read_text, write_text

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
        self.step_ms: list[float] = []  # every step, for the p99 (§6)
        self.army_value_lost: float = 0.0  # §8, fighting units only (no workers or structures)
        self.army_value_killed: float = 0.0
        # M5
        self.game_id: str = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"
        self.startup_ms: Optional[float] = None
        self.steps_over_warn: int = 0
        self.guard_activations: int = 0
        self.guarded_steps: int = 0
        self._last_snapshot: float = 0.0
        self.log_written: bool = False
        # M7 §8: army units lost by their intent at death, and those lost farther than
        # LOST_FAR_DISTANCE from the intent's point ("scout" for scouting units, "none" without one)
        self.lost_by_intent: dict[str, int] = {}
        self.lost_far: dict[str, int] = {}

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

    def on_own_unit_destroyed(self, unit, role: str = "?", intent=None) -> None:
        """`unit` is last step's snapshot of our destroyed unit; `role` its ares role; `intent`
        the army's (mode, point) for it, if it had one (M7)."""
        scouting = unit.tag in self._active_scouts
        if scouting:
            self.scout_ended(unit.tag, "expired" if unit.is_hallucination else "lost")
        if is_fighter(unit):
            self.army_value_lost += self._value(unit.type_id)
            self._army_unit_lost(unit, "scout" if scouting else intent)
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

    def _army_unit_lost(self, unit, intent) -> None:
        """M7 §8: where an army unit died, what it was doing, and how far from its point."""
        pos = unit.position  # a plain point: `unit` is last step's object (see PROBE lost below)
        if intent == "scout" or intent is None:
            mode, distance = intent or "none", None
        else:
            mode, point = intent
            distance = pos.distance_to(point)
        self.lost_by_intent[mode] = self.lost_by_intent.get(mode, 0) + 1
        if distance is not None and distance > LOST_FAR_DISTANCE:
            self.lost_far[mode] = self.lost_far.get(mode, 0) + 1
        logger.info(
            f"UNIT lost {unit.type_id.name} at {pos.rounded} ({self.bot.time_formatted}, {mode}"
            + (f" {distance:.0f} from its point" if distance is not None else "")
            + ")"
        )

    def record_step_time(self, started: float) -> float:
        """`started` is `time.perf_counter()` at the start of `on_step`; returns the step's ms."""
        ms = (time.perf_counter() - started) * 1000
        self.step_count += 1
        self.step_total_ms += ms
        self.step_max_ms = max(self.step_max_ms, ms)
        self.step_ms.append(ms)
        return ms

    def step_p99_ms(self) -> float:
        if not self.step_ms:
            return 0.0
        ordered = sorted(self.step_ms)
        return ordered[min(len(ordered) - 1, int(0.99 * len(ordered)))]

    def _value(self, type_id: UnitTypeId) -> float:
        cost = self.bot.calculate_unit_value(type_id)
        return cost.minerals + cost.vespene

    def on_enemy_unit_destroyed(self, unit) -> None:
        """`unit` is last step's snapshot of a destroyed enemy unit (not a structure)."""
        if is_fighter(unit):
            self.army_value_killed += self._value(unit.type_id)

    def step(self, snapshot: bool = True) -> None:
        """Every step. `snapshot` False (§6 step guard): no snapshot this step."""
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
        if not snapshot:
            return
        for mark in METRIC_TIMES_S:
            if mark not in self.snapshots and now >= mark:
                self._snapshot(mark)
        if now - self._last_snapshot >= TELEMETRY_SNAPSHOT_EVERY_S:
            self._last_snapshot = now
            self._periodic_snapshot()

    def _periodic_snapshot(self) -> None:
        """§3 step 7: a stdout snapshot every TELEMETRY_SNAPSHOT_EVERY_S."""
        bot = self.bot
        logger.info(
            f"METRIC snap t={bot.time_formatted} supply={int(bot.supply_used)}/{int(bot.supply_cap)} "
            f"army_supply={int(bot.supply_army)} probes={len(bot.workers)} bases={len(bot.ready_townhalls)} "
            f"minerals={bot.minerals} vespene={bot.vespene} value_lost={self.army_value_lost:.0f} "
            f"value_killed={self.army_value_killed:.0f}"
        )

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

    def end_report(self, flags=None, army=None) -> None:
        mean = self.step_total_ms / self.step_count if self.step_count else 0.0
        logger.info(
            f"METRIC end t={self.bot.time_formatted} supply_blocked_s={self.supply_blocked_s:.1f} "
            f"steps={self.step_count} step_mean_ms={mean:.1f} step_p99_ms={self.step_p99_ms():.1f} "
            f"step_max_ms={self.step_max_ms:.1f}"
        )
        # §8: army value lost vs killed; EngagementResult at each attack/retreat decision
        logger.info(
            f"METRIC army value_lost={self.army_value_lost:.0f} value_killed={self.army_value_killed:.0f}"
        )
        for d in army.decisions if army is not None else []:
            values = f" values {d.own_value:.0f} vs {d.enemy_value:.0f}" if d.own_value is not None else ""
            logger.info(f"METRIC engage {_mmss(d.t)} {d.action} level={d.level} ({d.reason}){values}")
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

    # -- M5: the per-game record (§8) ------------------------------------------------------------

    def game_record(
        self, result: str, flags=None, army=None, opener: str = "", ruleset: Optional[str] = None,
        wall_ok: Optional[bool] = None, memory=None, preraised: Optional[list[str]] = None, errors=None,
        detectors=None,
    ) -> dict[str, Any]:
        """Every §8 metric for this game as one JSON-ready dict."""
        bot = self.bot
        mean = self.step_total_ms / self.step_count if self.step_count else 0.0

        def snap(mark: int, key: str):
            return self.snapshots[mark][key] if mark in self.snapshots else None

        def capped(items: list) -> list:
            return items[:GAME_LOG_MAX_EVENTS]

        counter = army.counter if army is not None else None
        return {
            "version": 3,
            "game_id": self.game_id,
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "result": result,
            "opponent_id": bot.opponent_id,
            "opponent_race": bot.enemy_race.name,
            "map": bot.game_info.map_name,
            "game_length_s": round(bot.time, 1),
            "tie": result == "Tie" or bot.time >= LADDER_TIE_GAME_SECONDS,
            "opener": opener,
            "ruleset": ruleset,
            "wall_ok": wall_ok,
            "flags": capped([
                {
                    "threat": r.threat.name, "source": r.source, "raised": round(r.raised_at, 1), "reason": r.reason,
                    "expired": round(r.expired_at, 1) if r.expired_at is not None else None, "expire_reason": r.expire_reason,
                }
                for r in (flags.history if flags is not None else [])
            ]),
            "preraised": preraised or [],
            "opponent_games_before": memory.record["games"] if memory is not None and memory.loaded else 0,
            "probes": {"4:00": snap(240, "probes"), "6:00": snap(360, "probes"), "8:00": snap(480, "probes")},
            "bases": {"6:00": snap(360, "bases"), "10:00": snap(600, "bases")},
            "supply_blocked_s": round(self.supply_blocked_s, 1),
            "unspent": {
                "6:00": {"minerals": snap(360, "minerals"), "vespene": snap(360, "vespene")},
                "10:00": {"minerals": snap(600, "minerals"), "vespene": snap(600, "vespene")},
            },
            "first_aggression": (
                {"time": round(self.first_aggression[0], 1), "what": self.first_aggression[1]}
                if self.first_aggression is not None else None
            ),
            "army_value": {"lost": round(self.army_value_lost), "killed": round(self.army_value_killed)},
            "engage": capped([
                {
                    "t": round(d.t, 1), "action": d.action, "level": d.level, "reason": d.reason,
                    # M7 §8: the fight values the level came from (None when nothing was simulated)
                    "own_value": round(d.own_value) if d.own_value is not None else None,
                    "enemy_value": round(d.enemy_value) if d.enemy_value is not None else None,
                }
                for d in (army.decisions if army is not None else [])
            ]),
            "counterattacks": capped(list(counter.outcomes) if counter is not None else []),
            "scouts": {"tasks": len(self.scouts), f"lost_before_{SCOUT_LOSS_CHECK_S:.0f}s": len(self.scouts_lost_before())},
            "startup_ms": round(self.startup_ms, 1) if self.startup_ms is not None else None,
            "step_ms": {
                "mean": round(mean, 2), "p99": round(self.step_p99_ms(), 1), "max": round(self.step_max_ms, 1),
                "count": self.step_count, "over_warn": self.steps_over_warn,
                "guard_activations": self.guard_activations, "guarded_steps": self.guarded_steps,
            },
            # M6 error guard: errors caught per part, and each part's first one ("m:ss Type: message")
            "errors": dict(errors.counts) if errors is not None else {},
            "errors_first": dict(errors.first) if errors is not None else {},
            # M7 §8: army units lost by intent, and those lost far from their point
            "lost_by_intent": dict(self.lost_by_intent),
            "lost_far": dict(self.lost_far),
            # M7 §8: enemy structure and capital ship types, first seen (game seconds)
            "tech_seen": capped([
                {"type": name, "t": round(t, 1)}
                for name, t in sorted((detectors.first_seen if detectors is not None else {}).items(), key=lambda kv: kv[1])
            ]),
        }

    def write_game_record(self, record: dict[str, Any]) -> bool:
        """§8: stdout, and a line in ./data/logs/games.jsonl (the last GAME_LOG_KEEP games, oldest
        dropped first to keep ./data under DATA_MAX_BYTES, §2)."""
        line = json.dumps(record, separators=(",", ":"), default=str)
        logger.info(f"METRIC game {line}")
        path = data_path(LOGS_SUBDIR, GAME_LOG_FILE)
        lines = [ln for ln in (read_text(path) or "").splitlines() if ln.strip()]
        lines = lines[-(GAME_LOG_KEEP - 1):] + [line]
        budget = DATA_MAX_BYTES - data_size(exclude=path)
        while len(lines) > 1 and sum(len(ln) + 1 for ln in lines) > budget:
            lines.pop(0)
        if sum(len(ln) + 1 for ln in lines) > budget:
            logger.warning(f"LOG not written: ./data is at {DATA_MAX_BYTES - budget} bytes of {DATA_MAX_BYTES}")
            return False
        write_text(path, "\n".join(lines) + "\n")
        self.log_written = True
        logger.info(f"LOG {path.name}: {len(lines)} games, {sum(len(ln) + 1 for ln in lines)} bytes")
        return True
