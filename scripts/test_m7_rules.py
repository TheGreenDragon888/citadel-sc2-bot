"""Offline tests for M7's pure rules (docs/M7_PLAN.md; no game needed).

    poetry run python scripts/test_m7_rules.py

Each M7 step adds its cases here: the fight-input text (O1), the expansion-first proxy check
(B6), the main re-scout gate (B4), the cannon-rush ramp hold (B7), the Observer trip gate (B8),
and Phase 2's out-ranged rule (C1), eligibility (C2), retreat shooting (C3), penalty (C5), the melee
rule (C6, D18), weaponless units (C7, D19), home-defense hysteresis (C9, D22) and melee units in
the out-range share (C10, D23).
Units are stand-ins with only the attributes the rules read (no game needed). Prints PASS/FAIL per case; exits 1 on any failure.
"""

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

ROOT: Path = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

import run  # noqa: E402,F401  (puts ares-sc2 on sys.path)
from sc2.ids.unit_typeid import UnitTypeId  # noqa: E402
from sc2.ids.upgrade_id import UpgradeId  # noqa: E402
from sc2.position import Point2  # noqa: E402

from bot.army.army import Army, home_engages  # noqa: E402
from bot.army.blink import BlinkState, blink_back, blink_finish, blink_in_points, wave_allows  # noqa: E402
from bot.army.engagement import FightInputs, composition_text, value_level  # noqa: E402
from bot.army.micro import retreat_may_shoot  # noqa: E402
from bot.army.ranges import (  # noqa: E402
    can_hit,
    has_weapon,
    outrange_penalty,
    outranged,
    outranges,
    outranges_hitters,
    range_vs,
    reach,
)
from bot.constants import (  # noqa: E402
    BLINK_IN_MIN_STALKERS,
    BLINK_IN_PER_TARGET_S,
    BLINK_IN_WAVE_S,
    BLINK_RANGE,
    CANNON_RUSH_RADIUS,
    UPGRADE_CHAINS,
    MAIN_STALE_FROM_S,
    MELEE_RANGE_MAX,
    OUTRANGED_MARGIN,
    MAIN_STALE_S,
    PROXY_NATURAL_WAIT_UNTIL_S,
)
from bot.defense.defense_planner import rush_cannon_near, safe_hold_point  # noqa: E402
from bot.intel.detectors import (  # noqa: E402
    PROXY_EXPANSION,
    PROXY_MISSING,
    PROXY_PRODUCTION,
    PROXY_WAIT,
    proxy_production_check,
)
from bot.intel.scout_planner import main_rescout_due, observer_trip_ok, trip_seconds  # noqa: E402
from bot.macro.build_executor import tech_waits  # noqa: E402
from bot.macro.production import gas_starved, next_upgrades, templar_floor, unit_proportions  # noqa: E402
from bot.army.templar import TemplarInfo, behind, morph_pairs  # noqa: E402
from bot.intel.enemy_mix import EnemyMix, MixEntry, fade, measure, switch  # noqa: E402

# (name, function, args, kwargs, expected)
CASES: list[tuple[str, Callable, tuple, dict, Any]] = []


def case(name: str, fn: Callable, *args, expected: Any, **kwargs) -> None:
    CASES.append((name, fn, args, kwargs, expected))


# -- O1: fight inputs ----------------------------------------------------------------------------
case("composition: nothing", composition_text, [], expected=("nothing", 0.0))
case(
    "composition: counts by type, highest total value first",
    composition_text,
    [("ZEALOT", 100.0)] * 5 + [("TEMPEST", 425.0)] * 2 + [("VOIDRAY", 400.0)],
    expected=("2 TEMPEST 5 ZEALOT 1 VOIDRAY", 1750.0),
)
case(
    "composition: equal value sorts by name",
    composition_text,
    [("STALKER", 175.0), ("ADEPT", 175.0)],
    expected=("1 ADEPT 1 STALKER", 350.0),
)
case(
    "composition: at most max_types types, the rest counted",
    composition_text,
    [("A", 50.0), ("B", 40.0), ("C", 30.0), ("C", 30.0)],
    max_types=2,
    expected=("2 C 1 A +1 more", 150.0),
)
case(
    "fight inputs text",
    lambda: FightInputs("22 STALKER", 3850.0, "8 TEMPEST", 3400.0).text(),
    expected="vs 8 TEMPEST (3400) | ours 22 STALKER (3850)",
)

