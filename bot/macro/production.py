"""Army production and upgrades (DESIGN.md §3 `macro/production.py`, §4.5.1).

M1 scaffolding so the bot can win games: the §4.5.1 unit mix through ares's SpawnController
(units) and ProductionController (adds Gateways/Robotics Facilities and the tech buildings the
mix needs), plus the §4.5.1 upgrade order through ares's UpgradeController. The air switch and
the combat-sim checks of the mix come later.
"""

import math
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from ares.behaviors.macro import (
    BuildStructure,
    ProductionController,
    SpawnController,
    UpgradeController,
)
from ares.consts import GATEWAY_UNITS
from loguru import logger
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2

from bot.constants import (
    AIR_SWITCH_STALKER_PCT,
    ARCHON_VS_BIO_PCT,
    ARCHON_VS_ZEALOT_PCT,
    ARMY_COMPOSITION_PCT,
    ARMY_PRIORITY,
    CAPITAL_AIR_ADD_PCT,
    CAPITAL_AIR_COLOSSUS_PCT,
    CAPITAL_AIR_STALKER_PLUS_PCT,
    CAPITAL_VS_CARRIER_TEMPEST_PCT,
    EXTRA_GATEWAY_BANK,
    EXTRA_GATEWAY_HOLD_S,
    FOURTH_BASE_WINDOW_S,
    GATEWAY_POWER_RETRY_S,
    GATEWAY_POWER_SEARCH,
    GATEWAY_SPACE_PROBE,
    GATEWAY_SPACE_PYLON_TRIES,
    MAX_GATEWAYS,
    MAX_PRODUCTION_STRUCTURES,
    MINERAL_FLOAT_BANK,
    OBSERVER_COUNT,
    PRODUCTION_CONTROLLER_START_S,
    TEMPLAR_MAX_CASTERS,
    TEMPLAR_SHARE_MAX,
    UPGRADE_CHAINS,
    UPGRADES_START_S,
)
from bot.geometry import in_map
from bot.intel.enemy_mix import EnemyMixTracker
from bot.intel.threat_flags import Threat
from bot.macro.build_executor import bases_ready, race_key, tech_waits

if TYPE_CHECKING:
    from ares import AresBot
    from ares.behaviors.behavior import Behavior

    from bot.defense.defense_planner import DefensePlan


def next_upgrades(
    chains: dict[UnitTypeId, tuple[UpgradeId, ...]], ready: set[UnitTypeId], progress: dict[UpgradeId, float]
) -> list[UpgradeId]:
    """M7 K1 (§4.5.1): the next upgrade of each research building's chain whose building is ready,
    none while that building's current one is in progress (`progress` 0 to 1, python-sc2's
    `already_pending_upgrade`) (pure)."""
    out: list[UpgradeId] = []
    for building, chain in chains.items():
        if building not in ready:
            continue
        for upgrade in chain:
            done = progress.get(upgrade, 0.0)
            if done >= 1:
                continue
            if done == 0:
                out.append(upgrade)
            break
    return out


def unit_proportions(
    shares: dict[UnitTypeId, float], others: int, archons: int, share_max: float = TEMPLAR_SHARE_MAX
) -> dict[UnitTypeId, float]:
    """M7 K3 (§4.5.1): ares count proportions for a mix in percent that may hold ARCHON and
    HIGHTEMPLAR (pure). ARCHON is never in the result: Archons come from Templar Citadel morphs
    (`army/templar.py`), so the Templar share covers the casters (the HIGHTEMPLAR percent) plus two
    Templar for each Archon still missing.

    ares's SpawnController counts only the types in its dict, so the army size is implied by
    `others`, our units of the mix's other types (at least 1): per percent, `others / their percent`
    units. Archons wanted = that times the ARCHON percent, less the `archons` we have. The Templar
    share is capped at `share_max`; the other types share the rest in their ratios."""
    archon_pct = shares.get(UnitTypeId.ARCHON, 0.0)
    ht_pct = shares.get(UnitTypeId.HIGHTEMPLAR, 0.0)
    rest = {u: pct for u, pct in shares.items() if u not in (UnitTypeId.ARCHON, UnitTypeId.HIGHTEMPLAR)}
    rest_pct = sum(rest.values())
    if rest_pct <= 0:
        return {UnitTypeId.HIGHTEMPLAR: 1.0} if archon_pct + ht_pct > 0 else {}
    if archon_pct + ht_pct <= 0:
        return {u: pct / rest_pct for u, pct in rest.items()}
    per_pct = max(others, 1) / rest_pct
    templar = per_pct * ht_pct + 2 * max(0.0, per_pct * archon_pct - archons)
    share = min(share_max, templar / (max(others, 1) + templar))
    out = {u: (1 - share) * pct / rest_pct for u, pct in rest.items()}
    if share > 0:
        out[UnitTypeId.HIGHTEMPLAR] = share
    return out


