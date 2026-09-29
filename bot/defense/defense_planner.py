"""Active threat flags -> one DefensePlan (DESIGN.md §3 `defense/defense_planner.py`, §4.2, §5).

Runs every intel tick after the detectors and flag expiry. Each active threat contributes its
§4.2 plan and the parts are merged: counts take the maximum, `allow_*` must be allowed by every
active threat, unit priorities are concatenated in the order of `PLAN_ORDER`. The plan holds as
long as its flags do; §5's 20 s minimum is applied to the flags.

When a newly raised flag has `override_opener`, the planner ends the ares opener
(`build_order_runner.set_build_completed()`, §3 step 3); `BuildExecutor`'s opener essentials
then build what the opener would have.

Plans (§4.2):
- WORKER_RUSH: pull probes (worker_defense.py), Zealot first, no expansion while it lasts.
- CANNON_RUSH: probes on unfinished Pylons/Cannons (worker_defense.py); once a Cannon is done,
  Stalkers/Immortal, no expansion (and cancel ours) if a finished Cannon covers our natural.
- POOL_12: no expansion until POOL_12_UNITS_BEFORE_EXPAND units and no Zerglings near our bases;
  a Zealot/Adept holds the wall gap; a Battery in the main.
- PROXY: no expansion until PROXY_UNITS_BEFORE_EXPAND units; a 2nd Gateway and a Battery in the
  main; hold the ramp top; Adepts/Zealots (Stalkers vs Reapers); chrono Gateways.
- ONE_BASE_ALLIN: Batteries at the natural (main if none); all Gateways producing; no 3rd Nexus,
  no Forge; hold the natural; Immortals first vs Roaches.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from loguru import logger
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.constants import (
    CANNON_COVER_EXTRA,
    NATURAL_HOLD_OFFSET,
    ONE_BASE_BATTERIES,
    POOL_12_LING_CLEAR_RADIUS,
    POOL_12_MAIN_BATTERIES,
    POOL_12_UNITS_BEFORE_EXPAND,
    PROXY_GATEWAYS,
    PROXY_MAIN_BATTERIES,
    PROXY_UNITS_BEFORE_EXPAND,
    RAMP_HOLD_OFFSET,
    WORKER_RUSH_KEEP_MINING,
)
from bot.intel.threat_flags import Evidence, FlagStore, Threat

if TYPE_CHECKING:
    from ares import AresBot
    from sc2.unit import Unit

PLAN_ORDER: tuple[Threat, ...] = (
    Threat.WORKER_RUSH,
    Threat.CANNON_RUSH,
    Threat.POOL_12,
    Threat.PROXY,
    Threat.ONE_BASE_ALLIN,
)
# units that count toward "N units out" (§4.2); Observers and Oracles don't hold a ramp
GROUND_ARMY: frozenset[UnitTypeId] = frozenset(
    {
        UnitTypeId.ZEALOT, UnitTypeId.ADEPT, UnitTypeId.STALKER, UnitTypeId.SENTRY,
        UnitTypeId.IMMORTAL, UnitTypeId.COLOSSUS, UnitTypeId.ARCHON,
    }
)
ROACHES: frozenset[UnitTypeId] = frozenset({UnitTypeId.ROACH, UnitTypeId.RAVAGER})


@dataclass
class DefensePlan:
    active: set[Threat] = field(default_factory=set)
    allow_expand: bool = True
    batteries_needed: dict[str, int] = field(default_factory=lambda: {"main": 0, "natural": 0})
    cannons_needed: dict[str, int] = field(default_factory=lambda: {"main": 0, "natural": 0})
    probe_pull: int = 0  # probes assigned to DEFENDING (worker_defense.py fills in the targets)
    army_hold_point: Optional[Point2] = None
    pinned_unit_tags: set[int] = field(default_factory=set)
    # Citadel additions
    allow_third: bool = True
    allow_forge: bool = True
    gateways_needed: int = 0
    unit_priority: list[UnitTypeId] = field(default_factory=list)  # made before the normal mix
    all_gateways_producing: bool = False
    chrono_gateways: bool = False
    hold_wall_gap: bool = False  # the first Zealot/Adept holds the ramp wall gap
    cancel_natural: bool = False  # a finished enemy Cannon covers our natural

    def summary(self) -> str:
        if not self.active:
            return "none"
        parts = [
            "+".join(t.name for t in PLAN_ORDER if t in self.active),
            f"expand={'yes' if self.allow_expand else 'no'}",
        ]
        if not self.allow_third:
            parts.append("third=no")
        if not self.allow_forge:
            parts.append("forge=no")
        if any(self.batteries_needed.values()):
            parts.append(f"batteries={self.batteries_needed}")
        if self.gateways_needed:
            parts.append(f"gateways={self.gateways_needed}")
        if self.unit_priority:
            parts.append(f"units={[u.name for u in self.unit_priority]}")
        if self.probe_pull:
            parts.append(f"pull={self.probe_pull}")
        if self.army_hold_point is not None:
            parts.append(f"hold={self.army_hold_point.rounded}")
        if self.hold_wall_gap:
            parts.append("wall gap held")
        if self.cancel_natural:
            parts.append("cancel natural")
        return " ".join(parts)


class DefensePlanner:
    def __init__(self, bot: "AresBot", flags: FlagStore):
        self.bot = bot
        self.flags = flags
        self.plan = DefensePlan()
        self._summary: str = "none"
        self.opener_ended_by: Optional[str] = None
        self.reapers_seen: bool = False
        self.roaches_seen: bool = False

    # -- policy for new flags ------------------------------------------------------------------

    def override_for(self, threat: Threat, evidence: Evidence) -> bool:
        """Does a new flag end the ares opener? (§3 step 3; which threats do is Citadel's
        choice, see docs/VERIFY_NOTES.md M2 findings)."""
        if self.bot.build_order_runner.build_completed:
            return False
        if threat in (Threat.WORKER_RUSH, Threat.PROXY):
            return True
        if threat == Threat.CANNON_RUSH:
            return evidence == Evidence.STRUCTURE  # an enemy probe alone is often just a scout
        if threat == Threat.POOL_12:
            return not self._natural_started()  # §4.2: delay the natural if it isn't started
        return False

    def _natural_started(self) -> bool:
        bot = self.bot
        nat = bot.mediator.get_own_nat
        return any(th.distance_to(nat) < 3 for th in bot.townhalls) or bool(
            bot.mediator.get_building_counter[UnitTypeId.NEXUS]
        )

    # -- per intel tick ------------------------------------------------------------------------

    def update(self) -> DefensePlan:
        bot = self.bot
        for enemy in bot.enemy_units:
            if enemy.type_id == UnitTypeId.REAPER:
                self.reapers_seen = True
            elif enemy.type_id in ROACHES:
                self.roaches_seen = True
        self._maybe_end_opener()
        active = self.flags.active_threats()
        plan = DefensePlan(active=set(active))
        army = [u for u in bot.units if u.type_id in GROUND_ARMY]
        for threat in PLAN_ORDER:
            if threat in active:
                getattr(self, f"_plan_{threat.name.lower()}")(plan, army)
        # the unit priority list without repeats, in order
        seen: set[UnitTypeId] = set()
        plan.unit_priority = [u for u in plan.unit_priority if not (u in seen or seen.add(u))]
        self.plan = plan
        summary = plan.summary()
        if summary != self._summary:
            self._summary = summary
            logger.info(f"PLAN at {bot.time_formatted}: {summary}")
        return plan

    def _maybe_end_opener(self) -> None:
        runner = self.bot.build_order_runner
        if runner.build_completed:
            return
        overriding = [f for f in self.flags.active() if f.override_opener]
        if overriding:
            self.opener_ended_by = ", ".join(sorted({f.threat.name for f in overriding}))
            logger.info(
                f"OPENER ended at {self.bot.time_formatted} (step {runner.build_step}) by {self.opener_ended_by}"
            )
            runner.set_build_completed()

    # -- helpers ---------------------------------------------------------------------------------

    def _ramp_hold(self) -> Point2:
        bot = self.bot
        return bot.main_base_ramp.top_center.towards(bot.start_location, RAMP_HOLD_OFFSET)

    def _natural_hold(self) -> Point2:
        bot = self.bot
        return bot.mediator.get_own_nat.towards(bot.enemy_start_locations[0], NATURAL_HOLD_OFFSET)

    def _our_natural(self) -> Optional["Unit"]:
        nat = self.bot.mediator.get_own_nat
        return next((th for th in self.bot.townhalls if th.distance_to(nat) < 3), None)

    def completed_enemy_cannons(self) -> list["Unit"]:
        return [
            s for s in self.bot.enemy_structures
            if s.type_id == UnitTypeId.PHOTONCANNON and s.is_ready and s.is_powered
        ]

    def cannon_covers(self, point: Point2, radius: float) -> bool:
        """A finished, powered enemy Cannon can hit a structure of `radius` at `point`."""
        return any(
            c.distance_to(point) <= c.ground_range + c.radius + radius + CANNON_COVER_EXTRA
            for c in self.completed_enemy_cannons()
        )

    # -- per-threat plans (§4.2) -------------------------------------------------------------------

    def _plan_worker_rush(self, plan: DefensePlan, army: list) -> None:
        plan.allow_expand = False
        plan.unit_priority.append(UnitTypeId.ZEALOT)
        plan.gateways_needed = max(plan.gateways_needed, 1)
        plan.probe_pull = max(plan.probe_pull, len(self.bot.workers) - WORKER_RUSH_KEEP_MINING)

    def _plan_cannon_rush(self, plan: DefensePlan, army: list) -> None:
        if self.completed_enemy_cannons():
            plan.unit_priority += [UnitTypeId.IMMORTAL, UnitTypeId.STALKER]
            nat = self.bot.mediator.get_own_nat
            if self.cannon_covers(nat, 2.75):  # Nexus footprint radius
                plan.allow_expand = False
                plan.cancel_natural = True

    def _plan_pool_12(self, plan: DefensePlan, army: list) -> None:
        bot = self.bot
        lings_near = [
            e for e in bot.enemy_units
            if e.type_id == UnitTypeId.ZERGLING
            and any(e.distance_to(th) < POOL_12_LING_CLEAR_RADIUS for th in bot.townhalls)
        ]
        if len(army) < POOL_12_UNITS_BEFORE_EXPAND or lings_near:
            plan.allow_expand = False
        plan.unit_priority += [UnitTypeId.ZEALOT, UnitTypeId.ADEPT]
        plan.hold_wall_gap = True
        plan.batteries_needed["main"] = max(plan.batteries_needed["main"], POOL_12_MAIN_BATTERIES)

    def _plan_proxy(self, plan: DefensePlan, army: list) -> None:
        if len(army) < PROXY_UNITS_BEFORE_EXPAND:
            plan.allow_expand = False
        plan.gateways_needed = max(plan.gateways_needed, PROXY_GATEWAYS)
        plan.batteries_needed["main"] = max(plan.batteries_needed["main"], PROXY_MAIN_BATTERIES)
        plan.unit_priority += (
            [UnitTypeId.STALKER, UnitTypeId.ADEPT] if self.reapers_seen else [UnitTypeId.ADEPT, UnitTypeId.ZEALOT]
        )
        plan.chrono_gateways = True
        # §4.2 "hold at the top of the ramp"; once the units are out and our natural stands,
        # the natural is held instead so it isn't left alone (Citadel)
        if len(army) < PROXY_UNITS_BEFORE_EXPAND or self._our_natural() is None:
            plan.army_hold_point = self._ramp_hold()
        elif plan.army_hold_point is None:
            plan.army_hold_point = self._natural_hold()

    def _plan_one_base_allin(self, plan: DefensePlan, army: list) -> None:
        where = "natural" if self._our_natural() is not None else "main"
        plan.batteries_needed[where] = max(plan.batteries_needed[where], ONE_BASE_BATTERIES)
        plan.allow_third = False
        plan.allow_forge = False
        plan.all_gateways_producing = True
        if self.roaches_seen:
            plan.unit_priority.insert(0, UnitTypeId.IMMORTAL)
        plan.unit_priority += [UnitTypeId.STALKER, UnitTypeId.ZEALOT]
        if plan.army_hold_point is None or where == "natural":
            plan.army_hold_point = self._natural_hold() if where == "natural" else self._ramp_hold()