# -- B6: expansion-first proxy check (§4.4 rows 7/10) ----------------------------------------------
case("proxy: production in the main", proxy_production_check, True, False, False, 90.0, expected=PROXY_PRODUCTION)
case("proxy: production in the main, natural irrelevant", proxy_production_check, True, True, True, 90.0, expected=PROXY_PRODUCTION)
case("proxy: none, townhall at their natural (Nexus first)", proxy_production_check, False, True, True, 90.0, expected=PROXY_EXPANSION)
case("proxy: none, townhall seen before the natural was looked at", proxy_production_check, False, True, False, 90.0, expected=PROXY_EXPANSION)
case("proxy: none, natural not looked at yet: wait", proxy_production_check, False, False, False, 95.0, expected=PROXY_WAIT)
case(
    "proxy: none, natural looked at and empty: missing",
    proxy_production_check, False, False, True, 95.0, expected=PROXY_MISSING,
)
case(
    "proxy: none, natural never looked at by the deadline: missing",
    proxy_production_check, False, False, False, PROXY_NATURAL_WAIT_UNTIL_S, expected=PROXY_MISSING,
)

# -- B4: the main re-scout gate (§5) ---------------------------------------------------------------
T = MAIN_STALE_FROM_S + 300.0
case("rescout: before MAIN_STALE_FROM_S never", main_rescout_due, MAIN_STALE_FROM_S - 1, None, -MAIN_STALE_S, expected=False)
case("rescout: main never seen, none sent", main_rescout_due, T, None, -MAIN_STALE_S, expected=True)
case("rescout: main seen recently", main_rescout_due, T, T - MAIN_STALE_S + 1, -MAIN_STALE_S, expected=False)
case("rescout: main stale, one sent recently", main_rescout_due, T, T - MAIN_STALE_S - 1, T - 10, expected=False)
case("rescout: main stale, last one long ago", main_rescout_due, T, T - MAIN_STALE_S - 1, T - MAIN_STALE_S, expected=True)

# -- B7: the cannon-rush ramp hold (§4.2, D14) ----------------------------------------------------
MAIN, NAT = Point2((20, 20)), Point2((40, 30))
case("cannon hold: no Cannon", rush_cannon_near, [], [MAIN, NAT], CANNON_RUSH_RADIUS, expected=False)
case("cannon hold: a Cannon near the natural", rush_cannon_near, [Point2((45, 35))], [MAIN, NAT], CANNON_RUSH_RADIUS, expected=True)
case("cannon hold: a Cannon in the main", rush_cannon_near, [Point2((25, 15))], [MAIN, NAT], CANNON_RUSH_RADIUS, expected=True)
case(
    "cannon hold: a Cannon far from both",
    rush_cannon_near, [Point2((40 + CANNON_RUSH_RADIUS + 1, 30))], [MAIN, NAT], CANNON_RUSH_RADIUS, expected=False,
)

# the hold point steps toward our main out of finished Cannons' reach (`_safe`, B7)
RAMP, HOME = Point2((30, 20)), Point2((20, 20))
def _cover_x_above(limit: float, count: int = 1):  # noqa: E302
    return lambda p: count if p.x > limit else 0
case("hold point: not covered, unchanged", safe_hold_point, RAMP, HOME, _cover_x_above(40), 2.0, 6, expected=RAMP)
case("hold point: covered, first clear step", safe_hold_point, RAMP, HOME, _cover_x_above(25.5), 2.0, 6, expected=Point2((24, 20)))
case(
    "hold point: covered everywhere, the spot fewest cover",
    safe_hold_point, RAMP, HOME, lambda p: 2 if p.x > 25 else 1, 2.0, 6, expected=Point2((24, 20)),
)
case("hold point: equal cover everywhere, the original", safe_hold_point, RAMP, HOME, lambda p: 1, 2.0, 6, expected=RAMP)

# -- B8: the Observer expansion trip gate (§4.3, D15) ---------------------------------------------
case("trip: straight-line legs at speed 2", trip_seconds, Point2((0, 0)), [Point2((3, 4)), Point2((3, 10))], 2.0, expected=5.5)
case("trip: no speed", trip_seconds, Point2((0, 0)), [Point2((3, 4))], 0.0, expected=float("inf"))
case("trip: no points", trip_seconds, Point2((0, 0)), [], 2.0, expected=0.0)
case("observer trip: a second free Observer", observer_trip_ok, T, 200.0, T - 10, T - 10, 2, expected=True)
case("observer trip: back before the main goes stale", observer_trip_ok, T, MAIN_STALE_S - 20, T - 10, T - 10, 1, expected=True)
case("observer trip: the main goes stale during it", observer_trip_ok, T, MAIN_STALE_S + 40, T - 10, T - 10, 1, expected=False)
case("observer trip: main never seen", observer_trip_ok, T, 10.0, None, -MAIN_STALE_S, 1, expected=False)
case("observer trip: all before MAIN_STALE_FROM_S", observer_trip_ok, 0.0, MAIN_STALE_FROM_S - 1, None, -MAIN_STALE_S, 1, expected=True)

