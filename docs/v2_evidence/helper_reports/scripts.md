# Audit: scripts/, .github/workflows, README "Commands"

Read-only. Nothing in the repo was changed (`git status` clean after all runs). Scratch files: /tmp/claude-0/-home-user-citadel-sc2-bot/cc35ec4c-9b29-5d67-891d-a94a0ceb8ff8/scratchpad/audit/ (out_test_*.txt = full test output, dry.zip = zip dry run).

Classes: (a) offline test, (b) in-game test, (c) batch runner / tooling, (d) one-off experiment tied to a finished milestone, (e) release tooling.

## 1. Script table

| File | Class | Referenced by | Verdict |
|---|---|---|---|
| run_matches.py | c | README, STATUS, M7_PLAN, VERIFY_NOTES, m3_checks, test_bots, 5 staged tests (import `run_bot_game`) | keep (core). See SCR-6, SCR-7 |
| m3_checks.py | c (library) | run_matches, test_m3_checks | keep |
| check_game_log.py | c | README, STATUS, test_error_guard (imports `problems`) | keep. Its schema matches `Telemetry.game_record` (version 7 keys all present) |
| check_ramp_walls.py | b (plain python-sc2, 14 games) | README, VERIFY_NOTES | keep, low value. SCR-9 |
| create_ladder_zip.py | e | README, CLAUDE.md, STATUS, workflow, ladder_env_test | keep, fix. SCR-1, SCR-2 |
| ladder_env_test.py (+ ladder_env/ipv4only.c) | e (Docker, network) | README, STATUS, M7_PLAN | keep (shim only needed in the cloud container) |
| ladder_watch.py | c/e (network, read only) | README, STATUS, postmortems | keep. Log strings it greps (`STARTUP on_start took`, `METRIC game `, ` - ERROR in `) still exist in bot/ |
| upload_to_ai_arena.py | e (network) | README, STATUS, ladder_zip.yml | keep |
| update_ares.py | e (template leftover) | nothing | remove. SCR-5 |
| create_pyinstaller_exe.py | e (template leftover, Windows only) | only build_windows_exe.yaml | remove. SCR-4 |
| m7_d37_switch_back.py | d | VERIFY_NOTES only | remove. SCR-3 |
| test_air_counters.py | d (M7 E0; exit 0 always) | M7_PLAN, VERIFY_NOTES | remove or archive; result is in VERIFY_NOTES |
| test_can_win_fight.py | d (M0 probe; exit 0 if it completes) | README, VERIFY_NOTES | remove candidate (informational only) |
| test_scout_abilities.py | d (M3 probe; `return 0` always) | README, VERIFY_NOTES, STATUS | remove candidate (findings recorded) |
| test_attack_decision.py | a | README, STATUS, M7_PLAN | keep. SCR-8 |
| test_counterattack_rules.py | a | README, STATUS | keep. SCR-8 |
| test_m3_checks.py | a | README, STATUS | keep |
| test_m7_rules.py | a | M7_PLAN, STATUS | keep; add to README |
| test_opponent_memory.py | a (tmp dir) | README, STATUS | keep |
| test_threat_flags.py | a | README, STATUS | keep |
| test_error_guard.py | a with `--offline`, else b | README, STATUS | keep; README should show `--offline` |
| test_blink.py | b, PASS/FAIL | M7_PLAN, VERIFY_NOTES | keep; add to README |
| test_outranged.py | b, PASS/FAIL | M7_PLAN | keep; add to README |
| test_templar.py | b, PASS/FAIL | M7_PLAN | keep; add to README |
| test_gateway_space.py | b, PASS/FAIL | VERIFY_NOTES | keep; add to README |
| test_counterattack.py | b, 7 cases | README, STATUS | keep. Docstring usage omits `merge` and `early` |
| test_endgame.py | b | README, STATUS | keep |
| test_engagement.py | b | README, STATUS | keep |
| test_opener_cycle.py | b | README, STATUS | keep |
| test_step_guard.py | b | README, STATUS | keep |
| test_wall_fallback.py | b | README, STATUS | keep |
| test_bots/{__init__,common,cannon_rush,proxy_rax,twelve_pool,worker_rush}.py | c (scripted opponents) | run_matches, ladder_env_test, README | keep |
| .github/workflows/ladder_zip.yml | e | STATUS | keep, fix. SCR-2, SCR-10 |
| .github/workflows/build_windows_exe.yaml | e (template leftover) | nothing | remove with create_pyinstaller_exe.py |

