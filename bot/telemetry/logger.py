"""Per-game metrics (DESIGN.md §8), kept in memory and logged to stdout.

M1 records the economy snapshots the acceptance test needs (probes at 6:00) plus a few §8
metrics that come for free. Writing them to ./data/logs is M5.
"""

import time
from typing import TYPE_CHECKING, Optional

from loguru import logger

from sc2.ids.unit_typeid import UnitTypeId

from bot.constants import METRIC_TIMES_S

if TYPE_CHECKING:
    from ares import AresBot


def _mmss(seconds: float) -> str:
    return f"{int(seconds) // 60}:{int(seconds) % 60:02d}"


class Telemetry:
    def __init__(self, bot: "AresBot"):
        self.bot = bot
        self.snapshots: dict[int, dict] = {}
        self.supply_blocked_s: float = 0.0
        self._last_time: float = 0.0
        self._blocked_since: Optional[float] = None
        self.step_count: int = 0
        self.step_total_ms: float = 0.0
        self.step_max_ms: float = 0.0
        self.probes_lost: int = 0

    def on_own_unit_destroyed(self, type_id) -> None:
        if type_id == UnitTypeId.PROBE:
            self.probes_lost += 1

    def record_step_time(self, started: float) -> None:
        """`started` is `time.perf_counter()` at the start of `on_step`."""
        ms = (time.perf_counter() - started) * 1000
        self.step_count += 1
        self.step_total_ms += ms
        self.step_max_ms = max(self.step_max_ms, ms)

    def step(self) -> None:
        bot = self.bot
        now = bot.time
        blocked = bot.supply_left <= 0 and bot.supply_cap < 200
        if blocked:
            self.supply_blocked_s += now - self._last_time
            if self._blocked_since is None:
                self._blocked_since = now
        elif self._blocked_since is not None:
            logger.info(
                f"SUPPLY blocked {_mmss(self._blocked_since)}-{_mmss(now)} "
                f"at {int(bot.supply_used)}/{int(bot.supply_cap)}"
            )
            self._blocked_since = None
        self._last_time = now
        for mark in METRIC_TIMES_S:
            if mark not in self.snapshots and now >= mark:
                self._snapshot(mark)

    def _snapshot(self, mark: int) -> None:
        bot = self.bot
        snap = {
            "probes": len(bot.workers),
            "probes_lost": self.probes_lost,
            "bases": len(bot.ready_townhalls),
            "townhalls": len(bot.townhalls),  # includes ones under construction
            "gas": len(bot.gas_buildings),
            "supply_used": int(bot.supply_used),
            "army_supply": int(bot.supply_army),
            "supply_blocked_s": round(self.supply_blocked_s, 1),
            "minerals": bot.minerals,
            "vespene": bot.vespene,
        }
        self.snapshots[mark] = snap
        fields = " ".join(f"{k}={v}" for k, v in snap.items())
        logger.info(f"METRIC t={_mmss(mark)} {fields}")

    def end_report(self) -> None:
        mean = self.step_total_ms / self.step_count if self.step_count else 0.0
        logger.info(
            f"METRIC end t={self.bot.time_formatted} supply_blocked_s={self.supply_blocked_s:.1f} "
            f"steps={self.step_count} step_mean_ms={mean:.1f} step_max_ms={self.step_max_ms:.1f}"
        )