# -- Phase 2: stand-in units (ranges as in game data: Stalker 6, Tempest 10 ground / 14 air) -------
def unit(name, ground=0.0, air=0.0, flying=False, radius=0.5, type_id=None):  # noqa: E302
    return SimpleNamespace(
        name=name, ground_range=ground, air_range=air, can_attack_ground=ground > 0, can_attack_air=air > 0,
        is_flying=flying, radius=radius, type_id=type_id,
    )
STALKER, ZEALOT = unit("stalker", 6, 6, radius=0.625), unit("zealot", 0.1, radius=0.5)  # noqa: E305
TEMPEST, VOIDRAY = unit("tempest", 10, 14, flying=True, radius=1.25), unit("voidray", 6, 6, flying=True, radius=1.0)
CANNON, OVERLORD = unit("cannon", 7, 7, radius=1.125), unit("overlord", flying=True, radius=1.0)
MARINE = unit("marine", 5, 5, radius=0.375)
TANK = unit("sieged tank", 13, radius=0.875)
# no weapon in game data (VERIFY_NOTES "M7 findings"): ares's WEIGHT_COSTS ranges apply (D19), except
# for the Disruptor, which ares has none for
VOIDRAY_DATA = unit("voidray", flying=True, radius=1.0, type_id=UnitTypeId.VOIDRAY)
CARRIER_DATA = unit("carrier", flying=True, radius=1.25, type_id=UnitTypeId.CARRIER)
SENTRY_DATA = unit("sentry", radius=0.5, type_id=UnitTypeId.SENTRY)
DISRUPTOR_DATA = unit("disruptor", radius=0.5, type_id=UnitTypeId.DISRUPTOR)

# C1: the out-ranged rule
case("outranged: they can't hit us", outranged, 6.0, None, OUTRANGED_MARGIN, expected=False)
case("outranged: we can't hit them", outranged, None, 6.0, OUTRANGED_MARGIN, expected=True)
case("outranged: 10 vs 6", outranged, 6.0, 10.0, OUTRANGED_MARGIN, expected=True)
case("outranged: 7 vs 6, inside the margin", outranged, 6.0, 7.0, OUTRANGED_MARGIN, expected=False)
case("outranges: Tempest vs Stalker", outranges, TEMPEST, STALKER, expected=True)
case("outranges: Void Ray vs Stalker", outranges, VOIDRAY, STALKER, expected=False)
case("outranges: Void Ray vs Zealot (can't hit back)", outranges, VOIDRAY, ZEALOT, expected=True)
case("outranges: Cannon vs Zealot (melee, D18)", outranges, CANNON, ZEALOT, expected=False)
case("outranges: Cannon vs Stalker", outranges, CANNON, STALKER, expected=False)
case("outranges: Overlord (no weapon) vs Zealot", outranges, OVERLORD, ZEALOT, expected=False)
case("can_hit: Zealot vs Void Ray", can_hit, ZEALOT, VOIDRAY, expected=False)
case("reach: Tempest vs Stalker", reach, TEMPEST, STALKER, expected=10 + 1.25 + 0.625)
case("reach: Zealot vs Void Ray", reach, ZEALOT, VOIDRAY, expected=None)

# C6 (D18): a melee unit is out-ranged only by enemies it can't hit
case("outranged: melee 0.1 vs 5", outranged, 0.1, 5.0, OUTRANGED_MARGIN, MELEE_RANGE_MAX, expected=False)
case("outranged: at the melee cut-off", outranged, MELEE_RANGE_MAX, 7.0, OUTRANGED_MARGIN, MELEE_RANGE_MAX, expected=False)
case("outranged: just above the cut-off", outranged, MELEE_RANGE_MAX + 0.5, 7.0, OUTRANGED_MARGIN, MELEE_RANGE_MAX, expected=True)
case("outranged: melee that can't hit", outranged, None, 5.0, OUTRANGED_MARGIN, MELEE_RANGE_MAX, expected=True)
case("outranges: Marine vs Zealot", outranges, MARINE, ZEALOT, expected=False)
case("outranges: Tempest vs Zealot (can't hit air)", outranges, TEMPEST, ZEALOT, expected=True)
case("outranges: Marine vs Stalker", outranges, MARINE, STALKER, expected=False)

