"""Every TUNE value and threshold Citadel uses (CLAUDE.md rule).

Section references (§) point at docs/DESIGN.md. Values that come from game data are
read at runtime instead of being listed here.
"""

from typing import NamedTuple, Optional, Tuple

# §1, §4.7: the ladder ends a game as a tie at 80,640 game loops (60:00 game time)
LADDER_TIE_GAME_SECONDS: int = 3600

# §4.0 ruleset probe: on loop 0, <= this many workers means the 8-worker (5.0.16) ruleset
RULESET_8_WORKER_MAX: int = 8
RULESET_8_WORKER: str = "816"
RULESET_12_WORKER: str = "1215"


class AresIntelFlag(NamedTuple):
    """One ares IntelManager flag, as read in ares-sc2 v3.13.1 source (docs/VERIFY_NOTES.md §11.1).

    Read it as the mediator property `self.mediator.<accessor>` (no call parentheses),
    after `await super().on_step(iteration)` so the managers have updated this step.
    """

    accessor: str
    races: str  # enemy race the check runs for
    basis: str  # "units", "structures" or "units+structures": maps to §5 Evidence
    trigger: str  # the condition as coded in ares (t = self.time, game seconds)
    window_s: Optional[Tuple[float, float]]  # game-seconds window it can fire in; None = any time
    resets: bool  # False = latched True for the rest of the game once raised
    evaluated: str  # "every step" (ares update) or "on read" (lazy property)


# §4.2: ares IntelManager flags. Citadel's own ThreatFlag expiry (§5) applies on top of these.
ARES_INTEL: dict[str, AresIntelFlag] = {
    flag.accessor: flag
    for flag in (
        AresIntelFlag(
            "get_enemy_worker_rushed", "any", "units",
            "> 6 enemy workers (incl. remembered) within 15 of our start or 16 of our natural",
            (0, 180), False, "every step",
        ),
        AresIntelFlag(
            "get_enemy_ling_rushed", "Zerg", "units",
            "> 2 lings within 50 of our start (t<150), or > 7 lings seen (t<180), "
            "or > 4 lings seen (t<90); counts every ling ever seen and not dead",
            (0, 180), False, "every step",
        ),
        AresIntelFlag(
            "get_enemy_roach_rushed", "Zerg", "units",
            ">= 6 roaches within 50 of our start (t<240), or >= 3 roaches seen (t<180)",
            (0, 240), False, "every step",
        ),
        AresIntelFlag(
            "get_enemy_went_reaper", "Terran", "units",
            ">= 1 reaper ever seen",
            None, False, "every step",
        ),
        AresIntelFlag(
            "get_enemy_ravager_rush", "Zerg", "units",
            ">= 1 ravager seen, before 240 s",
            (0, 240), True, "on read",
        ),
        AresIntelFlag(
            "get_enemy_marine_rush", "Terran", "units+structures",
            ">= 3 barracks (t<180), or marines >= max(3, int(t)//45) more than 60 from the enemy "
            "start (t<300); False once t>210, any factory seen, or >= 2 enemy townhalls",
            (0, 210), True, "on read",
        ),
        AresIntelFlag(
            "get_enemy_went_marine_rush", "Terran", "units+structures",
            "latch: set only when get_enemy_marine_rush is read and True",
            (0, 210), False, "on read",
        ),
        AresIntelFlag(
            "get_enemy_marauder_rush", "Terran", "units+structures",
            "barracks tech lab within 55 of our natural, or >= 2 marauders (t<210), "
            "or >= 1 marauder (t<160)",
            (0, 240), True, "on read",
        ),
        AresIntelFlag(
            "get_enemy_went_marauder_rush", "Terran", "units+structures",
            "latch: set only when get_enemy_marauder_rush is read and True",
            (0, 240), False, "on read",
        ),
        AresIntelFlag(
            "get_enemy_four_gate", "Protoss", "structures",
            ">= 3 gateways (warp gates not counted) with < 2 enemy townhalls; False once t>210",
            (0, 200), True, "on read",
        ),
        AresIntelFlag(
            "get_enemy_went_four_gate", "Protoss", "structures",
            "latch: set only when get_enemy_four_gate is read and True",
            (0, 200), False, "on read",
        ),
        AresIntelFlag(
            "get_is_proxy_zealot", "Protoss", "units+structures",
            ">= 2 gateways within 100 of our start and > 60 from the enemy start, or >= 1 zealot "
            "within 65 of our start (t<150)",
            (0, 240), True, "on read",
        ),
        AresIntelFlag(
            "get_enemy_expanded", "any", "structures",
            "an enemy townhall > 6 from the enemy start location (no timing check)",
            None, True, "on read",
        ),
        AresIntelFlag(
            "get_enemy_has_base_outside_natural", "any", "structures",
            "an enemy townhall > 6 from both the enemy start and the enemy natural",
            None, True, "on read",
        ),
        AresIntelFlag(
            "get_did_enemy_rush", "any", "units+structures",
            "OR of ling/worker/roach rushed, marauder rush without expansion, proxy zealot, ravager "
            "rush, marine latch with no enemy structure within 15 of our natural, four gate, "
            ">= 3 roaches (t<240), >= 1 ling (t<105), >= 2 barracks (t<120)",
            None, False, "on read",
        ),
        AresIntelFlag(
            "get_enemy_was_greedy", "any", "structures",
            "never computed in ares v3.13.1: always False",
            None, True, "never",
        ),
    )
}
