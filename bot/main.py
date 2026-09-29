from typing import Optional

from ares import AresBot
from ares.behaviors.macro import Mining
from loguru import logger

from bot.constants import OPENER_TIMEOUT_S, PROBE_TARGET
from bot.ruleset import detect_ruleset


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

    async def on_start(self) -> None:
        # §4.0: loop-0 state is parsed here, before ares picks an opener in super().on_start()
        self.ruleset = detect_ruleset(self)
        await super(CitadelBot, self).on_start()
        self.opener = self.build_order_runner.chosen_opening
        logger.info(f"OPENER {self.opener} (enemy race at start: {self.enemy_race.name})")
        yaml_probes = self.config["Builds"][self.opener].get("ConstantWorkerProductionTill")
        if yaml_probes != PROBE_TARGET:
            logger.warning(
                f"protoss_builds.yml {self.opener} ConstantWorkerProductionTill={yaml_probes} "
                f"but constants.PROBE_TARGET={PROBE_TARGET}"
            )

    async def on_step(self, iteration: int) -> None:
        await super(CitadelBot, self).on_step(iteration)
        # ares only moves workers that a Mining behavior tells to mine; register it every step
        self.register_behavior(Mining())

        if not self.build_order_runner.build_completed and self.time > OPENER_TIMEOUT_S:
            logger.warning(
                f"OPENER {self.opener} still running at {self.time_formatted} "
                f"(step {self.build_order_runner.build_step}); ending it"
            )
            self.build_order_runner.set_build_completed()
