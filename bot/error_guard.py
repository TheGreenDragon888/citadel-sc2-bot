"""M6 error guard (user decision): an error in one part of a step is logged and counted, and the
rest of the step and the game go on.

On the ladder an unhandled error ends the game as a Crash: python-sc2 re-raises any exception
from `on_step` and leaves the game, and the event hooks and ares's after-step run outside even that
(docs/VERIFY_NOTES.md, "M6 findings"). python-sc2's connection errors (`ProtocolError`, which
`ConnectionAlreadyClosed` subclasses) are not caught: they mean the game or the connection is over,
and python-sc2 handles them as before. `asyncio.CancelledError` is a BaseException and passes too.
"""

from contextlib import contextmanager
from typing import Iterator

from loguru import logger
from sc2.protocol import ProtocolError

from bot.constants import ERROR_LOG_EVERY_S, ERROR_TRACEBACKS_PER_PART


class InjectedError(RuntimeError):
    """Raised on purpose after the parts in `ErrorGuard.test_parts` (scripts/test_error_guard.py)."""


class ErrorGuard:
    def __init__(self, bot) -> None:
        self.bot = bot
        self.counts: dict[str, int] = {}  # part -> errors caught there
        self.first: dict[str, str] = {}  # part -> "m:ss Type: message" of its first error
        self._last_logged: dict[str, float] = {}
        # set only by a dev test (always empty in games): these parts raise after each call
        self.test_parts: set[str] = set()

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    @contextmanager
    def guard(self, part: str) -> Iterator[None]:
        """`with guard(part): ...` runs the block; an error in it is recorded and swallowed."""
        try:
            yield
            if part in self.test_parts:
                raise InjectedError(f"test error in {part}")
        except ProtocolError:
            raise
        except Exception as error:  # noqa: BLE001 - the point of the guard
            self._record(part, error)

    def _record(self, part: str, error: Exception) -> None:
        count = self.counts[part] = self.counts.get(part, 0) + 1
        now = self._now()
        text = f"{type(error).__name__}: {error}"[:200]
        self.first.setdefault(part, f"{self._clock()} {text}")
        if count <= ERROR_TRACEBACKS_PER_PART:
            logger.exception(f"ERROR in {part} at {self._clock()} (#{count} there); skipped, the game goes on")
            self._last_logged[part] = now
        elif now - self._last_logged.get(part, float("-inf")) >= ERROR_LOG_EVERY_S:
            logger.error(f"ERROR in {part} at {self._clock()}: {count} so far there, latest {text}")
            self._last_logged[part] = now

    def _now(self) -> float:
        try:
            return float(self.bot.time)
        except Exception:  # noqa: BLE001 - before the first observation
            return 0.0

    def _clock(self) -> str:
        try:
            return self.bot.time_formatted
        except Exception:  # noqa: BLE001
            return "?"
