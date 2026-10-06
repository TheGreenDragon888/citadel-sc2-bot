"""Every TUNE value and threshold Citadel uses (CLAUDE.md rule).

Section references (§) point at docs/DESIGN.md. Values that come from game data are
read at runtime instead of being listed here.
"""

from typing import NamedTuple, Optional, Tuple

from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId

# §1, §4.7: the ladder ends a game as a tie at 80,640 game loops (60:00 game time)
LADDER_TIE_GAME_SECONDS: int = 3600

# §4.0 ruleset probe: on loop 0, <= this many workers means the 8-worker (5.0.16) ruleset
RULESET_8_WORKER_MAX: int = 8
RULESET_8_WORKER: str = "816"
RULESET_12_WORKER: str = "1215"


class AresIntelFlag(NamedTuple):
    """One ares IntelManager flag, as read in ares-sc2 v3.13.1 source (docs/VERIFY_NOTES.md §11.1).

    Read it as the mediator property `self.mediator.<accessor>` (no call parentheses),
    after `await super().on_step(iteration)` so the managers have updated this step.
    """

    accessor: str
    races: str  # enemy race the check runs for
    basis: str  # "units", "structures" or "units+structures": maps to §5 Evidence
    trigger: str  # the condition as coded in ares (t = self.time, game seconds)
    window_s: Optional[Tuple[float, float]]  # game-seconds window it can fire in; None = any time
    resets: bool  # False = latched True for the rest of the game once raised
    evaluated: str  # "every step" (ares update) or "on read" (lazy property)


# §4.2: ares IntelManager flags. Citadel's own ThreatFlag expiry (§5) applies on top of these.
ARES_INTEL: dict[str, AresIntelFlag] = {
    flag.accessor: flag
    for flag in (
        AresIntelFlag(
            "get_enemy_worker_rushed", "any", "units",
            "> 6 enemy workers (incl. remembered) within 15 of our start or 16 of our natural",
            (0, 180), False, "every step",
        ),
        AresIntelFlag(
            "get_enemy_ling_rushed", "Zerg", "units",
            "> 2 lings within 50 of our start (t<150), or > 7 lings seen (t<180), "
            "or > 4 lings seen (t<90); counts every ling ever seen and not dead",
            (0, 180), False, "every step",
        ),
        AresIntelFlag(
            "get_enemy_roach_rushed", "Zerg", "units",
            ">= 6 roaches within 50 of our start (t<240), or >= 3 roaches seen (t<180)",
            (0, 240), False, "every step",
        ),
        AresIntelFlag(
            "get_enemy_went_reaper", "Terran", "units",
            ">= 1 reaper ever seen",
            None, False, "every step",
        ),
        AresIntelFlag(
            "get_enemy_ravager_rush", "Zerg", "units",
            ">= 1 ravager seen, before 240 s",
            (0, 240), True, "on read",
        ),
        AresIntelFlag(
            "get_enemy_marine_rush", "Terran", "units+structures",
            ">= 3 barracks (t<180), or marines >= max(3, int(t)//45) more than 60 from the enemy "
            "start (t<300); False once t>210, any factory seen, or >= 2 enemy townhalls",
            (0, 210), True, "on read",
        ),
        AresIntelFlag(
            "get_enemy_went_marine_rush", "Terran", "units+structures",
            "latch: set only when get_enemy_marine_rush is read and True",
            (0, 210), False, "on read",
        ),
        AresIntelFlag(
            "get_enemy_marauder_rush", "Terran", "units+structures",
            "barracks tech lab within 55 of our natural, or >= 2 marauders (t<210), "
            "or >= 1 marauder (t<160)",
            (0, 240), True, "on read",
        ),
        AresIntelFlag(
            "get_enemy_went_marauder_rush", "Terran", "units+structures",
            "latch: set only when get_enemy_marauder_rush is read and True",
            (0, 240), False, "on read",
        ),
        AresIntelFlag(
            "get_enemy_four_gate", "Protoss", "structures",
            ">= 3 gateways (warp gates not counted) with < 2 enemy townhalls; False once t>210",
            (0, 200), True, "on read",
        ),
        AresIntelFlag(
            "get_enemy_went_four_gate", "Protoss", "structures",
            "latch: set only when get_enemy_four_gate is read and True",
            (0, 200), False, "on read",
        ),
        AresIntelFlag(
            "get_is_proxy_zealot", "Protoss", "units+structures",
            ">= 2 gateways within 100 of our start and > 60 from the enemy start, or >= 1 zealot "
            "within 65 of our start (t<150)",
            (0, 240), True, "on read",
        ),
        AresIntelFlag(
            "get_enemy_expanded", "any", "structures",
            "an enemy townhall > 6 from the enemy start location (no timing check)",
            None, True, "on read",
        ),
        AresIntelFlag(
            "get_enemy_has_base_outside_natural", "any", "structures",
            "an enemy townhall > 6 from both the enemy start and the enemy natural",
            None, True, "on read",
        ),
        AresIntelFlag(
            "get_did_enemy_rush", "any", "units+structures",
            "OR of ling/worker/roach rushed, marauder rush without expansion, proxy zealot, ravager "
            "rush, marine latch with no enemy structure within 15 of our natural, four gate, "
            ">= 3 roaches (t<240), >= 1 ling (t<105), >= 2 barracks (t<120)",
            None, False, "on read",
        ),
        AresIntelFlag(
            "get_enemy_was_greedy", "any", "structures",
            "never computed in ares v3.13.1: always False",
            None, True, "never",
        ),
    )
}


# ---------------------------------------------------------------------------------------------
# M1: openers, economy, supply, 3 bases, wall fallback
# ---------------------------------------------------------------------------------------------

# §1 economy-first: probes to this count. Must equal `ConstantWorkerProductionTill` in
# protoss_builds.yml, which covers the opener (checked at start-up).
PROBE_TARGET: int = 66
MAX_BASES: int = 3  # M1 deliverable: 3 bases
# While a threat plan forbids expanding (M2): probes to this many per ready base, plus a spare
# few for the next base (16 on minerals + 6 on gas saturate one base)
PROBES_PER_HELD_BASE: int = 22
PROBES_HELD_SPARE: int = 6

# §3/§6 cadence, in on_step calls (GameStep 2: one call every 2 game loops)
MACRO_EVERY_STEPS: int = 4  # economy, timed schedule, production
ARMY_EVERY_STEPS: int = 4

# Safety net: if the ares opener is still running at this game time, end it and let
# Citadel's macro rules take over (a stuck step would otherwise stall the whole build).
OPENER_TIMEOUT_S: float = 240.0

# Pylon timing after the opener (macro/supply.py): keep this much free supply, counting what
# Pylons (and a nearly finished Nexus) will add, per ready Nexus and production structure
SUPPLY_BUFFER_PER_PRODUCER: int = 3
SUPPLY_MIN_BUFFER: int = 6
SUPPLY_MAX_PYLONS_AT_ONCE: int = 4  # Pylons ordered but not yet started, at most
# When ares has no Pylon spot left (macro/supply.py), a free tile at least this far from ...
PYLON_FALLBACK_MINERAL_CLEARANCE: float = 3.5  # ... any mineral field of that base
PYLON_FALLBACK_RAMP_CLEARANCE: float = 5.0  # ... the main ramp top
PYLON_FALLBACK_CANNON_CLEARANCE: float = 9.0  # ... any enemy Photon Cannon
PYLON_STUCK_S: float = 25.0  # a Pylon order not started after this doesn't count as on its way
PYLON_FALLBACK_SCAN_EVERY_S: float = 2.0  # the fallback search is a few thousand tile checks

