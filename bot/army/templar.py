"""High Templar: Psionic Storm, positioning and Archon morphs (M7 K3, DESIGN.md §4.5.1, §4.5.3).

Run by the army every step after its own micro (Templar are skipped there, like Observers):
- **Storm:** a Templar with Storm castable (`AbilityId.PSISTORM_PSISTORM in unit.abilities`: it is
  missing without the research or the energy, VERIFY_NOTES "M7 findings") casts it through ares's
  `AutoUseAOEAbility`, which needs 4 targets, keeps it off our own ground and air units and doesn't
  stack it on a Storm already there. ares checks only that the new spot isn't inside a Storm already
  on the ground, so Citadel leaves out targets within `TEMPLAR_STORM_SPACING` Storm radii of our
  Storms and of other Templar's Storm orders, and gives at most one new Storm order per step (in
  staged tests two Templar stormed overlapping spots at once).
- **Positioning:** otherwise `TEMPLAR_BEHIND` behind its squad's centre, toward our main, never in
  front; out of danger first (`KeepUnitSafe` on the ground grid).
- **Morph** (`morph_pairs`, pure): vs Terran and Protoss (no Storm research there, R1) every Templar
  becomes half an Archon. Vs Zerg, Templar whose Storm has stayed uncastable for
  `TEMPLAR_MORPH_AFTER_S` since the research finished, and those beyond `TEMPLAR_MAX_CASTERS`
  (lowest energy first). Pairs go nearest first through ares's `request_archon_morph` (one
  two-tag `MORPH_ARCHON` command); a pair isn't asked again for `TEMPLAR_MORPH_RETRY_S`.

Storms are counted from our own Storm effects (a new spot each), Archons from new Archon tags.
"""

from typing import TYPE_CHECKING, NamedTuple, Sequence

from ares.behaviors.combat.individual import KeepUnitSafe
from ares.behaviors.combat.individual.auto_use_aoe_ability import AutoUseAOEAbility
from ares.dicts.aoe_ability_to_range import AOE_ABILITY_SPELLS_INFO
from sc2.ids.ability_id import AbilityId
from sc2.ids.effect_id import EffectId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
from sc2.unit import Unit

from bot.army import micro
from bot.constants import (
    TEMPLAR_BEHIND,
    TEMPLAR_MAX_CASTERS,
    TEMPLAR_MORPH_AFTER_S,
    TEMPLAR_MORPH_RETRY_S,
    TEMPLAR_SPOT_SLACK,
    TEMPLAR_STORM_SPACING,
    UPGRADE_CHAINS,
)
from bot.macro.build_executor import race_key

if TYPE_CHECKING:
    from ares import AresBot

STORM = AbilityId.PSISTORM_PSISTORM
STORM_RADIUS: float = AOE_ABILITY_SPELLS_INFO[STORM]["radius"]  # ares's table


class TemplarInfo(NamedTuple):
    tag: int
    position: Point2
    energy: float
    uncastable_for: float  # seconds Storm has stayed uncastable since the research (0 before it)


class TemplarOrder(NamedTuple):
    """One Templar for this step: its unit, the enemies near it, and its squad's centre."""

    unit: Unit
    enemies: list[Unit]
    centre: Point2
    own_tick: bool


def morph_pairs(
    templar: Sequence[TemplarInfo], casters_wanted: bool, max_casters: int = TEMPLAR_MAX_CASTERS,
    morph_after: float = TEMPLAR_MORPH_AFTER_S,
) -> list[tuple[int, int]]:
    """Pairs of Templar tags to morph into Archons (pure). `casters_wanted`: our upgrade chains
    research Storm (vs Zerg); without it every Templar morphs. With it, the Templar uncastable for
    `morph_after` morph, and of the rest those beyond `max_casters`, lowest energy first. Each
    candidate pairs with the nearest other candidate; an odd one waits."""
    if casters_wanted:
        spent = [t for t in templar if t.uncastable_for >= morph_after]
        keep = sorted((t for t in templar if t.uncastable_for < morph_after), key=lambda t: t.energy)
        candidates = spent + keep[: max(0, len(keep) - max_casters)]
    else:
        candidates = list(templar)
    pairs: list[tuple[int, int]] = []
    left = list(candidates)
    while len(left) >= 2:
        first = left.pop(0)
        other = min(left, key=lambda t: first.position.distance_to(t.position))
        left.remove(other)
        pairs.append((first.tag, other.tag))
    return pairs


