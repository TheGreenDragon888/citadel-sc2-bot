"""Counterattack on an out-of-position enemy army (DESIGN.md §4.6).

The rules are plain functions with no game objects (`pick_squad`, `pick_target`, `recall_reason`),
tested offline by scripts/test_counterattack_rules.py; `Counterattack` applies them in the game
through the army commander (bot/army/army.py), which owns the squads and the per-unit control.

Every DECISION_EVERY_STEPS steps (half a period after the main attack decision, to spread the
simulator calls), from COUNTER_FROM_S:
- **Detect** (bot/intel/army_position.py): the remembered enemy army is out of position (§4.6
  conditions 1-2; raises ARMY_OUT_OF_POSITION).
- **Target**: the known enemy base with the lowest local defence value, among bases with no more
  than COUNTER_TARGET_ARMY_FRACTION of the enemy army within COUNTER_TARGET_ARMY_RADIUS
  (condition 3); ties go to the base farther from the enemy army.
- **Squad**: Adepts, then Zealots with Charge, then Stalkers from the DEFEND squad (units the
  defense plan pins are never in a squad), up to COUNTER_SQUAD_MAX_FRACTION of our army supply,
  at least COUNTER_SQUAD_MIN_SUPPLY.
- **Home**: if a home threat is on, the DEFEND units left behind must read >= DEFEND_ENGAGE against
  it (condition 4).
- **Launch** at >= COUNTER_START against the defenders local to the target. The squad becomes the
  HARASS squad; inside the base it shoots what can fight back first, then workers, production and
  the townhall (user decision), and walks to the next of those when nothing is in range.
- **Recall** on any §4.6 rule (`recall_reason`): the out-of-position army's centre near the target or
  the squad, the fight at <= COUNTER_ABORT, the squad below half its start value, out longer than
  COUNTER_MAX_OUT_S, or a home threat the DEFEND units can't hold (Defense > Counterattack, §3);
  also when the target base is cleared. The squad walks home on a danger-aware path
  (`PathUnitToTarget` on the influence grid, bot/army/micro.py `retreat`).
- Never during a main attack; a main attack that launches while the squad is out takes it in
  (`merge`). No new counterattack within COUNTER_RELAUNCH_WAIT_S of the last one's end (Citadel).
Recall checks also run during the §6 step guard, which only skips detection and launch.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable, Optional, Sequence

from ares.consts import TOWNHALL_TYPES
from loguru import logger
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
from sc2.unit import Unit

from bot.army.engagement import ENEMY_DEFENDS, WE_DEFEND, WORKERS, is_fighter
from bot.army.squads import Role
from bot.constants import (
    COUNTER_ABORT,
    COUNTER_BASE_RADIUS,
    COUNTER_DEFENCE_RADIUS,
    COUNTER_FROM_S,
    COUNTER_MAX_OUT_S,
    COUNTER_RECALL_SQUAD_RADIUS,
    COUNTER_RECALL_TARGET_RADIUS,
    COUNTER_RECALL_VALUE_FRACTION,
    COUNTER_RELAUNCH_WAIT_S,
    COUNTER_SQUAD_MAX_FRACTION,
    COUNTER_SQUAD_MIN_SUPPLY,
    COUNTER_START,
    COUNTER_TARGET_ARMY_FRACTION,
    COUNTER_TARGET_ARMY_RADIUS,
    DEFEND_ENGAGE,
    ENGAGE_STATIC_RADIUS,
    STATIC_PENALTY_STALKERS,
)
from bot.intel.army_position import ArmyPosition, ArmyReading
from bot.intel.threat_flags import FlagStore

if TYPE_CHECKING:
    from ares import AresBot

    from bot.army.army import Army

IDLE, OUT = "idle", "out"

# §4.6 "inside the base: workers, then production, then townhall"
PRODUCTION: frozenset[UnitTypeId] = frozenset(
    {
        UnitTypeId.BARRACKS, UnitTypeId.FACTORY, UnitTypeId.STARPORT, UnitTypeId.GATEWAY,
        UnitTypeId.WARPGATE, UnitTypeId.ROBOTICSFACILITY, UnitTypeId.STARGATE,
        UnitTypeId.SPAWNINGPOOL, UnitTypeId.ROACHWARREN, UnitTypeId.BANELINGNEST,
        UnitTypeId.HYDRALISKDEN, UnitTypeId.LURKERDENMP, UnitTypeId.SPIRE, UnitTypeId.GREATERSPIRE,
        UnitTypeId.INFESTATIONPIT, UnitTypeId.ULTRALISKCAVERN,
    }
)


def _mmss(seconds: float) -> str:
    return f"{int(seconds) // 60}:{int(seconds) % 60:02d}"


# -- rules (no game objects) ---------------------------------------------------------------------


def squad_rank(type_id: UnitTypeId, has_charge: bool) -> Optional[int]:
    """§4.6 "fastest units first: Adepts, Zealots with Charge, then Stalkers"; None = not taken."""
    if type_id == UnitTypeId.ADEPT:
        return 0
    if type_id == UnitTypeId.ZEALOT and has_charge:
        return 1
    if type_id == UnitTypeId.STALKER:
        return 2
    return None


@dataclass
class Candidate:
    tag: int
    rank: int  # squad_rank
    supply: float
    distance: float  # to the target (nearer first within a rank)


def pick_squad(candidates: Iterable[Candidate], army_supply: float) -> list[int]:
    """Tags of the squad: by rank, then distance, up to COUNTER_SQUAD_MAX_FRACTION of
    `army_supply`; empty if that comes to less than COUNTER_SQUAD_MIN_SUPPLY."""
    cap = COUNTER_SQUAD_MAX_FRACTION * army_supply
    chosen: list[int] = []
    supply = 0.0
    for c in sorted(candidates, key=lambda c: (c.rank, c.distance)):
        if supply + c.supply <= cap + 1e-9:
            chosen.append(c.tag)
            supply += c.supply
    return chosen if supply >= COUNTER_SQUAD_MIN_SUPPLY else []


@dataclass
class BaseOption:
    position: Point2
    defence: float  # local_defence_value
    army_value: float  # remembered enemy army value within COUNTER_TARGET_ARMY_RADIUS


def pick_target(
    bases: Sequence[BaseOption], total_army_value: float, army_center: Optional[Point2]
) -> tuple[Optional[BaseOption], str]:
    """§4.6: the base with the lowest defence among those the enemy army isn't near (condition 3);
    ties go to the base farther from the enemy army's centre. Returns (base, why)."""
    if not bases:
        return None, "no known enemy base"
    limit = COUNTER_TARGET_ARMY_FRACTION * total_army_value
    eligible = [b for b in bases if b.army_value <= limit]
    if not eligible:
        return None, f"enemy army within {COUNTER_TARGET_ARMY_RADIUS:g} of every known base"
    lowest = min(b.defence for b in eligible)
    tied = [b for b in eligible if b.defence <= lowest + 1e-6]
    if army_center is not None:
        best = max(tied, key=lambda b: b.position.distance_to(army_center))
    else:
        best = tied[0]
    return best, f"defence {best.defence:.0f}, lowest of {len(eligible)}/{len(bases)} bases"


