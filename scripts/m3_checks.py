"""M3 acceptance checks (DESIGN.md §7 M3), shared by run_matches.py and test_m3_checks.py.

- `flag_check`: the "correct flag logged" test agreed for M3. Against a scripted cheese bot, the
  bot's expected threat must be raised by its deadline, and no threat outside the expected one
  and the bot's allowed list may be raised at any time in the game
  (`bot.constants.M3_EXPECTED_FLAGS`).
- "No scout lost before 4:00" is `Telemetry.scouts_lost_before()` being empty.
"""

from typing import Iterable

from bot.constants import M3_EXPECTED_FLAGS


def _mmss(seconds: float) -> str:
    return f"{int(seconds) // 60}:{int(seconds) % 60:02d}"


def flag_check(opponent: str, raised: Iterable[tuple[str, float]]) -> tuple[bool, str]:
    """`raised`: (threat name, game second raised) for every flag the game raised.

    Returns (ok, reason); the reason says what was missing, late or false."""
    expected, by_s, allowed = M3_EXPECTED_FLAGS[opponent]
    raised = list(raised)
    times = [t for name, t in raised if name == expected]
    false_flags = sorted({name for name, _ in raised if name != expected and name not in allowed})
    problems = []
    if not times:
        problems.append(f"{expected} never raised")
    elif min(times) > by_s:
        problems.append(f"{expected} late ({_mmss(min(times))} > {_mmss(by_s)})")
    if false_flags:
        problems.append("false " + ",".join(false_flags))
    if problems:
        return False, "; ".join(problems)
    return True, f"{expected} at {_mmss(min(times))}"