def behind(centre: Point2, home: Point2, distance: float = TEMPLAR_BEHIND) -> Point2:
    """`distance` behind `centre`, toward `home` (pure; `centre` itself when home is that close)."""
    if centre.distance_to(home) <= distance:
        return centre
    return centre.towards(home, distance)


class TemplarController:
    def __init__(self, bot: "AresBot") -> None:
        self.bot = bot
        self.uncastable_since: dict[int, float] = {}  # Templar tag -> when its Storm went uncastable
        self.asked: dict[int, float] = {}  # Templar tag -> when its morph was requested
        self.archon_tags: set[int] = set()
        self.storm_spots: set[Point2] = set()
        self.counts: dict[str, int] = {"storms": 0, "archons": 0}

    def casters_wanted(self) -> bool:
        return any(UpgradeId.PSISTORMTECH in chain for chain in UPGRADE_CHAINS[race_key(self.bot)].values())

    def step(self, orders: list[TemplarOrder]) -> None:
        self._count()
        if not orders:
            return
        bot = self.bot
        now = bot.time
        researched = UpgradeId.PSISTORMTECH in bot.state.upgrades
        taken = list(self.storm_spots) + [
            o.unit.order_target for o in orders
            if o.unit.is_using_ability(STORM) and isinstance(o.unit.order_target, Point2)
        ]
        spacing = TEMPLAR_STORM_SPACING * STORM_RADIUS
        new_storm = False
        infos: list[TemplarInfo] = []
        for order in orders:
            unit = order.unit
            castable = STORM in unit.abilities
            if castable or not researched:
                self.uncastable_since.pop(unit.tag, None)
            else:
                self.uncastable_since.setdefault(unit.tag, now)
            if unit.is_using_ability(STORM):
                if self._storm(unit, order.enemies):
                    continue
            elif castable and not new_storm:
                free = [e for e in order.enemies if all(e.distance_to(p) > spacing for p in taken)]
                if self._storm(unit, free):
                    new_storm = True
                    continue
            if unit.tag in self.asked and now - self.asked[unit.tag] < TEMPLAR_MORPH_RETRY_S:
                continue  # walking to its partner
            if not unit.is_using_ability(STORM):
                since = self.uncastable_since.get(unit.tag)
                infos.append(TemplarInfo(unit.tag, unit.position, unit.energy, now - since if since is not None else 0.0))
            self._position(unit, order.centre, order.own_tick)
        units = {o.unit.tag: o.unit for o in orders}
        for a, b in morph_pairs(infos, self.casters_wanted()):
            bot.request_archon_morph([units[a], units[b]])
            self.asked[a] = self.asked[b] = now

    def _storm(self, unit: Unit, enemies: list[Unit]) -> bool:
        targets = [e for e in enemies if not e.is_structure]
        if not targets:
            return False
        return AutoUseAOEAbility(unit=unit, targets=targets).execute(self.bot, self.bot.config, self.bot.mediator)

    def _position(self, unit: Unit, centre: Point2, own_tick: bool) -> None:
        bot = self.bot
        if KeepUnitSafe(unit=unit, grid=bot.mediator.get_ground_grid).execute(bot, bot.config, bot.mediator):
            return
        spot = behind(centre, bot.start_location)
        if own_tick and unit.distance_to(spot) > TEMPLAR_SPOT_SLACK:
            micro.move(unit, spot, attack=False)

    def _count(self) -> None:
        """Storms: our Storm effects at spots not seen last step; Archons: new Archon tags."""
        bot = self.bot
        spots = {
            p for effect in bot.state.effects
            if effect.id == EffectId.PSISTORMPERSISTENT and effect.is_mine for p in effect.positions
        }
        self.counts["storms"] += len(spots - self.storm_spots)
        self.storm_spots = spots
        for archon in bot.mediator.get_own_army_dict[UnitTypeId.ARCHON]:
            if archon.tag not in self.archon_tags:
                self.archon_tags.add(archon.tag)
                self.counts["archons"] += 1

    def forget(self, tag: int) -> None:
        self.uncastable_since.pop(tag, None)
        self.asked.pop(tag, None)