# Gas buildings after each opener's timed schedule is finished: this many per ready base
GAS_PER_BASE_AFTER_SCHEDULE: int = 2
# Gas float (macro/economy.py): from GAS_FLOAT_HIGH banked, this many probes per gas building,
# until the bank is below GAS_FLOAT_LOW (M2, Citadel)
GAS_FLOAT_HIGH: int = 700
GAS_FLOAT_LOW: int = 300
WORKERS_PER_GAS_FLOATING: int = 1
# A probe waiting at an expansion holds the macro plan's later spending for at most this long
RESERVE_FOR_PENDING_MAX_S: float = 45.0

# §4.1 chrono: Nexus probes until the Core is ready, then Warp Gate research. After that
# (Citadel's choice, not in the spec): the first busy structure type in this order.
CHRONO_AFTER_WARPGATE: Tuple[UnitTypeId, ...] = (
    UnitTypeId.NEXUS,  # only while probes < PROBE_TARGET
    UnitTypeId.ROBOTICSFACILITY,
    UnitTypeId.FORGE,
    UnitTypeId.TWILIGHTCOUNCIL,
    UnitTypeId.STARGATE,
)


class ScheduleItem(NamedTuple):
    """One timed opener step (§4.1), run by bot/macro/build_executor.py after the ares opener.

    The item becomes active at `at_s` game seconds (TUNE) and stays active until satisfied.
    `count` is the total wanted, counting finished and in-progress ones.
    """

    at_s: float
    kind: str  # "structure", "unit", "upgrade", "gas" or "bases"
    type_id: Optional[object] = None  # UnitTypeId (structure/unit) or UpgradeId (upgrade)
    count: int = 1
    where: str = "main"  # structures: "main", "nat" or "ramp" (ares's ramp-wall spots)
    # Must hold before the item acts (see build_executor.CONDITIONS)...
    only_if: Optional[str] = None
    # ...unless the game time is past this (None: wait for the condition forever)
    only_if_until_s: Optional[float] = None
    # Activates the item before `at_s` when this condition holds
    early_if: Optional[str] = None


# Per-opener timed steps (§4.1). Names match protoss_builds.yml. Times are TUNE.
# Citadel's choices where the spec is silent are marked "(Citadel)".
_A_SCHEDULE: Tuple[ScheduleItem, ...] = (
    ScheduleItem(170, "structure", UnitTypeId.ROBOTICSFACILITY),  # ~2:50
    ScheduleItem(170, "unit", UnitTypeId.OBSERVER),  # Robo's first unit
    # Battery at the natural when the Robo starts; a Pylon there first to power it (Citadel)
    ScheduleItem(170, "structure", UnitTypeId.PYLON, 1, "nat", only_if="robo_started"),
    ScheduleItem(170, "structure", UnitTypeId.SHIELDBATTERY, 1, "nat", only_if="robo_started"),
    ScheduleItem(210, "structure", UnitTypeId.GATEWAY, 3),  # ~3:30 2nd and 3rd Gateway
    ScheduleItem(225, "gas", None, 4),  # ~3:45 3rd/4th gas
    ScheduleItem(255, "structure", UnitTypeId.FORGE),  # ~4:15
    ScheduleItem(255, "upgrade", UpgradeId.PROTOSSGROUNDWEAPONSLEVEL1),
    ScheduleItem(285, "bases", None, 3),  # ~4:45 3rd Nexus
)
_A2_SCHEDULE: Tuple[ScheduleItem, ...] = (
    ScheduleItem(150, "structure", UnitTypeId.GATEWAY, 2),  # 2:30 2nd Gateway
    ScheduleItem(170, "structure", UnitTypeId.ROBOTICSFACILITY),
    ScheduleItem(170, "unit", UnitTypeId.OBSERVER),
    ScheduleItem(170, "structure", UnitTypeId.PYLON, 1, "nat", only_if="robo_started"),
    ScheduleItem(170, "structure", UnitTypeId.SHIELDBATTERY, 1, "nat", only_if="robo_started"),
    ScheduleItem(210, "structure", UnitTypeId.GATEWAY, 3),
    ScheduleItem(225, "gas", None, 4),
    ScheduleItem(255, "structure", UnitTypeId.FORGE),
    ScheduleItem(255, "upgrade", UpgradeId.PROTOSSGROUNDWEAPONSLEVEL1),
    ScheduleItem(330, "bases", None, 3),  # 3rd Nexus waits until 5:30
)
# B's 3rd Nexus waits for ares's ling/roach/ravager flags to be clear. ares latches the ling and
# roach flags for the whole game, so from this time the Nexus goes down anyway (Citadel).
B_THIRD_FLAG_WAIT_UNTIL_S: float = 330.0
_B_SCHEDULE: Tuple[ScheduleItem, ...] = (
    ScheduleItem(160, "structure", UnitTypeId.PYLON, 1, "nat"),  # powers the batteries (Citadel)
    ScheduleItem(165, "structure", UnitTypeId.STARGATE),  # ~2:45
    ScheduleItem(165, "unit", UnitTypeId.ORACLE),
    # 2 batteries at the natural by 3:30: started at 3:00 (Citadel)
    ScheduleItem(180, "structure", UnitTypeId.SHIELDBATTERY, 2, "nat"),
    ScheduleItem(225, "gas", None, 4),  # (Citadel: A's gas timing)
    ScheduleItem(
        230, "bases", None, 3,  # ~3:50
        only_if="no_zerg_rush_flag", only_if_until_s=B_THIRD_FLAG_WAIT_UNTIL_S,
    ),
    ScheduleItem(240, "structure", UnitTypeId.ROBOTICSFACILITY),  # ~4:00
    ScheduleItem(240, "unit", UnitTypeId.OBSERVER),
)
_B2_SCHEDULE: Tuple[ScheduleItem, ...] = (
    ScheduleItem(160, "structure", UnitTypeId.PYLON, 1, "nat"),
    ScheduleItem(165, "structure", UnitTypeId.ROBOTICSFACILITY),  # replaces the Stargate
    ScheduleItem(165, "unit", UnitTypeId.OBSERVER),
    ScheduleItem(180, "structure", UnitTypeId.SHIELDBATTERY, 2, "nat"),
    ScheduleItem(180, "structure", UnitTypeId.GATEWAY, 3),  # 3:00 (3 Gateways in total)
    ScheduleItem(225, "gas", None, 4),
    ScheduleItem(
        230, "bases", None, 3,
        only_if="no_zerg_rush_flag", only_if_until_s=B_THIRD_FLAG_WAIT_UNTIL_S,
    ),
)
_C_SCHEDULE: Tuple[ScheduleItem, ...] = (
    ScheduleItem(140, "structure", UnitTypeId.GATEWAY, 2),  # 2:20
    ScheduleItem(170, "structure", UnitTypeId.ROBOTICSFACILITY),  # 2:50
    ScheduleItem(170, "unit", UnitTypeId.OBSERVER),
    ScheduleItem(190, "bases", None, 2),  # 3:10 Nexus
    ScheduleItem(190, "structure", UnitTypeId.PYLON, 1, "nat"),
    ScheduleItem(190, "structure", UnitTypeId.SHIELDBATTERY, 1, "nat"),
    ScheduleItem(225, "gas", None, 4),  # (Citadel: A's gas timing)
    # No 3rd base before 5:30 unless the enemy has one
    ScheduleItem(330, "bases", None, 3, early_if="enemy_third"),
)
_C2_SCHEDULE: Tuple[ScheduleItem, ...] = (
    ScheduleItem(170, "structure", UnitTypeId.ROBOTICSFACILITY),  # ~2:50
    ScheduleItem(170, "unit", UnitTypeId.OBSERVER),
    ScheduleItem(170, "structure", UnitTypeId.PYLON, 1, "nat"),
    # Battery at the natural when the Nexus finishes
    ScheduleItem(170, "structure", UnitTypeId.SHIELDBATTERY, 1, "nat", only_if="nat_ready"),
    ScheduleItem(190, "structure", UnitTypeId.GATEWAY, 2),  # ~3:10
    ScheduleItem(225, "gas", None, 4),
    # Never a third before 5:00 unless the enemy has also expanded
    ScheduleItem(300, "bases", None, 3, early_if="enemy_expanded"),
)
# What every opener has built by its last step. Prepended to each schedule: when a threat flag
# ends the ares opener early (§3 step 3), these finish it; otherwise they are already met.
# The natural waits for DefensePlan.allow_expand (bases_target).
# M5: the gas waits for a Gateway (until OPENER_ESSENTIALS_GAS_WAIT_S), as in every opener. A flag
# pre-raised from opponent memory ends the opener at 0:00, and taking both gases first delayed the
# first Pylon: a 31 s supply block (0:18-0:49) and a 0:57 Gateway against a 12-pool
OPENER_ESSENTIALS_GAS_WAIT_S: float = 90.0
# M5: §4.4 rows 7/10 (the proxy check) wait this long after the enemy main counts as scouted, so
# the probe's lap can see a Forge there first (row 3); with CANNON_RUSH pre-raised from memory the
# scout reached the main earlier and the Forge came into vision 1 s too late (a false PROXY)
PROXY_CHECK_SETTLE_S: float = 3.0
OPENER_ESSENTIALS: Tuple[ScheduleItem, ...] = (
    ScheduleItem(0, "structure", UnitTypeId.GATEWAY, 1, "ramp"),
    ScheduleItem(0, "structure", UnitTypeId.CYBERNETICSCORE, 1, "ramp"),
    ScheduleItem(0, "gas", None, 2, only_if="gateway_started", only_if_until_s=OPENER_ESSENTIALS_GAS_WAIT_S),
    ScheduleItem(0, "upgrade", UpgradeId.WARPGATERESEARCH),
    ScheduleItem(0, "bases", None, 2),
)
OPENER_SCHEDULES: dict[str, Tuple[ScheduleItem, ...]] = {
    "A_Standard": _A_SCHEDULE,
    "A2_Safe": _A2_SCHEDULE,
    "B_PvZ": _B_SCHEDULE,
    "B2_PvZSafe": _B2_SCHEDULE,
    "C_2GateRobo": _C_SCHEDULE,
    "C2_1GateExpand": _C2_SCHEDULE,
    "A_vRandom": _A_SCHEDULE,
    "A2_vRandom": _A2_SCHEDULE,
}

