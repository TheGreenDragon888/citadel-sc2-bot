# Audit: macro / main / support modules (MAC-*)

Read-only. Library paths: ares = /home/user/citadel-sc2-bot/ares-sc2/src/ares, python-sc2 = the poetry venv site-packages/sc2.

## Findings (worst first)

### MAC-1  bot/main.py:264-267 (+ 269-284)  bug (measurement)  Verified
Step time covers only `on_step`: `started = time.perf_counter()` at main.py:165, `record_step_time(started)` at :267. Everything registered with `register_behavior` (the whole MacroPlan, Mining, ProductionController, Pylon fallback scan, warp-ins) runs later in `_after_step` (ares main.py:437-451 `behavior_executioner.execute()`, warp-ins, grid reset), which is not timed. Citadel's `_after_step` (main.py:269-284) has no timer.
Impact: mean/p99/max step ms, STEP_WARN_MS warnings and the STEP_GUARD (§6) never see the most expensive work. A slow after-step cannot trigger the guard and the METRIC numbers under-report real cost; timeout risk is invisible.
Fix: time `_after_step` too and add it to `record_step_time` / the guard check.

### MAC-2  bot/error_guard.py:38-47 + bot/main.py (all guards)  design / hidden failure  Verified
`guard()` swallows every `Exception` except `ProtocolError`. A part that fails on every step (e.g. `Production.behaviors` raising inside "macro plan", or ares's own on_step in "ares step") is only visible as: 3 tracebacks (ERROR_TRACEBACKS_PER_PART=3), then one log line per 60 s (ERROR_LOG_EVERY_S), and `errors`/`errors_first` in the end-of-game record (logger.py:386-387). Nothing at runtime reacts (no disable, no escalation, no threshold), nothing reads `errors.total` in bot/ (only scripts/run_matches.py:416). On the ladder, where logs are not read, a permanently dead part (no army production, no scouting) gives no signal except a lost game.
Specific hiding spots:
- "ares step" (main.py:172-173): if ares `on_step` raises early, `self.actual_iteration += 1` (ares main.py:~426) and `run_build()` are skipped every step; the opener never advances (only the 240 s OPENER_TIMEOUT_S rescues it).
- The name "unit destroyed" is reused for 7 different calls (main.py:343-366), so counts merge and `errors_first` shows only the first failing call.
- `on_end` (main.py:392-402) wraps end_report + game_record in one try; failure logs only, is not counted, and skips the game record.
Fix: count-based alarm (e.g. a part failing on >N consecutive steps sets a flag shown in the game record and logged at ERROR every time), unique part names.

### MAC-3  bot/main.py:89-128 on_start  bug / risk  Verified
Component construction in `on_start` is unguarded. python-sc2 main.py:~143-147 catches any on_start exception and resigns with `Result.Defeat`. One constructor error = every game lost instantly. (Probably intended, but it is the only unguarded path.)

### MAC-4  ares winrate data  design (ares behaviour, selection quality)  Verified
Opener choice = ares DataManager. `_get_opponent_data` (ares managers/data_manager.py, dummy entry `{STRATEGY_USED: build_cycle[0], RESULT: 2}`) creates a fake win for cycle[0] when no file exists, and `store_opponent_data` dumps `self.opponent_history` including it. So the first opener of each cycle (A_Standard / B_PvZ / C_2GateRobo / A_vRandom) gets a permanent fake win: it needs only 2 real games for MinGames=3, and its last-10 winrate is inflated until pushed out. Ties (result 1) count as non-wins.
Fix: none in bot code unless the file is pre-seeded; document it.

### MAC-5  Opener win rate vs pre-raised memory  design  Verified (code), impact Likely
When memory pre-raises a cheese flag with `override_opener` (main.py:146-149) the planner calls `set_build_completed()` at the first intel tick (defense_planner.py:269-277), so the "chosen" opener runs only a few steps, yet ares records the game under that opener name (`add_game_to_dict(self.chosen_opening, ...)`). WinrateBased then credits/blames an opener that was not played. Also the schedule for that opener still applies via OPENER_ESSENTIALS + schedule.
Fix: accept, or store the real opener name separately.

### MAC-6  bot/macro/build_executor.py:171-172 `finished`  bug risk  Likely
`finished` requires every `part_of_opener` item to be reached once. Items gated by `only_if` with no `only_if_until_s` (`robo_started` for the natural Pylon/Battery in A/A2/C2; `nat_ready` in C2), by `allow_forge`/`hold_tech`, or by a missing prerequisite (Gateway x3 with no powered spot: see production.py:179-190 docstring, "72 of 140 orders" had no Gateway) may never be reached. Then: `gas_target` stays at the schedule count (4, not 2 per base), `bases_target` never rises to the 4th-base cap (build_executor.py:199-206), the army `ProductionController` waits for PRODUCTION_CONTROLLER_START_S (330 s) only for production, but expansion priority (`prioritize=not executor.finished`, main.py:326) stays on. No timeout ends the schedule.
Fix: give `finished` a time fallback (like PRODUCTION_CONTROLLER_START_S) for gas/bases.

### MAC-7  bot/constants.py:245-258 `_B_SCHEDULE` (B_PvZ)  spec-silent weakness  Uncertain
vs Zerg, B has one Gateway until `ProductionController` starts (schedule finished, ~4:10+, or 5:30). Only B2 adds Gateways (x3 at 3:00). Zerg mix (Zealot 25 / Stalker 25 / Immortal 25 ...) is Gateway-heavy. Spec §4.1 B is silent on Gateways, so not a contradiction.

### MAC-8  bot/macro/production.py:397-416 vs spec §4.5.1  spec  Verified
Spec says Observer "2 fixed" and Sentry 1 vs T; code: Sentry share is 1% of the mix (`ARMY_COMPOSITION_PCT["Terran"]`), i.e. 1 Sentry only after ~100 other units; effectively never built. Not a bug, notes only.

### MAC-9  ladder.py:84  stale call  Verified
`sc2.main._play_game(players[0], client, realtime, portconfig, step_time_limit, game_time_limit)`; python-sc2 signature (main.py:212-219) is `(player, client, realtime, portconfig, game_time_limit=None, rgb_render_config=None)`, so `step_time_limit` lands in `game_time_limit` and `game_time_limit` in `rgb_render_config`. Both are always None, so no effect today.

### MAC-10  bot/main.py:274-284 `_after_step` recovery  bug (minor)  Likely
If the exception comes from python-sc2's part (`_do_actions`), the method returns without clearing `self.actions` / `unit_tags_received_action` (python-sc2 bot_ai_internal.py:867-871), so the same actions may be re-sent next step. Rare.

### MAC-11  Memory unused fields  dead-ish  Verified
`wins`, `losses`, `first_aggression_time` in the opponent record are only logged (`OpponentStore.load` log line, `opponent_games_before`); nothing in bot/ reads them to change behaviour (grep of bot/ for `.record[` / `first_aggression_time` finds only logger.py and opponent_store.py).

No other dead code found: `ReserveForStructure` (static_defense.py:50,155), `KeepBank`, all `CONDITIONS` keys, `external_tags`, `data_root` are used. `OPENER_ESSENTIALS_GAS_WAIT_S` is used inside constants.py:307.

## YAML check (protoss_builds.yml, config.yml) against ares
All names ares parses: `UseData`, `BuildSelection`, `MinGamesWinrateBased`, `BuildChoices`/`Cycle`, `Builds`, `OpeningBuildOrder`, `AutoSupplyAtSupply`, `ConstantWorkerProductionTill` (ares consts.py:25-86, build_order_runner.py:138-157). Race keys Terran/Zerg/Protoss/Random equal `Race.name` (checked). `test_123` = TEST_OPPONENT_ID, used when `Debug: True`. Step words: `pylon`, `gate`, `core`, `gas`, `expand`, `worker_scout`, `warpgateresearch`, `adept`, `stalker` all parse (checked in the venv: PYLON/ADEPT/STALKER are UnitTypeId members, WARPGATERESEARCH an UpgradeId, GAS/CORE/GATE/EXPAND/WORKER_SCOUT are BuildOrderOptions only). `@ ramp` -> BuildOrderTargetOptions.RAMP. config.yml keys are valid ares keys (`ActiveGrid: TacticalGround` is allowed). No unknown option found. `BuildSelection` is read once and stored but never used by ares (the yml comment is right).

## Hook order vs ares-sc2/src/ares/main.py (verified)
python-sc2: `_prepare_step` -> `issue_events` (on_unit_* hooks, before on_step) -> `on_step` -> `_after_step`. Citadel.on_step: `super().on_step` (ares: managers update, run_build, scout role reset, actual_iteration+1) first, then Citadel work, then Citadel._after_step -> ares `_after_step` (behaviors, archon/drop/zerg actions, grid reset, warp-ins) -> python-sc2 `_after_step` (sends actions). on_start: ruleset + wall.prepare before `super().on_start()` (managers, runner, executioner), the rest after. Order is consistent with ares.

## Capability summary

**Per-step order (main.py on_step; GameStep 2 = one call per 2 loops)**
Every step: ares step; Mining registered (long-distance off during cannon rush / wall hold); opener timeout (240 s -> `set_build_completed`, `opener_ended_by="timeout"`); worker_defense; army micro; telemetry; step-time check.
Every 8 steps: ares bridge, enemy-mix tracker, detectors, flag expiry, defense planner.
Every 4 steps (MACRO_EVERY_STEPS): scouts (skipped when step-guarded); static defense, gateway upkeep (morph Warp Gates, re-power), defense behaviors, chrono, then the MacroPlan (after the opener) or only defense behaviors (during the opener).
Every 4 steps (ARMY_EVERY_STEPS): wall holder, endgame update, army.step.
MacroPlan priority (stops at the first behavior that acts): Pylon timing -> defense units/buildings -> probes (to 66, +8 with a 4th base) -> ReserveForPending Nexus -> timed schedule items -> gas -> expansion -> KeepBank -> (if no schedule item waits for money) upgrades, Observers, early Stargate (capital air), extra Gateway/Pylon, Templar floor, mix SpawnController, mineral-float spawn, ProductionController.

**Openers** (all share the first ~2:30; the YAML lists are identical within A/A2, B/B2; only the timed schedules in constants.py differ)
- A_Standard / A_vRandom (vs T / Random): 14 pylon, 16 gate, scout, 17 gas, 20 nexus, 20 core, 21 gas, 22 pylon, WG research, Adept (Stalker vs Random). Hand-over when the last unit step completes. Then Robo 2:50 + Observer + natural Pylon/Battery, Gateways to 3 at 3:30, gas to 4 at 3:45, Forge + +1 weapons 4:15, 3rd Nexus 4:45.
- A2_Safe / A2_vRandom: same, 2nd Gateway 2:30, 3rd Nexus 5:30.
- B_PvZ (vs Z): same YAML; Pylon nat 2:40, Stargate 2:45 + one Oracle, 2 Batteries at nat 3:00, gas 4, 3rd Nexus 3:50 (waits for no ling/roach/ravager flag until 5:30), Robo + Observer 4:00.
- B2_PvZSafe: Robo 2:45 instead of Stargate, 3 Gateways at 3:00.
- C_2GateRobo (vs P): 14 pylon, 16 gate, scout, 17+18 gas, 19 core, 21 pylon, WG, Stalker; 2nd Gate 2:20, Robo 2:50, Nexus 3:10 + Battery, 3rd base 5:30 unless enemy has a third.
- C2_1GateExpand: same plus 23 Nexus in the YAML; Robo 2:50, 2nd Gate 3:10, 3rd base 5:00 unless enemy expanded.
Ending early: threat flag with override (planner), memory pre-raise, or 240 s timeout; then OPENER_ESSENTIALS (Gateway, Core, gas, WG, natural) are prepended.
Choice: ares DataManager, file `./data/<OpponentId>-protoss.json` (list of {Race, Duration, Strategy, Result}). Until each build in the race's 2-build cycle has 3 games: repeat after a win, next after loss/tie; then best winrate over each build's last 10 games, ties cycle. Local runs: `None-protoss.json`. Caveat MAC-4.

**Composition** (constants.py:326-341, production.py): vs T Stalker 30 / Zealot 20 / Immortal 15 / Colossus 25 / Sentry 1; vs Z Zealot 25 / Stalker 25 / Immortal 25 / Colossus 10 / Archon 15 + High Templar 8; vs P Stalker 40 / Immortal 25 / Colossus 25 / Zealot 10; Random counts as T until the race shows. Observers fixed at 2. Switches: Archon share vs T when remembered enemy is bio-heavy, vs P when Zealot-heavy (Templar morphed to Archons); air switch (+30 Stalker pct) when AIR_HARASS is active and enemy air share >= threshold; vs Z with air, Archon/HT shares go to Stalkers; capital-air mode (Colossus capped at 5%, +15 Stalker, +25 Tempest vs T/P, +25 Void Ray vs Z, +15 Tempest more vs Carriers) and an early Stargate/Blink move. Gas-starved with 700+ minerals: Zealot float (not vs air). Extra Gateways when minerals stay >=1000 for 20 s (cap 20). ProductionController adds buildings for the mix (max 12 per type) from the end of the schedule or 5:30; defense plan gates tech (`hold_tech`).
Upgrades (from 5:00; one per building, in parallel): Forge weapons1, weapons2, armor1, armor2; Twilight Blink then Charge (Charge then Blink vs Z); Robotics Bay Extended Thermal Lance; Templar Archives Psionic Storm (vs Z only). Tech timing: Forge 5:00 (A/A2 4:15), Twilight 5:30, Templar Archives 8:00 vs Z only; Twilight/Archives wait for 2 finished Nexuses; Robo Bay / Fleet Beacon only via ProductionController tech-up.
Bases: 3 (MAX_BASES); 4th when minerals >=1500, gas-starved >=60 s of the last 120 s, lines saturated, expansion allowed. Probes: 66, +8 with a 4th; held-plan cap 22 per ready base + 6.
Never built: Disruptor, Warp Prism, Dark Templar, Phoenix, Carrier, Mothership, Sentry in practice (1%), Adept beyond the opener unit, Oracle beyond the single B-opener Oracle, Void Ray/Tempest outside capital-air mode. Never researched: shields, +3 anything, Resonating Glaives, Gravitic Boosters/Drive, Flux Vanes, air upgrades. Chrono never goes to Gateways/Warp Gates (except proxy plan), Robo Bay, Templar Archives.

**Far ahead / far behind:** macro has no such switch. Nothing in main.py/production.py/economy.py/build_executor.py reads relative army or economy. Plan changes come only from threat flags (defense planner: hold tech/expansion, unit priority, bank), enemy-mix switches, and mineral-bank rules. The only value-ratio logic is in the army (attack_decision / endgame, §4.7), not macro.

**Opponent memory** (`./data/opponents/<id>.json`): games, wins, losses, threats_seen (per game: threat, time, detector source; last 20 games), earliest first_aggression_time. Next game it changes only: cheese flags (WORKER_RUSH, CANNON_RUSH, POOL_12, PROXY, ONE_BASE_ALLIN) raised in >=2 of the last 3 games are pre-raised at 0:00 (ends the opener, except POOL_12 which keeps it until its expand step). Opener win rates live separately in ares's file. Nothing else is learned (no map, enemy composition, timings, race, win/loss by opener, tech such as DT/air).

**Telemetry usable as a tuning objective** (METRIC game JSON, `./data/logs/games.jsonl`, logger.py:334-408): `result` + `tie` + `game_length_s` (primary); `probes` at 4/6/8:00, `bases` at 6:00/10:00, `supply_blocked_s`, `unspent` minerals/gas at 6:00/10:00 (macro efficiency); `army_value.lost/killed` (fight efficiency); `first_aggression`, `flags`, `engage` (own/enemy value per decision), `lost_by_intent`, `lost_far`; `errors` (must be 0) and `step_ms` p99/guard counts as constraints. Gaps: army_supply, income/collection rate, idle production time and gas count are in the snapshots but not exported in the record; step_ms excludes after-step work (MAC-1).

## Footer
(a) Files read fully: bot/main.py, bot/ruleset.py, bot/error_guard.py, bot/data_files.py, bot/geometry.py, bot/macro/{build_executor,economy,production,supply}.py, bot/memory/opponent_store.py, bot/telemetry/logger.py, run.py, ladder.py, config.yml, protoss_builds.yml, ares build_order_runner.py, data_manager.py (selection/storage parts); bot/constants.py lines 1-190, 216-545, 545+ (memory/telemetry/error parts); DESIGN.md §1-4.1, 4.5.1, 5 (memory), 6, 7, 8 parts.
(b) Calls checked and correct: AresBot.on_start/on_step/_after_step/on_end/on_unit_*; build_order_runner.set_build_completed/build_completed/chosen_opening/build_step; behavior_executioner.behaviors; grid_manager.reset_grids; BuildStructure, SpawnController, ProductionController, UpgradeController, GasBuildingController, ExpansionController, BuildWorkers, Mining (fields and kwargs); mediator.request_building_placement, select_worker, build_with_specific_worker, can_place_structure, get_building_counter, get_building_tracker_dict, get_own_nat, get_own_expansions, get_own_army_dict/structures_dict (defaultdict), get_own_unit_count, get_unit_role_dict; ai.unit_pending, structure_pending, not_started_but_in_building_tracker, pending_or_complete_upgrade, tech_ready_for_unit, ready_townhalls, gas_buildings, supply_workers/army, already_pending_upgrade, research, can_afford, calculate_cost, calculate_unit_value, get_available_abilities, get_terrain_z_height, game_data.units[..]._proto.food_provided and .cost.time (frames, ratio use is consistent), Unit.is_memory, _units_previous_map and the enemy maps, ProtocolError, Result names, opponent_id attribute (python-sc2 bot_ai_internal.py:82-85).
(c) Not checked: army/, intel/, defense/ internals (other auditors), ares Mining behaviour at workers_per_gas=1, real game behaviour (SC2 not installed), whether `EFFECT_CHRONOBOOSTENERGYCOST` appears in the 4.10 ability query (matches ares's own usage), the compiled cython_extensions `cy_unit_pending`.
