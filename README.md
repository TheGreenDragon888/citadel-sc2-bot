# Citadel

Protoss StarCraft II bot for the [AI Arena](https://aiarena.net) ladder, built on
[ares-sc2](https://github.com/AresSC2/ares-sc2) through the
[ares-sc2-bot-template](https://github.com/AresSC2/ares-sc2-bot-template).
The design spec is [`docs/DESIGN.md`](docs/DESIGN.md); API findings from source are in
[`docs/VERIFY_NOTES.md`](docs/VERIFY_NOTES.md).

## Pinned versions

| Component | Version |
|---|---|
| ares-sc2 (git submodule `ares-sc2/`) | **v3.13.1**, commit `87308658b0dfe1e59486c2b157ef552e9af0c7fd` |
| ares-sc2-bot-template (imported files) | commit `44ebb8c7b848abfb39584e12939e50e5fe77e549` |
| Python | 3.12 |
| StarCraft II (local) | Linux 4.10 (Base75689) |

## Setup (Linux)

```bash
git clone --recursive <repo-url>          # --recursive also fetches the ares-sc2 submodule
cd citadel-sc2-bot
poetry env use python3.12
poetry install
```

StarCraft II lives at `~/StarCraftII` and python-sc2 finds it through `SC2PATH`.
Copy the 7 pool maps from `maps/` into `~/StarCraftII/Maps` (the folder name is case-sensitive).
The 4.10 Linux client looks for maps in a lowercase `maps` folder, so also add a link to `Maps`
(see `docs/VERIFY_NOTES.md`, "Other M0 findings"):

```bash
cp maps/*.SC2Map ~/StarCraftII/Maps/
ln -s Maps ~/StarCraftII/maps     # a symbolic link named `maps` that points at `Maps`
```

## Openers and data

Openers are in `protoss_builds.yml` (ares build runner); their timed steps are
`OPENER_SCHEDULES` in `bot/constants.py`. ares records each game's opener and result in
`./data/<opponent_id>-protoss.json` (`None-protoss.json` in local games) and uses it to pick the
next opener. Delete `./data` to start local selection from scratch.

## Threats and defense (M2)

Every 8 steps `bot/intel/` turns what the bot sees into threat flags (DESIGN.md §4.2, §5): the
ares intel flags (`ares_bridge.py`), Citadel's own detectors (`detectors.py`) and the enemy
natural check by the scouting probe (`scout_planner.py`). `bot/defense/defense_planner.py`
merges the active flags into one plan that the macro, army and worker code follow. Game logs
show `FLAG raise` / `FLAG expire` and `PLAN` lines, and the end of game lists every flag.

Test opponents for the M2 cheeses are in `scripts/test_bots/` (plain python-sc2, not in the
ladder zip): `worker_rush`, `cannon_rush` (SharpCannons-style), `twelve_pool`, `proxy_rax`.

## Army (M4)

`bot/army/` runs the squads (DEFEND at home, ATTACK, REINFORCE groups, the scout planner's
SCOUT units) on Citadel's `EngagementResult` (DESIGN.md §4.5.2): the combat simulator's result
with our shields counted and the defender set (`engagement.py`), the attack/retreat state machine
with its hysteresis and end-game gates (`attack_decision.py`), home defense and targets
(`army.py`), per-step micro (`micro.py`) and the §4.7 structure hunt (`endgame.py`). Game logs
show `ENGAGE` lines at each launch/retreat/recall, `DEFEND` lines when the home-defense decision
changes, and `ENDGAME` lines.

## Counterattack, memory, telemetry, step guard (M5)

- **Counterattack** (DESIGN.md §4.6): `bot/intel/army_position.py` raises ARMY_OUT_OF_POSITION
  when the remembered enemy army is far (ground path) from all its bases; `bot/army/counterattack.py`
  then sends a small fast squad (the HARASS squad) to the least defended enemy base and recalls it
  on §4.6's rules. Logs: `COUNTER launch`, `COUNTER recall`, `COUNTER outcome`.
- **Opponent memory** (§5): `bot/memory/opponent_store.py` keeps `./data/opponents/<OpponentId>.json`
  (the ladder's `--OpponentId`; local games have none, so no memory). A cheese seen in 2 of the
  opponent's last 3 games is raised at 0:00 and acts like the same flag seen in game: it ends
  the opener, except POOL_12, whose plan applies while the opener runs on to its natural step.
  Logs: `MEMORY` lines.
- **Telemetry** (§8): each game appends one JSON line with every §8 metric to
  `./data/logs/games.jsonl` (the last 200 games) and prints it as `METRIC game {...}`.
- **Step guard** (§6): a warning for each step over 30 ms (`STEP ... ms`, naming the slow parts);
  after a step over 200 ms the scout planner, counterattack evaluation and telemetry snapshot
  wait 16 steps (`STEP guard on`).

Citadel writes files only under `./data` (`bot/data_files.py`), which AI Arena keeps between
games when "bot data enabled" is on. Local test runs fill `./data` too; delete it to start over.

## Ladder (M6)

- **Error guard**: each part of a step, the event hooks and ares's after-step run in
  `bot/error_guard.py`'s guard. An error there is logged (`ERROR in <part>`, with a traceback for
  the first three per part) and counted in the game's `METRIC game` line (`errors`), and the game
  goes on: on the ladder an unhandled error loses the game as a Crash.
- **Zip**: `scripts/create_ladder_zip.py` puts in the zip the python-sc2, map-analyzer and
  cython-extensions the Poetry environment has (the tested versions) and prints a content hash, so
  a rebuild can be matched to the zip that was tested.
- **Ladder environment** (DESIGN.md §8): `scripts/ladder_env_test.py` plays the zip in AI Arena's
  arena client in Docker (10 matches); see its docstring for the set-up.
- **Upload and watch**: with `UPLOAD_API_TOKEN` and `UPLOAD_BOT_ID` set,
  `scripts/upload_to_ai_arena.py --upload` uploads `publish/Citadel.zip` with bot data enabled, and
  `scripts/ladder_watch.py` lists Citadel's ladder games, their result causes and its own log lines.

## Commands

| Task | Command |
|---|---|
| One local game (random pool map and race) | `poetry run python run.py` |
| N games vs the built-in AI, with a summary | `poetry run python scripts/run_matches.py --help` |
| M1 acceptance batch (repeat with `--difficulty Hard`) | `poetry run python scripts/run_matches.py --difficulty Medium --map all --total 10 --race Terran Zerg Protoss Random` |
| One opener, forced (no `./data` written) | `poetry run python scripts/run_matches.py --opener B_PvZ --race Zerg --map PylonAIE_v4` |
| Opener selection wiring (ares cycles on a loss) | `poetry run python scripts/test_opener_cycle.py` |
| Ramp wall helpers on both spawns of every pool map | `poetry run python scripts/check_ramp_walls.py` |
| Forced ramp wall fallback (§4.8) | `poetry run python scripts/test_wall_fallback.py --case ramp` (or `--case choke`) |
| Combat-sim static-defense test | `poetry run python scripts/test_can_win_fight.py` |
| M2 acceptance batch, one per cheese bot | `poetry run python scripts/run_matches.py --opponent worker_rush --map all --total 10 --seed 100` (also `cannon_rush`, `twelve_pool`, `proxy_rax`) |
| One cheese variant only | add `--variant natural` or `main` (`cannon_rush`), `third` or `center` (`proxy_rax`) |
| One-base all-in plan vs the built-in AI | `poetry run python scripts/run_matches.py --difficulty Harder --build Rush --race Terran Zerg Protoss --map all --total 3` |
| ThreatFlag expiry rules (§5), no game | `poetry run python scripts/test_threat_flags.py` |
| M3 acceptance: the same cheese batches print `flag=` (on-time, no false flags) and `scouts=` (lost before 4:00 / tasks) per game and two `M3 ...` summary lines | `poetry run python scripts/run_matches.py --opponent worker_rush --map all --total 10 --seed 100` |
| M3 scout losses vs the built-in AI | `poetry run python scripts/run_matches.py --difficulty Harder --race Terran Zerg Protoss --map all --total 21` |
| M3 "correct flag" check, no game | `poetry run python scripts/test_m3_checks.py` |
| Scouting abilities in game (Adept shade, Hallucination, Pulsar Beam, detection) | `poetry run python scripts/test_scout_abilities.py` |
| M4 acceptance: 10 VeryHard games per race; the summary's `M4 wins per race` line needs ≥ 7/10 for each race, and each game prints `engage=` (launches/retreats/recalls), `value=` (army value lost/killed) and `step=` (mean/p99/max ms) | `poetry run python scripts/run_matches.py --difficulty VeryHard --race Terran --map all --total 10` (also `Zerg`, `Protoss`) |
| Attack/retreat gates, hysteresis and the §4.7 45:00 rule, no game | `poetry run python scripts/test_attack_decision.py` |
| Citadel's EngagementResult in game (shields counted, defender set) | `poetry run python scripts/test_engagement.py` |
| §4.7 structure hunt, staged with shortened thresholds | `poetry run python scripts/test_endgame.py` |
| M5 acceptance: 10 VeryHard games per race with a local opponent id; the summary's `M5 no crash` line, and per game `counter=` (counterattacks and why each ended), `pre=` (flags pre-raised from memory), `mem=`, `log=` (§8 line written), `guard=` | `poetry run python scripts/run_matches.py --difficulty VeryHard --race Terran --map all --total 10 --opponent-id local-vh-terran` (also `Zerg`, `Protoss`) |
| §4.6 counterattack, staged (7 cases vs a scripted Terran) | `poetry run python scripts/test_counterattack.py --case all` |
| §4.6 squad, target and recall rules, no game | `poetry run python scripts/test_counterattack_rules.py` |
| §5 opponent memory, `./data` file rules and the game log's bounds, no game | `poetry run python scripts/test_opponent_memory.py` |
| Opponent memory in game (game 3 pre-raises WORKER_RUSH) | `poetry run python scripts/run_matches.py --opponent worker_rush --map all --total 3 --seed 100 --opponent-id local-memory-check` |
| §6 step guard, in game | `poetry run python scripts/test_step_guard.py` |
| Check `./data/logs/games.jsonl` (every §8 field) and the size of `./data` | `poetry run python scripts/check_game_log.py --last 10` |
| Build the ladder zip (prints the content hash) | `poetry run python scripts/create_ladder_zip.py` |
| M6 error guard, offline and in game | `poetry run python scripts/test_error_guard.py` |
| M6 ladder environment (Docker running) | `poetry run python scripts/ladder_env_test.py` |
| M6 upload / ladder games (`UPLOAD_API_TOKEN`, `UPLOAD_BOT_ID` set) | `poetry run python scripts/upload_to_ai_arena.py --upload`; `poetry run python scripts/ladder_watch.py` |
| Check the zip layout | `unzip -l publish/*.zip \| head` (`run.py` must be at the top level) |