def templar_floor(
    shares: dict[UnitTypeId, float], others: int, archons: int, templar: int, max_casters: int = TEMPLAR_MAX_CASTERS
) -> int:
    """M7 K3: the Templar count to make at once, ahead of the mix (pure). ares's SpawnController
    stops at the first unit it can't afford, so while it saves gas for a Colossus or Immortal no
    Templar is made (no Templar in 6 of 10 VeryHard Zerg games on `ace729d`, and an unpaired one
    waited out a whole Terran game). The floor is the casters (the HIGHTEMPLAR percent of the army
    `unit_proportions` implies, rounded up, at most `max_casters`), and one more for an unpaired
    Templar beyond them while Archons are still wanted (`templar`: ours now, in production too)."""
    archon_pct = shares.get(UnitTypeId.ARCHON, 0.0)
    ht_pct = shares.get(UnitTypeId.HIGHTEMPLAR, 0.0)
    rest_pct = sum(pct for u, pct in shares.items() if u not in (UnitTypeId.ARCHON, UnitTypeId.HIGHTEMPLAR))
    if rest_pct <= 0 or archon_pct + ht_pct <= 0:
        return 0
    per_pct = max(others, 1) / rest_pct
    casters = min(max_casters, math.ceil(per_pct * ht_pct)) if ht_pct > 0 else 0
    archons_missing = per_pct * archon_pct - archons
    if templar > casters and archons_missing > 0 and (templar - casters) % 2 == 1:
        return templar + 1
    return casters


def gas_starved(minerals: float, vespene: float, wanted_gas: list[float], bank: float = MINERAL_FLOAT_BANK) -> bool:
    """M7 E1 (§4.5.1 economy; pulled into Phase 3 by user decision D28): a mineral bank of at least
    `bank` while the gas bank can't pay for the most gas-hungry thing production wants this tick
    (`wanted_gas`: game-data gas costs of the buildable mix's units, the upgrades due and a Templar
    still missing from the floor) (pure)."""
    return minerals >= bank and bool(wanted_gas) and vespene < max(wanted_gas)


NORMAL, AIR_SWITCH, CAPITAL = "normal", "air switch", "capital air"


def mix_mode(air_harass: bool, air_on: bool, capital_active: bool) -> str:
    """M7 E3 (§4.5.1): capital air while CAPITAL_AIR is ACTIVE, else the air switch while AIR_HARASS
    is active and the enemy air share is at the threshold (its hysteresis is the air ShareSwitch's),
    else normal (pure)."""
    if capital_active:
        return CAPITAL
    if air_harass and air_on:
        return AIR_SWITCH
    return NORMAL


def air_zerg_shares(shares: dict[UnitTypeId, float], race: str, air_on: bool) -> dict[UnitTypeId, float]:
    """M7 D32 (user decision): vs an air-heavy Zerg (the air ShareSwitch on), the Archon and Templar
    shares go to Stalkers: Archons aren't an anti-air tool (D10), and on `f2084c6` CheatInsane Zerg
    Air went 0/10 with about 2 Stalkers per fight (pure)."""
    if race != "Zerg" or not air_on:
        return dict(shares)
    out = dict(shares)
    moved = out.pop(UnitTypeId.ARCHON, 0.0) + out.pop(UnitTypeId.HIGHTEMPLAR, 0.0)
    if moved:
        out[UnitTypeId.STALKER] = out.get(UnitTypeId.STALKER, 0.0) + moved
    return out


