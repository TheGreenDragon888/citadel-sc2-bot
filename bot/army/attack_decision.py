"""Main attack / retreat on EngagementResult (DESIGN.md §4.5.2), with the §4.7 end-game gates.

A pure state machine: the army commander (bot/army/army.py) feeds it the level of the ATTACK
squad's fight at its target (bot/army/engagement.py) every DECISION_EVERY_STEPS steps, and acts on
the returned `Decision`. No game objects, so scripts/test_attack_decision.py tests it offline.

- GATHER -> ATTACK ("launch"): level >= ATTACK_START with ATTACK_START_SUPPLY supply used, or
  level >= ATTACK_START_MAX with ATTACK_START_MAX_SUPPLY; not within RELAUNCH_WAIT_S of a retreat.
- ATTACK -> GATHER ("retreat"): level <= RETREAT_AT, or the squad's value below
  RETREAT_VALUE_FRACTION of its start value (reinforcements that join add to the start value).
- No flip either way within MIN_STATE_SECONDS of the last one, unless the level is
  <= FLIP_ANYWAY_AT (§4.5.2). The value rule is not held back by it (Citadel: units dying is not
  simulator noise, and an enemy out of sight, e.g. sieged tanks, reads as an empty fight).
- `recall` (Defense > Main attack, §3) ends an attack without the relaunch wait.
- M7 C4 (§4.5.2 launch): a launch also needs no home fight within LAUNCH_AFTER_DEFEND_S; fresh
  intel on the remembered enemy army, or else a wait of at most LAUNCH_INTEL_WAIT_S while the army's
  Observer looks (`Decision.wants_intel`); and the level against that whole army passing the same
  gate.
- §4.7: from END_GAME_FROM_S, no launch while our army value is below the enemy's ("a tie is
  better than a loss; if we are behind, keep defending"); from END_GAME_ATTACK_FROM_S,
  ATTACK_START drops to END_GAME_ATTACK_START while our value is >= END_GAME_VALUE_RATIO x theirs.
"""

import math
from dataclasses import dataclass
from typing import Optional

from bot.constants import (
    ATTACK_CONTINUE,
    ATTACK_START,
    ATTACK_START_MAX,
    ATTACK_START_MAX_SUPPLY,
    ATTACK_START_SUPPLY,
    END_GAME_ATTACK_FROM_S,
    END_GAME_ATTACK_START,
    END_GAME_FROM_S,
    END_GAME_VALUE_RATIO,
    FLIP_ANYWAY_AT,
    LAUNCH_AFTER_DEFEND_S,
    LAUNCH_INTEL_WAIT_S,
    MIN_STATE_SECONDS,
    RELAUNCH_WAIT_S,
    RETREAT_AT,
    RETREAT_VALUE_FRACTION,
)

GATHER = "gather"
ATTACK = "attack"


@dataclass
class Decision:
    state: str  # the state after this evaluation
    action: str  # "launch", "retreat", "continue" or "wait"
    reason: str
    wants_intel: bool = False  # M7 C4: the launch waits for the army's Observer to look
    blocked_by: str = ""  # M7 C4: "home fight", "intel" or "remembered army" when that held a launch

    @property
    def flipped(self) -> bool:
        return self.action in ("launch", "retreat")


