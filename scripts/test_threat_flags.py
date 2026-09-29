"""Check the §5 ThreatFlag expiry rules without a game (DESIGN.md §5).

A fake clock and a fake view of the game (`ExpiryContext`) drive `bot/intel/threat_flags.py`.
Prints PASS/FAIL per check; exits 1 on any failure.

    poetry run python scripts/test_threat_flags.py
"""

import os
import sys
from pathlib import Path

ROOT: Path = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from loguru import logger  # noqa: E402

from bot.constants import MIN_PLAN_DURATION_S, UNIT_TTL_S  # noqa: E402
from bot.intel.threat_flags import Evidence, ExpiryContext, FlagStore, Threat  # noqa: E402

RESULTS: list[tuple[str, bool]] = []


def check(name: str, ok: bool) -> None:
    RESULTS.append((name, ok))


def ctx(visible=(), tags=(), phase=None) -> ExpiryContext:
    visible = set(visible)
    return ExpiryContext(
        is_visible=lambda p: p in visible,
        visible_enemy_tags=set(tags),
        phase_over=phase or {},
    )


def run_until(store: FlagStore, start: float, end: float, context: ExpiryContext, step: float = 0.5) -> None:
    t = start
    while t <= end:
        store.expire(t, context)
        t += step


def test_unit_ttl() -> None:
    for name, ttl in UNIT_TTL_S.items():
        threat = Threat[name]
        store = FlagStore()
        store.raise_flag(threat, Evidence.UNIT, "test", 100.0, "seen")
        # confirmed until 130 s, then silent
        for t in range(100, 131):
            store.confirm(threat, "test", float(t))
            store.expire(float(t), ctx())
        run_until(store, 131.0, 130.0 + ttl, ctx())
        still_there = store.is_active(threat)
        run_until(store, 130.0 + ttl + 0.5, 130.0 + ttl + 1.0, ctx())
        check(f"UNIT {name}: kept for {ttl:g} s after last confirm, expired after", still_there and not store.is_active(threat))


def test_min_plan_duration() -> None:
    store = FlagStore()
    store.raise_flag(Threat.POOL_12, Evidence.STRUCTURE, "test", 60.0, "pool", tags=[1], positions=[(10.0, 10.0)])
    phase = {Threat.POOL_12: "time > 4:00"}
    run_until(store, 60.0, 60.0 + MIN_PLAN_DURATION_S - 0.5, ctx(phase=phase))
    held = store.is_active(Threat.POOL_12)
    store.expire(60.0 + MIN_PLAN_DURATION_S, ctx(phase=phase))
    check(f"min plan duration: phase rule waits {MIN_PLAN_DURATION_S:g} s after the raise", held and not store.is_active(Threat.POOL_12))

    store = FlagStore()
    store.raise_flag(Threat.CANNON_RUSH, Evidence.STRUCTURE, "test", 60.0, "pylon", tags=[5], positions=[(1.0, 1.0)])
    store.on_unit_destroyed(5, 62.0)
    check("min plan duration: rule (a) expires at once", not store.is_active(Threat.CANNON_RUSH))


def test_structure_no_timer() -> None:
    store = FlagStore()
    store.raise_flag(Threat.PROXY, Evidence.STRUCTURE, "test", 90.0, "barracks", tags=[7], positions=[(50.0, 50.0)])
    run_until(store, 90.0, 3000.0, ctx(), step=5.0)
    check("STRUCTURE: never expires on a timer (90 s .. 50 min, no rule met)", store.is_active(Threat.PROXY))


def test_rule_a() -> None:
    store = FlagStore()
    store.raise_flag(Threat.CANNON_RUSH, Evidence.STRUCTURE, "test", 60.0, "pylon", tags=[1], positions=[(1.0, 1.0)])
    store.confirm(Threat.CANNON_RUSH, "test", 70.0, tags=[2], positions=[(2.0, 2.0)])
    store.on_unit_destroyed(1, 100.0)
    one_left = store.is_active(Threat.CANNON_RUSH)
    store.on_unit_destroyed(2, 101.0)
    check("rule (a): expires only when every evidence tag is destroyed", one_left and not store.is_active(Threat.CANNON_RUSH))

    store = FlagStore()
    store.raise_flag(Threat.WORKER_RUSH, Evidence.UNIT, "test", 30.0, "probes", tags=[1])
    store.on_unit_destroyed(1, 35.0)
    check("rule (a): does not apply to UNIT evidence", store.is_active(Threat.WORKER_RUSH))


