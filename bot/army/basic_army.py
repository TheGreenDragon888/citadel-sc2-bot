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

from typing import TYPE_CHECKING, Optional, Union

from loguru import logger
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit

from bot.constants import (
    ARMY_ALWAYS_ATTACK_SUPPLY,
    ARMY_ATTACK_SUPPLY,
    ARMY_CLEAR_STRUCTURES_SUPPLY,
    ARMY_DEFEND_RADIUS,
    ARMY_DIRECT_ATTACK_MARGIN,
    ARMY_RECALL_FRACTION,
    ARMY_STATUS_EVERY_S,
    ARMY_SUPPLY_PER_CANNON,
    ARMY_WORKER_THREAT_RADIUS,
    MAIN_RADIUS,
    SAME_LEVEL_Z,
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
WORKER_TYPES: frozenset[UnitTypeId] = frozenset({UnitTypeId.PROBE, UnitTypeId.SCV, UnitTypeId.DRONE})


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
        # point (the supply gates below still launch attacks); with `leash`, it engages only
        # enemies within it of the hold point or inside the main
        self.hold_point: Optional[Point2] = None
        self.leash: Optional[float] = None
        self._hunt_points: list[Point2] = []
        self._visited: set[Point2] = set()
        self._orders: dict[int, tuple[Point2, float]] = {}  # tag -> (target, time given)
        self._last_status: float = 0.0

    def step(self) -> None:
        bot = self.bot
        # ares's own-army cache also holds workers (its UNITS_TO_IGNORE is empty,
        # ares-sc2/src/ares/consts.py:908), so leave them out here
        units = [
            u for u in bot.mediator.get_own_army
            if u.type_id not in WORKER_TYPES and u.tag not in self.excluded_tags
        ]
        army = [u for u in units if u.type_id not in SUPPORT]
        support = [u for u in units if u.type_id in SUPPORT]
        if not army:
            return
        supply = sum(bot.calculate_supply_cost(u.type_id) for u in army)
        center = Point2.center([u.position for u in army])

        threat = self._home_threat(supply, attacking=self.state == self.ATTACK)
        if threat is not None:
            target = threat
        else:
            self._update_state(supply)
            if self.state == self.ATTACK:
                target = self._attack_target(center, army)
            else:
                target = self.hold_point if self.hold_point is not None else self._rally_point()

        for unit in army:
            self._engage(unit, target)
        target = target.position if isinstance(target, Unit) else target
        for unit in support:
            self._move(unit, center)
        if bot.time - self._last_status >= ARMY_STATUS_EVERY_S:
            self._last_status = bot.time
            idle = sum(1 for u in army if u.is_idle)
            logger.info(
                f"ARMY {bot.time_formatted} state={self.state} supply={supply:g} units={len(army)} "
                f"idle={idle} center={center.rounded} target={target.rounded}"
                + (" (home threat)" if threat is not None else "")
            )

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

    def _home_threat(self, army_supply: float, attacking: bool = False) -> Optional[Unit]:
        """Position of the visible enemy nearest one of our bases, if any is within
        `ARMY_DEFEND_RADIUS`: army units; workers only within `ARMY_WORKER_THREAT_RADIUS`
        (a rush is worker_defense.py's job, a lone worker left behind is the army's); enemy
        structures (proxy Pylons, Cannons) once the army has `ARMY_CLEAR_STRUCTURES_SUPPLY`, and
        `ARMY_SUPPLY_PER_CANNON` per finished Cannon near our bases.
        With a leash, only enemies near the hold point or inside the main. While attacking,
        only enemy army units with at least `ARMY_RECALL_FRACTION` of our army supply call the
        army back (a structure, worker or trickle near home would flip its target back and
        forth)."""
        bot = self.bot
        best: Optional[tuple[float, Unit]] = None
        start_z = bot.get_terrain_z_height(bot.start_location)
        # our townhalls, and the natural spot even before it has one (it is ours to hold)
        homes = [th.position for th in bot.townhalls] + [bot.mediator.get_own_nat]
        candidates = list(bot.enemy_units)
        cannons = [
            s for s in bot.enemy_structures
            if s.type_id == UnitTypeId.PHOTONCANNON and s.is_ready
            and any(s.distance_to(h) < ARMY_DEFEND_RADIUS for h in homes)
        ]
        strong_enough = army_supply >= max(ARMY_CLEAR_STRUCTURES_SUPPLY, ARMY_SUPPLY_PER_CANNON * len(cannons))
        if not attacking and strong_enough:
            candidates += [s for s in bot.enemy_structures if s.is_visible]
        for enemy in candidates:
            if enemy.type_id in HARMLESS or getattr(enemy, "is_memory", False):
                continue
            is_worker = enemy.type_id in WORKER_TYPES
            if attacking and is_worker:
                continue
            # a worker sheltering among finished Cannons isn't worth walking into them for
            if is_worker and not strong_enough and any(
                enemy.distance_to(c) <= c.ground_range + c.radius + 1 for c in cannons
            ):
                continue
            if self.hold_point is not None and self.leash is not None:
                inside = (
                    enemy.distance_to(bot.start_location) <= MAIN_RADIUS
                    and abs(bot.get_terrain_z_height(enemy) - start_z) < SAME_LEVEL_Z
                )
                if not inside and enemy.distance_to(self.hold_point) > self.leash:
                    continue
            radius = ARMY_WORKER_THREAT_RADIUS if is_worker else ARMY_DEFEND_RADIUS
            for home in homes:
                d = enemy.distance_to(home)
                if d < radius and (best is None or d < best[0]):
                    best = (d, enemy)
        if best is not None and attacking:
            # a trickle of units at home is left to new production; a real attack recalls
            near = [
                e for e in bot.enemy_units
                if not e.is_memory and e.type_id not in HARMLESS and e.type_id not in WORKER_TYPES
                and any(e.distance_to(h) < ARMY_DEFEND_RADIUS for h in homes)
            ]
            if sum(bot.calculate_supply_cost(e.type_id) for e in near) < ARMY_RECALL_FRACTION * army_supply:
                return None
        return best[1] if best else None

    def _rally_point(self) -> Point2:
        bot = self.bot
        bases = bot.ready_townhalls or bot.townhalls
        if not bases:
            return bot.start_location
        front = max(bases, key=lambda th: th.distance_to(bot.start_location))
        return front.position.towards(bot.enemy_start_locations[0], ARMY_RALLY_OFFSET)

    def _attack_target(self, center: Point2, army: list[Unit]) -> Union[Unit, Point2]:
        """The visible enemy structure nearest the army, else the nearest remembered one's
        position, else the next structure-hunt point."""
        bot = self.bot
        visible = bot.enemy_structures.filter(lambda s: s.is_visible)
        if visible:
            return visible.closest_to(center)
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

    def _engage(self, unit: Unit, target: Union[Unit, Point2]) -> None:
        """Attack-move toward the target; next to a visible enemy structure, attack it directly.
        An attack-move to a point inside a cluster of structures stops short of it with nothing
        in range (a Cannon cluster at our natural held a whole army idle in a test game)."""
        if isinstance(target, Unit):
            reach = unit.ground_range + unit.radius + target.radius + ARMY_DIRECT_ATTACK_MARGIN
            if target.is_structure and unit.distance_to(target) <= reach:
                if unit.order_target != target.tag:
                    unit.attack(target)
                    self._orders[unit.tag] = (target.position, self.bot.time)
                return
            target = target.position
        self._a_move(unit, target)

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