# C7 (D19): types with no game-data weapon use ares's ranges; with neither, no weapon
case("range: Void Ray (ares 6) vs Stalker", range_vs, VOIDRAY_DATA, STALKER, expected=6.0)
case("range: Carrier (ares 11) vs Void Ray", range_vs, CARRIER_DATA, VOIDRAY, expected=11.0)
case("range: Disruptor (neither)", range_vs, DISRUPTOR_DATA, STALKER, expected=0.0)
case("can_hit: Zealot vs Sentry (ground)", can_hit, ZEALOT, SENTRY_DATA, expected=True)
case("can_hit: our Sentry (ares 5) vs Zealot", can_hit, SENTRY_DATA, ZEALOT, expected=True)
case("outranges: Carrier vs Stalker (11 vs 6)", outranges, CARRIER_DATA, STALKER, expected=True)
case("outranges: Void Ray vs Stalker (6 vs 6)", outranges, VOIDRAY_DATA, STALKER, expected=False)
case("outranges: Void Ray vs Zealot (can't hit back)", outranges, VOIDRAY_DATA, ZEALOT, expected=True)
case("has_weapon: Sentry (ares)", has_weapon, SENTRY_DATA, expected=True)
case("has_weapon: Disruptor (neither)", has_weapon, DISRUPTOR_DATA, expected=False)
case("has_weapon: Overlord", has_weapon, OVERLORD, expected=False)

# C2: only defenders that can hit something in the threat group answer it
case(
    "eligibility: Zealots sit out vs Void Rays",
    lambda: [u.name for u in Army._able([STALKER, ZEALOT], [VOIDRAY])], expected=["stalker"],
)
case(
    "eligibility: both answer a mixed group",
    lambda: [u.name for u in Army._able([STALKER, ZEALOT], [VOIDRAY, ZEALOT])], expected=["stalker", "zealot"],
)
case(
    "eligibility: a weaponless unit of ours stays in (D19)",
    lambda: [u.name for u in Army._able([STALKER, ZEALOT, DISRUPTOR_DATA], [VOIDRAY_DATA])], expected=["stalker", "disruptor"],
)
case(
    "eligibility: our Sentry answers Zealots (ares range)",
    lambda: [u.name for u in Army._able([SENTRY_DATA], [ZEALOT])], expected=["sentry"],
)

# C3: retreating units shoot only enemies that fight back, and only when faster than every threat
case("retreat: faster than every threat", retreat_may_shoot, 4.13, [3.15, 2.25], True, expected=True)
case("retreat: a threat as fast", retreat_may_shoot, 4.13, [3.15, 4.13], True, expected=False)
case("retreat: nothing that fights back", retreat_may_shoot, 4.13, [], False, expected=False)
case("retreat: no threats", retreat_may_shoot, 4.13, [], True, expected=True)

# C5: the out-range penalty, whole levels per share
# C10 (D23): melee units count in the out-range share only when they are all that can hit the enemy
case("share: tank vs Stalkers + Zealots (Zealots left out)", outranges_hitters, TANK, [STALKER, ZEALOT], expected=True)
case("share: tank vs Zealots alone", outranges_hitters, TANK, [ZEALOT], expected=False)
case("share: Marine vs Zealots alone", outranges_hitters, MARINE, [ZEALOT], expected=False)
case("share: Marine vs Stalkers + Zealots", outranges_hitters, MARINE, [STALKER, ZEALOT], expected=False)
case("share: Tempest vs Stalkers", outranges_hitters, TEMPEST, [STALKER], expected=True)

# C9 (D22): home-defense hysteresis
case("home: starts at the gate", home_engages, 5, 5, False, 2, expected=True)
case("home: below the gate, not engaged", home_engages, 4, 5, False, 2, expected=False)
case("home: engaged, fights on at 3", home_engages, 3, 5, True, 2, expected=True)
case("home: engaged, gives up at 2", home_engages, 2, 5, True, 2, expected=False)
case("home: under a Battery the gate is 4", home_engages, 4, 4, False, 2, expected=True)

# K1 (§4.5.1): one upgrade per ready research building, in each chain's order
U, B = UpgradeId, UnitTypeId
case("upgrades vs P: Forge and Twilight ready", next_upgrades, UPGRADE_CHAINS["Protoss"], {B.FORGE, B.TWILIGHTCOUNCIL}, {},
     expected=[U.PROTOSSGROUNDWEAPONSLEVEL1, U.BLINKTECH])
