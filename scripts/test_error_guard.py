"""M6 test of the error guard (bot/error_guard.py, bot/main.py).

    poetry run python scripts/test_error_guard.py [--map PylonAIE_v4] [--offline]

Offline (no game): the guard records an error and goes on; python-sc2's connection errors
(`ProtocolError`, `ConnectionAlreadyClosed`) and `asyncio.CancelledError` pass through; it logs a
full traceback for the first ERROR_TRACEBACKS_PER_PART errors of a part, then one line per
ERROR_LOG_EVERY_S; an injected test error comes after the block has run.

In game (one local game, realtime=False, against the built-in Easy Terran) with errors injected
after these parts on every call: INJECTED_PARTS (on_step parts and event hooks), plus a behavior
that raises inside ares's after-step on every step from FAILING_FROM_S to FAILING_UNTIL_S. Each
would have ended the game as a Crash without the guard. PASS: the game ends with a result (no
exception out of python-sc2), every injected part shows up in the guard's counts, at most
ERROR_TRACEBACKS_PER_PART tracebacks per part, python-sc2's after-step ran on every step of the
failing-behavior window (actions were still sent), ares's behavior list did not grow, probes kept
being made through that window, and the game record carries the errors and passes
`check_game_log.problems`.
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT: Path = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

import run  # noqa: E402,F401  (puts ares-sc2 on sys.path)
from loguru import logger  # noqa: E402
from sc2 import maps  # noqa: E402
from sc2.data import Difficulty, Race, Result  # noqa: E402
from sc2.main import run_game  # noqa: E402
from sc2.player import Bot, Computer  # noqa: E402
from sc2.protocol import ConnectionAlreadyClosed, ProtocolError  # noqa: E402

from bot.constants import ERROR_LOG_EVERY_S, ERROR_TRACEBACKS_PER_PART  # noqa: E402
from bot.error_guard import ErrorGuard, InjectedError  # noqa: E402
from bot.main import CitadelBot  # noqa: E402
from scripts.check_game_log import problems  # noqa: E402

INJECTED_PARTS: set[str] = {"detectors", "micro", "ares step", "ares unit destroyed", "ares construction started"}
FAILING_FROM_S: float = 120.0
FAILING_UNTIL_S: float = 150.0
TIME_LIMIT_S: int = 1500

Check = tuple[str, bool, str]


class LogLines:
    """Collects ERROR log records (message, has traceback) from loguru."""

    def __init__(self) -> None:
        self.lines: list[tuple[str, bool]] = []
        self.sink_id = logger.add(self.sink, level="ERROR", format="{message}")

    def sink(self, message) -> None:
        record = message.record
        if record["message"].startswith("ERROR in"):
            self.lines.append((record["message"], record["exception"] is not None))

    def close(self) -> None:
        logger.remove(self.sink_id)


def offline_checks() -> list[Check]:
    clock = SimpleNamespace(time=10.0, time_formatted="00:10")
    guard = ErrorGuard(clock)
    log = LogLines()
    checks: list[Check] = []

    ran_after = False
    with guard.guard("a"):
        raise ValueError("boom")
    ran_after = True
    checks.append(("an error is recorded and the code after the block runs",
                   ran_after and guard.counts == {"a": 1} and guard.first["a"] == "00:10 ValueError: boom",
                   f"counts {guard.counts}, first {guard.first}"))

    for error in (ProtocolError("Game has already ended"), ConnectionAlreadyClosed("closed"), asyncio.CancelledError()):
        try:
            with guard.guard("b"):
                raise error
            passed = False
        except type(error):
            passed = True
        checks.append((f"{type(error).__name__} passes through", passed and "b" not in guard.counts, ""))

    for _ in range(ERROR_TRACEBACKS_PER_PART + 4):  # same game second: tracebacks, then quiet
        with guard.guard("c"):
            raise KeyError("x")
    clock.time += ERROR_LOG_EVERY_S
    with guard.guard("c"):
        raise KeyError("x")
    lines_c = [(m, tb) for m, tb in log.lines if m.startswith("ERROR in c ")]
    tracebacks = sum(tb for _, tb in lines_c)
    checks.append((f"part c: {ERROR_TRACEBACKS_PER_PART} tracebacks, then one line per {ERROR_LOG_EVERY_S:g} s",
                   guard.counts["c"] == ERROR_TRACEBACKS_PER_PART + 5 and tracebacks == ERROR_TRACEBACKS_PER_PART
                   and len(lines_c) == ERROR_TRACEBACKS_PER_PART + 1,
                   f"{guard.counts['c']} errors, {len(lines_c)} log lines, {tracebacks} with a traceback"))

    guard.test_parts = {"d"}
    body_ran = False
    with guard.guard("d"):
        body_ran = True
    checks.append(("an injected test error comes after the block ran",
                   body_ran and guard.counts.get("d") == 1 and "InjectedError" in guard.first["d"], f"{guard.first.get('d')}"))
    checks.append(("total counts every part", guard.total == sum(guard.counts.values()) == 1 + ERROR_TRACEBACKS_PER_PART + 5 + 1,
                   f"total {guard.total}"))
    log.close()
    return checks


class FailingBehavior:
    """An ares behavior that raises: registered last, so the real behaviors ran before it."""

    def execute(self, ai, config, mediator) -> bool:
        raise InjectedError("test error in a behavior")


class ErrorProbe(CitadelBot):
    def __init__(self) -> None:
        super().__init__()
        self.errors.test_parts = set(INJECTED_PARTS)
        self.window_steps = 0
        self.window_sent = 0  # steps in the window where python-sc2's after-step ran
        self.behaviors_max = 0
        self.probes_at: dict[str, int] = {}
        self._sent_at = 0.0

    async def on_step(self, iteration: int) -> None:
        await super().on_step(iteration)
        if FAILING_FROM_S <= self.time < FAILING_UNTIL_S:
            self.register_behavior(FailingBehavior())
            self.window_steps += 1
            self.probes_at.setdefault("start", self.workers.amount)
        elif self.time >= FAILING_UNTIL_S:
            self.probes_at.setdefault("end", self.workers.amount)
        self.behaviors_max = max(self.behaviors_max, len(self.behavior_executioner.behaviors))
        self._sent_at = self._time_after_step

    async def _after_step(self) -> int:
        loop = await super()._after_step()
        if FAILING_FROM_S <= self.time < FAILING_UNTIL_S and self._time_after_step != self._sent_at:
            self.window_sent += 1
        return loop


def game_checks(map_name: str) -> list[Check]:
    log = LogLines()
    bot = ErrorProbe()
    result = run_game(
        maps.get(map_name),
        [Bot(Race.Protoss, bot), Computer(Race.Terran, Difficulty.Easy)],
        realtime=False,
        game_time_limit=TIME_LIMIT_S,
    )
    log.close()
    checks: list[Check] = []
    checks.append(("the game ended with a result", isinstance(result, Result) and result != Result.Undecided,
                   f"{result} at {bot.time_formatted}"))
    missing = sorted(p for p in INJECTED_PARTS if not bot.errors.counts.get(p))
    checks.append(("every injected part was caught", not missing, f"counts {bot.errors.counts}; missing {missing}"))
    checks.append(("the failing behavior was caught in ares's after-step", bot.errors.counts.get("ares after step", 0) >= bot.window_steps > 0,
                   f"{bot.errors.counts.get('ares after step', 0)} errors over {bot.window_steps} window steps"))
    per_part: dict[str, int] = {}
    for message, traceback in log.lines:
        if traceback:
            part = message[len("ERROR in "):].split(" at ")[0]
            per_part[part] = per_part.get(part, 0) + 1
    checks.append((f"at most {ERROR_TRACEBACKS_PER_PART} tracebacks per part",
                   bool(per_part) and max(per_part.values()) <= ERROR_TRACEBACKS_PER_PART, f"{per_part}"))
    checks.append(("python-sc2's after-step (sending actions) ran on every window step",
                   bot.window_sent == bot.window_steps > 0, f"{bot.window_sent}/{bot.window_steps}"))
    checks.append(("ares's behavior list did not pile up", bot.behaviors_max < 100, f"max {bot.behaviors_max} behaviors in one step"))
    checks.append(("probes kept being made through the window",
                   bot.probes_at.get("end", 0) > bot.probes_at.get("start", 99), f"{bot.probes_at}"))
    record = bot.telemetry.game_record("Victory", bot.flags, bot.army, bot.opener, bot.ruleset, bot.wall_ok,
                                       bot.memory, bot.preraised, bot.errors)
    checks.append(("the game record carries the errors and is well formed",
                   record["errors"] == bot.errors.counts and set(record["errors_first"]) == set(bot.errors.counts)
                   and not problems(record), f"{problems(record)}; errors_first {record['errors_first']}"))
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--map", default="PylonAIE_v4")
    parser.add_argument("--offline", action="store_true", help="offline checks only")
    args = parser.parse_args()
    checks = offline_checks()
    if not args.offline:
        checks += game_checks(args.map)
    for name, ok, detail in checks:
        print(f"CHECK {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
    ok = all(good for _, good, _ in checks)
    print(f"CHECK {sum(g for _, g, _ in checks)}/{len(checks)}; RESULT {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
