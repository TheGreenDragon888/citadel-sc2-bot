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
OPENER_ESSENTIALS: Tuple[ScheduleItem, ...] = (
    ScheduleItem(0, "structure", UnitTypeId.GATEWAY, 1, "ramp"),
    ScheduleItem(0, "structure", UnitTypeId.CYBERNETICSCORE, 1, "ramp"),
    ScheduleItem(0, "gas", None, 2),
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

# M1 scaffolding (bot/army/basic_army.py), replaced by squads and EngagementResult gates in M4
ARMY_ATTACK_SUPPLY: int = 150  # §4.5.2 ATTACK_START's supply gate
ARMY_ALWAYS_ATTACK_SUPPLY: int = 190  # §4.5.2 ATTACK_START_MAX's supply gate
ARMY_RETREAT_FRACTION: float = 0.5  # retreat when army supply < this x supply at launch
ARMY_RELAUNCH_WAIT_S: float = 45.0  # §4.5.2: no re-launch for 45 s after a retreat
ARMY_DEFEND_RADIUS: float = 22.0  # enemies this close to a townhall pull the army home
ARMY_RALLY_OFFSET: float = 8.0  # rally this far from the newest base toward the enemy
HUNT_VISIT_RADIUS: float = 7.0  # a structure-hunt point counts as visited this close
HUNT_GRID_STEP: float = 20.0  # spacing of the structure-hunt grid over the playable area
ORDER_REFRESH_S: float = 3.0  # don't re-issue the same order to a unit more often (§6 APM)
ARMY_STATUS_EVERY_S: float = 60.0  # ARMY status log line
ARMY_DIRECT_ATTACK_MARGIN: float = 4.0  # this close beyond weapon range: attack a structure directly
# while attacking, enemies near our bases call the army back only with this share of its supply
ARMY_RECALL_FRACTION: float = 0.3
# while gathering, go out to enemies near our bases only with this share of their supply
# (inside the main or at the hold point the army always fights, next to its Batteries)
ARMY_ENGAGE_RATIO: float = 0.8

# §4.8 ramp wall fallback
WALL_RAMP_MAX_DIST: float = 30.0  # ramp top farther than this from our start: use a choke
WALL_CHOKE_MIN_DIST: float = 8.0  # ignore map-analyzer chokes this close to our start
WALL_BATTERY_MAX_DIST: float = 6.0  # battery within this of the ramp top, on the main side
WALL_HOLD_OFFSET: float = 1.5  # holding unit: ramp top moved this far toward the main
WALL_HOLD_UNTIL_S: float = 360.0  # the holding unit rejoins the army after this (Citadel)
WALL_SPOT_SEARCH_RADIUS: int = 3  # tiles searched around a wanted wall Pylon/Battery spot

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
# Natural scout (§4.3 probe route, M2 part): after ares's scout circles the enemy main, it
# watches the enemy natural from this far toward the map centre until the deadline above
NAT_SCOUT_STANDOFF: float = 7.0
NAT_SCOUT_RETREAT_HP: float = 0.5  # HP+shield fraction: below this the scout goes home

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
EXPANSION_RETRY_S: float = 90.0  # after a Nexus builder dies on its way, no expansion for this long
CANNON_COVER_EXTRA: float = 1.0  # safety margin on a finished Cannon's range
LING_DEFENSE_RADIUS: float = 9.0  # §4.2 "lings in the mineral line": this close to a mineral line
LING_DEFENSE_PROBES_PER_LING: int = 2
LING_DEFENSE_MAX: int = 16
POOL_12_UNITS_BEFORE_EXPAND: int = 3  # §4.2: resume the Nexus at >= 3 units ...
POOL_12_LING_CLEAR_RADIUS: float = 20.0  # ... and no lings within 20
POOL_12_GATE_HOLD_S: float = 10.0  # that condition must hold (or fail) this long to switch
POOL_12_PUSH_SUPPLY: int = 16  # from this army supply the army holds the natural, not the ramp
POOL_12_GATEWAYS: int = 2  # (Citadel; §4.2 names none for 12-pool)
POOL_12_RESERVE_UNITS: int = 1  # the wall-gap Zealot waits for nothing else (Citadel)
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
ARMY_SUPPLY_PER_CANNON: int = 6
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