case("upgrades vs Z: Charge before Blink", next_upgrades, UPGRADE_CHAINS["Zerg"], {B.TWILIGHTCOUNCIL}, {}, expected=[U.CHARGE])
case("upgrades vs Z: Blink after Charge is done", next_upgrades, UPGRADE_CHAINS["Zerg"], {B.TWILIGHTCOUNCIL}, {U.CHARGE: 1.0},
     expected=[U.BLINKTECH])
case("upgrades vs T: Blink first", next_upgrades, UPGRADE_CHAINS["Terran"], {B.TWILIGHTCOUNCIL}, {}, expected=[U.BLINKTECH])
case("upgrades: no building, no upgrade", next_upgrades, UPGRADE_CHAINS["Zerg"], set(), {}, expected=[])
case("upgrades: the Forge waits for its current one", next_upgrades, UPGRADE_CHAINS["Terran"], {B.FORGE},
     {U.PROTOSSGROUNDWEAPONSLEVEL1: 0.4}, expected=[])
case("upgrades: the Forge's next after W1", next_upgrades, UPGRADE_CHAINS["Terran"], {B.FORGE},
     {U.PROTOSSGROUNDWEAPONSLEVEL1: 1.0}, expected=[U.PROTOSSGROUNDWEAPONSLEVEL2])
case("upgrades vs Z: Storm once the Archives stand", next_upgrades, UPGRADE_CHAINS["Zerg"], {B.TEMPLARARCHIVE, B.ROBOTICSBAY}, {},
     expected=[U.EXTENDEDTHERMALLANCE, U.PSISTORMTECH])
case("upgrades vs P: no Storm chain", lambda: B.TEMPLARARCHIVE in UPGRADE_CHAINS["Protoss"], expected=False)
case("upgrades: chain done", next_upgrades, {B.ROBOTICSBAY: (U.EXTENDEDTHERMALLANCE,)}, {B.ROBOTICSBAY},
     {U.EXTENDEDTHERMALLANCE: 1.0}, expected=[])

# K2 (§4.5.3): Blink rules
case("blink back: low shields, threatened", blink_back, 0.2, True, 0.25, expected=True)
case("blink back: low shields, not threatened", blink_back, 0.2, False, 0.25, expected=False)
case("blink back: shields fine", blink_back, 0.6, True, 0.25, expected=False)
case("blink in: 12 away, reach 6.5 -> lands 5.5 from it, within range",
     lambda: [p.rounded for p in blink_in_points(Point2((0, 0)), Point2((12, 0)), 6.5)][0], expected=(6, 0))
case("blink in: every spot within BLINK_RANGE",
     lambda: all(Point2((0, 0)).distance_to(p) <= BLINK_RANGE for p in blink_in_points(Point2((0, 0)), Point2((12, 0)), 6.5)), expected=True)
case("blink in: too far for one blink", lambda: list(blink_in_points(Point2((0, 0)), Point2((20, 0)), 6.5)), expected=[])
case("blink in: already near (gain < 2)", lambda: list(blink_in_points(Point2((0, 0)), Point2((7, 0)), 6.5)), expected=[])
case("blink finish: one volley kills, safe, won", blink_finish, 20.0, 26.0, True, 8, 4.0, 7, 3.0, expected=True)
case("blink finish: not enough damage", blink_finish, 40.0, 26.0, True, 8, 4.0, 7, 3.0, expected=False)
case("blink finish: fight not won", blink_finish, 20.0, 26.0, True, 6, 4.0, 7, 3.0, expected=False)
case("blink finish: unsafe landing", blink_finish, 20.0, 26.0, False, 8, 4.0, 7, 3.0, expected=False)
case("blink finish: a short hop isn't worth the Blink", blink_finish, 20.0, 26.0, True, 8, 2.0, 7, 3.0, expected=False)
case("wave: a new one with enough Stalkers", wave_allows, 10.0, None, BLINK_IN_MIN_STALKERS, expected=(True, True))
case("wave: not alone", wave_allows, 10.0, None, BLINK_IN_MIN_STALKERS - 1, expected=(False, False))
case("wave: join within the wave window", wave_allows, 10.0 + BLINK_IN_WAVE_S, 10.0, 0, expected=(True, False))
case("wave: too late to join, too early for a new one", wave_allows, 10.0 + BLINK_IN_WAVE_S + 0.1, 10.0, 9, expected=(False, False))
case("wave: a new one after the budget", wave_allows, 10.0 + BLINK_IN_PER_TARGET_S, 10.0, BLINK_IN_MIN_STALKERS, expected=(True, True))

