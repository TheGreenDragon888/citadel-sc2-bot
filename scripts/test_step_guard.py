"""M5 in-game test of the §6 step guard (bot/main.py `_check_step_time`).

    poetry run python scripts/test_step_guard.py [--map PylonAIE_v4]

One local game (realtime=False) of Citadel against the built-in VeryEasy Terran. At step SLOW_AT
the test makes the army step sleep SLOW_S (over STEP_GUARD_MS), then records, step by step, which
non-critical modules ran:
- the scout planner (`ScoutPlanner.step`, every MACRO_EVERY_STEPS);
- the counterattack's tick (`Counterattack.tick`, every DECISION_EVERY_STEPS, half a period after the
  main attack decision) and whether it ran guarded (detection and launch skipped);
- the telemetry snapshot (`Telemetry.step(snapshot=...)`, every step).

PASS: the slow step logged a warning and turned the guard on through SLOW_AT + STEP_GUARD_STEPS;
inside that window no scout planner step, the counterattack tick ran guarded, and every telemetry
step had its snapshot off; right after it, all three run normally again.
"""

import argparse
import os
import sys
import time
from pathlib import Path

ROOT: Path = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

import run  # noqa: E402,F401  (puts ares-sc2 on sys.path)
from sc2 import maps  # noqa: E402
from sc2.data import Difficulty, Race  # noqa: E402
from sc2.main import run_game  # noqa: E402
from sc2.player import Bot, Computer  # noqa: E402

from bot.constants import (  # noqa: E402
    ARMY_EVERY_STEPS,
    DECISION_EVERY_STEPS,
    MACRO_EVERY_STEPS,
    STEP_GUARD_MS,
    STEP_GUARD_STEPS,
)
from bot.main import CitadelBot  # noqa: E402

SLOW_AT: int = 640  # a decision tick (multiple of DECISION_EVERY_STEPS), about 0:57
SLOW_S: float = 0.25
TIME_LIMIT_S: int = 90


class GuardProbe(CitadelBot):
    def __init__(self) -> None:
        super().__init__()
        self.now_iteration = -1
        self.scout_steps: list[int] = []
        self.counter_ticks: list[tuple[int, bool]] = []
        self.snapshot_flags: dict[int, bool] = {}
        self.guard_changes: list[tuple[int, int]] = []

    async def on_start(self) -> None:
        await super().on_start()
        scouts_step = self.scouts.step
        army_step = self.army.step
        counter_tick = self.army.counter.tick
        telemetry_step = self.telemetry.step

        def scouts(*args, **kwargs):
            self.scout_steps.append(self.now_iteration)
            return scouts_step(*args, **kwargs)

        def army(iteration, guarded=False):
            if iteration == SLOW_AT:
                time.sleep(SLOW_S)
            return army_step(iteration, guarded)

        def tick(guarded):
            self.counter_ticks.append((self.now_iteration, guarded))
            return counter_tick(guarded)

        def telemetry(snapshot=True):
            self.snapshot_flags[self.now_iteration] = snapshot
            return telemetry_step(snapshot)

        self.scouts.step = scouts
        self.army.step = army
        self.army.counter.tick = tick
        self.telemetry.step = telemetry

    async def on_step(self, iteration: int) -> None:
        self.now_iteration = iteration
        before = self.guard_until
        await super().on_step(iteration)
        if self.guard_until != before:
            self.guard_changes.append((iteration, self.guard_until))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--map", default="PylonAIE_v4")
    args = parser.parse_args()
    assert SLOW_AT % DECISION_EVERY_STEPS == 0 and SLOW_AT % ARMY_EVERY_STEPS == 0
    bot = GuardProbe()
    run_game(
        maps.get(args.map),
        [Bot(Race.Protoss, bot), Computer(Race.Terran, Difficulty.VeryEasy)],
        realtime=False,
        game_time_limit=TIME_LIMIT_S,
    )
    end = SLOW_AT + STEP_GUARD_STEPS
    window = range(SLOW_AT + 1, end + 1)
    checks: list[tuple[str, bool, str]] = []
    slow = [c for c in bot.guard_changes if c[0] == SLOW_AT]
    checks.append((f"step {SLOW_AT} (+{SLOW_S * 1000:.0f} ms) turned the guard on through step {end}",
                   bool(slow) and slow[0][1] == end, f"guard changes {bot.guard_changes}"))
    checks.append(("the slow step was counted over the warning level", bot.telemetry.steps_over_warn >= 1,
                   f"{bot.telemetry.steps_over_warn} steps over the warning level, {bot.telemetry.guard_activations} guard activations"))
    in_window = [i for i in bot.scout_steps if i in window]
    after = [i for i in bot.scout_steps if i > end]
    expected_after = (end // MACRO_EVERY_STEPS + 1) * MACRO_EVERY_STEPS  # the first scout tick after the window
    checks.append(("no scout planner step inside the window", not in_window and SLOW_AT in bot.scout_steps,
                   f"steps {in_window}; ran at {SLOW_AT}: {SLOW_AT in bot.scout_steps}"))
    checks.append(("scout planner back on its first tick after the window", bool(after) and after[0] == expected_after,
                   f"first after: {after[:1]}, expected {expected_after}"))
    ticks_in = [(i, g) for i, g in bot.counter_ticks if i in window]
    ticks_after = [(i, g) for i, g in bot.counter_ticks if i > end]
    checks.append(("counterattack tick inside the window ran guarded", bool(ticks_in) and all(g for _, g in ticks_in),
                   f"{ticks_in}"))
    checks.append(("counterattack tick after the window runs unguarded", bool(ticks_after) and not ticks_after[0][1],
                   f"{ticks_after[:1]}"))
    flags = [bot.snapshot_flags.get(i) for i in window]
    checks.append(("telemetry snapshot off for every step in the window", flags == [False] * STEP_GUARD_STEPS, f"{flags}"))
    checks.append(("telemetry snapshot back on right after", bot.snapshot_flags.get(SLOW_AT) is not False
                   and bot.snapshot_flags.get(end + 1) is True, f"step {SLOW_AT}: {bot.snapshot_flags.get(SLOW_AT)}, step {end + 1}: {bot.snapshot_flags.get(end + 1)}"))
    for name, ok, detail in checks:
        print(f"CHECK {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
    ok = all(good for _, good, _ in checks)
    print(f"CHECK guard threshold {STEP_GUARD_MS:g} ms, {STEP_GUARD_STEPS} steps; RESULT {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
