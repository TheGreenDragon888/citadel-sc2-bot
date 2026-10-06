# DOCUMENT 2 — DESIGN DOCUMENT FOR CLAUDE CODE (v2)

> Audience: an AI coding agent that has not seen the research. Everything needed is here. **TUNE** marks a starting value to adjust through testing. **VERIFY** marks an API or behaviour you must confirm in source before relying on it (see §11). Labels: **Verified** (confirmed in docs or code, or by several sources), **Likely**, **Uncertain**.

## 1. Overview

**Vision.** Citadel is a Protoss bot for the AI Arena StarCraft II ladder. It is economy-first, defense-first and information-driven. It gathers heavy scouting information to build defensive plans and to find weaknesses in the opponent.
1. **Economy-first:** it keeps building probes until 66 (TUNE; more with a 4th base, §4.5.1), saturates quickly, and expands on schedule unless a threat flag vetoes it.
2. **Defense-first:** it holds worker rushes, cannon rushes, 12-pools, proxy Barracks/Gateways and early one-base all-ins.
3. **Information-driven:** it follows a per-matchup scouting schedule (§4.3), and rule-based threat flags (§5) turn sightings into the defensive branches it chooses.

**Win condition (v1).**
- **Primary:** macro to 3 bases (a 4th when gas-starved with a mineral bank, §4.5.1, M7), then build a Blink Stalker/Immortal/Colossus/Zealot army with +1/+2 weapons. Vs Z it adds High Templar (Psionic Storm) and Archons; vs T and P, small Archon shares against bio and Zealot-heavy armies (§4.5.1). Launch the max-out attack using the gates on `EngagementResult` (§4.5.2). After a won fight, work down the target list in §4.5.2. After a retreat, fall back to the defensive position at our newest base and re-max.
- **Secondary (v1):** counterattack when the enemy army is out of position (§4.6).
- **Tie avoidance:** games reaching 80,640 loops (60:00) end in a tie (Verified, user-supplied controller source). The end-game rules in §4.7 apply from 40:00.
- **Why:** a bot that out-mines and out-defends its opponent has a bigger army by about 8–10 minutes. The risk is spending it badly, and gating attacks on the simulator is the fix.
- **Beyond v1:** Carriers and Skytoss as the main army. (Void Rays and Tempests are in v1 only as the answer to enemy capital ships, §4.5.1, M7.)

**Definition of done for v1:**
- Beats built-in VeryHard in ≥ 70% and Harder in ≥ 90% of games, across T/Z/P, on at least 3 of the 7 pool maps.
- Survives worker-rush, cannon-rush, 12-pool and proxy-rax test bots in ≥ 80% of games.
- No crashes. No `TimeOut` loss. Mean step ≤ 15 ms, p99 ≤ 40 ms, and no step over 1 s.
- Runs on AI Arena with "bot data enabled" on, and writes the opponent log to `./data`.

## 2. Technical stack

- **Framework:** ares-sc2, used through the official template `AresSC2/ares-sc2-bot-template`, which includes ares as a git submodule. The bot class subclasses `AresBot`. Plain python-sc2 calls are allowed anywhere. ares v3.13.1 was released on Sept 5, 2026 (GitHub releases, Verified). Pin the submodule commit in the README.
- **Python:** 3.12, which matches the ladder image `aiarena/aiarena-docker-base` (Verified, user-supplied). Dependency manager: Poetry, as the template uses.
- **Game:** local testing on SC2 Linux headless 4.10 (Build 75689) with the AIE maps. The ladder uses the same 4.10 engine, but the AIE maps embed newer balance data (sc2patch README, Verified), so never hard-code balance numbers (§4.0).
- **Local environment:** SC2 lives at `~/StarCraftII`, and python-sc2 finds it through the `SC2PATH` environment variable. Maps live directly inside `~/StarCraftII/Maps`; the folder name is case-sensitive (`Maps`, not `maps`). Edit `MAPS_PATH` in `run.py` if the maps live elsewhere.
- **Dependencies:** only those in the template (ares-sc2, python-sc2, numpy, cython-extensions-sc2, map analyzer, the sc2-helper combat sim, and pyyaml, which ares already uses), plus the standard library `dataclasses` and `json`. Add nothing else in v1.
- **AI Arena packaging:**
  - A zip of at most 50 MB with `run.py`/`ladder.py` at the zip root, not inside a folder.
  - Build it on Linux with the template's `scripts/create_ladder_zip.py`, or through the template's GitHub Actions workflow, which produces the artifact `ladder-zip.zip` on every push to `main`.
  - Check the layout with `unzip -l` before uploading: `run.py` must appear at the top level. If zipping manually, zip the bot folder's contents, not the folder itself.
  - The bot must accept the ladder arguments `--GamePort`, `--LadderServer`, `--StartPort` and `--OpponentId`; the template's `ladder.py` handles these.
  - Write only to `./data`, and keep that folder under 5 MB.
  - Network access is forbidden.
- **Bot data (Verified, user-supplied):** the ladder restores `./data` before each match and saves it afterwards, independently of the zip. Uploading a new version does not clear it. It only works when the bot's "bot data enabled" setting is on. WinrateBased opener selection and the opponent memory both depend on it.
- **Map pool:** MagannathaAIE_v2, UltraloveAIE_v2, LeyLinesAIE_v3, TorchesAIE_v4, PylonAIE_v4, PersephoneAIE_v4, IncorporealAIE_v4. Put all 7 in `MAPS_PATH` for testing.

## 3. Architecture

```
citadel/
  run.py / ladder.py          # template entry points (local run / ladder args)
  config.yml                  # bot name, race=Protoss, debug flags
  protoss_builds.yml          # ares build-runner openers; BuildSelection: WinrateBased (§4.1)
  bot/
    main.py                   # CitadelBot(AresBot): on_start/on_step/on_end orchestration
    constants.py              # every TUNE value, EngagementResult thresholds, ARES_INTEL (§4.2)
    ruleset.py                # detects 12- vs 8-worker ruleset on loop 0 (§4.0)
    intel/
      ares_bridge.py          # reads ares IntelManager flags + UnitMemoryManager each eval tick
      detectors.py            # Citadel-only detectors (cannon rush, proxy, no-natural, tech, air, capital air, DT, timing, out-of-position)
      enemy_mix.py            # M7: remembered enemy army shares (bio, Zealot, air) and capital-air value, from ares's army cache
      threat_flags.py         # ThreatFlag store with expiry rules (§5)
      scout_planner.py        # per-matchup scouting schedule (§4.3)
    macro/
      economy.py              # probe production, saturation, gas timing, chrono, expansions
      build_executor.py       # selects/overrides ares build runner; post-opener macro rules
      production.py           # army composition targets -> ares ProductionController
      supply.py               # pylon timing
    defense/
      defense_planner.py      # maps active threat flags -> DefensePlan (structures, unit holds)
      worker_defense.py       # worker-rush & cannon-rush probe pulls
      static_defense.py       # batteries/cannons placement
      wall_fallback.py        # ramp wall fallback for non-standard ramps (§4.8)
    army/
      squads.py               # squad roles: DEFEND, ATTACK, HARASS, SCOUT
      micro.py                # ares CombatManeuver wrappers (stalker kite, retreat, out-ranged rule; §4.5.3)
      blink.py                # M7: Blink rules (blink back, blink onto out-rangers, blink to finish; §4.5.3)
      templar.py              # M7: High Templar control (Psionic Storm, staying behind, Archon morphs; §4.5.3)
      attack_decision.py      # main attack/retreat on EngagementResult (§4.5.2)
      counterattack.py        # out-of-position counterattack (§4.6)
    memory/
      opponent_store.py       # ./data/opponents/<OpponentId>.json read/write
    telemetry/
      logger.py               # per-game metrics -> ./data/logs (bounded) + stdout
```