case("penalty: none", outrange_penalty, 0.0, 4.0, expected=0)
case("penalty: an all-Tempest army", outrange_penalty, 1.0, 4.0, expected=4)
case("penalty: 8 Tempests + 6 Zealots (85% of the value)", outrange_penalty, 3400 / 4000, 4.0, expected=3)
case("penalty: an eighth rounds to 1", outrange_penalty, 0.125, 4.0, expected=1)
case("penalty: under an eighth rounds to 0", outrange_penalty, 0.12, 4.0, expected=0)

# C7 (D19): the value level (ares's mapping, values as health)
case("value level: equal", value_level, 1000.0, 1000.0, expected=5)
case("value level: 1.25x (a fifth left, not above)", value_level, 1250.0, 1000.0, expected=5)
case("value level: 1.3x", value_level, 1300.0, 1000.0, expected=6)
case("value level: 2x", value_level, 2000.0, 1000.0, expected=7)
case("value level: 2.5x", value_level, 2500.0, 1000.0, expected=8)
case("value level: 10x", value_level, 10000.0, 1000.0, expected=10)
case("value level: half", value_level, 1000.0, 2000.0, expected=3)
case("value level: nothing of ours", value_level, 0.0, 1000.0, expected=0)
case("fight inputs: value cap and penalty", lambda: FightInputs("4 STALKER", 700, "4 VOIDRAY", 1000, 1, 3).text(),
     expected="vs 4 VOIDRAY (1000) | ours 4 STALKER (700); value cap 3; -1 out-ranged")


# K3: the remembered enemy army's mix (supply-weighted, fighting units only, old sightings fade)
def _mix(*entries):  # noqa: E302
    return measure([MixEntry(*e) for e in entries], fresh_s=60.0)


case("fade: fresh", fade, 30.0, 60.0, expected=1.0)
case("fade: halfway out", fade, 90.0, 60.0, expected=0.5)
case("fade: gone", fade, 150.0, 60.0, expected=0.0)
case("mix: nothing seen", _mix, expected=EnemyMix())
case("mix: 10 Marines (bio) + 2 Tanks", _mix, ("MARINE", 10.0, True, True, 0.0), ("SIEGETANK", 6.0, False, True, 0.0),
     expected=EnemyMix(16.0, 10 / 16, 0.0))
case("mix: Medivacs can't attack, left out", _mix, ("MARINE", 10.0, True, True, 0.0), ("MEDIVAC", 4.0, True, False, 0.0),
     expected=EnemyMix(10.0, 1.0, 0.0))
case("mix: 8 Zealots + 4 Stalkers", _mix, ("ZEALOT", 16.0, True, True, 0.0), ("STALKER", 8.0, False, True, 0.0),
     expected=EnemyMix(24.0, 16 / 24, 16 / 24))
case("mix: old Zealots fade to half", _mix, ("ZEALOT", 16.0, True, True, 90.0), ("STALKER", 8.0, False, True, 0.0),
     expected=EnemyMix(16.0, 0.5, 0.5))
case("switch: on at the threshold", switch, False, 0.5, 0.5, None, 100.0, 60.0, expected=(True, None))
case("switch: stays off below", switch, False, 0.4, 0.5, None, 100.0, 60.0, expected=(False, None))
case("switch: below, the hold starts", switch, True, 0.4, 0.5, None, 100.0, 60.0, expected=(True, 100.0))
case("switch: still within the hold", switch, True, 0.4, 0.5, 100.0, 159.0, 60.0, expected=(True, 100.0))
case("switch: off after the hold", switch, True, 0.4, 0.5, 100.0, 160.0, 60.0, expected=(False, None))
case("switch: back above resets the hold", switch, True, 0.6, 0.5, 100.0, 150.0, 60.0, expected=(True, None))

# K3: Archon shares become Templar (production.unit_proportions); never an ARCHON entry
_Z = {UnitTypeId.ZEALOT: 25, UnitTypeId.STALKER: 25, UnitTypeId.IMMORTAL: 25, UnitTypeId.COLOSSUS: 10,
      UnitTypeId.ARCHON: 15, UnitTypeId.HIGHTEMPLAR: 8}
_P = {UnitTypeId.STALKER: 40, UnitTypeId.IMMORTAL: 25, UnitTypeId.COLOSSUS: 25, UnitTypeId.ZEALOT: 10}


def _props(shares, others, archons, share_max=0.5):  # noqa: E302
    return {u.name: round(p, 3) for u, p in unit_proportions(shares, others, archons, share_max).items()}


