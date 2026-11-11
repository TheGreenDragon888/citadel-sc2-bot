"""M8: offline checks of the ares bridge (bot/intel/ares_bridge.py); no game needed.

    poetry run python scripts/test_ares_bridge.py

A fake bot stands in for ares: the mediator's flags are plain booleans, enemy units are simple
objects. Checks that (1) no bridge reads ares's reaper flag, (2) a unit-based ares flag raises
nothing while no matching unit is near our bases, (3) it raises once one is, (4) a structure-based
flag still raises on the structures alone.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "ares-sc2" / "src", ROOT / "ares-sc2"):
    sys.path.insert(0, str(p))

from sc2.ids.unit_typeid import UnitTypeId  # noqa: E402
from sc2.position import Point2  # noqa: E402

from bot.constants import BRIDGE_HOME_RADIUS  # noqa: E402
from bot.intel.ares_bridge import BRIDGES, AresBridge  # noqa: E402
from bot.intel.threat_flags import FlagStore, Threat  # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        FAILED.append(name)


HOME = Point2((30.0, 30.0))


def unit(type_id: UnitTypeId, pos: tuple[float, float], tag: int) -> SimpleNamespace:
    position = Point2(pos)
    return SimpleNamespace(
        type_id=type_id, position=position, tag=tag, is_memory=False, distance_to=lambda other: position.distance_to(other)
    )


def fake_bot(true_flags: set[str], enemy_units: list, enemy_structures: list, time: float) -> SimpleNamespace:
    mediator = SimpleNamespace(**{b.accessor: b.accessor in true_flags for b in BRIDGES})
    for latch in ("get_enemy_went_marine_rush", "get_enemy_went_marauder_rush", "get_enemy_went_four_gate"):
        setattr(mediator, latch, False)
    return SimpleNamespace(
        mediator=mediator, time=time, time_formatted=f"{int(time) // 60:02d}:{int(time) % 60:02d}",
        enemy_units=enemy_units, enemy_structures=enemy_structures,
        townhalls=[SimpleNamespace(position=HOME)], start_location=HOME,
    )


def active(flags: FlagStore) -> set[tuple[str, str]]:
    return {(f.threat.name, f.source) for f in flags.active()}


def run(true_flags: set[str], enemy_units: list, enemy_structures: list, time: float) -> set[tuple[str, str]]:
    flags = FlagStore()
    AresBridge(fake_bot(true_flags, enemy_units, enemy_structures, time), flags, lambda threat, evidence: False).update()
    return active(flags)


def main() -> int:
    accessors = {b.accessor for b in BRIDGES}
    check("no bridge reads ares's reaper flag", "get_enemy_went_reaper" not in accessors)
    check("no bridge maps to PROXY from a Reaper", all(UnitTypeId.REAPER not in b.evidence_types for b in BRIDGES))

    far = (HOME.x + BRIDGE_HOME_RADIUS + 40.0, HOME.y)
    near = (HOME.x + BRIDGE_HOME_RADIUS - 5.0, HOME.y)
    cases = [
        ("get_enemy_marine_rush", UnitTypeId.MARINE, 1, 120.0, {"PROXY", "ONE_BASE_ALLIN"}),
        ("get_enemy_ling_rushed", UnitTypeId.ZERGLING, 1, 100.0, {"POOL_12"}),
        ("get_enemy_roach_rushed", UnitTypeId.ROACH, 1, 170.0, {"ONE_BASE_ALLIN"}),
        ("get_is_proxy_zealot", UnitTypeId.ZEALOT, 1, 150.0, {"PROXY"}),
    ]
    for accessor, type_id, count, t, threats in cases:
        if accessor not in accessors:
            check(f"{accessor}: bridged", False)
            continue
        got = run({accessor}, [], [], t)
        check(f"{accessor} True, no unit seen: no flag", got == set(), f"{got}")
        got = run({accessor}, [unit(type_id, far, 100 + i) for i in range(count)], [], t)
        check(f"{accessor} True, units only far from our bases: no flag", got == set(), f"{got}")
        got = run({accessor}, [unit(type_id, near, 200 + i) for i in range(count)], [], t)
        check(f"{accessor} True, a unit near our bases: {sorted(threats)}", {name for name, _ in got} == threats, f"{got}")
        got = run(set(), [unit(type_id, near, 300 + i) for i in range(count)], [], t)
        check(f"{accessor} False, a unit near our bases: no flag", got == set(), f"{got}")

    gates = [unit(UnitTypeId.GATEWAY, (150.0, 150.0), 400 + i) for i in range(4)]
    got = run({"get_enemy_four_gate"}, [], gates, 170.0)
    check("four-gate (structure-based): raises on the Gateways alone", {name for name, _ in got} == {"ONE_BASE_ALLIN"}, f"{got}")

    reaper = unit(UnitTypeId.REAPER, near, 500)
    got = run({b.accessor for b in BRIDGES if b.evidence_types == frozenset({UnitTypeId.MARINE})}, [reaper], [], 150.0)
    check("a Reaper at our base with ares's marine flag True: no flag", got == set(), f"{got}")
    check("Threat.PROXY still exists for the structure detectors", Threat.PROXY.name == "PROXY")

    print(f"\n{'FAIL' if FAILED else 'PASS'}: {len(FAILED)} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
