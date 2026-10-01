"""Offline tests for the §4.6 counterattack rules (no game needed).

    poetry run python scripts/test_counterattack_rules.py

Covers bot/army/counterattack.py's `squad_rank`, `pick_squad` (fastest first, 35% cap, 8 supply
minimum), `pick_target` (lowest local defence, condition 3, ties by distance from the enemy army)
and `recall_reason` (each §4.6 return-home rule), and the value-weighted centre used by
bot/intel/army_position.py. The in-game behaviour is scripts/test_counterattack.py.
"""

import os
import sys
from pathlib import Path

ROOT: Path = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

import run  # noqa: E402,F401  (puts ares-sc2 on sys.path)
from sc2.ids.unit_typeid import UnitTypeId  # noqa: E402
from sc2.position import Point2  # noqa: E402

from bot.army.counterattack import (  # noqa: E402
    BaseOption,
    Candidate,
    pick_squad,
    pick_target,
    recall_reason,
    squad_rank,
)
from bot.constants import (  # noqa: E402
    COUNTER_ABORT,
    COUNTER_MAX_OUT_S,
    COUNTER_RECALL_SQUAD_RADIUS,
    COUNTER_RECALL_TARGET_RADIUS,
)
from bot.intel.army_position import weighted_center  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))


def candidates(spec: list[tuple[str, int, float]]) -> list[Candidate]:
    """[(type name, count, distance)] -> Candidates with tags 1, 2, ... and 2 supply each."""
    out = []
    tag = 0
    for name, count, distance in spec:
        rank = squad_rank(UnitTypeId[name], has_charge=True)
        for _ in range(count):
            tag += 1
            out.append(Candidate(tag, rank, 2.0, distance))
    return out


