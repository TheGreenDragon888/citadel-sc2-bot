"""Per-unit combat control (DESIGN.md §3 `army/micro.py`), built on ares's individual behaviors.

- `fight`: shoot the enemy in range with the lowest HP (units that can fight back first), and
  between shots step out of danger (`KeepUnitSafe`, i.e. ares's `StutterUnitBack`) if the unit
  out-ranges the closest threat; melee and short-range units attack-move.
- `retreat`: path home around danger (`PathUnitToTarget`); a ranged unit whose weapon is ready
  shoots a target already in range first, only one that fights back and only when faster than
  every visible threat (M7 C3, `retreat_may_shoot`).
- `step_out` (M7 C1, §4.5.3 out-ranged rule): a unit not committed to a fight steps out of the
  reach of enemies that out-range it by OUTRANGED_MARGIN or that it can't hit (`out_rangers`).
- `move`: attack-move (FIGHT/HOLD) or move (REINFORCE, support units) to a point; python-sc2 drops
  an order identical to the unit's current one (§6 APM).
- `harass`: the §4.6 counterattack squad: on the way, shoot only what can fight back; inside the
  target base, what can fight back first, then workers, production and the townhall (user
  decision), and walk to the next of those when nothing is in range.
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

from bot.army.engagement import WORKERS, is_static_defense
from bot.army.ranges import can_hit, outranged, outranges, range_vs, reach  # noqa: F401 (re-exported)
from bot.constants import (
    COUNTER_BASE_RADIUS,
    COUNTER_THREAT_MARGIN,
    KITE_RANGE_MARGIN,
    MOVE_REISSUE_DIST,
    OUTRANGED_REACH_BUFFER,
)

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


_range_vs = range_vs
_can_hit = can_hit


def threats_to(unit: Unit, enemies: Sequence[Unit]) -> list[Unit]:
    """Enemies that can attack `unit`."""
    return [e for e in enemies if (e.can_attack_air if unit.is_flying else e.can_attack_ground)]


def _fights_back(e: Unit) -> bool:
    """An enemy that can fight: a unit that can attack (not a worker), or finished static defense."""
    return (
        e.type_id not in WORKERS and (e.can_attack_ground or e.can_attack_air)
        and (not e.is_structure or is_static_defense(e))
    )


def out_rangers(unit: Unit, enemies: Sequence[Unit]) -> list[Unit]:
    """The enemies that out-range `unit` by OUTRANGED_MARGIN, or that it can't hit, and have it
    within their reach plus OUTRANGED_REACH_BUFFER (weapon ranges from game data)."""
    return [
        e for e in enemies
        if outranges(e, unit) and e.distance_to(unit) <= reach(e, unit) + OUTRANGED_REACH_BUFFER
    ]


def step_out(bot: "AresBot", unit: Unit) -> bool:
    """M7 C1: a unit holding, moving or retreating in an out-ranger's reach (`out_rangers`) steps
    to the nearest safe cell of the influence grid (ares `KeepUnitSafe`; with none within 11, the
    least dangerous one, VERIFY_NOTES "M7 findings"). True if it acted."""
    grid = bot.mediator.get_air_grid if unit.is_flying else bot.mediator.get_ground_grid
    return KeepUnitSafe(unit=unit, grid=grid).execute(bot, bot.config, bot.mediator)


def retreat_may_shoot(own_speed: float, threat_speeds: Sequence[float], target_fights_back: bool) -> bool:
    """M7 C3 (§4.5.3): a retreating unit shoots only an enemy that fights back, and only when it is
    faster than every visible threat that can hit it (pure)."""
    return target_fights_back and all(own_speed > speed for speed in threat_speeds)


def fight(bot: "AresBot", unit: Unit, enemies: Sequence[Unit], fallback: Point2) -> None:
    """`enemies`: visible enemies near `unit`. With none it can hit, attack-move to `fallback`."""
    targets = [e for e in enemies if _can_hit(unit, e) and not e.is_memory]
    if not targets:
        move(unit, fallback, attack=True)
        return
    # what can fight back (units, and finished static defense) before workers and other structures
    # (§4.6 priorities are M5's)
    fighters = [e for e in targets if _fights_back(e)]
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


def harass(
    bot: "AresBot", unit: Unit, enemies: Sequence[Unit], base: Point2, goals: Sequence[Sequence[Unit]], own_tick: bool
) -> None:
    """`enemies`: visible enemies near `unit`; `goals`: visible enemies at the target `base` in §4.6
    order (workers, production, townhalls). New orders go out on the unit's own tick or when idle."""
    targets = [e for e in enemies if _can_hit(unit, e) and not e.is_memory]
    fighters = [e for e in targets if _fights_back(e)]
    at_base = unit.distance_to(base) <= COUNTER_BASE_RADIUS
    groups: list[Sequence[Unit]] = [fighters]
    if at_base:
        tags = [{e.tag for e in g} for g in goals]
        groups += [[e for e in targets if e.tag in g] for g in tags] + [targets]
    for group in groups:
        if group and ShootTargetInRange(unit=unit, targets=group).execute(bot, bot.config, bot.mediator):
            return
    if not own_tick and not unit.is_idle:
        return
    # fight back first: a defender that can reach us
    threats = [
        e for e in fighters
        if e.distance_to(unit)
        <= (e.air_range if unit.is_flying else e.ground_range) + e.radius + unit.radius + COUNTER_THREAT_MARGIN
    ]
    for group in [threats] + [list(g) for g in goals]:
        reachable = [e for e in group if _can_hit(unit, e)]
        if reachable:
            goal = min(reachable, key=lambda e: e.distance_to(unit))
            if unit.order_target != goal.tag:
                unit.attack(goal)
            return
    move(unit, base, attack=at_base)


def retreat(bot: "AresBot", unit: Unit, enemies: Sequence[Unit], home: Point2, move_now: bool = True) -> None:
    """A ranged unit whose weapon is ready shoots a target in range that fights back, if it is
    faster than every visible threat (M7 C3; game-data speeds without upgrades on both sides);
    otherwise, on `move_now` (the path query is throttled), it paths home around danger."""
    if unit.type_id in KITERS and unit.weapon_cooldown == 0:
        targets = [e for e in enemies if _can_hit(unit, e) and not e.is_memory and _fights_back(e)]
        speeds = [e.movement_speed for e in threats_to(unit, enemies) if not e.is_structure and not e.is_memory]
        if (
            targets
            and retreat_may_shoot(unit.movement_speed, speeds, bool(targets))
            and ShootTargetInRange(unit=unit, targets=targets).execute(bot, bot.config, bot.mediator)
        ):
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