class AttackDecision:
    def __init__(self) -> None:
        self.state: str = GATHER
        self.state_since: float = 0.0
        self.retreated_at: Optional[float] = None
        self.start_value: float = 0.0
        self.intel_wait_since: Optional[float] = None  # M7 C4

    def attack_start(self, now: float, value_ratio: float) -> int:
        """ATTACK_START, lowered from 45:00 while we are ahead by END_GAME_VALUE_RATIO (§4.7)."""
        if now >= END_GAME_ATTACK_FROM_S and value_ratio >= END_GAME_VALUE_RATIO:
            return END_GAME_ATTACK_START
        return ATTACK_START

    def evaluate(
        self, now: float, level: int, supply_used: float, squad_value: float, value_ratio: float,
        since_home_fight_s: float = math.inf, army_level: Optional[int] = None, intel_fresh: bool = True,
    ) -> Decision:
        """`level`: the squad's EngagementResult value at its target; `squad_value`: resource value
        of the squad now; `value_ratio`: our army value / the enemy's remembered army value.
        M7 C4 launch inputs: seconds since the last home fight; the level against the remembered
        enemy army (None: no gate); whether that army's position is fresh."""
        held = now - self.state_since < MIN_STATE_SECONDS and level > FLIP_ANYWAY_AT
        if self.state == GATHER:
            if self.retreated_at is not None and now - self.retreated_at < RELAUNCH_WAIT_S:
                return Decision(GATHER, "wait", f"relaunch wait ({now - self.retreated_at:.0f} s since the retreat)")
            if now >= END_GAME_FROM_S and value_ratio < 1.0:
                return Decision(GATHER, "wait", f"end-game, behind (value ratio {value_ratio:.2f})")
            start = self.attack_start(now, value_ratio)
            if level >= start and supply_used >= ATTACK_START_SUPPLY:
                need = start
                why = f"level {level} >= {start}, supply {supply_used:g} >= {ATTACK_START_SUPPLY}"
            elif level >= ATTACK_START_MAX and supply_used >= ATTACK_START_MAX_SUPPLY:
                need = ATTACK_START_MAX
                why = f"level {level} >= {ATTACK_START_MAX}, supply {supply_used:g} >= {ATTACK_START_MAX_SUPPLY}"
            else:
                self.intel_wait_since = None
                return Decision(GATHER, "wait", f"level {level}, supply {supply_used:g}")
            # M7 C4: the gate above sees only what is near the squad or its target
            if since_home_fight_s < LAUNCH_AFTER_DEFEND_S:
                return Decision(GATHER, "wait", f"{why}, but a home fight {since_home_fight_s:.0f} s ago", blocked_by="home fight")
            if intel_fresh:
                self.intel_wait_since = None
            else:
                if self.intel_wait_since is None:
                    self.intel_wait_since = now
                waited = now - self.intel_wait_since
                if waited < LAUNCH_INTEL_WAIT_S:
                    return Decision(
                        GATHER, "wait", f"{why}, but the enemy army's whereabouts are stale ({waited:.0f} s looking)", True, "intel"
                    )
                why += f", intel still stale after {waited:.0f} s"
            if army_level is not None:
                if army_level < need:
                    return Decision(
                        GATHER, "wait", f"{why}, but level {army_level} < {need} vs the remembered army", blocked_by="remembered army"
                    )
                why += f", remembered army level {army_level}"
            if held:
                return Decision(GATHER, "wait", f"{why}, but {now - self.state_since:.0f} s since the last flip")
            self.state, self.state_since, self.start_value = ATTACK, now, squad_value
            self.intel_wait_since = None
            return Decision(ATTACK, "launch", why)

        if squad_value < RETREAT_VALUE_FRACTION * self.start_value:
            why = f"value {squad_value:.0f} < {RETREAT_VALUE_FRACTION:g} x start {self.start_value:.0f}"
        elif level <= RETREAT_AT:
            if held:
                return Decision(ATTACK, "continue", f"level {level} <= {RETREAT_AT}, held ({now - self.state_since:.0f} s since launch)")
            why = f"level {level} <= {RETREAT_AT}"
        else:
            return Decision(ATTACK, "continue", f"level {level} >= {ATTACK_CONTINUE}")
        self.state, self.state_since, self.retreated_at = GATHER, now, now
        return Decision(GATHER, "retreat", why)

    def add_value(self, value: float) -> None:
        """Reinforcements joined the ATTACK squad."""
        if self.state == ATTACK:
            self.start_value += value

    def recall(self, now: float) -> None:
        """Defense needs the army (§3): end the attack, without the relaunch wait."""
        if self.state == ATTACK:
            self.state, self.state_since = GATHER, now
