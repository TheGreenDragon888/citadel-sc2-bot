"""Army production and upgrades (DESIGN.md §3 `macro/production.py`, §4.5.1).

M1 scaffolding so the bot can win games: the §4.5.1 unit mix through ares's SpawnController
(units) and ProductionController (adds Gateways/Robotics Facilities and the tech buildings the
mix needs), plus the §4.5.1 upgrade order through ares's UpgradeController. The air switch and
the combat-sim checks of the mix come later.
"""

from typing import TYPE_CHECKING, Optional

from ares.behaviors.macro import ProductionController, SpawnController, UpgradeController
from ares.consts import GATEWAY_UNITS
from sc2.data import Race
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId

from bot.constants import (
    ARMY_COMPOSITION_PCT,
    ARMY_PRIORITY,
    MAX_PRODUCTION_STRUCTURES,
    MINERAL_FLOAT_BANK,
    OBSERVER_COUNT,
    PRODUCTION_CONTROLLER_START_S,
    UPGRADES_START_S,
    UPGRADES_VS_P,
    UPGRADES_VS_ZT,
)

if TYPE_CHECKING:
    from ares import AresBot
    from ares.behaviors.behavior import Behavior

    from bot.defense.defense_planner import DefensePlan


class Production:
    def __init__(self, bot: "AresBot"):
        self.bot = bot

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
