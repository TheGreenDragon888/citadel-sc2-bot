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
| M5 | Done (see `docs/VERIFY_NOTES.md`, "M5 acceptance evidence") | counterattack (§4.6), opponent memory (§5), telemetry to `./data/logs` (§8), step guard (§6) |
| M6 | In progress: pre-upload checks done (see `docs/VERIFY_NOTES.md`, "M6 acceptance evidence"); tested zip uploaded with bot data on and joined to the ladder; the first 20 ladder games pending | zip with the tested libraries, error guard, ladder-environment test, upload and watch scripts |

## Code map (M2-M6 additions)

| File | What it does |
|---|---|
| `bot/intel/threat_flags.py` | `FlagStore`: flags keyed by (threat, source), §5 expiry rules, history for the end-of-game report |
| `bot/intel/ares_bridge.py` | ares intel flags → ThreatFlags (`BRIDGES` table) |
| `bot/intel/detectors.py` | Citadel's detectors: worker rush, cannon structures/probe, early Pool, early lings, proxy (missing/far production), no natural; also the §5 phase rules (`expiry_context`) and scouting state (`main_scouted_at`, `enemy_workers_in_main`, `natural_seen_at`) |
| `bot/intel/scout_planner.py` | M3 `ScoutPlanner`: when each §4.3 scouting task starts and with which unit (Defense > Scouting), expansion checks, §5 re-scouts, Hallucination; `tags` keeps scouts out of the army |
| `bot/intel/scout_tasks.py` | M3 task classes (`MainProbeTask`, `PatrolProbeTask`, `LookTask`/`ProbeLookTask`, `AdeptShadeTask`, `OracleTask`, `PostTask`, `PhoenixTask`) and `Mover` (danger-aware paths, `KeepUnitSafe`, keeps out of static defense's reach) |
| `bot/defense/defense_planner.py` | active flags → one `DefensePlan` (per-threat `_plan_*`), ends the ares opener on override flags; M5: a POOL_12 pre-raised from memory ends it at the opener's expand step (`_end_opener_at_expand`) |
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
| `bot/intel/army_position.py` | M5 §4.4 row 17 detector: ARMY_OUT_OF_POSITION from ares's army cache (value, seen within 15 s, ground path from every known enemy townhall; path lengths cached) |
| `bot/army/counterattack.py` | M5 §4.6: squad/target/recall rules as plain functions, and `Counterattack` (HARASS squad launch, recall, merge into a main attack, outcome records); ticks 8 steps after the main attack decision |
| `bot/memory/opponent_store.py` | M5 §5 opponent memory: `./data/opponents/<OpponentId>.json`, recurring-cheese pre-raise |
| `bot/data_files.py` | M5: the only place Citadel writes files (inside `./data`, atomic), and the `./data` size |
| `bot/telemetry/logger.py` | M5 adds the §8 game record (`./data/logs/games.jsonl`, last 200 games, `METRIC game` on stdout), a 30 s snapshot, startup and step-guard counts |
| `bot/main.py` | M5 adds the §6 step guard (`_check_step_time`), on_start timing, memory load/pre-raise and the end-of-game writes, and `external_tags` (units a dev test drives) |
| `scripts/test_counterattack.py` / `test_counterattack_rules.py` / `test_opponent_memory.py` / `test_step_guard.py` / `check_game_log.py` | M5: 7 staged counterattack cases vs a scripted Terran; offline rules; offline memory + `./data` + log bounds; in-game guard window; game log validator |
| `bot/error_guard.py` | M6 error guard (user decision): each part of a step, the event hooks and ares's after-step run in `ErrorGuard.guard(part)`; an error is logged and counted (`errors` in the game record) and the game goes on |
| `scripts/create_ladder_zip.py` | M6: zips `sc2`, `map_analyzer`, `cython_extensions` from the Poetry environment (the tested versions) and prints the zip's content hash; stops unless run on Python 3.12 (the ladder's) |
| `scripts/test_error_guard.py` | M6: offline guard checks and one game with errors injected in five parts and in ares's after-step |
| `scripts/ladder_env_test.py` (+ `scripts/ladder_env/ipv4only.c`) | M6 §8 ladder-environment test: the real zip in AI Arena's arena client (official proxy/bot images and sc2_controller, this machine's SC2), 10 matches, Citadel's `./data` kept between them |
| `scripts/upload_to_ai_arena.py` / `scripts/ladder_watch.py` | M6: upload `publish/Citadel.zip` (`--upload`) and read Citadel's ladder games, causes and logs from the AI Arena API (`UPLOAD_API_TOKEN`, `UPLOAD_BOT_ID`) |

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
| M5 acceptance (10 VeryHard games per race with a local opponent id; `M5 no crash` summary line; `counter=`/`pre=`/`mem=`/`log=`/`guard=` columns) | `poetry run python scripts/run_matches.py --difficulty VeryHard --race Terran --map all --total 10 --opponent-id local-vh-terran` (also `Zerg`, `Protoss`) |
| M5 staged counterattack (7 cases) / rules / memory / step guard / game log | `poetry run python scripts/test_counterattack.py --case all`; `poetry run python scripts/test_counterattack_rules.py`; `poetry run python scripts/test_opponent_memory.py`; `poetry run python scripts/test_step_guard.py`; `poetry run python scripts/check_game_log.py --last 10` |
| Opponent memory in game (game 3 pre-raises WORKER_RUSH) | `poetry run python scripts/run_matches.py --opponent worker_rush --map all --total 3 --seed 100 --opponent-id local-memory-check` (an id keeps its memory across batches: delete `data/opponents/<id>.json` to start fresh) |
| Same games on two commits (A/B) | add `--game-seed N` (game i uses N + i); `--opener NAME` fixes the opener |
| Ladder zip | `poetry run python scripts/create_ladder_zip.py` (prints the content hash), then `unzip -l publish/*.zip \| head` |
| M6 error guard | `poetry run python scripts/test_error_guard.py` (`--offline` for the no-game checks) |
| M6 ladder environment (Docker running: `dockerd > /tmp/dockerd.log 2>&1 &`, or as a background task with the 2-hour limit) | `poetry run python scripts/ladder_env_test.py` (`--list`, `--matches 10 --keep-data`); workdir `ladder_env/` |
| M6 upload / ladder games (`UPLOAD_API_TOKEN`, `UPLOAD_BOT_ID` set) | `poetry run python scripts/upload_to_ai_arena.py --upload`; `poetry run python scripts/ladder_watch.py` |

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

