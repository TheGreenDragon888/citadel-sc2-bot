"""Offline tests for the M3 acceptance checks (no game needed).

    poetry run python scripts/test_m3_checks.py
"""

import os
import sys
from pathlib import Path

ROOT: Path = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from scripts.m3_checks import flag_check  # noqa: E402

CASES = [
    # (opponent, raised flags, expected ok, text the reason must contain)
    ("worker_rush", [("WORKER_RUSH", 36)], True, "WORKER_RUSH at 0:36"),
    ("worker_rush", [("WORKER_RUSH", 36), ("WORKER_RUSH", 37), ("UNKNOWN_AGGRO", 50)], True, ""),
    ("worker_rush", [("WORKER_RUSH", 36), ("CANNON_RUSH", 60)], False, "false CANNON_RUSH"),
    ("worker_rush", [("WORKER_RUSH", 61)], False, "late"),
    ("worker_rush", [], False, "never raised"),
    ("cannon_rush", [("CANNON_RUSH", 47), ("PROXY", 90)], False, "false PROXY"),
    ("cannon_rush", [("PROXY", 92)], False, "CANNON_RUSH never raised; false PROXY"),
    ("cannon_rush", [("CANNON_RUSH", 90)], True, ""),
    ("twelve_pool", [("POOL_12", 68), ("ONE_BASE_ALLIN", 135)], True, ""),
    ("twelve_pool", [("POOL_12", 106)], False, "late (1:46 > 1:45)"),
    ("twelve_pool", [("POOL_12", 200), ("POOL_12", 70)], True, "POOL_12 at 1:10"),
    ("proxy_rax", [("PROXY", 90), ("ONE_BASE_ALLIN", 158)], True, ""),
    ("proxy_rax", [("PROXY", 90), ("POOL_12", 158)], False, "false POOL_12"),
]


def main() -> int:
    failed = 0
    for opponent, raised, want_ok, want_text in CASES:
        ok, reason = flag_check(opponent, raised)
        good = ok == want_ok and want_text in reason
        failed += not good
        print(f"{'PASS' if good else 'FAIL'}  {opponent:<12} {raised} -> {ok}, {reason!r}")
    print(f"{len(CASES) - failed}/{len(CASES)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
