"""The army commander (DESIGN.md §3 `army/`, §4.5.2): squads, home defense, the main attack.

Replaces M1's BasicArmy. Every ARMY_EVERY_STEPS steps (`step`) it refreshes squad roles and each
unit's intent; every DECISION_EVERY_STEPS steps it also makes the decisions below; every step
(`micro`) it controls the units that have a visible enemy within MICRO_RADIUS.

Home defense (DEFEND squad; Defense > Main attack, §3):
- A home threat is the enemy nearest one of our bases (townhalls and the natural spot) within
  ARMY_DEFEND_RADIUS: army units; lone workers within ARMY_WORKER_THREAT_RADIUS; enemy structures
  (proxy Pylons, Cannons) once the squad can take them (M2 rules, now on the simulator). With the
  defense plan's leash, only enemies near its hold point or inside our main.
- The squad fights it if the enemy is inside our main or at the defensive position (nowhere to
  fall back to), at >= DEFEND_ENGAGE when the fight is within a ready Shield Battery's reach
  (§4.5.2: batteries are not simulated), or at >= ATTACK_CONTINUE elsewhere; otherwise it holds
  the defensive position. Our Cannons near the fight are on our side; we are the defender.
- While the ATTACK squad is out, a threat the DEFEND squad can't hold recalls it if the enemies
  are worth ARMY_RECALL_FRACTION of it.

Main attack (ATTACK squad, bot/army/attack_decision.py): launched from the DEFEND squad, then
evaluated at its target against the §4.5.2 inputs (bot/army/engagement.py). Targets: the known
enemy townhall nearest the squad (so its nearest expansion, then the next, then the main), then
other enemy structures, then a structure hunt. The squad regroups when stragglers hold
REGROUP_FRACTION of its supply. After a retreat it falls back to the defensive position (the
defense plan's hold point, else our newest base) and the DEFEND squad re-maxes. New units there
go out as REINFORCE groups of at least REINFORCE_MIN_SUPPLY and join the ATTACK squad near it.

One Observer stays with the army from OBSERVER_WITH_ARMY_FROM_S (§4.3), with the ATTACK squad
while it is out.
"""

from typing import TYPE_CHECKING, Optional

from ares.consts import TOWNHALL_TYPES, EngagementResult, UnitRole, UnitTreeQueryType
from loguru import logger
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit

from bot.army import micro
from bot.army.attack_decision import ATTACK, AttackDecision, Decision
from bot.army.engagement import (
    ENEMY_DEFENDS,
    WE_DEFEND,
    WORKERS,
    Engagement,
    is_fighter,
)
from bot.army.squads import Role, Squads
from bot.constants import (
    ARMY_CLEAR_STRUCTURES_SUPPLY,
    ARMY_DEFEND_RADIUS,
    ARMY_EVERY_STEPS,
    ARMY_HOLD_LEASH,
    ARMY_RALLY_OFFSET,
    ARMY_RECALL_FRACTION,
    ARMY_STATUS_EVERY_S,
    ARMY_WORKER_THREAT_RADIUS,
    ATTACK_CONTINUE,
    ATTACK_SQUAD_RADIUS,
    ATTACK_START_SUPPLY,
    BATTERY_COVER_RADIUS,
    CLEAR_STATIC_LEVEL,
    DECISION_EVERY_STEPS,
    DEFEND_ENGAGE,
    ENGAGE_STATIC_RADIUS,
    HOLD_ENGAGE_RADIUS,
    HOLD_RADIUS,
    HUNT_GRID_STEP,
    HUNT_VISIT_RADIUS,
    MAIN_RADIUS,
    MICRO_RADIUS,
    OBSERVER_WITH_ARMY_FROM_S,
    REGROUP_FRACTION,
    REINFORCE_JOIN_RADIUS,
    REINFORCE_MIN_SUPPLY,
    RETREAT_AT,
    RETREAT_DONE_RADIUS,
    SAME_LEVEL_Z,
)

if TYPE_CHECKING:
    from ares import AresBot

    from bot.army.endgame import EndGame