# §4.5.1 army composition (%). M1 scaffolding (production.py). Archons are left out because
# High Templar are cut from v1 (§7); the remaining shares are rescaled to 100%.
# Observers are a fixed count, not a share.
ARMY_COMPOSITION_PCT: dict[str, dict[UnitTypeId, float]] = {
    "Terran": {
        UnitTypeId.STALKER: 30, UnitTypeId.ZEALOT: 20, UnitTypeId.IMMORTAL: 15,
        UnitTypeId.COLOSSUS: 25, UnitTypeId.SENTRY: 1,
    },
    "Zerg": {
        UnitTypeId.ZEALOT: 25, UnitTypeId.STALKER: 25, UnitTypeId.IMMORTAL: 25,
        UnitTypeId.COLOSSUS: 10,
    },
    "Protoss": {
        UnitTypeId.STALKER: 40, UnitTypeId.IMMORTAL: 25, UnitTypeId.COLOSSUS: 25,
        UnitTypeId.ZEALOT: 10,
    },
}
# ares SpawnController priority (0 = highest)
ARMY_PRIORITY: dict[UnitTypeId, int] = {
    UnitTypeId.COLOSSUS: 0, UnitTypeId.IMMORTAL: 1, UnitTypeId.STALKER: 2,
    UnitTypeId.ZEALOT: 3, UnitTypeId.SENTRY: 4,
}
OBSERVER_COUNT: int = 2  # §4.5.1 "Observer 2 fixed"
# At this many banked minerals, also warp in Gateway units without waiting on higher-priority
# units that are short of gas
MINERAL_FLOAT_BANK: int = 700
# An unpowered idle Gateway blocks ares's SpawnController after Warp Gate: a Pylon within this
# many tiles of it, re-ordered at most this often
GATEWAY_POWER_SEARCH: int = 5
GATEWAY_POWER_RETRY_S: float = 30.0
# ProductionController (adds Gateways/Robos and the tech they need) starts when the opener's
# timed schedule is finished, or at this time at the latest
PRODUCTION_CONTROLLER_START_S: float = 330.0
MAX_PRODUCTION_STRUCTURES: int = 12
# §4.5.1 upgrades: Forge weapons first, then armour; Twilight -> Charge (vs Z, T) or Blink (vs P);
# then Colossus range. One at a time, in this order; UpgradeController builds the tech structures
# each one needs.
UPGRADES_START_S: float = 300.0
UPGRADES_VS_ZT: Tuple[UpgradeId, ...] = (
    UpgradeId.PROTOSSGROUNDWEAPONSLEVEL1, UpgradeId.PROTOSSGROUNDWEAPONSLEVEL2,
    UpgradeId.PROTOSSGROUNDARMORSLEVEL1, UpgradeId.CHARGE, UpgradeId.EXTENDEDTHERMALLANCE,
    UpgradeId.PROTOSSGROUNDARMORSLEVEL2,
)
UPGRADES_VS_P: Tuple[UpgradeId, ...] = (
    UpgradeId.PROTOSSGROUNDWEAPONSLEVEL1, UpgradeId.PROTOSSGROUNDWEAPONSLEVEL2,
    UpgradeId.PROTOSSGROUNDARMORSLEVEL1, UpgradeId.BLINKTECH, UpgradeId.EXTENDEDTHERMALLANCE,
    UpgradeId.PROTOSSGROUNDARMORSLEVEL2,
)

# Army (bot/army/army.py): home defense radii, rally point, structure hunt, status log
ARMY_DEFEND_RADIUS: float = 22.0  # enemies this close to a townhall (or the natural spot) are a home threat
ARMY_RALLY_OFFSET: float = 8.0  # defensive position: the newest base moved this far toward the enemy
HUNT_VISIT_RADIUS: float = 7.0  # a structure-hunt point counts as visited this close
HUNT_GRID_STEP: float = 20.0  # spacing of the structure-hunt grid over the playable area
ARMY_STATUS_EVERY_S: float = 60.0  # ARMY status log line
ORDER_REFRESH_S: float = 3.0  # don't re-issue the same order to a unit more often (§6 APM; wall holder)
# while the ATTACK squad is out, a home threat the DEFEND squad can't hold recalls it only if the
# enemies there are worth at least this share of the ATTACK squad's value (M2: supply)
ARMY_RECALL_FRACTION: float = 0.3

