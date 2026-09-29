import time
from typing import Optional

from ares import AresBot
from ares.behaviors.macro import MacroPlan, Mining
from loguru import logger
from sc2.data import Result

from bot.army.basic_army import BasicArmy
from bot.constants import (
    ARMY_EVERY_STEPS,
    MACRO_EVERY_STEPS,
    OPENER_TIMEOUT_S,
    PROBE_TARGET,
    RULESET_12_WORKER,
)
from bot.defense.wall_fallback import WallFallback
from bot.macro.build_executor import BuildExecutor
from bot.macro.economy import Economy
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
        self.army: Optional[BasicArmy] = None
        self.wall: Optional[WallFallback] = None
        self.wall_ok: Optional[bool] = None

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
        self.economy = Economy(self)
        self.executor = BuildExecutor(self, self.opener)
        self.telemetry = Telemetry(self)
        self.production = Production(self)
        self.army = BasicArmy(self)

    async def on_step(self, iteration: int) -> None:
        started = time.perf_counter()
        await super(CitadelBot, self).on_step(iteration)
        # ares only moves workers that a Mining behavior tells to mine; register it every step
        self.register_behavior(Mining())

        if not self.build_order_runner.build_completed and self.time > OPENER_TIMEOUT_S:
            logger.warning(
                f"OPENER {self.opener} still running at {self.time_formatted} "
                f"(step {self.build_order_runner.build_step}); ending it"
            )
            self.build_order_runner.set_build_completed()

        if iteration % MACRO_EVERY_STEPS == 0:
            await self.economy.chrono()
            if self.build_order_runner.build_completed:
                self._register_macro_plan()

        if iteration % ARMY_EVERY_STEPS == 0:
            holder = self.wall.step()
            self.army.excluded_tags = {holder} if holder is not None else set()
            self.army.step()

        self.telemetry.step()
        self.telemetry.record_step_time(started)

    def _register_macro_plan(self) -> None:
        """After the opener. A MacroPlan stops at the first behavior that acts (or, for
        AutoSupply and a prioritised expansion, that is still waiting for money), so the
        order below is the spending priority: supply, probes, timed opener steps, gas, bases,
        then army production (skipped while a timed step is waiting for money)."""
        executor = self.executor
        plan = MacroPlan()
        plan.add(supply_behavior(self))
        plan.add(self.economy.worker_behavior())
        for behavior in executor.behaviors():
            plan.add(behavior)
        plan.add(self.economy.gas_behavior(executor.gas_target()))
        bases = executor.bases_target()
        plan.add(self.economy.expansion_behavior(bases, prioritize=not executor.finished))
        if not executor.waiting_for_money:
            for behavior in self.production.behaviors(schedule_finished=executor.finished):
                plan.add(behavior)
        self.register_behavior(plan)

    async def on_unit_destroyed(self, unit_tag: int) -> None:
        # python-sc2 still holds last step's own units here, so the type is known
        own = self._units_previous_map.get(unit_tag)
        await super(CitadelBot, self).on_unit_destroyed(unit_tag)
        if self.army is not None:
            self.army.forget(unit_tag)
        if own is not None and self.telemetry is not None:
            self.telemetry.on_own_unit_destroyed(own.type_id)

    async def on_end(self, game_result: Result) -> None:
        if self.telemetry is not None:
            self.telemetry.end_report()
        await super(CitadelBot, self).on_end(game_result)