def recall_reason(
    now: float,
    launched_at: float,
    level: Optional[int],
    squad_value: float,
    start_value: float,
    army_center: Optional[Point2],
    target: Point2,
    squad_center: Optional[Point2],
    home_unheld: str = "",
) -> Optional[str]:
    """§4.6 "return home" rules, defense first; None = keep going."""
    if home_unheld:
        return f"defense: {home_unheld}"
    if army_center is not None:
        if army_center.distance_to(target) <= COUNTER_RECALL_TARGET_RADIUS:
            return f"enemy army within {COUNTER_RECALL_TARGET_RADIUS:g} of the target ({army_center.distance_to(target):.0f})"
        if squad_center is not None and army_center.distance_to(squad_center) <= COUNTER_RECALL_SQUAD_RADIUS:
            return f"enemy army within {COUNTER_RECALL_SQUAD_RADIUS:g} of the squad ({army_center.distance_to(squad_center):.0f})"
    if level is not None and level <= COUNTER_ABORT:
        return f"level {level} <= {COUNTER_ABORT}"
    if squad_value < COUNTER_RECALL_VALUE_FRACTION * start_value:
        return f"value {squad_value:.0f} < {COUNTER_RECALL_VALUE_FRACTION:g} x start {start_value:.0f}"
    if now - launched_at > COUNTER_MAX_OUT_S:
        return f"out for {now - launched_at:.1f} s > {COUNTER_MAX_OUT_S:g} s"
    return None