# §4.8 ramp wall fallback
WALL_RAMP_MAX_DIST: float = 30.0  # ramp top farther than this from our start: use a choke
WALL_CHOKE_MIN_DIST: float = 8.0  # ignore map-analyzer chokes this close to our start
WALL_BATTERY_MAX_DIST: float = 6.0  # battery within this of the ramp top, on the main side
WALL_HOLD_OFFSET: float = 1.5  # holding unit: ramp top moved this far toward the main
WALL_HOLD_UNTIL_S: float = 360.0  # the holding unit rejoins the army after this (Citadel)
WALL_SPOT_SEARCH_RADIUS: int = 3  # tiles searched around a wanted wall Pylon/Battery spot
# the wall-gap holder below this HP+shield fraction swaps with a Zealot/Adept above
# WALL_SWAP_FRESH_FRACTION within WALL_SWAP_RADIUS of the gap, and steps back WALL_SWAP_BACKOFF
# toward the main (Citadel; 12-pool test games lost one holder every ~20 s with the next unit
# standing behind it)
WALL_SWAP_HP_FRACTION: float = 0.35
WALL_SWAP_FRESH_FRACTION: float = 0.7
WALL_SWAP_RADIUS: float = 8.0
WALL_SWAP_BACKOFF: float = 3.0

# Telemetry snapshots (§8 metrics), game seconds
METRIC_TIMES_S: Tuple[int, ...] = (240, 360, 480, 600)
# M1 acceptance: 44 probes by 6:00 (12-worker ruleset)
M1_PROBES_AT_6_MIN: int = 44


# ---------------------------------------------------------------------------------------------
# M2: ares bridge, detectors, ThreatFlag expiry, defense plans
# ---------------------------------------------------------------------------------------------

# §3/§6 cadence: intel (ares bridge, detectors, flag expiry) and the defense planner
INTEL_EVERY_STEPS: int = 8

# §5 ThreatFlag expiry. Keyed by Threat name (bot/intel/threat_flags.py).
# UNIT evidence expires this long after it was last confirmed. §5 gives WORKER_RUSH,
# TIMING_ATTACK, ARMY_OUT_OF_POSITION and POOL_12; the others are Citadel's choice.
UNIT_TTL_S: dict[str, float] = {
    "WORKER_RUSH": 20.0,
    "TIMING_ATTACK": 30.0,
    "ARMY_OUT_OF_POSITION": 15.0,
    "POOL_12": 45.0,
    "CANNON_RUSH": 20.0,  # raised by an enemy probe in our main (Citadel)
    "PROXY": 45.0,  # raised by units, e.g. ares's marine-rush or reaper flags (Citadel)
    "ONE_BASE_ALLIN": 45.0,  # raised by units, e.g. ares's roach flag (Citadel)
}
UNIT_TTL_DEFAULT_S: float = 45.0
MIN_PLAN_DURATION_S: float = 20.0  # no flag expires sooner, except by rule (a)
RESCOUT_STALE_S: float = 90.0  # STRUCTURE evidence unseen this long: log a re-scout request
# §5 phase rules (c)
CANNON_RUSH_PHASE_END_S: float = 300.0  # and no enemy structure within the radius below
CANNON_RUSH_PHASE_RADIUS: float = 25.0
PROXY_PHASE_END_S: float = 330.0  # and no proxy structure known
ONE_BASE_PHASE_END_S: float = 420.0  # with ONE_BASE_PHASE_BATTERIES and the army supply below
ONE_BASE_PHASE_BATTERIES: int = 3
ONE_BASE_PHASE_ARMY_SUPPLY: int = 20
POOL_12_PHASE_END_S: float = 240.0

# §4.2 detectors (bot/intel/detectors.py, ares_bridge.py)
BRIDGE_HOME_RADIUS: float = 30.0  # "near our bases" for confirming units
BRIDGE_RAISE_UNTIL_S: float = 330.0  # ares flags with no time window raise flags until then
SAME_LEVEL_Z: float = 0.5  # terrain heights closer than this are the same level
MAIN_RADIUS: float = 22.0  # a main base: within this of its start location, on its level
# Worker rush (§4.2 local backup): >= 5 enemy workers within 30 of our main before 2:00
WORKER_RUSH_MIN_WORKERS: int = 5
WORKER_RUSH_RADIUS: float = 30.0
WORKER_RUSH_UNTIL_S: float = 120.0
WORKER_RUSH_CONFIRM_MIN: int = 2  # the pull ends at <= 1 enemy worker near our bases (§4.2)
# Cannon rush (§4.2): structures within 25 of our main/natural before 4:00; a probe in our main
# for > 10 s between 1:00 and 3:00
CANNON_RUSH_RADIUS: float = 25.0
CANNON_RUSH_UNTIL_S: float = 240.0
CANNON_PROBE_FROM_S: float = 60.0
CANNON_PROBE_UNTIL_S: float = 180.0
CANNON_PROBE_LINGER_S: float = 10.0
# 12-pool (§4.2): Zerglings seen before 2:20
EARLY_LINGS_UNTIL_S: float = 140.0
# a Pool started by then came before any natural Hatchery could (12 workers: the earliest
# hatch-first natural goes down at ~0:48), so no natural check is needed (Citadel)
EARLY_POOL_CERTAIN_S: float = 45.0
# Proxy (§4.4 rows 7 and 10), checked once the enemy main is scouted and not before 1:30
PROXY_CHECK_FROM_S: float = 90.0
PROXY_CHECK_UNTIL_S: float = 180.0  # ... and only if the main was scouted by then (Citadel)
MAIN_SAMPLE_STEP: float = 4.0  # enemy main sample-point spacing for "main scouted"
MAIN_SCOUTED_FRACTION: float = 0.6  # this share of the sample points seen = main scouted
PROXY_TERRAN_MAX_SCVS: int = 12
PROXY_PROTOSS_WORKERS_SHORT: int = 2
PROXY_FAR_FROM_MAIN: float = 50.0  # §4.2: a production structure this far from the enemy main
PROXY_NEAR_ENEMY_TOWNHALL: float = 15.0  # ...and not next to one of their townhalls (Citadel)
PROXY_DETECT_UNTIL_S: float = 330.0  # far production after this is not a proxy (Citadel)
# One-base (§4.2 detectors.no_natural): no natural townhall by 2:45 (T/P) or 2:15 (Z),
# with >= 2 gas or >= 3 production structures. Random uses the T/P time until the race is seen.
NO_NATURAL_DEADLINE_S: dict[str, float] = {"Terran": 165.0, "Protoss": 165.0, "Zerg": 135.0, "Random": 165.0}
NO_NATURAL_MIN_GAS: int = 2
NO_NATURAL_MIN_PRODUCTION: int = 3
NO_NATURAL_SEEN_GRACE_S: float = 10.0  # the natural counts as seen at the deadline if seen this recently
NO_NATURAL_GIVE_UP_S: float = 30.0  # natural still unseen this long after the deadline: skip the check
NATURAL_TOWNHALL_RADIUS: float = 6.0  # an enemy townhall this close to their natural spot
# The main probe watches the enemy natural from this far toward the map centre until the
# no-natural deadline above (§4.3 probe route; user decision in M2)
NAT_SCOUT_STANDOFF: float = 7.0