def test_rule_b() -> None:
    pos = (40.0, 40.0)
    store = FlagStore()
    store.raise_flag(Threat.PROXY, Evidence.STRUCTURE, "test", 90.0, "barracks", tags=[9], positions=[pos])
    store.expire(200.0, ctx(visible=[pos], tags=[9]))
    present = store.is_active(Threat.PROXY)
    store.expire(201.0, ctx(visible=[], tags=[]))
    fogged = store.is_active(Threat.PROXY)
    store.expire(202.0, ctx(visible=[pos], tags=[]))
    check("rule (b): kept while the structure is seen or the spot is fogged", present and fogged)
    check("rule (b): expires when the spot is in vision and the structure is gone", not store.is_active(Threat.PROXY))

    store = FlagStore()
    store.raise_flag(Threat.CANNON_RUSH, Evidence.STRUCTURE, "test", 60.0, "2 pylons", tags=[1, 2], positions=[(1.0, 1.0), (5.0, 5.0)])
    store.expire(120.0, ctx(visible=[(1.0, 1.0)], tags=[]))
    check("rule (b): needs vision of every evidence position", store.is_active(Threat.CANNON_RUSH))


def test_rule_c_and_ares() -> None:
    store = FlagStore()
    store.raise_flag(Threat.ONE_BASE_ALLIN, Evidence.STRUCTURE, "no_natural", 165.0, "no natural at 2:45")
    store.expire(300.0, ctx())
    kept = store.is_active(Threat.ONE_BASE_ALLIN)
    store.expire(301.0, ctx(phase={Threat.ONE_BASE_ALLIN: "enemy natural townhall seen"}))
    check("rule (c): a missing-structure flag expires only by its phase rule", kept and not store.is_active(Threat.ONE_BASE_ALLIN))

    store = FlagStore()
    store.raise_flag(Threat.POOL_12, Evidence.ARES, "ares:get_enemy_ling_rushed", 120.0, "ares", expires_as=Evidence.UNIT)
    ttl = UNIT_TTL_S["POOL_12"]
    run_until(store, 120.0, 120.0 + ttl, ctx())
    kept = store.is_active(Threat.POOL_12)
    store.expire(120.0 + ttl + 1.0, ctx())
    check("ARES evidence mirrored as UNIT uses the UNIT TTL", kept and not store.is_active(Threat.POOL_12))

    store = FlagStore()
    store.raise_flag(Threat.ONE_BASE_ALLIN, Evidence.ARES, "ares:get_enemy_four_gate", 150.0, "ares", expires_as=Evidence.STRUCTURE)
    run_until(store, 150.0, 1000.0, ctx(), step=5.0)
    kept = store.is_active(Threat.ONE_BASE_ALLIN)
    store.expire(1001.0, ctx(phase={Threat.ONE_BASE_ALLIN: "time > 7:00 with 3 batteries and 20 army supply"}))
    check("ARES evidence mirrored as STRUCTURE has no timer, expires by phase", kept and not store.is_active(Threat.ONE_BASE_ALLIN))


def test_keys_and_history() -> None:
    store = FlagStore()
    store.raise_flag(Threat.POOL_12, Evidence.STRUCTURE, "pool", 80.0, "pool seen", tags=[3], positions=[(0.0, 0.0)])
    store.raise_flag(Threat.POOL_12, Evidence.UNIT, "lings", 130.0, "lings seen")
    ttl = UNIT_TTL_S["POOL_12"]
    run_until(store, 130.0, 130.0 + ttl + 1.0, ctx())
    check(
        "two sources for one threat expire separately (lings gone, pool kept)",
        store.get(Threat.POOL_12, "lings") is None and store.get(Threat.POOL_12, "pool") is not None,
    )
    raised = [(r.threat.name, r.source, r.expired_at is not None) for r in store.history]
    check("history records raise and expiry", raised == [("POOL_12", "pool", False), ("POOL_12", "lings", True)])


def main() -> int:
    logger.remove()  # keep the output to the PASS/FAIL lines
    test_unit_ttl()
    test_min_plan_duration()
    test_structure_no_timer()
    test_rule_a()
    test_rule_b()
    test_rule_c_and_ares()
    test_keys_and_history()
    for name, ok in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    failed = sum(not ok for _, ok in RESULTS)
    print(f"{len(RESULTS) - failed}/{len(RESULTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
