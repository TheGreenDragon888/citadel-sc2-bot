"""Weapon reach between two units (M7 C1/C5/C6/C7, DESIGN.md §4.5.2-4.5.3).

Shared by `micro.py` (the out-ranged step) and `engagement.py` (the out-range penalty), so neither
imports the other. Ranges are python-sc2's: game data without upgrades, with its Battlecruiser and
Oracle special cases. A type with no weapon in game data (Void Ray, Carrier, Sentry, Baneling,
burrowed Widow Mine, Infestor: VERIFY_NOTES "M7 findings") uses ares's influence-map range for it
(`WEIGHT_COSTS`, user decision D19); one with neither (Disruptor, Swarm Host, Viper) can't hit
anything here.
"""

from typing import Optional

from ares.dicts.weight_costs import WEIGHT_COSTS
from sc2.unit import Unit

from bot.constants import MELEE_RANGE_MAX, OUTRANGED_MARGIN


def weapon_range(unit: Unit, flying: bool) -> Optional[float]:
    """`unit`'s range against a target on the air (`flying`) or ground layer, or None if it has no
    weapon for that layer: game data first, else ares's `WEIGHT_COSTS` entry when its range there
    is above 0 (D19)."""
    if unit.can_attack_air if flying else unit.can_attack_ground:
        return unit.air_range if flying else unit.ground_range
    if unit.can_attack_air or unit.can_attack_ground:
        return None  # a game-data weapon, just not for this layer
    entry = WEIGHT_COSTS.get(unit.type_id)
    if entry is None:
        return None
    r = entry["AirRange"] if flying else entry["GroundRange"]
    return float(r) if r > 0 else None


def has_weapon(unit: Unit) -> bool:
    """`unit` can hit something on either layer (game data or ares's range, D19)."""
    return weapon_range(unit, False) is not None or weapon_range(unit, True) is not None


def range_vs(unit: Unit, target: Unit) -> float:
    """`unit`'s range against `target`, 0 if it can't hit it."""
    return weapon_range(unit, target.is_flying) or 0.0


def can_hit(unit: Unit, target: Unit) -> bool:
    """`unit` has a weapon for `target`'s layer."""
    return weapon_range(unit, target.is_flying) is not None


def can_hit_layer(unit: Unit, flying: bool) -> bool:
    """`unit` has a weapon for the air (`flying`) or ground layer."""
    return weapon_range(unit, flying) is not None


def reach(attacker: Unit, target: Unit) -> Optional[float]:
    """Centre-to-centre distance from which `attacker` hits `target` (range plus both radii), or
    None if it can't hit it."""
    r = weapon_range(attacker, target.is_flying)
    if r is None:
        return None
    return r + attacker.radius + target.radius


def outranged(
    our_range: Optional[float], their_range: Optional[float], margin: float, melee_max: float = MELEE_RANGE_MAX
) -> bool:
    """M7 C1 (§4.5.3): an enemy with `their_range` against us (None: it can't hit us) out-ranges
    us, with `our_range` against it (None: we can't hit it), by at least `margin`. A melee unit
    (`our_range` at most `melee_max`) is out-ranged only by enemies it can't hit (D18: Zealots
    stepped back from Marines) (pure)."""
    if their_range is None:
        return False
    if our_range is None:
        return True
    return our_range > melee_max and their_range - our_range >= margin


def outranges(enemy: Unit, unit: Unit) -> bool:
    """`enemy` out-ranges `unit` by OUTRANGED_MARGIN, or can hit it while `unit` can't hit back."""
    return outranged(
        weapon_range(unit, enemy.is_flying),
        weapon_range(enemy, unit.is_flying),
        OUTRANGED_MARGIN,
    )


def outrange_penalty(share: float, per_share: float) -> int:
    """M7 C5 (§4.5.2): whole levels off a fight's level for `share` (0-1) of the enemy's value
    that out-ranges every unit of ours able to hit it, or that none can hit; rounded half up
    (pure)."""
    return int(share * per_share + 0.5)