case("proportions: no Templar in the mix (vs P)", _props, _P, 20, 0,
     expected={"STALKER": 0.4, "IMMORTAL": 0.25, "COLOSSUS": 0.25, "ZEALOT": 0.1})
case("proportions: vs Z, no Archons yet: casters + 2 per Archon", _props, _Z, 85, 0,
     expected={"ZEALOT": 0.203, "STALKER": 0.203, "IMMORTAL": 0.203, "COLOSSUS": 0.081, "HIGHTEMPLAR": 0.309})
case("proportions: vs Z, Archons at their share: casters only", _props, _Z, 85, 15,
     expected={"ZEALOT": 0.269, "STALKER": 0.269, "IMMORTAL": 0.269, "COLOSSUS": 0.108, "HIGHTEMPLAR": 0.086})
case("proportions: vs Z, no army yet counts as one unit", _props, _Z, 0, 0,
     expected={"ZEALOT": 0.203, "STALKER": 0.203, "IMMORTAL": 0.203, "COLOSSUS": 0.081, "HIGHTEMPLAR": 0.309})
case("proportions: vs P with the Zealot switch on: Templar for Archons only", _props, {**_P, UnitTypeId.ARCHON: 10}, 20, 0,
     expected={"STALKER": 0.333, "IMMORTAL": 0.208, "COLOSSUS": 0.208, "ZEALOT": 0.083, "HIGHTEMPLAR": 0.167})
case("proportions: Archons enough and no casters: no Templar", _props, {**_P, UnitTypeId.ARCHON: 10}, 20, 2,
     expected={"STALKER": 0.4, "IMMORTAL": 0.25, "COLOSSUS": 0.25, "ZEALOT": 0.1})
case("proportions: the Templar share is capped", _props, {**_P, UnitTypeId.ARCHON: 100}, 20, 0, 0.5,
     expected={"STALKER": 0.2, "IMMORTAL": 0.125, "COLOSSUS": 0.125, "ZEALOT": 0.05, "HIGHTEMPLAR": 0.5})
case("proportions: sum to 1", lambda: round(sum(unit_proportions(_Z, 40, 3).values()), 9), expected=1.0)
case("floor: vs Z, small army: one caster", templar_floor, _Z, 10, 0, 0, 4, expected=1)
case("floor: vs Z, 40 units: casters up to the cap", templar_floor, _Z, 40, 0, 0, 4, expected=4)
case("floor: vs Z, casters there: nothing more", templar_floor, _Z, 40, 0, 4, 4, expected=4)
case("floor: vs Z, an unpaired Templar beyond the casters gets a partner", templar_floor, _Z, 40, 0, 5, 4, expected=6)
case("floor: vs Z, a pair beyond the casters: nothing more", templar_floor, _Z, 40, 0, 6, 4, expected=4)
case("floor: vs Z, Archons enough: no partner", templar_floor, _Z, 40, 10, 5, 4, expected=4)
case("floor: vs P, no Archon share: none", templar_floor, _P, 20, 0, 1, 4, expected=0)
case("floor: vs P with the Zealot switch, an unpaired Templar gets a partner", templar_floor, {**_P, UnitTypeId.ARCHON: 10}, 20, 0, 1, 4,
     expected=2)
case("one-base wait: Twilight on one base waits", tech_waits, UnitTypeId.TWILIGHTCOUNCIL, 1, False, 2, expected=True)
case("one-base wait: Templar Archives on one base waits", tech_waits, UnitTypeId.TEMPLARARCHIVE, 1, False, 2, expected=True)
case("one-base wait: Twilight on two bases goes", tech_waits, UnitTypeId.TWILIGHTCOUNCIL, 2, False, 2, expected=False)
case("one-base wait: an opener's own Twilight goes", tech_waits, UnitTypeId.TWILIGHTCOUNCIL, 1, True, 2, expected=False)
case("one-base wait: the Forge goes on one base", tech_waits, UnitTypeId.FORGE, 1, False, 2, expected=False)
case("one-base wait: the Robotics Bay goes on one base", tech_waits, UnitTypeId.ROBOTICSBAY, 1, False, 2, expected=False)
case("gas-starved: a bank and no gas for a Colossus", gas_starved, 3000, 120, [50.0, 100.0, 200.0], 700, expected=True)
case("gas-starved: enough gas for everything wanted", gas_starved, 3000, 250, [50.0, 100.0, 200.0], 700, expected=False)
case("gas-starved: no mineral bank", gas_starved, 500, 0, [50.0, 200.0], 700, expected=False)
case("gas-starved: nothing wants gas", gas_starved, 3000, 0, [], 700, expected=False)
case("floor: vs P with the switch, a pair: nothing more", templar_floor, {**_P, UnitTypeId.ARCHON: 10}, 20, 0, 2, 4, expected=0)

