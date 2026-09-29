"""Scripted cheese bots for M2's acceptance games (DESIGN.md §7 M2, §8).

`TEST_BOTS` maps each `run_matches.py --opponent` name to its bot class and the races it
plays; a race list with several entries is cycled game by game.
"""

from sc2.data import Race

from scripts.test_bots.cannon_rush import CannonRushBot
from scripts.test_bots.proxy_rax import ProxyRaxBot
from scripts.test_bots.twelve_pool import TwelvePoolBot
from scripts.test_bots.worker_rush import WorkerRushBot

TEST_BOTS: dict[str, tuple[type, tuple[Race, ...]]] = {
    "worker_rush": (WorkerRushBot, (Race.Protoss, Race.Terran, Race.Zerg)),
    "cannon_rush": (CannonRushBot, (Race.Protoss,)),
    "twelve_pool": (TwelvePoolBot, (Race.Zerg,)),
    "proxy_rax": (ProxyRaxBot, (Race.Terran,)),
}