# §4.2 defense plans (bot/defense/)
WORKER_RUSH_KEEP_MINING: int = 2  # §4.2: pull all probes except 2
WORKER_RUSH_SWAP_HP: float = 15.0  # §4.2: a pulled probe below this HP+shield goes back to mining
WORKER_RUSH_END_AT: int = 1  # §4.2: end the pull when enemy workers near our base are <= 1
CANNON_PROBES_PER_PYLON: int = 3  # §4.2
CANNON_PROBES_PER_CANNON: int = 4  # §4.2
CANNON_PROBES_PER_ENEMY_PROBE: int = 1  # §4.2: "kill the enemy probe with 1-2 probes"
CANNON_PROBES_ON_PROBES_MAX: int = 2
CANNON_PULL_MAX: int = 12  # never more probes than this on a cannon rush (Citadel)
CANNON_NEARLY_DONE: float = 0.6  # probes skip targets in range of a Cannon this far built
# while a finished enemy Cannon covers one of our Nexuses, this many Gateway units come before
# probes and buildings (Citadel)
CANNON_SIEGE_RESERVE_UNITS: int = 3
EXPANSION_RETRY_S: float = 90.0  # after a Nexus builder dies on its way, no expansion for this long
CANNON_COVER_EXTRA: float = 1.0  # safety margin on a finished Cannon's range
LING_DEFENSE_RADIUS: float = 9.0  # §4.2 "lings in the mineral line": this close to a mineral line
LING_DEFENSE_PROBES_PER_LING: int = 2
LING_DEFENSE_MAX: int = 16
LING_DEFENSE_PULL_RADIUS: float = 15.0  # only probes this close to the lings (and on their level)
POOL_12_UNITS_BEFORE_EXPAND: int = 3  # §4.2: resume the Nexus at >= 3 units ...
POOL_12_LING_CLEAR_RADIUS: float = 20.0  # ... and no lings within 20
POOL_12_GATE_HOLD_S: float = 10.0  # that condition must hold (or fail) this long to switch
POOL_12_PUSH_SUPPLY: int = 16  # from this army supply the army holds the natural, not the ramp
POOL_12_GATEWAYS: int = 2  # (Citadel; §4.2 names none for 12-pool)
# the first Gateway units wait for nothing else (Citadel): with 1, the second unit came 78 s
# after the wall Zealot in a Magannatha test game while probes and buildings took the money
POOL_12_RESERVE_UNITS: int = 3
DEFENSE_TECH_AFTER_SUPPLY: int = 8  # proxy / one-base plans: timed tech waits below this army supply
HOLD_SHIFT_STEP: float = 2.0  # a hold point a finished enemy Cannon covers moves this far inward ...
HOLD_SHIFT_STEPS: int = 6  # ... at most this many times
POOL_12_MAIN_BATTERIES: int = 1
PROXY_UNITS_BEFORE_EXPAND: int = 2  # §4.2: skip the natural until 2 units are out
PROXY_GATEWAYS: int = 2
PROXY_MAIN_BATTERIES: int = 1
ONE_BASE_BATTERIES: int = 3  # §4.2 "2-3"; §5's phase rule counts 3
RAMP_HOLD_OFFSET: float = 2.0  # hold point: ramp top moved this far toward the main
POOL_12_HOLD_OFFSET: float = 4.0  # 12-pool: the army waits this far inside, behind the wall gap
ARMY_HOLD_LEASH: float = 8.0  # ramp holds: engage only enemies this close to the hold point ...
# ... or inside our main. Lone enemy workers this close to a townhall are army targets too,
# and enemy structures near our townhalls once the army has this much supply.
ARMY_WORKER_THREAT_RADIUS: float = 12.0
ARMY_CLEAR_STRUCTURES_SUPPLY: int = 8
NATURAL_HOLD_OFFSET: float = 6.0  # hold point: natural moved this far toward the enemy
MAIN_BATTERY_RAMP_DIST: float = 6.0  # main batteries within this of the ramp top, main level
# ... but clear of the path from the ramp top and the wall gap into the main (this long, and
# this far to each side of it, plus the building's own half-size)
RAMP_CORRIDOR_LENGTH: float = 6.0
RAMP_CORRIDOR_HALF_WIDTH: float = 1.5
MAIN_BATTERY_SEARCH_RADIUS: int = 5  # tiles searched around the wanted main battery/Pylon spot
DEFENSE_ORDER_RETRY_S: float = 20.0  # a probe sent to build that hasn't started may be re-sent
# structures (and our build orders) within this of the natural's townhall spot are "at the
# natural"
NATURAL_RADIUS: float = 14.0
# a builder that dies with an enemy Cannon, Bunker or Spine/Spore, or an enemy unit, within this
# of its target: the order is dropped and the spot blocked instead of ares sending the next
# probe there (static_defense.py)
BUILDER_DANGER_RADIUS: float = 12.0
# cancel our unfinished structure once its HP + shield is below this fraction of what it would
# have at its build progress if undamaged (a structure starts at BUILD_START_HP_FRACTION of its
# max and gains the rest as it builds). ares's own unused rule (health < max(50, 9% of max HP),
# building_manager.py:697-699) cancels a freshly placed Pylon at its first hit.
CANCEL_EXPECTED_FRACTION: float = 0.3
BUILD_START_HP_FRACTION: float = 0.1  # the game's: a new structure starts at 10% HP and shield


# ---------------------------------------------------------------------------------------------
# M3: scout planner (DESIGN.md §4.3), scouting-based flags (§4.4 rows 3 and 15), scout metrics
# ---------------------------------------------------------------------------------------------

# §8 "first enemy aggression time" (telemetry): the first visible enemy non-worker unit this
# close to one of our townhalls, this many enemy workers that close, or an enemy structure
# within CANNON_RUSH_RADIUS of our main/natural
AGGRESSION_RADIUS: float = 30.0
AGGRESSION_WORKERS: int = 3
# M3 acceptance: a scout lost before this game time counts against "no scout lost before 4:00"
SCOUT_LOSS_CHECK_S: float = 240.0

# M3 acceptance (user decision): per scripted cheese bot, the flag that must be raised, the game
# second it must be raised by (before the cheese reaches us), and the other threats that may also
# be raised in the game. Any other threat raised in the game is a false flag.
M3_EXPECTED_FLAGS: dict[str, tuple[str, float, Tuple[str, ...]]] = {
    "worker_rush": ("WORKER_RUSH", 60.0, ("UNKNOWN_AGGRO",)),
    "cannon_rush": ("CANNON_RUSH", 90.0, ("UNKNOWN_AGGRO",)),
    "twelve_pool": ("POOL_12", 105.0, ("ONE_BASE_ALLIN", "UNKNOWN_AGGRO")),
    "proxy_rax": ("PROXY", 120.0, ("ONE_BASE_ALLIN", "UNKNOWN_AGGRO")),
}
# M5: flags that describe the enemy army rather than a cheese; allowed in every M3 check
M3_ALWAYS_ALLOWED: Tuple[str, ...] = ("ARMY_OUT_OF_POSITION",)
M3_FLAG_RATE: float = 0.8  # correct flag in >= 80% of each bot's games
M3_SCOUT_SAFE_RATE: float = 0.7  # no scout lost before 4:00 in >= 70% of games

