"""Army production and upgrades (DESIGN.md §3 `macro/production.py`, §4.5.1).

M1 scaffolding so the bot can win games: the §4.5.1 unit mix through ares's SpawnController
(units) and ProductionController (adds Gateways/Robotics Facilities and the tech buildings the
mix needs), plus the §4.5.1 upgrade order through ares's UpgradeController. The air switch and
the combat-sim checks of the mix come later.
"""

from typing import TYPE_CHECKING

from ares.behaviors.macro import ProductionController, SpawnController, UpgradeController
from ares.consts import GATEWAY_UNITS
from sc2.data import Race
from sc2.ids.unit_typeid import UnitTypeId

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


class Production:
    def __init__(self, bot: "AresBot"):
        self.bot = bot

    def composition(self) -> dict[UnitTypeId, dict[str, float]]:
        """ares composition dict for the enemy race; vs Random, the vs-T mix until the race is
        seen (§4.1 treats Random like Terran until then)."""
        race = self.bot.enemy_race
        key = race.name if race in (Race.Terran, Race.Zerg, Race.Protoss) else Race.Terran.name
        shares = ARMY_COMPOSITION_PCT[key]
        total = sum(shares.values())
        return {
            unit: {"proportion": pct / total, "priority": ARMY_PRIORITY[unit]}
            for unit, pct in shares.items()
        }

    def behaviors(self) -> list["Behavior"]:
        """Behaviors for this tick's MacroPlan, after the economy and the opener schedule."""
        bot = self.bot
        comp = self.composition()
        out: list["Behavior"] = []
        if bot.time >= UPGRADES_START_S:
            upgrades = UPGRADES_VS_P if bot.enemy_race == Race.Protoss else UPGRADES_VS_ZT
            out.append(UpgradeController(list(upgrades), base_location=bot.start_location))
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
        out.append(SpawnController(comp))
        # ares's SpawnController stops at the first unit it can't afford (ares-sc2
        # behaviors/macro/spawn_controller.py), so while it saves gas for a Colossus or Immortal no
        # Gateway unit is made. Spend a mineral float on the Gateway share of the mix meanwhile.
        if bot.minerals >= MINERAL_FLOAT_BANK:
            gateway_mix = {u: info for u, info in comp.items() if u in GATEWAY_UNITS}
            if gateway_mix:
                out.append(SpawnController(gateway_mix, freeflow_mode=True))
        if bot.time >= PRODUCTION_CONTROLLER_START_S:
            out.append(
                ProductionController(
                    comp,
                    base_location=bot.start_location,
                    max_production_structures=MAX_PRODUCTION_STRUCTURES,
                )
            )
        return out
