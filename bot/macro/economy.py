"""Probes, gas, expansions and chrono (DESIGN.md §1, §3 `macro/economy.py`, §4.1).

During the opener the ares build runner makes probes (`ConstantWorkerProductionTill`), gas
and the natural itself; `CitadelBot` only adds these behaviors once the opener is complete.
Chrono runs from the first step, because the openers in protoss_builds.yml have no chrono steps.
"""

from typing import TYPE_CHECKING, Optional

from ares.behaviors.macro import BuildWorkers, ExpansionController, GasBuildingController
from sc2.ids.ability_id import AbilityId
from sc2.ids.buff_id import BuffId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.unit import Unit

from bot.constants import CHRONO_AFTER_WARPGATE, MAX_BASES, PROBE_TARGET

if TYPE_CHECKING:
    from ares import AresBot

CHRONO: AbilityId = AbilityId.EFFECT_CHRONOBOOSTENERGYCOST


class Economy:
    def __init__(self, bot: "AresBot"):
        self.bot = bot

    @staticmethod
    def worker_behavior() -> BuildWorkers:
        return BuildWorkers(to_count=PROBE_TARGET)

    @staticmethod
    def gas_behavior(to_count: int) -> GasBuildingController:
        return GasBuildingController(to_count=to_count)

    @staticmethod
    def expansion_behavior(to_count: int, prioritize: bool) -> ExpansionController:
        """Also rebuilds a lost base, since it counts ready and pending townhalls.

        `prioritize=True` returns True while the Nexus can't be afforded, so a MacroPlan keeps
        the minerals for it instead of spending them on the behaviors after it.
        """
        return ExpansionController(to_count=min(to_count, MAX_BASES), prioritize=prioritize)

    async def chrono(self) -> None:
        """Cast one chrono per call on the §4.1 target, if a Nexus has the energy for it.

        Energy cost isn't readable from game data (docs/VERIFY_NOTES.md §11.7), so ask the game
        which Nexuses can cast it right now instead of comparing energy to a number.
        """
        target: Optional[Unit] = self._chrono_target()
        if target is None:
            return
        nexuses = [th for th in self.bot.townhalls if th.is_ready]
        if not nexuses:
            return
        abilities = await self.bot.get_available_abilities(
            nexuses, ignore_resource_requirements=False
        )
        for nexus, available in zip(nexuses, abilities):
            if CHRONO in available:
                nexus(CHRONO, target)
                return

    def _chrono_target(self) -> Optional[Unit]:
        """§4.1: Nexus probes until the Core is ready, then Warp Gate research, then
        `constants.CHRONO_AFTER_WARPGATE` (Citadel's order)."""
        bot = self.bot

        def busy(type_id: UnitTypeId) -> list[Unit]:
            return [
                s
                for s in bot.mediator.get_own_structures_dict[type_id]
                if s.is_ready and not s.is_idle and not s.has_buff(BuffId.CHRONOBOOSTENERGYCOST)
            ]

        cores = [
            s for s in bot.mediator.get_own_structures_dict[UnitTypeId.CYBERNETICSCORE] if s.is_ready
        ]
        if not cores:
            nexuses = busy(UnitTypeId.NEXUS)
            return nexuses[0] if nexuses else None

        if UpgradeId.WARPGATERESEARCH not in bot.state.upgrades:
            # the research sits on the Core; wait for it to start rather than spend elsewhere
            researching = busy(UnitTypeId.CYBERNETICSCORE)
            return researching[0] if researching else None

        for type_id in CHRONO_AFTER_WARPGATE:
            if type_id == UnitTypeId.NEXUS and bot.supply_workers >= PROBE_TARGET:
                continue
            if candidates := busy(type_id):
                return candidates[0]
        return None
