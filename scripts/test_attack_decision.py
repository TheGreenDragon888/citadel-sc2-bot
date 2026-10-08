"""Offline tests for the §4.5.2 attack/retreat state machine and the §4.7 gates (no game needed).

    poetry run python scripts/test_attack_decision.py

Each case replays a sequence of evaluations (game second, level, supply used, squad value, our/
enemy value ratio) through `AttackDecision` and checks the action after each one. A step can end
with a dict of the M7 C4 launch inputs; "wait+intel" is a wait that asks the Observer to look.
"""

import os
import sys
from pathlib import Path

ROOT: Path = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from bot.army.attack_decision import ATTACK, GATHER, AttackDecision  # noqa: E402
from bot.constants import (  # noqa: E402
    END_GAME_ATTACK_FROM_S,
    END_GAME_FROM_S,
    LAUNCH_AFTER_DEFEND_S,
    LAUNCH_INTEL_WAIT_S,
    MIN_STATE_SECONDS,
    RELAUNCH_WAIT_S,
)

# (name, [(t, level, supply_used, squad_value, value_ratio, expected action), ...], extra steps)
# An entry ("add", value) or ("recall", t) in the list applies that call instead.
T0 = 600.0
CASES = [
    ("no launch below 150 supply", [(T0, 10, 149, 3000, 2.0, "wait")]),
    ("launch at level 8 and 150 supply", [(T0, 8, 150, 3000, 2.0, "launch")]),
    ("level 7 at 150 supply waits", [(T0, 7, 170, 3000, 2.0, "wait")]),
    ("level 5 launches at 190 supply", [(T0, 5, 190, 3000, 1.0, "launch")]),
    ("level 4 at 190 supply waits", [(T0, 4, 199, 3000, 1.0, "wait")]),
    (
        "continue at 5, hold a 4 inside 20 s, retreat at 4 after 20 s",
        [
            (T0, 9, 160, 3000, 2.0, "launch"),
            (T0 + 5, 5, 160, 3000, 2.0, "continue"),
            (T0 + 10, 4, 160, 3000, 2.0, "continue"),
            (T0 + MIN_STATE_SECONDS + 1, 4, 160, 3000, 2.0, "retreat"),
        ],
    ),
    (
        "level <= 2 retreats inside 20 s",
        [(T0, 9, 160, 3000, 2.0, "launch"), (T0 + 3, 2, 160, 3000, 2.0, "retreat")],
    ),
    (
        "level 3 inside 20 s is held",
        [(T0, 9, 160, 3000, 2.0, "launch"), (T0 + 3, 3, 160, 3000, 2.0, "continue")],
    ),
    (
        "value below 40% retreats even inside 20 s and at a high level",
        [(T0, 9, 160, 3000, 2.0, "launch"), (T0 + 5, 10, 160, 1100, 2.0, "retreat")],
    ),
    (
        "value at 40% continues",
        [(T0, 9, 160, 3000, 2.0, "launch"), (T0 + 5, 10, 160, 1200, 2.0, "continue")],
    ),
    (
        "reinforcements raise the start value",
        [
            (T0, 9, 160, 3000, 2.0, "launch"),
            ("add", 2000),
            (T0 + 30, 9, 160, 1900, 2.0, "retreat"),  # 1900 < 0.4 x 5000
        ],
    ),
    (
        "relaunch wait after a retreat",
        [
            (T0, 9, 160, 3000, 2.0, "launch"),
            (T0 + 30, 1, 160, 3000, 2.0, "retreat"),
            (T0 + 30 + RELAUNCH_WAIT_S - 1, 10, 200, 3000, 3.0, "wait"),
            (T0 + 30 + RELAUNCH_WAIT_S + 1, 10, 200, 3000, 3.0, "launch"),
        ],
    ),
    (
        "recall: no relaunch wait, but the 20 s flip hold",
        [
            (T0, 9, 160, 3000, 2.0, "launch"),
            ("recall", T0 + 30),
            (T0 + 35, 10, 200, 3000, 3.0, "wait"),
            (T0 + 30 + MIN_STATE_SECONDS + 1, 10, 200, 3000, 3.0, "launch"),
        ],
    ),
    (
        "45:00: ATTACK_START 6 when ahead by 1.2x",
        [
            (END_GAME_ATTACK_FROM_S - 1, 6, 160, 3000, 1.5, "wait"),
            (END_GAME_ATTACK_FROM_S, 6, 160, 3000, 1.1, "wait"),
            (END_GAME_ATTACK_FROM_S + 1, 6, 160, 3000, 1.2, "launch"),
        ],
    ),
    (
        "before 40:00, being behind doesn't stop a launch",
        [
            (END_GAME_FROM_S - 1, 5, 195, 3000, 0.9, "launch"),
        ],
    ),
    (
        "from 40:00, behind means no launch, even at 190 supply",
        [
            (END_GAME_FROM_S + 1, 9, 195, 3000, 0.9, "wait"),
            (END_GAME_FROM_S + 2, 9, 195, 3000, 1.0, "launch"),
        ],
    ),
    # -- M7 C4: the launch gate ------------------------------------------------------------------
    (
        "no launch within LAUNCH_AFTER_DEFEND_S of a home fight",
        [
            (T0, 9, 160, 3000, 2.0, "wait", {"since_home_fight_s": LAUNCH_AFTER_DEFEND_S - 1}),
            (T0 + 1, 9, 160, 3000, 2.0, "launch", {"since_home_fight_s": LAUNCH_AFTER_DEFEND_S}),
        ],
    ),
    (
        "the remembered army must pass the gate too",
        [
            (T0, 9, 160, 3000, 2.0, "wait", {"army_level": 7}),
            (T0 + 1, 9, 160, 3000, 2.0, "launch", {"army_level": 8}),
        ],
    ),
    (
        "at 190 supply the remembered army needs ATTACK_START_MAX",
        [
            (T0, 6, 195, 3000, 1.0, "wait", {"army_level": 4}),
            (T0 + 1, 6, 195, 3000, 1.0, "launch", {"army_level": 5}),
        ],
    ),
    (
        "stale intel: wait and look, then launch after LAUNCH_INTEL_WAIT_S",
        [
            (T0, 9, 160, 3000, 2.0, "wait+intel", {"intel_fresh": False}),
            (T0 + LAUNCH_INTEL_WAIT_S - 1, 9, 160, 3000, 2.0, "wait+intel", {"intel_fresh": False}),
            (T0 + LAUNCH_INTEL_WAIT_S, 9, 160, 3000, 2.0, "launch", {"intel_fresh": False}),
        ],
    ),
    (
        "stale intel: fresh intel launches at once",
        [
            (T0, 9, 160, 3000, 2.0, "wait+intel", {"intel_fresh": False}),
            (T0 + 5, 9, 160, 3000, 2.0, "launch", {"intel_fresh": True}),
        ],
    ),
    (
        "stale intel: the wait restarts once the gate stops passing",
        [
            (T0, 9, 160, 3000, 2.0, "wait+intel", {"intel_fresh": False}),
            (T0 + 30, 6, 160, 3000, 2.0, "wait", {"intel_fresh": False}),
            (T0 + 60, 9, 160, 3000, 2.0, "wait+intel", {"intel_fresh": False}),
        ],
    ),
    (
        "stale intel and a weak remembered army: still no launch after the wait",
        [
            (T0, 9, 160, 3000, 2.0, "wait+intel", {"intel_fresh": False, "army_level": 3}),
            (T0 + LAUNCH_INTEL_WAIT_S, 9, 160, 3000, 2.0, "wait", {"intel_fresh": False, "army_level": 3}),
        ],
    ),
]


def main() -> int:
    failed = 0
    for name, steps in CASES:
        machine = AttackDecision()
        problems = []
        for step in steps:
            if step[0] == "add":
                machine.add_value(step[1])
                continue
            if step[0] == "recall":
                machine.recall(step[1])
                continue
            t, level, supply, value, ratio, want = step[:6]
            got = machine.evaluate(t, level, supply, value, ratio, **(step[6] if len(step) > 6 else {}))
            want, want_intel = want.split("+")[0], want.endswith("+intel")
            if got.action != want or got.wants_intel != want_intel:
                problems.append(
                    f"t={t:g} level={level}: {got.action}{' +intel' if got.wants_intel else ''} ({got.reason}), wanted {step[5]}"
                )
            want_state = ATTACK if want in ("launch", "continue") else GATHER
            if machine.state != want_state:
                problems.append(f"t={t:g}: state {machine.state}, wanted {want_state}")
        failed += bool(problems)
        print(f"{'FAIL' if problems else 'PASS'}  {name}" + "".join(f"\n      {p}" for p in problems))
    print(f"{len(CASES) - failed}/{len(CASES)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