**Per-step flow** (`on_step(iteration)`):
1. ares updates its own managers, including unit memory, before your code runs (Likely; VERIFY the order in `main.py`, §11.9).
2. Every 8 steps:
   - `ares_bridge.update()` copies the ares intel booleans into flags.
   - `detectors.update()` runs Citadel's own detectors.
   - `threat_flags.expire()` applies the expiry rules.
   - `defense_planner.update()` produces the active `DefensePlan`.
3. `build_executor.step()`:
   - While in the opener, let the ares build runner run unless a flag with `override_opener=True` is active. An override calls `self.build_order_runner.set_build_completed()` (Verified API exists) and switches to the defensive macro rules.
   - After the opener, apply the macro rules.
4. Every 4 steps: `economy.step()` (probes, gas, chrono, expansions, subject to `DefensePlan.allow_expand`), `production.step()` (unit mix from the matchup and active flags) and `scout_planner.step()` (assign or advance scouting tasks).
5. Every step: `worker_defense.step()` and squad micro (including Blink and High Templar control, M7).
6. Every 16 steps: `attack_decision` and `counterattack`. The combat sim runs at most twice per evaluation.
7. `telemetry` records step timings and, every ~30 s of game time, a snapshot.

**Order of authority when components conflict:** Defense > Economy > Scouting > Counterattack > Main attack. The defense planner can veto expansions, pull probes, pin squads at home, and recall a counterattack squad at any moment. A counterattack must never pull units the defense planner needs.

## 4. Strategy specification

All times are **game time** at "faster" speed; `self.time` in python-sc2 is in seconds. 22.4 game loops = 1 s. Supply counts are `supply_used`. Timings are for the 12-worker ruleset unless a line says otherwise; the 8-worker shifts are given where they apply.

### 4.0 Ruleset detection
Patch 5.0.16 (8 starting workers, 13 Nexus supply, Warp Gate rework) is live on the human ladder (Verified). Which patch the AIE ladder maps replicate is Uncertain, so Citadel detects the ruleset at runtime.
- On loop 0, `RULESET = "816" if len(self.workers) <= 8 else "1215"`. Log the value and `self.supply_cap`: 13 means 5.0.16 Nexus supply, 15 means pre-5.0.16.
- Use `f"{race}_{RULESET}"` as the opener key group in `protoss_builds.yml`.
- Never hard-code unit stats. Read `self.game_data` (e.g. `calculate_cost`), and read Warp Gate availability from the research state and ability availability at runtime. VERIFY that the Warp Gate research ability ID exists on Gateways under the AIE data.

### 4.1 Openers (ares build runner, `BuildSelection: WinrateBased`)
Encode the openers in `protoss_builds.yml`. Per-opponent selection uses `BuildSelection: WinrateBased` (Verified, user-supplied), keyed by opponent ID or race, instead of custom logic. Each race gets 2 openers so the runner has a choice; ares also "cycle[s] through them on defeat" (ares docs, Verified). VERIFY the exact YAML schema against the build runner tutorial and an example bot before writing the file.

Chrono Nexus probes until the Cybernetics Core completes, then chrono Warp Gate research.

