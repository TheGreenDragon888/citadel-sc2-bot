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

Other checks on the final code:
- `poetry run python scripts/test_threat_flags.py`: 20/20 passed.
- Ladder zip: `poetry run python scripts/create_ladder_zip.py` builds `publish/Citadel.zip`
  (366 files) with `run.py`, `config.yml` and `ladder.py` at the top level.
