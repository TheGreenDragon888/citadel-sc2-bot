"""Fight evaluation for the §4.5.2 gates: Citadel's EngagementResult (DESIGN.md §4.5.2, §11.3).

The level comes from the same combat simulator ares's `mediator.can_win_fight` uses
(`sc2_helper`), mapped to the same 11 `EngagementResult` levels, with two changes (user
decisions for M4, docs/VERIFY_NOTES.md "M4 findings"):

- **Our shields count.** ares divides the health left after a win (HP + shields) by our HP
  without shields, so Protoss wins read 1-3 levels too high; here our side is HP + shields.
- **The defender is set.** With timing adjustment on, the simulator assumes both sides walk
  into range from a distance unless one is marked as the defender, and a unit that can't move
  (static defense) then never fires. When our squad attacks, the enemy holds its ground (its
  Cannons, Bunkers and Spines shoot while we walk in); when we defend at home, we hold ours.

Inputs (§4.5.2): our squad's fighting units; remembered enemy army (visible units and ares's
30 s ghosts) within `ENGAGE_ENEMY_RADIUS` of the squad or of its target, without workers,
hallucinations and units that can't fight; and enemy static defense within
`ENGAGE_STATIC_RADIUS` of the target (finished; Cannons powered), Shield Batteries included as
support.
"""

from typing import TYPE_CHECKING, Iterable, NamedTuple, Optional, Sequence

from ares.consts import EngagementResult, UnitTreeQueryType
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2_helper.combat_simulator import CombatSimulator

from bot.army.ranges import can_hit, outrange_penalty, outranges
from bot.constants import ENGAGE_ENEMY_RADIUS, ENGAGE_STATIC_RADIUS, FIGHT_LOG_TYPES, OUTRANGE_PENALTY_PER_SHARE

if TYPE_CHECKING:
    from ares import AresBot

WORKERS: frozenset[UnitTypeId] = frozenset(
    {UnitTypeId.PROBE, UnitTypeId.SCV, UnitTypeId.DRONE, UnitTypeId.MULE}
)
# units that neither fight nor matter to a fight's outcome (both sides)
NON_COMBAT: frozenset[UnitTypeId] = frozenset(
    {
        UnitTypeId.OVERLORD, UnitTypeId.OVERLORDTRANSPORT, UnitTypeId.OVERSEER,
        UnitTypeId.OVERSEERSIEGEMODE, UnitTypeId.OVERLORDCOCOON, UnitTypeId.TRANSPORTOVERLORDCOCOON,
        UnitTypeId.OBSERVER, UnitTypeId.OBSERVERSIEGEMODE, UnitTypeId.WARPPRISM,
        UnitTypeId.WARPPRISMPHASING, UnitTypeId.LARVA, UnitTypeId.EGG, UnitTypeId.BROODLORDCOCOON,
        UnitTypeId.CHANGELING, UnitTypeId.CHANGELINGMARINE, UnitTypeId.CHANGELINGMARINESHIELD,
        UnitTypeId.CHANGELINGZEALOT, UnitTypeId.CHANGELINGZERGLING,
        UnitTypeId.CHANGELINGZERGLINGWINGS, UnitTypeId.ADEPTPHASESHIFT,
        UnitTypeId.DISRUPTORPHASED,
    }
)
# §4.5.2 "enemy static defense within 15 of the target": Cannons, Bunkers, Spine Crawlers,
# Planetary Fortresses, and Shield Batteries as support
STATIC_DEFENSE: frozenset[UnitTypeId] = frozenset(
    {
        UnitTypeId.PHOTONCANNON, UnitTypeId.BUNKER, UnitTypeId.SPINECRAWLER,
        UnitTypeId.PLANETARYFORTRESS, UnitTypeId.SHIELDBATTERY,
    }
)

# sc2_helper `predict_engage` defender_player values
NO_DEFENDER, WE_DEFEND, ENEMY_DEFENDS = 0, 1, 2


def is_fighter(unit: Unit) -> bool:
    """A unit that counts in a fight (either side): not a worker, structure, hallucination or
    non-combat unit."""
    return not (
        unit.is_structure
        or unit.type_id in WORKERS
        or unit.type_id in NON_COMBAT
        or unit.is_hallucination
    )