def main() -> int:
    # -- squad_rank -------------------------------------------------------------------------------
    check(
        "rank: Adept 0, Charge Zealot 1, Stalker 2",
        [squad_rank(UnitTypeId.ADEPT, True), squad_rank(UnitTypeId.ZEALOT, True), squad_rank(UnitTypeId.STALKER, True)] == [0, 1, 2],
    )
    check("rank: Zealot without Charge not taken", squad_rank(UnitTypeId.ZEALOT, False) is None)
    check(
        "rank: Immortal, Colossus, Archon, Observer not taken",
        all(squad_rank(t, True) is None for t in (UnitTypeId.IMMORTAL, UnitTypeId.COLOSSUS, UnitTypeId.ARCHON, UnitTypeId.OBSERVER)),
    )

    # -- pick_squad -------------------------------------------------------------------------------
    pool = candidates([("STALKER", 6, 50.0), ("ADEPT", 6, 60.0)])
    squad = pick_squad(pool, army_supply=40.0)  # cap 14 supply
    adepts = {c.tag for c in pool if c.rank == 0}
    check(
        "squad: Adepts first, then Stalkers, capped at 35% of army supply",
        adepts <= set(squad) and len(squad) == 7,
        f"{len(squad)} units, 14 supply of 40",
    )
    check("squad: under 8 supply -> none", pick_squad(pool, army_supply=20.0) == [], "cap 7 supply")
    check("squad: exactly 8 supply is enough", len(pick_squad(pool, army_supply=8 / 0.35)) == 4)
    near_far = candidates([("STALKER", 1, 80.0), ("STALKER", 1, 30.0), ("STALKER", 4, 50.0)])
    squad = pick_squad(near_far, army_supply=8 / 0.35)
    check("squad: within a rank, the units nearest the target first", 2 in squad and 1 not in squad, f"{squad}")
    zealots = candidates([("STALKER", 4, 10.0), ("ZEALOT", 4, 90.0)])
    check(
        "squad: Charge Zealots before Stalkers",
        set(pick_squad(zealots, army_supply=8 / 0.35)) == {c.tag for c in zealots if c.rank == 1},
    )

    # -- pick_target ------------------------------------------------------------------------------
    nat = BaseOption(Point2((100, 100)), defence=0.0, army_value=0.0)
    main_base = BaseOption(Point2((120, 120)), defence=1500.0, army_value=0.0)
    third = BaseOption(Point2((60, 140)), defence=500.0, army_value=0.0)
    best, why = pick_target([main_base, third, nat], 2000.0, Point2((20, 20)))
    check("target: lowest local defence", best is nat, why)
    crowded = BaseOption(Point2((100, 100)), defence=0.0, army_value=600.0)  # 30% of 2000
    best, why = pick_target([main_base, third, crowded], 2000.0, Point2((20, 20)))
    check("target: condition 3 skips a base with > 25% of the enemy army near it", best is third, why)
    edge = BaseOption(Point2((100, 100)), defence=0.0, army_value=500.0)  # exactly 25%
    best, _ = pick_target([main_base, edge], 2000.0, None)
    check("target: exactly 25% of the army near it is allowed", best is edge)
    a = BaseOption(Point2((30, 30)), defence=0.0, army_value=0.0)
    b = BaseOption(Point2((150, 150)), defence=0.0, army_value=0.0)
    best, _ = pick_target([a, b], 2000.0, Point2((20, 20)))
    check("target: a tie goes to the base farther from the enemy army", best is b)
    best, why = pick_target([crowded], 2000.0, None)
    check("target: none when the army is near every base", best is None, why)
    check("target: none without a known base", pick_target([], 2000.0, None)[0] is None)

    # -- recall_reason ----------------------------------------------------------------------------
    target = Point2((100, 100))
    far = Point2((20, 20))
    squad_at = Point2((95, 95))
    base = dict(now=130.0, launched_at=100.0, level=10, squad_value=1000.0, start_value=1000.0,
                army_center=far, target=target, squad_center=squad_at)
    check("recall: nothing wrong -> keep going", recall_reason(**base) is None)
    r = recall_reason(**{**base, "home_unheld": "home threat at (30, 30)"})
    check("recall: a home threat the DEFEND units can't hold comes first", r is not None and r.startswith("defense"), r)
    near_target = target.towards(far, COUNTER_RECALL_TARGET_RADIUS - 1)
    r = recall_reason(**{**base, "army_center": near_target})
    check("recall: enemy army within 35 of the target", r is not None and "of the target" in r, r)
    r = recall_reason(**{**base, "army_center": target.towards(far, COUNTER_RECALL_TARGET_RADIUS + 1)})
    check("recall: enemy army at 36 from the target -> keep going", r is None, r or "")
    squad_far = Point2((160, 100))
    r = recall_reason(**{**base, "target": Point2((200, 100)), "squad_center": squad_far,
                         "army_center": squad_far.towards(far, COUNTER_RECALL_SQUAD_RADIUS - 1)})
    check("recall: enemy army within 20 of the squad", r is not None and "of the squad" in r, r)
    r = recall_reason(**{**base, "level": COUNTER_ABORT})
    check(f"recall: level {COUNTER_ABORT} (COUNTER_ABORT)", r is not None and "level" in r, r)
    check(f"recall: level {COUNTER_ABORT + 1} keeps going", recall_reason(**{**base, "level": COUNTER_ABORT + 1}) is None)
    r = recall_reason(**{**base, "squad_value": 499.0})
    check("recall: squad value below 50% of its start value", r is not None and "value" in r, r)
    check("recall: exactly 50% keeps going", recall_reason(**{**base, "squad_value": 500.0}) is None)
    r = recall_reason(**{**base, "now": 100.0 + COUNTER_MAX_OUT_S + 0.5})
    check("recall: out for more than 60 s", r is not None and "out for" in r, r)
    check("recall: out for exactly 60 s keeps going", recall_reason(**{**base, "now": 100.0 + COUNTER_MAX_OUT_S}) is None)
    check("recall: no enemy army centre known -> other rules only", recall_reason(**{**base, "army_center": None}) is None)

    # -- weighted centre --------------------------------------------------------------------------
    c = weighted_center([(Point2((0, 0)), 100.0), (Point2((10, 0)), 300.0)])
    check("army centre: value-weighted", c is not None and abs(c.x - 7.5) < 1e-9 and abs(c.y) < 1e-9, f"{c}")
    c = weighted_center([(Point2((0, 0)), 0.0), (Point2((10, 0)), 0.0)])
    check("army centre: plain centre when every value is 0", c is not None and abs(c.x - 5) < 1e-9)
    check("army centre: none for no units", weighted_center([]) is None)

    passed = sum(ok for _, ok, _ in RESULTS)
    print(f"\n{passed}/{len(RESULTS)} passed")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