Missing scripts: docs/postmortems/2026-10-17-Voltron-timeout.md:108,119 name `scripts/test_ladder_watch.py` and `scripts/test_stall_watch.py`. Neither exists (plan not done, or doc stale).

## 2. Offline tests run (poetry run python scripts/<cmd>, timeout 300 s, all from repo root)

| Command | Exit | Last output line |
|---|---|---|
| test_attack_decision.py | 0 | `16/16 passed` |
| test_counterattack_rules.py | 0 | `36/36 passed` |
| test_m3_checks.py | 0 | `14/14 passed` |
| test_m7_rules.py | 0 | `234/234 passed` |
| test_threat_flags.py | 0 | `31/31 passed` |
| test_opponent_memory.py | 0 | `38/38 passed` (writes only to a tempfile dir) |
| test_error_guard.py --offline | 0 | `CHECK 7/7; RESULT PASS` |

No failures. Counts equal those in docs/STATUS.md:181. Also: all 19 other script modules import cleanly (`importlib`; only create_pyinstaller_exe exits, by design on Linux), so no import of a removed name exists. Not run, by rule: ladder_watch, upload_to_ai_arena, update_ares, ladder_env_test. Not run, need SC2: every (b) script.

## 3. Do the tests test the real code?

- test_attack_decision: real `AttackDecision.evaluate/add_value/recall`. Sound. Literals pin TUNE values (see SCR-8).
- test_counterattack_rules: real `squad_rank/pick_squad/pick_target/recall_reason/recall_at_launch/weighted_center`. Sound; same pinning.
- test_m3_checks: real `flag_check`; expected values come from `M3_EXPECTED_FLAGS`.
- test_m7_rules: real pure functions with `SimpleNamespace` stand-in units. Does not re-implement logic. Weak spots: the duplicate case "mix mode: air share alone is not the air switch" has the same args and expectation as "mix mode: normal"; case `main()` catches every exception as a failed case (fine).
- test_threat_flags: real `FlagStore`; the `UNIT_TTL_S` loop runs 8 entries, not vacuous.
- test_opponent_memory: real `OpponentStore`, `data_files`, `Telemetry.write_game_record` (built via `__new__`). It monkey-patches `data_files.DATA_DIR` and `logger_module.DATA_MAX_BYTES`; works because `data_path` reads the module global.
- test_error_guard offline: real `ErrorGuard`. In-game part: real `CitadelBot`; `game_record(...)` is called without `detectors` (default None, fine).
- test_engagement: bare `AresBot` plus real `Engagement` (`level`, `outranged_share`, `attack_inputs`, `value`, `last_inputs`, `calls` all exist). Real assertions.
- test_endgame, test_step_guard, test_counterattack, test_wall_fallback, test_blink, test_outranged, test_templar, test_gateway_space: `CitadelBot` subclasses; patched names exist where they are read (checked `END_GAME_*`, `ATTACK_START_SUPPLY` in army.py/attack_decision.py, `COUNTER_FROM_S` in counterattack.py:52/302, `home_engages` called at army.py:462, `wall_fallback.WALL_RAMP_MAX_DIST` read in `prepare`, `production.extra_gateway(max_gateways=...)` at production.py:172). No stale name found.
- test_can_win_fight, test_scout_abilities: observation probes; only "completed" decides the exit code. test_air_counters: always returns 0, drops failed games silently (`if (r := play(...))`).
- check_ramp_walls re-implements `WallFallback.prepare`'s criteria instead of calling it (SCR-9).
- Swallowed exceptions: none that hide a failure. `except AssertionError: pass` (check_ramp_walls:68) is deliberate; the staged tests' `except Exception` after `run_bot_game` return False unless the verdict was already formed.