# §4.3 scouts: every scout goes home below this HP+shield fraction
SCOUT_RETREAT_HP: float = 0.5
# a scout waypoint that isn't in vision this long after the scout set off for it is skipped
SCOUT_WAYPOINT_TIMEOUT_S: float = 25.0
# a move order to within this of the scout's current move target is not re-issued (§6 APM)
SCOUT_REORDER_DIST: float = 1.0
# a probe scout is home (and goes back to mining) this close to our start location, or to one of
# our townhalls; mining orders take it through our own wall units (Citadel)
SCOUT_HOME_RADIUS: float = 25.0
SCOUT_HOME_TOWNHALL_RADIUS: float = 12.0
# Main probe (§4.3 "0:40 or Gateway placement"): the opener's `worker_scout` probe is taken over at
# once; with no such probe by this time, the planner picks one itself
MAIN_PROBE_FALLBACK_S: float = 45.0
# its lap around the enemy main: this many directions, at the first of these distances from the
# enemy start location that is pathable and on the main's level
MAIN_LAP_POINTS: int = 8
MAIN_LAP_RADII: Tuple[float, ...] = (11.0, 14.0, 8.0, 17.0)
# a main probe still outside the enemy main this long after setting off (a wall, e.g. Terran
# depots) laps from where it is; the lap ends after MAIN_LAP_MAX_S either way
MAIN_PROBE_TO_MAIN_S: float = 75.0
MAIN_LAP_MAX_S: float = 50.0
# a main probe that came home (or died) before the enemy main was scouted is replaced this many
# times, up to this game time, once no rush flag is active (Citadel)
MAIN_PROBE_RETRIES: int = 1
MAIN_PROBE_RETRY_UNTIL_S: float = 150.0
# §4.3 "return through the likely proxy spots (map-analyzer regions within 40 of our natural)":
# region centres, expansion locations and a ring around our natural, at least this far apart
PROXY_SPOT_RADIUS: float = 40.0
PROXY_SPOT_MIN_FROM_NATURAL: float = 10.0
PROXY_SPOT_SPACING: float = 12.0
PROXY_RING_RADIUS: float = 28.0
PROXY_RING_POINTS: int = 8
# §4.3 second probe: sent between these times if the enemy main showed fewer structures than
# expected (no Barracks/Gateway there, T/P), or when row 3's Forge-first flag is raised; it
# patrols our natural perimeter and main edge, then goes home
PATROL_FROM_S: float = 60.0
PATROL_START_UNTIL_S: float = 100.0
PATROL_FORGE_UNTIL_S: float = 180.0  # Forge-first (§4.4 row 3) starts one until then
PATROL_NATURAL_RADIUS: float = 12.0
PATROL_MAIN_EDGE: float = 16.0  # main-edge points this far from our start location
PATROL_POINTS: int = 6  # per ring
PATROL_LOOPS: int = 2

# §4.4 row 3 "at 1:30": an enemy Forge with no Gateway in the Protoss main raises a weak
# CANNON_RUSH once their natural was seen without a Nexus, or from this time without seeing it;
# the patrol probe goes out and this many minerals stay banked
FORGE_FIRST_UNTIL_S: float = 90.0
FORGE_FIRST_BANK: int = 150
# §4.4 row 15: UNKNOWN_AGGRO lasts until the enemy main is scouted, or until this time (Citadel)
UNKNOWN_AGGRO_PHASE_END_S: float = 300.0
UNKNOWN_AGGRO_EXTRA_BATTERIES: int = 1  # "+1 Battery"

# §4.3 per-matchup unit scouts (scout_planner.py). Combat units are only taken while none of the
# M2 defense threats is active (Defense > Scouting, §3), except UNKNOWN_AGGRO's own re-scout
UNIT_SCOUT_HOME_RADIUS: float = 15.0  # a unit scout is back (the army takes it) this close to our natural or start
# Adept shade: PvT at Core + ~40 s, PvZ at ~3:00. The Adept walks to the bottom of the enemy main
# ramp and shades up into the main; the shade is cancelled before it ends (it lives ~7 s and the
# Adept teleports to it when it does, docs/VERIFY_NOTES.md M3 findings)
ADEPT_SCOUT_AFTER_CORE_S: float = 40.0
ADEPT_SCOUT_PVZ_S: float = 180.0
SHADE_CAST_DIST: float = 3.0  # from the enemy ramp bottom ...
SHADE_CAST_MAX_DIST: float = 14.0  # ... or from this close once the Adept is in danger
SHADE_CANCEL_S: float = 6.0
SHADE_WAIT_S: float = 15.0  # at the ramp, wait this long for the shade to come off cooldown
# PvP Stalker poke at Core + ~30 s: looks at the enemy natural, then comes back
STALKER_POKE_AFTER_CORE_S: float = 30.0
# PvZ Oracle at ~3:45 (only if the opener made one): over the enemy natural, main and third
ORACLE_SCOUT_S: float = 225.0
ORACLE_REVELATION_MIN_UNITS: int = 4  # Revelation on a clump of at least this many enemy units ...
ORACLE_CLUMP_RADIUS: float = 5.0  # ... within this of one of them
ORACLE_DRONE_SAFE_RADIUS: float = 10.0  # §4.3: kill Drones only if no Queen or Spore is within 10
ORACLE_DRONE_RANGE: float = 8.0  # Drones this close to the Oracle
ORACLE_BEAM_MIN_ENERGY: float = 50.0  # the beam costs 25 to turn on, then drains (VERIFY_NOTES M3)
ORACLE_HARASS_MAX_S: float = 12.0
# Observers: PvT Robo + ~30 s to the path between the enemy natural and ours; PvP Robo done to
# outside the enemy natural choke; a 2nd one at home (PvP) once a Twilight Council is seen
OBSERVER_AFTER_ROBO_S: float = 30.0
OBSERVER_PATH_FRACTION: float = 0.35  # PvT post: this far from the enemy natural toward ours
OBSERVER_CHOKE_STANDOFF: float = 14.0  # PvP post: this far from the enemy natural toward ours
OBSERVER_DETECTED_BACKOFF: float = 6.0  # a detected Observer moves this far back toward our natural
OBSERVER_POST_UNTIL_S: float = 360.0  # §4.3 "from 6:00 travels with the army" (the army claims one, OBSERVER_WITH_ARMY_FROM_S)
HOME_OBSERVER_OFFSET: float = 8.0  # home Observer: our natural moved this far toward our main
# §4.3 "4:30, then every 60 s: visit each unscouted enemy expansion location" (Observer, else probe)
EXPANSION_CHECK_FROM_S: float = 270.0
EXPANSION_CHECK_EVERY_S: float = 60.0
EXPANSION_FRESH_S: float = 60.0  # a location in vision this recently is not visited
EXPANSION_CHECK_MAX: int = 5  # locations per trip
# §5 re-scout trigger: the enemy main unseen this long after MAIN_STALE_FROM_S; stale evidence of
# a STRUCTURE flag may go to a probe only this close to our natural (else an Observer)
MAIN_STALE_S: float = 60.0
MAIN_STALE_FROM_S: float = 180.0
RESCOUT_PROBE_RADIUS: float = 45.0
# §4.3 hallucinated Phoenix, only with a Sentry that already exists (user decision): at these
# times per enemy race, and whenever the enemy main has been unseen for HALLUCINATION_STALE_S
# after HALLUCINATION_FROM_S (PvT row: 90 s)
# M7 (user decision): the PvP ~4:30 and PvZ ~6:30 rows are dropped (the vs-P and vs-Z mixes have no
# Sentry, so they never fired; DESIGN.md §4.3)
HALLUCINATION_AT_S: dict[str, float] = {"Terran": 330.0}
HALLUCINATION_FROM_S: float = 240.0
HALLUCINATION_STALE_S: dict[str, float] = {"Terran": 90.0}
HALLUCINATION_STALE_DEFAULT_S: float = 60.0
HALLUCINATION_MIN_GAP_S: float = 45.0  # one Phoenix at a time (they live ~43 s)
PHOENIX_AWAY_DIST: float = 20.0  # after the natural, the Phoenix flies this far back toward our base
# scouts keep this far outside the range of enemy static defense (Cannon, Bunker, Spine Crawler,
# Planetary Fortress; Turrets and Spores for fliers), counting ones at least CANNON_NEARLY_DONE
# built (M3: cannon-rush test games lost probes that walked past finished Cannons)
SCOUT_STATIC_MARGIN: float = 3.0
SCOUT_STATIC_STEP: float = 4.0  # a scout inside that margin moves this far straight away
# a one-off matchup scout (Adept shade, Stalker poke, Oracle) not started this long after its time
# (a defense plan held the units) is skipped; any unit scout comes back after UNIT_SCOUT_MAX_S
# (M3: 12-pool test games started the 3:00 PvZ Adept shade at 9:48-12:42)
UNIT_SCOUT_LATE_S: float = 90.0
UNIT_SCOUT_MAX_S: float = 120.0
# a scout steps out of grid danger (KeepUnitSafe) only when hurt or when an enemy that isn't a
# worker and can hit it is this close (M3: mining workers kept a probe out of an enemy main)
SCOUT_DANGER_RADIUS: float = 12.0


