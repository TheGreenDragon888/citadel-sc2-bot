from typing import Optional

from ares import AresBot

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

    async def on_start(self) -> None:
        # §4.0: loop-0 state is parsed here, before ares picks an opener in super().on_start()
        self.ruleset = detect_ruleset(self)
        await super(CitadelBot, self).on_start()

    async def on_step(self, iteration: int) -> None:
        await super(CitadelBot, self).on_step(iteration)
        # bot logic here ...
