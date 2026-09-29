"""Mirror ares IntelManager flags into Citadel ThreatFlags (DESIGN.md §3, §4.2, §5).

Runs every intel tick after `super().on_step()`, so ares's managers have updated this step
(docs/VERIFY_NOTES.md §11.9). Every accessor in `BRIDGES` is read each tick: several ares flags
are lazy properties that only update (and set their latches) when read (§11.1).

A True ares flag raises an ARES-evidence flag that expires like its basis (§5):
- unit-based flags as UNIT evidence, confirmed each tick that a matching enemy unit is visible
  within BRIDGE_HOME_RADIUS of our bases (the ares boolean itself often never resets, so it
  can't be the confirmation, and units far away are not a threat to us yet). After the flag
  expires it is raised again only when the ares flag is True and such units are there.
- ares's four-gate flag (a Gateway count) as STRUCTURE evidence, with the Gateways as tags.
A flag is raised (or raised again) only inside the ares flag's own time window
(`constants.ARES_INTEL`), or before `BRIDGE_RAISE_UNTIL_S` for flags ares can raise at any
time (the reaper flag): a latched flag would otherwise re-raise its plan for the whole game
whenever a matching unit shows up.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.constants import ARES_INTEL, BRIDGE_HOME_RADIUS, BRIDGE_RAISE_UNTIL_S, WORKER_RUSH_CONFIRM_MIN
from bot.intel.threat_flags import Evidence, FlagStore, Threat

if TYPE_CHECKING:
    from ares import AresBot

WORKERS: frozenset[UnitTypeId] = frozenset({UnitTypeId.PROBE, UnitTypeId.SCV, UnitTypeId.DRONE})


@dataclass(frozen=True)
class Bridge:
    accessor: str  # ares mediator property (constants.ARES_INTEL)
    threats: tuple[Threat, ...]  # §4.2 rows that name this ares flag
    expires_as: Evidence
    # visible enemy units of these types confirm a UNIT flag (STRUCTURE: these are the evidence)
    evidence_types: frozenset[UnitTypeId]
    near_home_only: bool = True  # confirming units must be within BRIDGE_HOME_RADIUS of our bases
    min_units: int = 1  # fewer matching units than this neither confirm nor re-raise the flag


BRIDGES: tuple[Bridge, ...] = (
    # §4.2 ends the worker-rush pull at <= 1 enemy worker near our base
    Bridge(
        "get_enemy_worker_rushed", (Threat.WORKER_RUSH,), Evidence.UNIT, WORKERS,
        min_units=WORKER_RUSH_CONFIRM_MIN,
    ),
    Bridge("get_enemy_ling_rushed", (Threat.POOL_12,), Evidence.UNIT, frozenset({UnitTypeId.ZERGLING})),
    Bridge(
        "get_enemy_roach_rushed", (Threat.ONE_BASE_ALLIN,), Evidence.UNIT,
        frozenset({UnitTypeId.ROACH, UnitTypeId.RAVAGER}),
    ),
    Bridge(
        "get_enemy_ravager_rush", (Threat.ONE_BASE_ALLIN,), Evidence.UNIT,
        frozenset({UnitTypeId.RAVAGER, UnitTypeId.ROACH}),
    ),
    # §4.2 names the marine flag in both the proxy-Barracks and the one-base rows
    Bridge(
        "get_enemy_marine_rush", (Threat.PROXY, Threat.ONE_BASE_ALLIN), Evidence.UNIT,
        frozenset({UnitTypeId.MARINE}),
    ),
    Bridge("get_enemy_went_reaper", (Threat.PROXY,), Evidence.UNIT, frozenset({UnitTypeId.REAPER})),
    Bridge("get_enemy_marauder_rush", (Threat.ONE_BASE_ALLIN,), Evidence.UNIT, frozenset({UnitTypeId.MARAUDER})),
    Bridge(
        "get_enemy_four_gate", (Threat.ONE_BASE_ALLIN,), Evidence.STRUCTURE,
        frozenset({UnitTypeId.GATEWAY, UnitTypeId.WARPGATE}),
    ),
    Bridge("get_is_proxy_zealot", (Threat.PROXY,), Evidence.UNIT, frozenset({UnitTypeId.ZEALOT})),
)
# the latches ares sets while the flags above are read; logged only
LATCHES: tuple[str, ...] = ("get_enemy_went_marine_rush", "get_enemy_went_marauder_rush", "get_enemy_went_four_gate")


def source_of(bridge: Bridge) -> str:
    return f"ares:{bridge.accessor}"


class AresBridge:
    def __init__(self, bot: "AresBot", flags: FlagStore, override_for: "callable"):
        """`override_for(threat, evidence)` says whether a new flag ends the ares opener
        (decided by the defense planner's policy)."""
        self.bot = bot
        self.flags = flags
        self.override_for = override_for
        self.seen_true: set[str] = set()

    def update(self) -> None:
        bot = self.bot
        mediator = bot.mediator
        now = bot.time
        for bridge in BRIDGES:
            value = bool(getattr(mediator, bridge.accessor))
            if value and bridge.accessor not in self.seen_true:
                self.seen_true.add(bridge.accessor)
                logger.info(f"ARES {bridge.accessor} True at {bot.time_formatted}")
            evidence = self._evidence(bridge)
            if len(evidence) < bridge.min_units:
                evidence = []
            for threat in bridge.threats:
                source = source_of(bridge)
                active = self.flags.get(threat, source) is not None
                if active:
                    if evidence:
                        self.flags.confirm(threat, source, now, **self._tags_positions(bridge, evidence))
                    continue
                if not value or now > self._raise_until(bridge):
                    continue
                raised_before = any(r.threat == threat and r.source == source for r in self.flags.history)
                if raised_before and bridge.expires_as == Evidence.UNIT and not evidence:
                    continue  # latched ares flag, no new units: don't re-raise (§5)
                self.flags.raise_flag(
                    threat,
                    Evidence.ARES,
                    source,
                    now,
                    reason=f"ares {bridge.accessor} is True ({len(evidence)} matching units/structures visible)",
                    expires_as=bridge.expires_as,
                    override_opener=self.override_for(threat, bridge.expires_as),
                    **self._tags_positions(bridge, evidence),
                )
        for latch in LATCHES:
            if latch not in self.seen_true and getattr(mediator, latch):
                self.seen_true.add(latch)
                logger.info(f"ARES {latch} True at {bot.time_formatted}")

    @staticmethod
    def _raise_until(bridge: Bridge) -> float:
        window = ARES_INTEL[bridge.accessor].window_s
        return window[1] if window is not None else BRIDGE_RAISE_UNTIL_S

    def _evidence(self, bridge: Bridge) -> list:
        bot = self.bot
        if bridge.expires_as == Evidence.STRUCTURE:
            return [s for s in bot.enemy_structures if s.type_id in bridge.evidence_types]
        units = [
            u
            for u in bot.enemy_units
            if u.type_id in bridge.evidence_types and not u.is_memory
        ]
        if bridge.near_home_only:
            homes: list[Point2] = [th.position for th in bot.townhalls] + [bot.start_location]
            units = [u for u in units if any(u.distance_to(h) < BRIDGE_HOME_RADIUS for h in homes)]
        return units

    @staticmethod
    def _tags_positions(bridge: Bridge, evidence: list) -> dict:
        if bridge.expires_as != Evidence.STRUCTURE:
            return {}
        return {"tags": [s.tag for s in evidence], "positions": [s.position for s in evidence]}