def extra_gateway(minerals: float, banked_for: float, gateways: int, building: bool,
                  bank: float = EXTRA_GATEWAY_BANK, hold_s: float = EXTRA_GATEWAY_HOLD_S, max_gateways: int = MAX_GATEWAYS) -> bool:
    """M7 D34: one more Gateway while minerals have stayed at least `bank` for `hold_s`, with none
    under construction and fewer than `max_gateways` (Gateways + Warp Gates) (pure)."""
    return minerals >= bank and banked_for >= hold_s and not building and gateways < max_gateways


def gateway_space(powered_spot: bool, pylon_building: bool, unpowered_spot: bool, spot_tries: int,
                  max_tries: int = GATEWAY_SPACE_PYLON_TRIES) -> str:
    """M7 D35: what an extra-Gateway order does. "gateway" when a powered spot is free; else "wait"
    while a Pylon is under construction (it may power one); else "pylon" when a free spot only
    lacks power and fewer than `max_tries` Pylons were ordered for it; else "none" (pure). ares's
    `BuildStructure` builds nothing without a powered spot, which left 72 of 140 orders in a
    CheatInsane Zerg batch without a Gateway."""
    if powered_spot:
        return "gateway"
    if pylon_building:
        return "wait"
    return "pylon" if unpowered_spot and spot_tries < max_tries else "none"


def mode_shares(base: dict[UnitTypeId, float], mode: str, race: str, carriers_seen: bool) -> dict[UnitTypeId, float]:
    """M7 E3: the mix in percent for `mode` from the normal one (`base`, K3 shares included) (pure)."""
    shares = dict(base)
    if mode == AIR_SWITCH:
        shares[UnitTypeId.STALKER] = shares.get(UnitTypeId.STALKER, 0.0) + AIR_SWITCH_STALKER_PCT
    elif mode == CAPITAL:
        if UnitTypeId.COLOSSUS in shares:
            shares[UnitTypeId.COLOSSUS] = min(shares[UnitTypeId.COLOSSUS], CAPITAL_AIR_COLOSSUS_PCT)
        shares[UnitTypeId.STALKER] = shares.get(UnitTypeId.STALKER, 0.0) + CAPITAL_AIR_STALKER_PLUS_PCT
        for unit, pct in CAPITAL_AIR_ADD_PCT.get(race, {}).items():
            shares[unit] = shares.get(unit, 0.0) + pct
        if race == "Protoss" and carriers_seen:
            shares[UnitTypeId.TEMPEST] = shares.get(UnitTypeId.TEMPEST, 0.0) + CAPITAL_VS_CARRIER_TEMPEST_PCT
    return shares


def starved_seconds(log: list[tuple[float, bool]], now: float) -> float:
    """M7 E1: seconds of `log` ((time, starved) samples, oldest first) spent starved: each starved
    sample counts until the next one, the last until `now` (pure)."""
    total = 0.0
    for (t, starved), nxt in zip(log, [t for t, _ in log[1:]] + [now]):
        if starved:
            total += nxt - t
    return total


@dataclass
class ReserveForUnit:
    """Holds the rest of a MacroPlan (structures, probes) while fewer than `wanted` Gateway units
    exist, a Gateway could make `unit` now, and it can't be afforded yet (§4.2 "the first
    Zealot is top priority"; in 12-pool test games probes and buildings kept taking the minerals
    and the wall Zealot came after the first Zerglings)."""

    unit: UnitTypeId
    wanted: int

    def unmet(self, ai: "AresBot", mediator) -> bool:
        """Fewer than `wanted` Gateway units (made or in production) while a Gateway could make
        one now."""
        have = sum(len(mediator.get_own_army_dict[t]) for t in GATEWAY_UNITS) + ai.unit_pending(self.unit)
        if have >= self.wanted:
            return False
        return any(
            g.is_ready and g.is_idle for g in mediator.get_own_structures_dict[UnitTypeId.GATEWAY]
        ) or bool(mediator.get_own_structures_dict[UnitTypeId.WARPGATE])

    def holds(self, ai: "AresBot", mediator) -> bool:
        return not ai.can_afford(self.unit) and self.unmet(ai, mediator)

    def execute(self, ai: "AresBot", config: dict, mediator) -> bool:
        return self.holds(ai, mediator)


def reserve_for(bot: "AresBot", plan: "DefensePlan") -> Optional[ReserveForUnit]:
    """The plan's reserve: its first tech-ready Gateway unit, if it reserves any."""
    if not plan.reserve_units:
        return None
    unit = next((u for u in plan.unit_priority if u in GATEWAY_UNITS and bot.tech_ready_for_unit(u)), None)
    return ReserveForUnit(unit, plan.reserve_units) if unit is not None else None