# K3: Archon morph pairs (army/templar.py)
def _ht(tag, x, energy, uncastable_for=0.0):  # noqa: E302
    return TemplarInfo(tag, Point2((x, 0)), energy, uncastable_for)


case("morph: vs T/P every Templar, nearest pairs", morph_pairs, [_ht(1, 0, 50), _ht(2, 30, 50), _ht(3, 1, 50), _ht(4, 31, 50)], False,
     expected=[(1, 3), (2, 4)])
case("morph: an odd Templar waits", morph_pairs, [_ht(1, 0, 50), _ht(2, 5, 50), _ht(3, 9, 50)], False, expected=[(1, 2)])
case("morph: vs Z casters within the cap stay", morph_pairs, [_ht(1, 0, 50), _ht(2, 5, 60), _ht(3, 9, 70)], True, 4, 60.0,
     expected=[])
case("morph: vs Z the spent pair morphs", morph_pairs, [_ht(1, 0, 10, 61.0), _ht(2, 5, 20, 70.0), _ht(3, 9, 70)], True, 4, 60.0,
     expected=[(1, 2)])
case("morph: vs Z one spent waits for a partner", morph_pairs, [_ht(1, 0, 10, 61.0), _ht(2, 5, 60), _ht(3, 9, 70)], True, 4, 60.0,
     expected=[])
case("morph: vs Z beyond the cap, lowest energy first", morph_pairs,
     [_ht(1, 0, 90), _ht(2, 1, 40), _ht(3, 2, 80), _ht(4, 3, 45), _ht(5, 4, 100), _ht(6, 5, 100)], True, 4, 60.0,
     expected=[(2, 4)])
case("morph: vs Z spent plus the excess", morph_pairs,
     [_ht(1, 0, 10, 65.0), _ht(2, 1, 40), _ht(3, 2, 80), _ht(4, 3, 85), _ht(5, 4, 100), _ht(6, 5, 100)], True, 4, 60.0,
     expected=[(1, 2)])
case("behind: toward home", lambda: behind(Point2((10, 0)), Point2((0, 0)), 2.0), expected=Point2((8, 0)))
case("behind: home is nearer than the distance", lambda: behind(Point2((1, 0)), Point2((0, 0)), 2.0), expected=Point2((1, 0)))



def _blink_counts(steps):  # noqa: E302
    """BlinkState: orders, then refreshes with which Stalkers still have Blink ready."""
    from sc2.ids.ability_id import AbilityId
    state = BlinkState()
    stalker = lambda tag, ready: SimpleNamespace(  # noqa: E731
        tag=tag, type_id=UnitTypeId.STALKER, position=Point2((0, 0)),
        abilities={AbilityId.EFFECT_BLINK_STALKER} if ready else set(), __call__=None,
    )
    for now, order, ready in steps:
        if order is not None:
            state.ordered[order[0]] = (order[1], now)  # what BlinkState.blink records
        state.refresh([stalker(tag, r) for tag, r in ready.items()], now)
    return state.counts


case("blink count: on cooldown after the order", _blink_counts, [(10.0, (1, "finish"), {1: True}), (10.1, None, {1: False})],
     expected={"back": 0, "in": 0, "finish": 1})
case("blink count: still ready after BLINK_CONFIRM_S: not a blink", _blink_counts,
     [(10.0, (1, "finish"), {1: True}), (10.5, None, {1: True}), (11.2, None, {1: True}), (12.0, None, {1: False})],
     expected={"back": 0, "in": 0, "finish": 0})
case("blink count: re-ordered and then it went off counts once", _blink_counts,
     [(10.0, (1, "in"), {1: True}), (10.1, (1, "in"), {1: True}), (10.2, None, {1: False})],
     expected={"back": 0, "in": 1, "finish": 0})


def main() -> int:
    failed = 0
    for name, fn, args, kwargs, expected in CASES:
        try:
            got = fn(*args, **kwargs)
            ok = got == expected
            detail = "" if ok else f"\n      got {got!r}, wanted {expected!r}"
        except Exception as e:  # noqa: BLE001 - a crash is a failed case
            ok, detail = False, f"\n      raised {type(e).__name__}: {e}"
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {name}{detail}")
    print(f"{len(CASES) - failed}/{len(CASES)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
