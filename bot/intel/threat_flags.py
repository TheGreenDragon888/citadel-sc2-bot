"""Threat flags with explicit expiry (DESIGN.md §5).

Detectors (`ares_bridge.py`, `detectors.py`) raise and re-confirm flags; `FlagStore.expire`
applies the §5 expiry rules every intel tick. A threat is active while any of its flags is.
Flags hold unit tags and positions, never `Unit` objects.

Each flag is keyed by (threat, source), where `source` names the detector, so the same threat
seen two ways (a Spawning Pool, then Zerglings) keeps both pieces of evidence and each expires
by its own rule.

Expiry (§5):
- UNIT evidence: `UNIT_TTL_S[threat]` seconds after `last_confirmed`.
- STRUCTURE evidence never expires on a timer, only by
  (a) every evidence tag reported destroyed,
  (b) every evidence position in vision with none of the evidence structures there, or
  (c) the threat's phase rule (computed by the caller, see `ExpiryContext.phase_over`).
- ARES evidence expires like the category in `ThreatFlag.expires_as` (UNIT or STRUCTURE).
- No flag expires within `MIN_PLAN_DURATION_S` of being raised, except by rule (a).
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Iterable, Optional

from loguru import logger

from bot.constants import MIN_PLAN_DURATION_S, RESCOUT_STALE_S, UNIT_TTL_DEFAULT_S, UNIT_TTL_S


class Threat(Enum):
    WORKER_RUSH = auto()
    CANNON_RUSH = auto()
    POOL_12 = auto()
    PROXY = auto()
    ONE_BASE_ALLIN = auto()
    AIR_HARASS = auto()
    DT = auto()
    TIMING_ATTACK = auto()
    MACRO = auto()
    UNKNOWN_AGGRO = auto()
    ARMY_OUT_OF_POSITION = auto()


class Evidence(Enum):
    STRUCTURE = auto()  # buildings, tech, missing-structure-at-time observations
    UNIT = auto()  # units seen / moving
    ARES = auto()  # mirrored from ares IntelManager


Position = tuple[float, float]


@dataclass
class ThreatFlag:
    threat: Threat
    evidence: Evidence
    raised_at: float  # game seconds
    evidence_tags: set[int] = field(default_factory=set)  # tags only, never Unit objects
    evidence_positions: list[Position] = field(default_factory=list)
    last_confirmed: float = 0.0
    override_opener: bool = False  # True ends the ares build runner (§3)
    # Citadel additions
    source: str = ""  # detector that raised it
    reason: str = ""  # why it was raised (logged)
    expires_as: Optional[Evidence] = None  # UNIT or STRUCTURE; None = same as `evidence`
    destroyed_tags: set[int] = field(default_factory=set)
    positions_seen_at: float = 0.0  # last time every evidence position was in vision

    @property
    def expiry_kind(self) -> Evidence:
        return self.expires_as or self.evidence

    @property
    def key(self) -> tuple[Threat, str]:
        return (self.threat, self.source)


@dataclass
class ExpiryContext:
    """What `FlagStore.expire` needs from the game, so the rules can be tested without one."""

    is_visible: Callable[[Position], bool]
    # tags of enemy structures in vision right now (not snapshots)
    visible_enemy_tags: set[int]
    # threat -> reason, for threats whose §5 phase rule says they no longer matter
    phase_over: dict[Threat, str]
    # (threat, source) -> reason: a phase rule for one detector's flag only (M3)
    source_over: dict[tuple[Threat, str], str] = field(default_factory=dict)


@dataclass
class FlagRecord:
    """One raise-to-expiry span, for telemetry (§8 "flags with their raise and expire reasons")."""

    threat: Threat
    source: str
    evidence: Evidence
    raised_at: float
    reason: str
    expired_at: Optional[float] = None
    expire_reason: str = ""


def _mmss(seconds: float) -> str:
    return f"{int(seconds) // 60}:{int(seconds) % 60:02d}"


class FlagStore:
    def __init__(self) -> None:
        self.flags: dict[tuple[Threat, str], ThreatFlag] = {}
        self.history: list[FlagRecord] = []
        self._records: dict[tuple[Threat, str], FlagRecord] = {}
        self._rescout_logged: set[tuple[Threat, str]] = set()
        # §5 re-scout trigger: STRUCTURE flags whose evidence positions have gone unseen for
        # RESCOUT_STALE_S; the scout planner reads this (M3)
        self.stale: dict[tuple[Threat, str], list[Position]] = {}

    # -- raising -------------------------------------------------------------------------------

    def raise_flag(
        self,
        threat: Threat,
        evidence: Evidence,
        source: str,
        now: float,
        reason: str,
        tags: Iterable[int] = (),
        positions: Iterable[Position] = (),
        expires_as: Optional[Evidence] = None,
        override_opener: bool = False,
    ) -> ThreatFlag:
        """Raise the flag, or re-confirm it (adding evidence) if it is already active."""
        key = (threat, source)
        flag = self.flags.get(key)
        if flag is not None:
            self._add_evidence(flag, now, tags, positions)
            return flag
        flag = ThreatFlag(
            threat=threat,
            evidence=evidence,
            raised_at=now,
            last_confirmed=now,
            override_opener=override_opener,
            source=source,
            reason=reason,
            expires_as=expires_as,
            positions_seen_at=now,
        )
        self._add_evidence(flag, now, tags, positions)
        self.flags[key] = flag
        record = FlagRecord(threat, source, flag.expiry_kind, now, reason)
        self._records[key] = record
        self.history.append(record)
        logger.info(
            f"FLAG raise {threat.name} ({evidence.name}"
            f"{'->' + flag.expiry_kind.name if evidence == Evidence.ARES else ''}, {source}) "
            f"at {_mmss(now)}: {reason}"
            + (" [ends opener]" if override_opener else "")
        )
        return flag

    def confirm(
        self,
        threat: Threat,
        source: str,
        now: float,
        tags: Iterable[int] = (),
        positions: Iterable[Position] = (),
    ) -> bool:
        """Refresh `last_confirmed` of an active flag. Returns False if it isn't active."""
        flag = self.flags.get((threat, source))
        if flag is None:
            return False
        self._add_evidence(flag, now, tags, positions)
        return True

    @staticmethod
    def _add_evidence(flag: ThreatFlag, now: float, tags: Iterable[int], positions: Iterable[Position]) -> None:
        flag.last_confirmed = now
        for tag in tags:
            if tag not in flag.destroyed_tags:
                flag.evidence_tags.add(tag)
        for pos in positions:
            pos = (round(pos[0], 1), round(pos[1], 1))
            if pos not in flag.evidence_positions:
                flag.evidence_positions.append(pos)

    # -- queries -------------------------------------------------------------------------------

    def active(self) -> list[ThreatFlag]:
        return list(self.flags.values())

    def is_active(self, threat: Threat) -> bool:
        return any(key[0] == threat for key in self.flags)

    def active_threats(self) -> set[Threat]:
        return {key[0] for key in self.flags}

    def get(self, threat: Threat, source: str) -> Optional[ThreatFlag]:
        return self.flags.get((threat, source))

    def was_raised(self, threat: Threat) -> bool:
        return any(r.threat == threat for r in self.history)

    # -- expiry --------------------------------------------------------------------------------

    def on_unit_destroyed(self, tag: int, now: float) -> None:
        """Rule (a): a STRUCTURE-kind flag whose evidence tags are all destroyed expires at
        once (not held by the minimum plan duration)."""
        for key, flag in list(self.flags.items()):
            if tag not in flag.evidence_tags:
                continue
            flag.evidence_tags.discard(tag)
            flag.destroyed_tags.add(tag)
            if flag.expiry_kind == Evidence.STRUCTURE and not flag.evidence_tags:
                self._expire(key, now, f"rule (a): all {len(flag.destroyed_tags)} evidence structures destroyed")

    def expire(self, now: float, ctx: ExpiryContext) -> None:
        for key, flag in list(self.flags.items()):
            reason = self._expiry_reason(flag, now, ctx)
            if reason is not None and now - flag.raised_at >= MIN_PLAN_DURATION_S:
                self._expire(key, now, reason)

    def _expiry_reason(self, flag: ThreatFlag, now: float, ctx: ExpiryContext) -> Optional[str]:
        if flag.expiry_kind == Evidence.UNIT:
            ttl = UNIT_TTL_S.get(flag.threat.name, UNIT_TTL_DEFAULT_S)
            if now - flag.last_confirmed > ttl:
                return f"UNIT TTL {ttl:g} s since last confirmed at {_mmss(flag.last_confirmed)}"
            return None
        # STRUCTURE: rule (b), then rule (c)
        if flag.evidence_positions:
            if all(ctx.is_visible(p) for p in flag.evidence_positions):
                flag.positions_seen_at = now
                self.stale.pop(flag.key, None)
                if flag.evidence_tags and not (flag.evidence_tags & ctx.visible_enemy_tags):
                    return "rule (b): evidence positions in vision, structures gone"
            elif now - flag.positions_seen_at > RESCOUT_STALE_S:
                self.stale[flag.key] = list(flag.evidence_positions)
                if flag.key not in self._rescout_logged:
                    self._rescout_logged.add(flag.key)
                    logger.info(
                        f"RESCOUT wanted: {flag.threat.name} ({flag.source}) evidence not seen since "
                        f"{_mmss(flag.positions_seen_at)}"
                    )
        if flag.threat in ctx.phase_over:
            return f"rule (c): {ctx.phase_over[flag.threat]}"
        if flag.key in ctx.source_over:
            return f"rule (c): {ctx.source_over[flag.key]}"
        return None

    def _expire(self, key: tuple[Threat, str], now: float, reason: str) -> None:
        flag = self.flags.pop(key)
        self._rescout_logged.discard(key)
        self.stale.pop(key, None)
        record = self._records.pop(key, None)
        if record is not None:
            record.expired_at = now
            record.expire_reason = reason
        logger.info(
            f"FLAG expire {flag.threat.name} ({flag.source}) at {_mmss(now)} "
            f"(raised {_mmss(flag.raised_at)}): {reason}"
        )
