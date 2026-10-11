"""Timed opener steps after the ares build runner (DESIGN.md §3 `macro/build_executor.py`, §4.1).

The build runner only has supply triggers (docs/VERIFY_NOTES.md §11.4), so the time-based part
of each opener lives in `constants.OPENER_SCHEDULES` and runs here once the YAML opener is
complete. Each item becomes active at its time and stays active until its count is reached;
the first time it is reached is logged as a `SCHEDULE` line.

`constants.OPENER_ESSENTIALS` come first in every schedule: they rebuild what the opener would
have if a threat flag ended it early, and are already met otherwise. The active DefensePlan
(§4.2) gates expansions (`allow_expand`, `allow_third`) and the Forge (`allow_forge`).
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Optional

from ares.behaviors.macro import BuildStructure, SpawnController
from ares.behaviors.behavior import Behavior
from ares.consts import ID, TARGET
from loguru import logger
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.data import Race
from sc2.dicts.upgrade_researched_from import UPGRADE_RESEARCHED_FROM
from sc2.position import Point2

from bot.constants import (
    GAS_PER_BASE_AFTER_SCHEDULE,
    MAX_BASES,
    NATURAL_RADIUS,
    OPENER_ESSENTIALS,
    OPENER_SCHEDULES,
    TECH_MIN_BASES,
    TECH_STEPS,
    ScheduleItem,
)

if TYPE_CHECKING:
    from ares import AresBot

    from bot.defense.defense_planner import DefensePlanner

# other structure types that count toward an item's count
COUNTS_AS: dict[UnitTypeId, tuple[UnitTypeId, ...]] = {
    UnitTypeId.GATEWAY: (UnitTypeId.GATEWAY, UnitTypeId.WARPGATE),
}
# unit -> structure it is trained from
TRAINED_FROM: dict[UnitTypeId, UnitTypeId] = {
    UnitTypeId.OBSERVER: UnitTypeId.ROBOTICSFACILITY,
    UnitTypeId.IMMORTAL: UnitTypeId.ROBOTICSFACILITY,
    UnitTypeId.ORACLE: UnitTypeId.STARGATE,
}


def _nat_ready(bot: "AresBot") -> bool:
    nat: Point2 = bot.mediator.get_own_nat
    return any(th.is_ready and th.distance_to(nat) < 3 for th in bot.townhalls)


def race_key(bot: "AresBot") -> str:
    """The enemy race's name for per-race tables; Random counts as Terran until its race is seen
    (§4.1)."""
    race = bot.enemy_race
    return race.name if race in (Race.Terran, Race.Zerg, Race.Protoss) else Race.Terran.name


def _no_zerg_rush_flag(bot: "AresBot") -> bool:
    m = bot.mediator
    return not (m.get_enemy_ling_rushed or m.get_enemy_roach_rushed or m.get_enemy_ravager_rush)


# Named conditions for ScheduleItem.only_if / early_if. ares intel flags are mediator
# properties (docs/VERIFY_NOTES.md §11.1).
CONDITIONS: dict[str, Callable[["AresBot"], bool]] = {
    "robo_started": lambda bot: len(bot.mediator.get_own_structures_dict[UnitTypeId.ROBOTICSFACILITY]) > 0,
    # a Gateway placed, building or done (M5: the essentials' gas waits for it, as in every opener)
    "gateway_started": lambda bot: (
        len(bot.mediator.get_own_structures_dict[UnitTypeId.GATEWAY])
        + len(bot.mediator.get_own_structures_dict[UnitTypeId.WARPGATE])
        + bot.mediator.get_building_counter[UnitTypeId.GATEWAY]
    ) > 0,
    "nat_ready": _nat_ready,
    "no_zerg_rush_flag": _no_zerg_rush_flag,
    "enemy_third": lambda bot: bool(bot.mediator.get_enemy_has_base_outside_natural),
    "enemy_expanded": lambda bot: bool(bot.mediator.get_enemy_expanded),
    # M7 K1: the research buildings' per-race timed steps (constants.TECH_STEPS)
    "vs_terran": lambda bot: race_key(bot) == "Terran",
    "vs_protoss": lambda bot: race_key(bot) == "Protoss",
    "vs_zerg": lambda bot: race_key(bot) == "Zerg",
}


# what DefensePlan.hold_tech keeps waiting (everything but Pylons, Gateways, Batteries and gas)
TECH_ITEMS: frozenset = frozenset(
    {
        UnitTypeId.ROBOTICSFACILITY, UnitTypeId.STARGATE, UnitTypeId.FORGE, UnitTypeId.TWILIGHTCOUNCIL,
        UnitTypeId.OBSERVER, UnitTypeId.ORACLE, UpgradeId.PROTOSSGROUNDWEAPONSLEVEL1,
        UnitTypeId.TEMPLARARCHIVE,
    }
)
# M7 D29: research buildings that wait for TECH_MIN_BASES finished Nexuses (outside an opener)
TECH_WAIT_BUILDINGS: frozenset = frozenset({UnitTypeId.TWILIGHTCOUNCIL, UnitTypeId.TEMPLARARCHIVE})


def tech_waits(building: UnitTypeId, bases: int, part_of_opener: bool = False, min_bases: int = TECH_MIN_BASES) -> bool:
    """M7 D29: a Twilight Council or Templar Archives (its timed step, the tech-up toward Templar,
    or research there) waits while fewer than `min_bases` of our Nexuses are finished; an opener's
    own items don't (pure)."""
    return building in TECH_WAIT_BUILDINGS and not part_of_opener and bases < min_bases