**12-worker ruleset.** These follow standard LotV structure (Likely; they correspond to Liquipedia's MC 1 Gate FE for PvT, "fastest Robotics Facility… skip an early Sentry", and a Gate-Nexus-Stargate for PvZ).

- **A. "Citadel Standard" (vs T, and vs Random while the race is unknown):**
  1. 14 Pylon at `main_base_ramp.protoss_wall_pylon`, or the fallback (§4.8).
  2. 16 Gateway at a `protoss_wall_buildings` position → send the scouting probe immediately.
  3. 17 Assimilator.
  4. 19/20 Nexus (~1:25–1:40, TUNE).
  5. 20 Cybernetics Core (second wall slot).
  6. 21 Assimilator.
  7. 22 Pylon.
  8. At Core done: Warp Gate research, plus 1 Adept (vs T) or 1 Stalker (vs Random).
  9. ~2:50 Robotics Facility → first unit Observer. Shield Battery at the natural when the Robotics Facility starts.
  10. ~3:30 2nd and 3rd Gateway; 3rd/4th gas at ~3:45.
  11. ~4:15 Forge (+1 weapons); Immortal production.
  12. ~4:45 3rd Nexus if `DefensePlan.allow_expand`.
- **A2. Safe (vs T):** same as A, but the 2nd Gateway goes down at 2:30 and the 3rd Nexus waits until 5:30. WinrateBased chooses between A and A2.
- **B. PvZ (race known):** A up to the Core, then:
  - 1 Adept (shade to scout at ~3:00, §4.3), Warp Gate.
  - ~2:45 Stargate → 1 Oracle (scouting and Revelation; kill drones only if no Queen or Spore is within 10).
  - 2 Shield Batteries at the natural by 3:30.
  - Robotics Facility at ~4:00.
  - 3rd Nexus at ~3:50–4:15 if no ling, roach or ravager flag is active.
- **B2. PvZ safe:** as B, but a Robotics Facility replaces the Stargate and a 3rd Gateway goes down at 3:00.
- **C. PvP, 2 Gate Robo (Liquipedia "ultra-safe" answer to 4-gate; prioritises safety against 4-gate):**
  1. 14 Pylon.
  2. 16 Gateway (scout).
  3. 17 Assimilator.
  4. 18 Assimilator.
  5. 19 Cybernetics Core.
  6. 21 Pylon.
  7. At Core done: Stalker + Warp Gate.
  8. 2nd Gateway at 2:20.
  9. Robotics Facility at 2:50, Observer first.
  10. Nexus at 3:10.
  11. Shield Battery at the natural.
  - No 3rd base before 5:30 unless the enemy has one.
- **C2. PvP 1-gate expand (for use against macro opponents):**
  1. 14 Pylon.
  2. 16 Gateway (scout).
  3. 17 Assimilator.
  4. 18 Assimilator.
  5. 19 Cybernetics Core.
  6. 21 Pylon.
  7. At Core done: Stalker + Warp Gate.
  8. 23 Nexus (~2:30–2:45).
  9. ~2:50 Robotics Facility (Observer first).
  10. Shield Battery at the natural when the Nexus finishes.
  11. 2nd Gateway ~3:10.
  - Never take a third before 5:00 unless the enemy has also expanded.

**8-worker ruleset (Uncertain; TUNE):**
- Shift every supply trigger down by 4 (14 Pylon → 10 Pylon, and so on) and every time trigger later by ~20 s.
- Nexus supply is 13, so the first Pylon trigger is `supply_left ≤ 2`.
- Morph Warp Gates only when the warp-in position matters. Blizzard's 5.0.16 notes call the Warp Gate cost "an one time cost and once purchased, the player can switch between the different gateway modes for free", while a secondary guide says 25/25 per morph. VERIFY in game which one applies under the AIE data.
- Otherwise produce from Gateways. Blizzard's 5.0.16b hotfix notes say: "Gateway unit train time reduction bonus from researching Warp Gate increased from 40% to 50%".
- Chrono: Nexus probes until the Core is done, then Warp Gate research.
- No pro 8-worker builds were found. Replace these with sourced builds when they become available (§12, Open Question 2).

### 4.2 Defensive plans per threat — who detects what
Citadel reuses the ares IntelManager wherever it has a detector. The ares detector list is Verified (user-supplied), but its exact triggers and thresholds are **Uncertain** because `intel_manager.py` has not been read yet. On Day 1, read that file and fill in `constants.ARES_INTEL` with each flag's mediator name, trigger condition and time window, and whether it ever resets. If an ares flag never resets, Citadel's flag still expires by its own rule (§5).

| Threat | Detector | Citadel trigger (added or backup) | Plan |
|---|---|---|---|
| **Worker rush** | ares worker-rush flag | Local backup: ≥ 5 enemy workers within 30 range of our main before 2:00. This catches the rush before the ares flag fires | Pull all probes except 2. Focus-fire the enemy worker with the lowest HP+shield. Pull a probe back to mine when its HP+shield < 15 and swap in a fresh one. Keep building probes. Continue the Gateway; the first Zealot is top priority. End the pull when enemy workers near our base are ≤ 1 |
| **Cannon rush** | **Not in ares** | `detectors.cannon_rush`: enemy Pylon, Forge or Photon Cannon within 25 of our main or natural townhall before 4:00, or an enemy probe inside our main between 1:00 and 3:00 for > 10 s | Attack an **unfinished** Pylon with 3 probes and each unfinished Cannon with 4 probes (the proven CreepyBot pattern is 1 drone per probe and 4 per cannon). Kill the enemy probe with 1–2 probes. If a Cannon completes: stop the probe attack, build out of its range, get Stalkers or an Immortal, and cancel the natural if the Cannon covers it. Cancel our own structures that are about to die |
| **12-pool / early lings** | ares ling-rush flag | `detectors.early_pool`: Spawning Pool seen before the natural Hatchery, or lings seen before 2:20 (+20 s for 8-worker) | Cancel or delay the natural Nexus if it is not yet started. Build a Zealot or Adept from the Gateway. Hold the ramp gap with that unit (`protoss_wall_warpin`/gap position, or the fallback in §4.8). Add a Shield Battery in the main. Probes defend only against lings in the mineral line. Resume the Nexus once we have ≥ 3 units and no lings within 20 |
| **Proxy Barracks** | ares marine-rush and reaper flags (unit-based) | `detectors.proxy`: 0 Barracks in the Terran main at 1:45, or SCV count ≤ expected − 2, or a production structure seen > 50 from the enemy main (M7: the missing-production test waits for the natural to be seen and skips an expansion-first opening, §4.4 rows 7 and 10) | Keep the probe count up but skip the natural until 2 units are out. Add a 2nd Gateway and a Battery in the main. Hold at the top of the ramp. Stalkers vs Reapers. Chrono the Gateway units |
| **Proxy Gateway** | ares proxy-Zealot flag | Same structure test as proxy Barracks, using Gateways | Same as proxy Barracks |
| **One-base all-in** (roach/4-gate/3-rax) | ares roach, ravager, marine, marauder and four-gate flags | `detectors.no_natural`: no natural townhall by 2:45 (T/P) or 2:15 (Z) (+30 s for 8-worker), plus ≥ 2 gas or ≥ 3 production structures | 2–3 Batteries at the natural (or the main if the natural isn't taken). All Gateways producing. Delay the 3rd Nexus and the Forge. Army holds at the natural choke. Immortals first vs roaches |
| **Air / cloak** (Oracle/Banshee/Mutas/DTs) | **Not in ares** | `detectors.tech`: Stargate, Starport with tech lab, Spire, Dark Shrine, or Twilight with no expansion. M7 builds the air part (AIR_HARASS: Stargate, Starport with tech lab, Spire) | Build the Forge now, then 1 Photon Cannon + 1 Battery per mineral line. Observer at home vs DTs (build a Robotics Facility if none). Stalkers vs Mutas, plus Psionic Storm vs Z; Archons are not used as anti-air (M7, user decision) |
| **Capital air** (Tempest/Carrier/Mothership, Battlecruiser, Brood Lord) — M7 | **Not in ares** | `detectors.capital_air`: WARNING when a Fleet Beacon, Fusion Core or Greater Spire is seen; ACTIVE while the capital ships seen recently are worth ≥ `CAPITAL_AIR_MIN_VALUE` (TUNE, about one unit) | WARNING: one Stargate early, and Blink moves up the Twilight chain. ACTIVE: the capital-air mix (§4.5.1), for every race |
| **Timing attack** | **Not in ares** | `detectors.timing`: remembered enemy army value > 1.3× ours, with its centroid moving toward our bases (distance shrinking over 2 evaluations) | Pull the army to the natural choke next to the Batteries. Keep producing. Don't expand |
| **Macro opponent** | ares expansion and greedy flags | Nothing (the pattern: natural taken on time, 3rd base by 4:30) | Allow our 3rd Nexus on schedule; an optional 4th at ~7:00 |

### 4.3 Scouting schedule (per matchup)
The Oracle Stasis Ward is cut, and Phoenix production is PvZ-optional only. The sharpy-sc2 `HallucinatedPhoenixScout` and `DoubleAdeptScout` acts show these patterns in a public bot framework (Verified, sharpy wiki).

All scouts use ares `KeepUnitSafe` and path with `find_path_next_point` on `mediator.get_air_grid` or the ground grid (VERIFY the grid accessor names). They retreat below 50% HP+shield. Take the probe scout from `UnitRole.BUILD_RUNNER_SCOUT` (Verified).

**Common to all matchups:**

| Time | Unit | Task | Information |
|---|---|---|---|
| 0:40 or Gateway placement | Probe | Go to the enemy main (`enemy_start_locations[0]`) and circle it, check the natural at ~1:30, then return through the likely proxy spots (map-analyzer regions within 40 of our natural) | Race (vs Random), gas count/timing, Pool/Barracks/Gateway timing, worker count, natural timing, proxy structures |
| 1:00–1:40 | 2nd probe, only if the enemy main showed fewer structures than expected | Patrol our main edge and natural perimeter | Cannon-rush Pylons, proxies |
| 4:30, then every 60 s | Probe or Observer | Visit each unscouted enemy expansion location. The §5 main re-scout comes first: while it is due, no Observer goes on an expansion check (M7) | Base count |
| From 6:00 | Observer | Travels with the army | Fresh engagement intel for the combat sim |

**Per matchup:**

| Matchup | Time | Unit | Information |
|---|---|---|---|
| PvT | Core + ~40 s | Adept shade into the main | Factory/Starport count, tech lab or reactor, Barracks add-ons |
| PvT | Robo + ~30 s | Observer 1 → the path from the enemy natural to our natural | Army movement, drops, tanks |
| PvT | 5:30, then when the main is stale > 90 s | Hallucinated Phoenix | Starport count, Armory, Fusion Core, Ghost Academy |
| PvZ | ~3:00 | Adept shade into the natural or main | Roach Warren, Baneling Nest, ling count, 3rd base |
| PvZ | ~3:45 | Oracle (1 only), flying over the main and third | Drone count, 3rd/4th base, Lair. Cast Revelation on the largest clump if castable (VERIFY cost); Revelation keeps vision on those units. Kill drones only if no Queen or Spore is within 10 |
| PvP | Core + ~30 s | Stalker poke at the natural | Unit count, Nexus timing |
| PvP | Robo done | Observer 1 → outside the enemy natural choke, safe from detection; Observer 2 at home if a Twilight is seen | Army movement, timing attacks, DT defence |
| Random | — | Probe until the race is known, then that matchup's rows | Race |

**Dropped in M7 (user decision):** the PvZ ~6:30 and PvP ~4:30 Hallucinated Phoenix rows. The vs-Z and vs-P mixes have no Sentry, so they never fired; the Observer re-scout (§5) covers the enemy main.

**Hallucination rule:** applies when the enemy main is stale (> 60 s without vision, after 4:00) and a Sentry has ≥ 75 energy. Only an existing Sentry casts it (user decision), so in practice it fires vs T only (the only mix with a Sentry). Cast Hallucination (Phoenix), then send the Phoenix explicitly over the main and natural, and then away. It costs no gas and no army. Blizzard's 5.0.16b hotfix notes list "Reverted spawned Hallucinations inheriting their caster's order queue" (Verified), which is why the Phoenix must be given its own orders.

### 4.4 Observation → inference → response
Rows whose Source column names ares take their inference from the ares flags (§4.2), with the local trigger as a backup. For rows 5, 7, 8 and 10, add 20–30 s to each time for the 8-worker ruleset (TUNE, Uncertain).

| # | Observation (by time) | Inference / Flag | Source | Response (DefensePlan) |
|---|---|---|---|---|
| 1 | ≥ 5 enemy workers near our main before 2:00 | WORKER_RUSH | ares + local | Worker-rush plan |
| 2 | Enemy probe lingering in our base after 1:15, or an enemy Pylon near our base | CANNON_RUSH (or proxy Pylon) | Citadel | Cannon-rush plan; kill the probe |
| 3 | Enemy Forge seen before a Gateway at 1:30 (P) | CANNON_RUSH (weak); or a Forge-first expand if the natural exists | Citadel | Patrol probe on; save 150 minerals |
| 4 | Spawning Pool started before the Hatchery; lings seen before 2:20 | POOL_12 | ares + Citadel | 12-pool plan |
| 5 | No Hatchery at the Zerg natural by 1:45 and Pool done | ONE_BASE_ALLIN (1-base ling/roach) | Citadel | One-base plan; Batteries |
| 6 | Roach Warren before 2:45, or ≥ 2 gases with no 3rd Hatchery by 3:00 | ONE_BASE_ALLIN (roach/ravager) | ares roach/ravager + Citadel | One-base plan; Immortals; 2 Batteries |
| 7 | Terran main: no Barracks at 1:30, or SCV count ≤ 12 at 1:30. **M7 (user decision):** the missing-Barracks test waits until the enemy natural has been in vision (until `PROXY_NATURAL_WAIT_UNTIL_S`, TUNE), and doesn't count when a townhall is there (Command Center first) | PROXY (Barracks) | Citadel | Proxy plan |
| 8 | ≥ 2 Barracks and no natural CC by 2:30 | ONE_BASE_ALLIN (2–3 rax) | ares marine + Citadel | One-base plan |
| 9 | Factory + Starport with no expansion by 3:00 | AIR_HARASS (Banshee/Cyclone/drop) | Citadel | Air/cloak plan (Cannon + Battery, Observer) |
| 10 | Protoss main: no Gateway by 1:30, or probe count short by ≥ 2. **M7 (user decision):** the missing-Gateway test waits until the enemy natural has been in vision (until `PROXY_NATURAL_WAIT_UNTIL_S`, TUNE), and doesn't count when a Nexus is there (Nexus first; it raised a false PROXY in 7 of 8 losses to the built-in Protoss Air build) | PROXY (Gateways) | ares proxy-Zealot + Citadel | Proxy plan |
| 11 | ≥ 3 Gateways and no Nexus by 3:00 (P) | ONE_BASE_ALLIN (4-gate) | ares four-gate | One-base plan; Batteries at the ramp |
| 12 | Twilight Council + no expansion, or a Dark Shrine seen | DT (DTs/Blink) | Citadel | Robotics Facility → Observer at home; Forge → Cannon |
| 13 | Stargate seen (P), Spire seen (Z) | AIR_HARASS | Citadel | Air/cloak plan |
| 14 | Natural on time + 3rd base by 4:30 | MACRO | ares expansion/greedy | Normal macro; 3rd Nexus on time |
| 15 | Scouting probe killed before reaching the enemy main | UNKNOWN_AGGRO (likely aggression) | Citadel | Assume the worst: +1 Battery, delay the 3rd, re-scout with the first unit (Adept/Stalker) |
| 16 | Enemy army value > 1.3× ours and approaching | TIMING_ATTACK | Citadel | Pull the army to the natural choke next to the Batteries; keep producing; don't expand |
| 17 | Enemy army ≥ 60 path-distance from all its bases, and seen recently (§4.6) | ARMY_OUT_OF_POSITION | Citadel | Evaluate the counterattack (§4.6) |
| 18 | Fleet Beacon, Fusion Core or Greater Spire seen; capital ships seen (M7) | CAPITAL_AIR (WARNING; ACTIVE) | Citadel | Capital-air plan (§4.2) and mix (§4.5.1) |

### 4.5 Transition to the win condition

#### 4.5.1 Composition and upgrades
- **Army composition** (production targets as ratios, %):
  - vs T: Stalker 30 / Zealot 20 / Immortal 15 / Colossus 25 / Observer 2 fixed / Sentry 1. **M7:** plus a small Archon share (TUNE, ~10%) while the remembered enemy army is mostly biological (TUNE, ≥ 50% of its supply; "biological" is the unit attribute in game data).
  - vs Z: Zealot 25 / Stalker 25 / Immortal 25 / Archon 15 / Colossus 10. **M7:** plus High Templar (TUNE) for Psionic Storm. Templar whose energy is spent, or beyond the caster count (TUNE), morph into Archons (§4.5.3).
  - vs P: Stalker 40 / Immortal 25 / Colossus 25 / Zealot 10. **M7:** plus a small Archon share (TUNE, ~10%) while the remembered enemy army is Zealot-heavy (TUNE, ≥ 30% of its supply).
  - **M7:** vs T and P, Archons come from High Templar that morph straight away; there is no Psionic Storm research there (user decision). The Archon shares turn off again after a hold time (TUNE), so the mix doesn't flip back and forth.
  - Air switch: if enemy air supply is ≥ 30% of their army, shift the Stalker share up. **M7 (user decision):** Archons are not used as anti-air (this replaces "add Archons"), and no Phoenix is built in M7 (Phoenix production vs T/P stays cut). The switch ends after a hold time (TUNE).
  - **Capital-air mix (M7, every race):** while CAPITAL_AIR is ACTIVE (§4.2), the Colossus share drops (TUNE, ~0-10%), the Blink Stalker share rises, and Void Rays and/or Tempests are added. Expected (standard-patch values; the AIE maps may differ, so the M7 staged test sets the shares):
    - vs Tempests, Void Rays first: they are faster than Tempests, the Tempest's air bonus is against massive units (Void Rays aren't), the Void Ray's bonus is against armored units (Tempests are), and they need only a Stargate;
    - vs Carriers, Battlecruisers and Brood Lords, Tempests: range, and their bonus against massive units.

    The mix returns to normal after the capital ships have been gone for a hold time (TUNE). A Tempest vs Tempest fight is an even trade, so the side that already has more wins.
- **Upgrades:** Forge weapons first, then armour. Twilight → Blink then Charge (vs P, T) or Charge then Blink (vs Z) (M7, user decision). Robotics Bay → Extended Thermal Lance. Templar Archives → Psionic Storm (vs Z). **M7:** each research building works through its own list in parallel, and an upgrade never starts the building it needs (that building comes from the unit mix or its own timed step: Twilight Council, and the Templar Archives vs Z, at TUNE times).
- **Economy (M7, user decision):** a 4th base when minerals are ≥ `FOURTH_BASE_BANK` (TUNE) and gas income has been short of production's needs for `FOURTH_BASE_GAS_STARVED_S` (TUNE), with 3 bases saturated and `DefensePlan.allow_expand`; the probe target rises with it. While gas-starved with a mineral bank, Zealots may exceed their share.
- **Note:** if the ruleset is 5.0.16, Blizzard's 5.0.16b hotfix notes say "Colossus damaged increased from 10(+5 vs Light) to 12(+3 vs Light)" (Verified). It is slightly worse against Marines and Zerglings, so re-check the vs T/Z Colossus share with the combat sim before tuning.

#### 4.5.2 Attack / retreat on `EngagementResult`
`mediator.can_win_fight` returns an 11-level `EngagementResult` enum, from LOSS_EMPHATIC = 0 to VICTORY_EMPHATIC = 10 (Verified, user-supplied). Compare `.value` integers only. VERIFY the member names; the values in brackets below are assumptions.

```python
ATTACK_START      = 8   # (assumed VICTORY_DECISIVE) and supply_used >= 150
ATTACK_START_MAX  = 5   # (assumed TIE) allowed when supply_used >= 190
ATTACK_CONTINUE   = 5   # keep attacking while >= 5
RETREAT_AT        = 4   # retreat when <= 4 (3-level hysteresis vs ATTACK_START)
DEFEND_ENGAGE     = 4   # at home inside battery radius (batteries not simulated)
COUNTER_START     = 7   # vs defenders local to the counterattack target
COUNTER_ABORT     = 4
MIN_STATE_SECONDS = 20  # no attack/retreat flip within 20 s unless result <= 2
```

- **Home defence** engages at ≥ `DEFEND_ENGAGE` and never leaves the battery radius, because Shield Batteries are not simulated (Uncertain).
  - **M7:** only units that can hit something in the threat group answer it, and only they count in its simulation; the others hold the defensive position. The squad fights the enemies that were evaluated (within 20 of the threat), not whatever each unit happens to see.
  - **M7:** units walk back to the defensive position with a move, not an attack-move, so they don't chase attackers out of the battery radius.
- **Inputs:**
  - Own side: units in the ATTACK squad.
  - Enemy side: remembered enemy army units (UnitMemoryManager) within 20 of the squad's path target, or of the squad itself.
  - Also add **enemy static defense within 15 of the target** explicitly: Photon Cannons, Bunkers, Spine Crawlers, Planetary Fortresses, and Shield Batteries as support.
  - Whether the sim models structures is **Uncertain**. Day-1 test: compare 6 Stalkers vs [] against 6 Stalkers vs [1 Photon Cannon]. If the result doesn't change, apply a penalty instead: count each Cannon/Bunker/Spine as 3 Stalkers' worth of supply and a Planetary Fortress as 8 (TUNE). Apply it by lowering the result by one level per 4 penalty-supply.
  - **Launch (M7):** the inputs above see only what is near the squad or its target, and in the first ladder loss every launch read 8-10 against an army the bot had not seen. So a launch also needs all of these:
    1. The level against the remembered enemy army as a whole (every enemy fighter seen and not known dead, seen within `LAUNCH_CACHE_MAX_AGE_S`, TUNE) also passes the gate.
    2. At least `LAUNCH_INTEL_FRESH_FRACTION` (TUNE) of that army was seen within the last 15 s. Otherwise the army's Observer goes to look first, and the launch waits at most `LAUNCH_INTEL_WAIT_S` (TUNE).
    3. No launch within `LAUNCH_AFTER_DEFEND_S` (TUNE) of a home fight.
  - **Out-range penalty (M7, only if needed):** if the fight-input logs (§8) show the simulator rating fights against out-ranging enemies as wins, lower the level by `OUTRANGE_PENALTY_PER_SHARE` (TUNE) per share of enemy value that out-ranges all our units able to hit it, or that none of them can hit. The simulator never sees positions (§11.3).
- **Retreat** at ≤ `RETREAT_AT`, or when the squad's current value is < 40% of its start value.
- **After retreating,** fall back to the defensive position at our newest base, re-max, and don't re-launch for 45 s.
- **Targets:** nearest known enemy expansion → the next one → the main.
- **Reinforcements** rally in groups of ≥ 8 supply; never trickle them in. They go out only while the attack is on, and a retreat or recall sends them home too.

#### 4.5.3 Unit control (M7)
Citadel's choices, decided after the first ladder losses. Every threshold is TUNE in `bot/constants.py`; ranges and speeds come from game data.
- **Out-ranged rule:**
  - A unit that is not committed to a fight (holding, moving or retreating) and is inside the reach of a visible enemy it can't hit, or that out-ranges it by ≥ `OUTRANGED_MARGIN`, steps out of that enemy's reach (ares `KeepUnitSafe`).
  - Committed units (an attack, or a home fight the squad chose) keep fighting.
  - If out-rangers the squad can't beat cover the defensive position, it moves back toward the main in steps (`HOLD_FALLBACK_STEP` × at most `HOLD_FALLBACK_STEPS`).
- **Retreat:** retreating units shoot only enemies that fight back, and only when faster than every visible threat that can hit them. Blink Stalkers blink away first.
- **Blink:** Stalkers with Blink ready:
  - **blink back** on low shields (`BLINK_BACK_SHIELD_FRACTION`) when threatened;
  - **blink onto out-rangers together** when the squad is committed (at most `BLINK_IN_PER_TARGET_S` per target, so they arrive as a group);
  - **blink to finish** a fleeing unit one volley would kill, only when the landing spot is safe and the local fight is won.

  They never blink into fog, onto ground with enemy fire above `BLINK_DANGER_MAX`, or up a cliff without vision of the landing spot.
- **High Templar:**
  - They stay behind the squad and cast Psionic Storm on clumps, never on our own units (ares's AoE behaviour).
  - Templar whose energy is spent for `TEMPLAR_MORPH_AFTER_S`, or beyond `TEMPLAR_MAX_CASTERS`, morph into Archons in pairs.
  - Citadel morphs them itself: ares's production would merge any two idle Templar, casters included.
- **Void Rays and Tempests:** Void Rays target capital and armored units first, and use Prismatic Alignment when ≥ `VOIDRAY_ALIGN_MIN_ARMORED` armored enemies are in range. Tempests target massive units first and step back between shots like the other kiters.

### 4.6 v1 Counterattack
In v1, weakness exploitation is limited to counterattacking an out-of-position army.
- **Detect ARMY_OUT_OF_POSITION.** Evaluate every 16 steps, from 5:00 onward. All of these must hold:
  1. The remembered enemy army (non-worker, non-structure, excluding Overlords and Observers) has value ≥ 800. At least 60% of it was seen within the last 15 s, via Observer, army contact or a Revelation.
  2. The value-weighted centroid of that army has ground path distance ≥ 60 from every known enemy townhall (TUNE; use `find_path_next_point` sampling or map-analyzer path length, cached).
  3. Enemy army value within 25 of the target base is ≤ 25% of the total remembered army.
  4. Either our base is not under attack, or the enemy army is attacking our base and the defense planner reports that it can hold with the remaining forces: `can_win_fight(home_units, attackers) ≥ DEFEND_ENGAGE`.
- **Squad.** Take the fastest units first: Adepts, Zealots with Charge, then Stalkers. Take them only from units the defense planner has not pinned. Cap the squad at 35% of our army supply, with a minimum of 8 supply (TUNE).
- **Target.** Pick the known enemy base with the lowest `local_defence_value`: static defense penalty plus remembered units within 20. Break ties by larger distance from the enemy army centroid. Priority inside the base: workers, then production, then townhall.
- **Launch** if `can_win_fight(squad, local_defenders) ≥ COUNTER_START`.
- **Return home (recall)** on any of these:
  - The enemy army centroid comes within 35 of the target, or within 20 of the squad.
  - The result is ≤ `COUNTER_ABORT`.
  - Squad value is < 50% of its start value.
  - The squad has been out for > 60 s.
  - The defense planner raises any threat against our bases that needs these units.
- **Interactions:**
  - The counterattack never runs while a main ATTACK is active; the main attack absorbs it.
  - If the main attack gate opens while a counterattack is active, merge the counter squad into the ATTACK squad.
  - Defense has priority and can recall the squad at any moment.
  - While recalling, use `PathUnitToTarget` on the influence grid and avoid the enemy army.
- **Do not** base-trade in v1. If our main is falling, recall.

### 4.7 End-game and the 60-minute tie
Games that reach 80,640 loops (60:00) end in a tie (Verified, user-supplied).
- From 40:00: if no enemy structure has been seen for 60 s, run a **structure hunt**. Send Observers and a Phoenix, or Stalkers, to every expansion, then to a grid of map-analyzer region centres, including corners and islands.
- From 45:00: if our remembered army value is ≥ 1.2× the enemy's, drop `ATTACK_START` to 6.
- A tie is better than a loss. If we are behind, keep defending.

### 4.8 Ramp wall fallback
python-sc2's `protoss_wall_pylon`, `protoss_wall_buildings` and `protoss_wall_warpin` return None or an empty set on non-standard ramps (Verified, user-supplied).
1. On startup, cache `wall_ok = pylon is not None and len(buildings) >= 2 and warpin is not None`, and log it per map.
2. If `wall_ok` is false:
   - Let ares place the Pylon, Gateway and Core using its pre-calculated Protoss formations (ares docs, Verified; VERIFY the `BuildStructure` arguments) at `self.start_location`.
   - Put a Shield Battery within 6 of `main_base_ramp.top_center`, on the main side.
   - Treat the ramp as a unit-held choke: the first Zealot or Adept holds position at `main_base_ramp.top_center` offset 1.5 toward the main, with the Battery behind it.
3. If `main_base_ramp` itself looks wrong (its top is > 30 from the start location), use the map-analyzer choke nearest the main instead.
4. On the first run on each of the 7 pool maps, log which maps fall back. Which pool maps have non-standard ramps is Uncertain.

## 5. Data structures

Threat state is held as rule-based `ThreatFlag`s with explicit expiry. Flags raised by structures or tech must not expire on a timer. Store unit tags only, never `Unit` objects.

```python
from dataclasses import dataclass, field
from enum import Enum, auto

class Threat(Enum):
    WORKER_RUSH = auto(); CANNON_RUSH = auto(); POOL_12 = auto(); PROXY = auto()
    ONE_BASE_ALLIN = auto(); AIR_HARASS = auto(); DT = auto(); TIMING_ATTACK = auto()
    MACRO = auto(); UNKNOWN_AGGRO = auto(); ARMY_OUT_OF_POSITION = auto()
    CAPITAL_AIR = auto()   # M7: WARNING from STRUCTURE evidence, ACTIVE from UNIT evidence (§4.2)

class Evidence(Enum):
    STRUCTURE = auto()   # buildings, tech, missing-structure-at-time observations
    UNIT = auto()        # units seen / moving
    ARES = auto()        # mirrored from ares IntelManager

@dataclass
class ThreatFlag:
    threat: Threat
    evidence: Evidence
    raised_at: float                                            # game seconds
    evidence_tags: set[int] = field(default_factory=set)        # tags only, never Unit objects
    evidence_positions: list[tuple[float, float]] = field(default_factory=list)
    last_confirmed: float = 0.0
    override_opener: bool = False                               # True pauses the ares build runner (§3)

@dataclass
class DefensePlan:
    active: set[Threat]
    allow_expand: bool
    batteries_needed: dict[str, int]    # "main"/"natural" -> count
    cannons_needed: dict[str, int]
    probe_pull: int                     # number of probes assigned to DEFENDING role
    army_hold_point: "Point2"
    pinned_unit_tags: set[int]          # units held by defense; the counterattack may not take them
```

**Expiry rules** (`threat_flags.expire()`):
- **UNIT evidence** expires `UNIT_TTL` seconds after `last_confirmed`:
  - WORKER_RUSH: 20 s.
  - TIMING_ATTACK: 30 s.
  - ARMY_OUT_OF_POSITION: 15 s.
  - Lings / POOL_12 from units: 45 s.
  - CAPITAL_AIR (ACTIVE, M7): `CAPITAL_AIR_UNIT_TTL` (TUNE) after the remembered capital-ship value drops below `CAPITAL_AIR_MIN_VALUE`.
- **STRUCTURE evidence never expires on a timer.** It expires only when:
  - (a) every evidence tag has been reported destroyed (`on_unit_destroyed`); or
  - (b) we get vision of every evidence position and the structure is absent (a re-scout contradicts it); or
  - (c) a phase rule makes it irrelevant:
    - CANNON_RUSH: time > 5:00 and no enemy structure within 25 of our townhalls.
    - PROXY: time > 5:30 and no proxy structure is known.
    - ONE_BASE_ALLIN: enemy natural townhall seen, or time > 7:00 with our 3 Batteries and ≥ 20 army supply.
    - POOL_12: time > 4:00.
    - AIR_HARASS and DT: never by phase. They stay until detection exists at every mineral line; then the flag moves to "satisfied" and stops forcing builds.
    - CAPITAL_AIR (WARNING, M7): never by phase; only by (a) or (b).
- **ARES evidence** follows the matching category. A unit-based ares flag (e.g. ling rush) is treated as UNIT with its TTL, even if the ares boolean stays True. Record the ares reset behaviour in `constants.ARES_INTEL` after reading the source.
- **Minimum plan duration** is 20 s, unless the flag is cleared by rule (a).
- **Re-scout trigger:** any STRUCTURE flag whose evidence positions haven't been seen for > 90 s, or `now - last_main_scout > 60` after 3:00.

**Opponent memory:**
- `./data/opponents/<OpponentId>.json` holds `{games, wins, losses, threats_seen: [{threat, time}], first_aggression_time}`.
- Load it in `on_start` from the `--OpponentId` argument, which the template's ladder entry parses. Write it in `on_end`.
- If the opponent raised the same cheese flag in ≥ 2 of their last 3 games, pre-raise it at 0:00 as STRUCTURE evidence with a phase-only expiry.
- Opener selection itself is left to WinrateBased; the ares build runner tracks opener winrates (VERIFY where it stores them in `./data`).

## 6. Performance

- **Enforced:** 30 s without any response from the bot, including during startup, loses by TimeOut (Verified, user-supplied). Keep `on_start` under 5 s and log its duration. Do no pathing precompute over all expansion pairs; compute lazily and cache.
- **Documented but not enforced:** 40 ms per step, with no strike system (Verified, user-supplied). Target it anyway, because enforcement may arrive later: mean ≤ 15 ms, p99 ≤ 40 ms.
- **Measure:** log `time.perf_counter()` per step, and log a warning for any step above 30 ms.
- **Hard guard:** if a step exceeds 200 ms, skip the non-critical modules (scout planner, counterattack evaluation, telemetry snapshot) for the next 16 steps.
- **60-minute tie:** see §4.7. Telemetry must record whether the game was tied.
- **Cadence:**
  - Every step: worker-defense micro and squad micro for engaged units.
  - Every 4 steps: economy, production and scout planner.
  - Every 8 steps: intel (ares bridge, detectors, flag expiry) and the defense planner.
  - Every 16 steps: attack decision and counterattack (≤ 2 sims each).
  - Every 32 steps: expansion and building-placement searches.
- Use the ares KD-tree queries (`get_units_in_range`) instead of nested distance loops. Cache pathing results for static targets. Never await pathing queries (e.g. `self.client.query_pathing`) in a loop.
- Keep APM moderate: don't re-issue an identical order to a unit that already has it. This avoids the known order-lag bug, seen around 120k (and sometimes 60k) APM.

## 7. Milestones (2 weeks; each produces a runnable bot)

| M | Days | Deliverable | Acceptance |
|---|---|---|---|
| M0 | 1 | Template runs on the 7 maps. Ladder zip from the Action. Read the §11 APIs and fill `constants.ARES_INTEL`. Run the ruleset probe and log it. Run the `can_win_fight` static-defense test | Game completes; zip layout OK; a notes file records every §11 item |
| M1 | 2–4 | Openers A/B/C in YAML with WinrateBased. Economy, chrono, supply, 3 bases. Wall fallback | Beats Medium/Hard 10/10; 44 probes by 6:00 (12-worker) |
| M2 | 5–7 | ares bridge, Citadel detectors, ThreatFlag expiry, defense plans (worker rush, cannon, 12-pool, proxy, one-base) | ≥ 8/10 vs worker-rush, SharpCannons, 12-pool and proxy test bots |
| M3 | 8–9 | Per-matchup scout planner (probe, Adept shade, Observer, Oracle, hallucinated Phoenix) | Correct flag logged in ≥ 80% of scripted-cheese games; no scout lost before 4:00 in ≥ 70% |
| M4 | 10–11 | Squads, `EngagementResult` gates, retreat hysteresis, end-game rules | VeryHard ≥ 7/10 across races |
| M5 | 12–13 | Counterattack (§4.6), opponent memory, telemetry, step guard | Counterattack triggers and recalls correctly in ≥ 3 staged tests; no crash in 30 local games |
| M6 | 14 | Upload with bot data enabled; watch the first ladder games | No crashes or timeouts in the first 20 games |
| M7 | after M6 | Ladder fixes (user decision; plan and file-level steps in `docs/M7_PLAN.md`): fight and loss telemetry; army bugs; out-ranged rule, launch gate, threat eligibility, retreat (§4.5.2-4.5.3); per-building research, Blink, High Templar/Archons; 4th base, AIR_HARASS and CAPITAL_AIR detection and the capital-air mix (§4.2, §4.5.1) | Each phase's criteria in `docs/M7_PLAN.md`; VeryHard × 10 vs each race's built-in Air build meets the targets set after the baseline batches; the M1-M5 regressions hold; no crash or time-out in the first 20 ladder games after each upload |

**Cut from v1:**
- Stasis Wards; Oracle harass as a plan (the Oracle is for scouting only); Phoenix production vs T/P.
- Natural walls and PvZ full walls.
- Disruptors, Warp Prism, and Carriers / Skytoss as the main army. (M7 took High Templar and Blink micro off this list, and allows Void Rays and Tempests as the capital-air answer, §4.5.1.)
- Custom opener selection (WinrateBased replaces it).
- Base trades (counterattack only while our base is safe).
- 8-worker build optimisation beyond the shifted builds in §4.1.
- Custom speed-mining beyond ares's `SpeedMining` (Verified, exists).

## 8. Testing plan

- **Built-in AI:** difficulties Medium → Hard → Harder → VeryHard; builds `AIBuild.Rush`, `Timing`, `Power`, `Macro`, `Air`; all 3 races plus Random; at least 3 of the 7 pool maps. Always use `realtime=False`.
- **Scripted cheese:**
  - sharpy-sc2 dummy bots: SharpCannons, BluntCheese, BluntWorkers, the proxy zealot rush, RustyMarines/OldRusty and RustyOneBaseTurtle.
  - The AI Arena "House Bots" (downloadable, originally by Infy & Merfolk).
  - The local-play-bootstrap test bots.
- **Ladder environment:** `aiarena/local-play-bootstrap` (run with `docker compose up`) with Citadel's actual ladder zip, before every upload. Unzip the ladder zip into `bots/Citadel/`, add a line to `matches`, and afterwards read `results.json`, `replays/` and `logs/`.
- **Maps and ruleset:** run each opener on all 7 pool maps and log `wall_ok` and the ruleset.
- **Staged counterattack tests:** use debug spawning (ares chat debug, Verified) to place an enemy army 70 path-distance away. Check the trigger, the target choice, and the recall when the enemy army returns.
- **M7 staged tests** (debug spawning, dev-only scripts):
  - out-ranged units at a hold point (Tempests);
  - Blink;
  - High Templar (Storm placement, no Storm on our own units, Archon morphs);
  - which equal-cost groups beat Tempests, Battlecruisers, Brood Lords and a mass of Void Rays on the AIE data (sets the §4.5.1 capital-air shares, and decides whether Void Ray masses join that response; user decision).
- **Metrics per game** (JSON line in `./data/logs/`, capped at the last 200 games; also stdout):
  - result, opponent id/race, map, game length, opener, ruleset, tie flag;
  - flags with their raise and expire reasons (and times);
  - probes at 4:00/6:00/8:00, bases at 6:00/10:00, supply-block seconds, unspent resources at 6:00/10:00;
  - first enemy aggression time; army value lost vs killed;
  - `EngagementResult` values at each attack/retreat decision; counterattack outcomes;
  - startup ms; mean/p99/max step ms.
  - **M7:**
    - the fight inputs (unit counts and values, both sides) at each decision;
    - enemy tech and capital ships, first seen;
    - army losses by intent and distance from their point;
    - blinks, storms and Archon morphs;
    - capital-air state changes.

## 9. Risks and known pitfalls

1. **Storing `Unit` objects across steps** causes crashes and stale positions. Store tags only (AI Arena wiki).
2. **Windows-built zips:** Cython binaries won't run on the Linux ladder (Windows produces `.pyd` files; the ladder needs Linux `.so` files). Build the zip on Linux or with GitHub Actions (ares template).
3. **Zipping the folder instead of its contents** breaks the upload (AI Arena wiki).
4. **Ruleset uncertainty:** the ruleset may be 5.0.16 or earlier. Detect it (§4.0) and read game data instead of hard-coding balance numbers; the AIE maps carry newer patches on the 4.10 engine.
5. **Localhost connection in Docker:** honour `--LadderServer` (local-play-bootstrap).
6. **Season resets deactivate bots.** Re-activate and re-test on the new maps.
7. **APM order lag at extreme action counts.** Avoid duplicate orders.
8. **Over-pulling probes** wrecks the economy. Always release them once the threat flag clears, and keep building probes.
9. **Scouting-unit deaths** starve intel. Use influence-grid pathing and retreat thresholds.
10. **Plan flapping** is handled by the flag expiry rules, the 20 s minimum plan duration (§5) and `EngagementResult` hysteresis.
11. **Trickling reinforcements into fights** is the classic bot loss. Group them and gate them with the simulator.
12. **Step-time spikes from pathing queries.** Throttle and cache them.
13. **ares intel flags may never reset.** Citadel's flags have their own expiry.
14. **The combat sim may ignore static defense.** Use the explicit penalty (§4.5.2).
15. **"Bot data enabled" is off by default** (Likely). Without it, WinrateBased and the opponent memory silently do nothing.
16. **A counterattack squad caught out of position.** The recall rules and the 35% supply cap limit this.

## 10. Out of scope for v1

- Everything in the "Cut from v1" list in §7.
- Machine learning, and any network calls.
- Offensive cheese builds and proxy play.
- Human-vs-bot realtime executables.

Per-opponent build selection is in scope for v1 through `BuildSelection: WinrateBased` (§4.1).

## 11. APIs to verify in source before use

Several ares internals could not be read during research, so these assumptions must be checked in code (Day 1, M0).
1. `src/ares/managers/intel_manager.py`: exact mediator property names for each flag, trigger conditions, time windows, unit counts, and reset behaviour.
2. `unit_memory_manager.py`: how long ghost units are retained, how they expire, and the accessors (e.g. whether it's `mediator.get_enemy_army_dict` or a memory-units accessor).
3. `mediator.can_win_fight`: signature and parameters (e.g. `timing_adjust`, `good_positioning`, `workers_do_no_damage`), the `EngagementResult` member names and values, and whether structures are simulated.
4. The build runner YAML schema for `BuildSelection: WinrateBased`, where winrate data is stored in `./data`, the syntax of `@ enemy_nat` targets, and `set_build_completed`.
5. `BuildStructure` arguments for placing Protoss buildings through formations; `find_path_next_point`, `get_units_in_range`, `KeepUnitSafe`, `PathUnitToTarget`, `SpeedMining` (these exist, Verified; check the signatures).
6. Grid accessors: ground and air grids with influence.
7. The Warp Gate research and morph ability IDs, and Hallucination (Phoenix), Revelation and Oracle ability availability and costs under the AIE map data.
8. `self.workers` count and `self.supply_cap` on loop 0, for ruleset detection.
9. The order in which ares updates its managers relative to `on_step`.

## 12. Open Questions

1. Which live patch do the 2026 AIE maps replicate, and do they start with 8 or 12 workers? Ask on the AI Arena Discord or read the active competition page. Once known, delete the other ruleset's builds.
2. Pro-sourced 8-worker Protoss openers and timings (post-June 2026) to replace the shifted builds.
3. The actual ares IntelManager thresholds (§11.1). Some Citadel backup triggers may become redundant.
4. Does `can_win_fight` count static defense? That decides whether the penalty in §4.5.2 stays.
5. Results and races for the Jan–Mar 2026 tournament (Eris reportedly champion; not verified). Which strong Protoss bots publish source?
6. Which of the 7 pool maps fail the `protoss_wall_*` helpers?
7. Is the 60-path-distance out-of-position threshold right on small maps? Consider scaling it by map size.