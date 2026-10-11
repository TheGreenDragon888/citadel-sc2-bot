"""The remembered enemy army's mix (M7 K3, DESIGN.md §4.5.1).

`measure` (pure) turns ares's army cache into shares by supply, as §4.5.1's air switch is:
- `bio_share`: biological units (the game-data attribute; python-sc2 `Unit.is_biological`);
- `zealot_share`: Zealots;
- `air_share`: flying units (D30, ahead of E2: it pauses the gas-starved Zealot float).

Only units with a weapon (`ranges.has_weapon`) count. Sightings older than `MIX_FRESH_S` fade
linearly to nothing over another `MIX_FRESH_S`. `ArchonSwitch` turns an Archon share on at its
threshold and off again only after the share has stayed below it for `MIX_SWITCH_HOLD_S`, so the
mix doesn't flip back and forth (`ShareSwitch`; the air one holds for `AIR_SWITCH_HOLD_S`).
`EnemyMixTracker` reads the cache each intel tick.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple, Optional, Sequence

from loguru import logger

from bot.army.engagement import is_fighter
from bot.army.ranges import has_weapon
from bot.constants import (
    AIR_SWITCH_HOLD_S,
    AIR_SWITCH_SHARE,
    BIO_SHARE_FOR_ARCHONS,
    MIX_FRESH_S,
    MIX_SWITCH_HOLD_S,
    ZEALOT_SHARE_FOR_ARCHONS,
)

if TYPE_CHECKING:
    from ares import AresBot


class MixEntry(NamedTuple):
    type_name: str
    supply: float
    biological: bool
    can_attack: bool
    age: float  # seconds since last seen
    flying: bool = False


@dataclass
class EnemyMix:
    army_supply: float = 0.0
    bio_share: float = 0.0
    zealot_share: float = 0.0
    air_share: float = 0.0


def fade(age: float, fresh_s: float = MIX_FRESH_S) -> float:
    """Weight of a sighting `age` seconds old: 1 up to `fresh_s`, then down to 0 over another
    `fresh_s` (pure)."""
    if age <= fresh_s:
        return 1.0
    return max(0.0, 1.0 - (age - fresh_s) / fresh_s)


def measure(entries: Sequence[MixEntry], fresh_s: float = MIX_FRESH_S) -> EnemyMix:
    """Supply-weighted shares of the remembered enemy army (pure)."""
    army = bio = zealot = air = 0.0
    for e in entries:
        if not e.can_attack:
            continue
        w = fade(e.age, fresh_s) * e.supply
        army += w
        if e.biological:
            bio += w
        if e.type_name == "ZEALOT":
            zealot += w
        if e.flying:
            air += w
    if army <= 0:
        return EnemyMix()
    return EnemyMix(army, bio / army, zealot / army, air / army)


def switch(on: bool, share: float, threshold: float, below_since: Optional[float], now: float, hold_s: float = MIX_SWITCH_HOLD_S) -> tuple[bool, Optional[float]]:
    """Hysteresis for an Archon share: on at `threshold`; off once the share has been below it for
    `hold_s` (`below_since`: when it fell below, None while at or above) (pure). Returns the new
    (on, below_since)."""
    if share >= threshold:
        return True, None
    if not on:
        return False, None
    since = now if below_since is None else below_since
    return (False, None) if now - since >= hold_s else (True, since)


class ShareSwitch:
    def __init__(self, threshold: float, hold_s: float = MIX_SWITCH_HOLD_S) -> None:
        self.threshold = threshold
        self.hold_s = hold_s
        self.on = False
        self.below_since: Optional[float] = None

    def update(self, share: float, now: float) -> bool:
        self.on, self.below_since = switch(self.on, share, self.threshold, self.below_since, now, self.hold_s)
        return self.on


class EnemyMixTracker:
    """Each intel tick: the mix from ares's army cache, the two Archon switches (§4.5.1: vs T
    while the army is mostly biological, vs P while it is Zealot-heavy) and the air switch (D30)."""

    def __init__(self, bot: "AresBot") -> None:
        self.bot = bot
        self.mix = EnemyMix()
        self.vs_bio = ShareSwitch(BIO_SHARE_FOR_ARCHONS)
        self.vs_zealots = ShareSwitch(ZEALOT_SHARE_FOR_ARCHONS)
        self.air = ShareSwitch(AIR_SWITCH_SHARE, AIR_SWITCH_HOLD_S)

    def update(self) -> None:
        bot = self.bot
        entries = [
            MixEntry(u.type_id.name, bot.calculate_supply_cost(u.type_id), u.is_biological, has_weapon(u), u.age, u.is_flying)
            for u in bot.mediator.get_cached_enemy_army
            if is_fighter(u)
        ]
        self.mix = measure(entries)
        now = bot.time
        self.vs_bio.update(self.mix.bio_share, now)
        self.vs_zealots.update(self.mix.zealot_share, now)
        if self.air.on != self.air.update(self.mix.air_share, now):
            logger.info(f"MIX {bot.time_formatted} enemy air switch {'on' if self.air.on else 'off'} (air share {self.mix.air_share:.2f})")