## 4. Stale references

- m7_d37_switch_back.py vs docs/M7_PLAN.md D38: D38 removed C4 entirely. I checked each `old` string against the current code (count of occurrences): C1s 1, HOLD 1/1/1, C2 1, C3 1/1, C5 1, but **C4, C4h, C4r, C4i: 0** (army.py no longer has `since_home_fight_s=...`, `intel_fresh=...`). The script asserts `s.count(old) == 1`, so `ALL` applies C1s, HOLD, C2, C3, then dies on C4 with an AssertionError before C5 and leaves the worktree half-edited. The remaining groups still apply. It records a finished decision (D37/D38). Remove.
- test_counterattack.py docstring usage line lists 5 cases; `CASES` has 7 (`merge`, `early`).
- README Commands: "One opener, forced (no `./data` written)" is wrong; see SCR-7.
- README Commands does not list test_m7_rules, test_blink, test_outranged, test_templar, test_gateway_space, test_air_counters, or run_matches flags `--game-seed`, `--start`, `--time-limit`, `--replays`.

## Findings, by importance

**SCR-1 (bug, Likely): a zip built on Windows cannot run on the Linux ladder.** create_ladder_zip.py:40-52 has a separate Windows branch: `FILETYPES_TO_IGNORE = (".c", ".so", "pyx", "pyi")` keeps `.pyd`; the Linux branch keeps `.so`. The only guard is `check_python_version()` (line ~190, version only, not OS). CLAUDE.md says the bot is also developed on a Windows 11 desktop and gives one build command. A Windows build carries Windows `cython_extensions` binaries (`bootstrap.cpython-312-x86_64-linux-gnu.so` is what the Linux zip has, per STATUS.md:179). Impact: initialization failure on every ladder game if uploaded. Fix: `if platform.system() != "Linux": raise SystemExit`. I could not run on Windows.

**SCR-2 (spec/bug, Verified): the Windows branch also differs in what it packs.** create_ladder_zip.py:41-47: Windows `EXCLUDE` has the typo `"ares-src\\docs"` (docs are not excluded) and no `"__pycache__"` (Linux has it, line 56). So the same commit gives different zips by OS. Linux local vs the GitHub Action (ubuntu, Python 3.12, same script, same lock) should give the same zip: my dry run on this machine (260 files, 31.9 MB unpacked) has content hash `4b9cacf8074af3b678c1c4d742c5053ad124f16a2bb0dcbcfbec0d99329ddabf`, identical to the M7 upload's hash in STATUS.md:179, so the local build is reproducible. Possible Linux differences I could not check: untracked files in `bot/` or `ares-sc2/` locally (the script zips directories, not tracked files), a different cpu architecture, and wheel builds. Fix: also add a OS check; optionally have the Action print the hash and compare with the one in STATUS.

**SCR-3 (dead, Verified): m7_d37_switch_back.py is dead and partly broken** (section 4). Remove.

