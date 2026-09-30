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
| M4 | Next | squads, `EngagementResult` gates, retreat hysteresis, end-game rules (DESIGN.md §4.5.2, §4.7, §7) |

## Code map (M2 and M3 additions)

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
| `bot/army/basic_army.py` | M1 scaffolding army plus hold point / leash, home-threat and don't-feed rules (M4 replaces the supply-count gates with `EngagementResult`) |
| `scripts/test_bots/` | scripted cheese opponents (plain python-sc2): `worker_rush`, `cannon_rush` (natural/main), `twelve_pool`, `proxy_rax` (third/center) |
| `bot/telemetry/logger.py` | M3 adds scout records (`SCOUT start/done/home/lost/expired`, `METRIC scouts`) and the §8 first-aggression time |
| `scripts/m3_checks.py` | the M3 "correct flag" check (`M3_EXPECTED_FLAGS`), used by `run_matches.py` and `test_m3_checks.py` |
| `scripts/test_scout_abilities.py` | in-game checks of the Adept shade, Hallucination, Pulsar Beam and detection |

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
| Ladder zip | `poetry run python scripts/create_ladder_zip.py`, then `unzip -l publish/*.zip \| head` |

Four batches can run in parallel on a 4-core machine (about 40 minutes for 10 games each).
To stop batches, use a pattern that can't match your own shell, e.g.
`pkill -f "opponent twelve_poo[l]"`, in a command of its own.

## M3 checks on the final code (95ee868)

| Check | Result |
|---|---|
| M3 acceptance, 4 cheese bots × 10 (seed 100) | correct flag 40/40; no scout lost before 4:00 40/40; wins 10, 10, 9, 10 (M2 check passes) |
| M3 scout losses, built-in Harder × 21 | no scout lost before 4:00 21/21; 15/21 wins (losses 12:52-18:57) |
| M1 regression, Hard × 10 (T/Z/P/Random) | 10/10 wins, 0 crashes; 44+ probes at 6:00 in 8/10 (41 and 42 vs Pool-first Zerg with POOL_12 holding the natural's timing) |
| `test_threat_flags.py` / `test_m3_checks.py` | 20/20 / 13/13 |
| `test_scout_abilities.py` | shade, Hallucination, Pulsar Beam, detection as in `VERIFY_NOTES.md` M3 findings |
| Ladder zip | `publish/Citadel.zip`, 368 files, 5.4 MB, `run.py`/`ladder.py`/`config.yml` at the top level |

Details and the per-game tables: `docs/VERIFY_NOTES.md`, "M3 acceptance evidence".

## Carry-forward for M4 (squads, EngagementResult gates, retreat hysteresis, end-game)

- **What exists.** `bot/army/basic_army.py` is M1/M2 scaffolding with supply-count gates
  (`ARMY_ATTACK_SUPPLY`, `ARMY_ENGAGE_RATIO`, `ARMY_SUPPLY_PER_CANNON`, ...). M4 replaces them
  with `mediator.can_win_fight` and the §4.5.2 thresholds; `docs/VERIFY_NOTES.md` §11.3 has the
  `EngagementResult` members, the over-rating of Protoss wins, and the static-defence findings
  (`timing_adjust=False` or the penalty).
- **Units other modules control.** `CitadelBot` passes `army.excluded_tags` = the wall-gap holder
  plus `scouts.tags`; the defense plan's `army_hold_point`/`army_leash` and `pinned_unit_tags`
  must keep working with squads. Scouts return unit tags to the army when their task ends.
- **Observers.** From 6:00 one free Observer is left to the army (`BasicArmy` moves free
  Observers with its centre); M4's squads should keep one with the ATTACK squad (§4.3).
- **Remembered enemies.** The scouts feed ares's unit memory (ghosts for 30 s, `is_memory`) and the
  army cache; §4.5.2's inputs use those (§11.2).

## Open question for the user

- **A natural Nexus started before POOL_12 is raised.** §4.2 says to "cancel or delay the natural
  Nexus if it is not yet started", so Citadel keeps one that is already placed. Both 12-pool
  acceptance losses came from it: the opener placed it at ~1:20, the Pool was seen at 1:20-1:21,
  and once the Nexus finished, ares's Mining sent probes out past the wall-gap holder to its
  minerals. Cancelling a started Nexus on the flag would refund 75% and keep probes home, but it
  goes beyond §4.2 as written, so it waits for a decision. **M3 update:** the main probe now sees
  the Pool on entering the enemy main, so POOL_12 was raised by 1:08-1:13 in all ten M3 12-pool
  games, before the opener's Nexus; the question now only matters for a later-scouted 12-pool.

## Known issues (not blocking M3)

- A probe scout coming home while rush Cannons cover the way waits outside their reach for as long
  as they stand; two were caught there by the cannon bot's Stalkers after 5:40.
- The PvT Adept shade sometimes can't reach the enemy ramp bottom safely (Bunker/Marines) and comes
  back after `UNIT_SCOUT_MAX_S` without casting.
- Probe expansion checks from 4:30 cost a mining probe per trip and sometimes the probe (15 lost in
  the 21 built-in Harder games, all after 5:00); an Observer is used when one is free.
- ares's unit-based flags (marauder rush, "went reaper") still raise short ONE_BASE_ALLIN/PROXY
  flags vs the built-in AI (seen twice in the M1 regression, each gone within a minute).
- AIR_HARASS, DT, MACRO, TIMING_ATTACK detectors (§4.4 rows 9, 12-14, 16) are not in any
  milestone yet (user decision for M3: scouting rows 3 and 15 only); the scouts' sightings are in
  ares's memory and `enemy_structures`.

## Known issues from M2

- Cannon rush, main variant, Persephone (opponent seed 106): the rusher's first Cannon finishes
  next to our main Nexus by 2:00 and six more follow; §4.2 stops the probe attack once a Cannon
  completes, and the army never gets going (the Cannons also cover a Gateway). Lost in two of
  three runs.
- M1 Hard game 9 (Ultralove vs Terran) was lost twice on intermediate commits: the army sat idle
  in "attack" state for minutes while a Terran tank/Banshee/Raven contain picked at our bases.
  It won on the final commit and a debug replay of the matchup (the AI's build is random), so
  the cause is unconfirmed. `BasicArmy` does not skip lifted (flying) Terran buildings as
  targets, which ground units can't hit; M4 replaces this army code.
- §4.4's proxy rules raise PROXY vs some built-in AI builds (no production at 1:30, or few
  workers seen by a partial scout); that costs a little economy. M3's scouting should see more.

- The PROXY plan's expansion gate and hold point have no hysteresis: with units dying and
  being replaced they flip every few seconds (seen vs Harder Rush Terran), walking the army
  between the ramp and the natural. The 12-pool gate has hysteresis (`POOL_12_GATE_HOLD_S`);
  the proxy one could use the same.
- With Zerglings loitering near our natural, POOL_12 stays active on its lings source and ares's
  expansion can stall: a Persephone 12-pool game was still on one base with 56 probes at 10:00
  (it had 131 supply and would attack at the M1 150-supply gate).
- `BasicArmy`'s engage rules count supply (`ARMY_SUPPLY_PER_CANNON`, `ARMY_ENGAGE_RATIO`, ...);
  M4's `EngagementResult` gates should replace them.
- The scripted 12-pool bot never expands or drones past 13, so it is harsher than most
  12-pools; the cannon bot builds up to 8 Cannons.