## M5 checks on the final code (2f082d0; 8c00b0a for the pre-raised POOL_12)

| Check | Result |
|---|---|
| M5 acceptance, staged counterattack (7 cases, `test_counterattack.py`) | PylonAIE_v4 7/7, TorchesAIE_v4 7/7; trigger-and-recall cases 4/4 on each map (≥ 3 needed): PASS |
| M5 acceptance, 30 local games (VeryHard × 10 per race, opponent ids `m5z-vh-<race>`, `--game-seed 3000`) | 0 crashes, §8 log line 30/30: PASS; wins Terran 10/10, Zerg 9/10, Protoss 10/10 (M4 bar ≥ 7 each); 8 counterattacks |
| Offline: counterattack rules / opponent memory / step guard / game log | 36/36 / 38/38 / PASS / PASS (200 games, 0 malformed; `./data` 372 KB) |
| M2/M3 regression, 4 cheese bots × 10 (seed 100, `--game-seed 5000`, opponent ids, so games 3-10 pre-raise) | wins: worker rush 10/10, cannon rush 8/10, 12-pool 9/10, proxy 10/10 (M2 ≥ 8/10: PASS); correct flag 40/40; no scout lost before 4:00 40/40 |
| Pre-raise A/B (same seeds, with and without memory) | cannon rush game 3 won both ways; 12-pool without memory 10/10 and steady at 4:00, with POOL_12 pre-raised (opener ended at 0:00) 3 of 10 starts weak |
| Pre-raised POOL_12 keeps the opener (user decision, 8c00b0a) | 12-pool 10/10, every start steady at 4:00 (14-23 army supply, 0-1 probes lost); VeryHard Zerg with it pre-raised in every game 9/10; opener ended at its expand step at 1:07-1:08 in all 20; 0 crashes, 20/20 log lines |
| M1 regression, Hard × 10 (T/Z/P/Random) | 10/10 wins, 0 crashes, 10 counterattacks; 44+ probes at 6:00 in 6/10 (39-42 in the four Pool-first Zerg games, POOL_12 at 1:10-1:14) |
| `test_attack_decision.py` / `test_threat_flags.py` / `test_m3_checks.py` | 16/16 / 20/20 / 14/14 |
| Ladder zip (rebuilt on 8c00b0a) | `publish/Citadel.zip`, 386 files, 5.5 MB, `run.py`/`ladder.py`/`config.yml`/`protoss_builds.yml` at the top level, `sc2_helper` included, no `data/` |