**SCR-4 (dead): create_pyinstaller_exe.py and build_windows_exe.yaml** are an ares template Windows-exe path (default name `aresbot`, bundles `ares-sc2/sc2_helper`). Citadel ships a Linux Python zip. Nothing references them but each other; the workflow is `workflow_dispatch` only. `pyinstaller` in pyproject.toml is only for this (removing the dependency needs the owner's OK).

**SCR-5 (dead/risk, Verified): update_ares.py** runs `git submodule deinit -f .`, `git submodule update --remote` (moves ares off the pinned v3.13.1, against CLAUDE.md "Don't edit the ares-sc2 submodule"), `poetry remove`, edits pyproject.toml and relocks. Unreferenced. Remove.

**SCR-6 (capability gap): run_matches cannot run Citadel against arbitrary bots or an older commit in one process** (section 5).

**SCR-7 (doc/bug, Verified): `--opener` games still write ./data.** run_matches.py:101-105 sets `UseData=False` (ares opener data) only. `CitadelBot.on_end` (main.py:389-400) always calls `telemetry.write_game_record`, which appends to ./data/logs/games.jsonl (logger.py:425-441, capped to the last GAME_LOG_KEEP lines, oldest dropped). README and the class docstring ("Those games don't write ./data") say otherwise. For tuning: do not use games.jsonl as the result store; parse the `ROW` lines.

**SCR-8 (rule/fragility, Verified): tests pin TUNE values as literals.** test_attack_decision.py cases use 150, 190, levels 8/7/5/4, 0.4 (1100/1200 of 3000), 20 s, 1.2 against `ATTACK_START=8`, `ATTACK_START_SUPPLY=150`, `ATTACK_START_MAX=5`, `ATTACK_START_MAX_SUPPLY=190`, `RETREAT_AT=4`, `RETREAT_VALUE_FRACTION=0.4` (constants.py:766-780). test_counterattack_rules.py ("cap 14 supply", `len(squad) == 7`, 25 %) pins `COUNTER_SQUAD_MAX_FRACTION=0.35`, `COUNTER_SQUAD_MIN_SUPPLY=8`. Any tuning of those constants fails these tests though the logic is right. Fix: derive the cases from the constants.

**SCR-9 (dup logic, Verified): check_ramp_walls.py:44-50** recomputes `wall_ok` (pylon/buildings>=2/warpin/top_dist) instead of using `WallFallback.prepare` (wall_fallback.py:72-101, which uses the same rules), and exits 0 whenever 14 rows were collected, regardless of `wall_ok`. It can drift from the bot and cannot fail on a bad wall. Fix: call the bot's `prepare`, or drop the script (the runtime `wall_ok` log covers it).

**SCR-10 (CI, Verified): the workflow runs no tests.** ladder_zip.yml builds and uploads on every push to main; none of the seven offline tests runs. The upload step is a no-op today because config.yml has `AutoUploadToAiarena: False` (upload_to_ai_arena.py:61-69), but setting it True would upload an untested zip on every push. Fix: add `poetry run python scripts/test_m7_rules.py` etc. before the build.

**SCR-11 (low): unseeded randomness in the scripted opponents.** cannon_rush.py:152,154 use `ready_pylons.random` (python-sc2 `Units.random` = `random.choice`, units.py:158-160), so `--seed` does not fully fix cannon_rush. run_matches `--map random` (default) uses unseeded `random.choice` (run_matches.py:240), so `--start` replay of a cut batch only keeps its maps with explicit map lists.

**SCR-12 (low): ares content in the zip.** `ares-sc2` is zipped whole (145 files: `.git` file, `.github`, `examples`, `sc2_helper`, `poetry.lock`, `pytest.xml`; only `src/` = 113 files is needed). Harmless, but it inflates the zip and the content hash.

**SCR-13 (low): thresholds in scripts, not constants.py.** run_matches.py:70-71 `M2_WIN_RATE=0.8`, `M4_WIN_RATE=0.7`, `PROBES_AT_S=360` (other M3 rates are in constants.py). These are acceptance targets, not bot TUNE values; moving them is optional.

## 5. run_matches.py: what it can do

- Opponents: built-in AI via `Computer(opp_race, difficulty, ai_build=ai_build)` (line 351). `--difficulty` any `Difficulty` name (VeryEasy to CheatInsane), `--build` any `AIBuild` (RandomBuild, Rush, Timing, Power, Macro, Air), `--race` list cycled per game (lines 126-139). Or `--opponent` = one of `TEST_BOTS` (worker_rush, cannon_rush, twelve_pool, proxy_rax; test_bots/__init__.py:15-19) with `--variant` and `--seed` (seed + game index, line 346). Only these four classes; no flag takes another bot's path or class.
- Citadel always comes from the checkout the script lives in (`ROOT` = parent of scripts/, lines 53-55, `from bot.main import CitadelBot`). An older commit works by running the script from a git worktree of that commit (the docs call these "experiment worktrees"); two versions cannot meet in one process (same `bot` package). Old-vs-new needs ladder_env_test's mirror (`Citadel2`, both from one zip, Docker). Another real bot: `run_bot_game(map, [Bot(race, ours), Bot(race, other)], replay, limit, seed)` (lines 212-233) takes any python-sc2 bot, as the staged tests do with their own `StagedEnemy`. An ares-based second bot in the same process is unchecked (ares reads cwd config and ./data).
- Parallel: none. One sequential `for` loop (line 340), one SC2 per game (two for bot-vs-bot). Two script processes at once would share ./data/logs/games.jsonl.
- Per-game output: one `ROW ...` line to stdout (line 462, `flush=True`) with map, race, opener, probes@6:00, bases@6:00, result, game time, real time, flags, engage launches/retreats/recalls, army value lost/killed, step ms mean/p99/max, counterattacks, errors caught, scouts lost, M7 fields (lost-far, blinks, storms, mix modes, 4th base time); a summary table plus PASS/FAIL lines at the end; optional replay per game (`--replays DIR`, lines 360-363). No machine-readable output file; exit 1 only on a crash.
- Seeds: `--game-seed N` gives game i the SC2 `random_seed` N+i (lines 364, 380, 224); `--seed` seeds only the cheese bot's own rng; Citadel itself uses no `random` (grep bot/: none). Games stay non-deterministic (timing).
- Other controls: `--time-limit` (game seconds before Tie, default 3600), `--opener NAME` (forces one build by narrowing `BuildChoices`, lines 84-105), `--opponent-id` (turns on memory and ares data, lines 355-356), `--start`, `--map` list/`all`/`random`. No way to override a bot/constants.py value from the CLI: modules do `from bot.constants import X`, so tuning needs per-module patching as test_endgame/test_counterattack do (`module.X = ...` before `run_game`).

## 6. ladder_env_test.py: setup (code and comments only)

- Images: `aiarena/arenaclient-proxy:v0.8.0` and `aiarena/arenaclient-bot:v0.8.0` (lines 63-65), pulled with docker. `sc2_controller` is not run from its image: the script downloads that image's last layer (`aiarena/arenaclient-sc2`, sha256 `1e7d7a0d...`, lines 66-69) from `registry-1.docker.io` with a token from `auth.docker.io`, checks the digest, extracts `app/sc2_controller` and runs it in the proxy image with this machine's SC2 4.10 mounted read-only from `SC2PATH`/`~/StarCraftII`. Reason in the docstring: the sc2 image does not fit the cloud disk.
- Layout from `github.com/aiarena/local-play-bootstrap` at commit `6de4228` (git clone, host-network compose, `config.toml` copied).
- IPv6: if the kernel has none, `gcc` builds `scripts/ladder_env/ipv4only.c` into an LD_PRELOAD shim (socket/bind/connect/setsockopt rewritten to IPv4) for the proxy and sc2 controller only.
- CPU/memory limits: none in the compose text (lines 118-160 set `network_mode: host`, ports, volumes only), so the test does not reproduce the ladder's resource limits. Per-match timeout 7500 s (arena MAX_REAL_TIME 7200 s).
- Python/packages: not set by this script. The bots run as `python run.py --GamePort ... --OpponentId ...` inside the bot image; Python 3.12 comes from create_ladder_zip.py:26-29 (`LADDER_PYTHON`, "Python of aiarena/arenaclient-bot:v0.8.0"). The zip carries sc2, map_analyzer, cython_extensions from the Poetry env; cheese bots get the installed `sc2` copied in. Opponents: loser_bot and basic_bot from the bootstrap repo, the 6 packaged cheese bots, and a mirror copy of the zip; 10 matches over 7 maps.

## 7. Zip and workflows

- Zip contents (Linux dry run, 260 files): `bot/` (33), `ares-sc2/` whole minus build/dist/tests/docs (145), `sc2/` (49), `map_analyzer/` (21), `cython_extensions/` (8, incl. the `.so`), and top-level `config.yml`, `ladder.py`, `run.py`, `protoss_builds.yml` (terran/zerg build files only if present; they are not). No `scripts/`, no `data/`, no `__pycache__`, no `.c/.pyx/.pyi/.pyd`. `check_config_values()` asserts `Debug: False`.
- Local vs Action: both run `scripts/create_ladder_zip.py`, Linux, Python 3.12, locked deps, so they can match (local hash equals the M7 upload's). They can differ on: an untracked or modified file in a local `bot/` or `ares-sc2/` (Action sees only committed files), CPU architecture/wheel, and any Windows build (SCR-1, SCR-2). The Action also never checks the hash or runs tests (SCR-10). Windows exe workflow is manual only and produces a different artifact kind (SCR-4).

## 8. test_bots: strength and variety

Four single-plan cheese bots, all one-base, no micro beyond focus-fire; none harasses, drops, or attacks two places. All target `their_main` or mineral line.
- worker_rush: all starting workers attack; reinforces 3 at a time beyond 4 home miners. Race-agnostic.
- cannon_rush: variants natural/main; forward Pylon, up to 8 Cannons; after 4 Cannons or 4:00 adds 3 Gateways, Core, Zealots/Stalkers in groups of 6 straight at the main (the only follow-up, still one target).
- twelve_pool: 6 Zerglings first wave, then groups of 4, speed upgrade, one Queen, no expansion or tech.
- proxy_rax: 2 proxy Barracks (variants third/center), Marines from first wave of 4, third Barracks at home after 2:30, no stim or medivacs.
Variety is the 4 openings plus 2 variants each and 3 races for worker_rush. No late-game, macro, air or multi-prong opponent exists in scripts/; the staged tests' `StagedEnemy` bots only stand and fight.

## What I could not check

- Any in-game script (no SC2). Their PASS/FAIL logic was read, not run.
- Windows behaviour of create_ladder_zip.py (SCR-1/2 are from the code).
- Whether the GitHub Action's output hash equals the local one (no network, no CI logs).
- ladder_watch.py beyond its header and the log strings; upload_to_ai_arena.py beyond reading it (no network).
- Docker/ladder CPU and memory limits (not in the scripts).
- Whether two ares bots can share one process.

Files read fully: run_matches, m3_checks, m7_d37_switch_back, test_attack_decision, test_m3_checks, test_m7_rules, test_threat_flags, test_counterattack_rules, test_opponent_memory, test_error_guard, test_engagement, test_endgame, test_step_guard, test_wall_fallback, test_opener_cycle, check_game_log, check_ramp_walls, create_ladder_zip, ladder_env_test, ipv4only.c, upload_to_ai_arena, update_ares, all test_bots, both workflows, test_can_win_fight (most). Read in part (docstrings, setup, verdict code): test_counterattack, test_air_counters, test_blink, test_outranged, test_templar, test_gateway_space, test_scout_abilities, ladder_watch, create_pyinstaller_exe.
Library calls checked: python-sc2 `run_game`, `_host_game`, `_join_game`, `game_time_limit` (seconds), `random_seed` (host only), `Units.random`; ares `request_building_placement`, `HordeManager.on_building_started` (hub.py:316).
