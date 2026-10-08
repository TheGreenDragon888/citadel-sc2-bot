# VERIFY_NOTES: §11 API verification (M0)

What the source says about each item in `docs/DESIGN.md` §11, with the file and line, and
where it contradicts the spec. Versions read:

| Source | Version | Cited as |
|---|---|---|
| ares-sc2 (git submodule) | v3.13.1, commit `87308658` | `ares-sc2/src/ares/...`, `ares-sc2/sc2_helper/...` |
| python-sc2 (burnysc2 from `august-k/python-sc2` develop, installed by Poetry) | 7.1.0 @ `7ec25cf` | `sc2/...`, `s2clientprotocol/...` (venv site-packages) |
| StarCraft II client | Linux 4.10, `Base75689` | runtime results |

Line numbers are for these versions. Four subagents read the source (one per group of items);
the lines behind every "contradicts the spec" entry were then re-read directly. Runtime results
come from `scripts/test_can_win_fight.py` and `scripts/run_matches.py`; each is labelled
**Runtime**. `t` means `self.time` (game seconds, `game_loop / 22.4`, `sc2/bot_ai.py:48`).

## Spec impact summary

Items that change `docs/DESIGN.md`, most important first. Details are in each section.

1. **`can_win_fight` over-rates Protoss wins (§4.5.2).** ares divides the simulator's health
   left (which includes our shields) by our HP *without* shields
   (`ares-sc2/src/ares/managers/combat_sim_manager.py:143`, `:149`). Runtime: 6 Stalkers vs
   nothing return 960 health left against 480 HP, a ratio of 2.0. For Stalkers any win with
   ≥ 45% of HP+shields left reads VICTORY_EMPHATIC, so `ATTACK_START = 8` / `COUNTER_START = 7`
   fire far earlier than intended (§11.3).
2. **Static defence in the simulator (§4.5.2 Day-1 test).** The spec's test as written gives
   VICTORY_EMPHATIC 10 for both 6 Stalkers vs [] and vs [1 Cannon], so by §4.5.2 the penalty
   applies. The extra cases show why: with ares's default `timing_adjust=True`, Cannons never deal
   damage (they only soak shots); with `timing_adjust=False` they are fully armed (6 Cannons beat
   6 Stalkers). Calling with `timing_adjust=False` when static defence is involved is an
   alternative to the penalty. Results also vary by up to one level between identical calls
   (§11.3).
3. **The AIE pool uses the 12-worker, pre-5.0.16 ruleset (§4.0, §4.1, Open Question 1).** All 7
   pool maps start with 12 workers and `supply_cap` 15 on loop 0 (§11.8). The 8-worker builds
   are not needed for this pool.
4. **`BuildSelection: WinrateBased` does nothing (§4.1).** The value is stored and never read;
   selection is always "cycle on loss (or tie) until every build has `MinGamesWinrateBased`
   games, then best winrate over each build's last 10 games" (§11.4).
5. **`f"{race}_{RULESET}"` opener keys are not supported (§4.0).** `BuildChoices` is matched
   only by opponent id (or `test_123` in Debug) and then enemy race name; an unmatched race
   crashes `on_start` (§11.4). Given item 3 this is not urgent for the current pool.
6. **The build runner has supply triggers only (§4.1).** Time triggers such as "~2:50 Robotics
   Facility" cannot be written in YAML (§11.4).
7. **A failed ramp wall crashes ares before Citadel's fallback runs (§4.8).** ares's placement
   solver indexes `protoss_wall_buildings[0]` and `[1]` without a check during `on_start`
   (§11.5). It did not trigger on any of the 7 pool maps (for the spawn each game used).
8. **Warp Gate facts under this map data (§4.1 8-worker note, §4.0).** Research is 50/50 and
   2240 loops, on the Cybernetics Core (not Gateways). Gateways morph to Warp Gates on their own
   when it finishes, and morphing either way is free, repeatedly. python-sc2's
   `game_data.calculate_ability_cost(MORPH_WARPGATE)` wrongly reports 150/0 (§11.7).
9. **ares relies on that auto-morph (§4.1 "otherwise produce from Gateways").** Once Warp Gate is
   researched and a ready idle Gateway exists, ares's `SpawnController` and build runner stop
   Gateway production (§11.7).
10. **ares hard-codes unit costs (§4.0, CLAUDE.md rule).** Under `AresBot`,
    `calculate_cost(UnitTypeId.X)` returns ares's `COST_DICT`, not game data. On PylonAIE_v4 it
    matches game data for all 15 Protoss types checked, so nothing is wrong today (§11.7).
11. **Energy costs: no accessor, measured instead (§4.3).** Hallucination (Phoenix) uses 75 energy
    and Revelation 25; `get_available_abilities` already hides Hallucination below 75 energy
    (§11.7).
12. **Several ares intel flags differ from §4.2's assumptions:** "greedy" is never computed
    (always False), there is no standalone "marine" flag, several flags reset after a time
    window, and the "went" latches only update when their lazy property is read (§11.1).
13. **Remembered units are two different things (§4.5.2, §4.6).** Unit memory expires ghosts
    after 30 s and never holds structures; the army cache (`get_enemy_army_dict`) never expires
    until death (§11.1, §11.2).
14. **Ruleset probe placement (§4.0 "on loop 0").** It must run in `on_start` before
    `super().on_start()` (or in `on_before_start`) for opener selection to use it (§11.8).

## §11.1 IntelManager flags

**Found**
- Always on; no config key. The hub always builds it and updates it every step.
  `ares-sc2/src/ares/managers/hub.py:124` `else IntelManager(ai, config, self.manager_mediator)`;
  `ares-sc2/src/ares/managers/hub.py:201`.
- Flags are mediator **properties** (no call parentheses), routed by manager name:
  `ares-sc2/src/ares/managers/manager_mediator.py:100`,
  `ares-sc2/src/ares/managers/intel_manager.py:142`.
- In arcade mode (no enemy start location or no townhalls) every request returns `None`:
  `ares-sc2/src/ares/managers/intel_manager.py:136`, `ares-sc2/src/ares/main.py:351`.
- Two evaluation styles:
  - **Every step** (`update()`): ling rush, roach rush, worker rush, reaper. These latch True and
    never reset. `ares-sc2/src/ares/managers/intel_manager.py:400-407`.
  - **On read** (`@property_cache_once_per_frame`): expanded, base-outside-natural, marauder,
    four-gate, marine, ravager, did-rush. Computed only when something reads them.
    `get_is_proxy_zealot` is a plain property (`intel_manager.py:367`).
    `ares-sc2/src/ares/cache.py:32`.
- The three `get_enemy_went_*` latches (four-gate, marine, marauder) are set only as a side effect
  of reading the matching property (`ares-sc2/src/ares/managers/intel_manager.py:297`). Nothing
  in ares reads intel flags itself.
- Unit counts come from `get_enemy_army_dict` (UnitCacheManager): every enemy tag ever seen,
  removed only on death, stored as its **first-sighting** `Unit`, so distance tests use the first
  seen position. `ares-sc2/src/ares/managers/unit_cache_manager.py:304-306`.
- Race gating: Zerg (ling, roach, ravager), Terran (marine, marauder, reaper), Protoss
  (four-gate, proxy zealot), any (worker rush, expansion flags). Against Random, `enemy_race`
  only updates once an enemy unit is seen: `sc2/bot_ai_internal.py:734`.

