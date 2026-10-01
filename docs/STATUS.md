# Citadel status

Where the project stands, for picking up the next milestone. The spec is `docs/DESIGN.md`; API
findings and Citadel's choices are in `docs/VERIFY_NOTES.md`.

## Milestones

| M | State | Where |
|---|---|---|
| M0 | Done | `docs/VERIFY_NOTES.md` §11 |
| M1 | Done | openers, economy, supply, 3 bases, wall fallback (`bot/macro/`, `bot/defense/wall_fallback.py`) |
| M2 | Done (see the evidence in `docs/VERIFY_NOTES.md`, "M2 acceptance evidence") | ares bridge, detectors, ThreatFlag expiry, defense plans |
| M3 | Done (see `docs/VERIFY_NOTES.md`, "M3 acceptance evidence") | per-matchup scout planner, §4.4 rows 3 and 15 |
| M4 | Done (see `docs/VERIFY_NOTES.md`, "M4 acceptance evidence") | squads, `EngagementResult` gates, retreat hysteresis, end-game rules (`bot/army/`) |
| M5 | Next | counterattack (§4.6), opponent memory, telemetry to `./data`, step guard (DESIGN.md §7) |

## Code map (M2-M4 additions)

| File | What it does |
|---|---|
| `bot/intel/threat_flags.py` | `FlagStore`: flags keyed by (threat, source), §5 expiry rules, history for the end-of-game report |
| `bot/intel/ares_bridge.py` | ares intel flags → ThreatFlags (`BRIDGES` table) |
| `bot/intel/detectors.py` | Citadel's detectors: worker rush, cannon structures/probe, early Pool, early lings, proxy (missing/far production), no natural; also the §5 phase rules (`expiry_context`) and scouting state (`main_scouted_at`, `enemy_workers_in_main`, `natural_seen_at`) |
| `bot/intel/scout_planner.py` | M3 `ScoutPlanner`: when each §4.3 scouting task starts and with which unit (Defense > Scouting), expansion checks, §5 re-scouts, Hallucination; `tags` keeps scouts out of the army |
| `bot/intel/scout_tasks.py` | M3 task classes (`MainProbeTask`, `PatrolProbeTask`, `LookTask`/`ProbeLookTask`, `AdeptShadeTask`, `OracleTask`, `PostTask`, `PhoenixTask`) and `Mover` (danger-aware paths, `KeepUnitSafe`, keeps out of static defense's reach) |
| `bot/defense/defense_planner.py` | active flags → one `DefensePlan` (per-threat `_plan_*`), ends the ares opener on override flags |
| `bot/defense/worker_defense.py` | probe pulls (worker rush, cannon rush, lings in a mineral line) and the cancel-when-dying rule |
| `bot/defense/static_defense.py` | main/natural Batteries, extra Gateways, Core first vs 12-pool, Cannon-range placement blocking, build-order retargeting, dead-builder handling |
| `bot/army/engagement.py` | M4 fight evaluation: Citadel's `EngagementResult` from the combat simulator with our HP+shields and the defender set; §4.5.2 inputs (`attack_inputs`, `enemies_near`, `static_defense_near`); unit values |
| `bot/army/attack_decision.py` | M4 main attack state machine (§4.5.2 gates, 20 s flip hold, 40% value rule, 45 s relaunch wait, recall) and the §4.7 45:00 / 40:00 gates; no game objects |
| `bot/army/squads.py` | M4 squad roles by tag (DEFEND, ATTACK, REINFORCE, HARASS for M5, SCOUT), mirrored as ares `UnitRole`s |
| `bot/army/army.py` | M4 commander (replaces M1's `BasicArmy`): home defense on the simulator (M2 rules kept), launches/retreats/recalls, targets and the ground structure hunt, regroup, reinforcements, the army's Observer, per-step micro dispatch; `ENGAGE`/`DEFEND`/`ARMY` log lines |
| `bot/army/micro.py` | M4 per-unit control on ares behaviors (focus fire, kiting with `KeepUnitSafe`, danger-aware retreat) |
| `bot/army/endgame.py` | M4 §4.7 structure hunt state and points (the scout planner gives Observers/Phoenix trips) |
| `scripts/test_bots/` | scripted cheese opponents (plain python-sc2): `worker_rush`, `cannon_rush` (natural/main), `twelve_pool`, `proxy_rax` (third/center) |
| `bot/telemetry/logger.py` | M3 adds scout records (`SCOUT start/done/home/lost/expired`, `METRIC scouts`) and the §8 first-aggression time |
| `scripts/m3_checks.py` | the M3 "correct flag" check (`M3_EXPECTED_FLAGS`), used by `run_matches.py` and `test_m3_checks.py` |
| `scripts/test_scout_abilities.py` | in-game checks of the Adept shade, Hallucination, Pulsar Beam and detection |
| `scripts/test_attack_decision.py` / `test_engagement.py` / `test_endgame.py` | M4: offline gate/hysteresis tests; in-game levels vs ares's; staged §4.7 structure hunt with shortened thresholds |

Every threshold is in `bot/constants.py`.

## Test commands

| Check | Command |
|---|---|
| ThreatFlag expiry unit test (no game) | `poetry run python scripts/test_threat_flags.py` |
| M2 acceptance, one batch per cheese bot | `poetry run python scripts/run_matches.py --opponent worker_rush --map all --total 10 --seed 100` (also `cannon_rush`, `twelve_pool`, `proxy_rax`) |
| One cheese variant | add `--variant natural`/`main` (`cannon_rush`) or `third`/`center` (`proxy_rax`) |
| One-base plan vs the built-in AI | `poetry run python scripts/run_matches.py --difficulty Harder --build Rush --race Terran Zerg Protoss --map all --total 3` |
| M1 regression | `poetry run python scripts/run_matches.py --difficulty Hard --map all --total 10 --race Terran Zerg Protoss Random` |
| Wall fallback | `poetry run python scripts/test_wall_fallback.py --case ramp` (and `--case choke --map TorchesAIE_v4 --race Zerg`) |
| Opener cycling | `poetry run python scripts/test_opener_cycle.py` |
| M3 acceptance (same batches; `flag=`/`scouts=` columns and `M3 ...` summary lines) | `poetry run python scripts/run_matches.py --opponent <bot> --map all --total 10 --seed 100` |
| M3 scout losses vs the built-in AI | `poetry run python scripts/run_matches.py --difficulty Harder --race Terran Zerg Protoss --map all --total 21` |
| M3 flag check / scouting abilities | `poetry run python scripts/test_m3_checks.py`; `poetry run python scripts/test_scout_abilities.py` |
| M4 acceptance (10 VeryHard games per race; `M4 wins per race` summary line; `engage=`/`value=`/`step=` columns) | `poetry run python scripts/run_matches.py --difficulty VeryHard --race Terran --map all --total 10` (also `Zerg`, `Protoss`) |
| M4 gates / fight levels / structure hunt | `poetry run python scripts/test_attack_decision.py`; `poetry run python scripts/test_engagement.py`; `poetry run python scripts/test_endgame.py` |
| Ladder zip | `poetry run python scripts/create_ladder_zip.py`, then `unzip -l publish/*.zip \| head` |

Four batches can run in parallel on a 4-core machine (about 40-70 minutes for 10 games each).
Each finished game prints a `ROW` line; if the container restarts mid-batch, rerun the same
command with `--start N` (games keep their map and seed).
To stop batches, use a pattern that can't match your own shell, e.g.
`pkill -f "opponent twelve_poo[l]"`, in a command of its own (nothing else in that command may
contain the matched text), then kill the orphaned `SC2_x64` clients (parent PID 1).

## M4 checks on the final code (d20f15b)

| Check | Result |
|---|---|
| M4 acceptance, VeryHard × 10 per race | Terran 10/10, Zerg 9/10, Protoss 10/10 (≥ 7 each): PASS; 0 crashes |
| M2/M3 regression, 4 cheese bots × 10 (seed 100) | wins: worker rush 10/10, cannon rush 8/10 (1 tie, 1 loss), 12-pool 10/10, proxy 10/10 (M2 ≥ 8/10: PASS); correct flag 40/40; no scout lost before 4:00 40/40 |
| M1 regression, Hard × 10 (T/Z/P/Random) | 10/10 wins, 0 crashes; 44+ probes at 6:00 in 8/10 (41 and 41 vs Pool-first Zerg with POOL_12 holding the natural's timing, as in M3) |
| `test_attack_decision.py` / `test_threat_flags.py` / `test_m3_checks.py` | 16/16 / 20/20 / 13/13 |
| `test_engagement.py` / `test_endgame.py` | PASS / PASS |
| Ladder zip | `publish/Citadel.zip`, 378 files, 5.5 MB, `run.py`/`ladder.py`/`config.yml` at the top level, `sc2_helper` included |

Details and the per-game tables: `docs/VERIFY_NOTES.md`, "M4 acceptance evidence".

## Carry-forward for M5 (counterattack, opponent memory, telemetry, step guard)

- **Squads.** `Role.HARASS` exists for the §4.6 counterattack squad and nothing is assigned to it
  yet. `Army.busy_tags` keeps the scout planner off the ATTACK/REINFORCE squads; a HARASS squad
  should be added there. The defense plan's pinned units never reach a squad (`held_tags`).
- **Fight levels.** `Engagement.level(own, enemy, defender)` is the one entry point (our
  HP+shields, defender set, 0-10); `attack_inputs(center, target)` builds the §4.5.2 enemy side.
  §4.6's `COUNTER_START`/`COUNTER_ABORT` are not in `bot/constants.py` yet.
- **Interactions M5 must keep.** `AttackDecision.recall` (no relaunch wait) is how defense pulls
  the main attack home; §4.6 says the counterattack never runs during a main attack and is merged
  into the ATTACK squad when the attack gate opens.
- **Enemy army value.** `Army._value_ratio` uses ares's army cache (every enemy unit seen, until
  it dies); §4.6's "seen within the last 15 s" needs `unit.age` / `is_memory` on top.
- **Telemetry.** `Telemetry` now keeps army value lost/killed, per-step times (p99) and
  `Army.decisions` (every launch/retreat/recall with its level); M5 writes them to `./data/logs`.
- **Step time.** Over the 30 acceptance games (4 in parallel on 4 cores): mean 3.4-10.9 ms, p99
  over 40 ms in 2 games (42, 55), max step 49-411 ms; a cheese game run with 6 clients on 4 cores
  had a 1.3 s step. §6's 200 ms guard (skip non-critical modules for 16 steps) is M5's.

## Starting M5

- **Deliverable / acceptance (DESIGN.md §7):** counterattack (§4.6), opponent memory (§5 "Opponent
  memory"), telemetry (§8, written to `./data/logs`, last 200 games), step guard (§6). Acceptance:
  the counterattack triggers and recalls correctly in ≥ 3 staged tests; no crash in 30 local games.
- **Spec sections to read:** §4.6, §4.4 row 17 (ARMY_OUT_OF_POSITION), §5 (opponent memory and
  the `UNIT_TTL_S` for ARMY_OUT_OF_POSITION), §6, §8, and §2's `./data` rules (≤ 5 MB, written only
  under `./data`, "bot data enabled" on the ladder).
- **Reusable test patterns:** `scripts/test_endgame.py` (a CitadelBot subclass that sets up a game
  with debug commands and patches thresholds inside the test) fits §8's staged counterattack tests
  (place an enemy army ~70 path-distance away, check trigger, target, recall). Offline state-machine
  tests like `scripts/test_attack_decision.py` fit the §4.6 recall rules.
- **Environment:** the cloud container restarted three times during M4's long runs and killed the
  batches; `run_matches.py --start N` resumes a batch, and each game prints a `ROW` line.

## Open question for the user

- **A natural Nexus started before POOL_12 is raised.** §4.2 says to "cancel or delay the natural
  Nexus if it is not yet started", so Citadel keeps one that is already placed. Both 12-pool
  acceptance losses came from it: the opener placed it at ~1:20, the Pool was seen at 1:20-1:21,
  and once the Nexus finished, ares's Mining sent probes out past the wall-gap holder to its
  minerals. Cancelling a started Nexus on the flag would refund 75% and keep probes home, but it
  goes beyond §4.2 as written, so it waits for a decision. **M3 update:** the main probe now sees
  the Pool on entering the enemy main, so POOL_12 was raised by 1:08-1:13 in all ten M3 12-pool
  games, before the opener's Nexus; the question now only matters for a later-scouted 12-pool.

## Known issues (not blocking M4)

- **Cannon rush 8/10 (M3: 10/10).** The Ultralove natural variant tied at 60:00 once and the Pylon
  main variant lost once in the final run: in both the first few units were lost near the rush
  Cannons before the army grew (the Ultralove seed won on 3d230e1; the Pylon one is the "Cannon
  finishes next to our main Nexus" pattern below). M2's bar (≥ 8/10) still holds.
- **Late-game Zerg.** The one VeryHard Zerg loss went to 25:33 against Mutalisks, Ultralisks,
  Brood Lords, Swarm Hosts and Corruptors: the §4.5.1 air switch (Stalker share up vs air) isn't
  built and the vs-Z mix has no Archons (High Templar are cut). The army was recalled home five
  times by runbys in that game.
- **Launch inputs are local.** §4.5.2's enemy side is what is near the squad or its target, so a
  launch reads the target's defenders only; an enemy army elsewhere is met on the way and the
  retreat rules handle it (first attacks lost up to half the squad in a few intermediate games).
- A probe scout coming home while rush Cannons cover the way waits outside their reach for as long
  as they stand; two were caught there by the cannon bot's Stalkers after 5:40.
- The PvT Adept shade sometimes can't reach the enemy ramp bottom safely (Bunker/Marines) and comes
  back after `UNIT_SCOUT_MAX_S` without casting.
- Probe expansion checks from 4:30 cost a mining probe per trip and sometimes the probe; an
  Observer is used when one is free.
- ares's unit-based flags (marauder rush, "went reaper") still raise short ONE_BASE_ALLIN/PROXY
  flags vs the built-in AI (VeryHard Terran on Torches/Ultralove raised PROXY + ONE_BASE_ALLIN at
  1:13 and held its natural; the games were won).
- AIR_HARASS, DT, MACRO, TIMING_ATTACK detectors (§4.4 rows 9, 12-14, 16) are not in any
  milestone yet; the scouts' sightings are in ares's memory and `enemy_structures`.

## Known issues from M2

- Cannon rush, main variant, Persephone (opponent seed 106): the rusher's first Cannon finishes
  next to our main Nexus by 2:00 and six more follow; §4.2 stops the probe attack once a Cannon
  completes, and the army never gets going (the Cannons also cover a Gateway). Lost in two of
  three M2 runs; in M4 lost once (3d230e1) and won in the final run, where the same pattern lost
  the Pylon main-variant game.
- §4.4's proxy rules raise PROXY vs some built-in AI builds (no production at 1:30, or few
  workers seen by a partial scout); that costs a little economy. M3's scouting should see more.

- The PROXY plan's expansion gate and hold point have no hysteresis: with units dying and
  being replaced they flip every few seconds (seen vs Harder Rush Terran), walking the army
  between the ramp and the natural. The 12-pool gate has hysteresis (`POOL_12_GATE_HOLD_S`);
  the proxy one could use the same.
- With Zerglings loitering near our natural, POOL_12 stays active on its lings source and ares's
  expansion can stall: a Persephone 12-pool game was still on one base with 56 probes at 10:00
  (it had 131 supply).
- The scripted 12-pool bot never expands or drones past 13, so it is harsher than most
  12-pools; the cannon bot builds up to 8 Cannons.