# enemy units that never make a home threat
HARMLESS: frozenset[UnitTypeId] = frozenset(
    {
        UnitTypeId.OVERLORD, UnitTypeId.OVERLORDTRANSPORT, UnitTypeId.OVERSEER,
        UnitTypeId.OBSERVER, UnitTypeId.CHANGELING, UnitTypeId.CHANGELINGMARINE,
        UnitTypeId.CHANGELINGMARINESHIELD, UnitTypeId.CHANGELINGZEALOT,
        UnitTypeId.CHANGELINGZERGLING, UnitTypeId.CHANGELINGZERGLINGWINGS, UnitTypeId.LARVA,
        UnitTypeId.EGG,
    }
)
SUPPORT: frozenset[UnitTypeId] = frozenset({UnitTypeId.OBSERVER, UnitTypeId.OBSERVERSIEGEMODE})
# enemies micro never shoots at
NOT_TARGETS: frozenset[UnitTypeId] = frozenset(
    {
        UnitTypeId.LARVA, UnitTypeId.EGG, UnitTypeId.CHANGELING, UnitTypeId.CHANGELINGMARINE,
        UnitTypeId.CHANGELINGMARINESHIELD, UnitTypeId.CHANGELINGZEALOT, UnitTypeId.CHANGELINGZERGLING,
        UnitTypeId.CHANGELINGZERGLINGWINGS, UnitTypeId.ADEPTPHASESHIFT,
    }
)

# unit intents
FIGHT, HOLD, RETREAT, MOVE = "fight", "hold", "retreat", "move"