| mediator property | trigger (as coded) | window | resets? | source |
|---|---|---|---|---|
| `get_enemy_worker_rushed` | > 6 enemy workers (incl. remembered) within 15 of our start or 16 of our natural | t < 180 | never | `ares-sc2/src/ares/managers/intel_manager.py:463-477` |
| `get_enemy_ling_rushed` | > 2 lings within 50 of our start (t<150), or > 7 lings seen (t<180), or > 4 (t<90) | t < 180 | never | `ares-sc2/src/ares/managers/intel_manager.py:410-435` |
| `get_enemy_roach_rushed` | ≥ 6 roaches within 50 of our start (t<240), or ≥ 3 seen (t<180) | t < 240 | never | `ares-sc2/src/ares/managers/intel_manager.py:437-461` |
| `get_enemy_went_reaper` | ≥ 1 reaper ever seen | any | never | `ares-sc2/src/ares/managers/intel_manager.py:402-407` |
| `get_enemy_ravager_rush` | ≥ 1 ravager seen | t < 240 | yes (False after) | `ares-sc2/src/ares/managers/intel_manager.py:300-314` |
| `get_enemy_marine_rush` | ≥ 3 barracks (t<180), or marines ≥ max(3, int(t)//45) > 60 from the enemy start (t<300); False if t > 210, any factory, or ≥ 2 townhalls | t ≤ 210 | yes | `ares-sc2/src/ares/managers/intel_manager.py:254-298` |
| `get_enemy_went_marine_rush` | latch of the above, set only when it is read True | — | never | `ares-sc2/src/ares/managers/intel_manager.py:294-297` |
| `get_enemy_marauder_rush` | barracks tech lab within 55 of our natural, or ≥ 2 marauders (t<210), or ≥ 1 (t<160) | t ≤ 240 | yes | `ares-sc2/src/ares/managers/intel_manager.py:195-223` |
| `get_enemy_went_marauder_rush` | latch, set on read | — | never | `ares-sc2/src/ares/managers/intel_manager.py:218-220` |
| `get_enemy_four_gate` | ≥ 3 GATEWAY (warp gates not counted) and < 2 townhalls; False if t > 210 | t < 200 | yes | `ares-sc2/src/ares/managers/intel_manager.py:226-251` |
| `get_enemy_went_four_gate` | latch, set on read | — | never | `ares-sc2/src/ares/managers/intel_manager.py:247-250` |
| `get_is_proxy_zealot` | ≥ 2 gateways within 100 of our start and > 60 from theirs, or a zealot within 65 of our start (t<150) | t ≤ 240 | yes | `ares-sc2/src/ares/managers/intel_manager.py:367-394` |
| `get_enemy_expanded` | an enemy townhall > 6 from `enemy_start_locations[0]` | any | yes (if it disappears) | `ares-sc2/src/ares/managers/intel_manager.py:144-165` |
| `get_enemy_has_base_outside_natural` | as above and > 6 from the enemy natural | any | yes | `ares-sc2/src/ares/managers/intel_manager.py:167-192` |
| `get_did_enemy_rush` | OR of the rush flags plus: ≥ 3 roaches (t<240), ≥ 1 ling (t<105), ≥ 2 barracks (t<120) | per term | never | `ares-sc2/src/ares/managers/intel_manager.py:316-365` |
| `get_enemy_was_greedy` | never assigned after `False` | — | always False | `ares-sc2/src/ares/managers/intel_manager.py:101`, `ares-sc2/src/ares/managers/manager_mediator.py:782` |

`bot/constants.py` `ARES_INTEL` holds this table as data (accessor, races, evidence basis,
trigger, window, resets, evaluation style).

**Contradicts the spec**
- §4.2/§4.4 "greedy" flag: exists but is never computed (always False). Macro detection (§4.4
  row 14) needs a Citadel detector.
- §4.2 lists a "marine" flag separately from "marine-rush": there is only `get_enemy_marine_rush`
  and its latch.
- §5/§9.13 "ares flags may never reset": true for ling, roach, worker, reaper, did-rush and the
  latches; **false** for four-gate, marine, marauder, ravager, proxy-zealot (drop to False after
  their window) and the expansion flags.
- §4.4 row 11 (≥ 3 Gateways, no Nexus by 3:00): ares uses t < 200, counts Gateways only (not Warp
  Gates) and switches off at 210 s.
- §4.2 proxy Barracks via "marine-rush and reaper flags (unit-based)": marine rush also has a
  structure term (≥ 3 barracks) and turns off on any Factory; the reaper flag fires on any reaper
  at any time.
- §4.2 proxy Zealot: partly structure-based and not latched.
- §4.4 row 14 (natural on time + 3rd by 4:30): `get_enemy_expanded` has no timing and nothing
  checks for a third base.
- §3 step 2 (`ares_bridge.update()` copies the booleans): the bridge must read the lazy
  properties (`get_enemy_marine_rush`, `get_enemy_four_gate`, `get_enemy_marauder_rush`) itself;
  reading only the latches or `get_did_enemy_rush` misses the marine latch
  (`ares-sc2/src/ares/managers/intel_manager.py:339`).

**Not verified**
- Whether a roach keeps its tag when it morphs to a ravager (ares only comments on
  zergling → baneling, `ares-sc2/src/ares/managers/unit_cache_manager.py:313`).

## §11.2 UnitMemoryManager

**Found**
- Structures are **not** remembered; only enemy non-structures are stored.
  `ares-sc2/src/ares/managers/unit_memory_manager.py:36`, `ares-sc2/src/ares/main.py:632`.
  Fogged enemy structures are only the game's own snapshots (`sc2/unit.py:483`).
- Up to 10 snapshots per tag (`ares-sc2/src/ares/consts.py:145`); hallucinations are skipped
  (`ares-sc2/src/ares/managers/unit_memory_manager.py:267`).
- A ghost expires when **any** of these happens (checked every step for tags not visible):
  - its last snapshot is older than **30 game seconds** (air and ground, hard-coded):
    `ares-sc2/src/ares/managers/unit_memory_manager.py:91-92`, `:375-377`;
  - all grid cells at and around its last position are visible (burrowed units are kept unless a
    detector covers the spot): `ares-sc2/src/ares/managers/unit_memory_manager.py:198`, `:214`;
  - it dies (`on_unit_destroyed`): `ares-sc2/src/ares/managers/unit_memory_manager.py:358`.
- After `super().on_step()`, ghosts are merged into `self.enemy_units` and `self.all_enemy_units`
  (not `self.enemy_structures`) and carry `is_memory == True`:
  `ares-sc2/src/ares/managers/unit_memory_manager.py:224`.
- Memory-backed mediator accessors: `get_all_enemy`, `get_enemy_ground`, `get_enemy_fliers`
  (properties returning `Units`), `get_enemy_tree`, `get_own_tree`, and the keyword-only methods
  `get_units_in_range(start_points=, distances=, query_tree=, return_as_dict=False)`,
  `get_any_enemies_in_range(positions=, radius=)`, `get_is_detected(unit=, by_enemy=True)`.
  `ares-sc2/src/ares/managers/manager_mediator.py:2409`, `:2441`, `:2454`, `:2479`.
- There is no mediator accessor for ghosts alone; `self.manager_hub.unit_memory_manager.ghost_units`
  (`ares-sc2/src/ares/managers/unit_memory_manager.py:321`).
- `get_cached_enemy_army` / `get_enemy_army_dict` belong to UnitCacheManager, not memory: every
  enemy army tag ever seen, kept until it dies, **no timer**.
  `ares-sc2/src/ares/managers/manager_mediator.py:2267`, `:2293`;
  `ares-sc2/src/ares/managers/unit_cache_manager.py:349`.
- `get_units_in_range` queries KD-trees rebuilt each step from all enemies **including ghosts and
  structures**; ground/air split by `is_flying`.
  `ares-sc2/src/ares/managers/unit_memory_manager.py:405`, `:461`.
- No config key controls memory (`expire_air`/`expire_ground` are plain attributes).
- `on_enemy_unit_left_vision` fires for every ghost tag every step (the "previous" map already
  includes ghosts): `sc2/bot_ai_internal.py:698`.

**Contradicts the spec**
- §11.2 guessed `get_enemy_army_dict` as the memory accessor: it is the never-expiring army cache.
- §4.6 "≥ 60% of the remembered army seen within the last 15 s": ghosts only live 30 s and the
  army cache never expires, so "seen within 15 s" must be computed from `unit.age` / `is_memory`.
- §4.5.2 "remembered enemy army units within 20": the enemy KD-trees include structures and
  workers, so results need filtering.

**Not verified**
- Engine behaviour for undetected cloaked units and for snapshot structures destroyed in fog.

## §11.3 `mediator.can_win_fight`

**Found**
- Mediator method is keyword-only and forwards to CombatSimManager:
  `ares-sc2/src/ares/managers/manager_mediator.py:235`, `:253`.
- Signature: `can_win_fight(own_units: Units, enemy_units: Units, timing_adjust: bool = True,
  good_positioning: bool = False, workers_do_no_damage: bool = False) -> EngagementResult`.
  `ares-sc2/src/ares/managers/combat_sim_manager.py:100-107`. The spec's parameter names are right.
- Units are passed through unfiltered: no structure, worker, power or build-progress filtering in
  Python. `ares-sc2/src/ares/managers/combat_sim_manager.py:136-137`.
- No caching; every call runs a full simulation. The manager is always constructed
  (`ares-sc2/src/ares/managers/hub.py:167`).
- The simulator core is compiled Rust (`ares-sc2/sc2_helper/combat_simulator.py:3`); no Rust source
  is in the repo. The module warns it has bugs and suggests using it only "when all units involved
  can attack each other" (`ares-sc2/src/ares/managers/combat_sim_manager.py:4-5`).
- `predict_engage` returns (own side won, **winner's** health left):
  `ares-sc2/sc2_helper/combat_simulator.py:114-118`, `:144`.
- **Health asymmetry.** Our health is HP only; the enemy's is HP + shields
  (`ares-sc2/src/ares/managers/combat_sim_manager.py:143-144`; python-sc2 `health` excludes shields,
  `sc2/unit.py:407`). On a win the level is `health_left / own_health` (`:149`); on a loss,
  `health_left / enemy_health` (`:161`).

| EngagementResult | value | condition | source |
|---|---|---|---|
| VICTORY_EMPHATIC | 10 | won, ratio ≥ 0.9 | `ares-sc2/src/ares/consts.py:266`, `ares-sc2/src/ares/managers/combat_sim_manager.py:150-151` |
| VICTORY_OVERWHELMING | 9 | won, ≥ 0.75 | `ares-sc2/src/ares/managers/combat_sim_manager.py:152-153` |
| VICTORY_DECISIVE | 8 | won, ≥ 0.6 | `ares-sc2/src/ares/managers/combat_sim_manager.py:154-155` |
| VICTORY_CLOSE | 7 | won, > 0.4 | `ares-sc2/src/ares/managers/combat_sim_manager.py:156-157` |
| VICTORY_MARGINAL | 6 | won, > 0.2 | `ares-sc2/src/ares/managers/combat_sim_manager.py:158-159` |
| TIE | 5 | fall-through: won **or lost** with ratio ≤ 0.2 | `ares-sc2/src/ares/managers/combat_sim_manager.py:172-173` |
| LOSS_MARGINAL | 4 | lost, > 0.2 | `ares-sc2/src/ares/managers/combat_sim_manager.py:170-171` |
| LOSS_CLOSE | 3 | lost, > 0.4 | `ares-sc2/src/ares/managers/combat_sim_manager.py:168-169` |
| LOSS_DECISIVE | 2 | lost, > 0.6 | `ares-sc2/src/ares/managers/combat_sim_manager.py:166-167` |
| LOSS_OVERWHELMING | 1 | lost, ≥ 0.75 | `ares-sc2/src/ares/managers/combat_sim_manager.py:164-165` |
| LOSS_EMPHATIC | 0 | lost, ≥ 0.9 | `ares-sc2/src/ares/managers/combat_sim_manager.py:162-163` |

`EngagementResult` is an `int` enum (`ares-sc2/src/ares/consts.py:263`), so it compares directly
with ints.

- Probe of the compiled module with mock units (subagent, no game; not source):
  it reads type, weapons, dps/range, armor, speed, HP/shields/energy (current and max), radius,
  flying and upgrade levels; it does **not** read `position`, `is_structure`, `is_powered`,
  `build_progress` or buffs. Static stats are cached per unit type for the whole process. Empty
  unit lists are accepted. About 0.07 ms per call for 10 v 15 units.

**Runtime** (`poetry run python scripts/test_can_win_fight.py`, PylonAIE_v4). 6 own Stalkers
against an enemy group 11.8 away (Stalkers) and 10.8 away (nearest Cannon); every unit at full
HP+shields; all 6 Cannons ready and powered. Each cell is the most common of 20 calls, with the
range when calls differed.

| scenario | default args (`timing_adjust=True`) | raw `predict_engage` (won, health left) | `timing_adjust=False` |
|---|---|---|---|
| 6 Stalkers vs nothing **[spec]** | VICTORY_EMPHATIC 10 | True, 960.0 | VICTORY_EMPHATIC 10 |
| 6 Stalkers vs 1 Cannon **[spec]** | VICTORY_EMPHATIC 10 | True, 960.0 | VICTORY_EMPHATIC 10 |
| 6 Stalkers vs 3 Cannons | VICTORY_EMPHATIC 10 | True, 960.0 | VICTORY_DECISIVE 8 |
| 6 Stalkers vs 6 Cannons | VICTORY_EMPHATIC 10 | True, 960.0 | LOSS_OVERWHELMING 1 |
| 6 Stalkers vs 6 Stalkers | TIE 5 | False, 189.0 | TIE 5 |
| 6 Stalkers vs 6 Stalkers + 1 Cannon | LOSS_CLOSE 3 | False, 546.1 | LOSS_DECISIVE 2 |
| 6 Stalkers vs 6 Stalkers + 2 Cannons | LOSS_CLOSE 3 (2–3) | False, 1044.8 | LOSS_OVERWHELMING 1 |
| 6 Stalkers vs 6 Stalkers + 4 Cannons | LOSS_DECISIVE 2 (1–2) | False, 1569.0 | LOSS_OVERWHELMING 1 |

- **The spec's test as written:** [] and [1 Cannon] both give VICTORY_EMPHATIC 10: "the result
  doesn't change", so §4.5.2's penalty applies.
- **Why:** with ares's default `timing_adjust=True`, Cannons deal no damage (6 Stalkers kill 6
  Cannons and keep all 960 HP+shields) but still count as targets: next to enemy Stalkers each
  Cannon soaks shots and lowers the result. With `timing_adjust=False` Cannons are fully armed.
  So the simulator does model structures, and the default timing adjustment is what disarms them
  (inferred from these results; the Rust source is not available to confirm the mechanism).
- **Shield inflation confirmed:** vs nothing, health left is 960 = HP 480 + shields 480, and ares
  divides by 480 (ratio 2.0).
- **Not deterministic:** identical calls differ by up to one level (rows with a range), and single
  raw calls for "+1 Cannon" returned 734.5, 602.6 and 546.1 across three runs of the script.

**Contradicts the spec**
- §4.5.2: member names and values are exactly as assumed (8 = VICTORY_DECISIVE, 5 = TIE).
- §4.5.2 `ATTACK_CONTINUE = 5`: TIE is also returned for narrow predicted **losses**, so "keep
  attacking while ≥ 5" continues through predicted narrow losses.
- §4.5.2 gates (`ATTACK_START = 8`, `COUNTER_START = 7`): with our shields left out of the
  denominator, Protoss victory levels are inflated (see Runtime). The gates need a correction, for
  example Citadel computing the level itself from `predict_engage` with HP + shields.
- §4.5.2 static defence: the Day-1 test's outcome is "apply the penalty", but the cause is the
  default `timing_adjust=True`, not missing structure support. `timing_adjust=False` models Cannons
  directly (and loses the distance adjustment for mobile units).
- §4.5.2 flip rules (`MIN_STATE_SECONDS`, 3-level hysteresis): single calls can move one level on
  identical input, which the hysteresis already absorbs; one-level thresholds such as
  `ATTACK_CONTINUE = 5` vs `RETREAT_AT = 4` will see that noise.
- §4.5.2 "Shield Batteries as support": any unit passed in is simulated as a combatant or target;
  nothing models battery healing as support.
- §4.5.2 "enemy static defense": unpowered or unfinished structures are not filtered and would
  count at full strength; Citadel must filter them.
- `timing_adjust` cannot use real distances: positions are never passed to the core.

**Not verified**
- Splash (docstring says TODO, `ares-sc2/sc2_helper/combat_simulator.py:34`) and battery healing.

## §11.4 Build runner YAML, WinrateBased, data storage, `@` targets, `set_build_completed`

**Found**
- File: `<race>_builds.yml` → `protoss_builds.yml` in the working directory, loaded in
  `on_before_start` and shallow-merged into `self.config` (its `UseData` overrides config.yml).
  `ares-sc2/src/ares/main.py:307`, `:312`.
- The opener is chosen when DataManager is constructed in `on_start`:
  `ares-sc2/src/ares/managers/data_manager.py:95`, `ares-sc2/src/ares/main.py:357`.
- Top-level keys read: `UseData`, `BuildSelection` (stored only), `MinGamesWinrateBased` (default 3,
  `ares-sc2/src/ares/managers/data_manager.py:145`), `BuildChoices: {<key>: {Cycle: [...]}}`
  (only `Cycle` is read; `BotName` is never read), `Builds`. A chosen name missing from `Builds`
  asserts (`ares-sc2/src/ares/build_runner/build_order_runner.py:129`).
- Per-build keys: `OpeningBuildOrder` (required), `AutoSupplyAtSupply` (default 200),
  `ConstantWorkerProductionTill` (default 0), `PersistentWorker` (True), `ShouldHandleGasSteal`
  (True). `ares-sc2/src/ares/build_runner/build_order_runner.py:134-159`, `:260-263`.
- `BuildChoices` lookup: key `test_123` if `Debug: True`, else `opponent_id`; then
  `enemy_race.name` (`Terran`, `Zerg`, `Protoss`, `Random`).
  `ares-sc2/src/ares/managers/data_manager.py:279-289`. `opponent_id` is None locally
  (`sc2/bot_ai_internal.py:85`) and set by `ladder.py:42` on the ladder. Against Random the
  `Random` key is used (race unknown at `on_start`). If nothing matches, `build_cycle[0]` raises
  IndexError in `on_start` and python-sc2 resigns (`ares-sc2/src/ares/managers/data_manager.py:153`).
- Selection (when `UseData: True`): cycle rule until every build in the cycle has
  `MinGamesWinrateBased` games (`ares-sc2/src/ares/managers/data_manager.py:211`), then highest
  winrate over each build's last 10 games (`:224`, `:242`), ties rotate (`:263`). Cycle rule:
  repeat after a win, advance after a loss **or tie** (`:183`, `:187`). With no data file the
  history starts with a phantom win for `build_cycle[0]` (`:305`).
- Data file: `./data/<opponent_id>-protoss.json` (`None-protoss.json` locally), a JSON list of
  `{EnemyRace, Duration, StrategyUsed, Result}` (2 win, 0 loss, 1 other), written once in `on_end`
  and only if `UseData` is True. `ares-sc2/src/ares/managers/data_manager.py:100`, `:329-336`;
  `ares-sc2/src/ares/main.py:493`. This is the only file ares writes.
- Step syntax: `"<supply> <command> [@] [target] [xN]"`; supply triggers only
  (`ares-sc2/src/ares/build_runner/build_order_parser.py:600`, `:609`). Commands resolve as a
  `UnitTypeId` name, then an `UpgradeId` name (e.g. `warpgateresearch`), then a
  `BuildOrderOptions` value: ADDONSWAP, CANCEL_GAS, CHRONO, CORE, GATE, GAS, EXPAND, ORBITAL,
  OVERLORD_SCOUT, SUPPLY, WORKER, WORKER_SCOUT (`ares-sc2/src/ares/consts.py:205`).
- `@` targets (`@` itself is optional): ENEMY_NAT, ENEMY_NAT_HG_SPOT, ENEMY_NAT_VISION, ENEMY_RAMP,
  ENEMY_SPAWN, ENEMY_THIRD, ENEMY_FOURTH, THIRD..SIXTH, MAP_CENTER, NAT, NAT_WALL, RAMP,
  REAPER_WALL, SPAWN (`ares-sc2/src/ares/consts.py:224`;
  resolution `ares-sc2/src/ares/build_runner/build_order_runner.py:742`). `expand` and `gas`
  ignore targets (`:606`, `:582`). `chrono` needs a unit-type target such as `@ nexus`
  (`ares-sc2/src/ares/build_runner/build_order_parser.py:482`). Structures `@ ramp` request
  ares's wall placement.
- Scout step: `- 14 worker_scout` circles the enemy main; the dict form
  `- 14 worker_scout: [enemy_spawn, enemy_nat]` sets waypoints
  (`ares-sc2/src/ares/build_runner/build_order_parser.py:440`). `UnitRole.BUILD_RUNNER_SCOUT`
  exists (`ares-sc2/src/ares/consts.py:559`); idle scouts return to GATHERING before 390 s
  (`ares-sc2/src/ares/main.py:430`).
- `set_build_completed(self) -> None` on `self.build_order_runner`: logs, returns
  PERSISTENT_BUILDER workers to GATHERING, sets the completed flag
  (`ares-sc2/src/ares/build_runner/build_order_runner.py:114-119`). Runtime switch:
  `switch_opening(opening_name, remove_completed=True)` (`:189`).

**Contradicts the spec**
- §4.1 `BuildSelection: WinrateBased`: never read (`ares-sc2/src/ares/managers/data_manager.py:102`,
  `:143` write it; nothing reads it). Selection is the rule above either way. "Cycle through them
  on defeat" also advances on ties, and the first build starts with a phantom win.
- §4.0 `f"{race}_{RULESET}"` key groups: not matched. Options that work in source: rewrite
  `self.config["BuildChoices"]` after `await super().on_before_start()`, a custom `DataManager`
  via `register_managers`, or `switch_opening` at runtime (which leaves winrate data recorded
  under the originally chosen build, `ares-sc2/src/ares/managers/data_manager.py:328`). **Needs a
  decision before M1.**
- §4.1 time-based steps ("~2:50 Robotics Facility", "Nexus at 3:10"): the runner has supply
  triggers only; time steps must be Citadel code after the opener.
- §3 step 3 override via `set_build_completed()`: works, but also stops the runner's worker
  production and AutoSupply at once; GAS_STEAL_PREVENTER probes keep that role.
- §5 "where the build runner stores winrates": `./data/<OpponentId>-protoss.json`; no clash with
  Citadel's planned `./data/opponents/`.

**Not verified**
- The IndexError crash paths are read from code, not reproduced.

## §11.5 `BuildStructure`, `find_path_next_point`, `get_units_in_range`, `KeepUnitSafe`, `PathUnitToTarget`, `SpeedMining`

**Found**
- Behaviors implement `execute(ai, config, mediator) -> bool` and are registered with
  `self.register_behavior(...)` (`ares-sc2/src/ares/behaviors/behavior.py:14`); mediator methods
  are keyword-only.

| API | import | signature | source |
|---|---|---|---|
| `BuildStructure` | `ares.behaviors.macro` | `(base_location, structure_id, max_on_route=1, first_pylon=False, static_defence=False, wall=False, closest_to=None, to_count=0, to_count_per_base=0, tech_progress_check=0.85, supply_depot=False, missile_turret=False, sensor_tower=False, upgrade_structure=False, production=True, bunker=False, reaper_wall=False, find_alternative=True)` | `ares-sc2/src/ares/behaviors/macro/build_structure.py:24-98` |
| `mediator.request_building_placement` | mediator | `(base_location, structure_type, first_pylon=False, static_defence=False, wall=False, find_alternative=True, reserve_placement=True, within_psionic_matrix=False, pylon_build_progress=1.0, closest_to=None, supply_depot=False, production=False, upgrade_structure=False, missile_turret=False, sensor_tower=False, bunker=False, reaper_wall=False) -> Point2 \| None` | `ares-sc2/src/ares/managers/placement_manager.py:305-324` |
| `mediator.find_path_next_point` | mediator | `(start, target, grid, sensitivity=5, smoothing=False, sense_danger=True, danger_distance=20.0, danger_threshold=5.0) -> Point2` | `ares-sc2/src/ares/managers/path_manager.py:251-261` |
| `mediator.get_units_in_range` | mediator; `ares.consts.UnitTreeQueryType` (`AllOwn`, `AllEnemy`, `EnemyFlying`, `EnemyGround`) | `(start_points, distances, query_tree, return_as_dict=False) -> list[Units] \| dict` | `ares-sc2/src/ares/managers/unit_memory_manager.py:419-425`, `ares-sc2/src/ares/consts.py:562` |
| `KeepUnitSafe` | `ares.behaviors.combat.individual` | `(unit, grid)` | `ares-sc2/src/ares/behaviors/combat/individual/keep_unit_safe.py:22-41` |
| `PathUnitToTarget` | `ares.behaviors.combat.individual` | `(unit, grid, target, success_at_distance=0.0, sensitivity=5, smoothing=False, sense_danger=True, danger_distance=20.0, danger_threshold=5.0)` | `ares-sc2/src/ares/behaviors/combat/individual/path_unit_to_target.py:21-59` |
| `SpeedMining` | `ares.behaviors.macro` | `(worker, target, worker_position, resource_target_pos, distance_to_townhall_factor=1.08, townhall=None)` — per-worker helper | `ares-sc2/src/ares/behaviors/macro/speed_mining.py:24-56` |
| `Mining` (the behavior to register) | `ares.behaviors.macro` | `(flee_at_health_perc=0.5, keep_safe=True, long_distance_mine=True, mineral_boost=True, vespene_boost=False, workers_per_gas=3, self_defence_active=True, safe_long_distance_mineral_fields=None, locked_action_tags={}, weight_safety_limit=12.0)` | `ares-sc2/src/ares/behaviors/macro/mining.py:41-86` |

- `BuildStructure` for Protoss non-Pylons forces `within_psionic_matrix=True` and needs a finished
  Pylon (`ares-sc2/src/ares/behaviors/macro/build_structure.py:134`). `production` defaults to
  True although its docstring says False (`:95`).
- Main-ramp wall: ares's Protoss placement solver adds wall spots from python-sc2's
  `protoss_wall_pylon` / `protoss_wall_buildings`; request them with
  `BuildStructure(self.start_location, UnitTypeId.PYLON, wall=True)` (and Gateway/Core), which is
  what `@ ramp` does. `ares-sc2/src/ares/managers/placement_manager.py:1296`.
- ares ships natural-wall placements for the seven pool maps (2025 patch 5.0.14 data):
  `ares-sc2/src/ares/protoss_building_placements.yml:1`.
- `KeepUnitSafe` does nothing if the unit's tile weight ≤ 1.0, else paths to
  `find_closest_safe_spot` (radius 11):
  `ares-sc2/src/ares/behaviors/combat/individual/keep_unit_safe.py:45`.
- `find_path_next_point` returns `target` without pathing when `sense_danger` finds no tile
  ≥ `danger_threshold` within `danger_distance` (`ares-sc2/src/ares/managers/path_manager.py:328`).

**Contradicts the spec**
- §7 "ares's `SpeedMining`": the name exists but is a per-worker helper; register `Mining()`,
  which speed-mines by default.
- §4.8 wall fallback: on a map where `protoss_wall_buildings` is empty, ares raises IndexError at
  `ares-sc2/src/ares/managers/placement_manager.py:1306` during `on_start` (placement manager
  initialise, `ares-sc2/src/ares/managers/hub.py:228`), before Citadel's `wall_ok` check can run;
  python-sc2's wall properties can also raise themselves (`sc2/game_info.py:172`), not only
  return None/empty as §4.8 assumes. With exactly one building it raises at `:1309` instead.

**Runtime:** not triggered on the current pool. In the 7-map run (§11.8) ares solved placements on
every map (`Solved placement formation` logged 7 times) and reads wall slots `[0]` and `[1]`
(`ares-sc2/src/ares/managers/placement_manager.py:1306-1309`), so each map returned at least two
wall buildings for the spawn used. A future map with a non-standard main ramp would still crash in
`on_start`.

## §11.6 Grid accessors

**Found**
- All grid accessors are mediator **properties** returning the **live** array (copy before
  editing): `ares-sc2/src/ares/managers/manager_mediator.py:1358-1359`,
  `ares-sc2/src/ares/managers/grid_manager.py:136`.
- Base grids: ground = pathable 1 / inf (`ares-sc2/src/ares/managers/grid_manager.py:169`); air =
  1 inside the playable area (`:163`). Grids are reset at the end of every step
  (`ares-sc2/src/ares/main.py:449`); influence is added during unit preparation and
  `GridManager.update` inside `super().on_step()` (`ares-sc2/src/ares/main.py:415`, `:623`).
- Only **visible** enemies add influence, not ghosts (`ares-sc2/src/ares/managers/grid_manager.py:221`).
- Structures with influence: powered Photon Cannon, Missile Turret, Spore Crawler, Bunker,
  Planetary Fortress, Auto-Turret (`ares-sc2/src/ares/managers/grid_manager.py:596`, `:613`).
  **Spine Crawlers and Shield Batteries add none.**

| mediator property | influence | config flag | source |
|---|---|---|---|
| `get_ground_grid` | enemy ground attackers, WEIGHT_COSTS units, phased Disruptor, powered Cannon/Bunker/PF/Auto-Turret, ground effects | no | `ares-sc2/src/ares/managers/manager_mediator.py:1502` |
| `get_climber_grid` | as ground, on a Reaper/Colossus cliff base | no | `ares-sc2/src/ares/managers/manager_mediator.py:1437` |
| `get_air_grid` | enemy anti-air, Cannon/Turret/Spore/Bunker/Auto-Turret, air effects | no | `ares-sc2/src/ares/managers/manager_mediator.py:1359` |
| `get_air_vs_ground_grid` | as air; base 10 on ground-pathable tiles | no | `ares-sc2/src/ares/managers/manager_mediator.py:1384` |
| `get_ground_to_air_grid` | non-flying anti-air only | no | `ares-sc2/src/ares/managers/manager_mediator.py:1519` |
| `get_ground_avoidance_grid` | Blinding Cloud, Lurker spines, Storm, Disruptor, Biles, Nukes, Auto-Turret | no | `ares-sc2/src/ares/managers/manager_mediator.py:1485` |
| `get_air_avoidance_grid` | Storm, Parasitic Bomb, Biles, Nukes, Auto-Turret | no | `ares-sc2/src/ares/managers/manager_mediator.py:1335` |
| `get_priority_ground_avoidance_grid` | Storm, Disruptor, Biles, Nukes | no | `ares-sc2/src/ares/managers/manager_mediator.py:1553` |
| `get_tactical_ground_grid` | army-value tactical grid | **yes**: `Features: TacticalGroundGrid: True` (off in both configs) | `ares-sc2/src/ares/managers/manager_mediator.py:1567`, `ares-sc2/src/ares/managers/grid_manager.py:190-191` |
| `get_cached_ground_grid` | none (clean pathing, refreshed every 8 iterations) | no | `ares-sc2/src/ares/managers/manager_mediator.py:1415` |

**Contradicts the spec**
- §4.3: `mediator.get_air_grid` is right; the ground one is `mediator.get_ground_grid`. Both are
  properties (no parentheses).
- `find_path_next_point` must be called with keywords; `sense_danger` defaults to **True** in code
  (`ares-sc2/src/ares/managers/path_manager.py:258`) though its docstring says False (`:278`).
- §4.3 scouts: the ground grid carries no influence from Spine Crawlers, Shield Batteries or
  out-of-sight enemies.

## §11.7 Warp Gate, Hallucination and Revelation ability IDs and costs

**Found**

| thing | enum member | id | source |
|---|---|---|---|
| Warp Gate research | `AbilityId.RESEARCH_WARPGATE` | 1568 | `sc2/ids/ability_id.py:454` |
| Warp Gate upgrade | `UpgradeId.WARPGATERESEARCH` | 84 | `sc2/ids/upgrade_id.py:94` |
| Gateway → Warp Gate | `AbilityId.MORPH_WARPGATE` | 1518 | `sc2/ids/ability_id.py:432` |
| Warp Gate → Gateway | `AbilityId.MORPH_GATEWAY` | 1520 | `sc2/ids/ability_id.py:434` |
| Hallucination (Phoenix) | `AbilityId.HALLUCINATION_PHOENIX` | 154 | `sc2/ids/ability_id.py:57` |
| Oracle Revelation | `AbilityId.ORACLEREVELATION_ORACLEREVELATION` | 2146 | `sc2/ids/ability_id.py:650` |

- IDs are generated for game version 4.11.4.78285 (`sc2/ids/id_version.py:1`); unknown ability ids
  silently become `NULL_NULL` (`sc2/ids/ability_id.py:1396-1397`).
- Static tables put Warp Gate research on the **Cybernetics Core**
  (`sc2/dicts/unit_abilities.py:254`, `sc2/dicts/upgrade_researched_from.py:82`) and the morph on
  the Gateway (`sc2/dicts/unit_abilities.py:419`).
- Costs from game data: `calculate_cost(UpgradeId | AbilityId)` reads game data
  (`sc2/bot_ai.py:500`, `:503`); `Cost` has minerals, vespene and time only, no energy
  (`sc2/game_data.py:331-333`). Hallucination and Revelation return 0/0
  (`sc2/game_data.py:75`). The morph cost is Warp Gate cost minus Gateway cost from game data
  (`sc2/game_data.py:284-286`).
- **Under `AresBot`, `calculate_cost(UnitTypeId.X)` returns ares's hard-coded `COST_DICT`**
  (`ares-sc2/src/ares/main.py:161-167`; e.g. `ares-sc2/src/ares/dicts/cost_dict.py:114`
  `UnitTypeId.WARPGATE: Cost(150, 0)`). Upgrade and ability ids still reach game data.
- **No energy-cost accessor** exists in python-sc2, ares or cython_extensions; the `AbilityData`
  proto has no energy field (`s2clientprotocol/data_pb2.pyi:106-134`).
- Availability: `await self.get_available_abilities(units, ignore_resource_requirements=False)`
  (`sc2/bot_ai.py:203-205`); `Unit.abilities` is filled each step (`sc2/unit.py:598`).
- ares assumes Gateways auto-morph: once Warp Gate is researched and a ready idle Gateway exists,
  `SpawnController.execute` returns False for the whole call
  (`ares-sc2/src/ares/behaviors/macro/spawn_controller.py:84-89`) and the build runner skips
  Gateway-unit steps (`ares-sc2/src/ares/build_runner/build_order_runner.py:279-286`). Nothing in
  ares or python-sc2 issues `MORPH_WARPGATE`.

**Runtime** (`poetry run python scripts/test_can_win_fight.py` phase 2, PylonAIE_v4 game data;
worker income stopped so every resource delta is exactly what the game charged):

| check | result |
|---|---|
| Warp Gate research in game data | 50/50, 2240 loops (100 s) |
| charged for Warp Gate research | 50/50 |
| `RESEARCH_WARPGATE` available | Cybernetics Core: yes; Gateway: no |
| `MORPH_WARPGATE` on a Gateway before research | not available |
| when research completes | the Gateway morphs to a Warp Gate on its own; charged 0/0 |
| Warp Gate → Gateway, then Gateway → Warp Gate again | both available, both charged 0/0 |
| `game_data.calculate_ability_cost(MORPH_WARPGATE)` | reports 150/0, which the game does not charge |
| Hallucination (Phoenix) | not available at 50 energy, available at 200; used 74.93 over 2 loops (≈ 0.07 regen) → **75 energy**; one hallucinated Phoenix appeared |
| Revelation | available at 50 energy; used 24.93 over 2 loops → **25 energy** |
| ares `COST_DICT` vs `BotAI.calculate_cost` (game data) | identical for Nexus, Pylon, Gateway, Warp Gate, Cybernetics Core, Photon Cannon, Shield Battery, Zealot, Stalker, Sentry, Adept, Oracle, Immortal, Colossus, Observer |

**Contradicts the spec**
- §4.0 "VERIFY that the Warp Gate research ability ID exists on Gateways": it is on the
  Cybernetics Core; the Gateway has the morph.
- §4.0 "Read `self.game_data` (e.g. `calculate_cost`)" / CLAUDE.md "read game data at runtime":
  `self.calculate_cost(UnitTypeId.X)` does not read game data under ares. Use
  `sc2.bot_ai.BotAI.calculate_cost(self, ...)` or `self.game_data.calculate_ability_cost(...)`.
- §4.3 "Sentry has ≥ 75 energy" and Revelation "VERIFY cost": no accessor; see Runtime for the
  measured values and whether availability already gates on energy.
- §4.1 8-worker "morph Warp Gates only when warp-in position matters; otherwise produce from
  Gateways": conflicts with ares's production helpers (above), and Gateways morph on their own
  when research finishes.
- §4.1 "VERIFY in game which [Warp Gate morph cost] applies": under the pool's data the morph is
  free in both directions and on every repeat; only the research costs (50/50).
- §4.3 Hallucination rule "Sentry has ≥ 75 energy": 75 is right, and checking
  `AbilityId.HALLUCINATION_PHOENIX in sentry.abilities` (or `get_available_abilities`) gives the
  same gate from game state instead of a constant.

## §11.8 `self.workers` and `self.supply_cap` on loop 0

**Found**
- python-sc2 start-up order: `_initialize_variables` (placeholder `supply_cap = 15`, empty
  workers, `sc2/bot_ai_internal.py:97`, `:120`) → `_prepare_start` → first observation →
  `_prepare_step` → `on_before_start` → `_prepare_first_step` → `on_start`
  (`sc2/main.py:119-140`). The loop-0 observation is parsed **before** `on_before_start` and
  `on_start`.
- With `realtime=False` no `client.step()` happens before the first `on_step`, so iteration 0 is
  also loop 0 (`sc2/main.py:172`, `:184`, `:208`); ares sets `game_step` from config in `on_start`
  (`ares-sc2/src/ares/main.py:344-345`), so later steps see loops 2, 4, …
- `supply_cap` is `state.common.food_cap` (`sc2/bot_ai_internal.py:709`); workers are own
  DRONE/PROBE/SCV (+ burrowed drones) of any build state (`ares-sc2/src/ares/main.py:723-724`).
- ares picks the opener inside `AresBot.on_start` (`ares-sc2/src/ares/main.py:357`) and does not
  override `_prepare_first_step`.
- Therefore the probe runs in `CitadelBot.on_start` before `super().on_start()` (`bot/main.py:23`,
  `bot/ruleset.py:13`).

**Runtime** (`poetry run python scripts/run_matches.py --map all --games 1 --race Terran
--difficulty VeryHard --build Rush`), the probe line from each game:

| map | game_loop | workers | supply_cap | supply_used | ruleset |
|---|---|---|---|---|---|
| Magannatha AIE | 0 | 12 | 15 | 12 | 1215 |
| Ultralove AIE | 0 | 12 | 15 | 12 | 1215 |
| Ley Lines AIE | 0 | 12 | 15 | 12 | 1215 |
| Torches AIE | 0 | 12 | 15 | 12 | 1215 |
| Pylon AIE | 0 | 12 | 15 | 12 | 1215 |
| Persephone AIE | 0 | 12 | 15 | 12 | 1215 |
| Incorporeal AIE | 0 | 12 | 15 | 12 | 1215 |

The loop-0 state is parsed, not placeholders: `supply_cap` 15 happens to equal python-sc2's
placeholder, but the same `_prepare_step` that set workers = 12 and supply_used = 12 (placeholders:
empty and 0) sets `supply_cap` from `food_cap` (`sc2/bot_ai_internal.py:709`). Every pool map uses the 12-worker ruleset with 15 Nexus supply
(pre-5.0.16).

**Contradicts the spec**
- §4.0 "On loop 0" does not name a hook; only `on_before_start` or `on_start` before `super()` run
  early enough for opener selection.
- §4.0/§4.1 and Open Question 1: the current pool is the 12-worker, pre-5.0.16 ruleset (above).

## §11.9 Order of ares manager updates vs `on_step`

**Found**
- python-sc2 iteration: `_prepare_step` → `issue_events` → `on_step` → `_after_step` →
  `client.step()` (`sc2/main.py:157-208`).
- ares's `_prepare_units` (called from `_prepare_step`) resets managers, records own units and
  stores enemies into cache and memory, then adds ghosts (`ares-sc2/src/ares/main.py:211`,
  `:292`, `:631-632`).
- `AresBot.on_step`: `update_managers` → build runner (if not complete) → return idle
  BUILD_RUNNER_SCOUTs to mining before 390 s → `actual_iteration += 1`
  (`ares-sc2/src/ares/main.py:415-432`).
- Manager order: Data, UnitRole, UnitCache, UnitMemory, Grid, Path, Terrain, Resource, Building,
  AbilityTracker, Placement, WarpIn, EnemyToBase, Intel, CombatSim, FlyingStructure, Squad, Creep,
  Nydus (`ares-sc2/src/ares/managers/hub.py:186-207`).
- After Citadel's code, `AresBot._after_step` executes registered behaviors, handles special
  actions, resets grids, does warp-ins, then flushes actions (`ares-sc2/src/ares/main.py:438-450`).
- `GameStep: 2` (config.yml) → `on_step` every 2 game loops; `iteration` counts `on_step` calls,
  not loops (`sc2/main.py:172`, `sc2/client.py:180`). The spec's "every 8 steps" is 16 loops
  (~0.71 s).
- In realtime ares only refreshes units every 4 loops but `on_step` still runs every loop
  (`ares-sc2/src/ares/main.py:187`); local games use `realtime=False`.

**Contradicts the spec**
- None: §3 step 1 is confirmed (managers, including unit memory, update before Citadel's code).
  Not in the spec: the build runner also acts before Citadel's code, registered behaviors run
  after it, and `on_unit_*` events fire before the managers update.

**Not verified**
- Whether AI Arena starts bots with `--RealTime`.

## Other M0 findings (not in §11)

- **SC2 4.10 Linux map folder.** python-sc2 sends the game a path relative to its maps folder
  (`sc2/maps.py:31`, `sc2/controller.py:26`), and the Linux client resolves it inside a
  lowercase `~/StarCraftII/maps`. With only `Maps` present, game creation failed with
  `InvalidMapPath: map_path '/root/StarCraftII/maps/PylonAIE_v4.SC2Map' file doesn't exist`.
  Fix used: keep the maps in `Maps` and add a symlink `~/StarCraftII/maps -> Maps`
  (python-sc2 then uses `maps`, `sc2/paths.py:150-153`). CLAUDE.md and DESIGN.md §2 say
  "`Maps`, not `maps`"; on this client both names are needed.
- **Template zip script** deleted `../python-sc2` (a folder beside the repo) before cloning; fixed
  to `./python-sc2`.

## M1 findings

Found while building M1 (openers, economy, wall fallback). Source lines are for the versions
at the top of this file.

**Ramp walls on every pool spawn (§4.8, Open Question 6).** `scripts/check_ramp_walls.py`
evaluates python-sc2's `protoss_wall_*` helpers from both spawns of each map (two players per
game). All 14 spawns have a wall Pylon, 2 wall buildings and a warp-in spot, and every ramp top
is 14.0–17.9 from the start location (§4.8's limit is 30). No pool map uses the fallback.

| map | spawn | ramp upper points | start → ramp top | wall_ok |
|---|---|---|---|---|
| Magannatha AIE | (38.5, 141.5) / (141.5, 38.5) | 2 / 2 | 15.1 / 15.1 | True / True |
| Ultralove AIE | (42.5, 46.5) / (141.5, 137.5) | 2 / 2 | 14.6 / 15.8 | True / True |
| Ley Lines AIE | (155.5, 133.5) / (42.5, 40.5) | 2 / 5 | 15.0 / 14.4 | True / True |
| Torches AIE | (124.5, 159.5) / (124.5, 48.5) | 2 / 2 | 15.7 / 15.2 | True / True |
| Pylon AIE | (175.5, 76.5) / (72.5, 171.5) | 2 / 5 | 16.2 / 15.8 | True / True |
| Persephone AIE | (37.5, 145.5) / (37.5, 34.5) | 5 / 2 | 17.9 / 17.5 | True / True |
| Incorporeal AIE | (32.5, 139.5) / (123.5, 24.5) | 2 / 2 | 14.0 / 15.0 | True / True |

**How the fallback avoids ares's crash without editing ares (§4.8, §11.5).**
- python-sc2's wall helpers are `functools.cached_property` (`sc2/game_info.py:163`, `:178`,
  `:200`), so assigning the attribute on our `Ramp` object replaces the cached value.
  `bot/defense/wall_fallback.py` does that before `super().on_start()`, pointing them at
  unbuildable map-edge tiles.
- ares keeps only placements that pass `can_place_structure`
  (`ares-sc2/src/ares/managers/placement_manager.py:713`), so those spots are never offered.
- With no wall spot available, ares's placement strategies fall back to ordinary spots: 3x3s near
  a Pylon toward `main_base_ramp.bottom_center`
  (`ares-sc2/src/ares/managers/utils/placement_strategy.py:161`) and Pylons at the free spot
  nearest `main_base_ramp.top_center` (`:263`, `:276`). `scripts/test_wall_fallback.py` checks
  this in game.

**`MacroPlan` stops at the first behavior that returns True**
(`ares-sc2/src/ares/behaviors/macro/macro_plan.py:51`). Two ares behaviors return True without
acting, which stops everything after them:
- `AutoSupply` returns True whenever supply is "required"
  (`ares-sc2/src/ares/behaviors/macro/auto_supply.py:43`, `:58`), and it counts as required until
  half as many Pylons are in progress as there are production structures (`:119`). It builds with
  `BuildStructure`, whose `max_on_route` defaults to 1
  (`ares-sc2/src/ares/behaviors/macro/build_structure.py:83`, `:111`), so only one Pylon is ever
  on its way. In test games it returned True on 68 and 109 macro ticks in minutes 7 and 8, and
  probes and production stopped. Citadel uses its own Pylon timing after the opener
  (`bot/macro/supply.py`). The build runner still uses `AutoSupply` during the opener
  (`ares-sc2/src/ares/build_runner/build_order_runner.py:264`).
- `SpawnController` stops at the first unit in priority order that it can't afford, even when
  that unit's share is already met ("don't spend resources on lower priority units",
  `ares-sc2/src/ares/behaviors/macro/spawn_controller.py:176-178`). Short of gas for a Colossus or
  Immortal, it made nothing while minerals piled up. `bot/macro/production.py` adds a
  `freeflow_mode` Gateway-unit spend above `MINERAL_FLOAT_BANK`.
- `SpawnController` also skips a unit whose tech isn't ready
  (`ares-sc2/src/ares/behaviors/macro/spawn_controller.py:130`) and stops making a unit once its
  count reaches its share of the current army (`:190`). A share for an unbuildable unit (Colossus
  before a Robotics Bay) therefore left the Gateways idle: in a C_2GateRobo game vs Hard Protoss
  the army was 22 supply at 6:00 with 700+ minerals banked. `bot/macro/production.py` now gives it
  only the tech-ready units, with their shares rescaled (32 army supply in the same game).

