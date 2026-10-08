"""The army commander (DESIGN.md §3 `army/`, §4.5.2): squads, home defense, the main attack.

Replaces M1's BasicArmy. Every ARMY_EVERY_STEPS steps (`step`) it refreshes squad roles and each
unit's intent; every DECISION_EVERY_STEPS steps it also makes the decisions below; every step
(`micro`) it controls the units that have a visible enemy within MICRO_RADIUS.

Home defense (DEFEND squad; Defense > Main attack, §3):
- A home threat is the enemy nearest one of our bases (townhalls and the natural spot) within
  ARMY_DEFEND_RADIUS: army units; lone workers within ARMY_WORKER_THREAT_RADIUS; enemy structures
  (proxy Pylons, Cannons) once the squad can take them (M2 rules, now on the simulator). With the
  defense plan's leash, only enemies near its hold point or inside our main. With no other threat,
  a known proxy production structure while PROXY is active, once the squad can take it (M7 B9).
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

Counterattack (HARASS squad, bot/army/counterattack.py, §4.6): evaluated every
DECISION_EVERY_STEPS, half a period after the main attack decision; a main attack launch takes the
HARASS squad in.
"""

import math
from typing import TYPE_CHECKING, NamedTuple, Optional

from ares.consts import TOWNHALL_TYPES, EngagementResult, UnitRole, UnitTreeQueryType
from loguru import logger
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit

from bot.army import micro
from bot.army.attack_decision import ATTACK, AttackDecision, Decision
from bot.army.counterattack import Counterattack
from bot.army.engagement import (
    ENEMY_DEFENDS,
    WE_DEFEND,
    WORKERS,
    Engagement,
    FightInputs,
    is_fighter,
)
from bot.army.squads import Role, Squads
from bot.intel.threat_flags import Threat
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
    ENGAGE_ENEMY_RADIUS,
    ENGAGE_STATIC_RADIUS,
    HOLD_ENGAGE_RADIUS,
    HOLD_FALLBACK_MEMORY_S,
    HOLD_FALLBACK_STEP,
    HOLD_FALLBACK_STEPS,
    HOLD_RADIUS,
    LAUNCH_CACHE_MAX_AGE_S,
    LAUNCH_INTEL_FRESH_FRACTION,
    HUNT_GRID_STEP,
    HUNT_VISIT_RADIUS,
    MAIN_RADIUS,
    MICRO_RADIUS,
    OBSERVER_WITH_ARMY_FROM_S,
    OUT_OF_POSITION_FRESH_S,
    OUTRANGED_REACH_BUFFER,
    PROXY_CLEAR_SUPPLY,
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
    from bot.intel.threat_flags import FlagStore

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
FIGHT, HOLD, RETREAT, MOVE, HARASS = "fight", "hold", "retreat", "move", "harass"


class DecisionRecord(NamedTuple):
    """One main-attack decision for §8: its level, and the fight values the level came from (M7)."""

    t: float
    action: str
    level: int
    reason: str
    own_value: Optional[float] = None
    enemy_value: Optional[float] = None


