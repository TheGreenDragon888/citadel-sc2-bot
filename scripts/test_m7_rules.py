"""Offline tests for M7's pure rules (docs/M7_PLAN.md; no game needed).

    poetry run python scripts/test_m7_rules.py

Each M7 step adds its cases here: the fight-input text (O1), the expansion-first proxy check
(B6) and the main re-scout gate (B4). Prints PASS/FAIL per case; exits 1 on any failure.
"""

import os
import sys
from pathlib import Path
from typing import Any, Callable

ROOT: Path = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

import run  # noqa: E402,F401  (puts ares-sc2 on sys.path)

from bot.army.engagement import FightInputs, composition_text  # noqa: E402
from bot.constants import (  # noqa: E402
    MAIN_STALE_FROM_S,
    MAIN_STALE_S,
    PROXY_NATURAL_WAIT_UNTIL_S,
)
from bot.intel.detectors import (  # noqa: E402
    PROXY_EXPANSION,
    PROXY_MISSING,
    PROXY_PRODUCTION,
    PROXY_WAIT,
    proxy_production_check,
)
from bot.intel.scout_planner import main_rescout_due  # noqa: E402

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
