"""Per-unit combat control (DESIGN.md §3 `army/micro.py`), built on ares's individual behaviors.

- `fight`: shoot the enemy in range with the lowest HP (units that can fight back first), and
  between shots step out of danger (`KeepUnitSafe`, i.e. ares's `StutterUnitBack`) if the unit
  out-ranges the closest threat; melee and short-range units attack-move.
- `retreat`: path home around danger (`PathUnitToTarget`); a ranged unit whose weapon is ready
  shoots a target already in range first.
- `move`: attack-move (FIGHT/HOLD) or move (REINFORCE, support units) to a point; python-sc2 drops
  an order identical to the unit's current one (§6 APM).
"""

from typing import TYPE_CHECKING, Optional, Sequence

from ares.behaviors.combat.individual import (
    KeepUnitSafe,
    PathUnitToTarget,
    ShootTargetInRange,
)
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit

from bot.army.engagement import WORKERS
from bot.constants import KITE_RANGE_MARGIN, MOVE_REISSUE_DIST

if TYPE_CHECKING:
    from ares import AresBot

# Units that step back between shots when they out-range the closest threat (§3 micro.py "stalker
# kite"); Blink is cut from v1 (§7)
KITERS: frozenset[UnitTypeId] = frozenset(
    {
        UnitTypeId.STALKER, UnitTypeId.ADEPT, UnitTypeId.IMMORTAL, UnitTypeId.COLOSSUS,
        UnitTypeId.SENTRY, UnitTypeId.PHOENIX, UnitTypeId.VOIDRAY, UnitTypeId.ORACLE,
    }
)


def _range_vs(unit: Unit, target: Unit) -> float:
    return unit.air_range if target.is_flying else unit.ground_range


def _can_hit(unit: Unit, target: Unit) -> bool:
    return unit.can_attack_air if target.is_flying else unit.can_attack_ground


def threats_to(unit: Unit, enemies: Sequence[Unit]) -> list[Unit]:
    """Enemies that can attack `unit`."""
    return [e for e in enemies if (e.can_attack_air if unit.is_flying else e.can_attack_ground)]


def fight(bot: "AresBot", unit: Unit, enemies: Sequence[Unit], fallback: Point2) -> None:
    """`enemies`: visible enemies near `unit`. With none it can hit, attack-move to `fallback`."""
    targets = [e for e in enemies if _can_hit(unit, e) and not e.is_memory]
    if not targets:
        move(unit, fallback, attack=True)
        return
    # units that can fight back before workers and structures (§4.6 priorities are M5's)
    fighters = [e for e in targets if not e.is_structure and e.type_id not in WORKERS and (e.can_attack_ground or e.can_attack_air)]
    for group in (fighters, targets):
        if group and ShootTargetInRange(unit=unit, targets=group).execute(bot, bot.config, bot.mediator):
            return
    if unit.type_id in KITERS and unit.weapon_cooldown > 0:
        threats = threats_to(unit, fighters)
        closest = min(threats, key=lambda e: e.distance_to(unit), default=None)
        if closest is not None:
            their_reach = (closest.air_range if unit.is_flying else closest.ground_range) + closest.radius + unit.radius
            our_reach = _range_vs(unit, closest) + closest.radius + unit.radius
            if our_reach > their_reach and closest.distance_to(unit) < our_reach + KITE_RANGE_MARGIN:
                grid = bot.mediator.get_air_grid if unit.is_flying else bot.mediator.get_ground_grid
                if KeepUnitSafe(unit=unit, grid=grid).execute(bot, bot.config, bot.mediator):
                    return
    target = min(fighters or targets, key=lambda e: e.distance_to(unit))
    move(unit, target.position, attack=True)


def retreat(bot: "AresBot", unit: Unit, enemies: Sequence[Unit], home: Point2, move_now: bool = True) -> None:
    """A ranged unit whose weapon is ready shoots a target in range; otherwise, on `move_now`
    (the path query is throttled), it paths home around danger."""
    if unit.type_id in KITERS and unit.weapon_cooldown == 0:
        targets = [e for e in enemies if _can_hit(unit, e) and not e.is_memory]
        if targets and ShootTargetInRange(unit=unit, targets=targets).execute(bot, bot.config, bot.mediator):
            return
    if not move_now:
        return
    grid = bot.mediator.get_air_grid if unit.is_flying else bot.mediator.get_ground_grid
    PathUnitToTarget(unit=unit, grid=grid, target=home, success_at_distance=2.0).execute(bot, bot.config, bot.mediator)


def move(unit: Unit, point: Point2, attack: bool) -> None:
    """Attack-move or move, skipping an order to (nearly) where the unit is already going."""
    current: Optional[Point2] = None
    if unit.orders:
        target = unit.orders[0].target
        if isinstance(target, Point2) or hasattr(target, "x"):
            current = Point2((target.x, target.y))
    if current is not None and current.distance_to(point) < MOVE_REISSUE_DIST and not unit.is_idle:
        return
    if unit.distance_to(point) < 1.0:
        return
    if attack:
        unit.attack(point)
    else:
        unit.move(point)


def keep_safe(bot: "AresBot", unit: Unit, point: Point2) -> None:
    """Support units (Observers): out of danger on the air grid, else to `point`."""
    grid = bot.mediator.get_air_grid if unit.is_flying else bot.mediator.get_ground_grid
    if KeepUnitSafe(unit=unit, grid=grid).execute(bot, bot.config, bot.mediator):
        return
    move(unit, point, attack=False)
