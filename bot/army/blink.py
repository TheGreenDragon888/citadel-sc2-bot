"""Blink rules for Stalkers (M7 K2, DESIGN.md §4.5.3).

Stalkers with Blink ready (`AbilityId.EFFECT_BLINK_STALKER in unit.abilities`; it drops out of the
set while on cooldown, VERIFY_NOTES "M7 findings"):
- **blink back** on low shields (`BLINK_BACK_SHIELD_FRACTION`) when an enemy that can hit them has
  them in reach, to the safest spot within `BLINK_RANGE`;
- **blink in** onto an out-ranger when the squad is committed: in waves, at most one per out-ranger
  per `BLINK_IN_PER_TARGET_S`, which the Stalkers ready within `BLINK_IN_WAVE_S` of its start join,
  started only with `BLINK_IN_MIN_STALKERS` ready nearby, so they arrive as a group;
- **blink to finish** a unit just out of reach that one volley kills, only when the landing spot is
  safe and the local fight's level is at least `BLINK_FINISH_LEVEL`.

They never blink into fog, onto unpathable ground, or onto a cell whose ground-grid danger is above
`BLINK_DANGER_MAX` (`landing_ok`); fog also rules out a cliff they have no vision of.
`BLINK_RANGE` is measured (game data gives Blink a cast range of 500).
"""

import math
from typing import TYPE_CHECKING, Iterator, Optional

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit

from bot.constants import (
    BLINK_BACK_SHIELD_FRACTION,
    BLINK_DANGER_MAX,
    BLINK_FINISH_LEVEL,
    BLINK_IN_MIN_GAIN,
    BLINK_IN_MIN_STALKERS,
    BLINK_IN_PER_TARGET_S,
    BLINK_IN_WAVE_S,
    BLINK_RANGE,
)

if TYPE_CHECKING:
    from ares import AresBot

BLINK = AbilityId.EFFECT_BLINK_STALKER
# landing spots tried around an out-ranger, as angles (degrees) off the line from the unit to it
BLINK_IN_ANGLES: tuple[float, ...] = (0.0, 30.0, -30.0, 60.0, -60.0)


def blink_ready(unit: Unit) -> bool:
    return unit.type_id == UnitTypeId.STALKER and BLINK in unit.abilities


# -- pure rules ------------------------------------------------------------------------------------


def blink_back(shield_fraction: float, threatened: bool, threshold: float = BLINK_BACK_SHIELD_FRACTION) -> bool:
    """Blink away: shields at or below `threshold` of their maximum while threatened (pure)."""
    return threatened and shield_fraction <= threshold


def blink_in_points(
    unit_pos: Point2, target_pos: Point2, reach: float, blink_range: float = BLINK_RANGE,
    min_gain: float = BLINK_IN_MIN_GAIN,
) -> Iterator[Point2]:
    """Landing spots for blinking onto a target from `unit_pos`: `reach` - 1 from it (inside our
    weapon's reach), on the line from the unit and then turned by BLINK_IN_ANGLES. Only spots within
    `blink_range` of the unit, and only if the blink saves at least `min_gain` of walking (pure)."""
    dist = unit_pos.distance_to(target_pos)
    stand = max(reach - 1.0, 0.5)
    if dist - stand < min_gain:
        return
    base = math.atan2(unit_pos.y - target_pos.y, unit_pos.x - target_pos.x)
    for angle in BLINK_IN_ANGLES:
        a = base + math.radians(angle)
        p = Point2((target_pos.x + stand * math.cos(a), target_pos.y + stand * math.sin(a)))
        if unit_pos.distance_to(p) <= blink_range:
            yield p


def blink_finish(
    target_hp_shield: float, our_volley: float, landing_safe: bool, local_level: int,
    finish_level: int = BLINK_FINISH_LEVEL,
) -> bool:
    """Blink to finish: one volley kills the target, the landing is safe and the fight is won (pure)."""
    return our_volley >= target_hp_shield > 0 and landing_safe and local_level >= finish_level


def wave_allows(now: float, wave_start: Optional[float], ready_near: int) -> tuple[bool, bool]:
    """Blink-in waves on one out-ranger: (may blink, starts a new wave). A Stalker joins a wave that
    began within BLINK_IN_WAVE_S; a new wave needs BLINK_IN_PER_TARGET_S since the last one began and
    BLINK_IN_MIN_STALKERS ready nearby (pure)."""
    if wave_start is not None and now - wave_start <= BLINK_IN_WAVE_S:
        return True, False
    if (wave_start is None or now - wave_start >= BLINK_IN_PER_TARGET_S) and ready_near >= BLINK_IN_MIN_STALKERS:
        return True, True
    return False, False


# -- game checks -----------------------------------------------------------------------------------


def landing_ok(bot: "AresBot", point: Point2) -> bool:
    """A Blink landing spot: pathable, in vision (never into fog, nor up a cliff without vision),
    and with ground-grid danger at most BLINK_DANGER_MAX (1.0 is a cell nobody threatens)."""
    if not bot.in_pathing_grid(point) or not bot.is_visible(point):
        return False
    return bot.mediator.is_position_safe(
        grid=bot.mediator.get_ground_grid, position=point, weight_safety_limit=1.0 + BLINK_DANGER_MAX
    )


class BlinkState:
    """Per-game Blink bookkeeping, held by the army: blink-in waves (out-ranger tag -> start time),
    this step's Stalkers with Blink ready (for "together"), and blinks by kind for the game record."""

    def __init__(self) -> None:
        self.waves: dict[int, float] = {}
        self.ready_tags: set[int] = set()
        self.ready_positions: list[Point2] = []
        self.counts: dict[str, int] = {"back": 0, "in": 0, "finish": 0}

    def refresh(self, stalkers: list[Unit]) -> None:
        ready = [u for u in stalkers if blink_ready(u)]
        self.ready_tags = {u.tag for u in ready}
        self.ready_positions = [u.position for u in ready]

    def ready_near(self, point: Point2, radius: float) -> int:
        return sum(1 for p in self.ready_positions if p.distance_to(point) <= radius)

    def blink(self, unit: Unit, point: Point2, kind: str) -> None:
        unit(BLINK, point)
        self.counts[kind] += 1
        self.ready_tags.discard(unit.tag)
