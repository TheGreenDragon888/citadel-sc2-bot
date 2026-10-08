"""Weapon reach between two units, from game data (M7 C1/C5, DESIGN.md §4.5.2-4.5.3).

Shared by `micro.py` (the out-ranged step) and `engagement.py` (the out-range penalty), so neither
imports the other. Ranges are python-sc2's: game data without upgrades, with its Battlecruiser and
Oracle special cases; a Carrier has no weapon in game data (its Interceptors do), so it never
out-ranges anything here (VERIFY_NOTES "M7 findings").
"""

from typing import Optional

from sc2.unit import Unit

from bot.constants import OUTRANGED_MARGIN


def range_vs(unit: Unit, target: Unit) -> float:
    return unit.air_range if target.is_flying else unit.ground_range


def can_hit(unit: Unit, target: Unit) -> bool:
    """`unit` has a weapon for `target`'s layer."""
    return unit.can_attack_air if target.is_flying else unit.can_attack_ground


def reach(attacker: Unit, target: Unit) -> Optional[float]:
    """Centre-to-centre distance from which `attacker` hits `target` (range plus both radii), or
    None if it can't hit it."""
    if not can_hit(attacker, target):
        return None
    return range_vs(attacker, target) + attacker.radius + target.radius


def outranged(our_range: Optional[float], their_range: Optional[float], margin: float) -> bool:
    """M7 C1 (§4.5.3): an enemy with `their_range` against us (None: it can't hit us) out-ranges
    us, with `our_range` against it (None: we can't hit it), by at least `margin` (pure)."""
    if their_range is None:
        return False
    return our_range is None or their_range - our_range >= margin


def outranges(enemy: Unit, unit: Unit) -> bool:
    """`enemy` out-ranges `unit` by OUTRANGED_MARGIN, or can hit it while `unit` can't hit back."""
    return outranged(
        range_vs(unit, enemy) if can_hit(unit, enemy) else None,
        range_vs(enemy, unit) if can_hit(enemy, unit) else None,
        OUTRANGED_MARGIN,
    )


def outrange_penalty(share: float, per_share: float) -> int:
    """M7 C5 (§4.5.2): whole levels off a fight's level for `share` (0-1) of the enemy's value
    that out-ranges every unit of ours able to hit it, or that none can hit; rounded half up
    (pure)."""
    return int(share * per_share + 0.5)