Details and the per-game tables: `docs/VERIFY_NOTES.md`, "M5 acceptance evidence".

## Carry-forward for M6 (upload with bot data enabled; first ladder games)

- **Bot data.** Opponent memory (`./data/opponents/`), ares's opener data (`./data/<id>-protoss.json`)
  and the game log (`./data/logs/games.jsonl`) only persist when the bot's "bot data enabled"
  setting is on (§2, §9 risk 15). `config.yml` has `BotDataEnabled: True`; check it on the
  AI Arena bot page after the upload. `./data` is not in the zip (local test data stays local).
- **What to watch in the first 20 games** (M6 acceptance: no crashes or timeouts): the bot logs'
  `STARTUP on_start took ... ms` (§6 limit 5 s; 0.6-3.6 s locally), `STEP ... ms` warnings and
  `STEP guard on` lines, `METRIC game {...}` (every §8 metric), `MEMORY` lines (the opponent's
  record and any pre-raise) and `COUNTER` lines. The game log in the bot data holds the same
  JSON lines.
- **Ladder environment test** (§8): done before the upload (`scripts/ladder_env_test.py`, see
  "M6 checks before the upload"); rerun it before every later upload.
- **Counterattacks against bots.** The built-in AI rarely leaves its army seen and far from home,
  so most M5 evidence is staged; the first ladder games are the first real test of §4.6's
  thresholds (`COUNTER_*`, `OUT_OF_POSITION_*` in `bot/constants.py`). Locally: 8 launches in 30
  VeryHard games and 10 in 10 Hard games, most recalled within seconds (see "Known issues").
- **Pre-raises on the ladder.** A cheese seen in 2 of an opponent's last 3 games is raised at 0:00
  (`MEMORY ... recurring cheese` and `FLAG raise ... (STRUCTURE, memory)` lines). POOL_12 keeps
  the opener until its natural step (user decision after the M5 A/B); the others end it at once.
  A pre-raise costs economy when the opponent switches plans (VeryHard Zerg with POOL_12
  pre-raised: 29-43 probes at 6:00), and helps against the cheese it expects.
- **Step times.** Local bot-vs-bot batches run both bots in one Python process and ran five at a
  time on 4 cores; their slow steps (up to 2 s, in every section) are probably the machine. The
  ladder's `STEP ... ms` / `STEP guard on` lines and the `METRIC game` step fields give the real
  numbers.

## M6 checks before the upload (bot code 4d53ca5)

| Check | Result |
|---|---|
| Zip | `publish/Citadel.zip`, 256 files, 9.9 MB, content hash `f02e94a724e15fcf985cca65aa2dfbacace36df9e989a38276fa781a1b9ef4ee` (md5 of the tested build `07db06fe540df9dec7e1105fbc8ab491`); libraries identical to the Poetry environment; imports in the ladder bot image in 1.4 s |
| Error guard (`test_error_guard.py`) | 15/15; Victory with errors injected in five parts every call and in ares's after-step for 30 s |
| M1 regression with the guard, Hard × 10 (T/Z/P/Random) | 10/10 wins, 0 crashes, 0 errors caught, §8 line 10/10 |
| Ladder environment (`ladder_env_test.py`, 10 matches, 7 maps) | 10/10 played to a result with no Citadel crash, time-out or initialization error; startup 441-1074 ms; no guarded error or traceback; WORKER_RUSH pre-raised in the third worker-rush game; `./data` 18 KB with every memory file and 10 game-log lines. One attempt of match 10 ended `Error` (the two SC2 processes never started the game, scored as an arena error); rerun alone, it played normally |

Details and the per-match table: `docs/VERIFY_NOTES.md`, "M6 acceptance evidence".

## Finishing M6 (next session: upload, then the first 20 ladder games)

