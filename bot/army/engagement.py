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

from typing import TYPE_CHECKING, Iterable, Optional, Sequence

from ares.consts import EngagementResult, UnitTreeQueryType
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2_helper.combat_simulator import CombatSimulator

from bot.constants import ENGAGE_ENEMY_RADIUS, ENGAGE_STATIC_RADIUS

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
    """A finished enemy static defense structure that fights (a Cannon only while powered)."""
    if structure.type_id not in STATIC_DEFENSE or not structure.is_ready:
        return False
    return structure.is_powered if structure.type_id == UnitTypeId.PHOTONCANNON else True


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
        """EngagementResult value (0-10) of `own` fighting `enemy`."""
        own = [u for u in own if is_fighter(u) or (u.is_structure and u.can_attack)]
        if not own:
            return EngagementResult.LOSS_EMPHATIC if enemy else EngagementResult.TIE
        if not enemy:
            return EngagementResult.VICTORY_EMPHATIC
        if defender == WE_DEFEND and any(u.is_structure for u in enemy):
            # neither side would walk in: the simulator would call it on health alone
            defender = ENEMY_DEFENDS
        self.calls += 1
        won, health_left = self.sim.predict_engage(list(own), list(enemy), defender_player=defender)
        own_health = sum(u.health + u.shield for u in own)
        enemy_health = sum(u.health + u.shield for u in enemy)
        return int(level_from_sim(won, health_left, own_health, enemy_health))
