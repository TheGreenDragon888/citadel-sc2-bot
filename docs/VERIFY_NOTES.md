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

## M7 baseline

## M7 acceptance evidence