class Army:
    def __init__(self, bot: "AresBot", endgame: Optional["EndGame"] = None, flags: Optional["FlagStore"] = None):
        self.bot = bot
        self.endgame = endgame  # §4.7
        self.engagement = Engagement(bot)
        self.decision = AttackDecision()
        self.squads = Squads(bot)
        self.flags = flags
        self.counter = Counterattack(bot, self, flags)  # §4.6
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
        # M7 C2: the DEFEND units that can hit the evaluated threat group (None: all of them)
        self._defend_tags: Optional[set[int]] = None
        self._home_fight_at: Optional[float] = None  # M7 C4: last time the DEFEND squad fought units
        self._fallback_steps: int = 0  # M7 C1: steps the defensive position moved back
        self.wants_intel: bool = False  # M7 C4: the launch waits for the army's Observer to look
        self._intel_wait_logged: bool = False
        # main attack
        self.target: Optional[Point2] = None
        self._target_tag: Optional[int] = None
        self.attack_center: Optional[Point2] = None
        self.last_level: Optional[int] = None
        self.decisions: list[DecisionRecord] = []  # §8
        # the fight inputs behind the last main-attack and home-defense levels (M7 §8)
        self._attack_inputs: Optional[FightInputs] = None
        self._home_inputs: Optional[FightInputs] = None
        # M7 B1 regression metric: reinforcements sent out in the tick of a retreat or recall (must stay 0)
        self.reinforce_after_retreat: int = 0
        self._hunt_points: list[Point2] = []
        self._visited: set[Point2] = set()
        self._last_status: float = 0.0
        self._step: int = 0

    # -- interface -----------------------------------------------------------------------------

    @property
    def busy_tags(self) -> set[int]:
        """Units the scout planner must not take: the ATTACK, REINFORCE and HARASS squads and the
        army's Observer."""
        tags = self.squads.tags(Role.ATTACK) | self.squads.tags(Role.REINFORCE) | self.squads.tags(Role.HARASS)
        return tags | ({self.observer_tag} if self.observer_tag is not None else set())

    @property
    def attacking(self) -> bool:
        """The main attack is on (§4.6: no counterattack then)."""
        return self.decision.state == ATTACK

    def retreating(self, tag: int) -> bool:
        intent = self.intents.get(tag)
        return intent is not None and intent[0] == RETREAT

    def send_home(self, tags: set[int]) -> None:
        """Squad units back to the DEFEND squad, walking home on a danger-aware path."""
        self.squads.assign(tags, Role.DEFEND)
        for tag in tags:
            self.intents[tag] = (RETREAT, self.anchor)

    def forget(self, tag: int) -> None:
        self.squads.forget(tag)
        self.intents.pop(tag, None)
        if tag == self.observer_tag:
            self.observer_tag = None

    def step(self, iteration: int, guarded: bool = False) -> None:
        """`guarded`: the §6 step guard is on (the counterattack skips detection and launch)."""
        bot = self.bot
        self._step = iteration
        army = [
            u for u in bot.mediator.get_own_army
            if u.type_id not in WORKERS and not u.is_hallucination and not u.is_structure
            and u.build_progress == 1  # not while warping in
        ]
        self.squads.update(army, self.scout_tags, self.held_tags)
        self.anchor = self._fallback_anchor(self.hold_point if self.hold_point is not None else self._rally_point())
        self._claim_observer()
        if iteration % DECISION_EVERY_STEPS == 0:
            self._decide()
        elif iteration % DECISION_EVERY_STEPS == DECISION_EVERY_STEPS // 2:
            self.counter.tick(guarded)
        self.counter.refresh_goals()
        self._set_intents()
        self._status()

    # -- decisions (every DECISION_EVERY_STEPS) --------------------------------------------------

    def fighters(self, role: Role) -> list[Unit]:
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
        defenders = self.fighters(Role.DEFEND)
        self._home_defense(defenders)
        self.wants_intel = False
        attackers = self.fighters(Role.ATTACK)
        if self.decision.state == ATTACK and self.threat is not None and self.defend_target is None:
            near = self.engagement.enemies_near([self.threat])
            value = self.engagement.value(attackers)
            if value > 0 and self.engagement.value(near) >= ARMY_RECALL_FRACTION * value:
                self.decision.recall(now)
                self._log(
                    Decision(self.decision.state, "recall", f"home threat at {self.threat.rounded} the DEFEND squad can't hold"),
                    self.home_level,
                    inputs=self._home_inputs,
                )
                self._retreat_attack_squad()
                return
        if self.decision.state == ATTACK:
            self._evaluate_attack(attackers)
            # a retreat decided just now sends no one out (M7 B1: at 9:32 of the first ladder loss,
            # a group left for the old fight in the retreat's own tick and died there)
            if self.decision.state == ATTACK:
                self._reinforce(defenders)
        elif self.threat is None and bot.supply_used >= ATTACK_START_SUPPLY and defenders:
            self._evaluate_launch(defenders)

    def _evaluate_launch(self, candidates: list[Unit]) -> None:
        bot = self.bot
        center = Point2.center([u.position for u in candidates])
        target = self._attack_target(center, candidates)
        enemy = self.engagement.attack_inputs(center, target)
        level = self.engagement.level(candidates, enemy, ENEMY_DEFENDS)
        self._attack_inputs = self.engagement.last_inputs
        self.last_level = level
        # M7 C4: the level against the remembered enemy army as a whole, and how fresh it is
        cached = [u for u in bot.mediator.get_cached_enemy_army if is_fighter(u) and u.age <= LAUNCH_CACHE_MAX_AGE_S]
        army_level = self.engagement.level(candidates, cached, ENEMY_DEFENDS) if cached else None
        total = self.engagement.value(cached)
        fresh = self.engagement.value(u for u in cached if u.age <= OUT_OF_POSITION_FRESH_S)
        since_fight = bot.time - self._home_fight_at if self._home_fight_at is not None else math.inf
        decision = self.decision.evaluate(
            bot.time, level, bot.supply_used, self.engagement.value(candidates), self._value_ratio(),
            since_home_fight_s=since_fight, army_level=army_level,
            intel_fresh=total > 0 and fresh >= LAUNCH_INTEL_FRESH_FRACTION * total,
        )
        if decision.wants_intel and not self._intel_wait_logged:
            logger.info(f"ARMY {bot.time_formatted} launch waits, the Observer looks: {decision.reason}")
        self.wants_intel = self._intel_wait_logged = decision.wants_intel
        if decision.action == "launch":
            self.squads.assign([u.tag for u in candidates], Role.ATTACK)
            self.target = target
            for u in candidates:
                self.intents.pop(u.tag, None)
            self._log(
                decision, level, f"{len(candidates)} units, {self._supply(candidates):g} supply -> {target.rounded}",
                inputs=self._attack_inputs,
            )
            self.counter.merge()  # §4.6: the main attack absorbs a counterattack

    def _evaluate_attack(self, attackers: list[Unit]) -> None:
        bot = self.bot
        center = self._main_group_center(attackers)
        self.attack_center = center
        if center is None:
            level = 0
            enemy_value = 0.0
            target = self.target
            self._attack_inputs = None
        else:
            target = self._attack_target(center, attackers)
            enemy = self.engagement.attack_inputs(center, target)
            level = self.engagement.level(attackers, enemy, ENEMY_DEFENDS)
            self._attack_inputs = self.engagement.last_inputs
            enemy_value = self.engagement.value(enemy)
        self.target = target
        self.last_level = level
        decision = self.decision.evaluate(
            bot.time, level, bot.supply_used, self.engagement.value(attackers), self._value_ratio()
        )
        if decision.action == "retreat":
            self._log(decision, level, f"{len(attackers)} units left, enemy value near {enemy_value:.0f}", inputs=self._attack_inputs)
            self._retreat_attack_squad()

    def _retreat_attack_squad(self) -> None:
        self.send_home(self.squads.tags(Role.ATTACK) | self.squads.tags(Role.REINFORCE))
        self._target_tag = None
        self.attack_center = None  # M7 B1: nothing may rally to the old fight

    def _reinforce(self, defenders: list[Unit]) -> None:
        """§4.5.2: new units go out in groups of >= REINFORCE_MIN_SUPPLY, never one by one."""
        if self.attack_center is None:
            return
        # groups on their way: join the squad near it, or come back from a fight they'd lose
        group = self.fighters(Role.REINFORCE)
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
            last = self.decisions[-1] if self.decisions else None
            if last is not None and last.t == self.bot.time and last.action in ("retreat", "recall"):
                self.reinforce_after_retreat += 1
            logger.info(f"ARMY reinforcements out at {self.bot.time_formatted}: {len(ready)} units, {self._supply(ready):g} supply")

    # -- home defense ----------------------------------------------------------------------------

    @staticmethod
    def _able(defenders: list[Unit], enemies: list[Unit]) -> list[Unit]:
        """M7 C2: the defenders that can hit at least one of `enemies` (game data)."""
        return [u for u in defenders if any(micro.can_hit(u, e) for e in enemies)]

    def _homes(self) -> list[Point2]:
        # our townhalls, and the natural spot even before it has one (it is ours to hold)
        return [th.position for th in self.bot.townhalls] + [self.bot.mediator.get_own_nat]

    def _inside_main(self, point: Point2) -> bool:
        bot = self.bot
        return (
            point.distance_to(bot.start_location) <= MAIN_RADIUS
            and abs(bot.get_terrain_z_height(point) - bot.get_terrain_z_height(bot.start_location)) < SAME_LEVEL_Z
        )

    def own_cannons_near(self, point: Point2) -> list[Unit]:
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
        self._home_inputs = None
        self._defend_tags = None
        state = "none"
        if found is None and (proxy := self._proxy_clear(defenders)) is not None:
            found, level, self._home_inputs = proxy
            self.threat = self.defend_target = found.position
            self.home_level = level
            state = f"clearing proxy {found.type_id.name} (level {level})"
        elif found is not None:
            if found.is_structure or found.type_id in WORKERS:
                # static defense covering the target, and the units around it, fight for it
                # (M4 cannon_rush Ultralove: the Cannons around a Pylon near our base were just
                # outside the "near our bases" radius, and the squad died walking in)
                # (a Cannon target is part of its own guard)
                guard = self.engagement.static_defense_near(found.position) + self.engagement.enemies_near([found.position])
                level = self.engagement.level(defenders, guard, ENEMY_DEFENDS) if guard else int(EngagementResult.VICTORY_EMPHATIC)
                self._home_inputs = self.engagement.last_inputs if guard else None
                self.home_level = level
                if level >= CLEAR_STATIC_LEVEL:
                    self.defend_target, state = found.position, f"clearing {found.type_id.name} (level {level})"
                else:
                    state = f"hold, {found.type_id.name} covered (level {level} < {CLEAR_STATIC_LEVEL})"
            elif self._inside_main(found.position) or found.distance_to(self.anchor) <= ARMY_HOLD_LEASH:
                # M7 C2: only units that can hit the group answer it; the others hold
                group = self.engagement.enemies_near([found.position]) or [found]
                able = self._able(defenders, group)
                if able:
                    self.defend_target, state = found.position, "last stand (main or defensive position)"
                    self._defend_tags = {u.tag for u in able}
                else:
                    state = "hold, nothing can hit it (main or defensive position)"
            else:
                enemy = self.engagement.enemies_near([found.position]) + self.engagement.static_defense_near(found.position)
                # M7 C2 (§4.5.2): only units that can hit something in the group answer it, and only
                # they count in its simulation
                able = self._able(defenders, enemy or [found])
                self._defend_tags = {u.tag for u in able}
                level = self.engagement.level(able + self.own_cannons_near(found.position), enemy, WE_DEFEND)
                self._home_inputs = self.engagement.last_inputs
                self.home_level = level
                covered = self._covered_by_battery(found.position)
                needed = DEFEND_ENGAGE if covered else ATTACK_CONTINUE
                if level >= needed:
                    self.defend_target = found.position
                    state = f"engage (level {level} >= {needed}{', batteries' if covered else ''})"
                else:
                    state = f"hold (level {level} < {needed}{', batteries' if covered else ''})"
        if self.defend_target is not None and not (found.is_structure or found.type_id in WORKERS):
            self._home_fight_at = self.bot.time  # M7 C4
        if state != self._defend_state:
            self._defend_state = state
            if found is not None or self.decision.state != ATTACK:
                logger.info(
                    f"DEFEND {self.bot.time_formatted}: {state}"
                    + (f" vs {found.type_id.name} at {found.position.rounded}" if found is not None else "")
                    + f", {len(defenders)} defenders ({self._supply(defenders):g} supply)"
                    + (f"; {self._home_inputs.text()}" if self._home_inputs is not None else "")
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

    def _proxy_clear(self, defenders: list[Unit]) -> Optional[tuple[Unit, int, Optional[FightInputs]]]:
        """M7 B9 (D17): while PROXY is active, the known proxy production structure nearest our
        natural (the proxy_structure flag's evidence) and the level against what guards it, if the
        DEFEND squad has PROXY_CLEAR_SUPPLY and beats that at CLEAR_STATIC_LEVEL. Only then is it a
        home threat: one the squad holds against would stop launches and reinforcements. In two
        test games the PROXY plan held one base for 60 minutes under the launch gate's supply while
        the proxy Barracks stood."""
        flag = self.flags.get(Threat.PROXY, "proxy_structure") if self.flags is not None else None
        if flag is None or self._supply(defenders) < PROXY_CLEAR_SUPPLY:
            return None
        structures = [s for s in self.bot.enemy_structures if s.tag in flag.evidence_tags]
        if not structures:
            return None
        nat = self.bot.mediator.get_own_nat
        target = min(structures, key=lambda s: s.distance_to(nat))
        guard = self.engagement.static_defense_near(target.position) + self.engagement.enemies_near([target.position])
        if not guard:
            return target, int(EngagementResult.VICTORY_EMPHATIC), None
        level = self.engagement.level(defenders, guard, ENEMY_DEFENDS)
        return (target, level, self.engagement.last_inputs) if level >= CLEAR_STATIC_LEVEL else None

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
        if self.decision.state != ATTACK and (stray := self.squads.tags(Role.REINFORCE)):
            # reinforcements exist only while the attack is on (§4.5.2, M7 B1)
            self.send_home(stray)
        for u in self.squads.units(Role.DEFEND):
            intent = self.intents.get(u.tag)
            if intent is not None and intent[0] == RETREAT and u.distance_to(anchor) > RETREAT_DONE_RADIUS:
                self.intents[u.tag] = (RETREAT, anchor)
            elif self.defend_target is not None and is_fighter(u) and (
                self._defend_tags is None or u.tag in self._defend_tags
            ):
                self.intents[u.tag] = (FIGHT, self.defend_target)
            elif intent is not None and intent[0] == FIGHT and u.distance_to(anchor) > HOLD_ENGAGE_RADIUS:
                # a home fight turned bad: fall back, not attack-move back through the enemy
                # (M4 VeryHard Zerg Torches: the squad chased lings to the natural, Roaches came,
                # and the units died fighting their way back)
                self.intents[u.tag] = (RETREAT, anchor)
            else:
                self.intents[u.tag] = (HOLD, anchor)
        attackers = self.fighters(Role.ATTACK)
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
        for u in self.squads.units(Role.HARASS):
            self.intents[u.tag] = (HARASS, self.counter.target or anchor)
        # the army's Observer: with the ATTACK squad's main group while it is out, else at home
        if self.observer_tag is not None:
            where = self.attack_center if self.decision.state == ATTACK and self.attack_center is not None else anchor
            if self.wants_intel and self.decision.state != ATTACK:
                where = self._look_point()  # M7 C4: look at the enemy army before launching
            self.intents[self.observer_tag] = (MOVE, where)

    def _look_point(self) -> Point2:
        """M7 C4: where the army's Observer looks before a launch: the remembered enemy army's
        centre, else the enemy main."""
        army = [u for u in self.bot.mediator.get_cached_enemy_army if is_fighter(u)]
        return Point2.center([u.position for u in army]) if army else self.bot.enemy_start_locations[0]

    def _fallback_anchor(self, anchor: Point2) -> Point2:
        """M7 C1 (§4.5.3): while enemies that out-range every DEFEND unit type (seen within
        HOLD_FALLBACK_MEMORY_S) have the defensive position in reach and home defense isn't
        fighting, the position steps toward our main, HOLD_FALLBACK_STEP at a time, at most
        HOLD_FALLBACK_STEPS times. Logged when the number of steps changes."""
        steps = 0
        defenders = self.fighters(Role.DEFEND)
        if self.defend_target is None and defenders:
            kinds = list({u.type_id: u for u in defenders}.values())  # one unit per type
            longest = max(max(u.ground_range, u.air_range) for u in kinds)
            covers = []
            for e in self.bot.mediator.get_cached_enemy_army:
                if e.age > HOLD_FALLBACK_MEMORY_S or e.distance_to(anchor) > longest + 30:
                    continue
                if all(micro.outranges(e, u) for u in kinds):
                    reaches = [r for u in kinds if (r := micro.reach(e, u)) is not None]
                    if reaches:
                        covers.append((e.position, max(reaches) + OUTRANGED_REACH_BUFFER))
            home = self.bot.start_location
            while steps < HOLD_FALLBACK_STEPS and any(p.distance_to(anchor) <= r for p, r in covers):
                anchor = anchor.towards(home, HOLD_FALLBACK_STEP)
                steps += 1
        if steps != self._fallback_steps:
            self._fallback_steps = steps
            logger.info(
                f"ARMY {self.bot.time_formatted} hold point back to {anchor.rounded} ({steps} of {HOLD_FALLBACK_STEPS} steps)"
                if steps else f"ARMY {self.bot.time_formatted} hold point restored to {anchor.rounded}"
            )
        return anchor

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
        goals: list[list[Unit]] = []
        if self.counter.target is not None:
            goals = [
                [e for tag in group if (e := get(tag)) is not None and not e.is_memory]
                for group in self.counter.goals
            ]
        for unit, near in zip(units, near_lists):
            mode, point = self.intents.get(unit.tag, (HOLD, self.anchor))
            own_tick = (iteration + unit.tag) % ARMY_EVERY_STEPS == 0 or unit.is_idle
            if unit.type_id in SUPPORT:
                if own_tick:
                    micro.keep_safe(bot, unit, point)
                continue
            visible = [e for e in near if not e.is_memory and e.type_id not in NOT_TARGETS]
            if mode in (HOLD, MOVE, RETREAT) and micro.out_rangers(unit, visible):
                # M7 C1 (§4.5.3): not committed to a fight, so out of the out-rangers' reach first
                # (Stalkers holding at the natural died in place to Tempests in the first ladder loss)
                if not own_tick or micro.step_out(bot, unit):
                    continue
            if mode == HARASS:
                micro.harass(bot, unit, visible, point, goals, own_tick)
                continue
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
            elif self.squads.roles.get(unit.tag) == Role.DEFEND:
                # a home fight is against the group it evaluated, not whatever each unit sees (M7 B3,
                # §4.5.2: a Stalker ran at Tempests while the squad fought a Zealot elsewhere)
                visible = [e for e in visible if e.distance_to(point) <= ENGAGE_ENEMY_RADIUS]
            if visible:
                micro.fight(bot, unit, visible, point)
            elif own_tick and (mode != HOLD or unit.distance_to(point) > HOLD_RADIUS):
                # only a fight is walked to with an attack-move: units going back to their hold
                # point move, so the engine doesn't send them after whatever shoots them (M7 B2)
                micro.move(unit, point, attack=mode == FIGHT)

    # -- logging ---------------------------------------------------------------------------------

    def _log(self, decision: Decision, level: int, detail: str = "", inputs: Optional[FightInputs] = None) -> None:
        """`inputs`: the fight the level came from, logged and kept for §8 (M7)."""
        now = self.bot.time
        self.decisions.append(
            DecisionRecord(
                now, decision.action, level, decision.reason,
                inputs.own_value if inputs is not None else None,
                inputs.enemy_value if inputs is not None else None,
            )
        )
        logger.info(
            f"ENGAGE {self.bot.time_formatted} {decision.action} level={level} ({decision.reason})"
            + (f": {detail}" if detail else "")
            + (f"; {inputs.text()}" if inputs is not None else "")
        )

    def _status(self) -> None:
        bot = self.bot
        if bot.time - self._last_status < ARMY_STATUS_EVERY_S:
            return
        self._last_status = bot.time
        parts = []
        for role in (Role.DEFEND, Role.ATTACK, Role.REINFORCE, Role.HARASS, Role.SCOUT):
            units = self.squads.units(role)
            if units:
                parts.append(f"{role.value}={len(units)}/{self._supply(units):g}")
        logger.info(
            f"ARMY {bot.time_formatted} state={self.decision.state} {' '.join(parts) or 'no units'} "
            f"anchor={self.anchor.rounded} target={self.target.rounded if self.target else '-'} "
            f"level={self.last_level if self.last_level is not None else '-'} defend={self._defend_state} "
            f"counter={self.counter.state}"
            + (f" (enemy army: {self.counter.position.last.why})" if self.counter.position.last is not None else "")
        )