def is_static_defense(structure: Unit) -> bool:
    """A finished enemy static defense structure that fights (a visible Cannon only while powered;
    a snapshot in the fog doesn't report power, so it counts as powered: M4 cannon_rush Ultralove,
    where 8 fogged Cannons were left out and 4 units read level 10 against them)."""
    if structure.type_id not in STATIC_DEFENSE or not structure.is_ready:
        return False
    if structure.type_id == UnitTypeId.PHOTONCANNON and structure.is_visible:
        return structure.is_powered
    return True


class FightInputs(NamedTuple):
    """What one `Engagement.level` call simulated (M7 §8 fight inputs)."""

    own_text: str
    own_value: float
    enemy_text: str
    enemy_value: float
    penalty: int = 0  # M7 C5: levels taken off for out-ranging enemies

    def text(self) -> str:
        return (
            f"vs {self.enemy_text} ({self.enemy_value:.0f}) | ours {self.own_text} ({self.own_value:.0f})"
            + (f"; -{self.penalty} out-ranged" if self.penalty else "")
        )


def composition_text(pairs: Iterable[tuple[str, float]], max_types: int = FIGHT_LOG_TYPES) -> tuple[str, float]:
    """(type name, resource value) per unit -> ("8 TEMPEST 4 ZEALOT", total value): counts by type,
    the highest total value first, at most `max_types` types (the rest summed as "+N more")."""
    counts: dict[str, int] = {}
    values: dict[str, float] = {}
    for name, value in pairs:
        counts[name] = counts.get(name, 0) + 1
        values[name] = values.get(name, 0.0) + value
    order = sorted(counts, key=lambda n: (-values[n], n))
    text = " ".join(f"{counts[n]} {n}" for n in order[:max_types])
    if len(order) > max_types:
        text += f" +{sum(counts[n] for n in order[max_types:])} more"
    return text or "nothing", sum(values.values())


def level_from_sim(won: bool, health_left: float, own_health: float, enemy_health: float) -> int:
    """ares's mapping (`combat_sim_manager.py:147-173`) with `own_health` = our HP + shields."""
    if won:
        ratio = health_left / (own_health + 1e-16)
        if ratio >= 0.9:
            return EngagementResult.VICTORY_EMPHATIC
        if ratio >= 0.75:
            return EngagementResult.VICTORY_OVERWHELMING
        if ratio >= 0.6:
            return EngagementResult.VICTORY_DECISIVE
        if ratio > 0.4:
            return EngagementResult.VICTORY_CLOSE
        if ratio > 0.2:
            return EngagementResult.VICTORY_MARGINAL
    else:
        ratio = health_left / (enemy_health + 1e-16)
        if ratio >= 0.9:
            return EngagementResult.LOSS_EMPHATIC
        if ratio >= 0.75:
            return EngagementResult.LOSS_OVERWHELMING
        if ratio > 0.6:
            return EngagementResult.LOSS_DECISIVE
        if ratio > 0.4:
            return EngagementResult.LOSS_CLOSE
        if ratio > 0.2:
            return EngagementResult.LOSS_MARGINAL
    return EngagementResult.TIE