def bases_ready(bot: "AresBot") -> int:
    return len(bot.townhalls.ready)


# structures and upgrades that need a Forge; §4.2 one-base delays the Forge
NEEDS_FORGE: frozenset = frozenset(
    {
        UnitTypeId.FORGE, UnitTypeId.PHOTONCANNON,
        UpgradeId.PROTOSSGROUNDWEAPONSLEVEL1, UpgradeId.PROTOSSGROUNDARMORSLEVEL1,
        UpgradeId.PROTOSSSHIELDSLEVEL1,
    }
)


class BuildExecutor:
    def __init__(self, bot: "AresBot", opener: str, planner: "DefensePlanner"):
        self.bot = bot
        self.opener = opener
        self.planner = planner
        schedule = OPENER_SCHEDULES.get(opener, ())
        if not schedule:
            logger.warning(f"SCHEDULE: no timed steps for opener {opener}")
        self.schedule: tuple[ScheduleItem, ...] = schedule
        self._reached: set[ScheduleItem] = set()  # items whose count was reached once
        self.waiting_for_money: bool = False

    @property
    def items(self) -> tuple[ScheduleItem, ...]:
        """The opener essentials (only once a threat flag or the timeout ended the opener
        early), then the opener's timed schedule, then the research buildings' timed steps (M7 K1)."""
        if self.planner.opener_ended_by is not None:
            return OPENER_ESSENTIALS + self.schedule + TECH_STEPS
        return self.schedule + TECH_STEPS

    @property
    def finished(self) -> bool:
        """Every opener item reached once (the research buildings' timed steps don't count)."""
        return all(item in self._reached for item in self.items if item.part_of_opener)

    # -- targets used by the economy -------------------------------------------------------

    def gas_target(self) -> int:
        bot = self.bot
        if self.finished:
            return GAS_PER_BASE_AFTER_SCHEDULE * len(bot.ready_townhalls)
        counts = [item.count for item in self.items if item.kind == "gas" and self._active(item)]
        return max(counts, default=len(bot.gas_buildings))

    def bases_target(self) -> int:
        """Bases wanted now, after the DefensePlan: no new base while `allow_expand` is off
        (a Nexus already started stays), at most 2 while `allow_third` is off."""
        townhalls = len(self.bot.townhalls)
        if self.finished:
            target = MAX_BASES
        else:
            counts = [item.count for item in self.items if item.kind == "bases" and self._active(item)]
            target = max(counts, default=townhalls)
        plan = self.planner.plan
        if not plan.allow_expand:
            target = min(target, townhalls)
        if not plan.allow_third:
            target = min(target, max(2, townhalls))
        return target

    # -- per macro tick -----------------------------------------------------------------------

    def behaviors(self) -> list[Behavior]:
        """Behaviors for this tick's MacroPlan, in schedule order. Also sets
        `waiting_for_money` when an active item could act but can't be afforded yet."""
        bot = self.bot
        self.waiting_for_money = False
        out: list[Behavior] = []
        for item in self.items:
            if not self._active(item):
                continue
            have = self._count(item)
            if have >= item.count:
                if item not in self._reached:
                    self._reached.add(item)
                    name = item.type_id.name if item.type_id is not None else item.kind
                    logger.info(
                        f"SCHEDULE {self.opener}: {name} x{item.count} ({item.where}) "
                        f"reached at {bot.time_formatted} (planned "
                        f"{int(item.at_s) // 60}:{int(item.at_s) % 60:02d})"
                    )
                continue
            behavior = self._behavior(item)
            if behavior is not None:
                out.append(behavior)
        return out

    def _active(self, item: ScheduleItem) -> bool:
        bot = self.bot
        plan = self.planner.plan
        if item.type_id in NEEDS_FORGE and not plan.allow_forge:
            return False
        if item.type_id in TECH_ITEMS and plan.hold_tech:
            return False
        if tech_waits(item.type_id, bases_ready(bot), item.part_of_opener):
            return False
        if item.where == "nat" and plan.hold_wall_gap:
            return False  # the probe couldn't get past our own gap holder
        if item.where == "nat" and not self._have_natural():
            # a Pylon/Battery for a natural we don't have: with rush Cannons there, every
            # probe sent died on the way in test games
            return False
        early = item.early_if is not None and CONDITIONS[item.early_if](bot)
        if bot.time < item.at_s and not early:
            return False
        if item.only_if is not None and not CONDITIONS[item.only_if](bot):
            if item.only_if_until_s is None or bot.time < item.only_if_until_s:
                return False
        return True

    def _have_natural(self) -> bool:
        nat: Point2 = self.bot.mediator.get_own_nat
        return any(th.distance_to(nat) < 3 for th in self.bot.townhalls)

    def _count(self, item: ScheduleItem) -> int:
        bot = self.bot
        if item.kind == "gas":
            return len(bot.gas_buildings) + bot.mediator.get_building_counter[bot.gas_type]
        if item.kind == "bases":
            return len(bot.townhalls) + bot.mediator.get_building_counter[UnitTypeId.NEXUS]
        if item.kind == "upgrade":
            return 1 if bot.already_pending_upgrade(item.type_id) > 0 else 0
        if item.kind == "unit":
            return len(bot.mediator.get_own_army_dict[item.type_id]) + bot.unit_pending(item.type_id)
        # structures: finished or under construction, plus workers on their way to build one
        types = COUNTS_AS.get(item.type_id, (item.type_id,))
        structures = [s for t in types for s in bot.mediator.get_own_structures_dict[t]]
        if item.where != "nat":
            return len(structures) + bot.not_started_but_in_building_tracker(item.type_id)
        # at the natural: only structures and build orders there (a main Battery order must not
        # count toward the natural's)
        nat: Point2 = bot.mediator.get_own_nat
        structures = [s for s in structures if s.distance_to(nat) < NATURAL_RADIUS]
        started = {s.position.rounded for s in bot.structures}
        on_route = sum(
            1
            for info in bot.mediator.get_building_tracker_dict.values()
            if info[ID] == item.type_id
            and isinstance(target := info[TARGET], Point2)
            and target.distance_to(nat) < NATURAL_RADIUS
            and target.rounded not in started
        )
        return len(structures) + on_route

    def _behavior(self, item: ScheduleItem) -> Optional[Behavior]:
        bot = self.bot
        if item.kind in ("gas", "bases"):
            if item.kind == "bases" and self.bases_target() > len(bot.townhalls) and not bot.can_afford(UnitTypeId.NEXUS):
                self.waiting_for_money = True
            return None  # handled by the economy through gas_target() / bases_target()

        if item.kind == "upgrade":
            upgrade: UpgradeId = item.type_id
            source = UPGRADE_RESEARCHED_FROM[upgrade]
            if not [s for s in bot.mediator.get_own_structures_dict[source] if s.is_ready and s.is_idle]:
                return None
            if not bot.can_afford(upgrade):
                self.waiting_for_money = True
                return None
            return ResearchUpgrade(upgrade)

        if item.kind == "unit":
            source = TRAINED_FROM[item.type_id]
            if not [s for s in bot.mediator.get_own_structures_dict[source] if s.is_ready and s.is_idle]:
                return None
            if not bot.can_afford(item.type_id):
                self.waiting_for_money = True
                return None
            return SpawnController(
                {item.type_id: {"proportion": 1.0, "priority": 0}},
                freeflow_mode=True,
                maximum=item.count - self._count(item),
            )

        # structure
        if bot.tech_requirement_progress(item.type_id) < 1.0:
            return None
        if not bot.can_afford(item.type_id):
            self.waiting_for_money = True
            return None
        at_nat = item.where == "nat"
        return BuildStructure(
            base_location=bot.mediator.get_own_nat if at_nat else bot.start_location,
            structure_id=item.type_id,
            static_defence=item.type_id == UnitTypeId.SHIELDBATTERY,
            wall=item.where == "ramp",  # ares's ramp-wall spots, as `@ ramp` in the opener
            # a natural item must not wander to another base when the natural has no spot yet
            find_alternative=not at_nat,
        )


@dataclass
class ResearchUpgrade:
    """Start one upgrade (the caller checked the research structure and the money)."""

    upgrade: UpgradeId

    def execute(self, ai: "AresBot", config: dict, mediator) -> bool:
        return bool(ai.research(self.upgrade))
