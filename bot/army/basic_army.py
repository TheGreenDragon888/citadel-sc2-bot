"""M1 scaffolding: one army that defends, gathers, attacks and hunts structures.

Temporary so M1 games can be won; M4 replaces it with squads and EngagementResult gates
(DESIGN.md §4.5.2). No combat sim, no micro: attack-move only.

- Defend: visible enemy army units near one of our townhalls pull the whole army there.
- Gather: otherwise the army waits in front of our forward base.
- Attack: at `ARMY_ATTACK_SUPPLY` supply used (not within `ARMY_RELAUNCH_WAIT_S` of a retreat,
  unless at `ARMY_ALWAYS_ATTACK_SUPPLY`), attack-move to the known enemy structure nearest the
  army; with none known, visit the enemy start, then enemy expansions, every other expansion
  and a grid over the map (the built-in Terran AI floats buildings away when losing).
- Retreat: when the army's supply drops below `ARMY_RETREAT_FRACTION` of its supply at launch.
"""

from typing import TYPE_CHECKING, Optional

from loguru import logger
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit

from bot.constants import (
    ARMY_ALWAYS_ATTACK_SUPPLY,
    ARMY_ATTACK_SUPPLY,
    ARMY_DEFEND_RADIUS,
    ARMY_RALLY_OFFSET,
    ARMY_RELAUNCH_WAIT_S,
    ARMY_RETREAT_FRACTION,
    HUNT_GRID_STEP,
    HUNT_VISIT_RADIUS,
    ORDER_REFRESH_S,
)

if TYPE_CHECKING:
    from ares import AresBot

# enemy units that never pull the army home
HARMLESS: frozenset[UnitTypeId] = frozenset(
    {
        UnitTypeId.OVERLORD,
        UnitTypeId.OVERLORDTRANSPORT,
        UnitTypeId.OVERSEER,
        UnitTypeId.OBSERVER,
        UnitTypeId.CHANGELING,
        UnitTypeId.CHANGELINGMARINE,
        UnitTypeId.CHANGELINGMARINESHIELD,
        UnitTypeId.CHANGELINGZEALOT,
        UnitTypeId.CHANGELINGZERGLING,
        UnitTypeId.CHANGELINGZERGLINGWINGS,
        UnitTypeId.LARVA,
        UnitTypeId.EGG,
    }
)
SUPPORT: frozenset[UnitTypeId] = frozenset({UnitTypeId.OBSERVER})