class Army:
    def __init__(self, bot: "AresBot", endgame: Optional["EndGame"] = None):
        self.bot = bot
        self.endgame = endgame  # §4.7
        self.engagement = Engagement(bot)
        self.decision = AttackDecision()
        self.squads = Squads(bot)
        # set by CitadelBot each army tick
        self.held_tags: set[int] = set()  # the wall-gap holder (other modules control it)
        self.scout_tags: set[int] = set()  # the scout planner's units
        # §4.2 DefensePlan.army_hold_point / army_leash: the DEFEND squad waits here instead of
        # at the rally point; with the leash it fights only enemies near it or inside the main
        self.hold_point: Optional[Point2] = None
        self.leash: Optional[float] = None
        self.intents: dict[int, tuple[str, Point2]] = {}
        self.anchor: Point2 = bot.start_location
        self.observer_tag: Optional[int] = None
        # home defense, refreshed each decision tick
        self.defend_target: Optional[Point2] = None
        self.threat: Optional[Point2] = None
        self.home_level: int = -1  # the DEFEND squad's level against the home threat (-1: not simulated)
        self._defend_state: str = ""
        # main attack
        self.target: Optional[Point2] = None
        self._target_tag: Optional[int] = None
        self.attack_center: Optional[Point2] = None
        self.last_level: Optional[int] = None
        self.decisions: list[tuple[float, str, int, str]] = []  # (time, action, level, reason) for §8
        self._hunt_points: list[Point2] = []
        self._visited: set[Point2] = set()
        self._last_status: float = 0.0
        self._step: int = 0

    # -- interface -----------------------------------------------------------------------------

    @property
    def busy_tags(self) -> set[int]:
        """Units the scout planner must not take: the ATTACK and REINFORCE squads and the
        army's Observer."""
        tags = self.squads.tags(Role.ATTACK) | self.squads.tags(Role.REINFORCE)
        return tags | ({self.observer_tag} if self.observer_tag is not None else set())

    def forget(self, tag: int) -> None:
        self.squads.forget(tag)
        self.intents.pop(tag, None)
        if tag == self.observer_tag:
            self.observer_tag = None

    def step(self, iteration: int) -> None:
        bot = self.bot
        self._step = iteration
        army = [
            u for u in bot.mediator.get_own_army
            if u.type_id not in WORKERS and not u.is_hallucination and not u.is_structure
            and u.build_progress == 1  # not while warping in
        ]
        self.squads.update(army, self.scout_tags, self.held_tags)
        self.anchor = self.hold_point if self.hold_point is not None else self._rally_point()
        self._claim_observer()
        if iteration % DECISION_EVERY_STEPS == 0:
            self._decide()
        self._set_intents()
        self._status()

    # -- decisions (every DECISION_EVERY_STEPS) --------------------------------------------------

    def _fighters(self, role: Role) -> list[Unit]:
        return [u for u in self.squads.units(role) if is_fighter(u)]

    def _supply(self, units: list[Unit]) -> float:
        return sum(self.bot.calculate_supply_cost(u.type_id) for u in units)

    def _value_ratio(self) -> float:
        """Our army value / the enemy's remembered army value (ares's army cache: every enemy
        unit seen and not known dead, §4.7)."""
        ours = self.engagement.value(u for u in self.bot.units if is_fighter(u))
        theirs = self.engagement.value(u for u in self.bot.mediator.get_cached_enemy_army if is_fighter(u))
        return ours / theirs if theirs > 0 else float("inf")

    def _decide(self) -> None:
        bot = self.bot
        now = bot.time
        defenders = self._fighters(Role.DEFEND)
        self._home_defense(defenders)
        attackers = self._fighters(Role.ATTACK)
        if self.decision.state == ATTACK and self.threat is not None and self.defend_target is None:
            near = self.engagement.enemies_near([self.threat])
            value = self.engagement.value(attackers)
            if value > 0 and self.engagement.value(near) >= ARMY_RECALL_FRACTION * value:
                self.decision.recall(now)
                self._log(
                    Decision(self.decision.state, "recall", f"home threat at {self.threat.rounded} the DEFEND squad can't hold"),
                    self.home_level,
                )
                self._retreat_attack_squad()
                return
        if self.decision.state == ATTACK:
            self._evaluate_attack(attackers)
            self._reinforce(defenders)
        elif self.threat is None and bot.supply_used >= ATTACK_START_SUPPLY and defenders:
            self._evaluate_launch(defenders)

    def _evaluate_launch(self, candidates: list[Unit]) -> None:
        bot = self.bot
        center = Point2.center([u.position for u in candidates])
        target = self._attack_target(center, candidates)
        enemy = self.engagement.attack_inputs(center, target)
        level = self.engagement.level(candidates, enemy, ENEMY_DEFENDS)
        self.last_level = level
        decision = self.decision.evaluate(bot.time, level, bot.supply_used, self.engagement.value(candidates), self._value_ratio())
        if decision.action == "launch":
            self.squads.assign([u.tag for u in candidates], Role.ATTACK)
            self.target = target
            for u in candidates:
                self.intents.pop(u.tag, None)
            self._log(decision, level, f"{len(candidates)} units, {self._supply(candidates):g} supply -> {target.rounded}")

    def _evaluate_attack(self, attackers: list[Unit]) -> None:
        bot = self.bot
        center = self._main_group_center(attackers)
        self.attack_center = center
        if center is None:
            level = 0
            enemy_value = 0.0
            target = self.target
        else:
            target = self._attack_target(center, attackers)
            enemy = self.engagement.attack_inputs(center, target)
            level = self.engagement.level(attackers, enemy, ENEMY_DEFENDS)
            enemy_value = self.engagement.value(enemy)
        self.target = target
        self.last_level = level
        decision = self.decision.evaluate(
            bot.time, level, bot.supply_used, self.engagement.value(attackers), self._value_ratio()
        )
        if decision.action == "retreat":
            self._log(decision, level, f"{len(attackers)} units left, enemy value near {enemy_value:.0f}")
            self._retreat_attack_squad()

    def _retreat_attack_squad(self) -> None:
        tags = self.squads.tags(Role.ATTACK) | self.squads.tags(Role.REINFORCE)
        self.squads.assign(tags, Role.DEFEND)
        for tag in tags:
            self.intents[tag] = (RETREAT, self.anchor)
        self._target_tag = None

    def _reinforce(self, defenders: list[Unit]) -> None:
        """§4.5.2: new units go out in groups of >= REINFORCE_MIN_SUPPLY, never one by one."""
        if self.attack_center is None:
            return
        # groups on their way: join the squad near it, or come back from a fight they'd lose
        group = self._fighters(Role.REINFORCE)
        if group:
            center = Point2.center([u.position for u in group])
            if center.distance_to(self.attack_center) <= REINFORCE_JOIN_RADIUS:
                self.squads.assign([u.tag for u in group], Role.ATTACK)
                self.decision.add_value(self.engagement.value(group))
                logger.info(f"ARMY reinforcements joined at {self.bot.time_formatted}: {len(group)} units, {self._supply(group):g} supply")
            else:
                near = self.engagement.enemies_near([center], MICRO_RADIUS)
                if near and self.engagement.level(group, near, ENEMY_DEFENDS) <= RETREAT_AT:
                    tags = [u.tag for u in group]
                    self.squads.assign(tags, Role.DEFEND)
                    for tag in tags:
                        self.intents[tag] = (RETREAT, self.anchor)
                    logger.info(f"ARMY reinforcements turned back at {self.bot.time_formatted}: enemies on the way")
            return
        if self.threat is not None:
            return
        ready = [u for u in defenders if u.distance_to(self.anchor) <= HOLD_ENGAGE_RADIUS]
        if self._supply(ready) >= REINFORCE_MIN_SUPPLY:
            self.squads.assign([u.tag for u in ready], Role.REINFORCE)
            for u in ready:
                self.intents.pop(u.tag, None)
            logger.info(f"ARMY reinforcements out at {self.bot.time_formatted}: {len(ready)} units, {self._supply(ready):g} supply")

    # -- home defense ----------------------------------------------------------------------------

    def _homes(self) -> list[Point2]:
        # our townhalls, and the natural spot even before it has one (it is ours to hold)
        return [th.position for th in self.bot.townhalls] + [self.bot.mediator.get_own_nat]

    def _inside_main(self, point: Point2) -> bool:
        bot = self.bot
        return (
            point.distance_to(bot.start_location) <= MAIN_RADIUS
            and abs(bot.get_terrain_z_height(point) - bot.get_terrain_z_height(bot.start_location)) < SAME_LEVEL_Z
        )

    def _own_cannons_near(self, point: Point2) -> list[Unit]:
        return [
            s for s in self.bot.structures
            if s.type_id == UnitTypeId.PHOTONCANNON and s.is_ready and s.is_powered
            and s.distance_to(point) <= ENGAGE_STATIC_RADIUS
        ]

    def _covered_by_battery(self, point: Point2) -> bool:
        return any(
            b.is_ready and b.is_powered and b.distance_to(point) <= BATTERY_COVER_RADIUS
            for b in self.bot.structures if b.type_id == UnitTypeId.SHIELDBATTERY
        )

    def _home_defense(self, defenders: list[Unit]) -> None:
        """Sets `threat` (the home threat's position, if any) and `defend_target` (where the
        DEFEND squad fights, or None to hold the defensive position)."""
        found = self._home_threat(defenders)
        self.threat = found.position if found is not None else None
        self.defend_target = None
        self.home_level = -1
        state = "none"
        if found is not None:
            if found.is_structure or found.type_id in WORKERS:
                # static defense covering the target, and the units around it, fight for it
                # (M4 cannon_rush Ultralove: the Cannons around a Pylon near our base were just
                # outside the "near our bases" radius, and the squad died walking in)
                guard = self.engagement.static_defense_near(found.position) + self.engagement.enemies_near([found.position])
                guard = [g for g in guard if g.tag != found.tag]
                level = self.engagement.level(defenders, guard, ENEMY_DEFENDS) if guard else EngagementResult.VICTORY_EMPHATIC
                self.home_level = int(level)
                if level >= CLEAR_STATIC_LEVEL:
                    self.defend_target, state = found.position, f"clearing {found.type_id.name} (level {level})"
                else:
                    state = f"hold, {found.type_id.name} covered (level {level} < {CLEAR_STATIC_LEVEL})"
            elif self._inside_main(found.position) or found.distance_to(self.anchor) <= ARMY_HOLD_LEASH:
                self.defend_target, state = found.position, "last stand (main or defensive position)"
            else:
                enemy = self.engagement.enemies_near([found.position]) + self.engagement.static_defense_near(found.position)
                level = self.engagement.level(defenders + self._own_cannons_near(found.position), enemy, WE_DEFEND)
                self.home_level = level
                covered = self._covered_by_battery(found.position)
                needed = DEFEND_ENGAGE if covered else ATTACK_CONTINUE
                if level >= needed:
                    self.defend_target = found.position
                    state = f"engage (level {level} >= {needed}{', batteries' if covered else ''})"
                else:
                    state = f"hold (level {level} < {needed}{', batteries' if covered else ''})"
        if state != self._defend_state:
            self._defend_state = state
            if found is not None or self.decision.state != ATTACK:
                logger.info(
                    f"DEFEND {self.bot.time_formatted}: {state}"
                    + (f" vs {found.type_id.name} at {found.position.rounded}" if found is not None else "")
                    + f", {len(defenders)} defenders ({self._supply(defenders):g} supply)"
                )

    def _home_threat(self, defenders: list[Unit]) -> Optional[Unit]:
        """The enemy nearest one of our bases (M2 rules): army units within ARMY_DEFEND_RADIUS;
        workers within ARMY_WORKER_THREAT_RADIUS (a rush is worker_defense.py's job, a lone worker
        left behind is the army's); enemy structures once the squad has ARMY_CLEAR_STRUCTURES_SUPPLY
        and beats the finished Cannons near our bases and the units around them at
        CLEAR_STATIC_LEVEL, and before that a finished Cannon that can hit one of our townhalls once
        the squad beats the Cannons covering it (and those units) at that level. With the leash, only enemies near the hold point or inside the main."""
        bot = self.bot
        homes = self._homes()
        cannons = [
            s for s in bot.enemy_structures
            if s.type_id == UnitTypeId.PHOTONCANNON and s.is_ready
            and any(s.distance_to(h) < ARMY_DEFEND_RADIUS for h in homes)
        ]
        supply = self._supply(defenders)
        # the Cannons fight together with the enemy units around them
        guards = self.engagement.enemies_near([c.position for c in cannons]) if cannons else []
        strong_enough = supply >= ARMY_CLEAR_STRUCTURES_SUPPLY and (
            not cannons or self.engagement.level(defenders, cannons + guards, ENEMY_DEFENDS) >= CLEAR_STATIC_LEVEL
        )
        candidates = [e for e in bot.enemy_units if not e.is_memory]
        if strong_enough:
            # snapshots too: Cannons at our natural out of vision were never attacked in an M2
            # test game that tied at 60:00; the engine drops a snapshot once its spot is seen empty
            candidates += list(bot.enemy_structures)
        elif defenders:
            # a finished Cannon that can hit one of our townhalls is a target as soon as the squad
            # can beat the Cannons covering it (M2: one Cannon killed a main Nexus while the army
            # waited to clear every structure)
            for c in self._sieging(cannons):
                covering = [o for o in cannons if o.distance_to(c.position) <= o.ground_range + o.radius + c.radius + 1]
                if self.engagement.level(defenders, covering + guards, ENEMY_DEFENDS) >= CLEAR_STATIC_LEVEL:
                    candidates.append(c)
        best: Optional[tuple[float, Unit]] = None
        for enemy in candidates:
            if enemy.type_id in HARMLESS or enemy.is_hallucination:
                continue
            is_worker = enemy.type_id in WORKERS
            # a worker sheltering among finished Cannons isn't worth walking into them for
            if is_worker and not strong_enough and any(
                enemy.distance_to(c) <= c.ground_range + c.radius + 1 for c in cannons
            ):
                continue
            if self.hold_point is not None and self.leash is not None:
                if not self._inside_main(enemy.position) and enemy.distance_to(self.hold_point) > self.leash:
                    continue
            radius = ARMY_WORKER_THREAT_RADIUS if is_worker else ARMY_DEFEND_RADIUS
            for home in homes:
                d = enemy.distance_to(home)
                if d < radius and (best is None or d < best[0]):
                    best = (d, enemy)
        return best[1] if best is not None else None

    def _sieging(self, cannons: list[Unit]) -> list[Unit]:
        """Visible finished Cannons that can hit one of our ready townhalls."""
        homes = self.bot.townhalls.ready
        return [
            c for c in cannons
            if c.is_visible
            and any(c.distance_to(th.position) <= c.ground_range + c.radius + th.radius for th in homes)
        ]

    # -- targets ---------------------------------------------------------------------------------

    def _rally_point(self) -> Point2:
        """§4.5.2 "the defensive position at our newest base": the base farthest from our main,
        moved ARMY_RALLY_OFFSET toward the enemy."""
        bot = self.bot
        bases = bot.ready_townhalls or bot.townhalls
        if not bases:
            return bot.start_location
        front = max(bases, key=lambda th: th.distance_to(bot.start_location))
        return front.position.towards(bot.enemy_start_locations[0], ARMY_RALLY_OFFSET)

    def _attack_target(self, center: Point2, units: list[Unit]) -> Point2:
        """§4.5.2 targets: the known enemy townhall nearest the squad (its nearest expansion, the
        next, then the main), kept until it is gone; then other enemy structures; then the
        structure hunt. Flying (lifted) structures are left to the hunt."""
        bot = self.bot
        if self._target_tag is not None:
            kept = bot.enemy_structures.find_by_tag(self._target_tag)
            if kept is not None and (not kept.is_flying or (self.endgame is not None and self.endgame.hunting)):
                return kept.position
            self._target_tag = None
        grounded = [s for s in bot.enemy_structures if not s.is_flying]
        townhalls = [s for s in grounded if s.type_id in TOWNHALL_TYPES]
        pool = townhalls or grounded
        if not pool and self.endgame is not None and self.endgame.hunting and any(u.can_attack_air for u in units):
            # §4.7: lifted Terran buildings, for the units that can shoot up
            pool = [s for s in bot.enemy_structures if s.is_flying]
        if pool:
            chosen = min(pool, key=lambda s: s.distance_to(center))
            self._target_tag = chosen.tag
            return chosen.position
        return self._hunt_point(units)

    def _hunt_point(self, units: list[Unit]) -> Point2:
        if not self._hunt_points:
            self._hunt_points = self._build_hunt_points()
        for point in self._hunt_points:
            if point in self._visited:
                continue
            if any(u.distance_to(point) < HUNT_VISIT_RADIUS for u in units) or self.bot.is_visible(point):
                self._visited.add(point)
                continue
            return point
        self._visited.clear()  # every point seen once: start the sweep again
        return self._hunt_points[0]

    def _build_hunt_points(self) -> list[Point2]:
        """Enemy start, enemy-side expansions, all other expansions, region centres, then a map
        grid (ground points only)."""
        bot = self.bot
        points: list[Point2] = [bot.enemy_start_locations[0]]
        points += [p for p, _ in bot.mediator.get_enemy_expansions]
        points += sorted(bot.expansion_locations_list, key=lambda p: p.distance_to(bot.enemy_start_locations[0]))
        # §4.7 region centres the army can walk to (islands are the Observers')
        points += [
            c for r in bot.mediator.get_map_data_object.regions.values()
            if bot.in_pathing_grid(c := Point2(r.center))
        ]
        area = bot.game_info.playable_area
        x = area.x + HUNT_GRID_STEP / 2
        while x < area.x + area.width:
            y = area.y + HUNT_GRID_STEP / 2
            while y < area.y + area.height:
                p = Point2((x, y))
                if bot.in_pathing_grid(p):
                    points.append(p)
                y += HUNT_GRID_STEP
            x += HUNT_GRID_STEP
        unique: list[Point2] = []
        for p in points:
            if all(p.distance_to(q) > HUNT_VISIT_RADIUS for q in unique):
                unique.append(p)
        return unique

    def _groups(self, attackers: list[Unit]) -> list:
        """ares's spatial groups of the ATTACK squad's fighters (main group first)."""
        types = {u.type_id for u in attackers}
        if not types:
            return []
        squads = self.bot.mediator.get_squads(role=UnitRole.ATTACKING, squad_radius=ATTACK_SQUAD_RADIUS, unit_type=types)
        return sorted(squads, key=lambda s: (not s.main_squad, -len(s.squad_units)))

    def _main_group_center(self, attackers: list[Unit]) -> Optional[Point2]:
        groups = self._groups(attackers)
        return groups[0].squad_position if groups else None

    # -- intents (every ARMY_EVERY_STEPS) --------------------------------------------------------

    def _set_intents(self) -> None:
        anchor = self.anchor
        for u in self.squads.units(Role.DEFEND):
            intent = self.intents.get(u.tag)
            if intent is not None and intent[0] == RETREAT and u.distance_to(anchor) > RETREAT_DONE_RADIUS:
                self.intents[u.tag] = (RETREAT, anchor)
            elif self.defend_target is not None and is_fighter(u):
                self.intents[u.tag] = (FIGHT, self.defend_target)
            elif intent is not None and intent[0] == FIGHT and u.distance_to(anchor) > HOLD_ENGAGE_RADIUS:
                # a home fight turned bad: fall back, not attack-move back through the enemy
                # (M4 VeryHard Zerg Torches: the squad chased lings to the natural, Roaches came,
                # and the units died fighting their way back)
                self.intents[u.tag] = (RETREAT, anchor)
            else:
                self.intents[u.tag] = (HOLD, anchor)
        attackers = self._fighters(Role.ATTACK)
        if attackers and self.decision.state == ATTACK:
            groups = self._groups(attackers)
            main = groups[0] if groups else None
            target = self.target or anchor
            if main is not None:
                main_supply = self._supply(main.squad_units)
                total = self._supply(attackers)
                engaged = bool(self.engagement.enemies_near([main.squad_position], MICRO_RADIUS))
                wait = not engaged and total > 0 and (total - main_supply) / total >= REGROUP_FRACTION
                for u in main.squad_units:
                    self.intents[u.tag] = (HOLD, main.squad_position) if wait else (FIGHT, target)
                for g in groups[1:]:
                    for u in g.squad_units:
                        self.intents[u.tag] = (MOVE, main.squad_position)
            grouped = {u.tag for g in groups for u in g.squad_units}
            for u in attackers:
                if u.tag not in grouped:
                    self.intents[u.tag] = (FIGHT, target)
        rally = self.attack_center or anchor
        for u in self.squads.units(Role.REINFORCE):
            self.intents[u.tag] = (MOVE, rally)
        # the army's Observer: with the ATTACK squad's main group while it is out, else at home
        if self.observer_tag is not None:
            where = self.attack_center if self.decision.state == ATTACK and self.attack_center is not None else anchor
            self.intents[self.observer_tag] = (MOVE, where)

    def _claim_observer(self) -> None:
        """§4.3: from OBSERVER_WITH_ARMY_FROM_S one Observer travels with the army."""
        bot = self.bot
        if self.observer_tag is not None and self.observer_tag in self.squads.roles:
            return
        self.observer_tag = None
        if bot.time < OBSERVER_WITH_ARMY_FROM_S:
            return
        free = [
            u for u in self.squads.units(Role.DEFEND) + self.squads.units(Role.ATTACK)
            if u.type_id in SUPPORT
        ]
        if free:
            self.observer_tag = min(free, key=lambda u: u.distance_to(self.anchor)).tag

    # -- micro (every step) ----------------------------------------------------------------------

    def micro(self, iteration: int) -> None:
        """Every step. Orders that need a path query or a new move go out on a unit's own tick
        (one step in ARMY_EVERY_STEPS, staggered by tag) unless the unit is idle (§6)."""
        bot = self.bot
        get = bot.unit_tag_dict.get
        units = [
            u for tag, role in self.squads.roles.items()
            if role != Role.SCOUT and (u := get(tag)) is not None
        ]
        if not units:
            return
        near_lists = bot.mediator.get_units_in_range(
            start_points=[u.position for u in units], distances=MICRO_RADIUS, query_tree=UnitTreeQueryType.AllEnemy
        )
        for unit, near in zip(units, near_lists):
            mode, point = self.intents.get(unit.tag, (HOLD, self.anchor))
            own_tick = (iteration + unit.tag) % ARMY_EVERY_STEPS == 0 or unit.is_idle
            if unit.type_id in SUPPORT:
                if own_tick:
                    micro.keep_safe(bot, unit, point)
                continue
            visible = [e for e in near if not e.is_memory and e.type_id not in NOT_TARGETS]
            if mode == RETREAT:
                if own_tick or unit.weapon_cooldown == 0:
                    micro.retreat(bot, unit, visible, point, move_now=own_tick)
                continue
            if mode == MOVE:
                # walking out to the squad: fight only what can fight back
                visible = [e for e in visible if e.can_attack_ground or e.can_attack_air]
            elif mode == HOLD:
                radius = self.leash if (self.leash is not None and point == self.hold_point) else HOLD_ENGAGE_RADIUS
                visible = [e for e in visible if e.distance_to(point) <= radius or self._inside_main(e.position)]
            if visible:
                micro.fight(bot, unit, visible, point)
            elif own_tick and (mode != HOLD or unit.distance_to(point) > HOLD_RADIUS):
                micro.move(unit, point, attack=mode != MOVE)

    # -- logging ---------------------------------------------------------------------------------

    def _log(self, decision: Decision, level: int, detail: str = "") -> None:
        now = self.bot.time
        self.decisions.append((now, decision.action, level, decision.reason))
        logger.info(
            f"ENGAGE {self.bot.time_formatted} {decision.action} level={level} ({decision.reason})"
            + (f": {detail}" if detail else "")
        )

    def _status(self) -> None:
        bot = self.bot
        if bot.time - self._last_status < ARMY_STATUS_EVERY_S:
            return
        self._last_status = bot.time
        parts = []
        for role in (Role.DEFEND, Role.ATTACK, Role.REINFORCE, Role.SCOUT):
            units = self.squads.units(role)
            if units:
                parts.append(f"{role.value}={len(units)}/{self._supply(units):g}")
        logger.info(
            f"ARMY {bot.time_formatted} state={self.decision.state} {' '.join(parts) or 'no units'} "
            f"anchor={self.anchor.rounded} target={self.target.rounded if self.target else '-'} "
            f"level={self.last_level if self.last_level is not None else '-'} defend={self._defend_state}"
        )