# -- in the game ---------------------------------------------------------------------------------


class Counterattack:
    def __init__(self, bot: "AresBot", army: "Army", flags: Optional[FlagStore]):
        self.bot = bot
        self.army = army
        self.position = ArmyPosition(bot, flags)
        self.state: str = IDLE
        self.target: Optional[Point2] = None
        self.launched_at: float = 0.0
        self.ended_at: Optional[float] = None
        self.start_value: float = 0.0
        self.watched: set[int] = set()  # the out-of-position army's tags at launch
        self.last_level: Optional[int] = None
        self.outcomes: list[dict] = []  # §8 counterattack outcomes
        self.current: Optional[dict] = None
        # visible enemies at the target base, refreshed each army tick: workers, production, townhalls
        self.goals: list[list[int]] = [[], [], []]
        self.guard_skips: int = 0  # launch evaluations skipped by the §6 step guard
        self._wait: str = ""

    # -- interface -----------------------------------------------------------------------------

    def tick(self, guarded: bool) -> None:
        """Every DECISION_EVERY_STEPS."""
        if self.state == OUT:
            self._check_recall()
        elif guarded:
            self.guard_skips += 1
        else:
            self._evaluate_launch()

    def merge(self) -> None:
        """The main attack launched: it takes the counterattack squad (§4.6)."""
        if self.state != OUT:
            return
        tags = self.army.squads.tags(Role.HARASS)
        self.army.squads.assign(tags, Role.ATTACK)
        for tag in tags:
            self.army.intents.pop(tag, None)
        self._end(f"merged into the main attack ({len(tags)} units)")

    def refresh_goals(self) -> None:
        """Visible enemies at the target base in §4.6 order (every army tick while out)."""
        if self.state != OUT or self.target is None:
            self.goals = [[], [], []]
            return
        bot = self.bot
        near = [
            e for e in bot.all_enemy_units
            if not e.is_memory and not e.is_snapshot and e.distance_to(self.target) <= COUNTER_BASE_RADIUS
        ]
        self.goals = [
            [e.tag for e in near if e.type_id in WORKERS],
            [e.tag for e in near if e.type_id in PRODUCTION],
            [e.tag for e in near if e.type_id in TOWNHALL_TYPES],
        ]

    def on_enemy_destroyed(self, unit: Unit) -> None:
        """`unit`: last step's snapshot of a destroyed enemy unit or structure."""
        if self.state != OUT or self.current is None or self.target is None:
            return
        if unit.position.distance_to(self.target) > COUNTER_BASE_RADIUS + ENGAGE_STATIC_RADIUS:
            return
        current = self.current
        if unit.type_id in WORKERS:
            current["workers_killed"] += 1
        elif unit.is_structure:
            current["structures_killed"] += 1
        else:
            current["units_killed"] += 1
        if current["first_kill"] is None:
            current["first_kill"] = unit.type_id.name
        current["value_killed"] += self.position.value(unit)

    # -- launch ----------------------------------------------------------------------------------

    def _supply(self, units: Iterable[Unit]) -> float:
        return sum(self.bot.calculate_supply_cost(u.type_id) for u in units)

    def defence_of(self, base: Point2) -> float:
        """local_defence_value: remembered units within COUNTER_DEFENCE_RADIUS plus static defence
        within ENGAGE_STATIC_RADIUS counted as Stalkers' worth of value (§4.5.2's penalty)."""
        stalker = self.bot.calculate_unit_value(UnitTypeId.STALKER)
        stalker_value = stalker.minerals + stalker.vespene
        static = sum(
            STATIC_PENALTY_STALKERS[s.type_id] * stalker_value
            for s in self.army.engagement.static_defense_near(base)
        )
        return self.position.value_near(base, COUNTER_DEFENCE_RADIUS) + static

    def _home_level(self, leaving: set[int]) -> Optional[int]:
        """Level of the DEFEND units (minus `leaving`) against the home threat; None if none."""
        army = self.army
        if army.threat is None:
            return None
        engagement = army.engagement
        home = [u for u in army.fighters(Role.DEFEND) if u.tag not in leaving]
        enemy = engagement.enemies_near([army.threat]) + engagement.static_defense_near(army.threat)
        return engagement.level(home + army.own_cannons_near(army.threat), enemy, WE_DEFEND)

    def _evaluate_launch(self) -> None:
        bot = self.bot
        army = self.army
        now = bot.time
        if now < COUNTER_FROM_S or army.attacking:
            return
        if self.ended_at is not None and now - self.ended_at < COUNTER_RELAUNCH_WAIT_S:
            return
        reading = self.position.update()
        if not reading.out:
            self._set_wait("")
            return
        bases = [
            BaseOption(p, self.defence_of(p), self.position.value_near(p, COUNTER_TARGET_ARMY_RADIUS))
            for p in self.position.enemy_bases()
        ]
        target, target_why = pick_target(bases, reading.total_value, reading.center)
        if target is None:
            self._set_wait(target_why)
            return
        has_charge = UpgradeId.CHARGE in bot.state.upgrades
        candidates = []
        for u in army.fighters(Role.DEFEND):
            rank = squad_rank(u.type_id, has_charge)
            if rank is not None and not army.retreating(u.tag):
                candidates.append(
                    Candidate(u.tag, rank, bot.calculate_supply_cost(u.type_id), u.distance_to(target.position))
                )
        army_supply = self._supply(u for u in bot.units if is_fighter(u))
        tags = pick_squad(candidates, army_supply)
        if not tags:
            self._set_wait(
                f"no squad: {len(candidates)} Adepts/Charge Zealots/Stalkers at home, cap "
                f"{COUNTER_SQUAD_MAX_FRACTION:g} x {army_supply:g} supply, minimum {COUNTER_SQUAD_MIN_SUPPLY:g}"
            )
            return
        get = bot.unit_tag_dict.get
        squad = [u for tag in tags if (u := get(tag)) is not None]
        home = self._home_level(set(tags))
        if home is not None and home < DEFEND_ENGAGE:
            self._set_wait(f"home threat at {army.threat.rounded}: level {home} < {DEFEND_ENGAGE} without the squad")
            return
        engagement = army.engagement
        defenders = engagement.enemies_near([target.position], COUNTER_DEFENCE_RADIUS) + engagement.static_defense_near(target.position)
        level = engagement.level(squad, defenders, ENEMY_DEFENDS)
        self.last_level = level
        if level < COUNTER_START:
            self._set_wait(f"level {level} < {COUNTER_START} at {target.position.rounded} ({target_why})")
            return
        self._launch(reading, target, target_why, squad, level)

    def _launch(self, reading: ArmyReading, target: BaseOption, target_why: str, squad: list[Unit], level: int) -> None:
        bot = self.bot
        army = self.army
        tags = [u.tag for u in squad]
        army.squads.assign(tags, Role.HARASS)
        for tag in tags:
            army.intents.pop(tag, None)
        self.state = OUT
        self.target = target.position
        self.launched_at = bot.time
        self.start_value = army.engagement.value(squad)
        self.watched = set(reading.fresh_tags)
        self._wait = ""
        kinds: dict[str, int] = {}
        for u in squad:
            kinds[u.type_id.name] = kinds.get(u.type_id.name, 0) + 1
        supply = self._supply(squad)
        self.current = {
            "launched": round(bot.time, 1),
            "target": [round(target.position.x, 1), round(target.position.y, 1)],
            "target_why": target_why,
            "units": kinds,
            "supply": supply,
            "level": level,
            "start_value": round(self.start_value),
            "enemy_army": reading.why,
            "ended": None,
            "reason": "",
            "end_value": None,
            "workers_killed": 0,
            "structures_killed": 0,
            "units_killed": 0,
            "value_killed": 0.0,
            "first_kill": None,
        }
        logger.info(
            f"COUNTER launch at {bot.time_formatted} level={level}: {len(squad)} units ({supply:g} supply: "
            + ", ".join(f"{n} {k}" for k, n in kinds.items())
            + f") -> {target.position.rounded} ({target_why}); enemy {reading.why}"
        )

    def _set_wait(self, why: str) -> None:
        if why and why != self._wait:
            logger.info(f"COUNTER wait at {self.bot.time_formatted}: {why}")
        self._wait = why

    # -- while out -------------------------------------------------------------------------------

    def _target_cleared(self) -> bool:
        """No known enemy structure and no visible enemy worker left at the target base."""
        bot = self.bot
        if any(s.distance_to(self.target) <= COUNTER_BASE_RADIUS for s in bot.enemy_structures):
            return False
        return not any(
            e.type_id in WORKERS and not e.is_memory and e.distance_to(self.target) <= COUNTER_BASE_RADIUS
            for e in bot.enemy_units
        )

    def _check_recall(self) -> None:
        bot = self.bot
        army = self.army
        squad = army.fighters(Role.HARASS)
        if not squad:
            self._end("squad lost")
            return
        engagement = army.engagement
        center = Point2.center([u.position for u in squad])
        enemy = engagement.attack_inputs(center, self.target)
        level = engagement.level(squad, enemy, ENEMY_DEFENDS)
        self.last_level = level
        value = engagement.value(squad)
        home = self._home_level(set())
        home_unheld = (
            f"home threat at {army.threat.rounded}, home level {home} < {DEFEND_ENGAGE}"
            if home is not None and home < DEFEND_ENGAGE else ""
        )
        reason = recall_reason(
            bot.time, self.launched_at, level, value, self.start_value,
            self.position.center_of(self.watched), self.target, center, home_unheld,
        )
        if reason is None and self._target_cleared():
            reason = "target base cleared"
        if reason is not None:
            self.recall(reason, level, value)

    def recall(self, reason: str, level: Optional[int] = None, value: Optional[float] = None) -> None:
        army = self.army
        tags = army.squads.tags(Role.HARASS)
        army.send_home(tags)
        logger.info(
            f"COUNTER recall at {self.bot.time_formatted}: {reason}; {len(tags)} units home after "
            f"{self.bot.time - self.launched_at:.0f} s"
        )
        if self.current is not None and value is not None:
            self.current["end_value"] = round(value)
        self._end(reason)

    def _end(self, reason: str) -> None:
        now = self.bot.time
        if self.current is not None:
            self.current["ended"] = round(now, 1)
            self.current["reason"] = reason
            self.current["value_killed"] = round(self.current["value_killed"])
            self.outcomes.append(self.current)
            logger.info(
                f"COUNTER outcome: out {_mmss(self.current['launched'])}-{_mmss(now)}, {reason}; killed "
                f"{self.current['workers_killed']} workers, {self.current['structures_killed']} structures, "
                f"{self.current['units_killed']} units ({self.current['value_killed']} value)"
            )
        self.current = None
        self.state = IDLE
        self.target = None
        self.watched = set()
        self.goals = [[], [], []]
        self.ended_at = now
