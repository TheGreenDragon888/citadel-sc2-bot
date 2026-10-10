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
from sc2.position import Point2  # noqa: E402

from bot.army.army import Army, home_engages  # noqa: E402
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
    CANNON_RUSH_RADIUS,
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