# ---------------------------------------------------------------------------------------------
# M4: squads, EngagementResult gates, retreat hysteresis, end-game (DESIGN.md §4.5.2, §4.7)
# ---------------------------------------------------------------------------------------------

# §4.5.2 gates on Citadel's EngagementResult (bot/army/engagement.py: our HP+shields, defender set;
# user decisions). Values compare as ints: LOSS_EMPHATIC 0 ... TIE 5 ... VICTORY_EMPHATIC 10.
ATTACK_START: int = 8  # launch at >= this with ATTACK_START_SUPPLY supply used ...
ATTACK_START_SUPPLY: int = 150
ATTACK_START_MAX: int = 5  # ... or at >= this with ATTACK_START_MAX_SUPPLY supply used
ATTACK_START_MAX_SUPPLY: int = 190
ATTACK_CONTINUE: int = 5  # keep attacking while >= this
RETREAT_AT: int = 4  # retreat at <= this (3-level hysteresis vs ATTACK_START)
DEFEND_ENGAGE: int = 4  # at home, inside the battery radius (batteries are not simulated)
MIN_STATE_SECONDS: float = 20.0  # no attack/retreat flip within this unless the result is <= ...
FLIP_ANYWAY_AT: int = 2  # ... this
RETREAT_VALUE_FRACTION: float = 0.4  # retreat when the squad's value is below this x its start value
RELAUNCH_WAIT_S: float = 45.0  # after a retreat, no launch for this long
# §4.5.2 inputs: remembered enemy army within this of the squad or its target; static defense
# within ENGAGE_STATIC_RADIUS of the target
ENGAGE_ENEMY_RADIUS: float = 20.0
ENGAGE_STATIC_RADIUS: float = 15.0
# §3 cadence, in on_step calls: attack decision (<= 2 simulations per evaluation); home defense
# is evaluated on the same tick
DECISION_EVERY_STEPS: int = 16
# §4.5.2 "Reinforcements rally in groups of >= 8 supply; never trickle them in"
REINFORCE_MIN_SUPPLY: int = 8
# §4.7 end-game and the 60-minute tie
END_GAME_FROM_S: float = 2400.0  # 40:00: structure hunt; no launch while our army value is behind
END_GAME_HUNT_UNSEEN_S: float = 60.0  # hunt when no enemy structure has been seen for this long
END_GAME_ATTACK_FROM_S: float = 2700.0  # 45:00: ATTACK_START drops to END_GAME_ATTACK_START ...
END_GAME_ATTACK_START: int = 6
END_GAME_VALUE_RATIO: float = 1.2  # ... if our army value is >= this x the enemy's remembered army
# Squads and micro (bot/army/army.py, micro.py; Citadel's choices where §4.5.2 is silent)
MICRO_RADIUS: float = 12.0  # a unit with a visible enemy this close gets per-step combat control
KITE_RANGE_MARGIN: float = 1.5  # a kiter steps back while the closest threat is this far beyond our reach
MOVE_REISSUE_DIST: float = 2.0  # a move/attack-move to within this of the current order target is not re-issued
HOLD_RADIUS: float = 6.0  # units holding a point walk back to it once farther than this
HOLD_ENGAGE_RADIUS: float = 12.0  # ... and fight enemies this close to it (the defense plan's leash if set)
RETREAT_DONE_RADIUS: float = 8.0  # a retreating unit this close to the defensive position holds there
ATTACK_SQUAD_RADIUS: float = 10.0  # ares squad radius: ATTACK units farther apart form separate groups
REGROUP_FRACTION: float = 0.25  # the main group waits while other groups hold this share of the squad's supply
REINFORCE_JOIN_RADIUS: float = 12.0  # a reinforcement group this close to the ATTACK squad's main group joins it
# enemy static defense near our bases (cannon rush) is attacked at this level, not ATTACK_CONTINUE:
# M2's "6 supply per finished Cannon" (3 Stalkers each) reads 7-8 (6 Stalkers vs 3 Cannons = 5,
# 12 vs 3 = 9), and at 5 the M4 army fed 4 units into rush Cannons (cannon_rush Ultralove game 2)
CLEAR_STATIC_LEVEL: int = 7
BATTERY_COVER_RADIUS: float = 8.0  # a fight this close to a ready Shield Battery of ours is "inside the battery radius"
OBSERVER_WITH_ARMY_FROM_S: float = 360.0  # §4.3 "from 6:00 travels with the army": one Observer
END_GAME_CORNER_INSET: float = 4.0  # hunt points at the playable area's corners, this far inside
END_GAME_POINTS_PER_TRIP: int = 8  # hunt points per Observer trip (a unit scout comes back after UNIT_SCOUT_MAX_S)


# ---------------------------------------------------------------------------------------------
# M5: counterattack (§4.6), opponent memory (§5), telemetry to ./data (§8), step guard (§6)
# ---------------------------------------------------------------------------------------------