The environment variables `UPLOAD_API_TOKEN` (the AI Arena API token) and `UPLOAD_BOT_ID` (the
bot's id on aiarena.net, created by the user as Citadel / Protoss / Python) are set in the cloud
environment's settings; a new session picks them up. Check with
`test -n "$UPLOAD_API_TOKEN" && test -n "$UPLOAD_BOT_ID" && echo set` (never print the token).
The code is on branch `claude/eloquent-albattani-lhjcsi` (M5 and M6); `main` is still M4 (e345c04).

**Session of 2026-10-04 (branch `claude/lucid-gauss-cgaphp`, fast-forwarded to 8e59c89).** The
user uploaded the zip by hand. `UPLOAD_API_TOKEN` and `UPLOAD_BOT_ID` were **not set** in that
session's container, and AI Arena's API answers 403 without the token, so step 0's check
(`ladder_watch.py`: `bot_data_enabled=True`, md5 `07db06fe...`) and step 4 are still open; the user
was asked to add both variables in the cloud environment's settings. Done that session: step 1's
rebuild matches the tested zip (content hash `f02e94a7...`, 9,854,928 bytes, 256 files), but only
on Python 3.12, see the next paragraph.

**Session of 2026-10-04, later (branch `claude/modest-einstein-9l4qe7`, fast-forwarded to
ba098e0).** Both variables were set. Steps 0 and 3 are done: `ladder_watch.py` printed
`bot_data_enabled=True zip md5 07db06fe540df9dec7e1105fbc8ab491 updated 2026-10-04T15:11:01Z`,
and `GET /api/competition-participations/?bot=1358` shows Citadel in competition 37 ("Sc2 AI
Arena 2026 Pre-Season 2", open), active, in placements, 0 matches at 15:25 UTC. Step 4 (watching)
is under way with `send_later` check-ins. The 3.12 venv workaround below worked as written.
Still 0 matches at 21:29 UTC: competition 37's round 76 started at 14:48 UTC, before Citadel
was created (15:11), and rounds 72-75 each took 18-20 h (`GET /api/rounds/?competition=37`), so
Citadel's first ladder games are expected in round 77 (about 09:00-12:00 UTC on 2026-10-05).
Round 77 started at 09:16 UTC; at 17:10 UTC 10/20 played games, 8 wins and 2 losses (both
game_rules), 0 guarded errors or tracebacks, startup 440-1095 ms, max step 143 ms, guard never on.
Match 5027201 (vs BlayzReinforcementBot) never ran: the arena client log shows the opponent's
process exiting with status 1 after 1.6 s, while Citadel connected, waited, and exited 0 when the
controller timed out; AI Arena scored `InitializationError` for both (result `none`, no Elo
change). `ladder_watch.py` now lists such matches as `NOT PLAYED (not counted)` and counts 20
played games; a Citadel initialization failure is still a `loss` and counts as a failure.

**The Poetry environment must be Python 3.12** (the ladder image's version; README, Setup). In the
cloud container `poetry env use python3.12` (even with `/usr/bin/python3.12`) builds a 3.11
environment, and a zip built there carries `cython_extensions/bootstrap.cpython-311-...so`, which
the ladder's Python 3.12 can't import (content hash `327d607c...` instead of `f02e94a7...`).
What works: `poetry env remove --all`, then `/usr/bin/python3.12 -m venv
/root/.cache/pypoetry/virtualenvs/ares-sc2-starter-bot-SiapW_LM-py3.12`, `poetry env use
<that path>/bin/python`, `poetry install`; check with `poetry run python --version`.
`create_ladder_zip.py` now stops on any Python other than 3.12 (`LADDER_PYTHON`).

0. **The user uploads the tested zip by hand** (their choice after the pre-upload checks): the file
   sent to them is `publish/Citadel.zip`, md5 `07db06fe540df9dec7e1105fbc8ab491`, content hash
   `f02e94a7...`. If they did, skip steps 1 and 2's upload: run `poetry run python
   scripts/ladder_watch.py` and check that it reports `bot_data_enabled=True` and zip md5
   `07db06fe540df9dec7e1105fbc8ab491`; then go on with step 3.
1. **Rebuild the zip and match it to the tested one.** `poetry run python scripts/create_ladder_zip.py`
   must print `Content hash: f02e94a724e15fcf985cca65aa2dfbacace36df9e989a38276fa781a1b9ef4ee`
   (`publish/` is not in git, so the tested file itself isn't in a new session). A different hash
   means the bot code or a library differs: rerun the M6 checks above before uploading.
2. **Upload with bot data enabled.** `poetry run python scripts/upload_to_ai_arena.py --upload`
   (PATCH `/api/bots/<id>/` with the zip and `bot_data_enabled` from `config.yml`'s
   `BotDataEnabled: True`). Then `poetry run python scripts/ladder_watch.py` prints the bot's
   `bot_data_enabled` and `bot_zip_md5hash`: it must say `True`, and the md5 must equal
   `md5sum publish/Citadel.zip`. `AutoUploadToAiarena` stays False (otherwise every push to `main`
   would upload through the GitHub Action, if the repo had the secrets).
3. **The user joins Citadel to the ladder competition** on the bot's page on aiarena.net (the API
   used here doesn't do that).
4. **Watch.** `poetry run python scripts/ladder_watch.py` lists the games after the upload (result,
   cause, opponent, map, length, AI Arena's average step time) and, from Citadel's match logs
   (saved in `ladder_logs/`), STARTUP ms, the `METRIC game` step times, guarded errors and
   tracebacks; its last line is the acceptance: `M6 acceptance: N/20 games so far, K with a Citadel
   crash/timeout/initialization failure: PASS/FAIL/WAITING`. Ladder games come at AI Arena's pace
   (maybe a day or more for 20): schedule check-ins (`send_later`, every few hours) until it reads
   PASS or FAIL. Report any guarded error (`errors=`) even when the game was fine.
5. **If Citadel crashes or times out:** read its log in `ladder_logs/<match>.zip`, fix, rerun the
   checks above (including `ladder_env_test.py`: start `dockerd` as a background task with the
   2-hour limit; the images are about 11 GB), upload again, and count 20 games from the new upload
   (the plan's rule).
6. **When M6 passes:** fill in the ladder table in VERIFY_NOTES "M6 acceptance evidence", update
   this file, and ask the user to merge M5 + M6 into `main` (their decision: after M6 passes).

## Open questions for the user

- **A natural Nexus started before POOL_12 is raised.** §4.2 says to "cancel or delay the natural
  Nexus if it is not yet started", so Citadel keeps one that is already placed. Both 12-pool
  acceptance losses came from it: the opener placed it at ~1:20, the Pool was seen at 1:20-1:21,
  and once the Nexus finished, ares's Mining sent probes out past the wall-gap holder to its
  minerals. Cancelling a started Nexus on the flag would refund 75% and keep probes home, but it
  goes beyond §4.2 as written, so it waits for a decision. **M3 update:** the main probe now sees
  the Pool on entering the enemy main, so POOL_12 was raised by 1:08-1:13 in all ten M3 12-pool
  games, before the opener's Nexus; the question now only matters for a later-scouted 12-pool.

## Known issues (not blocking M4 or M5)

- **Counterattacks recalled on the way.** In local games most launches end within seconds by
  "enemy army within 20 of the squad" (5 of 8 in the 30 VeryHard games, 7 of 10 vs Hard): an
  army 60-68 from its bases, just past `OUT_OF_POSITION_PATH`, often stands on the squad's way
  to the target. One VeryHard counterattack did what §4.6 is for (7 workers and 6 units killed,
  6 of its 12 units lost). A launch check on the squad's path, or a larger threshold, would
  change §4.6, so it waits for ladder data.
- **Zerg Ley Lines, game seed 3002.** Lost in all three `--game-seed 3000` runs (d24ba02, 5555cfa, 2f082d0):
  a Pool-first Zerg (POOL_12 at 1:12), then a Roach/Ling attack the army never engages
  (`engage=0/0/0`); M4's code lost the Ley Lines game of the Zerg A/B too.
- **Gas piles up under POOL_12.** Every 12-pool game had 469-774 gas banked at 4:00 (the plan's
  units are Zealots and Adepts and "tech waits"); one gas, or fewer gas probes, would put more
  into units. M2 behaviour.
- **Cannon rush 8/10 (M3: 10/10).** In M5 the main variant lost on Ley Lines (10:00) and Pylon
  (11:33), both with CANNON_RUSH pre-raised; replayed, the Ley Lines game was won with and without
  memory, so the main variant is close either way (the Pylon one is the "Cannon finishes next to
  our main Nexus" pattern below). In M4 the Ultralove natural variant tied once. M2's bar (≥ 8/10)
  still holds.
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