class Engagement:
    def __init__(self, bot: "AresBot"):
        self.bot = bot
        # our own simulator object: ares's (used by can_win_fight) keeps its own settings
        self.sim = CombatSimulator()
        self.sim.enable_timing_adjustment(True)
        self.calls: int = 0  # simulator calls this game (§3: at most 2 per evaluation)
        self.last_inputs: Optional[FightInputs] = None  # the last `level` call's inputs (M7 §8)

    # -- values ----------------------------------------------------------------------------------

    def value(self, units: Iterable[Unit]) -> float:
        """Resource value (minerals + gas, from game data) of `units`."""
        total = 0.0
        for u in units:
            cost = self.bot.calculate_unit_value(u.type_id)
            total += cost.minerals + cost.vespene
        return total

    # -- inputs ----------------------------------------------------------------------------------

    def enemies_near(self, points: Sequence[Point2], radius: float = ENGAGE_ENEMY_RADIUS) -> list[Unit]:
        """Remembered enemy fighters (visible + ghosts) within `radius` of any of `points`."""
        if not points:
            return []
        found = self.bot.mediator.get_units_in_range(
            start_points=list(points), distances=radius, query_tree=UnitTreeQueryType.AllEnemy
        )
        seen: set[int] = set()
        out: list[Unit] = []
        for group in found:
            for u in group:
                if u.tag not in seen and is_fighter(u):
                    seen.add(u.tag)
                    out.append(u)
        return out

    def static_defense_near(self, point: Point2, radius: float = ENGAGE_STATIC_RADIUS) -> list[Unit]:
        """Enemy static defense within `radius` of `point` (snapshots in fog included)."""
        return [
            s for s in self.bot.enemy_structures
            if s.type_id in STATIC_DEFENSE and is_static_defense(s) and s.distance_to(point) <= radius
        ]

    def attack_inputs(self, squad_center: Point2, target: Optional[Point2]) -> list[Unit]:
        """§4.5.2 enemy side for a squad going to `target`: remembered army within
        ENGAGE_ENEMY_RADIUS of the squad or the target, plus static defense near the target."""
        points = [squad_center] + ([target] if target is not None else [])
        enemy = self.enemies_near(points)
        if target is not None:
            enemy += self.static_defense_near(target)
        # static defense next to the squad itself fights too (a Cannon on the way)
        tags = {u.tag for u in enemy}
        enemy += [s for s in self.static_defense_near(squad_center) if s.tag not in tags]
        return enemy

    # -- the level -------------------------------------------------------------------------------

    def level(self, own: Sequence[Unit], enemy: Sequence[Unit], defender: int) -> int:
        """EngagementResult value (0-10) of `own` fighting `enemy`. The inputs are kept in
        `last_inputs` for the log lines (M7 §8)."""
        own = [u for u in own if is_fighter(u) or (u.is_structure and u.can_attack)]
        self.last_inputs = self._inputs(own, enemy)
        if not own:
            return int(EngagementResult.LOSS_EMPHATIC if enemy else EngagementResult.TIE)
        if not enemy:
            return int(EngagementResult.VICTORY_EMPHATIC)
        if defender == WE_DEFEND and any(u.is_structure for u in enemy):
            # neither side would walk in: the simulator would call it on health alone
            defender = ENEMY_DEFENDS
        self.calls += 1
        won, health_left = self.sim.predict_engage(list(own), list(enemy), defender_player=defender)
        own_health = sum(u.health + u.shield for u in own)
        enemy_health = sum(u.health + u.shield for u in enemy)
        raw = int(level_from_sim(won, health_left, own_health, enemy_health))
        # M7 C5 (§4.5.2): the simulator never sees positions, and rated home fights against
        # Tempest armies 7-9 at a third of their value in the Phase 1 batches
        penalty = outrange_penalty(self.outranged_share(own, enemy), OUTRANGE_PENALTY_PER_SHARE)
        self.last_inputs = self.last_inputs._replace(penalty=penalty)
        return max(int(EngagementResult.LOSS_EMPHATIC), raw - penalty)

    def outranged_share(self, own: Sequence[Unit], enemy: Sequence[Unit]) -> float:
        """M7 C5: the share of the enemy's value that out-ranges every unit of ours able to hit it
        (by OUTRANGED_MARGIN), or that none of ours can hit while it can hit some of them."""
        kinds = list({u.type_id: u for u in own}.values())  # one unit per type
        total = out = 0.0
        for e in enemy:
            v = self.value([e])
            if v <= 0:
                continue
            total += v
            hitters = [u for u in kinds if can_hit(u, e)]
            if hitters:
                if all(outranges(e, u) for u in hitters):
                    out += v
            elif any(can_hit(e, u) for u in kinds):
                out += v
        return out / total if total > 0 else 0.0

    def _inputs(self, own: Sequence[Unit], enemy: Sequence[Unit]) -> FightInputs:
        def pairs(units: Sequence[Unit]) -> list[tuple[str, float]]:
            out = []
            for u in units:
                cost = self.bot.calculate_unit_value(u.type_id)
                out.append((u.type_id.name, cost.minerals + cost.vespene))
            return out

        own_text, own_value = composition_text(pairs(own))
        enemy_text, enemy_value = composition_text(pairs(enemy))
        return FightInputs(own_text, own_value, enemy_text, enemy_value)
