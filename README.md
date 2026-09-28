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

## Commands

| Task | Command |
|---|---|
| One local game (random map/race) | `poetry run python run.py` |
| N games vs the built-in AI, with a summary | `poetry run python scripts/run_matches.py --help` |
| Combat-sim static-defense test | `poetry run python scripts/test_can_win_fight.py` |
| Build the ladder zip | `poetry run python scripts/create_ladder_zip.py` |
| Check the zip layout | `unzip -l publish/*.zip \| head` (`run.py` must be at the top level) |