# §4.6 gates on Citadel's EngagementResult (same 0-10 levels as §4.5.2)
COUNTER_START: int = 7  # launch at >= this against the defenders local to the target
COUNTER_ABORT: int = 4  # recall at <= this
# §4.4 row 17 / §4.6 ARMY_OUT_OF_POSITION (bot/intel/army_position.py), evaluated with the
# counterattack every DECISION_EVERY_STEPS (half a period after the main attack decision)
COUNTER_FROM_S: float = 300.0  # from 5:00
OUT_OF_POSITION_MIN_VALUE: float = 800.0  # remembered enemy army value (minerals + gas) ...
OUT_OF_POSITION_FRESH_S: float = 15.0  # ... at least OUT_OF_POSITION_FRESH_FRACTION of it seen this recently
OUT_OF_POSITION_FRESH_FRACTION: float = 0.6
OUT_OF_POSITION_PATH: float = 60.0  # its centre this far (ground path) from every known enemy townhall
OUT_OF_POSITION_PATH_CELL: float = 4.0  # path lengths are cached per cell of this size
OUT_OF_POSITION_PATH_CACHE_MAX: int = 2000  # ... and the cache is emptied beyond this many entries
# §4.6 target: the known enemy base with the lowest local defence value (remembered units within
# COUNTER_DEFENCE_RADIUS plus static defence within ENGAGE_STATIC_RADIUS, counted with §4.5.2's
# penalty in Stalkers' worth of value; a Shield Battery is Citadel's 1)
COUNTER_DEFENCE_RADIUS: float = 20.0
STATIC_PENALTY_STALKERS: dict[UnitTypeId, float] = {
    UnitTypeId.PHOTONCANNON: 3.0,
    UnitTypeId.BUNKER: 3.0,
    UnitTypeId.SPINECRAWLER: 3.0,
    UnitTypeId.PLANETARYFORTRESS: 8.0,
    UnitTypeId.SHIELDBATTERY: 1.0,
}
COUNTER_TARGET_ARMY_RADIUS: float = 25.0  # enemy army value within this of the target ...
COUNTER_TARGET_ARMY_FRACTION: float = 0.25  # ... is at most this share of the remembered army
COUNTER_BASE_RADIUS: float = 14.0  # the target base's workers, production and townhall are within this
COUNTER_THREAT_MARGIN: float = 1.0  # a defender this far beyond its reach to a squad unit is fought first
# §4.6 squad: Adepts, Zealots with Charge, then Stalkers, from units no one has pinned
COUNTER_SQUAD_MAX_FRACTION: float = 0.35  # of our army supply
COUNTER_SQUAD_MIN_SUPPLY: float = 8.0
# §4.6 recall
COUNTER_RECALL_TARGET_RADIUS: float = 35.0  # the out-of-position army's centre within this of the target ...
COUNTER_RECALL_SQUAD_RADIUS: float = 20.0  # ... or within this of the squad, ...
# ... or (user decision, M5 staged tests: on Torches the natural's only exit faces the returning
# army, and squads recalled at 35 lost 5-7 of 7 units) its centre this much closer to the target
# (ground path) than at launch: it is heading back
COUNTER_RECALL_HEADING_BACK: float = 20.0
COUNTER_RECALL_VALUE_FRACTION: float = 0.5  # squad value below this x its start value
COUNTER_MAX_OUT_S: float = 60.0
COUNTER_RELAUNCH_WAIT_S: float = 30.0  # Citadel: no new counterattack this soon after one ends

# §5 opponent memory (bot/memory/opponent_store.py): ./data/opponents/<OpponentId>.json
DATA_DIR: str = "data"  # §2: Citadel writes only under ./data (ares's own file is ./data/<id>-protoss.json)
OPPONENTS_SUBDIR: str = "opponents"
MEMORY_CHEESE: Tuple[str, ...] = ("WORKER_RUSH", "CANNON_RUSH", "POOL_12", "PROXY", "ONE_BASE_ALLIN")  # user decision
# weak sources that don't count toward the pre-raise (a Forge-first expand; an enemy probe alone,
# which M2 already doesn't let end the opener)
MEMORY_IGNORED_SOURCES: Tuple[Tuple[str, str], ...] = (("CANNON_RUSH", "forge_first"), ("CANNON_RUSH", "cannon_probe"))
MEMORY_LAST_GAMES: int = 3  # §5: the same cheese flag in >= MEMORY_MIN_GAMES of the last 3 games ...
MEMORY_MIN_GAMES: int = 2  # ... is pre-raised at 0:00 as STRUCTURE evidence with a phase-only expiry
MEMORY_KEEP_GAMES: int = 20  # threats_seen keeps entries from this many recent games
MEMORY_SOURCE: str = "memory"  # flag source of a pre-raised flag (never counted for the next game)
# Pre-raised flags that apply their plan but leave the ares opener running (user decision after the
# M5 12-pool A/B): the same flag raised in game, or the opener reaching its `expand` step (a Nexus
# the plan won't allow), ends it. Every other pre-raised cheese ends the opener at 0:00.
MEMORY_KEEPS_OPENER: Tuple[str, ...] = ("POOL_12",)
# §5 has no phase rule for WORKER_RUSH (UNIT evidence); a pre-raised one ends after this time once
# at most WORKER_RUSH_END_AT enemy workers are within BRIDGE_HOME_RADIUS of our bases (user decision)
WORKER_RUSH_MEMORY_END_S: float = 150.0

# §8 telemetry: one JSON line per game in ./data/logs/games.jsonl, the last GAME_LOG_KEEP games
LOGS_SUBDIR: str = "logs"
GAME_LOG_FILE: str = "games.jsonl"
GAME_LOG_KEEP: int = 200
DATA_MAX_BYTES: int = 4_500_000  # §2 keeps ./data under 5 MB: older log lines go first
GAME_LOG_MAX_EVENTS: int = 100  # at most this many flag/engage/counterattack entries per list
TELEMETRY_SNAPSHOT_EVERY_S: float = 30.0  # §3 step 7: a stdout snapshot this often

# §6 step time
STEP_WARN_MS: float = 30.0  # log a warning for any step above this
STEP_GUARD_MS: float = 200.0  # a step above this ...
STEP_GUARD_STEPS: int = 16  # ... skips the scout planner, counterattack evaluation and snapshot for this many steps
STARTUP_WARN_MS: float = 5000.0  # §6: keep on_start under 5 s
STEP_SECTION_LOG_MS: float = 2.0  # a slow step's warning lists the parts that took at least this long

# M6 error guard (user decision): an error in one part of a step is logged and the game goes on
# (on the ladder an unhandled error ends the game as a Crash, VERIFY_NOTES "M6 findings")
ERROR_TRACEBACKS_PER_PART: int = 3  # full tracebacks logged per part; later errors there ...
ERROR_LOG_EVERY_S: float = 60.0  # ... get one line per part this often (game seconds) with the count


# ---------------------------------------------------------------------------------------------
# M7: ladder fixes (docs/M7_PLAN.md; DESIGN.md §4.2-§4.5.3, §8)
# ---------------------------------------------------------------------------------------------

# Phase 0 telemetry (§8 M7 metrics)
FIGHT_LOG_TYPES: int = 6  # ENGAGE/DEFEND lines list at most this many unit types per side (highest value first)
LOST_FAR_DISTANCE: float = 12.0  # an army unit that dies farther than this from its intent's point counts as "far"
# §4.2 capital air (M7): the ships, by name in game data. An explicit list: python-sc2 reports a
# Carrier as unable to attack (its interceptors do; VERIFY_NOTES "M7 findings")
CAPITAL_AIR_TYPES: frozenset[UnitTypeId] = frozenset(
    {
        UnitTypeId.TEMPEST, UnitTypeId.CARRIER, UnitTypeId.MOTHERSHIP, UnitTypeId.BATTLECRUISER,
        UnitTypeId.BROODLORD, UnitTypeId.BROODLORDCOCOON,
    }
)
