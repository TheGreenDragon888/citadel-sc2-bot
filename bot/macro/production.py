"""Army production and upgrades (DESIGN.md §3 `macro/production.py`, §4.5.1).

M1 scaffolding so the bot can win games: the §4.5.1 unit mix through ares's SpawnController
(units) and ProductionController (adds Gateways/Robotics Facilities and the tech buildings the
mix needs), plus the §4.5.1 upgrade order through ares's UpgradeController. The air switch and
the combat-sim checks of the mix come later.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from ares.behaviors.macro import (
    ProductionController,
    SpawnController,
    UpgradeController,
)
from ares.consts import GATEWAY_UNITS
from loguru import logger
from sc2.data import Race
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2

from bot.constants import (
    ARMY_COMPOSITION_PCT,
    ARMY_PRIORITY,
    GATEWAY_POWER_RETRY_S,
    GATEWAY_POWER_SEARCH,
    MAX_PRODUCTION_STRUCTURES,
    MINERAL_FLOAT_BANK,
    OBSERVER_COUNT,
    PRODUCTION_CONTROLLER_START_S,
    UPGRADES_START_S,
    UPGRADES_VS_P,
    UPGRADES_VS_ZT,
)
from bot.geometry import in_map

if TYPE_CHECKING:
    from ares import AresBot
    from ares.behaviors.behavior import Behavior

    from bot.defense.defense_planner import DefensePlan


@dataclass
class ReserveForUnit:
    """Holds the rest of a MacroPlan (structures, probes) while fewer than `wanted` Gateway units
    exist, a Gateway could make `unit` now, and it can't be afforded yet (§4.2 "the first
    Zealot is top priority"; in 12-pool test games probes and buildings kept taking the minerals
    and the wall Zealot came after the first Zerglings)."""

    unit: UnitTypeId
    wanted: int

    def unmet(self, ai: "AresBot", mediator) -> bool:
        """Fewer than `wanted` Gateway units (made or in production) while a Gateway could make
        one now."""
        have = sum(len(mediator.get_own_army_dict[t]) for t in GATEWAY_UNITS) + ai.unit_pending(self.unit)
        if have >= self.wanted:
            return False
        return any(
            g.is_ready and g.is_idle for g in mediator.get_own_structures_dict[UnitTypeId.GATEWAY]
        ) or bool(mediator.get_own_structures_dict[UnitTypeId.WARPGATE])

    def holds(self, ai: "AresBot", mediator) -> bool:
        return not ai.can_afford(self.unit) and self.unmet(ai, mediator)

    def execute(self, ai: "AresBot", config: dict, mediator) -> bool:
        return self.holds(ai, mediator)


def reserve_for(bot: "AresBot", plan: "DefensePlan") -> Optional[ReserveForUnit]:
    """The plan's reserve: its first tech-ready Gateway unit, if it reserves any."""
    if not plan.reserve_units:
        return None
    unit = next((u for u in plan.unit_priority if u in GATEWAY_UNITS and bot.tech_ready_for_unit(u)), None)
    return ReserveForUnit(unit, plan.reserve_units) if unit is not None else None