class Production:
    def __init__(self, bot: "AresBot"):
        self.bot = bot
        self._power_ordered: dict[int, float] = {}  # Gateway tag -> time a Pylon was ordered for it
        self.mix = EnemyMixTracker(bot)  # M7 K3: updated each intel tick (main.py)
        self.starved = False  # M7 E1: last tick's gas_starved, for the log line on each change
        self.starved_log: deque[tuple[float, bool]] = deque()  # (time, starved) per macro tick, E1's window
        self.mode: str = NORMAL  # M7 E3: the mix selection, and its changes (game seconds, mode)
        self.bank_since: Optional[float] = None  # M7 D34: since when minerals have been >= EXTRA_GATEWAY_BANK
        self.extra_gateways: int = 0
        self.space_pylons: int = 0  # M7 D35: Pylons ordered to make room for an extra Gateway
        self.no_gateway_space = False  # logged once until a Gateway spot is free again
        self.space_pylon_tries: dict[Point2, int] = {}  # Gateway spot -> Pylons ordered for it
        self.gateway_order: Optional[tuple[str, Optional[Point2]]] = None  # the D34/D35 order being given
        self.mode_changes: list[tuple[float, str]] = []

    def gateway_upkeep(self) -> None:
        """Once Warp Gate is researched, ares's SpawnController makes nothing while any ready,
        idle Gateway exists, waiting for it to morph (`spawn_controller.py`, start of
        `execute`). An unpowered Gateway (its Pylon killed) never morphs, which froze all
        production in test games. Morph powered idle Gateways, and put a Pylon next to
        unpowered ones."""
        bot = self.bot
        if UpgradeId.WARPGATERESEARCH not in bot.state.upgrades:
            return
        for gate in bot.mediator.get_own_structures_dict[UnitTypeId.GATEWAY]:
            if not gate.is_ready or not gate.is_idle:
                continue
            if gate.is_powered:
                gate(AbilityId.MORPH_WARPGATE)
                continue
            if bot.time - self._power_ordered.get(gate.tag, -GATEWAY_POWER_RETRY_S) < GATEWAY_POWER_RETRY_S:
                continue
            spot = self._pylon_spot_near(gate.position)
            if spot is None or not bot.can_afford(UnitTypeId.PYLON):
                continue
            worker = bot.mediator.select_worker(target_position=spot, force_close=True)
            if worker is not None and bot.mediator.build_with_specific_worker(
                worker=worker, structure_type=UnitTypeId.PYLON, pos=spot
            ):
                self._power_ordered[gate.tag] = bot.time
                logger.info(f"PRODUCTION Gateway at {gate.position.rounded} unpowered: Pylon at {spot.rounded} ({bot.time_formatted})")

    def _extra_gateway_behaviors(self, schedule_finished: bool, plan: "DefensePlan") -> list["Behavior"]:
        """M7 D34/D35: the extra Gateway, or a Pylon to make room for one (`gateway_space`). A
        MacroPlan stops at the first behavior that acts (ares `MacroPlan.execute` is `any(...)`), so
        an order given for one step was lost whenever supply, probes or a warp-in acted first (a
        staged test lost 4 of 8): the order is given every step until its building is under
        construction, and only then does the next EXTRA_GATEWAY_HOLD_S of bank start."""
        bot = self.bot
        if bot.minerals >= EXTRA_GATEWAY_BANK:
            self.bank_since = bot.time if self.bank_since is None else self.bank_since
        else:
            self.bank_since = None
        structures = bot.mediator.get_own_structures_dict
        gateways = len(structures[UnitTypeId.GATEWAY]) + len(structures[UnitTypeId.WARPGATE])
        building = bool(bot.mediator.get_building_counter[UnitTypeId.GATEWAY]) or any(
            not g.is_ready for g in structures[UnitTypeId.GATEWAY]
        )
        if building and self.gateway_order is not None and self.gateway_order[0] == "gateway":
            self.gateway_order = None  # it went through
            self.bank_since = bot.time if self.bank_since is not None else None
        banked_for = 0.0 if self.bank_since is None else bot.time - self.bank_since
        after_opener = schedule_finished or bot.time >= PRODUCTION_CONTROLLER_START_S
        if not (after_opener and not plan.hold_tech and extra_gateway(bot.minerals, banked_for, gateways, building)):
            if not building:
                self.gateway_order = None
            return []
        powered = bot.mediator.request_building_placement(
            base_location=bot.start_location, structure_type=UnitTypeId.GATEWAY,
            within_psionic_matrix=True, reserve_placement=False, production=True,
        )
        pylons = structures[UnitTypeId.PYLON]
        pylon_building = bool(bot.mediator.get_building_counter[UnitTypeId.PYLON]) or any(not p.is_ready for p in pylons)
        base, spot = (None, None) if powered or pylon_building else self._unpowered_gateway_spot()
        action = gateway_space(powered is not None, pylon_building, spot is not None, self.space_pylon_tries.get(spot, 0))
        if action == "gateway":
            if self.gateway_order != ("gateway", None):
                self.gateway_order = ("gateway", None)
                self.extra_gateways += 1
                self.no_gateway_space = False
                logger.info(f"PRODUCTION {bot.time_formatted} extra Gateway ({gateways + 1}) at {powered.rounded}: {bot.minerals} minerals banked for {banked_for:.0f} s")
            return [BuildStructure(bot.start_location, UnitTypeId.GATEWAY)]
        if action == "pylon":
            # the free Pylon placement nearest the spot (not ares's production Pylon spots, which can be farther)
            if self.gateway_order != ("pylon", spot):
                self.gateway_order = ("pylon", spot)
                self.space_pylons += 1
                self.space_pylon_tries[spot] = self.space_pylon_tries.get(spot, 0) + 1
                logger.info(f"PRODUCTION {bot.time_formatted} Pylon for Gateway space near {spot.rounded} ({gateways} Gateways, no powered spot free)")
            return [BuildStructure(base, UnitTypeId.PYLON, closest_to=spot, find_alternative=False, production=False)]
        self.gateway_order = None
        if action == "none":
            self.bank_since = bot.time  # looked again only after another EXTRA_GATEWAY_HOLD_S of bank
            if not self.no_gateway_space:
                self.no_gateway_space = True
                logger.info(f"PRODUCTION {bot.time_formatted} no Gateway space left at our bases ({gateways} Gateways)")
        return []  # "wait": a Pylon is under construction

    def _unpowered_gateway_spot(self) -> tuple[Optional[Point2], Optional[Point2]]:
        """(base location, spot) of a free Gateway placement without power at one of our bases,
        nearest the main first (ares's placements; `find_alternative` off, so no other base).
        ares offers a base's free spot nearest `closest_to`, so a spot that had its
        GATEWAY_SPACE_PYLON_TRIES is passed over by asking again from GATEWAY_SPACE_PROBE away on
        each side of the base."""
        bot = self.bot
        bases = [bot.start_location] + [base for base, _ in bot.mediator.get_own_expansions]  # the list leaves out the main
        found: Optional[tuple[Point2, Point2]] = None
        for base in bases:
            if not any(th.distance_to(base) < 3 for th in bot.townhalls):
                continue
            d = GATEWAY_SPACE_PROBE
            for near in (base, base.offset((d, 0)), base.offset((-d, 0)), base.offset((0, d)), base.offset((0, -d))):
                spot = bot.mediator.request_building_placement(
                    base_location=base, structure_type=UnitTypeId.GATEWAY, closest_to=near,
                    within_psionic_matrix=False, reserve_placement=False, find_alternative=False,
                )
                if spot is None:
                    break  # nothing free at this base
                if self.space_pylon_tries.get(spot, 0) < GATEWAY_SPACE_PYLON_TRIES:
                    return base, spot
                found = found or (base, spot)
        return found if found is not None else (None, None)  # only spots that had their tries: "none"

    def _pylon_spot_near(self, point: Point2) -> Optional[Point2]:
        bot = self.bot
        cx, cy = round(point.x), round(point.y)
        spots = [
            Point2((cx + dx, cy + dy))
            for dx in range(-GATEWAY_POWER_SEARCH, GATEWAY_POWER_SEARCH + 1)
            for dy in range(-GATEWAY_POWER_SEARCH, GATEWAY_POWER_SEARCH + 1)
        ]
        spots = [
            p for p in spots
            if in_map(bot, p) and p.distance_to(point) <= GATEWAY_POWER_SEARCH
            and bot.mediator.can_place_structure(position=p, structure_type=UnitTypeId.PYLON)
        ]
        return min(spots, key=lambda p: p.distance_to(point), default=None)

    def composition(self, tech_ready_only: bool = False) -> dict[UnitTypeId, dict[str, float]]:
        """ares composition dict for the enemy race; vs Random, the vs-T mix until the race is
        seen (§4.1 treats Random like Terran until then).

        M7 K3: vs T an Archon share while the remembered enemy army is mostly biological, vs P while
        it is Zealot-heavy (`EnemyMixTracker` switches); Archons become a Templar share
        (`unit_proportions`), never an ARCHON entry (ares would merge any two idle Templar).

        `tech_ready_only` keeps only units whose tech is ready and rescales their shares. ares's
        SpawnController fills each unit up to its share of the current army, so a unit that
        can't be built yet (a Colossus before the Robotics Bay) otherwise leaves the rest of the
        production idle once the buildable units reach their shares.
        """
        bot = self.bot
        shares, others, archons = self._mix_counts()
        proportions = unit_proportions(shares, others, archons)
        if tech_ready_only:
            ready = {u: p for u, p in proportions.items() if bot.tech_ready_for_unit(u)}
            if ready:
                proportions = ready
        total = sum(proportions.values())
        return {
            unit: {"proportion": p / total, "priority": ARMY_PRIORITY[unit]}
            for unit, p in proportions.items()
        }

    def _mix_counts(self) -> tuple[dict[UnitTypeId, float], int, int]:
        """This tick's mix in percent (with the K3 Archon switches), our units of its types other
        than Archons and Templar, and our Archons (in production too)."""
        bot = self.bot
        race = race_key(bot)
        shares = dict(ARMY_COMPOSITION_PCT[race])
        extra = 0.0
        if race == "Terran" and self.mix.vs_bio.on:
            extra = ARCHON_VS_BIO_PCT
        elif race == "Protoss" and self.mix.vs_zealots.on:
            extra = ARCHON_VS_ZEALOT_PCT
        if extra:
            shares[UnitTypeId.ARCHON] = shares.get(UnitTypeId.ARCHON, 0.0) + extra
        # M7 E3: the air switch / capital-air mix
        flags = getattr(bot, "flags", None)
        mode = mix_mode(
            flags is not None and flags.is_active(Threat.AIR_HARASS), self.mix.air.on,
            flags is not None and flags.capital_air() == "ACTIVE",
        )
        if mode != self.mode:
            logger.info(f"MIX {bot.time_formatted} {self.mode} -> {mode}")
            self.mode_changes.append((round(bot.time, 1), mode))
            self.mode = mode
        detectors = getattr(bot, "detectors", None)
        carriers = detectors is not None and "CARRIER" in detectors.first_seen
        shares = mode_shares(air_zerg_shares(shares, race, self.mix.air.on), mode, race, carriers)
        count = bot.mediator.get_own_unit_count
        others = sum(count(unit_type_id=u) for u in shares if u not in (UnitTypeId.ARCHON, UnitTypeId.HIGHTEMPLAR))
        return shares, others, count(unit_type_id=UnitTypeId.ARCHON)

    def templar_tech_wanted(self) -> bool:
        """M7 D32: False vs an air-heavy Zerg (the air ShareSwitch on), when the mix has no Templar:
        the Templar Archives' timed step and Storm research wait too."""
        return not (race_key(self.bot) == "Zerg" and self.mix.air.on)

    def starved_for(self) -> float:
        """M7 E1: gas-starved seconds within the last FOURTH_BASE_WINDOW_S (`starved_seconds`)."""
        return starved_seconds(list(self.starved_log), self.bot.time)

    def templar_missing(self) -> int:
        """M7 K3: Templar short of `templar_floor` (0 without the Templar Archives)."""
        bot = self.bot
        if not bot.tech_ready_for_unit(UnitTypeId.HIGHTEMPLAR):
            return 0
        shares, others, archons = self._mix_counts()
        have = bot.mediator.get_own_unit_count(unit_type_id=UnitTypeId.HIGHTEMPLAR)
        return max(0, templar_floor(shares, others, archons, have) - have)

    def gateway_mix(self, comp: dict[UnitTypeId, dict[str, float]]) -> dict[UnitTypeId, dict[str, float]]:
        """The mix's Gateway units for freeflow spending (defense, a mineral float), without High
        Templar: they are gas-heavy and only wanted at their share."""
        return {u: info for u, info in comp.items() if u in GATEWAY_UNITS and u != UnitTypeId.HIGHTEMPLAR}

    def _next_upgrades(self, allow_forge: bool) -> list[UpgradeId]:
        """M7 K1: one upgrade per research building that stands ready (the Forge's only while the
        DefensePlan allows the Forge, §4.2 one-base; the Twilight's and Templar Archives' only on
        TECH_MIN_BASES, D29)."""
        bot = self.bot
        chains = dict(UPGRADE_CHAINS[race_key(bot)])
        if not allow_forge:
            chains.pop(UnitTypeId.FORGE, None)
        flags = getattr(bot, "flags", None)
        if flags is not None and flags.capital_air() is not None and UnitTypeId.TWILIGHTCOUNCIL in chains:
            # M7 E3 (§4.2 capital air WARNING): Blink moves up the Twilight chain
            chain = chains[UnitTypeId.TWILIGHTCOUNCIL]
            if UpgradeId.BLINKTECH in chain:
                chains[UnitTypeId.TWILIGHTCOUNCIL] = (UpgradeId.BLINKTECH,) + tuple(u for u in chain if u != UpgradeId.BLINKTECH)
        bases = bases_ready(bot)
        chains = {b: chain for b, chain in chains.items() if not tech_waits(b, bases)}  # M7 D29
        if not self.templar_tech_wanted():
            chains.pop(UnitTypeId.TEMPLARARCHIVE, None)  # M7 D32: no Storm while no Templar are wanted
        ready = {b for b in chains if any(s.is_ready for s in bot.mediator.get_own_structures_dict[b])}
        progress = {u: bot.already_pending_upgrade(u) for chain in chains.values() for u in chain}
        return next_upgrades(chains, ready, progress)

    def defense_behaviors(self, plan: "DefensePlan") -> list["Behavior"]:
        """§4.2 plan units, ahead of everything else (Defense > Economy, §3): the first
        tech-ready unit of `plan.unit_priority` from every idle producer, and with
        `all_gateways_producing` the Gateway share of the mix without waiting for a bank."""
        bot = self.bot
        out: list["Behavior"] = []
        unit = next((u for u in plan.unit_priority if bot.tech_ready_for_unit(u)), None)
        if unit is not None:
            out.append(SpawnController({unit: {"proportion": 1.0, "priority": 0}}, freeflow_mode=True))
        if (reserve := reserve_for(bot, plan)) is not None:
            if reserve.unit != unit:
                out.append(SpawnController({reserve.unit: {"proportion": 1.0, "priority": 0}}, freeflow_mode=True))
            out.append(reserve)
        if plan.all_gateways_producing:
            gateway_mix = self.gateway_mix(self.composition(tech_ready_only=True))
            if gateway_mix:
                out.append(SpawnController(gateway_mix, freeflow_mode=True))
        return out

    def behaviors(self, schedule_finished: bool, plan: "DefensePlan") -> list["Behavior"]:
        """Behaviors for this tick's MacroPlan, after the economy and the opener schedule.
        ProductionController (more Gateways/Robos and their tech) starts once the opener's timed
        schedule is finished, or at `PRODUCTION_CONTROLLER_START_S` at the latest. Upgrades wait
        while the DefensePlan delays the Forge (§4.2 one-base)."""
        bot = self.bot
        comp = self.composition()  # full mix: ProductionController techs toward all of it
        if UnitTypeId.HIGHTEMPLAR in comp and tech_waits(UnitTypeId.TEMPLARARCHIVE, bases_ready(bot)):
            # M7 D29: on one base no tech-up toward Templar (it adds a Twilight and Templar Archives)
            rest = {u: info for u, info in comp.items() if u != UnitTypeId.HIGHTEMPLAR}
            total = sum(info["proportion"] for info in rest.values()) or 1.0
            comp = {u: {**info, "proportion": info["proportion"] / total} for u, info in rest.items()}
        buildable = self.composition(tech_ready_only=True)
        out: list["Behavior"] = []
        upgrades: list[UpgradeId] = []
        if not plan.hold_tech and bot.time >= UPGRADES_START_S:
            # M7 K1: each research building works through its own chain; with auto tech-up off an
            # upgrade never starts a building (given a whole list, UpgradeController once started
            # Forge, Twilight and Robo Bay at 5:00 in a Hard-Zerg loss). The buildings come from
            # their timed steps (constants.TECH_STEPS) or the unit mix
            upgrades = self._next_upgrades(plan.allow_forge)
            for upgrade in upgrades:
                out.append(UpgradeController([upgrade], base_location=bot.start_location, auto_tech_up_enabled=False))
        observers = len(bot.mediator.get_own_army_dict[UnitTypeId.OBSERVER]) + bot.unit_pending(
            UnitTypeId.OBSERVER
        )
        if observers < OBSERVER_COUNT:
            out.append(
                SpawnController(
                    {UnitTypeId.OBSERVER: {"proportion": 1.0, "priority": 0}},
                    freeflow_mode=True,
                    maximum=OBSERVER_COUNT - observers,
                )
            )
        flags = getattr(bot, "flags", None)
        if (
            flags is not None and flags.capital_air() is not None
            and not (bot.structures(UnitTypeId.STARGATE) or bot.mediator.get_building_counter[UnitTypeId.STARGATE])
            and bot.can_afford(UnitTypeId.STARGATE)
        ):
            # M7 E3 (§4.2 capital air WARNING): one Stargate goes down early
            out.append(BuildStructure(bot.start_location, UnitTypeId.STARGATE))
        # M7 D34/D35: a Gateway more while a mineral bank stays (after the opener; not while tech
        # waits), ahead of the unit spenders below
        out.extend(self._extra_gateway_behaviors(schedule_finished, plan))
        templar = self.templar_missing()
        if templar > 0:
            # M7 K3: Templar up to the floor, before the mix's SpawnController (as Observers are)
            out.append(
                SpawnController(
                    {UnitTypeId.HIGHTEMPLAR: {"proportion": 1.0, "priority": 0}}, freeflow_mode=True, maximum=templar
                )
            )
        out.append(SpawnController(buildable))
        # ares's SpawnController stops at the first unit it can't afford (ares-sc2
        # behaviors/macro/spawn_controller.py), so while it saves gas for a Colossus or Immortal no
        # Gateway unit is made. Spend a mineral float on the Gateway share of the mix meanwhile.
        # M7 E1 (D28): while gas-starved, on Zealots only, so the gas bank can grow (the float's
        # Stalkers took every 50 gas, and Templar, Storm and Blink waited for gas until 200 supply)
        wanted_gas = [bot.calculate_cost(u).vespene for u in buildable] + [bot.calculate_cost(u).vespene for u in upgrades]
        if templar > 0:
            wanted_gas.append(bot.calculate_cost(UnitTypeId.HIGHTEMPLAR).vespene)
        starved = gas_starved(bot.minerals, bot.vespene, [g for g in wanted_gas if g > 0])
        self.starved_log.append((bot.time, starved))
        while self.starved_log and bot.time - self.starved_log[0][0] > FOURTH_BASE_WINDOW_S:
            self.starved_log.popleft()
        if starved != self.starved:
            self.starved = starved
            logger.info(f"PRODUCTION {bot.time_formatted} gas-starved {'on: the float makes Zealots' if starved else 'off'} ({bot.minerals} minerals, {bot.vespene} gas)")
        if bot.minerals >= MINERAL_FLOAT_BANK:
            # M7 D30: not vs an air army (Zealots can't hit air); the mix's Gateway units then, as before D28
            if starved and not self.mix.air.on:
                out.append(SpawnController({UnitTypeId.ZEALOT: {"proportion": 1.0, "priority": 0}}, freeflow_mode=True))
            elif gateway_mix := self.gateway_mix(buildable):
                out.append(SpawnController(gateway_mix, freeflow_mode=True))
        if (schedule_finished or bot.time >= PRODUCTION_CONTROLLER_START_S) and not plan.hold_tech:
            out.append(
                ProductionController(
                    comp,
                    base_location=bot.start_location,
                    max_production_structures=MAX_PRODUCTION_STRUCTURES,
                )
            )
        return out