class BasicArmy:
    GATHER = "gather"
    ATTACK = "attack"

    def __init__(self, bot: "AresBot"):
        self.bot = bot
        self.state: str = self.GATHER
        self.launch_supply: float = 0.0
        self.retreated_at: float = -ARMY_RELAUNCH_WAIT_S
        self.excluded_tags: set[int] = set()  # units other modules control (wall holder)
        # §4.2 DefensePlan.army_hold_point: while set, the army waits here instead of the rally
        # point and doesn't attack
        self.hold_point: Optional[Point2] = None
        self._hunt_points: list[Point2] = []
        self._visited: set[Point2] = set()
        self._orders: dict[int, tuple[Point2, float]] = {}  # tag -> (target, time given)

    def step(self) -> None:
        bot = self.bot
        units = [u for u in bot.mediator.get_own_army if u.tag not in self.excluded_tags]
        army = [u for u in units if u.type_id not in SUPPORT]
        support = [u for u in units if u.type_id in SUPPORT]
        if not army:
            return
        supply = sum(bot.calculate_supply_cost(u.type_id) for u in army)
        center = Point2.center([u.position for u in army])

        threat = self._home_threat()
        if threat is not None:
            target = threat
        elif self.hold_point is not None:
            if self.state == self.ATTACK:
                self.state = self.GATHER
                logger.info(f"ARMY recalled to the defense hold point at {bot.time_formatted}")
            target = self.hold_point
        else:
            self._update_state(supply)
            target = self._attack_target(center, army) if self.state == self.ATTACK else self._rally_point()

        for unit in army:
            self._a_move(unit, target)
        for unit in support:
            self._move(unit, center)

    def _update_state(self, supply: float) -> None:
        bot = self.bot
        now = bot.time
        if self.state == self.GATHER:
            waited = now - self.retreated_at >= ARMY_RELAUNCH_WAIT_S
            if (bot.supply_used >= ARMY_ATTACK_SUPPLY and waited) or bot.supply_used >= ARMY_ALWAYS_ATTACK_SUPPLY:
                self.state = self.ATTACK
                self.launch_supply = supply
                logger.info(f"ARMY attack at {bot.time_formatted}: army supply {supply:g}, supply used {bot.supply_used:g}")
        elif supply < ARMY_RETREAT_FRACTION * self.launch_supply and bot.supply_used < ARMY_ALWAYS_ATTACK_SUPPLY:
            self.state = self.GATHER
            self.retreated_at = now
            logger.info(f"ARMY retreat at {bot.time_formatted}: army supply {supply:g} of {self.launch_supply:g}")

    def _home_threat(self) -> Optional[Point2]:
        """Position of the visible enemy army unit nearest one of our townhalls, if any is
        within `ARMY_DEFEND_RADIUS`. Workers are left to M2's worker defence."""
        bot = self.bot
        best: Optional[tuple[float, Point2]] = None
        for enemy in bot.enemy_units:
            if (
                enemy.type_id in HARMLESS
                or enemy.is_structure
                or enemy.type_id in (UnitTypeId.PROBE, UnitTypeId.SCV, UnitTypeId.DRONE)
                or getattr(enemy, "is_memory", False)
            ):
                continue
            for th in bot.townhalls:
                d = enemy.distance_to(th)
                if d < ARMY_DEFEND_RADIUS and (best is None or d < best[0]):
                    best = (d, enemy.position)
        return best[1] if best else None

    def _rally_point(self) -> Point2:
        bot = self.bot
        bases = bot.ready_townhalls or bot.townhalls
        if not bases:
            return bot.start_location
        front = max(bases, key=lambda th: th.distance_to(bot.start_location))
        return front.position.towards(bot.enemy_start_locations[0], ARMY_RALLY_OFFSET)

    def _attack_target(self, center: Point2, army: list[Unit]) -> Point2:
        bot = self.bot
        if bot.enemy_structures:
            return bot.enemy_structures.closest_to(center).position
        if not self._hunt_points:
            self._hunt_points = self._build_hunt_points()
        for point in self._hunt_points:
            if point in self._visited:
                continue
            if any(u.distance_to(point) < HUNT_VISIT_RADIUS for u in army):
                self._visited.add(point)
                continue
            return point
        self._visited.clear()  # every point seen once: start the sweep again
        return self._hunt_points[0]

    def _build_hunt_points(self) -> list[Point2]:
        """Enemy start, enemy-side expansions, all other expansions, then a map grid."""
        bot = self.bot
        points: list[Point2] = [bot.enemy_start_locations[0]]
        points += [p for p, _ in bot.mediator.get_enemy_expansions]
        points += sorted(bot.expansion_locations_list, key=lambda p: p.distance_to(bot.enemy_start_locations[0]))
        area = bot.game_info.playable_area
        x = area.x + HUNT_GRID_STEP / 2
        while x < area.x + area.width:
            y = area.y + HUNT_GRID_STEP / 2
            while y < area.y + area.height:
                points.append(Point2((x, y)))
                y += HUNT_GRID_STEP
            x += HUNT_GRID_STEP
        unique: list[Point2] = []
        for p in points:
            if all(p.distance_to(q) > HUNT_VISIT_RADIUS for q in unique):
                unique.append(p)
        return unique

    def _a_move(self, unit: Unit, target: Point2) -> None:
        """Attack-move, re-issued only for a new target or an idle unit (§6: avoid order spam)."""
        last = self._orders.get(unit.tag)
        now = self.bot.time
        if last is not None and last[0].distance_to(target) < 3 and (
            not unit.is_idle or now - last[1] < ORDER_REFRESH_S
        ):
            return
        unit.attack(target)
        self._orders[unit.tag] = (target, now)

    def _move(self, unit: Unit, target: Point2) -> None:
        last = self._orders.get(unit.tag)
        now = self.bot.time
        if last is not None and last[0].distance_to(target) < 3 and now - last[1] < ORDER_REFRESH_S:
            return
        unit.move(target)
        self._orders[unit.tag] = (target, now)

    def forget(self, tag: int) -> None:
        self._orders.pop(tag, None)