class Production:
    def __init__(self, bot: "AresBot"):
        self.bot = bot
        self._power_ordered: dict[int, float] = {}  # Gateway tag -> time a Pylon was ordered for it

    def gateway_upkeep(self) -> None:
        """Once Warp Gate is researched, ares's SpawnController makes nothing while any ready,
        idle Gateway exists, waiting for it to morph (`spawn_controller.py`, start of
        `execute`). An unpowered Gateway (its Pylon killed) never morphs, which froze all
        production in test games. Morph powered idle Gateways, and put a Pylon next to
        unpowered ones."""
        bot = self.bot
        if UpgradeId.WARPGATERESEARCH not in bot.state.upgrades:
            return
        for gate in bot.mediator.get_own_structures_dict[UnitTypeId.GATEWAY]:
            if not gate.is_ready or not gate.is_idle:
                continue
            if gate.is_powered:
                gate(AbilityId.MORPH_WARPGATE)
                continue
            if bot.time - self._power_ordered.get(gate.tag, -GATEWAY_POWER_RETRY_S) < GATEWAY_POWER_RETRY_S:
                continue
            spot = self._pylon_spot_near(gate.position)
            if spot is None or not bot.can_afford(UnitTypeId.PYLON):
                continue
            worker = bot.mediator.select_worker(target_position=spot, force_close=True)
            if worker is not None and bot.mediator.build_with_specific_worker(
                worker=worker, structure_type=UnitTypeId.PYLON, pos=spot
            ):
                self._power_ordered[gate.tag] = bot.time
                logger.info(f"PRODUCTION Gateway at {gate.position.rounded} unpowered: Pylon at {spot.rounded} ({bot.time_formatted})")

    def _pylon_spot_near(self, point: Point2) -> Optional[Point2]:
        bot = self.bot
        cx, cy = round(point.x), round(point.y)
        spots = [
            Point2((cx + dx, cy + dy))
            for dx in range(-GATEWAY_POWER_SEARCH, GATEWAY_POWER_SEARCH + 1)
            for dy in range(-GATEWAY_POWER_SEARCH, GATEWAY_POWER_SEARCH + 1)
        ]
        spots = [
            p for p in spots
            if in_map(bot, p) and p.distance_to(point) <= GATEWAY_POWER_SEARCH
            and bot.mediator.can_place_structure(position=p, structure_type=UnitTypeId.PYLON)
        ]
        return min(spots, key=lambda p: p.distance_to(point), default=None)

    def composition(self, tech_ready_only: bool = False) -> dict[UnitTypeId, dict[str, float]]:
        """ares composition dict for the enemy race; vs Random, the vs-T mix until the race is
        seen (§4.1 treats Random like Terran until then).

        `tech_ready_only` keeps only units whose tech is ready and rescales their shares. ares's
        SpawnController fills each unit up to its share of the current army, so a unit that
        can't be built yet (a Colossus before the Robotics Bay) otherwise leaves the rest of the
        production idle once the buildable units reach their shares.
        """
        race = self.bot.enemy_race
        key = race.name if race in (Race.Terran, Race.Zerg, Race.Protoss) else Race.Terran.name
        shares = ARMY_COMPOSITION_PCT[key]
        if tech_ready_only:
            ready = {u: pct for u, pct in shares.items() if self.bot.tech_ready_for_unit(u)}
            if ready:
                shares = ready
        total = sum(shares.values())
        return {
            unit: {"proportion": pct / total, "priority": ARMY_PRIORITY[unit]}
            for unit, pct in shares.items()
        }

    def _next_upgrade(self) -> Optional[UpgradeId]:
        bot = self.bot
        order = UPGRADES_VS_P if bot.enemy_race == Race.Protoss else UPGRADES_VS_ZT
        for upgrade in order:
            progress = bot.already_pending_upgrade(upgrade)
            if progress == 0:
                return upgrade
            if progress < 1:
                return None  # wait for the one in progress
        return None

    def defense_behaviors(self, plan: "DefensePlan") -> list["Behavior"]:
        """§4.2 plan units, ahead of everything else (Defense > Economy, §3): the first
        tech-ready unit of `plan.unit_priority` from every idle producer, and with
        `all_gateways_producing` the Gateway share of the mix without waiting for a bank."""
        bot = self.bot
        out: list["Behavior"] = []
        unit = next((u for u in plan.unit_priority if bot.tech_ready_for_unit(u)), None)
        if unit is not None:
            out.append(SpawnController({unit: {"proportion": 1.0, "priority": 0}}, freeflow_mode=True))
        if (reserve := reserve_for(bot, plan)) is not None:
            if reserve.unit != unit:
                out.append(SpawnController({reserve.unit: {"proportion": 1.0, "priority": 0}}, freeflow_mode=True))
            out.append(reserve)
        if plan.all_gateways_producing:
            gateway_mix = {u: info for u, info in self.composition(tech_ready_only=True).items() if u in GATEWAY_UNITS}
            if gateway_mix:
                out.append(SpawnController(gateway_mix, freeflow_mode=True))
        return out

    def behaviors(self, schedule_finished: bool, plan: "DefensePlan") -> list["Behavior"]:
        """Behaviors for this tick's MacroPlan, after the economy and the opener schedule.
        ProductionController (more Gateways/Robos and their tech) starts once the opener's timed
        schedule is finished, or at `PRODUCTION_CONTROLLER_START_S` at the latest. Upgrades wait
        while the DefensePlan delays the Forge (§4.2 one-base)."""
        bot = self.bot
        comp = self.composition()  # full mix: ProductionController techs toward all of it
        buildable = self.composition(tech_ready_only=True)
        out: list["Behavior"] = []
        if plan.allow_forge and not plan.hold_tech and bot.time >= UPGRADES_START_S and (upgrade := self._next_upgrade()) is not None:
            # one at a time, in §4.5.1 order: given the whole list, UpgradeController starts every
            # tech building at once (a Hard-Zerg loss had Forge, Twilight and Robo Bay at 5:00)
            out.append(UpgradeController([upgrade], base_location=bot.start_location))
        observers = len(bot.mediator.get_own_army_dict[UnitTypeId.OBSERVER]) + bot.unit_pending(
            UnitTypeId.OBSERVER
        )
        if observers < OBSERVER_COUNT:
            out.append(
                SpawnController(
                    {UnitTypeId.OBSERVER: {"proportion": 1.0, "priority": 0}},
                    freeflow_mode=True,
                    maximum=OBSERVER_COUNT - observers,
                )
            )
        out.append(SpawnController(buildable))
        # ares's SpawnController stops at the first unit it can't afford (ares-sc2
        # behaviors/macro/spawn_controller.py), so while it saves gas for a Colossus or Immortal no
        # Gateway unit is made. Spend a mineral float on the Gateway share of the mix meanwhile.
        if bot.minerals >= MINERAL_FLOAT_BANK:
            gateway_mix = {u: info for u, info in buildable.items() if u in GATEWAY_UNITS}
            if gateway_mix:
                out.append(SpawnController(gateway_mix, freeflow_mode=True))
        if (schedule_finished or bot.time >= PRODUCTION_CONTROLLER_START_S) and not plan.hold_tech:
            out.append(
                ProductionController(
                    comp,
                    base_location=bot.start_location,
                    max_production_structures=MAX_PRODUCTION_STRUCTURES,
                )
            )
        return out