- `UpgradeController` walks its whole list on every call
  (`ares-sc2/src/ares/behaviors/macro/upgrade_controller.py:66`). An upgrade whose research
  building is still under construction is skipped, and the next one starts its own tech building
  (`:81-86`, `:118`), so a list of six started a Forge, Twilight Council and Robotics Bay within
  one second at 5:00. That game (B_PvZ vs Hard Zerg) had 9 army supply at 6:00 and was lost.
  `bot/macro/production.py` passes one upgrade at a time.

**Opener timing on the pool (12-worker, with Nexus chrono from 0:00).**
- The build runner logs `<supply> <time> <command>` when a step completes
  (`ares-sc2/src/ares/build_runner/build_order_runner.py:530`); these are the opener timings.
- A family (A/A2/B/B2 and the vs-Random pair): "19 Nexus" landed at 1:17, before §4.1's
  ~1:25–1:40, so the openers use the spec's other option, 20.
- C2's "23 Nexus" lands at about 2:10, before §4.1's ~2:30–2:45. The supply number is kept.
- Two supply blocks happen in every A/B opener: 0:18–0:32 (waiting for the 14 Pylon to finish)
  and about 1:50–2:04 at 23/31. The 22 Pylon only goes down at ~1:46 once the Nexus, Core and gas
  are paid for; a 21 trigger changed nothing. Removing it would need a Pylon before the Core,
  which changes the spec's build.

## M2 findings

Found while building M2 (ares bridge, detectors, ThreatFlag expiry, defense plans). Source lines
are for the versions at the top of this file.

**ares's own-army cache includes workers (M1 bug, fixed in M2).**
`mediator.get_own_army` is UnitCacheManager's `own_army`, which gets every own unit whose type
is not in `UNITS_TO_IGNORE` (`ares-sc2/src/ares/managers/unit_cache_manager.py:365-367`), and
that set is empty (`ares-sc2/src/ares/consts.py:908`); `_prepare_units` stores every own
non-structure there (`ares-sc2/src/ares/main.py:718-720`). M1's `BasicArmy` iterated it, so it
gave probes attack-move orders whenever its target changed and counted them as army supply
(an "army supply 145" attack at 14:20 in a test game was ~80 without probes). `BasicArmy` now
leaves workers out.

**Building tracker.**
- ares drops a build order only after 120 s (`BUILDING_WORKER_TIMEOUT`,
  `ares-sc2/src/ares/managers/building_manager.py:67`, checked at `:229-234`).
- A dead builder's order goes to a new worker with the same target (`:393-411`), so a spot an
  enemy Cannon covers keeps drawing probes; a spot that can't be placed is re-requested
  (`:369-377`).
- Citadel: `static_defense.py` moves tracked orders whose target an enemy Cannon covers to a new
  ares placement (as ares does for a blocked spot), and `supply.py` stops counting a Pylon order
  that hasn't started after `PYLON_STUCK_S` as on its way (neither as a free build slot nor as
  coming supply: ares's `structure_pending` counts every tracker entry,
  `ares-sc2/src/ares/main.py:1086-1115`).
- A builder that dies with enemy static defense or enemy units within `BUILDER_DANGER_RADIUS`
  of its target or of where it fell has its order dropped (target None, which ares removes,
  `building_manager.py:254-257`) instead of handed on; with static defense at the target the
  spot is also marked unavailable. Other builder deaths are left to ares. **Runtime** (cannon rush, natural
  variant, PylonAIE_v4): before the fix one Pylon order sat 55 s at (93, 181) next to the rush
  Cannons while minerals reached 960 at 47/47 supply; after it, `DEFENSE PYLON order moved from
  (93, 181) to (78, 172)`.
- ares's Pylon spots are the ones it computed at start (`placement_manager.py:900`,
  `_find_placements_for_base_location`); a one-base bot ran out of them at 62/70 supply.
  `supply.py` falls back to a free tile it finds itself.

**Placement table.** `mediator.get_placements_dict` is a property returning the live dict
(`ares-sc2/src/ares/managers/manager_mediator.py:1664`); its `available` flag is what ares's
placement search filters on (`ares-sc2/src/ares/managers/placement_manager.py:697-715`).
`static_defense.py` marks spots in a Cannon's range unavailable and restores them when the
Cannon is gone. `BUILDING_SIZE_ENUM_TO_RADIUS` is in `ares.consts` (`consts.py:198`);
`STRUCTURE_TO_BUILDING_SIZE` is in `ares.dicts.structure_to_building_size` (`:9`), not
`ares.consts`.

**ares never cancels a dying structure.** `BuildingManager.on_structure_took_damage` would
cancel below max(50, 9% of max HP) (`ares-sc2/src/ares/managers/building_manager.py:688-701`),
but the hub's `on_unit_took_damage` is an empty method
(`ares-sc2/src/ares/managers/hub.py:306-314`), so it never runs. ares's threshold also compares
health only, against the finished maximum: a structure starts at 10% of its HP and shield and
gains the rest as it builds, so a new Pylon (20 of 200 HP) is under 50 from the start and would
be cancelled at its first hit. Citadel's `WorkerDefense.on_structure_damaged` (called from
`CitadelBot.on_unit_took_damage`) cancels when HP + shield falls below
`CANCEL_EXPECTED_FRACTION` of the undamaged value at the current build progress.
python-sc2 fires `on_unit_took_damage` for own units and structures
(`sc2/bot_ai_internal.py:917`, `:952`) and `on_unit_destroyed` for every tag in the previous
step's map, enemies included (`sc2/bot_ai_internal.py:980-982`), which §5 rule (a) needs.

**Worker scout lifecycle.** The `worker_scout` step queues moves around the enemy main and
gives the probe `BUILD_RUNNER_SCOUT` (`ares-sc2/src/ares/build_runner/build_order_runner.py:446-455`);
once idle, ares hands it back to `GATHERING` before 390 s
(`ares-sc2/src/ares/main.py:419-429`), inside `AresBot.on_step`, before Citadel's code.
`bot/intel/scout_planner.py` notices the role change and takes it back as `SCOUTING`
(`UnitRole.SCOUTING`, `ares-sc2/src/ares/consts.py:536`) to watch the enemy natural.

**Roles and mining.** `mediator.assign_role(tag=, role=)` and
`mediator.get_units_from_role(role=, unit_type=)`
(`ares-sc2/src/ares/managers/unit_role_manager.py:168`, `:242`). ares's `Mining` only moves
`GATHERING` workers (`ares-sc2/src/ares/behaviors/macro/mining.py:88-92`), so pulled probes get
`UnitRole.DEFENDING` (`consts.py:503`) and are handed back as `GATHERING`. With
`self_defence_active`, mining workers hit enemies in range when their tile is unsafe
(`mining.py:115-165`, `:516-527`). `Mining(workers_per_gas=n)` sets the gas saturation through
`mediator.set_workers_per_gas`; ares pulls one worker per update when a gas building has more
(`ares-sc2/src/ares/managers/resource_manager.py:519-534`).

**Build runner and walls.** Wall placement (`@ ramp`) is skipped while any enemy unit is within
10 of the ramp top (`ares-sc2/src/ares/build_runner/build_order_runner.py:618-625`).

**python-sc2 memory flag.** `Unit.is_memory` is True for a Unit object older than the current
game loop (`sc2/unit.py:476-479`), which is how ares's ghosts show up in `enemy_units`: its
UnitMemoryManager appends remembered units to `ai.enemy_units` and `ai.all_enemy_units` each
step (`ares-sc2/src/ares/managers/unit_memory_manager.py:224-225`). Checks of where enemies are
now (the 12-pool expansion gate, worker defense targets) filter them out.

**ExpansionController stops holding money once its probe leaves.** With `prioritize=True` it
returns True (holding the rest of a MacroPlan) only until it sends a probe; from then on the
order counts as pending (`structure_pending` counts building-tracker entries,
`ares-sc2/src/ares/main.py:1100-1107`) and `execute` returns False
(`ares-sc2/src/ares/behaviors/macro/expansion_controller.py`, `execute`). Everything after it keeps
spending, and ares's building manager only places the Nexus when it can be afforded
(`building_manager.py:380-385`). **Runtime** (worker rush, UltraloveAIE_v2): the probe waited at
the natural from 1:17 to past 5:00 with minerals under 400. `economy.ReserveForPending` now holds
later spending while such an order is younger than `RESERVE_FOR_PENDING_MAX_S`.

**Attack-moving into a cluster of structures.** An attack-move to a point inside a
cluster of enemy structures stops short with nothing in range (units idle ~9 from a Cannon
cluster at our natural in a test game); `BasicArmy` attacks a visible structure directly once
within `ARMY_DIRECT_ATTACK_MARGIN` of weapon range. `client.query_pathing` to a point inside a
structure's footprint returns None, so it can't be used to test such targets.

## M2 Citadel choices

Where §4.2/§5 leave a choice open, or a test game showed the spec's plan alone wasn't enough,
M2 decided as below. Every value is in `bot/constants.py`.

| Area | Choice | Why |
|---|---|---|
| Proxy check (§4.4 rows 7, 10) | Runs once, only if the enemy main was scouted by `PROXY_CHECK_UNTIL_S` (3:00). The worker counts stay as §4.4 writes them (what the scout saw): gating them on seeing the mineral line removed false flags vs the built-in AI but missed a 3-Barracks all-in (3 SCVs seen), and a missed all-in costs more than a false flag | Mains first seen by the army at 9:00+ raised PROXY mid-game |
| Scope (user decision) | Detectors for M2's five threats only; test opponents are our own python-sc2 bots (`scripts/test_bots/`); the proxy check uses §4.4 rows 7 and 10 once our scout has seen the enemy main, not before 1:30; the scout probe then watches the enemy natural until the one-base deadline | Plan approval |
| Opener override | WORKER_RUSH, PROXY and POOL_12 end the ares opener; CANNON_RUSH only with STRUCTURE evidence (an enemy probe alone is often a scout); ONE_BASE_ALLIN never. After an override or the 4:00 timeout `BuildExecutor` adds `OPENER_ESSENTIALS` (ramp Gateway and Core, 2 gas, Warp Gate, 2 bases) | 12-pool Zerglings arrived before the opener's Zealot |
| Early Pool | A Pool started by `EARLY_POOL_CERTAIN_S` (0:45) raises POOL_12 at once; later ones are compared with the natural Hatchery | No hatch-first natural starts before ~0:48 on 12 workers |
| Unit reserve | `reserve_units`: until that many Gateway units exist, the MacroPlan and the direct main-Battery orders wait for the plan's first tech-ready Gateway unit (`ReserveForUnit`) | Probes and Pylons took the minerals for the wall Zealot |
| 12-pool | 2 Gateways, chrono on Gateways, Zealot then Adepts, tech waits while the expansion gate is closed; the gate switches only after its condition holds `POOL_12_GATE_HOLD_S`; the army holds behind the wall gap until `POOL_12_PUSH_SUPPLY`, then the natural. The first `POOL_12_RESERVE_UNITS` (3) Gateway units, and any Gateway, Core or Battery order waiting for money, come before probes; no long-distance mining while the gap is held; probes fight lings only in their own base's mineral line (same level, within `LING_DEFENSE_PULL_RADIUS`). The Cybernetics Core (ramp wall) comes right after the reserved units, but is not rebuilt while enemy ground units are in the main. A gap holder below `WALL_SWAP_HP_FRACTION` swaps with a healthy Zealot/Adept and steps back | Magannatha, Torches and Ley Lines test games: the second unit came 78 s after the first while the Nexus made probes; main probes were pulled out through the gap to the natural's mineral line; the Battery waited for a late Core; five probes died rebuilding the wall Core among the lings; a holder died every ~20 s with the next unit standing behind it |
| Proxy | Timed tech waits below `DEFENSE_TECH_AFTER_SUPPLY` army supply (not vs Cannons); ramp hold with a leash until 2 units and a natural, then the natural | Units trickled out one by one |
| One-base | Timed tech waits below 8 army supply unless Roaches or Cannons are seen; Immortal after earlier threats' first units vs Roaches; an earlier threat's hold point stands | Plan precedence |
| Cannon rush | Build out of finished Cannons' range by marking ares's placement table; move covered orders; no long-distance mining; while a Cannon covers our natural, no expansion at all (every probe sent to the next base died passing the Cannons). While a finished Cannon covers one of our Nexuses: no expansion, `CANNON_SIEGE_RESERVE_UNITS` Gateway units before probes, and the army attacks that Cannon once it has `ARMY_SUPPLY_PER_CANNON` per Cannon covering it | Natural-variant test games; a main-variant game where one Cannon killed the main Nexus while 2 units idled |
| Expansion | `EXPANSION_RETRY_S` without a new Nexus after a Nexus builder dies; probes capped at `PROBES_PER_HELD_BASE` per base + `PROBES_HELD_SPARE` while expanding is held | 60 probes on one base left the Gateways idle |
| Army | Recall from an attack only if enemies at home have ≥ `ARMY_RECALL_FRACTION` of our supply; don't engage at home below `ARMY_ENGAGE_RATIO` of enemy supply (finished Cannons count `ARMY_SUPPLY_PER_CANNON`); structures near our bases are targets from `ARMY_CLEAR_STRUCTURES_SUPPLY` | Units fed into Cannons and Marines one at a time |
| Production | `gateway_upkeep` morphs powered idle Gateways and powers unpowered ones | ares's SpawnController makes nothing while any ready idle Gateway exists after Warp Gate |
| Cancel rule | HP + shield below `CANCEL_EXPECTED_FRACTION` of the undamaged value at the current build progress | ares's rule cancels new Pylons at their first hit |

## M2 acceptance evidence

Acceptance (DESIGN.md §7): at least 8/10 wins against each of the worker-rush, SharpCannons-style,
12-pool and proxy test bots. Each batch is 10 games, one per pool map in order
(`MagannathaAIE_v2, UltraloveAIE_v2, LeyLinesAIE_v3, TorchesAIE_v4, PylonAIE_v4,
PersephoneAIE_v4, IncorporealAIE_v4`, then the first three again), opponent seed 100 + game
number, 60:00 game limit:

```
poetry run python scripts/run_matches.py --opponent <bot> --map all --total 10 --seed 100
```

The batches ran on commit d3ae640. A container restart stopped them before the last games; those
were resumed with the same maps and seeds (e.g. games 8-10 of `cannon_rush` with
`--map MagannathaAIE_v2 UltraloveAIE_v2 LeyLinesAIE_v3 --total 3 --seed 107`, since game `i`
of a run uses seed `--seed + i`). The final code (cb092d1) differs from d3ae640 only in the
§4.4 worker-count rule of the proxy check, which never decides a flag against these bots: none
of them has a Barracks or Gateway in its main at 1:30, so their PROXY flags come from the
"no production" part either way.

| Test bot | Wins | Losses | Crashes | Result |
|---|---|---|---|---|
| `worker_rush` | 10 | 0 | 0 | PASS |
| `cannon_rush` (natural and main variants) | 9 | 1 (game 6, Persephone, main variant) | 0 | PASS |
| `twelve_pool` | 8 | 2 (game 4 Torches, game 10 Ley Lines) | 0 | PASS |
| `proxy_rax` (third and center variants) | 10 | 0 | 0 | PASS |

The losses:
- **Cannon rush, Persephone, main variant, seed 106** (lost in two of three runs): the rusher's
  first Cannon finishes next to our main Nexus by 2:00 and six more follow by 3:00. §4.2 stops
  the probe attack once a Cannon completes, the Cannons also cover our second Gateway, and the
  Nexus dies before 4:00.
