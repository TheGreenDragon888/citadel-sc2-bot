import time
from typing import Optional

from ares import AresBot
from ares.behaviors.macro import MacroPlan
from loguru import logger
from sc2.data import Result
from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import Unit

from bot.army.army import Army
from bot.army.endgame import EndGame
from bot.constants import (
    ARMY_EVERY_STEPS,
    INTEL_EVERY_STEPS,
    MACRO_EVERY_STEPS,
    OPENER_TIMEOUT_S,
    PROBE_TARGET,
    RULESET_12_WORKER,
)
from bot.defense.defense_planner import DefensePlanner
from bot.defense.static_defense import StaticDefense
from bot.defense.wall_fallback import WallFallback
from bot.defense.worker_defense import WorkerDefense
from bot.intel.ares_bridge import AresBridge
from bot.intel.detectors import Detectors
from bot.intel.scout_planner import ScoutPlanner
from bot.intel.threat_flags import FlagStore, Threat
from bot.macro.build_executor import BuildExecutor
from bot.macro.economy import Economy, KeepBank, ReserveForPending
from bot.macro.production import Production
from bot.macro.supply import supply_behavior
from bot.ruleset import detect_ruleset
from bot.telemetry.logger import Telemetry


class CitadelBot(AresBot):
    def __init__(self, game_step_override: Optional[int] = None):
        """Citadel: Protoss bot for the AI Arena ladder (docs/DESIGN.md).

        Parameters
        ----------
        game_step_override :
            If provided, set the game_step to this value regardless of how it was
            specified elsewhere
        """
        super().__init__(game_step_override)
        self.ruleset: Optional[str] = None
        self.opener: str = ""
        self.economy: Optional[Economy] = None
        self.executor: Optional[BuildExecutor] = None
        self.telemetry: Optional[Telemetry] = None
        self.production: Optional[Production] = None
        self.army: Optional[Army] = None  # M4: squads, EngagementResult gates (§4.5.2)
        self.endgame: Optional[EndGame] = None  # M4: §4.7 end-game rules
        self.wall: Optional[WallFallback] = None
        self.wall_ok: Optional[bool] = None
        self.pylon_fallback_scan_at: Optional[float] = None  # macro/supply.py
        # M2: intel and defense (§3, §4.2, §5)
        self.flags: Optional[FlagStore] = None
        self.planner: Optional[DefensePlanner] = None
        self.bridge: Optional[AresBridge] = None
        self.detectors: Optional[Detectors] = None
        self.scouts: Optional[ScoutPlanner] = None  # M3: §4.3 scouting schedule
        self.static_defense: Optional[StaticDefense] = None
        self.worker_defense: Optional[WorkerDefense] = None

    async def on_start(self) -> None:
        # §4.0: loop-0 state is parsed here, before ares picks an opener in super().on_start()
        self.ruleset = detect_ruleset(self)
        if self.ruleset != RULESET_12_WORKER:
            # M1 ships 12-worker openers only (every pool map is 12-worker, VERIFY_NOTES §11.8)
            logger.error(f"RULESET {self.ruleset}: no openers for it; playing the 12-worker ones")
        # §4.8: must run before ares's placement solver, which crashes on an unusable ramp wall
        self.wall = WallFallback(self)
        self.wall_ok = self.wall.prepare()
        await super(CitadelBot, self).on_start()
        self.wall.after_start()
        self.opener = self.build_order_runner.chosen_opening
        logger.info(f"OPENER {self.opener} (enemy race at start: {self.enemy_race.name})")
        yaml_probes = self.config["Builds"][self.opener].get("ConstantWorkerProductionTill")
        if yaml_probes != PROBE_TARGET:
            logger.warning(
                f"protoss_builds.yml {self.opener} ConstantWorkerProductionTill={yaml_probes} "
                f"but constants.PROBE_TARGET={PROBE_TARGET}"
            )
        self.flags = FlagStore()
        self.planner = DefensePlanner(self, self.flags)
        self.bridge = AresBridge(self, self.flags, self.planner.override_for)
        self.detectors = Detectors(self, self.flags, self.planner.override_for)
        self.telemetry = Telemetry(self)
        self.endgame = EndGame(self)
        self.scouts = ScoutPlanner(self, self.detectors, self.flags, self.telemetry, self.endgame)
        self.static_defense = StaticDefense(self, self.planner)
        self.worker_defense = WorkerDefense(self, self.planner)
        self.economy = Economy(self)
        self.executor = BuildExecutor(self, self.opener, self.planner)
        self.production = Production(self)
        self.army = Army(self, self.endgame)

    async def on_step(self, iteration: int) -> None:
        started = time.perf_counter()
        await super(CitadelBot, self).on_step(iteration)
        # ares only moves workers that a Mining behavior tells to mine; register it every step.
        # No long-distance mining while rush Cannons may cover other bases' minerals (§4.2), or
        # while our unit holds the wall gap (the probes would walk out past it into the lings)
        plan = self.planner.plan
        self.register_behavior(
            self.economy.mining_behavior(
                long_distance=Threat.CANNON_RUSH not in plan.active and not plan.hold_wall_gap
            )
        )

        if not self.build_order_runner.build_completed and self.time > OPENER_TIMEOUT_S:
            logger.warning(
                f"OPENER {self.opener} still running at {self.time_formatted} "
                f"(step {self.build_order_runner.build_step}); ending it"
            )
            self.build_order_runner.set_build_completed()
            self.planner.opener_ended_by = "timeout"  # BuildExecutor adds the opener essentials

        # §3 step 2: intel, flag expiry and the defense plan
        if iteration % INTEL_EVERY_STEPS == 0:
            self.bridge.update()
            self.detectors.update()
            self.flags.expire(self.time, self.detectors.expiry_context(self.supply_army))
            self.planner.update()
        plan = self.planner.plan
        if iteration % MACRO_EVERY_STEPS == 0:
            # §3 step 4; the ATTACK/REINFORCE squads and the army's Observer are not free to scout
            self.scouts.step(pinned=self.army.held_tags | plan.pinned_unit_tags | self.army.busy_tags)
        self.worker_defense.step(plan)  # §3 step 5: every step

        if iteration % MACRO_EVERY_STEPS == 0:
            self.static_defense.step(plan)
            self.production.gateway_upkeep()
            # units before structures: in test games Batteries and Pylons took every mineral
            # while Marines walked in
            defense = self.production.defense_behaviors(plan) + self.static_defense.behaviors(plan)
            await self.economy.chrono(gateways_first=plan.chrono_gateways)
            if self.build_order_runner.build_completed:
                self._register_macro_plan(defense)
            elif defense:
                # during the opener the build runner makes Pylons; defense spends before it
                # can act again (Defense > Economy, §3)
                defense_plan = MacroPlan()
                for behavior in defense:
                    defense_plan.add(behavior)
                self.register_behavior(defense_plan)

        if iteration % ARMY_EVERY_STEPS == 0:
            holder = self.wall.step(hold_gap=plan.hold_wall_gap)
            # the wall-gap holder and scouts are controlled elsewhere
            self.army.held_tags = {holder} if holder is not None else set()
            self.army.scout_tags = self.scouts.tags
            plan.pinned_unit_tags = self.army.held_tags | self.scouts.tags | set(self.worker_defense.jobs)
            self.army.hold_point = plan.army_hold_point
            self.army.leash = plan.army_leash
            self.endgame.update()
            self.army.step(iteration)
        self.army.micro(iteration)  # §3 step 5: squad micro every step

        self.telemetry.step()
        self.telemetry.record_step_time(started)

    def _register_macro_plan(self, defense: list) -> None:
        """After the opener. A MacroPlan stops at the first behavior that acts (or, for
        Pylon timing and a prioritised expansion, that is still waiting for money), so the
        order below is the spending priority: supply, the DefensePlan's structures and units
        (Defense > Economy, §3), probes, a Nexus a probe is waiting to build, timed opener
        steps, gas, bases, a mineral bank the DefensePlan asks for, then army production
        (skipped while a timed step is waiting for money)."""
        executor = self.executor
        plan = MacroPlan()
        plan.add(supply_behavior(self, other_bases=not self.planner.plan.hold_wall_gap))
        for behavior in defense:
            plan.add(behavior)
        plan.add(self.economy.worker_behavior(expansion_allowed=self.planner.plan.allow_expand))
        plan.add(ReserveForPending(UnitTypeId.NEXUS))  # a probe waiting at an expansion
        for behavior in executor.behaviors():
            plan.add(behavior)
        plan.add(self.economy.gas_behavior(executor.gas_target()))
        bases = executor.bases_target()
        plan.add(self.economy.expansion_behavior(bases, prioritize=not executor.finished))
        if self.planner.plan.bank_minerals:
            plan.add(KeepBank(self.planner.plan.bank_minerals))
        if not executor.waiting_for_money:
            for behavior in self.production.behaviors(
                schedule_finished=executor.finished, plan=self.planner.plan
            ):
                plan.add(behavior)
        self.register_behavior(plan)

    async def on_unit_destroyed(self, unit_tag: int) -> None:
        # python-sc2 still holds last step's own units here, so the type is known
        own = self._units_previous_map.get(unit_tag)
        enemy = self._enemy_units_previous_map.get(unit_tag)
        role = "?"
        if own is not None and self.static_defense is not None:
            role = next((str(r) for r, tags in self.mediator.get_unit_role_dict.items() if unit_tag in tags), "?")
            self.static_defense.on_worker_died(unit_tag, own.position)  # before ares hands its order on
        await super(CitadelBot, self).on_unit_destroyed(unit_tag)
        if self.army is not None:
            self.army.forget(unit_tag)
        if self.scouts is not None:
            self.scouts.on_unit_destroyed(unit_tag)
        if self.flags is not None:
            self.flags.on_unit_destroyed(unit_tag, self.time)  # §5 expiry rule (a)
        if own is not None and self.telemetry is not None:
            self.telemetry.on_own_unit_destroyed(own, role)
        if enemy is not None and self.telemetry is not None:
            self.telemetry.on_enemy_unit_destroyed(enemy)

    async def on_unit_took_damage(self, unit: Unit, amount_damage_taken: float) -> None:
        await super(CitadelBot, self).on_unit_took_damage(unit, amount_damage_taken)
        if self.worker_defense is not None:
            self.worker_defense.on_structure_damaged(unit)

    async def on_end(self, game_result: Result) -> None:
        if self.telemetry is not None:
            self.telemetry.end_report(self.flags, self.army)
        await super(CitadelBot, self).on_end(game_result)
