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

# Gas buildings after each opener's timed schedule is finished: this many per ready base
GAS_PER_BASE_AFTER_SCHEDULE: int = 2

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
    where: str = "main"  # structures: "main" or "nat"
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

# §4.8 ramp wall fallback
WALL_RAMP_MAX_DIST: float = 30.0  # ramp top farther than this from our start: use a choke
WALL_CHOKE_MIN_DIST: float = 8.0  # ignore map-analyzer chokes this close to our start
WALL_BATTERY_MAX_DIST: float = 6.0  # battery within this of the ramp top, on the main side
WALL_HOLD_OFFSET: float = 1.5  # holding unit: ramp top moved this far toward the main
WALL_HOLD_UNTIL_S: float = 360.0  # the holding unit rejoins the army after this (Citadel)

# Telemetry snapshots (§8 metrics), game seconds
METRIC_TIMES_S: Tuple[int, ...] = (240, 360, 480, 600)
# M1 acceptance: 44 probes by 6:00 (12-worker ruleset)
M1_PROBES_AT_6_MIN: int = 44