- **12-pool, Torches and Ley Lines**: the opener's natural Nexus was already placed when POOL_12
  was raised (1:20-1:21), so it was kept (§4.2 cancels or delays it only "if it is not yet
  started"). When it finished, ares's Mining sent probes out through the wall gap to its
  minerals (gathering probes pass through units), and the lings killed them there.

Other checks on the final code (cb092d1):
- M1 regression, `poetry run python scripts/run_matches.py --difficulty Hard --map all --total 10 --race Terran Zerg Protoss Random`:
  10/10 wins, 0 crashes; 44+ probes at 6:00 in 9/10 games (median 57.5). The exception (41, Ley
  Lines vs Hard Protoss) had PROXY raised by §4.4's "no Gateway in the main at 1:30", which
  holds the expansion; the built-in AI sometimes has no production at 1:30.
- One-base plan, `poetry run python scripts/run_matches.py --difficulty Harder --build Rush --race Terran Zerg Protoss --map all --total 3`:
  2/3. Vs Terran, ONE_BASE_ALLIN was raised at 1:32 and 3:20 (ares marine rush) with PROXY
  (3 SCVs seen next to 3 Barracks), the plan asked for 3 natural Batteries, no third and no
  Forge, and the game was won. The Zerg rush was held (1 probe lost, 149 supply at 10:00);
  that game was lost after 10:00 to Ultralisks and Brood Lords (M4's army work). Vs Protoss
  no all-in was detected and the game was won.
- `poetry run python scripts/test_threat_flags.py`: 20/20 passed.
- Ladder zip: `poetry run python scripts/create_ladder_zip.py` builds `publish/Citadel.zip`
  (366 files) with `run.py`, `config.yml` and `ladder.py` at the top level.

## M3 findings

Found while building M3 (scout planner). Source lines are for the versions at the top of this
file; **Runtime** results come from `poetry run python scripts/test_scout_abilities.py`
(PylonAIE_v4, a bare AresBot driven by debug commands, so nothing else moves the units).

**Adept shade (§4.3 PvT/PvZ).** Runtime:

| check | result |
|---|---|
| ability on the Adept | `AbilityId.ADEPTPHASESHIFT_ADEPTPHASESHIFT` (2544), with a target point |
| the shade | own unit `UnitTypeId.ADEPTPHASESHIFT`, appears 2 loops after the cast; takes `MOVE_MOVE`; offers `CANCEL_ADEPTSHADEPHASESHIFT` |
| the Adept while the shade lives | offers `CANCEL_ADEPTPHASESHIFT` (2594) |
| shade lifetime | 158 loops (~7.1 s) |
| when it ends by itself | the Adept teleports to it (18 away in the test) |
| `CANCEL_ADEPTPHASESHIFT` on the Adept | the shade disappears at once and the Adept stays where it cast |
| cooldown | castable again 256 loops (~11.4 s) after the cast |
| `on_unit_destroyed` | fires for the shade's tag both when it ends and when cancelled (so the shade must not be tracked as a scout, or it would count as lost) |

`AdeptShadeTask` cancels at `SHADE_CANCEL_S` (6 s).

**Hallucination (Phoenix).** Runtime: the hallucinated Phoenix appears 2 loops after the cast,
1.2 from the Sentry, in `self.units` with `is_hallucination` True and **no orders** (as §4.3
expects after the 5.0.16b revert), so `PhoenixTask` orders every point itself. It lived 958
loops (~42.8 s) and flew ~120; `on_unit_destroyed` fires when it ends. The Sentry used 74.9
energy (§11.7's 75). `Unit.is_hallucination` reads the observation proto
(`sc2/unit.py:1047-1049`); Telemetry records a hallucination's end as "expired", not "lost".

**Oracle Pulsar Beam.** Runtime: `BEHAVIOR_PULSARBEAMON` (2375) is available at 200 energy and
swaps for `BEHAVIOR_PULSARBEAMOFF` (2376); activation took 25.4 energy over 4 loops; with the beam
on the Oracle lost 20.1 energy in 10 s (net of regeneration). The test Drone fled out of vision, so
killing one was not observed; the Oracle kept its attack order. `OracleTask` turns the beam on only
at `ORACLE_BEAM_MIN_ENERGY` and logs `SCOUT oracle beam on`.

**Unit abilities are refreshed every step.** python-sc2 queries every own unit's available
abilities in `_prepare_step` with `ignore_resource_requirements=False`
(`sc2/bot_ai_internal.py:722-730`), so `AbilityId.X in unit.abilities` is also the energy and
cooldown check (Hallucination, Revelation, the shade).

**Detection.** Runtime: `mediator.get_is_detected(unit=observer)` is True for an own Observer 3 from
a powered enemy Photon Cannon and False 20 away; `Unit.is_revealed` stayed False in both. A
detected Observer next to a Cannon is shot down within seconds (the first test Observer died).

**Ground-grid influence of workers and melee units.** Units with ground range < 2 (workers,
Zerglings, Zealots) add their ground DPS within `RangeBuffer` (4.0, `ares-sc2/src/ares/config.yml:39`)
of their position to the ground grid (`ares-sc2/src/ares/managers/grid_manager.py:808-825`), so
scouts path around enemy workers and lings too.

**Map regions for proxy spots.** `mediator.get_map_data_object` is a property returning
map-analyzer's `MapData` (`ares-sc2/src/ares/managers/manager_mediator.py:1539-1550`);
`MapData.regions` is a dict of `Region`s, and `Region.center` is a region point nearest its centre
of mass (`map_analyzer/Polygon.py:156-170`). The pool maps give 3-4 proxy spots within 40 of our
natural once expansions and a ring are added and spots closer than 12 are merged.

**Taking the build runner's scout.** The `worker_scout` step selects a probe, sends it a queue of
moves and gives it `BUILD_RUNNER_SCOUT`
(`ares-sc2/src/ares/build_runner/build_order_runner.py:446-455`); ares only hands idle probes with
that role back to mining (`ares-sc2/src/ares/main.py:419-429`), so reassigning `SCOUTING` in the
same step keeps it. `unit.order_target` is the first order's target tag or point
(`sc2/unit.py:1092-1100`); `Mover.move` uses it to skip identical move orders (§6 APM).

**Cannon test bot on Torches and Incorporeal.** The cannon bot's "natural" is the expansion nearest
our main in a straight line, which on some maps is not ares's natural; its Cannons can then be
> 25 from both our main and natural (§4.2's radius), and on Torches its rush probe placed nothing
at all. In both cases only §4.4 row 3 (the Forge in its main) gives a CANNON_RUSH flag.

## M3 Citadel choices

| Area | Choice | Why |
|---|---|---|
| Scope (user decision) | "Correct flag" = the bot's expected flag raised before the cheese reaches us (worker rush 1:00, cannon 1:30, 12-pool 1:45, proxy 2:00) and no flag outside its allowed list (`M3_EXPECTED_FLAGS`); games: the 4 test bots × 10 plus 21 built-in Harder games for the scout-loss criterion; new flags only §4.4 rows 3 and 15; Hallucination only from an existing Sentry | Plan approval |
| Main probe route | Past the enemy natural first, then a lap of the main, then the natural watch until the no-natural deadline (M2 decision), then the proxy spots near our natural, then home | Row 3 needs to know the natural was empty after the Forge started; the natural is on the way |
| Probe exits | Home at once on POOL_12, and on WORKER_RUSH before it reaches the enemy main; straight to the proxy spots on PROXY; home below 50% HP+shield | M2: the scout died to lings in 10/10 12-pool games and to the rushers in 5/10 worker-rush games |
| When a scout counts as lost | Only while it has a task. A probe's task ends when it is back within `SCOUT_HOME_RADIUS` of our start (or 12 of a townhall); a unit's when it is back at our natural. A recalled probe that then fights a worker rush is a defender, not a scout | Definition for the acceptance metric |
| Retry | One more main probe (by 2:30) if the first came home or died before the main was scouted, once no rush flag is active | After a worker rush the enemy main was otherwise never seen |
| Row 3 | A Forge in the Protoss main with no Gateway there, and their natural seen empty since the Forge started (or 1:30 passed), raises CANNON_RUSH `forge_first`: patrol probe and a 150 bank after the opener, no opener override; the proxy check doesn't raise PROXY in that case; the flag expires if their natural Nexus is seen (Forge-first expand) | Every cannon-rush game raised a false PROXY in M2 |
| Row 15 | UNKNOWN_AGGRO only if no active rush flag explains the dead scout; expires when the enemy main is scouted or at 5:00 | "Unknown" aggression |
| Worker rush | No proxy check after a WORKER_RUSH; rush probes never count as a lingering cannon-rush probe | False PROXY / CANNON_RUSH flags in M2's worker-rush games |
| Unit scouts | Combat units are taken only while none of WORKER_RUSH, POOL_12, PROXY, ONE_BASE_ALLIN, or a non-Forge-first CANNON_RUSH is active (Defense > Scouting); never pinned units | §3 order of authority |
| Observers | Before 6:00 posts per matchup; from 6:00 one is left to `BasicArmy`, which already moves free Observers with the army | §4.3 "travels with the army" |
| Re-scouts | Stale STRUCTURE evidence: Observer, or a probe if on our side (within 45 of our natural); stale main (60 s, after 3:00): Observer; Hallucination as §4.3 | §5 re-scout trigger |

## M3 acceptance evidence

Acceptance (DESIGN.md §7 M3, user decisions): the correct flag logged in ≥ 80% of scripted-cheese
games, meaning each test bot's expected flag is raised by its deadline and no flag outside its
allowed list is raised (`M3_EXPECTED_FLAGS`, checked by `scripts/m3_checks.py`, tested offline by
`scripts/test_m3_checks.py`, 13/13); and no scout lost before 4:00 in ≥ 70% of games, over the
40 cheese games and, separately, 21 built-in Harder games. A unit counts as a scout while it has a
scouting task (M3 choices above). All runs on commit 95ee868, same maps and seeds as M2:

```
poetry run python scripts/run_matches.py --opponent <bot> --map all --total 10 --seed 100
poetry run python scripts/run_matches.py --difficulty Harder --race Terran Zerg Protoss --map all --total 21
```

| Games | Correct flag | No scout lost before 4:00 | Wins (M2 check) | Crashes |
|---|---|---|---|---|
| `worker_rush` × 10 | 10/10 (WORKER_RUSH at 0:35-0:39) | 10/10 | 10/10 | 0 |
| `cannon_rush` × 10 | 10/10 (CANNON_RUSH at 0:39-1:20) | 10/10 | 10/10 | 0 |
| `twelve_pool` × 10 | 10/10 (POOL_12 at 1:08-1:24) | 10/10 | 9/10 | 0 |
| `proxy_rax` × 10 | 10/10 (PROXY at 0:39-1:30) | 10/10 | 10/10 | 0 |
| Built-in Harder × 21 (T/Z/P) | not part of the criterion | 21/21 | 15/21 | 0 |

**Result: PASS.** Correct flag 40/40 (≥ 8/10 per bot); no scout lost before 4:00 in 40/40 cheese
games and 21/21 built-in games (≥ 70%).

Against M2's code on the same seeds (M2 logs): 25/40 cheese games kept their scout to 4:00 (the
probe died to the rushers in 5/10 worker-rush games and to Zerglings in 10/10 12-pool games), and
the strict flag check failed in every cannon-rush game (a false PROXY) and in half the worker-rush
games (false CANNON_RUSH/PROXY).

Scouting tasks run in the 21 built-in games (outcome counts): main probe home 21; patrol probe home
7; Adept shade done 10, lost 3 (4:36, 4:53, 5:30); Stalker poke 7; Oracle 6 (Revelation or Drone
beam 11 times across all runs); Observer post 14; home Observer 6; hallucinated Phoenix 27
(Sentries exist vs Terran only); expansion checks 150 (15 probes lost, all after 5:00); re-scouts
67. The built-in games raised no false PROXY flag (M2's known issue); POOL_12 was raised in all 7
Zerg games (the Harder Zerg AI opened Pool first, 1:10-1:29); 2 of those were lost, after 12:50.

Losses:
- 12-pool game 10 (Ley Lines): the Pool was seen at 1:24 on the spawn with the longer route, 5 s
  after the opener placed the natural Nexus (1:19); lings broke the wall gap at ~3:00 (the M2
  open question in `docs/STATUS.md`).
- Built-in Harder: six losses, all between 12:52 and 18:57 (late-game army play, M4's area).

Regression checks on 95ee868 are listed in `docs/STATUS.md`.

## M4 findings

Found while building M4 (squads, `EngagementResult` gates, retreat hysteresis, end-game). Source
lines are for the versions at the top of this file.

**What the simulator's timing adjustment does (§4.5.2 static defence, §11.3).** The simulator
core is compiled (`ares-sc2/sc2_helper/sc2_helper.*.so`; its Rust source is not in the repo), so
this is from runtime probes (`scratchpad` probe game on PylonAIE_v4, 6 own Stalkers = 960 HP +
shields; most common of 20 calls to `predict_engage`):

| enemy | timing on, defender none (ares's `can_win_fight`) | timing on, enemy defends | timing on, we defend | timing off |
|---|---|---|---|---|
| 3 Cannons | won, 960 left | won, 113 left | won, 960 left | won, 320 left |
| 6 Cannons | won, 960 left | lost, 1529 left | lost, 1800 left | lost, 1481 left |
| 6 Stalkers | lost, 189 left | lost, 189 left | lost, 189 left | lost, 189 left |

- `predict_engage(own, enemy, optimistic=False, defender_player=0)`
  (`ares-sc2/sc2_helper/combat_simulator.py:114`); ares always passes the default
  `defender_player=0` (`ares-sc2/src/ares/managers/combat_sim_manager.py:136-137`).
- The simulator is never given positions. With timing adjustment on, the side(s) not marked as
  the defender must walk into range first, which takes time by movement speed. With no defender,
  a Cannon (movement speed 0) never gets into range, so it never fires: that is M0's "Cannons
  soak shots but never shoot". With the enemy as defender its Cannons shoot from the start while
  our units walk in. With us as defender and only structures on the enemy side, nobody walks in
  and the result is decided on health alone (the "we defend" column).
- Confirmed by the per-type cache: the simulator keeps each unit type's stats from the first
  unit of that type it sees in the process. In a fresh process whose first Cannon reported a
  Stalker's movement speed (a Python proxy object), Cannons fired with no defender too (won,
  113 left vs 3 Cannons).

**Citadel's level (`bot/army/engagement.py`, user decisions).** The same simulator and the same
11 levels as ares's `can_win_fight`, but with our HP + shields as the denominator after a win, and
the defender set: the enemy when our squad attacks, us when we defend at home (the enemy when
its side holds structures, which would otherwise stall the simulation). Runtime
(`poetry run python scripts/test_engagement.py`, PylonAIE_v4; most common of 20 calls, range in
brackets):

| scenario | Citadel | ares `can_win_fight` |
|---|---|---|
| 6 Stalkers vs nothing | 10 (10-10) | 10 (10-10) |
| 6 Stalkers vs 6 Stalkers | 5 (5-5) | 5 (5-5) |
| 6 Stalkers vs 4 Zealots | 6 (6-6) | 10 (10-10) |
| 6 Stalkers vs 3 Cannons (attacking) | 5 (5-5) | 10 (10-10) |
| 6 Stalkers vs 6 Cannons (attacking) | 1 (1-1) | 10 (10-10) |
| 12 Stalkers vs 3 Cannons (attacking) | 9 (9-9) | 10 (10-10) |
| 6 Stalkers vs 6 Stalkers (defending) | 5 (5-5) | 5 (5-5) |
| 6 Stalkers + 2 own Cannons vs 6 Stalkers (defending) | 9 (8-9) | 10 (7-10) |

`Engagement.attack_inputs` from our Stalkers to the enemy group returned the 6 Stalkers, 4
Zealots, 6 Cannons and the Shield Battery, and left out the 4 Probes, the Observer and the Pylon.

**Snapshots don't report power.** An enemy Photon Cannon out of vision is a snapshot, and its
`is_powered` (`sc2/unit.py:1009`, the proto's `is_powered`) was False for every fogged Cannon in the
cannon_rush Ultralove game: with a "powered" check, 8 rush Cannons were left out of the fight and 4
of our units read level 10 against them. Citadel's static-defence test now requires power only of
a visible Cannon (`bot/army/engagement.py` `is_static_defense`).

**The last structure's death isn't reported.** When the enemy's last structure dies the game ends
in that step, and python-sc2 never calls `on_unit_destroyed` for it (`scripts/test_endgame.py`: the
Victory is the evidence).

## M4 Citadel choices

Where §4.5.2/§4.7 leave a choice open, M4 decided as below. Every value is in `bot/constants.py`.

| Area | Choice | Why |
|---|---|---|
| Scope (user decisions) | Acceptance = 10 VeryHard games per race (T/Z/P, all 7 maps cycled), ≥ 7 wins for each race. The level is computed by Citadel from the simulator with our HP + shields; the defender is set (the enemy when we attack, us at home) instead of a static-defence penalty. Non-army changes are allowed if the VeryHard losses call for them, each logged here | Plan approval |
| Fight inputs (§4.5.2) | Our side: the squad's fighting units (no workers, Observers, Warp Prisms, hallucinations). Enemy side: visible units and ares's 30 s ghosts within 20 of the squad or its target, without workers, hallucinations, Overlords/Overseers/Observers, eggs, larvae, changelings; finished static defence (Cannons only when powered) and Shield Batteries within 15 of the target or of the squad | Workers and support units don't decide fights; ghosts expire after 30 s (§11.2) |
| Home defence | The DEFEND squad fights a home threat inside our main or within `ARMY_HOLD_LEASH` of the defensive position whatever the level (there is nowhere to fall back to); at ≥ `DEFEND_ENGAGE` (4) when the fight is within `BATTERY_COVER_RADIUS` of a ready Battery; at ≥ `ATTACK_CONTINUE` (5) elsewhere; otherwise it holds the defensive position. Our Cannons within 15 of the fight are on our side | §4.5.2 "never leaves the battery radius"; a base without Batteries is only defended on an even or better fight |
| Structures near our bases (M2 rules) | M2's "6 supply per finished Cannon" becomes "level ≥ `CLEAR_STATIC_LEVEL` (7) against the finished Cannons near our bases and the enemy units around them"; any structure or worker target near our bases is attacked only if the squad beats the static defence and units within 15/20 of that target at the same level; `ARMY_CLEAR_STRUCTURES_SUPPLY` stays | M2's 3 Stalkers per Cannon reads 7-8 (6 vs 3 = 5, 12 vs 3 = 9). At level 5, and with only the Cannons "near our bases" counted, the M4 army fed its first units into rush Cannons in the cannon_rush Ultralove game (a loss, then a 60:00 tie, where M3 had won) |
| Home fight turns bad | A DEFEND unit that was fighting and is farther than `HOLD_ENGAGE_RADIUS` from the defensive position when the decision flips to hold retreats (danger-aware path, shooting only when its weapon is ready) instead of attack-moving back | VeryHard Zerg (Torches, acceptance game 4 on 5589a6c): the squad chased Zerglings to the natural, Roaches arrived, and the units died fighting their way back; the main Nexus fell at 6:00 |
| Recall (§3 Defense > Main attack) | While the ATTACK squad is out, a home threat the DEFEND squad won't fight recalls it if the enemies there are worth ≥ `ARMY_RECALL_FRACTION` of the ATTACK squad's value; a recall has no relaunch wait, only the 20 s flip hold | M2's rule in value instead of supply; a recall is not a lost fight |
| Retreat rules | The 40% value rule is not held back by `MIN_STATE_SECONDS` (units dying is not simulator noise; sieged tanks out of sight read as an empty fight); the level rule is | §4.5.2 lists the two triggers separately |
| Targets | The known enemy townhall nearest the squad's main group, kept until it is gone (destroyed, or its snapshot dropped); then the nearest other grounded structure; then the structure hunt (enemy start, enemy expansions, all expansions, walkable region centres, a map grid) | §4.5.2 "nearest known enemy expansion → the next one → the main" |
| Regroup | ares's squad manager splits the ATTACK squad (radius `ATTACK_SQUAD_RADIUS`); while not in a fight, the main group holds while the other groups have ≥ `REGROUP_FRACTION` of the squad's supply, and the others walk to it | Stragglers otherwise fight alone |
| Reinforcements | DEFEND units within `HOLD_ENGAGE_RADIUS` of the defensive position leave as one REINFORCE group once they have `REINFORCE_MIN_SUPPLY` (8) and no home threat is on; the group joins the ATTACK squad within `REINFORCE_JOIN_RADIUS` of its main group (its value is added to the start value) and turns back if a fight on the way reads ≤ `RETREAT_AT` | §4.5.2 "groups of ≥ 8 supply; never trickle them in" |
| Micro | Every step for units with a visible enemy within `MICRO_RADIUS`: shoot the lowest-HP enemy in range that can fight back (then anything in range); between shots, kiters (Stalker, Adept, Immortal, Colossus, Sentry, Phoenix, Void Ray, Oracle) step out of danger with `KeepUnitSafe` when they out-range the closest threat; retreats path around danger. Path queries and new move orders go out once per `ARMY_EVERY_STEPS` per unit (staggered by tag) | §3 "squad micro every step"; §6 step budget |
| Observer | From 6:00 the army claims one Observer and pins it (the scout planner no longer keeps one back itself); it follows the ATTACK squad's main group while it is out | §4.3 "travels with the army" |
| End-game (§4.7) | "No enemy structure seen" = none in vision (snapshots don't count) for 60 s. Hunt points: every expansion, the map-analyzer region centres, the four corners (4 inside the playable area) and a 20-tile grid; free Observers take 8-point trips, a hallucinated Phoenix (existing Sentry only) takes the next points; the army's own hunt walks the ground points, and lifted Terran buildings become targets for units that can shoot up. "Behind" = our army value below the enemy's remembered army (ares's army cache: every enemy unit seen and not known dead): from 40:00 no attack launches then, not even at 190 supply | §4.7; the 30 s memory is too short for a whole-army comparison |

## M4 acceptance evidence

Acceptance (DESIGN.md §7 M4, user decision): at least 7/10 wins against the built-in VeryHard AI
for each race (Terran, Zerg, Protoss), 10 games each, the 7 pool maps cycled, `RandomBuild`. All
runs on commit d20f15b:

```
poetry run python scripts/run_matches.py --difficulty VeryHard --race Terran --map all --total 10
poetry run python scripts/run_matches.py --difficulty VeryHard --race Zerg --map all --total 10
poetry run python scripts/run_matches.py --difficulty VeryHard --race Protoss --map all --total 10
```

| Race | Wins | Losses | Game lengths | Main attacks (launch / retreat / recall) | Army value lost / killed |
|---|---|---|---|---|---|
| Terran | **10/10** | 0 | 10:12-13:17 | 13 / 1 / 2 | 28.9k / 53.8k |
| Zerg | **9/10** | 1 (Ultralove, 25:33) | 10:36-25:33 | 21 / 4 / 8 | 58.8k / 114.6k |
| Protoss | **10/10** | 0 | 11:12-14:23 | 12 / 1 / 1 | 28.3k / 88.1k |

**Result: PASS** (≥ 7/10 for each race). 0 crashes. The `M4 wins per race` summary line printed
PASS for each batch.

- The one loss (Zerg, Ultralove): our army traded evenly for 25 minutes (22.6k lost, 28.9k
  killed) against Mutalisks, Hydralisks, Ultralisks, Brood Lords, Swarm Hosts and Corruptors, and
  was recalled five times by runbys; the §4.5.1 air switch (more Stalkers / Archons against
  enemy air) is not built yet, and the vs-Z mix has no Archons (High Templar are cut).
- Before M4 (M3's code, commit 023a64d, 7 per race on the same maps): Terran 6/7, Zerg 3/6,
  Protoss 5/6 (19 games finished before a container restart). Its losses were the M1 army's
  pattern: attack at 150 supply used with ~74 army supply, lose half, retreat, repeat.
- Intermediate runs: M4's first army commit (ff19b9e) won 21/21 (7 per race); commit 5589a6c won
  Terran 10/10, Zerg 9/10, Protoss 10/10. The changes after it (home retreat, fogged Cannons, a
  Cannon target in its own guard) came from the cheese regression runs.
- Step time over the 30 games (4 games in parallel on 4 cores): mean 3.4-10.9 ms per game (average
  5.2), p99 18-55 ms (over 40 ms in 2 games), max 49-411 ms. The §6 step guard is M5's.

Other M4 checks on d20f15b:

| Check | Command | Result |
|---|---|---|
| Gates, hysteresis, relaunch wait, value rule, recall, §4.7 45:00 and 40:00 rules | `poetry run python scripts/test_attack_decision.py` | 16/16 |
| Citadel's EngagementResult in game | `poetry run python scripts/test_engagement.py` | PASS; same levels as the M4 findings table except "6 Stalkers + 2 Cannons (defending)" 8 (8-9) instead of 9 (8-9) (the simulator's one-level noise) |
| §4.7 structure hunt (thresholds shortened in the test) | `poetry run python scripts/test_endgame.py` | PASS: the Supply Depot found by the army's own hunt at 0:43 and destroyed at 0:49, the hunt on at 1:00, the lifted Barracks found during the hunt at 1:22, Victory |
| ThreatFlag expiry / M3 flag check | `test_threat_flags.py` / `test_m3_checks.py` | 20/20 / 13/13 |

Regression checks on d20f15b (the M4 army replaces the M1 army every earlier milestone relied on):

| Check | Command | Result |
|---|---|---|
| M2 acceptance + M3 flag/scout checks, 4 cheese bots × 10 | `poetry run python scripts/run_matches.py --opponent <bot> --map all --total 10 --seed 100` | worker rush 10/10, cannon rush 8/10 (Ultralove natural tied at 60:00, Pylon main lost at 9:53), 12-pool 10/10, proxy 10/10: M2 PASS (≥ 8/10 each); correct flag 40/40; no scout lost before 4:00 40/40 |
| M1 regression, Hard × 10 | `poetry run python scripts/run_matches.py --difficulty Hard --map all --total 10 --race Terran Zerg Protoss Random` | 10/10 wins; 44+ probes at 6:00 in 8/10 (41 in two Pool-first Zerg games, as in M3) |
| Ladder zip | `poetry run python scripts/create_ladder_zip.py`; `unzip -l publish/*.zip` | 378 files, 5.5 MB; `run.py`, `ladder.py`, `config.yml` at the top level; `ares-sc2/sc2_helper` (the simulator) included |

Two container restarts cut the worker-rush, 12-pool, proxy and Hard batches short (every game
they had finished was won); they were rerun in full with `run_matches.py`'s new per-game `ROW`
lines (and `--start` to finish a batch cut short). Cannon rush: M3 won 10/10 on the same seeds; the
three M4 fixes from these runs are in "M4 Citadel choices" (level 7 against rush Cannons with the
units around them, fogged Cannons counted, a Cannon target in its own guard).


## M5 findings

Found while building M5 (counterattack, opponent memory, telemetry, step guard). Source lines are
for the versions at the top of this file.

**ares's army cache holds each enemy unit's last observation (§4.6 "seen within the last 15 s").**
`UnitCacheManager.store_enemy_unit` (`ares-sc2/src/ares/managers/unit_cache_manager.py:281-327`)
replaces a seen-before unit's entry with this step's `Unit` object (old entry removed through
`enemy_tags_to_remove`, new one added in `update_enemy_army`, `:329-342`); a morphing Zerg unit
(`DOES_NOT_USE_LARVA`, Hellion tank) is re-added from `ai.unit_tag_dict`, which ares fills with
every unit of the step, own, enemy and neutral (`ares-sc2/src/ares/main.py:251`). So for a cached
unit `unit.age` (`sc2/unit.py:471-473`: current loop minus the observation's loop, / 22.4) is the
time since it was last seen. The cache also holds enemy workers (added before the worker check,
`unit_cache_manager.py:303-310`); Citadel filters it with `is_fighter`.

**Ground path lengths (§4.6 "ground path distance").** `mediator.find_raw_path(start=, target=,
grid=, sensitivity=)` (`ares-sc2/src/ares/managers/manager_mediator.py:1315`) runs map-analyzer's
`pathfind` (`map_analyzer/Pather.py:348-390`): start and goal are rounded and moved to the nearest
pathable point within 10, the start point is left out of the result, and it returns None when
there is no path. **Runtime** (probe game, PylonAIE_v4): map centre to the enemy main, 69 points,
length 85.6 against 70.1 in a straight line, 0.7 ms. Citadel uses the clean ground grid
(`get_cached_ground_grid`, §11.6) so influence doesn't lengthen paths.

**Debug commands in a bot-vs-bot game.** **Runtime** (probe with two python-sc2 bots hosted by
`_host_game`/`_join_game`, as `run_matches.py --opponent` does): `debug_create_unit` from the host
creates units for either player, `debug_show_map` works, and the other bot sees and orders the
units created for it. `scripts/test_counterattack.py` relies on this. Leaving a game with
`client.leave()` sometimes ends the other side with `ConnectionAlreadyClosed`.

**`opponent_id` and `./data`.** python-sc2 keeps an `opponent_id` set before the game
(`sc2/bot_ai_internal.py:83-87` sets None only if the attribute is missing); the template's
`ladder.py:42` sets it from `--OpponentId`. ares names its data file from it
(`ares-sc2/src/ares/managers/data_manager.py:99-101`) under `ares.consts.DATA_DIR = "./data"`
(`consts.py:106`), relative to the working directory; Citadel's files use the same base.

**Destroyed enemy structures.** python-sc2 keeps last step's enemy structures in
`_enemy_structures_previous_map` (`sc2/bot_ai_internal.py:699`), so `on_unit_destroyed` can tell
what was destroyed (the counterattack's kills).

**Startup.** `on_start` took 0.7-1.6 s in the M5 test games (§6's limit is 5 s).

**An opener's `expand` step only finishes when a Nexus starts.** ares parses `expand` as a step
whose command is `base_townhall_type` (Nexus), started once minerals reach 285 for Protoss, and
whose end condition is a Nexus at 0-5% progress (`ares-sc2/src/ares/build_runner/build_order_parser.py:113-125`).
The runner moves past a step only when `set_step_complete` is called from
`on_building_construction_started` (`ares-sc2/src/ares/main.py:577`) or the end condition holds
(`build_order_runner.py:474-476`), and a Protoss structure's probe is sent one supply early once
its start condition holds (`build_order_runner.py:290-298`). So a Nexus order the defense plan
drops (`static_defense.py` `_retarget_builds`) leaves the opener waiting at that step until
`OPENER_TIMEOUT_S`; Citadel ends the opener there when only a pre-raised POOL_12 holds expansions
(below).

## M5 Citadel choices

Where §4.6, §5, §6 and §8 leave a choice open, M5 decided as below. Every value is in
`bot/constants.py`.

| Area | Choice | Why |
|---|---|---|
| Scope (user decisions) | Pre-raised flags act like the same flag raised in game, including ending the ares opener (WORKER_RUSH, PROXY, Cannon-structure CANNON_RUSH; POOL_12 changed after the acceptance runs, see "Pre-raised POOL_12" below); cheese for the pre-raise = WORKER_RUSH, CANNON_RUSH (not the weak Forge-first source), POOL_12, PROXY and ONE_BASE_ALLIN; a pre-raised WORKER_RUSH ends after 2:30 with ≤ 1 enemy worker near our bases (§5 gives it no phase rule); inside the counterattack target, what can fight back first, then workers, production, townhall; the 30 games = 10 VeryHard per race, each batch with a local opponent id; recall also when the enemy army heads back, and no launch that a recall rule would end at once (below) | Plan approval; the last two after the staged test and the first 30-game run below |
| Remembered army (§4.6 1) | ares's army cache (every enemy fighter seen and not known dead), as for §4.7 in M4; "seen within 15 s" = the cached observation is ≤ 15 s old | §11.2: the 30 s memory is too short for a whole army |
| Army centre (§4.6 2) | Value-weighted centre of the units seen within 15 s only | Up to 40% of the value can be minutes old and would pull the centre to where units used to be |
| Path distance (§4.6 2) | The straight line where it is already ≥ 60 (a path is never shorter); otherwise `find_raw_path` on the clean ground grid, cached per 4-tile cell; the straight line if there is no ground path | §6 "cache pathing results"; 0.7 ms per query |
| Known enemy bases | Enemy townhalls seen (snapshots too); the enemy start location if none has been seen | §4.6 "known enemy townhall" |
| Launch | Only on an evaluation that finds the army out of position now; the flag's 15 s TTL (§5) keeps it active for the logs | A flag up to 15 s old shouldn't send a squad |
| Target (§4.6) | Condition 3 as a filter (bases with ≤ 25% of the enemy army within 25), then the lowest local defence value: remembered army value within 20 plus static defence within 15 counted as Stalkers' value (Cannon, Bunker, Spine Crawler 3; Planetary Fortress 8, §4.5.2's penalty; Shield Battery 1, Citadel); ties to the base farther from the enemy army | §4.6 "static defense penalty plus remembered units", in one unit (resource value) |
| Squad (§4.6) | Adepts, Zealots with Charge, then Stalkers (no other type), nearest the target first within a type, from DEFEND units that aren't retreating; cap 35% of our fighting units' supply, minimum 8 | §4.6 order; units the defense plan pins are never in a squad (M4) |
| Home check (§4.6 4 and the defense recall) | A home threat blocks a launch, and recalls the squad, when the DEFEND units left at home read < DEFEND_ENGAGE against the enemies around it (static defence included, we defend) | "the defense planner reports that it can hold" |
| Recall: "the enemy army" | The out-of-position army's units at launch (their tags): the value-weighted centre of those seen within 15 s (all of them if none) | Defenders seen at the target would otherwise read as "the enemy army at the target" |
| Recall: heading back (user decision) | Besides §4.6's 35 of the target / 20 of the squad, recall once the out-of-position army's centre is `COUNTER_RECALL_HEADING_BACK` (20) closer to the target by ground path than it was at launch (both measured by path, not the straight-line shortcut) | Staged `return` case on TorchesAIE_v4: the natural's only exit faces the returning army; recalled at 35 (nearest enemy unit 30 away) the squad lost 6, 7 and 5 of its 7 units on the way home in three runs; retreating without shooting changed nothing (5 lost); recalling at 60 or on heading back brought 7/7 home on Torches and Pylon, recalled about 7 s after the army turned |
| No launch a recall would end (user decision) | No launch while the enemy army's centre is already within 20 of the squad or 35 of the target (`recall_at_launch`); §4.6 condition 4 allows a launch while the enemy army is at our base, but its "within 20 of the squad" recall then fires at once | First 30-game run (commit eb06fe4): 3 of 5 real counterattacks were launched and recalled within 1 s, the enemy army having counted as out of position while it stood near our base |
| Recall: target cleared | Also recall when no known enemy structure and no visible enemy worker is left within 14 of the target | Nothing left to kill |
| Relaunch wait | 30 s after a counterattack ends | A squad recalled after 60 s would turn round at once |
| Cadence | Every 16 steps, 8 steps after the main attack decision; ≤ 2 simulations per evaluation (launch: home check + squad level; out: squad level + home check) | §3 "≤ 2 sims each"; spreads the simulator calls |
| Step guard (§6) | Skips the scout planner, the counterattack's detection and launch (recall checks keep running), and the telemetry snapshots (4:00-10:00 and 30 s) for 16 steps; every step over 30 ms is logged with the parts that took ≥ 2 ms | Defense keeps priority; detection holds the path queries |
| Opponent memory (§5) | `threats_seen` entries also carry the game number and the detector source; one entry per (threat, source) per game with its first raise time; the last 20 games kept; `first_aggression_time` = the earliest over all games; flags pre-raised from memory are never recorded; Cannon flags from an enemy probe alone (`cannon_probe`) don't count toward the pre-raise either (Citadel's addition to the user's Forge-first decision); an id is reduced to letters, digits, `_`, `-`, `.` before it names a file; no id → no memory; an unreadable file → a fresh record | "Last 3 games" needs game numbers; a pre-raise must not keep itself going; M2 already doesn't let a probe alone end the opener |
| Game log (§8) | `./data/logs/games.jsonl`, one JSON line per game (also `METRIC game` on stdout), the last 200 games; the oldest lines are dropped first if `./data` would pass 4.5 MB; lists capped at 100 entries; written atomically | §2 keeps `./data` under 5 MB |
| Pre-raised POOL_12 (user decision after the A/B below) | A POOL_12 flag from memory applies its plan from 0:00 (no Nexus, the main Battery, 2 Gateways, Zealot then Adepts, the wall gap held) but leaves the opener running (`MEMORY_KEEPS_OPENER`); the same flag raised in game ends it as before, and otherwise it ends when the opener reaches its `expand` step (`DefensePlanner._end_opener_at_expand`), which the plan holds and which would stall (finding above) | Option B of three put to the user (keep; keep the opener; change the fallback build). In every no-memory 12-pool game the in-game flag ended the opener at that same step (step 4, 1:08-1:13) |
| Opener essentials' gas (M2 code) | The two Assimilators in `OPENER_ESSENTIALS` wait until a Gateway is placed (`gateway_started`, at most until 1:30), as in every opener | A flag pre-raised from memory ends the opener at 0:00, and the essentials then took both gases at 0:10-0:16 before the first Pylon: against the 12-pool bot (pre-raised POOL_12, Pylon, seed 105) a 31 s supply block (0:18-0:49), the Gateway at 0:57, 14 probes and no army at 6:00 (a loss); replayed with the fix: a 13 s block (0:19-0:32, as in the openers), Gateway 0:33, gas 0:41, 35 probes and 24 army supply at 6:00 |
| Proxy check settle time (M3 code) | §4.4 rows 7/10 wait `PROXY_CHECK_SETTLE_S` (3 s) after the enemy main counts as scouted | With CANNON_RUSH pre-raised, the opener's scouting step never runs and the scout planner's probe reached the cannon rusher's main earlier: the main counted as scouted at 1:35 and its Forge came into vision at 1:36, after row 10 had raised a false PROXY (M3's Forge exception, row 3, comes too late); seen in both pre-raised cannon-rush games (d24ba02 and 5555cfa) |
| Writes | Every file write goes through `bot/data_files.py`, which refuses any path outside `./data` | §2 |
| Test hook | `CitadelBot.external_tags`: units a dev test drives itself are held like the wall-gap holder; always empty in games | `scripts/test_counterattack.py`'s Observer over the enemy army |
| M3 flag check | ARMY_OUT_OF_POSITION is allowed in every game (`M3_ALWAYS_ALLOWED`) | It says where the enemy army is, not which cheese it is |

## M5 acceptance evidence

Acceptance (DESIGN.md §7 M5): the counterattack triggers and recalls correctly in at least 3
staged tests; no crash in 30 local games (user decision: 10 VeryHard games per race, each batch
with a local opponent id so opponent memory and telemetry are written and read in every game).
Final code: commit 8c00b0a, which is 2f082d0 plus the pre-raised POOL_12 change (user decision
after the A/B below; it acts only when POOL_12 is pre-raised from memory and is tested in its own
section). Every other run below is on 2f082d0 unless it says otherwise.

**Staged counterattack tests** (`scripts/test_counterattack.py`, 7 cases against a scripted Terran,
see the file's docstring for the setup), on two maps:

```
poetry run python scripts/test_counterattack.py --case all --map PylonAIE_v4
poetry run python scripts/test_counterattack.py --case all --map TorchesAIE_v4
```

| Case | What happens | PylonAIE_v4 | TorchesAIE_v4 |
|---|---|---|---|
| `return` | the enemy army walks back to the target once the squad is near it | PASS: recall "enemy army heading back: 101 from the target by ground, 126 at launch"; 7/7 home after 18 s | PASS: heading back (73 vs 97); 7/7 home after 22 s |
| `timeout` | the enemy army stays away | PASS: recall "out for 60.0 s > 60 s"; 6 SCVs killed, first kill an SCV; 7/7 home after 20 s | PASS: same; 6 SCVs, first kill an SCV; 7/7 home after 22 s |
| `defense` | 16 Marauders, 12 Marines, 3 sieged Tanks appear in our main 15 s after launch | PASS: recall "defense: home threat at (69, 172), home level 1 < 4"; 7/7 home after 9 s | PASS: same; 7/7 home after 11 s |
| `abort` | 10 Marauders and 3 sieged Tanks appear at the target as the squad nears it | PASS: recall "level 3 <= 4"; 6/7 home (1 lost after the recall) | PASS: "level 1 <= 4" 4 s after they appeared; 6/7 home (1 lost before the recall) |
| `merge` | the main attack's supply gate is lowered once the squad is out | PASS: "merged into the main attack (7 units)", squad in the ATTACK squad | PASS: same |
| `in_position` (negative) | the enemy army waits next to its natural | PASS: no flag, no launch (detector: "centre 16 from an enemy base") | PASS (centre 10) |
| `early` (negative) | real COUNTER_FROM_S (5:00) | PASS: no flag, no launch, no detector run before 5:00 | PASS |

Summary lines: `CHECK SUMMARY trigger+recall cases passed: 4/4; merge: PASS; in_position: PASS;
early: PASS` on both maps. In every positive case ARMY_OUT_OF_POSITION was raised at 0:31-0:32
(enemy army value 1600, 81% seen within 15 s, centre 79-103 from the nearest enemy base) and the
counterattack launched at once against the enemy natural (defence 0; the main has 2 Bunkers and 6
Marines) with 6 Adepts and 1 Stalker: 14 of 40 army supply, the 35% cap, Adepts first, no
Immortals, not the test's held Observer. **Result: PASS** (4 trigger-and-recall cases out of the
≥ 3 needed, on each map; the merge and both negative cases pass too). The two tracebacks in each
log are python-sc2's `ConnectionAlreadyClosed` after the test leaves the game; the harness keeps
the verdict (`CHECK case ...: (connection closed after leaving ...)`). The same 7/7 on both maps on
d24ba02.

Offline, on the same code:

| Command | Result |
|---|---|
| `poetry run python scripts/test_counterattack_rules.py` | 36/36 (squad, target, every recall rule including heading back, the launch block) |
| `poetry run python scripts/test_opponent_memory.py` | 38/38 (memory file, pre-raise rule, `./data` boundary, game log bounds) |
| `poetry run python scripts/test_step_guard.py` | PASS (a 250 ms step at 640 turns the guard on for steps 641-656: no scout planner, the counterattack tick runs guarded, no snapshots; all back after) |
| `poetry run python scripts/check_game_log.py` | 200 games (the 200 cap reached), 300 KB, 0 malformed; all of `./data` 372 KB (limit 4.5 MB): PASS |
| `test_m3_checks.py` / `test_threat_flags.py` / `test_attack_decision.py` | 14/14 / 20/20 / 16/16 |

**30 local games:**

```
poetry run python scripts/run_matches.py --difficulty VeryHard --race Terran --map all --total 10 --opponent-id m5z-vh-terran --game-seed 3000
poetry run python scripts/run_matches.py --difficulty VeryHard --race Zerg --map all --total 10 --opponent-id m5z-vh-zerg --game-seed 3000
poetry run python scripts/run_matches.py --difficulty VeryHard --race Protoss --map all --total 10 --opponent-id m5z-vh-protoss --game-seed 3000
```

(three batches in parallel; after a container restart each was resumed with `--start N`, so the
summary lines printed at the end cover games N-10; the table counts all ten `ROW` lines.)

| Race | Crashes | §8 log line written | Wins (M4 bar ≥ 7) | Counterattacks (how they ended) | Pre-raised |
|---|---|---|---|---|---|
| Terran | **0** | 10/10 | 10/10 | 2 (enemy army within 20 of the squad; defense: home level 1) | none |
| Zerg | **0** | 10/10 | 9/10 (Ley Lines 10:48) | 4 (level 2 after killing 7 workers and 6 units for 1050 value; heading back, 1 unit killed; enemy army within 20 of the squad ×2) | POOL_12 in 4 games (5, 6, 9, 10) |
| Protoss | **0** | 10/10 | 10/10 | 2 (enemy army within 20 of the squad ×2) | none |

**Result: PASS** (0 crashes in 30 games; every `ROW` has `log=ok`; each batch's summary line reads
`M5 no crash: N/N games without a crash, §8 log line written N/N ...: PASS`).

- Every game's record was found by its game id in `./data/logs/games.jsonl`; the file has held
  its 200-game cap since the cheese batches below (the oldest local test games dropped first).
- Opponent memory: each batch's record (`./data/opponents/m5z-vh-<race>.json`) has 10 games. The
  Zerg one saw POOL_12 in games 3 and 4 and pre-raised it in games 5 and 6; with POOL_12 not raised
  in game 5 or 6 (both pre-raised, which isn't recorded) the last three games no longer had it in
  two, so games 7 and 8 started without it; they raised it again and games 9 and 10 pre-raised it
  (`MEMORY ... recurring cheese {'POOL_12': 2}` / `none` lines).
- Step time over the 30 games (3 batches in parallel with a cheese batch): mean 3.1-7.6 ms per
  game, p99 13-50 ms (over 40 in 2 games), max 86-468 ms; the step guard turned on 13 times in 7
  games; startup 0.56-3.6 s (§6: 5 s).
- Counterattacks: 8 in 30 games. One did what §4.6 is for (Zerg game 7: 3 Adepts and 9 Stalkers
  at the enemy third at 9:03, 7 workers and 6 units killed, recalled at level 2 after 40 s, 6 of 12
  home); one was recalled when the army turned home (heading back, 27 s out); one by the defense
  rule (1 s out, an attack on our base); the other five by "enemy army within 20 of the squad"
  after 1-16 s: the enemy army was 60-68 from its bases, just past the threshold, and on the
  squad's way (see "Known issues" in `docs/STATUS.md`).

The Zerg loss (Ley Lines, game seed 3002) is the same game lost on d24ba02 (10:15) and 5555cfa
(11:34): a Pool-first Zerg (POOL_12 at 1:12), then a Roach/Ling attack we never engage
(`engage=0/0/0`); M4's code lost the Ley Lines game of the A/B below too.

**Regressions** (`--seed 100 --game-seed 5000`, each with its own opponent id so the pre-raise is
exercised from game 3 on):

```
poetry run python scripts/run_matches.py --opponent <bot> --map all --total 10 --seed 100 --game-seed 5000 --opponent-id m5z-<bot>
poetry run python scripts/run_matches.py --difficulty Hard --map all --total 10 --race Terran Zerg Protoss Random --game-seed 6000
```

| Batch | Wins (M2 bar ≥ 8/10) | Correct flag (M3) | Crashes / log lines | Pre-raised | Notes |
|---|---|---|---|---|---|
| worker rush | 10/10 | 10/10 | 0 / 10 | WORKER_RUSH from game 3 (8 games) | raised in game at 0:35-0:45 too; 42-55 probes at 6:00 in the pre-raised games, 33 in games 1-2 |
| cannon rush | 8/10 | 10/10 | 0 / 10 | CANNON_RUSH from game 3 (8 games) | lost the main variant on Ley Lines (10:00) and Pylon (11:33), both pre-raised; see below |
| 12-pool | 9/10 | 10/10 | 0 / 10 | POOL_12 from game 3 (8 games) | lost Pylon game 5 (10:55); see below |
| proxy rax | 10/10 | 10/10 | 0 / 10 | PROXY + ONE_BASE_ALLIN from game 3 (8 games) | the pre-raised games stay on one base until ONE_BASE_ALLIN's phase end at 7:00 (the proxy bot never takes a natural); in games 1-2 the in-game flags came at 1:30-2:38, after the opener had placed the natural: 28-39 probes at 6:00 against 54-55, wins in 11:18-13:54 against 8:49-9:23 |
| Hard × 10 (T/Z/P/Random) | 10/10 | — | 0 / 10 | — | 10 counterattacks (7 ended by the enemy army within 20 of the squad, 1 heading back, 1 merged into the main attack, 1 defense; none killed anything); 44+ probes at 6:00 in 6/10, the four under 44 (39-42) all Pool-first Zerg with POOL_12 at 1:10-1:14 |

No scout was lost before 4:00 in the 40 cheese games (`scouts=0/...` in every `ROW`).

**Do the pre-raised flags cost the two losses?** Both cheese losses above had the flag pre-raised
at 0:00, so each game was replayed on the same seeds with and without memory (a copy of the
batch's opponent file under a new id, or no id):

```
poetry run python scripts/run_matches.py --opponent cannon_rush --map all --start 3 --total 3 --seed 100 --game-seed 5000 [--opponent-id <copy>]
poetry run python scripts/run_matches.py --opponent twelve_pool --map all --start <N> --total <M> --seed 100 --game-seed 5000 [--opponent-id <copy>]
```

- Cannon rush, game 3 (Ley Lines, main variant): won with the pre-raise (10:08, 52 probes at 6:00)
  and without it (10:05, 47 probes; CANNON_RUSH raised in game at 0:47 on the rusher's first
  Pylon). The same game was lost on d24ba02 and 2f082d0 and won on 5555cfa, all pre-raised: the
  main variant is close (M2's known pattern), and the pre-raise only moves the plan 47 s earlier.
- 12-pool: all 10 games again without memory (four `--start/--total` slices in parallel): **10/10
  wins**, POOL_12 raised in game at 1:08-1:13, army supply 12-19 and 0-2 probes lost at 4:00 in
  every game. With POOL_12 pre-raised (games 3-10 of the batch, and two replays of game 5): 8 of 9
  finished games won, and 3 of 10 starts were weak at 4:00 (army supply 4, 6 and 8 with 5-8
  probes lost: games 5 and 7 of the batch and the first game 5 replay, which a container restart
  stopped at 15:00); the other 7 had 12-18 and 0-2. Probes at 6:00: 28-42 without memory, 19-43
  with it. In the weak starts the opener had ended at 0:00 and the essentials put the Gateway at
  0:33 and both gases at 0:41 (20 minerals banked at 1:00 against 230 while the opener runs to
  1:12), and the main Battery needed a Pylon of its own, placed at 2:27 next to the wall, whose
  builder died to Zerglings. **The pre-raise as decided (it ends the opener) makes the 12-pool
  defense less reliable**; the M2 bar still holds (9/10). Put to the user with three options; they
  chose to keep the opener running (next section).

**Pre-raised POOL_12 that keeps the opener (8c00b0a).** Every game started with POOL_12 pre-raised
(each lane's opponent id began as a copy of the 12-pool record, `{'POOL_12': 3}`; the VeryHard
Zerg games used a fresh copy per game, so the pre-raise held in all ten), same seeds as above:

```
poetry run python scripts/run_matches.py --opponent twelve_pool --map all --start <N> --total <M> --seed 100 --game-seed 5000 --opponent-id <copy>
poetry run python scripts/run_matches.py --difficulty VeryHard --race Zerg --map all --start <g> --total <g> --game-seed 3000 --opponent-id <copy-g>
```

| Batch | Wins | Opener ended | 4:00 army supply / probes lost | Probes at 6:00 | Crashes / log lines |
|---|---|---|---|---|---|
| 12-pool, POOL_12 raised in game (2f082d0, no memory) | 10/10 | 1:08-1:13, step 4, by the in-game flag | 12-19 / 0-2 | 28-42 | 0 / 10 |
| 12-pool, pre-raised, opener ended at 0:00 (2f082d0) | 8/9 finished | 0:00 | 4-8 / 5-8 in 3 of 10 starts, 12-18 / 0-2 in the rest | 19-43 | 0 / 9 |
| **12-pool, pre-raised, opener kept (8c00b0a)** | **10/10** | 1:07-1:08, step 4, at its expand step | **14-23 / 0-1** | 33-43 | 0 / 10 |
| VeryHard Zerg, pre-raised in every game (8c00b0a) | 9/10 (Ley Lines seed 3002, lost on every M5 commit) | 1:07-1:08, step 4 | 20-25 / 0 | 29-43 | 0 / 10 |

In all 20 games the log shows `FLAG raise POOL_12 (STRUCTURE, memory) at 0:00` without
`[ends opener]`, the opener's Pylon, Gateway, worker scout and first gas, then `OPENER ended at
01:07 (step 4) by POOL_12 (memory): its expand step, which the plan holds`, and the main Battery
at 2:20-2:25. **Result:** the pre-raise no longer weakens the 12-pool defense (10/10, every start
steady at 4:00). Against VeryHard Zerg, which doesn't 12-pool every game, the pre-raise still costs
economy (29-43 probes at 6:00 against 40-65 without it in the 30-game run; the plan holds the
natural until 3 units and no Zerglings near) and the wins take longer (12:43-15:12), as on
2f082d0 (39-42 probes in its four pre-raised games). WORKER_RUSH, PROXY, CANNON_RUSH and
ONE_BASE_ALLIN pre-raises are unchanged. Offline tests on 8c00b0a: 38/38, 36/36, 20/20, 14/14,
16/16; the ladder zip rebuilt (386 files, 5.5 MB, `MEMORY_KEEPS_OPENER` in its `bot/constants.py`).

**Step times in the cheese batches.** The 12-pool, proxy and worker-rush batches ran 5 at a time
with the Hard batch and the staged suites, four of the five bot-vs-bot (two SC2 clients each, and
both bots in one Python process: `run_matches.py` runs them with `asyncio.gather`), on 4 cores.
They logged 28-49 steps over 200 ms per batch (max 1.4-2.1 s) against 1-12 per batch in the other
runs; the slow steps fell in every section (ares 39 of the steps over 300 ms, macro 23, micro 14,
scouts 4, worker defense 3, army 2, intel 1), at any game time, which points at the shared machine
rather than one code path. The step guard turned on each time and the games went on normally. On
the ladder each bot runs in its own process; M6's first games give the real numbers.

**Ladder zip** (`poetry run python scripts/create_ladder_zip.py`, then `unzip -l publish/*.zip`):
`publish/Citadel.zip`, 386 files, 5.5 MB; `run.py`, `ladder.py`, `config.yml` and
`protoss_builds.yml` at the top level; `sc2_helper` included; no `data/` folder.

Earlier runs on superseded commits (same 30-game commands, other opponent ids; the first without a
game seed):

| Commit | Change after it | Games | Crashes | Log lines | Terran | Zerg | Protoss |
|---|---|---|---|---|---|---|---|
| a2da122 | the two recall/launch decisions | 29 | 0 | 29/29 | 10/10 | 6/10 | 9/9 (a restart stopped game 10) |
| eb06fe4 | the launch decision | 27 | 0 | 27/27 | 9/9 | 7/9 | 9/9 (a restart stopped the batches) |
| d24ba02 | essentials' gas waits for a Gateway | 30 | 0 | 30/30 | 10/10 | 8/10 | 10/10 |
| 5555cfa | proxy check settle time | 30 | 0 | 30/30 | 10/10 | 9/10 | 9/10 |

**Zerg A/B, M4 vs M5 code.** The first 30-game run (a2da122) went 6/10 against VeryHard Zerg (M4:
9/10): four early losses on one base to a Pool-first, then Roach/Zergling attack at 4:00-5:00. To
tell code from chance, the same 10 games were played on M4's final code (e345c04, a separate
worktree) and on M5's (d24ba02) with the game's random seed fixed (`--game-seed 2000`, new in M5),
the opener forced (`--opener B_PvZ`) and no opponent id:

```
poetry run python scripts/run_matches.py --difficulty VeryHard --race Zerg --map all --total 10 --opener B_PvZ --game-seed 2000
```

| Game | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | Wins |
|---|---|---|---|---|---|---|---|---|---|---|---|
| M4 (e345c04) | W | L 27:25 | L 11:44 | W | W | W | W | W | W | W | 8/10 |
| M5 (d24ba02) | W | W | L 7:01 | W | W | W | W | W | W | W | 9/10 |

Same outcome in 9 of 10 games; the one difference is a 27-minute M4 loss that M5 won. M5's code
doesn't weaken play against VeryHard Zerg: the earlier 6/10 came from the AI's random builds (all
four losses met the 4:00 Roach attack, which also beats M4 in game 3) and from ares cycling openers
afresh under a new opponent id (B2_PvZSafe in 8 of those 10 games); all four losses were holding
against Roaches at 4:05-4:17. The POOL_12 plan against a Pool-into-Roach build is in "Known
issues" (`docs/STATUS.md`).

## M6 findings

Found while preparing the upload (M6). Sources: the arena client's source
(`aiarena/sc2-ai-match-controller`, `main` at `88b3204`, 2026-09-28; the `v0.8.0` images that
`aiarena/local-play-bootstrap` uses have no git tag, so the exact commit behind them is not
confirmed) and the `aiarena/arenaclient-bot:v0.8.0` image.

**The ladder's bot image.** `aiarena/arenaclient-bot:v0.8.0`: Python 3.12.12
(`/usr/local/bin/python`), Debian 12 with glibc 2.36; it carries numpy 2.0.2, scipy 1.17.0,
scikit-learn 1.8.0, scikit-image 0.26.0, loguru 0.7.3, aiohttp 3.13.3, protobuf 6.33.4,
s2clientprotocol, PyYAML 6.0.3, burnysc2 7.1.3 and others (`pip list` in the image). The zip's own
`sc2/` folder comes first on `sys.path` (`python run.py` puts `/bot` first), so the image's
burnysc2 is not used. The zip's compiled files need glibc 2.34 at most (`objdump -T`:
`sc2_helper` 2.34, `cython_extensions` and `map_analyzer` 2.14).

**How the bot is started** (`bot_controller/src/main.rs`): `python run.py --GamePort <port>
--LadderServer <host IP> --StartPort <pass port> --OpponentId <id>` with `/bot` as the working
directory (so `./data` is `/bot/data`); stdout and stderr go to `/bot/logs/stdout.log` and
`/bot/logs/stderr.log`. The template's `ladder.py` reads all four arguments and honours
`--LadderServer` (§9 risk 5).

**What the ladder scores as Crash or TimeOut** (`sc2_controller/src/websocket/player.rs`,
`game/game_config.rs`, `game/game_result.rs`):
- `timeout_secs: 30` (`game_config.rs:58`): every request the bot sends must come within 30 s of
  the previous response (`player.rs:45`, `:287`), from the join request on, so `on_start` and every
  step count; a miss is `PlayerNTimeOut` (`player.rs:407-416`, `game_result.rs:95-96`).
- The bot's websocket closing or an unexpected message is `PlayerNCrash` (`player.rs:375-399`).
  python-sc2 re-raises any exception from `on_step` and leaves the game
  (`sc2/main.py:158-166` in the venv's python-sc2), so one unhandled error in a step loses the
  game as a Crash; an exception in `on_start` is caught and logged (`sc2/main.py:140-144`).
- `max_frame_time: 40` is stored (`game_config.rs:8`, `:57`) and read nowhere; there is no strike
  count in the source (local-play-bootstrap's `config.toml` still lists `MAX_FRAME_TIME = 40` and
  `STRIKES = 10`). The controller only records the average step time (`runtime_vars.rs:48-53`).
  This matches §6 ("documented but not enforced").
- `max_game_time: 80640` loops ends the game as a Tie (`player.rs`, "Max time reached"), §4.7.
- `disable_debug: true`: debug requests get an empty response and never reach the game.

**The template's zip carried other library versions than the tested ones.**
`scripts/create_ladder_zip.py` cloned the default branch of each library at build time, while the
Poetry environment every local test ran in has the versions `poetry.lock` pins:

| Library | Tested (Poetry environment) | In the zip before M6 |
|---|---|---|
| python-sc2 | `august-k/python-sc2` `develop` @ `7ec25cf` | `august-k/python-sc2` default branch: `Units.__call__` needs an argument, `query_available_abilities_with_tag` gets `self.units`/`self.structures`, other typing changes |
| map-analyzer | `spudde123/SC2MapAnalysis` `develop` (0.2.0) | `raspersc2/SC2MapAnalysis` default branch: no `CREEPTUMORQUEEN`/`CREEPTUMORBURROWED` in the pathing blockers, no `DESTRUCTIBLEEXPEDITIONGATE6X6` |
| cython-extensions-sc2 | 0.17.0 (PyPI manylinux wheel) | 0.18.0, built from source (its build step also reinstalled the Poetry environment's copy until `poetry install` put 0.17.0 back) |

M6 changes the script to copy `sc2`, `map_analyzer` and `cython_extensions` from the Poetry
environment's site-packages (`installed_package_dir`, `SITE_PACKAGES_LIBRARIES`), and leaves
`__pycache__` folders out. The template's GitHub Action runs `poetry install` first, so it zips the
locked versions too.

**Import time in the bot image.** Importing the unzipped bot (`from bot.main import CitadelBot`
plus `sc2`, `map_analyzer`, `cython_extensions`, `sc2_helper`) took 1.4-1.5 s warm and 15.5 s on
the first run after a machine restart (cold disk cache).

**ares's behaviors after a failure** (`ares-sc2/src/ares/behavior_exectioner.py:51-61`):
`BehaviorExecutioner.execute` runs every registered behavior and only then empties its list, so a
behavior that raises leaves the list in place and the next step would run all of it again
(behind the new ones). python-sc2 runs `issue_events` (the `on_unit_*`/`on_building_*` hooks)
before `on_step` and ares's `_after_step` (`ares-sc2/src/ares/main.py:437-451`: behaviors,
drop/archon/placement actions, grid reset, warp-ins, then python-sc2's `_after_step`, which sends
the step's actions, `sc2/bot_ai_internal.py:856-875`) after it, both outside the `on_step` try
(`sc2/main.py:153-167`). ares refills its other per-step action lists at the start of each step
(`ares-sc2/src/ares/main.py:853-856`).

**The arena client in practice** (runtime, `scripts/ladder_env_test.py`):
- The proxy comments out each `matches` line it has played (`#1,Citadel,...`), so a rerun of
  the same file plays nothing.
- `results.json` entries hold `type` (`Player1Win`, `Player2Win`, `Tie`, `Player1Crash`,
  `InitializationError`, ...), `game_steps` and `bot1_avg_step_time`/`bot2_avg_step_time`
  (seconds; 0.0044-0.0071 for Citadel in the first runs).
- Each bot's output is in `logs/bot_controller<seat>/<bot name>/stderr.log`; Citadel's `./data`
  is `bots/Citadel/data`, which stays between matches as the ladder's bot data does.
- `--OpponentId` is the opponent's ID column in `matches`.
- A bot that dies before joining gives `InitializationError` for the match, whichever bot it was.
- The port picker of both the proxy and the sc2 controller binds every candidate port on IPv6 and
  IPv4 (`common/src/utilities/portpicker/mod.rs` at tag v0.6.10; the v0.8.0 binary carries the
  same "Could not allocate port" message), so on a kernel without IPv6 (this container) the sc2
  controller answers "Could not allocate port" and the proxy panics setting up the game's port
  config.
- The template's `ladder.py` uses `sc2.portconfig` without importing it: it works for Citadel
  because `run.py` imports `sc2.main` first; a bot whose `run.py` doesn't fails with
  `AttributeError: module 'sc2' has no attribute 'portconfig'`.

**The AI Arena API** (`aiarena/aiarena-web` at `c5edb81`, `aiarena/api/`): token auth
(`Authorization: Token <token>`, from the profile's token page) for every endpoint;
`PATCH /api/bots/<id>/` takes `bot_zip`, `bot_zip_publicly_downloadable`, `bot_data`,
`bot_data_publicly_downloadable`, `bot_data_enabled`, `wiki_article_content`
(`views/serializers.py:167-181`), the zip validated by the bot model; `GET /api/bots/<id>/` reports
`bot_data_enabled`, `bot_zip_updated` and `bot_zip_md5hash` (`views/include.py:1-17`);
`GET /api/match-participations/?bot=<id>` gives `match`, `result` (win/loss/tie/none),
`result_cause` (game_rules, crash, timeout, race_mismatch, match_cancelled,
initialization_failure, error), `avg_step_time` and `match_log`
(`core/models/match_participation.py:18-49`; a "crash" in AI Arena's own terms is a loss caused by
crash, timeout or initialization_failure, `:71-72`); `/api/match-participations/<id>/match-log/`
downloads the bot's log for the bot's owner only (`:122-123`); lists are paged 100 at a time
(`aiarena/settings/default.py:161-162`).

## M6 Citadel choices

| Area | Choice | Why |
|---|---|---|
| Error guard (user decision) | Every part of `on_step` (ares's step, mining, opener timeout, bridge, detectors, flag expiry, defense planner, scouts, worker defense, static defense, Gateway upkeep, defense behaviors, chrono, macro plan, wall, army, endgame, micro, telemetry, step time), ares's after-step, the event hooks ares or Citadel implement (one guard per call in `on_unit_destroyed`) and ares's `on_end` run in `ErrorGuard.guard(part)`; `on_start` is not (python-sc2 already catches it and resigns, a Defeat, not a Crash, and a half-built bot shouldn't play) | An error costs one part for one step instead of the game |
| What the guard lets through | python-sc2's `ProtocolError` (and its `ConnectionAlreadyClosed`) and BaseExceptions such as `CancelledError` | They mean the game or connection is over; python-sc2 ends the game as before |
| Error logging | A full traceback for the first `ERROR_TRACEBACKS_PER_PART` (3) errors of a part, then one line per `ERROR_LOG_EVERY_S` (60 game seconds) with the count; `errors` (per part) and `errors_first` in the game record (version 2), `err=` in `run_matches.py` rows | A part failing every step would otherwise fill the ladder log |
| A failure inside ares's after-step | Empty ares's behavior list, reset its grids, then run python-sc2's after-step so the step's actions are still sent (skipped when the error came from python-sc2's own part) | Finding above; without it the list grows every step |
| Ladder zip libraries | Copied from the Poetry environment (`SITE_PACKAGES_LIBRARIES`) | Finding above: the zip must hold what was tested |
| Ladder environment test (user decision: hybrid) | Official v0.8.0 proxy and bot images; the official v0.8.0 `sc2_controller` from its image layer (sha256-checked), run in the proxy image with this machine's SC2 4.10 (the SC2 image, 7.8 GB compressed, doesn't fit this machine's disk next to the 11 GB bot image); the IPv4 shim (`scripts/ladder_env/ipv4only.c`) for the proxy and sc2 controller only, on a kernel without IPv6 | Same bot image, launch command, timeouts and result rules as the ladder |
| Upload | `scripts/upload_to_ai_arena.py --upload` from a dev machine with `UPLOAD_API_TOKEN`/`UPLOAD_BOT_ID`; `AutoUploadToAiarena` stays False | One tested zip, uploaded once; with auto-upload on, every push to `main` would upload |
| Counting the first 20 games | `scripts/ladder_watch.py`: games played after the latest zip upload (`bot_zip_updated`), oldest first; a Citadel failure is a loss with `result_cause` crash, timeout or initialization_failure; if one happens, the fix is uploaded and the count starts again from that upload | AI Arena's own crash definition; the plan stated the restart |

## M6 acceptance evidence

Acceptance (DESIGN.md §7 M6): upload with bot data enabled; no crashes or timeouts in the first
20 ladder games. The ladder games are counted after the upload (`scripts/ladder_watch.py`, below);
this section first records what was checked before uploading. Bot code: commit 4d53ca5 (later
commits change scripts and docs only).

**The zip** (`poetry run python scripts/create_ladder_zip.py`): `publish/Citadel.zip`, 256 files,
9,854,928 bytes, md5 `07db06fe540df9dec7e1105fbc8ab491`, content hash
`f02e94a724e15fcf985cca65aa2dfbacace36df9e989a38276fa781a1b9ef4ee` (sha256 over every file's name
and contents, printed by the zip script; a rebuild of the same commit gives other bytes, md5
`afc29ba6...`, and the same content hash). `run.py`, `ladder.py`, `config.yml`,
`protoss_builds.yml` at the top level; no `data/`; `bot/` identical to the commit (`diff -rq`).
Its `sc2`, `map_analyzer` and `cython_extensions` are the Poetry environment's (`diff -rq`: 0
differences each, M6 findings); imported in the ladder bot image in 1.4-1.5 s (15.5 s cold).

**Error guard** (`poetry run python scripts/test_error_guard.py`, Easy Terran, PylonAIE_v4, errors
injected after five parts on every call plus a behavior raising inside ares's after-step for
2:00-2:30): 15/15 checks, Victory at 8:38 with 5,806 errors in "ares step", 5,806 in "micro", 726
in "detectors", 336 in "ares after step" (one per window step, actions still sent on 336/336), 54
in "ares unit destroyed", 43 in "ares construction started"; 3 tracebacks per part; ares's behavior
list at most 3 long; probes 21 → 23 through the window. (The first run, before the per-call guards
in `on_unit_destroyed`: 15/15, Victory at 8:48.)

**Regression with the guard** (`poetry run python scripts/run_matches.py --difficulty Hard --map
all --total 10 --race Terran Zerg Protoss Random`): 10/10 wins (Terran 3/3, Zerg 3/3, Protoss 2/2,
Random 2/2), `M5 no crash` 10/10 with the §8 line 10/10, `M6 errors caught: 0 in 0/10 games`, no
scout lost before 4:00 in 10/10, 2 counterattacks; 44+ probes at 6:00 in 8/10 (41 and 41 against
Pool-first Zerg, as in M4/M5); step mean 2.4-3.3 ms, max 31-166 ms (three batches shared the
machine).

**Ladder environment** (`poetry run python scripts/ladder_env_test.py`, the hybrid set-up in the
M6 choices: official v0.8.0 proxy and bot images, the official v0.8.0 sc2_controller, this
machine's SC2 4.10; Citadel's `./data` kept from match to match):

| # | Map | Opponent (race) | Citadel's seat | Arena result | Citadel | Game | Startup | Step mean/p99/max (ms) | Controller avg step | Errors | Pre-raised | Games in memory |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | PylonAIE_v4 | loser_bot (T) | 1 | Player1Win | Win | 8:24 | 1074 ms | 1.71/6.7/68.8 | 4.8 ms | 0 | - | 0 |
| 2 | TorchesAIE_v4 | basic_bot (T) | 2 | Player2Win | Win | 9:12 | 755 ms | 1.43/6.0/54.5 | 4.4 ms | 0 | - | 0 |
| 3 | MagannathaAIE_v2 | worker_rush (Z) | 1 | Player1Win | Win | 9:51 | 763 ms | 1.94/6.7/57.3 | 5.1 ms | 0 | - | 0 |
| 4 | UltraloveAIE_v2 | worker_rush (T) | 2 | Player2Win | Win | 9:55 | 895 ms | 1.88/6.7/51.1 | 4.8 ms | 0 | - | 1 |
| 5 | LeyLinesAIE_v3 | worker_rush (P) | 1 | Player1Win | Win | 9:15 | 576 ms | 1.75/6.4/66.2 | 4.6 ms | 0 | WORKER_RUSH | 2 |
| 6 | PersephoneAIE_v4 | cannon_rush (P) | 2 | Player2Win | Win | 10:48 | 640 ms | 2.38/8.8/62.5 | 5.6 ms | 0 | - | 0 |
| 7 | IncorporealAIE_v4 | twelve_pool (Z) | 1 | Player1Win | Win | 10:33 | 441 ms | 2.59/12.4/73.9 | 4.8 ms | 0 | - | 0 |
| 8 | PylonAIE_v4 | proxy_rax (T) | 2 | Player2Win | Win | 11:32 | 1002 ms | 2.92/10.9/62.1 | 5.5 ms | 0 | - | 0 |
| 9 | TorchesAIE_v4 | Citadel mirror (P) | 1 | Player2Win | Loss | 11:14 | 557 ms | 2.81/9.9/77.7 | 5.4 ms | 0 | - | 0 |
| 10 | LeyLinesAIE_v3 | twelve_pool (Z) | 2 | Error (see below) | - | - | - | - | - | - | - | - |
| 10 again | LeyLinesAIE_v3 | twelve_pool (Z) | 2 | Player2Win | Win | 9:52 | 614 ms | 2.89/13.4/68.1 | 5.6 ms | 0 | - | 1 |

- 10 of 10 matches played to a result with no Crash, TimeOut or InitializationError from Citadel,
  every one with its STARTUP line (441-1074 ms) and `METRIC game` line, no traceback, no guarded
  error; the third game against `le-worker-rush` pre-raised WORKER_RUSH from memory.
- Match 10's first attempt: the twelve_pool bot (seat 1) created the game, and neither SC2 process
  started it: Citadel's `join_game` returned after 33 s and its next request got "A game has not
  been started yet" (python-sc2 raised in `initialize_first_step`, before `on_start`), and the other
  SC2 process didn't answer for 60 s (`Sc2Timeout(60s)` → SC2Crash). The arena client scores that
  `Error` (on AI Arena: no result, cause "error", not a bot crash). Run alone with the data kept
  (`--matches 10 --keep-data`), it played normally.
- Citadel's `./data` after the 10 matches: 15 files, 18,369 bytes (limit 5 MB): ares's
  `<id>-protoss.json` and `opponents/<id>.json` for each of the 7 opponent ids, and
  `logs/games.jsonl` with 10 lines, all version 2 and well formed (`check_game_log.problems`), with
  `errors` empty in each.
- Earlier runs of the same test: the first (commit 901491e) played matches 1, 2 and 9 the same way
  (Citadel won all three, startup 749-1100 ms); its six cheese-bot matches ended in
  InitializationError at once because the cheese bots' generated `run.py` didn't import `sc2.main`
  (M6 findings); fixed in ce5c35b. The second stopped in match 1 when the Docker daemon, run as a
  time-limited background task, was stopped.

## M7 findings

API checks and Citadel's choices for M7 (`docs/M7_PLAN.md`). Checked before the plan was written
(python-sc2 at `7ec25cf`, ares at `8730865`):
- `Unit.is_biological` reads the type's attributes from game data (`sc2/unit.py:180-182`).
- `Unit.can_attack_ground` / `can_attack_air` special-case only Battlecruiser and Oracle
  (`sc2/unit.py:230-273`); a Carrier has no weapon in game data (its interceptors attack), so
  "flying and can attack" misses it. Capital air is an explicit list (`CAPITAL_AIR_TYPES`).
- `Unit.age` is the seconds since the Unit object's data was taken (`sc2/unit.py:471-473`).
- `Unit.movement_speed` is game data at "normal" speed and excludes upgrades and buffs
  (`sc2/unit.py:322-327`); `calculate_speed` adds them from python-sc2's own tables.
- `Unit.abilities` leaves out abilities on cooldown or without their tech (`sc2/unit.py:598`).
- ares has no Blink behavior (its ability tracker's Blink entry is commented out,
  `ares-sc2/src/ares/managers/ability_tracker_manager.py:163`).
- ares `AutoUseAOEAbility` casts Psionic Storm avoiding our own ground and air units
  (`ares-sc2/src/ares/behaviors/combat/individual/auto_use_aoe_ability.py`).
- ares's SpawnController morphs Archons from any two idle, ready High Templar not already morphing
  (`ares-sc2/src/ares/behaviors/macro/spawn_controller.py`, `_handle_archon_morph`), so Archons
  stay out of its mix and Citadel morphs them itself (§4.5.3).
- **Weaponless unit types in this game data (found in Phase 2's staged engagement test).** A one-off check of `game_data.units[t]._proto.weapons` on PylonAIE_v4 (SC2 4.10 with the AIE map's data) found **no weapons** for:
  - Sentry, Disruptor, Void Ray, Oracle, Carrier, Widow Mine (burrowed), Battlecruiser, Bunker, Baneling, Infestor, Swarm Host and Viper.
  - The other army types checked have their weapons. The Tempest's are 10 against ground and 13 against air here.
  - python-sc2 special-cases only the Battlecruiser's and Oracle's range and `can_attack_*` (`sc2/unit.py:230-297`). So a Void Ray reads `can_attack_air = can_attack_ground = False` with ranges 0/0, and so does a Carrier.
  - ares hard-codes ranges and costs for its influence grids for several of these (`dicts/weight_costs.py`: Void Ray 6/6, Carrier 11/11, Battlecruiser 6/6, Oracle, Widow Mine, Baneling).
  - **The combat simulator sees no attack for them either:** `Engagement.level` and ares's `can_win_fight` both rate 12 Zealots against 4 Void Rays at 10 (an emphatic win). The Phase 1 home fights rated 7-9 at a third of the enemy's value were against Void Ray and Carrier armies.
  - So C1's out-ranged rule and C5's penalty don't see Void Rays or Carriers, and the simulator underrates every army built on them. **Put to the user;** no stand-in values were added (CLAUDE.md: no hard-coded unit stats).
- **B8's trip estimate** (python-sc2 in the Poetry environment):
  - `Unit.movement_speed` is "the unit movement speed on game speed 'normal'. To convert it to 'faster' movement speed, multiply it by a factor of '1.4'". It doesn't include upgrades or buffs (`sc2/unit.py:322-326`).
  - `BotAI.time` is `game_loop / 22.4`, seconds on "faster" (`sc2/bot_ai.py:46-48`).
  - So an Observer covers `movement_speed × 1.4` per `bot.time` second without Gravitic Boosters, and more with them; the estimate errs long (`NORMAL_TO_FASTER`).
  - `Unit.distance_per_step` divides `real_speed` by 22.4 without the 1.4 (`sc2/unit.py:385-388`), so B8 doesn't use it.
- **Phase 2 VERIFY items** (ares `8730865`, python-sc2 in the Poetry environment, map_analyzer):
  - **Do Tempests add influence to ares's ground grid? Yes.** `Tempest` has a fixed entry in `ares/dicts/weight_costs.py`: GroundCost 17, GroundRange 10, AirCost 17, AirRange 14. `GridManager._add_cost_to_all_grids` adds it over range + `Pathing.RangeBuffer` (4.0 in ares's `config.yml`; Citadel's doesn't override it), so 14 on the ground grid (`managers/grid_manager.py` `_handle_weight_cost_unit`).
    - Units with no entry use their game-data range and dps (`_handle_generic_unit`), so a Carrier gets the fixed entry (11) and its Interceptors their own weapons.
  - **What does `KeepUnitSafe` do with no safe cell nearby?** When its cell isn't safe, it paths to `find_closest_safe_spot(radius=11)`: map_analyzer's `lowest_cost_points_array` returns the cells with the lowest cost within 11 (`Pather.py:276-282`), and ares takes the closest of them (`managers/path_manager.py:154-182`).
    - So with no safe cell within 11 it walks to the least dangerous cell, which may still be in reach. It returns True (it acted) whenever the unit's cell isn't safe.
  - **Does `Unit.movement_speed` exclude upgrades? Yes**, normal-speed game data without upgrades or buffs (`sc2/unit.py:322-326`; B8 above).
  - **Is a cached army unit's `age` the time since it was last seen? Yes.** `Unit.age` is `(game_loop - unit.game_loop) / 22.4` (`sc2/unit.py:471-473`). ares stores every visible enemy each step (`main.py:631` → `UnitCacheManager.store_enemy_unit`), replacing the stored Unit by tag (`unit_cache_manager.py:281-327`), so a cached unit's `game_loop` is the last step it was in vision. `bot/intel/army_position.py` relies on the same.
- **B2's in-game check (`poetry run python scripts/test_outranged.py --case idle_hold`, PylonAIE_v4,
  code `f62475a`):** do units at their hold point get drawn out after an attacker beyond the
  leash? No.
  - Setup: 10 Tempests on hold position 12.5 from the anchor (the hold leash is 12) shot 6
    Stalkers standing at it.
  - Result: home defense held ("hold (level 1 < 5)", then level 0). The farthest any Stalker got
    from the anchor was 4.7 (limit 16). They had ATTACK orders with an engaged target (the
    Tempests that had spread inside 12 were in their micro's reach), and all 6 died within 13 s
    while the Tempests took damage.
  - So the plan's fallback (re-issuing a move when `engaged_target_tag` is set past the leash) is
    not needed.
  - What the test shows instead is the Phase 2 problem: a squad standing in an out-ranging
    enemy's reach dies in place.
- **Phase 0 in a real game** (`run_matches.py --difficulty VeryHard --race Protoss --build Air --map
  PersephoneAIE_v4 --total 1 --game-seed 7500`, code `4a36da2`): the new lines show finding A
  directly.
  - `ENGAGE 09:28 launch level=10 ...; vs nothing (0) | ours 17 ADEPT 8 STALKER 2 IMMORTAL 1 COLOSSUS 3 ZEALOT (5025)`
  - 24 s later: `ENGAGE 09:52 retreat level=3 ...; vs 8 VOIDRAY 10 STALKER 2 PHOENIX 3 ADEPT 1 ORACLE 2 SENTRY +4 more (6875)`.
- **D18/D19 sources** (ares `8730865`, python-sc2 in the Poetry environment):
  - `ares.dicts.weight_costs.WEIGHT_COSTS` (`ares-sc2/src/ares/dicts/weight_costs.py`) is a `dict[UnitTypeId, dict]` with the keys `AirCost`, `GroundCost`, `AirRange` and `GroundRange`.
    - It has entries for the game-data-weaponless types Void Ray (6/6), Carrier (11/11), Battlecruiser (6/6), Oracle (ground 4), Sentry (5/5), Baneling (ground 3), burrowed Widow Mine (5.5/5.5) and Infestor (10/10).
    - It has none for the Disruptor, Swarm Host, Viper, Bunker or unburrowed Widow Mine.
    - Some entries include upgrades (Hydralisk 6). Citadel reads it only for types with no game-data weapon (`ranges.weapon_range`).
  - python-sc2 gives the Battlecruiser `can_attack_ground`/`can_attack_air` and ranges 6/6, and the Oracle `can_attack_ground` and range 4 (`sc2/unit.py:228-294`). So those two never reach the ares fallback.
  - Game-data ranges of the melee types (a one-off `_proto.weapons` dump on PylonAIE_v4): Zealot, Dark Templar, Zergling and Broodling 0.1; Probe, SCV and Drone 0.2; Ultralisk 1.0. The shortest ranged weapon is the Hellbat's 2.0 and the Interceptor's 2.0. Hence `MELEE_RANGE_MAX` = 1.0.
  - The unburrowed Widow Mine has no weapon either (the earlier dump only had the burrowed one).
  - ares's `BuildingManager` drops a Protoss build order 120 s after it was given (`BUILDING_WORKER_TIMEOUT`, `managers/building_manager.py:67, 229-235`). So a stuck Nexus order can't block the schedule for good (D20).

## M7 baseline

Bot code `8036973` (M6, unchanged by the M7 kickoff), run on 2026-10-06 in the cloud container:
- SC2 Linux 4.10 (Base75689) from Blizzard's package (`docs/RESEARCH.md` commands).
- The 7 pool maps.
- Poetry on Python 3.12 (STATUS workaround). The `ares-sc2` submodule had to be checked out first: `git submodule update --init ares-sc2`.
- Offline tests before the games: `test_attack_decision` 16/16, `test_threat_flags` 20/20, `test_m3_checks` 14/14, `test_counterattack_rules` 36/36, `test_opponent_memory` 38/38.

Commands (the three ran in parallel; replays in `replays/m7-baseline-<race>/`, not in git):

```bash
SC2PATH=$HOME/StarCraftII poetry run python scripts/run_matches.py --difficulty VeryHard --race Protoss --build Air --map all --total 10 --game-seed 7000 --replays replays/m7-baseline-protoss
SC2PATH=$HOME/StarCraftII poetry run python scripts/run_matches.py --difficulty VeryHard --race Terran  --build Air --map all --total 10 --game-seed 7100 --replays replays/m7-baseline-terran
SC2PATH=$HOME/StarCraftII poetry run python scripts/run_matches.py --difficulty VeryHard --race Zerg    --build Air --map all --total 10 --game-seed 7200 --replays replays/m7-baseline-zerg
```

| Batch | Wins | Crashes / errors | probes@6 (min / median / max) |
|---|---|---|---|
| Protoss Air | **2/10** | 0 / 0 | 40 / 42 / 59 |
| Terran Air | 9/10 | 0 / 0 | 54 / 57 / 60 |
| Zerg Air | 10/10 | 0 / 0 | 56 / 64 / 66 |

The "enemy capital ships" and "top killers" columns come from the saved replays' tracker events. They were read with Blizzard's s2protocol in a scratch environment; it is not a project dependency.

**Protoss Air, VeryHard × 10, `--game-seed 7000`**

| # | map | result | length | probes@6 | bases@6 | value lost/killed | flags (first raise) | enemy capital ships made (died) | top killers of our army |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Magannatha_v2 | Defeat | 15:37 | 45 | 2 | 9.7k/4.4k | PROXY@01:30 | Tempest 1 (0), Carrier 1 (0) | VoidRay 34, Stalker 14, Sentry 3 (of 55) |
| 2 | Ultralove_v2 | Defeat | 12:56 | 40 | 1 | 9.4k/2.1k | PROXY@01:30,CANNON_RUSH@01:58 | Tempest 4 (0) | VoidRay 31, Stalker 15, Phoenix 3 (of 51) |
| 3 | LeyLines_v3 | Defeat | 13:54 | 41 | 1 | 11.3k/3.2k | PROXY@01:30,CANNON_RUSH@01:56 | Tempest 6 (0), Carrier 5 (0) | Stalker 25, VoidRay 14, Tempest 10 (of 57) |
| 4 | Torches_v4 | Victory | 11:40 | 56 | 2 | 4.5k/5.9k | - | - | VoidRay 14, Stalker 5, Probe 1 (of 20) |
| 5 | Pylon_v4 | Victory | 10:53 | 59 | 3 | 1.6k/7.7k | - | Tempest 1 (1), Carrier 1 (1) | Stalker 4, VoidRay 2, Interceptor 1 (of 7) |
| 6 | Persephone_v4 | Defeat | 15:24 | 40 | 1 | 8.8k/3.0k | PROXY@01:30 | Tempest 6 (0), Carrier 6 (0) | VoidRay 19, Tempest 14, Interceptor 8 (of 47) |
| 7 | Incorporeal_v4 | Defeat | 14:49 | 43 | 1 | 19.3k/6.9k | PROXY@01:30 | Tempest 4 (0), Carrier 4 (0) | VoidRay 30, Interceptor 24, Tempest 24 (of 99) |
| 8 | Magannatha_v2 | Defeat | 15:01 | 41 | 1 | 11.0k/3.4k | PROXY@01:30 | Tempest 4 (0) | VoidRay 39, Stalker 5, Tempest 5 (of 56) |
| 9 | Ultralove_v2 | Defeat | 18:41 | 46 | 2 | 29.6k/12.7k | ONE_BASE_ALLIN@02:45 | Tempest 3 (0) | VoidRay 97, Immortal 23, Tempest 12 (of 144) |
| 10 | LeyLines_v3 | Defeat | 14:51 | 40 | 1 | 16.6k/5.4k | PROXY@01:30 | Tempest 4 (0), Carrier 3 (0) | Interceptor 31, VoidRay 22, Tempest 15 (of 86) |

**Terran Air, VeryHard × 10, `--game-seed 7100`**

| # | map | result | length | probes@6 | bases@6 | value lost/killed | flags (first raise) | enemy capital ships made (died) | top killers of our army |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Magannatha_v2 | Victory | 10:31 | 59 | 2 | 1.9k/5.8k | - | Battlecruiser 2 (2) | VikingFighter 4, Battlecruiser 3, Sentry 3 (of 14) |
| 2 | Ultralove_v2 | Defeat | 22:11 | 56 | 2 | 21.8k/10.5k | PROXY@01:30 | Battlecruiser 11 (1) | Battlecruiser 69, Marauder 18, VikingAssault 16 (of 125) |
| 3 | LeyLines_v3 | Victory | 11:18 | 56 | 2 | 2.9k/7.0k | PROXY@01:30 | Battlecruiser 1 (1) | Marauder 7, VikingAssault 6, AutoTurret 3 (of 22) |
| 4 | Torches_v4 | Victory | 11:35 | 54 | 2 | 3.3k/8.2k | PROXY@01:30 | Battlecruiser 3 (3) | Battlecruiser 14, Marauder 6, VikingAssault 4 (of 27) |
| 5 | Pylon_v4 | Victory | 10:05 | 59 | 2 | 2.2k/6.2k | - | Battlecruiser 1 (1) | Battlecruiser 4, VikingFighter 2, Sentry 2 (of 14) |
| 6 | Persephone_v4 | Victory | 12:57 | 55 | 2 | 5.5k/9.1k | PROXY@01:30 | Battlecruiser 4 (4) | Marauder 10, Battlecruiser 9, Marine 3 (of 32) |
| 7 | Incorporeal_v4 | Victory | 10:53 | 59 | 2 | 2.8k/4.3k | ONE_BASE_ALLIN@02:45 | Battlecruiser 2 (2) | Battlecruiser 6, VikingAssault 4, VikingFighter 4 (of 16) |
| 8 | Magannatha_v2 | Victory | 12:10 | 60 | 2 | 3.3k/6.0k | ONE_BASE_ALLIN@02:45 | Battlecruiser 2 (2) | Banshee 7, Battlecruiser 4, Marine 3 (of 20) |
| 9 | Ultralove_v2 | Victory | 10:29 | 58 | 2 | 2.4k/5.0k | ONE_BASE_ALLIN@02:45 | - | VikingAssault 6, Marauder 5, VikingFighter 1 (of 13) |
| 10 | LeyLines_v3 | Victory | 14:18 | 55 | 2 | 10.0k/11.7k | PROXY@01:30 | Battlecruiser 6 (6) | Battlecruiser 31, Marauder 14, VikingFighter 6 (of 59) |

**Zerg Air, VeryHard × 10, `--game-seed 7200`**

| # | map | result | length | probes@6 | bases@6 | value lost/killed | flags (first raise) | enemy capital ships made (died) | top killers of our army |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Magannatha_v2 | Victory | 09:55 | 63 | 3 | 1.7k/5.6k | - | - | Roach 5, Hydralisk 4, Mutalisk 4 (of 14) |
| 2 | Ultralove_v2 | Victory | 10:20 | 65 | 3 | 1.5k/4.5k | - | - | Hydralisk 6, SpineCrawler 2, Roach 2 (of 13) |
| 3 | LeyLines_v3 | Victory | 10:01 | 65 | 3 | 1.0k/5.0k | - | - | Roach 4, Hydralisk 4 (of 8) |
| 4 | Torches_v4 | Victory | 10:40 | 58 | 3 | 1.3k/4.1k | POOL_12@01:31 | - | Roach 6, Hydralisk 3, Zergling 1 (of 10) |
| 5 | Pylon_v4 | Victory | 10:25 | 57 | 3 | 1.0k/4.0k | POOL_12@01:25 | - | Roach 4, ? 1, Zergling 1 (of 8) |
| 6 | Persephone_v4 | Victory | 10:25 | 56 | 3 | 1.4k/4.9k | POOL_12@01:30 | - | Mutalisk 3, Hydralisk 3, Roach 1 (of 8) |
| 7 | Incorporeal_v4 | Victory | 09:59 | 65 | 3 | 0.7k/2.9k | - | - | Roach 2, Queen 1, SpineCrawler 1 (of 4) |
| 8 | Magannatha_v2 | Victory | 10:07 | 57 | 3 | 1.2k/4.8k | POOL_12@01:30 | - | Roach 5, Hydralisk 3, Mutalisk 2 (of 10) |
| 9 | Ultralove_v2 | Victory | 09:49 | 65 | 3 | 1.2k/5.3k | - | - | Hydralisk 4, Roach 3, Corruptor 1 (of 10) |
| 10 | LeyLines_v3 | Victory | 09:55 | 66 | 3 | 1.0k/4.9k | - | - | Hydralisk 6, Zergling 1, Broodling 1 (of 8) |

**Findings:**
- **The Air build exposes what the M4/M5 VeryHard batches missed.** Those ran with `--build RandomBuild` and won 10/10 vs Protoss; the Protoss Air build wins 8/10 against the same code. The losses follow the ladder loss: our army value lost was 2.2-4.5× what it killed.
- **Void Rays were our top killer in 7 of the 10 Protoss games** (Stalkers in 2, Carrier interceptors in 1). Tempests and/or Carriers were built in 9 of the 10, and they died only in game 5 (one Tempest, one Carrier; a win), the ladder pattern again.
- **The PROXY flag (§4.4 row 10, "no Gateway by 1:30") was false in 7 of the 8 Protoss losses** and absent from both wins. This build opens Nexus first (~1:04) and puts down its first Gateway at 1:18-1:34 (Magannatha 1:33, LeyLines 1:34, Ultralove 1:18, Pylon 1:19; Torches 0:41, no flag), so at the 1:30 check its main often has none yet.
  - The flag ends our opener and holds our natural, so the PROXY games had 40-45 probes at 6:00 and 1-2 bases, against 56-59 probes in the two wins.
  - The flag expired by its phase rule at 5:30 every time ("no proxy structure known").
  - It also fired in 5 of 10 Terran games, which were won.
- **Terran's one loss was to Battlecruisers:** 11 made, 1 killed, and they killed 69 of our 125 units. In the 8 other games with Battlecruisers, every one died (1-6 per game).
- **The VeryHard Zerg Air build never reached capital ships:** no Brood Lords, and every game was over by 10:40. So this batch doesn't test the Zerg capital-air response.

### CheatInsane Air baselines (for the D11 targets vs Terran and Zerg)

Same bot code as above (M6). The batches started before the Phase 0 commits, and their game records are version 2, which only the M6 code writes. The two batches ran in parallel; replays are in `replays/m7-baseline-<race>-insane/`, not in git.

```bash
SC2PATH=$HOME/StarCraftII poetry run python scripts/run_matches.py --difficulty CheatInsane --race Terran --build Air --map all --total 10 --game-seed 7300 --replays replays/m7-baseline-terran-insane
SC2PATH=$HOME/StarCraftII poetry run python scripts/run_matches.py --difficulty CheatInsane --race Zerg   --build Air --map all --total 10 --game-seed 7400 --replays replays/m7-baseline-zerg-insane
```

| Batch | Wins | Crashes / errors | probes@6 (min / median / max) |
|---|---|---|---|
| Terran Air, CheatInsane | **2/10** | 0 / 0 | 55 / 58.5 / 61 |
| Zerg Air, CheatInsane | 8/10 | 0 / 0 | 40 / 56 / 62 |

**Terran Air, CheatInsane × 10, `--game-seed 7300`**

| # | map | result | length | probes@6 | bases@6 | value lost/killed | flags (first raise, count) | enemy capital ships made (died) | top killers of our army |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Magannatha_v2 | Victory | 14:32 | 61 | 2 | 7.8k/16.3k | - | Battlecruiser 3 (3) | Marauder 13, VikingFighter 10, VikingAssault 6 (of 51) |
| 2 | Ultralove_v2 | Defeat | 12:37 | 57 | 2 | 13.1k/3.3k | PROXY@01:30,ARMY_OUT_OF_POSITION@10:10 | Battlecruiser 4 (0) | Battlecruiser 25, Marauder 20, VikingAssault 20 (of 76) |
| 3 | LeyLines_v3 | Defeat | 19:25 | 58 | 2 | 30.6k/21.4k | ARMY_OUT_OF_POSITION@05:13 (×6) | Battlecruiser 7 (3) | Marauder 43, Battlecruiser 26, VikingAssault 26 (of 157) |
| 4 | Torches_v4 | Defeat | 17:20 | 57 | 2 | 23.1k/12.2k | ONE_BASE_ALLIN@02:45,ARMY_OUT_OF_POSITION@05:07 (×5) | Battlecruiser 9 (3) | Battlecruiser 44, VikingAssault 19, Marauder 16 (of 119) |
| 5 | Pylon_v4 | Defeat | 21:03 | 59 | 2 | 30.8k/20.3k | ARMY_OUT_OF_POSITION@12:37 (×3) | Battlecruiser 9 (4) | Battlecruiser 61, Marauder 36, VikingAssault 18 (of 156) |
| 6 | Persephone_v4 | Victory | 11:43 | 61 | 2 | 3.1k/9.0k | - | Battlecruiser 2 (2) | Marine 12, Marauder 5, Sentry 3 (of 26) |
| 7 | Incorporeal_v4 | Defeat | 16:35 | 59 | 2 | 20.7k/5.8k | ONE_BASE_ALLIN@02:45,ARMY_OUT_OF_POSITION@10:55 (×3) | Battlecruiser 10 (3) | Battlecruiser 46, Marauder 25, VikingAssault 23 (of 108) |
| 8 | Magannatha_v2 | Defeat | 19:55 | 59 | 2 | 32.0k/22.1k | ONE_BASE_ALLIN@02:45,ARMY_OUT_OF_POSITION@05:35 (×2) | Battlecruiser 9 (6) | Marauder 42, Battlecruiser 36, SiegeTank 27 (of 169) |
| 9 | Ultralove_v2 | Defeat | 14:26 | 55 | 2 | 13.5k/5.3k | PROXY@01:30,ARMY_OUT_OF_POSITION@10:20 | Battlecruiser 7 (2) | Battlecruiser 38, Marauder 29, VikingAssault 4 (of 77) |
| 10 | LeyLines_v3 | Defeat | 19:47 | 58 | 2 | 32.5k/17.6k | ARMY_OUT_OF_POSITION@12:17 (×2) | Battlecruiser 8 (4) | Marauder 68, Battlecruiser 32, VikingAssault 27 (of 175) |

**Zerg Air, CheatInsane × 10, `--game-seed 7400`**

| # | map | result | length | probes@6 | bases@6 | value lost/killed | flags (first raise, count) | enemy capital ships made (died) | top killers of our army |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Magannatha_v2 | Victory | 13:05 | 62 | 3 | 5.7k/13.6k | POOL_12@01:30 | - | SpineCrawler 14, Roach 12, Hydralisk 10 (of 43) |
| 2 | Ultralove_v2 | Victory | 16:40 | 57 | 3 | 6.9k/24.4k | POOL_12@01:27 | BroodLord 3 (3) | Roach 10, Hydralisk 6, SpineCrawler 5 (of 40) |
| 3 | LeyLines_v3 | Victory | 14:41 | 56 | 3 | 5.7k/16.7k | POOL_12@01:30 | BroodLord 1 (1) | Roach 14, Hydralisk 11, SpineCrawler 5 (of 37) |
| 4 | Torches_v4 | Victory | 13:37 | 56 | 3 | 5.0k/12.7k | POOL_12@01:30 | BroodLord 2 (2) | Hydralisk 8, SpineCrawler 8, Roach 6 (of 32) |
| 5 | Pylon_v4 | Defeat | 17:54 | 40 | 1 | 20.6k/25.4k | POOL_12@01:07,ARMY_OUT_OF_POSITION@08:15 (×5) | BroodLord 14 (6) | Roach 30, Hydralisk 24, BroodlingEscort 21 (of 106) |
| 6 | Persephone_v4 | Victory | 20:25 | 57 | 3 | 19.1k/35.8k | POOL_12@01:35,ARMY_OUT_OF_POSITION@09:00 (×2) | BroodLord 9 (9) | Roach 30, Mutalisk 17, SpineCrawler 16 (of 122) |
| 7 | Incorporeal_v4 | Victory | 15:31 | 55 | 3 | 6.3k/18.1k | POOL_12@01:27,ARMY_OUT_OF_POSITION@09:00 | BroodLord 2 (2), BroodLordCocoon 1 (1) | Roach 17, Hydralisk 11, SpineCrawler 10 (of 53) |
| 8 | Magannatha_v2 | Victory | 17:10 | 53 | 3 | 11.2k/30.4k | POOL_12@01:29,ARMY_OUT_OF_POSITION@09:36 | BroodLord 5 (5) | Roach 30, SpineCrawler 11, Hydralisk 10 (of 83) |
| 9 | Ultralove_v2 | Defeat | 33:12 | 56 | 3 | 34.1k/44.0k | POOL_12@01:25,ARMY_OUT_OF_POSITION@18:53 (×9) | BroodLord 9 (5) | Roach 42, LurkerMPBurrowed 28, BroodlingEscort 26 (of 181) |
| 10 | LeyLines_v3 | Victory | 14:32 | 57 | 3 | 6.8k/20.0k | POOL_12@01:30,ARMY_OUT_OF_POSITION@07:49 | BroodLord 3 (3) | Roach 14, Hydralisk 10, SpineCrawler 10 (of 44) |

(`BroodlingEscort` is a Brood Lord's attack: the broodlings it launches.)

**Findings:**
- **Terran: Battlecruisers decide the games.** They were made in all 10 games (2-10 each).
  - In all 8 losses they were one of our army's two top killers (the top one in 5), and we killed 0-6 of the 4-10 made.
  - In both wins every Battlecruiser died (3 and 2).
  - ARMY_OUT_OF_POSITION fired in all 8 losses and in neither win.
  - Our value lost was 1.4-4.0× what we killed in the losses.
- **Zerg: Brood Lords are where the losses come from.** They were made in 9 of 10 games (1-14 each).
  - In the 7 wins with Brood Lords, every one died.
  - The 2 losses had 14 (6 died) and 9 (5 died); their broodlings were our third top killer in both.
  - Game 5 also faced a real 12 pool (POOL_12@01:07) and was on 1 base with 40 probes at 6:00.
  - Game 9 lasted 33 minutes, and burrowed Lurkers were our second top killer.
- So these two batches test what the Phase 3 capital-air responses (K1-K3) are for. The VeryHard batches above don't, because VeryHard Terran makes few Battlecruisers and VeryHard Zerg makes no Brood Lords.

## M7 acceptance evidence

### Phase 0 + Phase 1 (M7_PLAN.md), run 2026-10-06

Code under test: `07d4ddd`. It holds O1-O3, B1-B6 and `scripts/test_outranged.py`; the commits after it change only docs. All games ran in the cloud container, with the same set-up as the baseline. Up to four batches ran in parallel on 4 cores. Logs were kept outside the repo; replays are in `replays/m7-p1-<race>/`, not in git.

**Summary**

| Criterion (M7_PLAN.md) | Result |
|---|---|
| P0: one local game shows the three new line types | PASS |
| P0: `check_game_log.py` passes | PASS: `RESULT PASS`, 181 records, 0 malformed, ./data 383 KB |
| P0: M1 regression (Hard × 10, T/Z/P/Random) unchanged | PASS: 10/10, as on M6 |
| P1: Air batches on the same seeds: `reinforce_after_retreat` = 0 | PASS: 0 in all 30 Air games (and 0 in every other game below) |
| P1: Air batches on the same seeds: `lost_far` for HOLD lower than baseline | **FAIL as written**: 8 against 2. HOLD deaths overall fell from 45 to 17; see below |
| P1: main re-scouts at least every ~90 s from 6:00 while an Observer is free | PASS as written; gaps remain while the only free Observer is on an expansion trip (see below) |
| P1 (B6): no PROXY in the Nexus-first Protoss Air games | PASS: 0 of 7 (baseline 7 of 7) |
| P1 (B6): `proxy_rax` still raises PROXY; correct flag 40/40 | PASS: correct flag 40/40; vs `proxy_rax`, PROXY was raised in game at 1:30 (games 1-2) and from memory from game 3 |
| P1: M2/M3 cheese × 10 each (≥ 8/10, flags, no scout lost before 4:00) | **Not met for cannon rush**: worker rush, 12 pool and proxy rax 10/10 each; cannon rush **5/10**, then 8/10 on a rerun (Phase-0 code 9/10; A/B below). M3 parts pass: correct flag 40/40, and no scout lost before 4:00 in 9/10 (worker rush), 10/10 (cannon rush), 10/10 (12 pool) and 9/10 (proxy rax) games |
| P1: M4 VeryHard × 10 per race (≥ 7 each) | PASS: Terran 10/10, Zerg 9/10, Protoss 10/10 |

**Offline tests** (`poetry run python scripts/<name>.py`):

| Script | Result |
|---|---|
| `test_m7_rules` (new) | 17/17 |
| `test_attack_decision` | 16/16 |
| `test_threat_flags` | 20/20 |
| `test_m3_checks` | 14/14 |
| `test_counterattack_rules` | 36/36 |
| `test_opponent_memory` | 38/38 |

The staged `test_outranged.py --case idle_hold` passed; it is B2's VERIFY, recorded under "M7 findings".

**Phase 0: the new log lines.** One local game on `4a36da2` (O1-O3; "M7 findings"):

```
poetry run python scripts/run_matches.py --difficulty VeryHard --race Protoss --build Air --map PersephoneAIE_v4 --total 1 --game-seed 7500
```

- It logged 4 `ENGAGE`/`DEFEND` lines with the simulator's inputs, for example:
  - `DEFEND 10:11: engage (level 10 >= 5) vs ZEALOT at (49, 73), 25 defenders (62 supply); vs 1 ZEALOT (100) | ours 8 STALKER 11 ADEPT 2 COLOSSUS 2 IMMORTAL 2 ZEALOT (4675)`
- It logged 11 `INTEL first seen` lines, for example `INTEL first seen NEXUS at 01:06 (65, 149)`.
- It logged 76 `UNIT lost` lines, for example `UNIT lost ADEPT at (54, 109) (09:44, fight 15 from its point)`.
- Across the Phase 1 batches below, `INTEL first seen` caught capital ships as well: Tempest 9, Carrier 6, Battlecruiser 8, Brood Lord 1, Brood Lord cocoon 1.

**Air batches, same seeds as the baseline**

```
SC2PATH=$HOME/StarCraftII poetry run python scripts/run_matches.py --difficulty VeryHard --race <Protoss|Terran|Zerg> --build Air --map all --total 10 --game-seed <7000|7100|7200> --replays replays/m7-p1-<race>
```

| Batch | Baseline (M6) | Phase 1 | D11 target (end of M7) | `reinforce_after_retreat` | probes@6 median (baseline → P1) |
|---|---|---|---|---|---|
| Protoss Air | 2/10 | **8/10** | ≥ 7/10 | 0 | 42 → 49 |
| Terran Air | 9/10 | **10/10** (no Battlecruiser loss) | ≥ 9/10, no Battlecruiser loss | 0 | 57 → 59 |
| Zerg Air | 10/10 | **10/10** | ≥ 9/10 | 0 | 64 → 62 |

**The baseline's openers differ from Phase 1's, so the Protoss comparison was re-run with them matched.**
- Citadel picks its opener from `./data/None-protoss.json`, which every no-id batch shares and updates. So the baseline played `C2_1GateExpand` in 7 games and Phase 1 played `C_2GateRobo` in 7.
- To compare like with like, the Phase-0-only code (`4a36da2`: O1-O3 logging, otherwise M6) was run again on seed 7000. Each game was forced to the opener Phase 1 picked in it (a `git worktree` of `4a36da2` with the `ares-sc2` folder linked in, and the same Poetry environment). Forced openers don't write `./data`.

```
SC2PATH=$HOME/StarCraftII python scripts/run_matches.py --difficulty VeryHard --race Protoss --build Air --map all --game-seed 7000 --replays replays/m7-p0-protoss-paired --total 6 --opener C_2GateRobo
... --start 7 --total 7 --opener C2_1GateExpand
... --start 8 --total 8 --opener C_2GateRobo
... --start 9 --total 10 --opener C2_1GateExpand
```

Each cell reads: result and length; probes/bases at 6:00; false PROXY; army value lost/killed; army units lost, with the HOLD deaths (deaths more than 12 from the point in brackets) and the RETREAT deaths.

| # | map | opener (both) | Phase 0 code (`4a36da2`) | Phase 1 code (`07d4ddd`) |
|---|---|---|---|---|
| 1 | Magannatha_v2 | C_2GateRobo | Defeat 15:10; 45/2; PROXY@01:30; 12.1k/5.2k; 69 lost, hold 21 (1), retreat 9 | Victory 18:56; 47/2; -; 12.1k/18.0k; 60 lost, hold 0 (0), retreat 3 |
| 2 | Ultralove_v2 | C_2GateRobo | Defeat 20:12; 39/1; PROXY@01:30; 22.4k/15.8k; 114 lost, hold 3 (1), retreat 40 | Victory 14:03; 48/2; -; 9.2k/12.8k; 49 lost, hold 0 (0), retreat 0 |
| 3 | LeyLines_v3 | C_2GateRobo | Defeat 13:47; 41/1; PROXY@01:30; 11.2k/3.3k; 57 lost, hold 18 (0), retreat 12 | Victory 14:46; 49/2; -; 9.3k/14.0k; 42 lost, hold 0 (0), retreat 0 |
| 4 | Torches_v4 | C_2GateRobo | Victory 11:52; 50/2; -; 4.5k/6.8k; 19 lost, hold 0 (0), retreat 0 | Victory 11:46; 50/2; -; 5.5k/6.3k; 29 lost, hold 0 (0), retreat 2 |
| 5 | Pylon_v4 | C_2GateRobo | Victory 13:45; 51/2; -; 7.0k/11.4k; 33 lost, hold 0 (0), retreat 3 | Victory 14:55; 48/2; -; 6.5k/13.6k; 31 lost, hold 0 (0), retreat 0 |
| 6 | Persephone_v4 | C_2GateRobo | Defeat 16:53; 40/1; PROXY@01:30; 21.4k/9.6k; 109 lost, hold 0 (0), retreat 32 | Defeat 15:24; 48/2; -; 18.1k/7.6k; 86 lost, hold 8 (6), retreat 12 |
| 7 | Incorporeal_v4 | C2_1GateExpand | Victory 17:18; 43/1; PROXY@01:30; 17.6k/11.5k; 94 lost, hold 0 (0), retreat 23 | Victory 13:02; 58/3; -; 10.3k/11.2k; 50 lost, hold 0 (0), retreat 0 |
| 8 | Magannatha_v2 | C_2GateRobo | Defeat 13:14; 40/1; PROXY@01:30; 8.9k/3.0k; 47 lost, hold 1 (0), retreat 4 | Defeat 20:28; 49/2; -; 17.7k/6.0k; 85 lost, hold 9 (2), retreat 12 |
| 9 | Ultralove_v2 | C2_1GateExpand | Victory 10:42; 54/2; -; 3.2k/6.1k; 17 lost, hold 0 (0), retreat 0 | Victory 11:07; 57/2; -; 5.2k/6.5k; 27 lost, hold 0 (0), retreat 0 |
| 10 | LeyLines_v3 | C2_1GateExpand | Defeat 17:19; 40/1; PROXY@01:30; 21.2k/9.6k; 106 lost, hold 2 (0), retreat 24 | Victory 12:04; 58/3; -; 3.8k/7.8k; 16 lost, hold 0 (0), retreat 0 |

| Totals | Phase 0 | Phase 1 |
|---|---|---|
| Wins | 4/10 | 8/10 |
| False PROXY@01:30 | 7 | 0 |
| Army units lost | 664 | 473 |
| HOLD deaths, all / farther than 12 from the point | 45 / 2 | 17 / 8 |
| RETREAT deaths | 147 | 29 |
| Main re-scouts sent from 6:00 | 30 (none in games 1 and 8) | 62 (4-11 in every game) |

**B1 (retreats).** `reinforce_after_retreat` was 0 in all 120 Phase 1 games: 30 Air, 30 VeryHard, 10 Hard and 50 cheese (the 40 plus the cannon rush rerun). With the same openers, RETREAT deaths fell from 147 to 29.

**B2/B3 and the HOLD criterion: missed as written.**
- The plan asked for fewer HOLD deaths farther than `LOST_FAR_DISTANCE` (12) from the point. Phase 1 has 8, the Phase-0 code 2.
- That metric was meant to catch units at the hold point being drawn out after an attacker. B2's in-game check showed that doesn't happen.
- The HOLD losses the postmortem found are units dying at the hold point in an out-ranging army's reach. Those fell from 45 to 17, and none were in Phase 1's eight wins.
- The 8 far HOLD deaths all came in Phase 1's two losses (games 6 and 8), during home fights against a mass air army.
  - In game 6, the decision switched between engage, hold and last stand every 1-3 s from 10:31 to 12:47 (Void Rays, Carriers and Tempests).
  - Stalkers that the switch left 14-23 from their point died walking back to it with a plain move, which is B2's behaviour.
  - Phase 2's C1 (out-ranged units step to safety before shooting, and the hold point moves back) and C2 (defenders that can't hit the threat hold) target exactly this.
  - Its staged case `hold_vs_tempest` checks that no unit dies beyond the leash.

**B4 (main re-scouts) as measured** (Protoss Air, from 6:00):
- 62 re-scouts went out (4-11 per game), against 30 on the Phase-0 code and 56 on the baseline (which had none after 6:00 in game 3).
- Of the 62 intervals (6:00 to the first re-scout, then between re-scouts), 57 were at most 90 s; most were 60 s, the re-scout period.
- The 5 longer gaps were 95-180 s:
  - in 3 of them, the only free Observer was on an expansion trip;
  - in the other 2, an Observer died and the next was free 20 s or 2:17 later.
- Game 8 then had no free Observer from 14:32 to the end (20:28): one was on the home post and one was with the army.
- **What remains:** right after each re-scout, the main was just seen, so the next expansion check takes the same Observer for 90-110 s. The main then goes unseen for up to ~2.5 minutes (the first ladder loss had 5:43-11:01). B4 as specified only stops an expansion check from starting while the re-scout is already due. This is put to the user; no change was made.

**B5.** Hallucinations ran only against Terran: 25 in Terran Air, 32 in VeryHard Terran and 13 in the M1 batch's Terran games (one of them a Random opponent that was Terran). None ran against Protoss or Zerg.

**B6 (expansion-first proxy check).**
- In the 7 Protoss Air games where the enemy opened Nexus first (1, 2, 3, 6, 7, 8, 10; natural townhall seen at 1:04-1:07, no Gateway in the main at 1:30):
  - the baseline and the Phase-0 code raised `PROXY@01:30` in all 7;
  - Phase 1 logged `SCOUT proxy check at 01:30: 0 Gateways in the main, 20 workers seen, a townhall at their natural (expansion first)` and raised nothing.
- In the other 3 games the main had a Gateway, so there was no flag on any code.
- Against `proxy_rax`, the missing-production path still fires when the natural is empty: `FLAG raise PROXY (STRUCTURE, proxy_missing) at 1:30: no Barracks in the scouted main [ends opener]` (games 1-2, before memory pre-raises it).
- The VeryHard Protoss batch's 10 proxy checks all found a Gateway.

**Regressions**

```
SC2PATH=$HOME/StarCraftII poetry run python scripts/run_matches.py --difficulty Hard --map all --total 10 --race Terran Zerg Protoss Random --game-seed 4000
SC2PATH=$HOME/StarCraftII poetry run python scripts/run_matches.py --difficulty VeryHard --race <Terran|Zerg|Protoss> --map all --total 10 --game-seed 3000 --opponent-id m7p1-vh-<race>
SC2PATH=$HOME/StarCraftII poetry run python scripts/run_matches.py --opponent <bot> --map all --total 10 --seed 100 --game-seed 5000 --opponent-id m7p1-<bot>
```

| Batch | Wins | Correct flag | Games with no scout lost before 4:00 | `raa` | Notes |
|---|---|---|---|---|---|
| M1: Hard × 10 (T/Z/P/Random) | **10/10** (3/3, 3/3, 2/2, 2/2) | — | 10/10 | 0 | M6: 10/10 |
| M4: VeryHard Terran | **10/10** | — | 10/10 | 0 | |
| M4: VeryHard Zerg | **9/10** | — | 10/10 | 0 | The loss is Ley Lines game 3 (12 pool, then a 10-Roach push at 4:05; 8:46), lost on every M5 commit too; M5 was also 9/10 with this loss |
| M4: VeryHard Protoss | **10/10** | — | 10/10 | 0 | |
| M2/M3: worker rush | **10/10** | 10/10 | 9/10 | 0 | Game 6: the fallback main probe (sent at 2:30) was killed by a leftover worker-rush Drone at 3:28 |
| M2/M3: cannon rush | **5/10** (2 losses, 3 ties at 60:00) | 10/10 | 10/10 | 0 | **Under the M2 bar.** Rerun 8/10; Phase-0 code 9/10 (A/B below) |
| M2/M3: 12 pool | **10/10** | 10/10 | 10/10 | 0 | |
| M2/M3: proxy rax | **10/10** | 10/10 | 9/10 | 0 | Game 3 (PROXY pre-raised from memory): the main probe checked the proxy spots and came home unscouted; the retry probe met the proxy Marines at 2:38 |

**Cannon rush A/B.** After the 5/10, the same batch was run again on both codes in parallel, each with fresh opponent memory and no other batch running:

```
# Phase 0 (4a36da2, the worktree above)
SC2PATH=$HOME/StarCraftII python scripts/run_matches.py --opponent cannon_rush --map all --total 10 --seed 100 --game-seed 5000 --opponent-id m7p0-cannon_rush
# Phase 1 (07d4ddd), rerun
SC2PATH=$HOME/StarCraftII poetry run python scripts/run_matches.py --opponent cannon_rush --map all --total 10 --seed 100 --game-seed 5000 --opponent-id m7p1b-cannon_rush
```

| # | map | variant | Phase 0 | Phase 1, first run | Phase 1, rerun |
|---|---|---|---|---|---|
| 1 | Magannatha | natural | Victory 15:28 | Victory 12:09 | Victory 13:22 |
| 2 | Ultralove | natural | Victory 15:25 | **Tie** (60:00; 11 HOLD deaths far from the point) | **Defeat** 12:43 |
| 3 | Ley Lines | main | Victory 9:59 | Victory 9:43 | Victory 10:19 |
| 4 | Torches | natural | Victory 9:31 | Victory 9:30 | Victory 10:38 |
| 5 | Pylon | main | Victory 9:49 | **Tie** (60:00) | Victory 9:58 |
| 6 | Persephone | main | Victory 9:42 | Victory 9:50 | Victory 9:27 |
| 7 | Incorporeal | natural | Victory 10:48 | Victory 10:50 | Victory 10:41 |
| 8 | Magannatha | natural | **Defeat** 11:47 (6 HOLD far) | **Tie** (60:00; 8 HOLD far) | **Defeat** 9:22 (9 HOLD far) |
| 9 | Ultralove | main | Victory 9:42 | **Defeat** 31:13 | Victory 9:40 |
| 10 | Ley Lines | main | Victory 10:20 | **Defeat** 9:49 | Victory 10:11 |
| | | | **9/10** | **5/10** | **8/10** |

- **The main-variant games are noise.** Games 5, 9 and 10 were lost or tied in the first run, with 24-25 probes and no townhall at 6:00, and won in the rerun with 53 probes. Same code, same seeds.
- **The natural-variant losses share one mechanism**, the same in all three runs of game 8 and in the first run of game 2:
  - The army's anchor is `_rally_point()`: our front base, moved toward the enemy. The CANNON_RUSH plan sets no hold point.
  - When the natural Nexus completes (game 8: its cancel order at 3:14-3:17 came too late), the anchor moves from the main's front (135, 44) to the natural's front (114, 65).
  - Every new unit then walks from the main past the rush Cannons at about (119, 35) and dies on the way: 6-9 per game between 3:47 and 5:28.
  - The Phase-0 code loses game 8 the same way: its units attack-move and still die there. With B2's plain move they don't stop to shoot on the way. Among the natural-variant games, game 2 is the one the Phase-0 code won and Phase 1 didn't, in both runs.
- **This anchor behaviour predates M7.** B2 makes the walk costlier. A fix is put to the user; no change was made.

- The two scout losses happen in probe-scheduling code that M7 didn't change; M5 had none in 40 cheese games. The M3 bar (≥ 7/10 games per batch) holds.
- No crashes and no caught errors in any of the 120 games, and every `ROW` has `log=ok`.

**Notes**
- **Load.** The cheese batches run two bots and two SC2 clients per game. With three of them in parallel (load ~12 on 4 cores), the M6 step guard fired 1-14 times per cheese game, and the worst step was 7.0 s (proxy rax game 6). In the Air batches it fired in 3 of 30 games (once or twice each).
- **One non-proxy flag.** Protoss Air game 6 raised CANNON_RUSH at 2:05 from an enemy probe that stayed in our main for 10 s (UNIT evidence). It expired at 2:30 with the natural still taken ("expand=yes"); it is §4.4's existing rule, not a proxy.

### Phase 1 additions B7 and B8 (user decisions D14-D16), run 2026-10-07

Code under test:
- **`703b084`:** B7 (the army holds the main ramp top while a rush Cannon stands near our main or natural) and B8 (the Observer expansion-trip gate).
- **`d89b6ff`:** the B7 follow-up. `_safe` keeps the whole `HOLD_RADIUS` around a hold point out of finished Cannons' reach, and takes the least-covered step when none is clear. It came from the first two B7 cannon batches, where one game lost 32 holding units within 8 of the ramp hold point.
- **Which batches ran on which:** cannon rush C and D and proxy rax ran on `d89b6ff`; everything else on `703b084`. The follow-up only changes anything when a finished enemy Cannon covers one of our hold points, so it doesn't affect the other batches.

Three batches ran at a time on 4 cores. Logs were kept outside the repo; replays are in `replays/m7-p1b-<race>/`, not in git.

**Summary**

| Criterion (M7_PLAN.md Phase 1, with D14-D16) | Result |
|---|---|
| B7: cannon rush ≥ 8/10 on two runs | **PASS on `d89b6ff`: 9/10 and 9/10.** On `703b084`: 7/10 and 9/10, which led to the follow-up |
| B7: no unit lost walking to a hold point past rush Cannons | **Nearly**: 2 per run, both in game 5 (main variant): a lone Zealot sent to clear the first Cannon walks back once home defense switches to hold. The Phase 1 runs had 22 and 10 |
| B8: no gap over 90 s between main re-scouts from 6:00 while a free Observer exists | **PASS**: 76 re-scouts in the Protoss Air batch (Phase 1: 62). The two longer gaps had no free Observer (below) |
| `reinforce_after_retreat` = 0 | **PASS**: 0 in every game below |
| HOLD `lost_far` in the Air batches | Moved to Phase 2 (D16) |
| D11 targets (end of M7, recorded for progress) | Terran Air 10/10 and Zerg Air 10/10 meet theirs. Protoss Air is 4/10 with free openers and 7/10 with Phase 1's openers; the Phase 1 code scored 8/10 and 6/10 the same two ways (see the variance table) |
| M1: Hard × 10 | **PASS**: 10/10 |
| M4: VeryHard × 10 per race (≥ 7) | **PASS**: Terran 9/10, Zerg 9/10, Protoss 9/10 |
| M2/M3: cheese × 10 (≥ 8/10, correct flag, no scout lost before 4:00 in ≥ 7) | **PASS**: worker rush 10/10, 12 pool 10/10, proxy rax 8/10 (2 ties, below), cannon rush 9/10 and 9/10. Correct flag in every game. Scout criterion: worker rush 9/10 (game 6 again: the fallback main probe killed by a leftover Drone, at 3:09), the rest 10/10 |

**Offline tests** (`poetry run python scripts/<name>.py`):
- `test_m7_rules`: 33/33. It adds `rush_cannon_near`, `safe_hold_point`, `trip_seconds` and `observer_trip_ok`.
- `test_attack_decision` 16/16, `test_threat_flags` 20/20, `test_m3_checks` 14/14, `test_counterattack_rules` 36/36, `test_opponent_memory` 38/38.
- `check_game_log.py` after the batches: `RESULT PASS`, 200 records (the cap), 0 malformed.

**Smoke games** (`703b084`, one game each):
- Cannon rush game 8 (the natural-variant game every earlier run had lost or tied): the plan logged `hold=(128, 36)` at the ramp top, cleared the Cannons from 4:18 to 5:30, and won at 12:47.
- Protoss Air game 1: the Observer re-scouted the enemy main every 60 s from 6:00 to the end (largest gap 61 s), and probes took the expansion trips.

**B7: cannon rush, every run on the same seeds** (`--opponent cannon_rush --map all --total 10 --seed 100 --game-seed 5000`, each run with its own fresh opponent id; W/L/T = win/loss/tie at 60:00):

| # | map | variant | Phase 0 | P1 run 1 | P1 run 2 | B7 A | B7 B | B7+safe C | B7+safe D |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Magannatha | natural | W | W | W | W | W | W | W |
| 2 | Ultralove | natural | W | **T** | **L** | **L** | **T** | W | W |
| 3 | LeyLines | main | W | W | W | W | W | W | W |
| 4 | Torches | natural | W | W | W | W | W | W | W |
| 5 | Pylon | main | W | **T** | W | **L** | W | **L** | **T** |
| 6 | Persephone | main | W | W | W | W | W | W | W |
| 7 | Incorporeal | natural | W | W | W | W | W | W | W |
| 8 | Magannatha | natural | **L** | **T** | **L** | W | W | W | W |
| 9 | Ultralove | main | W | **L** | W | **T** | W | W | W |
| 10 | LeyLines | main | W | **L** | W | W | W | W | W |
| | | wins | **9/10** | **5/10** | **8/10** | **7/10** | **9/10** | **9/10** | **9/10** |
| | | HOLD deaths (farther than 12) | 9 (7) | 22 (22) | 11 (10) | 35 (7) | 55 (2) | 15 (2) | 12 (2) |

Codes: Phase 0 `4a36da2`, Phase 1 `07d4ddd`, B7 `703b084`, B7 + `_safe` `d89b6ff`.

- **Natural-variant games:** all 10 were won on `d89b6ff` (games 1, 2, 4, 7, 8 in both runs).
  - Game 8 had been lost or tied in all three earlier runs: units sent to the natural's hold point walked past the rush Cannons.
  - Game 2 had failed in every run since Phase 1.
- **Main variant:** game 5 (Pylon) is lost or tied in 4 of 7 runs, on every code. The rush Cannons kill the main Nexus by about 3:30 with minerals at 5-10 from 2:30, and the main Nexus dies whatever the army's hold point. It is the known close case from M2.
- **The `_safe` follow-up:** before it, run B lost 36 holding units in game 1. 32 died within 8 of the ramp hold point (128, 36), at about (125, 34), between 3:07 and 12:23.
  - Holding units stand anywhere within `HOLD_RADIUS` (6) without moving, and fight only enemies within `HOLD_ENGAGE_RADIUS` (12) of the point. The nearest Cannon was out of the point's reach but in theirs, and beyond the 12.
  - With the whole radius kept out of reach, HOLD deaths per run fell from 35 and 55 to 15 and 12.

**B8: main re-scouts** (Protoss Air, seed 7000, from 6:00):
- Phase 1 sent 62 main re-scouts; B8 sent 76.
- Phase 1 had 5 intervals over 90 s, all because the only free Observer was on an expansion trip or had died. B8 had 2:
  - game 6, 95 s: one re-scout trip took that long, and the next left the moment it returned;
  - game 8, 5:44: the only Observer took the PvP home post when a Twilight Council was seen (§4.3), so none was free.
- The cost: probes on expansion trips lost per 10 games went from 16 to 19 (22 in the opener-matched batch).
- PvT, Terran Air × 10 (Phase 1 → B8): Observer expansion trips 26 → 2; probe expansion trips 16 → 45; Observer main re-scouts 26 → 42. The log shows the Observer kept for the re-scout 23 times, and Hallucinations ran 25 times, the same as before (B5).

**Protoss Air variance.** The free-opener batch on `703b084` went 4/10, against Phase 1's 8/10, so both codes were run again with each game forced to the opener Phase 1 picked. This is the same method as the Phase 0 comparison: a `git worktree` of `07d4ddd` with `ares-sc2` linked in, run with the same Poetry environment's Python.

```
SC2PATH=$HOME/StarCraftII python scripts/run_matches.py --difficulty VeryHard --race Protoss --build Air --map all --game-seed 7000 --total 6 --opener C_2GateRobo
... --start 7 --total 7 --opener C2_1GateExpand
... --start 8 --total 8 --opener C_2GateRobo
... --start 9 --total 10 --opener C2_1GateExpand
```

| Batch | Openers | Wins | Units lost | HOLD deaths | Probes lost on expansion trips |
|---|---|---|---|---|---|
| Phase 1 (`07d4ddd`), 2026-10-06 | free (picked these) | 8/10 | 475 | 17 | 16 |
| Phase 1 (`07d4ddd`), rerun | forced, the same | 6/10 | 640 | 10 | 18 |
| B7/B8 (`703b084`) | free (5 games differ) | 4/10 | 639 | 28 | 19 |
| B7/B8 (`703b084`) | forced, the same | 7/10 | 714 | 23 | 22 |

- **With the same openers, B7/B8 won 7/10 against the Phase 1 code's 6/10.** The 4/10 batch played a different opener in 5 games and won 2 of them; Phase 1 won all 5 of its own.
- **The same code swings by about ±2 wins in 10 here** (Phase 1: 8 then 6). A 10-game Protoss Air batch can't show a change smaller than that. Phase 2's comparisons should use opener-matched pairs, or 20 games.
- B7 never triggered in the Air games, which had no rush Cannons.

**Regressions**

```
SC2PATH=$HOME/StarCraftII poetry run python scripts/run_matches.py --difficulty VeryHard --race <Terran|Zerg|Protoss> --build Air --map all --total 10 --game-seed <7100|7200|7000> --replays replays/m7-p1b-<race>
SC2PATH=$HOME/StarCraftII poetry run python scripts/run_matches.py --difficulty VeryHard --race <Terran|Zerg|Protoss> --map all --total 10 --game-seed 3000 --opponent-id m7b8-vh-<race>
SC2PATH=$HOME/StarCraftII poetry run python scripts/run_matches.py --difficulty Hard --map all --total 10 --race Terran Zerg Protoss Random --game-seed 4000
SC2PATH=$HOME/StarCraftII poetry run python scripts/run_matches.py --opponent <bot> --map all --total 10 --seed 100 --game-seed 5000 --opponent-id m7b8-<bot>
```

The VeryHard Terran and Zerg batches were cut off at 2 hours, after game 8 and game 7 respectively. They were finished with `--start 9` and `--start 8`, keeping the same opponent ids.

| Batch | Wins | Notes |
|---|---|---|
| Terran Air | **10/10** | |
| Zerg Air | **10/10** | |
| VeryHard Terran | **9/10** | Game 3 (Ley Lines; Phase 1 won it): ONE_BASE_ALLIN from ares's marauder-rush flag held us on one base, then a home fight lost at 9:30-10:00 |
| VeryHard Zerg | **9/10** | Game 3 (Ley Lines), the 12-pool into Roach push lost on every commit since M5 |
| VeryHard Protoss | **9/10** | Game 5 (Pylon; Phase 1 won it): 9 Stalkers and a Zealot hit our 6 units at 4:50, before anything B7 or B8 changes |
| M1: Hard × 10 | **10/10** | |
| Worker rush | **10/10** | Correct flag 10/10; game 6 lost its fallback main probe to a leftover Drone at 3:09, as in Phase 1 |
| 12 pool | **10/10** | Correct flag 10/10 |
| Proxy rax | **8/10** (2 ties at 60:00) | Correct flag 10/10. Phase 1 and M5 went 10/10 on these seeds; see below |

No crashes and no caught errors in any of these games; every `ROW` has `log=ok` and `raa=0`.

**The proxy-rax ties (games 8 and 9) are a stalemate that predates M7, now hit at the margin.**
- In both, the Nexus builders died to the proxy Marines (game 8 at 8:43; game 9 at 3:56, 6:13 and 10:19), so we stayed on one base.
- The PROXY flag never expired: the proxy Barracks was never killed, and the Observer's §5 evidence re-scouts every ~2 minutes never contradicted it.
- With the plan holding the natural and the main mined out from about 14:00, supply peaked at 146 (game 8, 13:00) against the attack's 150 launch gate, so no attack ever went out (`engage=0/0/0`). Value was 3.8k lost against 16.6k killed in game 8.
- The 40:00 structure hunt switched on and off as the Barracks came in and out of vision.
- Phase 1's run of the same seeds had the same one-base state and the same PROXY flag. Its army reached 150 supply and attacked at 11:44 and 11:45, and it won both by 14:00 (in game 9 the flag expired at 12:15, when the Barracks was gone).
- No probes were lost scouting in either run, and there are no Cannons, so neither B7 nor B8 is involved.
- Put to the user as a finding; no change made.

### B9 (user decision D17) and Phase 2 (C1-C5), run 2026-10-08

**B9: clear known proxy production** (`2307de5`). Two proxy-rax runs on the same seeds, each with fresh opponent memory, plus VeryHard Terran (the matchup where PROXY can fire outside the cheese bot):

```
SC2PATH=$HOME/StarCraftII poetry run python scripts/run_matches.py --opponent proxy_rax --map all --total 10 --seed 100 --game-seed 5000 --opponent-id m7b9<a|b>-proxy_rax
SC2PATH=$HOME/StarCraftII poetry run python scripts/run_matches.py --difficulty VeryHard --race Terran --map all --total 10 --game-seed 3000 --opponent-id m7b9-vh-terran
```

| Batch | Wins | Notes |
|---|---|---|
| Proxy rax, run A | **10/10** | No ties; `DEFEND … clearing proxy BARRACKS` at 4:00-4:42 in 9 games; the PROXY flag expired in every game |
| Proxy rax, run B | **10/10** | No ties; cleared at 3:54-4:37 in 9 games; games 3-10 won in 11:14-12:40 (12:14-14:04 before B9) |
| VeryHard Terran | **10/10** | No PROXY flag and no proxy clear in any game: B9 doesn't fire outside real proxies |

The two runs before B9 had tied games 8 and 9 at 60:00 (one base, the proxy Barracks never killed).

**Phase 2 code.**
- `5c61e4e` holds C1-C5.
- `7cf384f` added the fallback hold-down, C4's logged hold reasons and the staged-test fixes.
- `79fdd0e` limits C4's home-fight cooldown to fights worth `LAUNCH_HOME_FIGHT_MIN_FRACTION` (0.2) of the defenders. Without it, a 12-pool bot's trickle of 1-8 Zerglings every 15-20 s held a 200-supply army at home from 9:00 to 21:50, and the game tied. Cannon rush game 3 was held 8:22-17:50 the same way.
- Batches marked † ran on `7cf384f`, the rest on `79fdd0e`. The difference only makes home-fight holds rarer.

**Commands** (Phase 2; logs kept outside the repo, replays in `replays/m7-p2*-<race>/`, not in git):

```
SC2PATH=$HOME/StarCraftII poetry run python scripts/run_matches.py --difficulty VeryHard --race <Terran|Zerg|Protoss> --build Air --map all --total 10 --game-seed <7100|7200|7000> --replays replays/m7-p2-<race>
SC2PATH=$HOME/StarCraftII python scripts/run_matches.py --difficulty VeryHard --race Protoss --build Air --map all --game-seed 7000 --start N --total N --opener <Phase 1's opener for game N>   # "forced", one call per game, as in the B7/B8 section
SC2PATH=$HOME/StarCraftII poetry run python scripts/run_matches.py --difficulty VeryHard --race <race> --map all --total 10 --game-seed 3000 --opponent-id m7p2-vh-<race>
SC2PATH=$HOME/StarCraftII poetry run python scripts/run_matches.py --difficulty Hard --map all --total 10 --race Terran Zerg Protoss Random --game-seed 4000
SC2PATH=$HOME/StarCraftII poetry run python scripts/run_matches.py --opponent <bot> --map all --total 10 --seed 100 --game-seed 5000 --opponent-id m7p2-<bot>
SC2PATH=$HOME/StarCraftII poetry run python scripts/test_engagement.py
SC2PATH=$HOME/StarCraftII poetry run python scripts/test_outranged.py --case <idle_hold|hold_vs_tempest|committed>
SC2PATH=$HOME/StarCraftII poetry run python scripts/test_counterattack.py
```

The `79fdd0e` reruns used the same arguments, with opponent ids `m7p2f-<bot>` / `m7p2f-vh-zerg` and `replays/m7-p2f-zerg`.

**Summary**

| Criterion (M7_PLAN.md) | Result |
|---|---|
| B9: proxy rax ≥ 8/10 on two runs, no tie (on `2307de5`) | **PASS**: 10/10 and 10/10, no tie; no false proxy clear in VeryHard Terran 10/10 |
| Phase 2: Air ratio and launch-then-retreat-within-60-s count better than Phase 1 | **Not shown.** Protoss Air means improve (ratio 1.09 against 1.21; quick retreats 10.7 against 12), but stay inside the same code's run-to-run spread. Terran and Zerg Air were already at 0 quick retreats |
| Phase 2: HOLD `lost_far` in the Air batches below Phase 1's 8 | **Mixed**: 3 and 0 in two Protoss Air runs, 14 in the third (mean 5.7) |
| M1: Hard × 10 | **PASS** † 10/10 |
| M2/M3: cheese × 10 (≥ 8/10, correct flag, no scout lost before 4:00) | **FAIL on proxy rax: 7/10 on `79fdd0e`** (2 losses, 1 tie; below); its flag 10/10 and scout 8/10 pass. Worker rush † 10/10, 12 pool 10/10, cannon rush 10/10 |
| M4: VeryHard × 10 per race (≥ 7) | **PASS**: Terran † 10/10, Zerg 9/10, Protoss † 10/10 |
| M5: staged counterattack 7/7 | **PASS** † |

**Offline tests:**
- `test_m7_rules` 57/57: C1 ranges with stand-in units, C2 eligibility, C3 `retreat_may_shoot`, C5 `outrange_penalty`, plus the Phase 0/1 cases.
- `test_attack_decision` 23/23: the C4 cooldown, remembered-army, intel-wait and restart cases.
- `test_threat_flags` 20/20, `test_m3_checks` 14/14, `test_counterattack_rules` 36/36, `test_opponent_memory` 38/38.

**Staged tests** (`7cf384f`; one game per case, PylonAIE_v4):

| Test | Result |
|---|---|
| `test_engagement.py` | PASS; the C5 rows are below |
| `test_outranged.py --case idle_hold` (B2) | PASS: no Stalker drawn toward the Tempests (closest 10.7, limit 8.5); home defense held |
| `test_outranged.py --case hold_vs_tempest` (C1) | PASS: 1 of 6 Stalkers died (6 of 6 in 13 s before C1); the defensive position moved 4.8 farther from the Tempests; home defense held |
| `test_outranged.py --case committed` (C1) | PASS: home defense engaged (level 6), killed both Tempests, lost no Stalker |
| `test_counterattack.py` (M5, all 7 cases) | **7/7 PASS**. The `merge` case switches the C4 gate off with the supply gate: its forced 20-supply launch can't pass the remembered-army check by design |

C5 in the simulator (`Engagement.level`, most common of 20 calls; raw simulator level and penalty in brackets):

| Scenario | Level (raw, penalty) | ares `can_win_fight` |
|---|---|---|
| 30 Stalkers + 4 Colossi vs 8 Tempests + 4 Zealots | 5 (9, -4) | 10 |
| 30 Stalkers vs 8 Tempests | 5 (9, -4) | 10 |
| 12 Stalkers vs 8 Tempests | 0 (4, -4) | 2 |
| 12 Zealots vs 8 Tempests | 0 (4, -4) | 0 |
| 12 Stalkers vs 4 Void Rays | 10 (10, -0) | 10 |
| **12 Zealots vs 4 Void Rays** | **10 (10, -0)** | **10** |
| 12 Stalkers vs 2 Carriers (no Interceptors) | 10 (10, -0) | 10 |

**The last three rows show the weaponless-unit gap (see "M7 findings").** Void Rays, Carriers and Battlecruisers have no weapon in this game data. The simulator calls 12 Zealots against 4 Void Rays an emphatic win, and C1's rule and C5's penalty don't see them either.

**Air batches** (Protoss: the Phase 1 code's runs as the baseline, since B7/B8 don't touch fights; "forced" means each game forced to the opener Phase 1 picked):

| Batch | Wins | Value lost / killed | Launches | … retreated within 60 s | HOLD deaths (far) | RETREAT deaths | Units lost |
|---|---|---|---|---|---|---|---|
| Phase 1, free openers | 8/10 | 0.94 | 20 | 6 | 17 (8) | 29 | 475 |
| Phase 1, forced | 6/10 | 1.23 | 26 | 16 | 10 (4) | 103 | 640 |
| B7/B8, free | 4/10 | 1.56 | 21 | 12 | 28 (16) | 132 | 639 |
| B7/B8, forced | 7/10 | 1.12 | 30 | 14 | 23 (8) | 112 | 714 |
| **Phase 2 †, free** | 5/10 | 1.17 | 22 | 16 | 43 (3) | 66 | 721 |
| **Phase 2 †, forced A** | 5/10 | 1.26 | 18 | 9 | 37 (14) | 73 | 562 |
| **Phase 2 †, forced B** | 8/10 | 0.85 | 19 | 7 | 6 (0) | 22 | 570 |
| Terran Air: P1 / B7-B8 / **Phase 2 †** | 10 / 10 / **10** | 0.42 / 0.45 / **0.38** | 10 / 10 / 10 | 0 / 0 / 0 | 0 / 0 / 0 | | |
| Zerg Air: P1 / B7-B8 / **Phase 2 †** / **final** | 10 / 10 / **10** / **10** | 0.33 / 0.30 / **0.31** / **0.28** | 10 / 10 / 10 / 11 | 0 | 0 | 0 | |

- **Protoss Air means, Phase 2 against the Phase 1 code:**
  - value lost/killed 1.09 against 1.21;
  - launches retreated within 60 s 10.7 against 12;
  - HOLD deaths far from the point 5.7 against 9 (D16 asked for fewer than 8: two runs, 3 and 0, did; one, 14, didn't);
  - RETREAT deaths 54 against 94.
- All of these are better on average but inside the spread of the same code's runs (±2 wins, ratio 0.85-1.56). **The Phase 2 Air criterion is not shown to be met.**
- The reason is in the logs. In the free batch, C4's remembered-army level read 8-10 at the launches that retreated within 60 s, because the remembered army was mostly Void Rays and Carriers, which the simulator sees as harmless (game 9: "remembered army level 10" against 10-12 Void Rays). Most of those retreats came from the value rule (below 40% of the start value) with the level still at 7.
- **What C1-C4 did** across the three Protoss batches:
  - 4-28 fallback steps per batch;
  - 23-35 "nothing can hit it" holds (C2);
  - 47-60 fight lines with an out-range penalty (C5);
  - 18-28 launches held, mostly for intel (C4).
- C4's waits made the Zerg Air games 1:33 longer on `7cf384f` (10:18 → 11:51), with no losses. On `79fdd0e` they average 10:26 again (`LAUNCH_HOME_FIGHT_MIN_FRACTION`).

**Regressions**

| Batch | Wins | Notes |
|---|---|---|
| M1: Hard × 10 † | **10/10** | |
| M4: VeryHard Terran † | **10/10** | |
| M4: VeryHard Zerg † / final | **9/10** / **9/10** | The usual Ley Lines game 3, both times |
| M4: VeryHard Protoss † | **10/10** | |
| M2/M3: worker rush † | **10/10** | Correct flag 10/10, no scout lost before 4:00 |
| M2/M3: 12 pool (final) | **10/10** | Correct flag 10/10; every game won in 10:02-13:43; no launch held by a home fight. On `7cf384f`, game 2 tied at 60:00 (the home-fight cooldown above) |
| M2/M3: cannon rush (final) | **10/10** | The first 10/10 on these seeds: game 5 (Pylon main variant) won at 9:50; 4 HOLD deaths, none far. On `7cf384f`: 4 of 6 played, games 3-4 took 16-20 min (home-fight holds), game 6 lost |
| M2/M3: proxy rax (final) | **7/10** (2 losses, 1 tie) | Correct flag 10/10; no scout lost before 4:00 in 8/10. Below the ≥ 8/10 bar: see below |
| M5: staged counterattack | **7/7** | |

**The proxy-rax regression (`79fdd0e`, 7/10).** B9's two runs on `2307de5` (the code before Phase 2) won all 10 games, on the same seeds.
- **Games 1 and 2 (lost at 7:45 and 8:09)** are the two games without opponent memory, where the army is 2-3 Zealots when the proxy Marines arrive at 2:37.
  - Before Phase 2, both runs engaged at levels 9-10 (`vs 2-3 MARINE | ours 2-3 ZEALOT`), lost no probe, and won by 9:01.
  - On `79fdd0e` the same fight reads `level 3 < 5 … vs 4 MARINE (200) | ours 2 ZEALOT (200); -4 out-ranged`: the raw simulator level is 7, and C5 subtracts 4.
  - Per the spec (§4.5.2-4.5.3), a Marine (range 5) out-ranges a Zealot (melee) by more than `OUTRANGED_MARGIN` (2). So C5 penalises every fight between melee units and ranged ones. C1 also makes holding Zealots step out of Marine reach, and moves the hold point back (9 fallback steps in each game).
  - The Marines then took the natural: 38 and 43 probes lost, and the Nexus builders killed.
  - After the Zealots died, the remaining defenders were Sentries. A Sentry has no weapon in this game data (see "M7 findings"), so C2 left it out (`hold, nothing can hit it`: 10 and 8 times) and C1 stepped it away from every enemy. 7 Sentries died at hold, 6 of them 12-16 from the point.
- **Games 3-7** (opponent memory pre-raises PROXY, so the plan builds more units early) were won at 12:36-14:21, with 0-1 out-range penalties and 0-1 fallback steps each.
- **Game 8 tied at 60:00:** the one-base stalemate from the B7/B8 run's games 8 and 9.
  - The proxy Barracks was cleared at 4:01, but no Nexus was ever started, although the plan read `expand=yes` from 2:47. Supply peaked at 133, under the 150-supply launch gate, and the main mined out from about 15:00.
  - 37 units died at hold, none far: Adepts 4-8 from the ramp hold point, one at a time, from 9:00 to 26:42, with no home-defense threat logged.
  - The B7/B8 run's game 8 (`703b084`, before Phase 2) lost 24 Adepts the same way and tied the same way. B9's runs won it at 11:50-13:02 on one base, after reaching 146-150 supply with no units lost.
  - So game 8 predates Phase 2. It is not investigated further here.
- Games 9 and 10 were won at 13:33 and 11:45, with the proxy cleared at 4:12 and 4:10 (1 out-range penalty and 1-2 fallback steps each).
- The one earlier proxy-rax game on `7cf384f` (game 1, cut short when the code changed) was won only at 45:35. It shows the same `-4 out-ranged` holds with 2 Zealots against 4 Marines.
- Elsewhere, Zealot-only home defenses were penalised 6 times in the `7cf384f` cannon-rush batch (against a Cannon or Stalkers) and 3 times in the Protoss Air batches (against Stalkers). The 12-pool, worker-rush and VeryHard batches had none.

No crashes and no caught errors in any of these games; every `ROW` has `log=ok` and `raa=0`. `check_game_log.py` after the batches: `RESULT PASS`, 200 records (the cap), 0 malformed, `./data` 494 KB.

**Open for the user:**
- **The out-ranged rules and melee units (the proxy-rax regression above).** §4.5.2-4.5.3 call any enemy whose range beats ours by `OUTRANGED_MARGIN` an out-ranger, and say nothing about melee units. Against Marines, Zerglings excepted, every ranged unit out-ranges a Zealot by that much. So C1 makes holding Zealots step back from Marines, and C5 takes 4 levels off a Zealot defense against them. The spec needs a rule here, so this is put to the user.
- **The weaponless-unit gap.** 12 army types have no weapon in this game data, among them the Void Ray, Carrier, Battlecruiser and our own Sentry.
  - The simulator and C1/C5 don't see the enemy's: the Protoss Air and capital-air goals can't be measured fairly until they do.
  - Our Sentries: C2 leaves them out of home fights, and C1 steps them away from every enemy.
- The 38-minute stalled attack in the `7cf384f` 12-pool game 2 didn't happen again in two replays on `79fdd0e` (wins at 10:46 and 11:06). The ARMY status line now shows the attack squad's centre and its intents.
