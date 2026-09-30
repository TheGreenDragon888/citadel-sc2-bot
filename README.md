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
| Build the ladder zip | `poetry run python scripts/create_ladder_zip.py` |
| Check the zip layout | `unzip -l publish/*.zip \| head` (`run.py` must be at the top level) |
