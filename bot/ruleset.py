"""§4.0 ruleset detection: 8-worker (5.0.16) vs 12-worker ruleset, probed on loop 0."""

from typing import TYPE_CHECKING

from loguru import logger

from bot.constants import RULESET_8_WORKER, RULESET_8_WORKER_MAX, RULESET_12_WORKER

if TYPE_CHECKING:
    from ares import AresBot


def detect_ruleset(bot: "AresBot") -> str:
    """Return the ruleset key and log the evidence for it.

    Call from `on_start` before `super().on_start()`: python-sc2 has parsed the loop-0
    observation by then, and ares has not yet chosen an opener (docs/VERIFY_NOTES.md §11.8).
    `supply_cap` is logged, not used: 13 means 5.0.16 Nexus supply, 15 means pre-5.0.16.
    """
    workers: int = len(bot.workers)
    ruleset: str = RULESET_8_WORKER if workers <= RULESET_8_WORKER_MAX else RULESET_12_WORKER
    logger.info(
        f"RULESET probe: map={bot.game_info.map_name} game_loop={bot.state.game_loop} "
        f"workers={workers} supply_cap={bot.supply_cap} supply_used={bot.supply_used} "
        f"ruleset={ruleset}"
    )
    return ruleset
