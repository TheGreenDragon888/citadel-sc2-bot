"""The remembered enemy army's mix (M7 K3, DESIGN.md §4.5.1).

`measure` (pure) turns ares's army cache into shares by supply, as §4.5.1's air switch is:
- `bio_share`: biological units (the game-data attribute; python-sc2 `Unit.is_biological`);
- `zealot_share`: Zealots.

Only units with a weapon (`ranges.has_weapon`) count. Sightings older than `MIX_FRESH_S` fade
linearly to nothing over another `MIX_FRESH_S`. `ArchonSwitch` turns an Archon share on at its
threshold and off again only after the share has stayed below it for `MIX_SWITCH_HOLD_S`, so the
mix doesn't flip back and forth. `EnemyMixTracker` reads the cache each intel tick.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple, Optional, Sequence

from bot.army.engagement import is_fighter
from bot.army.ranges import has_weapon
from bot.constants import (
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


@dataclass
class EnemyMix:
    army_supply: float = 0.0
    bio_share: float = 0.0
    zealot_share: float = 0.0


def fade(age: float, fresh_s: float = MIX_FRESH_S) -> float:
    """Weight of a sighting `age` seconds old: 1 up to `fresh_s`, then down to 0 over another
    `fresh_s` (pure)."""
    if age <= fresh_s:
        return 1.0
    return max(0.0, 1.0 - (age - fresh_s) / fresh_s)


def measure(entries: Sequence[MixEntry], fresh_s: float = MIX_FRESH_S) -> EnemyMix:
    """Supply-weighted shares of the remembered enemy army (pure)."""
    army = bio = zealot = 0.0
    for e in entries:
        if not e.can_attack:
            continue
        w = fade(e.age, fresh_s) * e.supply
        army += w
        if e.biological:
            bio += w
        if e.type_name == "ZEALOT":
            zealot += w
    if army <= 0:
        return EnemyMix()
    return EnemyMix(army, bio / army, zealot / army)


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


class ArchonSwitch:
    def __init__(self, threshold: float) -> None:
        self.threshold = threshold
        self.on = False
        self.below_since: Optional[float] = None

    def update(self, share: float, now: float) -> bool:
        self.on, self.below_since = switch(self.on, share, self.threshold, self.below_since, now)
        return self.on


class EnemyMixTracker:
    """Each intel tick: the mix from ares's army cache, and the two Archon switches (§4.5.1: vs T
    while the army is mostly biological, vs P while it is Zealot-heavy)."""

    def __init__(self, bot: "AresBot") -> None:
        self.bot = bot
        self.mix = EnemyMix()
        self.vs_bio = ArchonSwitch(BIO_SHARE_FOR_ARCHONS)
        self.vs_zealots = ArchonSwitch(ZEALOT_SHARE_FOR_ARCHONS)

    def update(self) -> None:
        bot = self.bot
        entries = [
            MixEntry(u.type_id.name, bot.calculate_supply_cost(u.type_id), u.is_biological, has_weapon(u), u.age)
            for u in bot.mediator.get_cached_enemy_army
            if is_fighter(u)
        ]
        self.mix = measure(entries)
        now = bot.time
        self.vs_bio.update(self.mix.bio_share, now)
        self.vs_zealots.update(self.mix.zealot_share, now)
