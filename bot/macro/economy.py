"""Probes, gas, expansions and chrono (DESIGN.md §1, §3 `macro/economy.py`, §4.1).

During the opener the ares build runner makes probes (`ConstantWorkerProductionTill`), gas
and the natural itself; `CitadelBot` only adds these behaviors once the opener is complete.
Chrono runs from the first step, because the openers in protoss_builds.yml have no chrono steps.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from ares.behaviors.macro import BuildWorkers, ExpansionController, GasBuildingController, Mining
from ares.consts import ID, TARGET, TIME_ORDER_COMMENCED
from loguru import logger
from sc2.ids.ability_id import AbilityId
from sc2.ids.buff_id import BuffId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.unit import Unit

from bot.constants import (
    CHRONO_AFTER_WARPGATE,
    GAS_FLOAT_HIGH,
    GAS_FLOAT_LOW,
    MAX_BASES,
    PROBE_TARGET,
    PROBES_HELD_SPARE,
    PROBES_PER_HELD_BASE,
    RESERVE_FOR_PENDING_MAX_S,
    WORKERS_PER_GAS_FLOATING,
)

if TYPE_CHECKING:
    from ares import AresBot

CHRONO: AbilityId = AbilityId.EFFECT_CHRONOBOOSTENERGYCOST


@dataclass
class ReserveForPending:
    """Holds the rest of a MacroPlan while a probe waits at a build spot for money.

    ares's ExpansionController sends a probe as soon as it decides to expand, then counts that
    order as pending and stops holding money (`expansion_controller.py`, `execute`), so
    everything after it keeps spending and the probe can wait for minutes (a worker-rush test
    game sat at one base until 10:00 with the probe parked at the natural).
    """

    type_id: UnitTypeId

    def execute(self, ai: "AresBot", config: dict, mediator) -> bool:
        """True (hold) while an order for `type_id` younger than RESERVE_FOR_PENDING_MAX_S waits
        for money; an older one is likely stuck and shouldn't starve everything else."""
        if ai.can_afford(self.type_id):
            return False
        return any(
            info[ID] == self.type_id
            and info[TARGET] is not None
            and ai.time - info[TIME_ORDER_COMMENCED] <= RESERVE_FOR_PENDING_MAX_S
            for info in mediator.get_building_tracker_dict.values()
        )


class Economy:
    def __init__(self, bot: "AresBot"):
        self.bot = bot
        self.gas_floating: bool = False

    def mining_behavior(self, long_distance: bool = True) -> Mining:
        """ares's Mining (speed mining included). While at least `GAS_FLOAT_HIGH` gas is banked,
        only `WORKERS_PER_GAS_FLOATING` probes per gas building; back to 3 below `GAS_FLOAT_LOW`
        (defense plans make mineral-only units, and a one-base bot starves on minerals).

        `long_distance=False` keeps spare probes home instead of sending them to other bases'
        minerals (ares's long-distance mining walked them one by one into rush Cannons at our
        natural in test games)."""
        vespene = self.bot.vespene
        if not self.gas_floating and vespene >= GAS_FLOAT_HIGH:
            self.gas_floating = True
            logger.info(f"GAS {vespene} banked at {self.bot.time_formatted}: {WORKERS_PER_GAS_FLOATING} probe(s) per gas")
        elif self.gas_floating and vespene < GAS_FLOAT_LOW:
            self.gas_floating = False
            logger.info(f"GAS {vespene} banked at {self.bot.time_formatted}: 3 probes per gas again")
        return Mining(
            workers_per_gas=WORKERS_PER_GAS_FLOATING if self.gas_floating else 3,
            long_distance_mine=long_distance,
        )

    def worker_behavior(self, expansion_allowed: bool = True) -> BuildWorkers:
        """Probes to PROBE_TARGET (§1). While a threat plan forbids expanding, only to
        PROBES_PER_HELD_BASE per ready base plus PROBES_HELD_SPARE: probes past saturation
        took the minerals the Gateways needed in cannon-rush test games (60 probes on one base,
        idle Warp Gates)."""
        target = PROBE_TARGET
        if not expansion_allowed:
            bases = max(1, len(self.bot.ready_townhalls))
            target = min(PROBE_TARGET, PROBES_PER_HELD_BASE * bases + PROBES_HELD_SPARE)
        return BuildWorkers(to_count=target)

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

    async def chrono(self, gateways_first: bool = False) -> None:
        """Cast one chrono per call on the §4.1 target, if a Nexus has the energy for it.
        `gateways_first` (§4.2 proxy plan, "chrono the Gateway units") puts a busy Gateway first.

        Energy cost isn't readable from game data (docs/VERIFY_NOTES.md §11.7), so ask the game
        which Nexuses can cast it right now instead of comparing energy to a number.
        """
        gates = self._busy(UnitTypeId.GATEWAY) if gateways_first else []
        target: Optional[Unit] = gates[0] if gates else self._chrono_target()
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

    def _busy(self, type_id: UnitTypeId) -> list[Unit]:
        return [
            s
            for s in self.bot.mediator.get_own_structures_dict[type_id]
            if s.is_ready and not s.is_idle and not s.has_buff(BuffId.CHRONOBOOSTENERGYCOST)
        ]

    def _chrono_target(self) -> Optional[Unit]:
        """§4.1: Nexus probes until the Core is ready, then Warp Gate research, then
        `constants.CHRONO_AFTER_WARPGATE` (Citadel's order)."""
        bot = self.bot
        busy = self._busy

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
