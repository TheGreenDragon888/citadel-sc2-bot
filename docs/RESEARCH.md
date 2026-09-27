# DOCUMENT 1 — RESEARCH REPORT

## Area 1: Platform and technical requirements

### 1.1 AI Arena rules and submission (mostly Verified)

- **Zip format (Verified, AI Arena wiki "Getting Started"):** "For a successful upload the Bot must be packed using zip. (Max 50 MB)". The entry file must be "in the root path after extraction (**Don't zip the directory**)". So `Citadel.zip` must contain `run.py`, `bot/` and so on directly, not `Citadel/run.py`.
- **Persistent data (Verified, same page):** "The bots may write to a `./data` directory. Any files in the data directory will persist between games. The data can be downloaded via profile page."
- **Opponent identification (Verified, AI Arena wiki "Bot Development"):** "A unique ID for each opponent is provided… as a command-line argument after a `--OpponentId` flag… This ID can be saved in your bot's data folder if desired."
- **Rules (Verified, AI Arena wiki "Rules"):**
  - No network access "besides connecting to the local sc2api process or the aiarena api".
  - No purposely slowing the system.
  - No "huge amounts of data on the disc without purpose".
  - No clones of other bots. You may use an existing bot as a starting point only with the author's permission and after modifying it.
  - The bot must be "trying to win its matches".
- **Game version (Verified, AI Arena wiki "Bot Development", SC2 Version Considerations):**
  - "There are no Linux builds past Build 75689" (4.10). The wiki adds that "Blizzard's support for the Protobuf API and bot play seems to be nonexistent as of 2022" and that "Several attempts have been made to contact Blizzard to release a newer Linux build, but to no avail."
  - Bot-vs-bot games on newer builds tend to desync ("On 5.0.10, around 80% of games may end up desynced"). The wiki's advice: "just use Build 75689".
  - "To stay up-to-date with the meta, we use custom maps (suffixed with `AIE`) with the latest balance patches applied." The aiarena/sc2patch repo describes this as modifying "map files to replicate behavior of the live version".
  - **Design implication:** the engine is 4.10, but unit stats follow the patched maps. Read costs, cooldowns and energy from `self.game_data` at runtime rather than hard-coding human-ladder numbers.
- **Map pool (Partly verified; conflicting labels):**
  - The 2025 AI Arena tournament used ThunderbirdAIE, AcropolisAIE, InterloperAIE, EphemeronAIE, AutomatonAIE and AbyssalReefAIE (AI Arena wiki, 2025 Tournament page).
  - The wiki Maps page lists "Sc2 AI Arena 2025 PreSeason 2" as its newest download, but still labels "2024 Season 1 Version 1" as the "Current map pool". That label is evidently stale.
  - The same page says maps for running competitions are on each competition's page. I could not render those pages; they load with JavaScript.
  - **Conclusion (Uncertain):** I could not confirm the exact Fall-2026 pool. Treat it as "whatever the active competition page lists", and write map-agnostic code: no hard-coded coordinates, use MapAnalyzer/ramps.
- **Ladder mechanics (Verified, AI Arena wiki "Ladders"):**
  - Round-robin rounds.
  - Elo starts at 1600 with K = 16.
  - "Bots are automatically deactivated at the start of a season", so you must re-activate after each new season and new map pool.
  - Bots can tag matches by sending a chat message starting with `Tag:`. That is useful for logging which build was chosen.
- **Match requests (Verified, wiki "Match requests"):** "The default limit is 30 matches per month", which can be raised via Patreon. A recent aiarena-web pull request adds optional bot arguments to *requested* matches, but "Ladder matches never carry any."
- **Current activity (Verified):**
  - The aiarena-web repo has an open issue dated Sep 24, 2026 about running matches in parallel.
  - The site's stream page shows a Sept 23, 2026 date.
  - YouTube VODs show a "Fall 2026" tournament with an "Active Author Qualifier" and Swiss days.
  - The platform is clearly active in late 2026.
- **Step-time limits (NOT verified):**
  - Matches are run by the Rust `sc2-ai-match-controller`; the older Python arena client was archived in July 2023.
  - I could not find the exact per-step timeout, strike count or game-length limit in public docs.
  - The legacy arena client was commonly believed to use about 40 ms per frame with 10 strikes, a game cap of about 60,486 game loops (≈45 minutes) and a ~60 s startup timeout. Treat these as **Uncertain** and design to stay well under them.
- **Known API quirks (Verified, wiki "Bot Development"):**
  - The API does not expose the enemy Adept shade timer, the unit type of a Stargate warp-in, enemy Chrono Boost, enemy Metabolic Boost/Tunneling Claws upgrades, or Hatchery→Lair morphing.
  - Bots instantly recognise cloaked units and Changelings, and enemy unit IDs stay stable across visibility.
  - An "APM bug" appears at extreme action rates. It has been "observed most commonly around 120k APM (although some have observed this issue at 60k APM)": orders queue up, and units may execute orders that are "very old (even an hour of ingame time)".
  - In python-sc2, keep unit **tags** between steps, not `Units` objects.

### 1.2 Python frameworks compared

| Framework | Status (2026) | What you get | Learning curve | Verdict |
|---|---|---|---|---|
| **python-sc2 (BurnySc2)** | Maintained. Issues filed through Nov 2025. AI Arena calls it "Recommended for beginners" and the "Most popular/supported interface" | Raw game-state API, examples, ramp helpers, `run_game`. Needs Python 3.9+ | Low | The foundation. Too bare for a 2-week feature-rich bot on its own |
| **ares-sc2** | Very active: 1,315 commits, CI for lint/tests/docs, template updated for Python 3.11/3.12 | Build runner from YAML (`protoss_builds.yml`), cycles builds on defeat; `mediator` with unit roles, worker selection, ground/air grids with enemy influence, pathing (`find_path_next_point`), MapAnalyzer, CombatSim (`can_win_fight`), KD-tree range queries, `BuildStructure`/production controllers, precomputed Protoss production layouts, combat behaviours (`KeepUnitSafe`, `PathUnitToTarget`…) | Medium. Still "resembles starting with a blank python-sc2 bot" | **Chosen** |
| **sharpy-sc2** | Works. README: "a work in progress". Python 3.8/3.9/3.11. Its ladder script still lists 2021 maps | Complete bot kit behind Sharpened Edge. Plan/Step build DSL, many ready "dummy" bots (SharpCannons, BluntCheese, BluntWorkers, RustyOneBaseTurtle, etc.) | Medium–high, opinionated | Use its **dummy bots as test opponents**, not as Citadel's base |
| **pysc2 (DeepMind)** | Built for ML research | Feature layers for RL | High | Out of scope |

**Why ares over plain python-sc2 (Verified features, Likely conclusion):**
- Citadel's hardest parts are defensive micro, worker pulls, safe pathing, "should I fight?" decisions and build switching. ares already solves them.
- ares ships a GitHub Actions workflow that builds the Linux ladder zip and can auto-upload it to AI Arena with an API token and bot ID.
- **Main risk:** the ares template README warns that, because ares depends on Cython, the zip script "is necessary to execute… on a Linux environment in order to generate Linux binaries". Your Ubuntu VM or the GitHub workflow handles this.

### 1.3 Local development

- **Headless Linux SC2:** Blizzard's s2client-proto Linux package, which the ares template points to. Alternatively, Battle.net through Wine/Lutris with env vars `SC2PF=WineLinux`, `SC2PATH=...` and `WINE=...` (ares template and python-sc2 README).
- **Maps:** copy them into `StarCraftII/Maps`. "Note for linux users: the folder name is case sensitive" (AI Arena wiki Maps).
- **Ladder-identical matches:** `aiarena/local-play-bootstrap` runs matches "using the same set of docker images that the AI Arena ladder runs on":
  - Put bots in `./bots`, maps in `./maps`, and list matches in the `matches` file.
  - Run `docker compose up`.
  - Results appear in `results.json`, replays in `replays/`, logs in `logs/`.
  - A bot that connects to localhost fails with "Could not find port for started process". Fix it by honouring the `--LadderServer` argument, e.g. `--GamePort 8080 --LadderServer 172.18.0.2 --StartPort 8080 --OpponentId ABCD`, or use `docker-compose-host-network.yml`.
- **Built-in AI testing:** python-sc2's `run_game(... Computer(Race.X, Difficulty.Y, AIBuild.Z))`, with `realtime=False` so the game waits for each bot step.
- **Replay analysis:** the ladder result pages and the Data API. The wiki describes fetching match participations, then results, then the `replay_file` URL.
- **Windows vs Linux:**
  - On Windows you get the full graphical client, but Battle.net installs the *latest* build, not 4.10.
  - When running under WSL, "python-sc2 detects WSL by default and starts Windows Starcraft 2 instead of Linux Starcraft 2" (python-sc2 README).
  - Cython `.so` files built on Windows (`.pyd`) will not run on the ladder.
  - Map folder case matters only on Linux.

## Area 2: The bot-ladder meta

- **Who is strong (Partly verified):**
  - I could not render the live ranking or the API output, so I cannot name the current top-10 with confidence (**Uncertain**).
  - Long-running Protoss bots include **Sharpened Edge** (sharpy-sc2's author's bot, created 2019 and still listed on aiarena.net in 2026) and **Aeolus**, a newer C++ Protoss bot "inspired by… ares-sc2" whose README has an "AIArena ladder build" section.
  - **CannonLover** is an open python-sc2 example of how a Protoss bot is organised. It cannon-rushes into macro, "compare[s] nearby friendly vs enemy army size before taking an engagement (measured by health + shield)" and "remembers enemy units no longer in sight to better know when to engage, and to avoid dying on ramps" (sc2ai wiki).
- **Threats Citadel must survive (Verified that they exist as bot strategies; prevalence is Likely):**
  - The sharpy dummy roster alone includes proxy zealot rush, cannon rush (SharpCannons), worker rush (BluntWorkers), 12-pool/cheese (BluntCheese), roach/ling all-ins, marine rushes and one-base turtles.
  - In a 26 Jan 2017 guest post on Jay Scott's satirist.org Starcraft AI blog ("the end of the rushbots"), Martin Rooijackers, author of the Brood War Terran bot LetaBot, records that worker rushes beat established bots: "In 2016, LetaBot used the same strategy to defeat several bots (BeeBot, XelnagaII, Iron Bot, Krasi0)". The same source advises:
    - "keep on building worker units no matter what";
    - "pull back worker units that are damaged";
    - "have a zealot out before the opponent has a critical mass of worker units";
    - "with proper scouting, a bot should be able to stop any rush build if it starts out with a safe build order."
- **Bot-vs-bot differences (Verified API facts, Likely behavioural conclusions):**
  - Bots have perfect multitasking and focus-fire, and see cloak and changelings instantly.
  - Scripted bots are predictable: the same opener every game, or cycling through a fixed list. Per-opponent memory via `--OpponentId` + `./data` is therefore unusually valuable.
  - Common weaknesses are fighting on bad terrain, chasing units forever, trickling reinforcements, and failing against unusual compositions or timings.
- **Lessons from authors (Verified from wiki/READMEs):**
  - Store tags, not Unit objects.
  - Keep APM sane (the APM bug, seen around 120k and sometimes 60k APM).
  - Test on the ladder's 4.10 engine, not a newer build.
  - Re-activate after season resets.
  - Mineral-gathering micro ("speed mining") pays off. ImpulseCloud (Holtan), quoted on the AI Arena wiki, reports "a 10% speedup doing sock-folding and a couple of other tricks", and Soupcatcher's Zoe gathered "3975 minerals in 5 minutes (6720 frames) using 12 workers that's 12% more of the 3550 an idle bot would get". ares advertises "speed mine" in its test bot.

## Area 3: Protoss strategy from high-level human play

**Source caveat:** I spent this pass's search budget on platform and framework sources, so the build orders below come from standard, long-stable LotV Protoss practice rather than freshly fetched pro guides (**Likely**). The AIE maps apply newer balance patches, so any number tied to balance (Shield Battery values, Oracle/Revelation energy, Hallucination cost) must be read from game data at runtime. Treat all timings as tuning targets.

- **Standard skeleton (all matchups):**
  1. 14 Pylon
  2. 16 Gateway
  3. 17 Assimilator
  4. ~19–20 Nexus
  5. 20 Cybernetics Core
  6. 21 second Assimilator
  7. 22 Pylon
  8. When the Core finishes: Warp Gate research plus the first unit (Adept or Stalker)

  Chrono Boost the Nexus (probes) until Warp Gate starts, then Warp Gate/Robo/Stargate. Target 16 mineral + 6 gas probes per base (2 per patch, 3 per geyser), 44 probes on 2 bases around 5:30, and 60–70 on 3 bases.
- **PvT:**
  - Threats: proxy Barracks/Reaper, bunker rush, 2-/3-rax, early Cyclone/Hellion.
  - Standard responses: Stalker first, Shield Battery at the natural, Robo → Observer.
- **PvZ:**
  - Threats: 12-pool, ling floods, roach/ravager all-ins.
  - Standard: Adept first, Stargate → Oracle (scouting plus Revelation), Batteries at the natural, third Nexus around 4:00 if safe.
  - Humans also use a natural wall; for a v1 bot, holding the main ramp plus Batteries is simpler.
- **PvP:**
  - Threats: proxy gates, cannon rush, 4-gate/blink all-ins, Adept/Oracle harass.
  - Standard: 2 gas, Stalker, Robo, delayed Nexus.
- **vs Random:** use the PvT skeleton (Stalker first) until the race is revealed, then branch.

## Area 4: Scouting-to-decision logic

- **Representation (design recommendation, Likely):** keep a hypothesis score per enemy plan, e.g. `P(proxy)`, `P(12pool)`, `P(cannon_rush)`, `P(one_base_allin)`, `P(macro)`.
  - Each scouting observation adds or subtracts evidence, or sets a hard trigger for certain signals (e.g. an enemy Pylon in our base).
  - Evidence decays with age.
  - Re-scout whenever the top hypothesis is ambiguous (<0.6), the last sighting of the enemy main/natural is older than about 60 s after 3:00, or an expected structure is missing.
- **How existing bots do it:**
  - Ares cycles builds on defeat through its data manager (Verified).
  - CannonLover keeps a memory of enemy units (Verified).
  - sharpy-sc2 contains an enemy rush/build detector. This is from my memory of its source, not re-fetched this pass (**Uncertain**).
  - The full observation → inference → response table is in Document 2, §4.4.

## Open Questions
1. The exact Fall-2026 ladder map pool and season name. Check the active competition page after logging in.
2. The exact step-time/strike/game-length limits in `sc2-ai-match-controller`. Ask in the AI Arena Discord or read the repo config.
3. The Python version and preinstalled packages in the current ladder Docker image. The ares template's Linux build implies 3.11/3.12 compatibility (**Likely**, not confirmed).
4. The current top Protoss bots and their public repos. The ranking pages would not render for me.
5. Which balance-patch values the current AIE maps carry (e.g. Battery, Oracle, Sentry). Read them at runtime.

---

# DOCUMENT 2 — DESIGN DOCUMENT FOR CLAUDE CODE

> Audience: an AI coding agent that has not seen the research. Everything needed is here. Where a value is marked **TUNE**, treat it as a starting point and adjust through testing.

## 1. Overview

**Vision.** Citadel is a Protoss bot for the AI Arena StarCraft II ladder. It is:
1. **Economy-first:** it never stops probe production before ~66 probes, saturates quickly, and expands on schedule unless intel says otherwise.
2. **Defense-first:** it holds worker rushes, cannon rushes, 12-pools, proxy Barracks/Gateways and early one-base all-ins.
3. **Information-driven:** it runs a scheduled scouting plan, and an intel model turns sightings into hypotheses that choose defensive branches.

**Win condition (v1).** Macro to 3 bases, then build a Stalker/Immortal/Colossus/Zealot army (Archons optional) with +1/+2 upgrades. Attack when (a) `supply_used ≥ 150` **and** the combat simulator (`mediator.can_win_fight`) says we win against the known enemy army, **or** (b) supply is ≥ 190. After a won fight, target the enemy's newest expansion, then production. After a lost simulation, retreat to the defensive position at our newest base and re-max.
- **Why:** a bot that out-mines and out-defends its opponent has a bigger army by about 8–10 minutes. The risk is spending it badly, and gating attacks on the simulator is the fix.
- **v2 extension:** Carrier/Void Ray/Tempest late game on 4+ bases, and per-opponent build selection.

**Definition of done for v1:**
- Beats built-in AI VeryHard in ≥ 80% of games, and Harder/Hard in ≥ 90%, across all 3 races on 3 AIE ladder maps.
- Survives worker rush, cannon rush, 12-pool and proxy-rax test bots in ≥ 80% of games.
- Never crashes. No step above 100 ms. Mean step ≤ 15 ms.
- Uploads and runs on AI Arena, and writes an opponent log to `./data`.

## 2. Technical stack

- **Framework:** ares-sc2, used through the official template (`AresSC2/ares-sc2-bot-template`, which includes ares as a git submodule). The bot class subclasses `AresBot`. Plain python-sc2 calls are allowed anywhere.
- **Python:** 3.12 (3.11 is also fine). Dependency manager: Poetry, as the template uses.
- **Game:** SC2 Linux headless 4.10 (Build 75689) for testing. The ladder uses the same engine.
- **Dependencies:** those from the template (ares-sc2, python-sc2, numpy, cython-extensions-sc2, map analyzer, sc2-helper combat sim), plus `pyyaml` (already used by ares) and the standard library `dataclasses` and `json`. Add nothing else in v1.
- **AI Arena packaging requirements:**
  - A zip of at most 50 MB with `run.py`/`ladder.py` at the zip root, not inside a folder.
  - Build it on Linux with the template's `scripts/create_ladder_zip.py`, or via the template's GitHub Actions workflow, which produces the artifact `ladder-zip.zip` on every push to `main`.
  - The bot must accept the ladder arguments `--GamePort`, `--LadderServer`, `--StartPort` and `--OpponentId`; the template's `ladder.py` handles these.
  - Write only to `./data`, and keep that folder small (under 5 MB).
  - Network access is forbidden.

### 2.1 Linux setup, explained step by step (Ubuntu 24.04 VM on Proxmox)

**Proxmox VM:** create a VM with Ubuntu Server 24.04, 4 vCPU, 8 GB RAM and a 60 GB disk. No GPU is needed because the Linux SC2 build is headless (it has no graphics). The commands below are typed in the VM's terminal, over SSH or the Proxmox console.

```bash
sudo apt update
```
`sudo` runs the command as administrator. `apt` is Ubuntu's package manager, and `update` refreshes its list of available software without installing anything.

```bash
sudo apt install -y git unzip wget curl python3.12 python3.12-venv python3-pip build-essential
```
`install` downloads and installs the listed packages. `-y` answers "yes" automatically.
- `git` downloads code repositories.
- `unzip`, `wget` and `curl` extract archives and download files.
- `python3.12-venv` lets Python create isolated environments.
- `build-essential` provides the C compiler that Cython needs to compile ares's fast extensions.

```bash
cd ~
wget http://blzdistsc2-a.akamaihd.net/Linux/SC2.4.10.zip
unzip -P iagreetotheeula SC2.4.10.zip
```
- `cd ~` moves to your home folder (`~` means `/home/<you>`).
- `wget URL` downloads Blizzard's official Linux build 4.10. (The Blizzard s2client-proto README confirms the password: "The files are password protected with the password 'iagreetotheeula'"; this download URL is the one community guides use.)
- `unzip -P <password> file` extracts it. `-P` supplies the archive password, which represents accepting Blizzard's AI and Machine Learning licence.
- The result is a folder `~/StarCraftII`.

```bash
mkdir -p ~/StarCraftII/Maps
unzip <downloaded_ladder_maps>.zip -d ~/StarCraftII/Maps
ls ~/StarCraftII/Maps
```
- `mkdir -p` creates the folder; `-p` means "don't complain if it exists, and create parent folders if needed".
- `-d <dir>` tells unzip where to put the files.
- `ls` lists the folder so you can confirm the `.SC2Map` files are directly inside `Maps`. The name is **case-sensitive** on Linux: `Maps` ≠ `maps`.
- Download the current map zip from the AI Arena wiki Maps page or the active competition page in a browser, then copy it to the VM with `scp file user@vm-ip:~` from your PC. `scp` is "secure copy" over SSH.

```bash
echo 'export SC2PATH="$HOME/StarCraftII"' >> ~/.bashrc
source ~/.bashrc
```
- `export VAR=value` sets an environment variable that programs can read; python-sc2 reads `SC2PATH` to find the game.
- `echo '...' >> ~/.bashrc` appends that line to your shell start-up file so it applies in every new terminal. `>>` appends; a single `>` would overwrite the file.
- `source` re-reads the file now.

```bash
curl -sSL https://install.python-poetry.org | python3 -
poetry --version
```
- `curl` downloads the Poetry installer script. `-s` is silent, `-S` still shows errors, and `-L` follows redirects.
- `|` (a "pipe") feeds that script straight into `python3 -`, where `-` means "read the program from input". This is the install method from the ares template README.
- If `poetry` is "not found", add `export PATH="$HOME/.local/bin:$PATH"` to `~/.bashrc`. `PATH` is the list of folders the shell searches for commands.

```bash
git clone --recursive https://github.com/<you>/citadel.git
cd citadel
poetry install
poetry run python run.py
```
- Create `citadel` on GitHub from the ares starter/template with "Use this template".
- `git clone` downloads it. `--recursive` also downloads the `ares-sc2` **submodule**, a repo nested inside yours; without it you get "does not seem to be a Python package". To fix an existing clone, run `git submodule update --init --recursive`.
- `poetry install` creates a virtual environment (an isolated Python with its own packages), installs the dependencies and compiles the Cython code.
- `poetry run <cmd>` runs a command inside that environment.
- On Linux, edit `MAPS_PATH` in `run.py` if your maps live elsewhere.

**Docker for ladder-identical bot-vs-bot tests:**
```bash
sudo apt install -y docker.io docker-compose-v2
sudo usermod -aG docker $USER
newgrp docker
git clone https://github.com/aiarena/local-play-bootstrap.git
cd local-play-bootstrap
docker compose up
```
- `docker.io` is the container engine. A container is a lightweight isolated Linux environment, and AI Arena runs matches in these.
- `usermod -aG docker $USER` adds your user (`$USER`) to the `docker` group so you don't need `sudo` for every docker command. `-a` appends and `-G` names the group.
- `newgrp docker` applies the group change in the current terminal; logging out and back in also works.
- `docker compose up` reads `docker-compose.yml` and starts the match containers. The first run downloads the images.
- To test your own match, unzip your ladder zip into `bots/Citadel/`, add a line to `matches`, and read `results.json`, `replays/` and `logs/` afterwards.
- `docker compose logs` shows past output.

**Packaging the zip by hand (Linux):**
```bash
poetry run python scripts/create_ladder_zip.py
unzip -l publish/*.zip | head
```
- The first command builds the zip.
- `unzip -l` lists the zip's contents without extracting; `| head` shows only the first lines.
- Check that `run.py` appears at the top level, not under a folder. If you ever zip manually, run `cd <bot_folder> && zip -r ../Citadel.zip .`. `&&` runs the second command only if the first succeeded, `-r` recurses into subfolders, and `.` means "the contents of this folder", which keeps files at the zip root.

**Windows vs Linux notes:**
- Windows is fine for watching replays and quick graphical runs, but Battle.net installs the latest SC2, not 4.10, so behaviour can differ slightly.
- Never upload a zip built on Windows: its Cython binaries are `.pyd` files, and the ladder needs Linux `.so` files.
- Under WSL, python-sc2 launches Windows SC2 by default.
- Paths: Windows uses `C:\Program Files (x86)\StarCraft II\Maps`; Linux uses `~/StarCraftII/Maps` (case-sensitive).

## 3. Architecture

```
citadel/
  run.py / ladder.py          # template entry points (local run / ladder args)
  config.yml                  # bot name, race=Protoss, debug flags
  protoss_builds.yml          # ares build-runner openers (see §4.1)
  bot/
    main.py                   # CitadelBot(AresBot): on_start/on_step/on_end orchestration
    constants.py              # timings, thresholds (all TUNE values in one place)
    intel/
      sightings.py            # EnemyMemory: last-seen store (tags -> Sighting)
      hypotheses.py           # ThreatModel: evidence -> P(plan)
      scout_planner.py        # schedules/assigns scouting tasks
    macro/
      economy.py              # probe production, saturation, gas timing, chrono, expansions
      build_executor.py       # selects/overrides ares build runner; post-opener macro rules
      production.py           # army composition targets -> ares ProductionController
      supply.py               # pylon timing
    defense/
      defense_planner.py      # maps active threats -> DefensePlan (structures, unit holds)
      worker_defense.py       # worker-rush & cannon-rush probe pulls
      static_defense.py       # batteries/cannons placement
    army/
      squads.py               # squad roles: DEFEND, ATTACK, HARASS, SCOUT
      micro.py                # ares CombatManeuver wrappers (stalker kite, retreat)
      attack_decision.py      # when to attack/retreat (combat sim + supply gates)
    memory/
      opponent_store.py       # ./data/opponents/<OpponentId>.json read/write
    telemetry/
      logger.py               # per-game metrics -> ./data/logs (bounded) + stdout
```

**Per-step flow** (`on_step(iteration)`):
1. `intel.sightings.update()`: record every visible enemy unit and structure with a timestamp. This runs every step and is cheap.
2. Every 8 steps: `hypotheses.update()` recomputes threat probabilities, and `defense_planner.update()` emits the active `DefensePlan`.
3. `build_executor.step()`:
   - While in the opener, let the ares build runner run unless the `DefensePlan` requires an override. An override pauses the runner (`self.build_order_runner.set_build_completed()` or equivalent) and switches to the defensive macro rules.
   - After the opener, apply the macro rules.
4. `economy.step()`: probes, gas, chrono, expansions (subject to `DefensePlan.allow_expand`).
5. `production.step()`: unit mix from the matchup and intel.
6. `scout_planner.step()`: assign or advance scouting tasks.
7. `worker_defense.step()` and `army.squads.step()`: micro, with `attack_decision` evaluated every 16 steps.
8. `telemetry` records timings and, every ~30 s of game time, a snapshot.

**Order of authority when components conflict:** Defense > Economy > Scouting > Attack. The defense planner can veto expansions, pull probes and pin squads at home.

## 4. Strategy specification

All times are **game time** at "faster" speed; `self.time` in python-sc2 is in seconds. 22.4 game loops = 1 s. Supply counts are `supply_used`.

### 4.1 Openers (encode in `protoss_builds.yml`; use Chrono on Nexus probes until the Core completes)

**A. "Citadel Standard" — vs Terran and vs Random (race unknown):**
1. 14 Pylon, placed at `main_base_ramp.protoss_wall_pylon`
2. 16 Gateway at a `protoss_wall_buildings` position → send the scouting probe immediately
3. 17 Assimilator
4. 19 Nexus (~1:25–1:40)
5. 19 Cybernetics Core (second wall slot)
6. 20 Assimilator
7. 21 Pylon
8. At Core done: Warp Gate research, then 1 Stalker (vs Random) / 1 Stalker (vs T) → chrono Warp Gate
9. ~2:50 Robotics Facility → first unit Observer; Shield Battery at the natural when the Robo starts
10. ~3:30 2nd and 3rd Gateway; 3rd/4th gas at ~3:45
11. ~4:15 Forge (+1 weapons); Immortal production
12. ~4:45 3rd Nexus if `DefensePlan.allow_expand`

**B. PvZ (race known):** A up to the Core, then:
- 1 Adept (shade to scout at ~2:45), Warp Gate.
- ~2:45 Stargate → 1 Oracle (scouting/Revelation; kill drones only if no Queen or Spore is seen) → then Robo at ~4:00.
- 2 Shield Batteries at the natural by 3:30.
- 3rd Nexus ~3:50–4:15 if no early aggression is detected.

**C. PvP (race known):**
1. 14 Pylon
2. 16 Gateway (scout)
3. 17 Assimilator
4. 18 Assimilator
5. 19 Cybernetics Core
6. 21 Pylon
7. At Core done: Stalker + Warp Gate
8. 23 Nexus (~2:30–2:45)
9. ~2:50 Robotics Facility (Observer first)
10. Shield Battery at the natural when it finishes
11. 2nd Gateway ~3:10
- Never take a third before 5:00 unless the enemy has also expanded.

### 4.2 Defensive plans per detected threat (`defense_planner`)

| Threat | Trigger (see §4.4) | Plan |
|---|---|---|
| **Worker rush** | ≥ 5 enemy workers within 30 range of our main before 2:00 | Pull all probes except 2. Focus-fire the enemy worker with the lowest HP+shield. Pull a probe back to mine when its HP+shield < 15 and swap in a fresh one. Keep building probes. Continue the Gateway; the first Zealot is top priority. End the pull when enemy workers near our base are ≤ 1 |
| **Cannon rush** | Enemy Pylon/Photon Cannon/Forge-probe seen within 25 of our main or natural before 4:00 | Attack an **unfinished** Pylon with 3 probes and each unfinished Cannon with 4 probes (the proven CreepyBot pattern is 1 drone per probe and 4 per cannon). Kill the enemy probe with 1–2 probes. If a Cannon completes: don't fight it with probes; build out of its range; get Stalkers/Immortal; cancel the natural if it is covered. Cancel our own structures that are about to die |
| **12-pool / early lings** | Pool seen before the enemy natural Hatchery, or lings seen before 2:20 | Cancel or delay the natural Nexus if it is not yet started. Build Zealot/Adept from the Gateway. Hold the ramp wall with the Zealot in the gap position (`protoss_wall_warpin`/gap). Add a Shield Battery in the main. Probes defend only lings in the mineral line. Resume the Nexus after ≥ 3 units and no lings nearby |
| **Proxy Barracks/Gateway** | Enemy main shows ≤ 1 production structure at 1:45 and/or the worker count is short by ≥ 2, or a proxy structure is found | Keep the probe count up but skip the natural until 2 units are out. Add a second Gateway and a Battery in the main. Hold at the top of the ramp. Stalkers vs Reapers. Chrono the Gateway units |
| **One-base all-in** (roach/4-gate/3-rax) | No enemy natural by 2:45 (T/P) or 2:15 (Z), plus ≥ 2 gas or ≥ 3 production structures | 2–3 Batteries at the natural (or the main if it isn't taken). All Gateways producing. Delay the 3rd Nexus and Forge. Army holds at the natural choke. Immortal priority vs roaches |
| **Air threat** (Oracle/Banshee/Mutas/DTs) | Stargate/Starport with tech lab/Spire/Dark Shrine or Twilight + no army seen | 1 Photon Cannon + Battery per mineral line (build the Forge now). Observer at home vs DTs (buy a Robo if none). Stalkers/Phoenix or Archons vs mutas |
| **Macro opponent** | Natural taken on time, third base by 4:30 | Allow our 3rd Nexus on schedule; an optional 4th at ~7:00 |

### 4.3 Scouting schedule (`scout_planner`)

| Time | Unit | Task | Info targets |
|---|---|---|---|
| 0:40 (after the Gateway is placed) | Probe | Go to `enemy_start_locations[0]`, circle the main, check the natural at ~1:30, then return along the likely proxy spots (hidden corners near our natural, the map centre route) | Race (vs Random), gas count/timing, Pool/Barracks/Gateway timing, worker count, natural timing, proxy structures |
| 1:00–1:40 | 2nd probe (only if the enemy main showed < expected structures) | Patrol our main edge and natural perimeter | Cannon-rush Pylons, proxies |
| ~2:45 | Adept shade (vs Z/T) or first Stalker (vs P, poke only) | Enter the enemy natural/main | Unit counts, Roach Warren/Factory/Robo/Stargate tech |
| ~3:30 | Observer #1 | Park outside the enemy natural choke, safe from detection | Army movements, timing attacks |
| ~3:45 | Oracle (PvZ) | Fly over the main/third; cast **Revelation** on the largest unit clump if the energy cost can be paid | Tech (Lair, Roach Warren, Spire), drone count; Revelation keeps vision on units |
| 4:30 and every 60 s | Probe or Observer | Visit each unscouted enemy expansion location | Base count |
| When intel is stale (> 60 s without a view of the enemy main) and a Sentry has energy | Sentry Hallucination → Phoenix | Fly a hallucinated Phoenix over the main and natural, then away. It costs no gas or army | Tech refresh (Spire, Fusion Core, Templar Archives) |
| From 6:00 | Observer #2 | Travels with the army | Engagement intel for the combat sim |
| PvZ from 5:00 | Oracle Stasis Ward | Place 1 at our 3rd base's attack path (opportunistic) | Early warning / trap |

Every scouting unit uses ares `KeepUnitSafe`/influence-grid pathing, and retreats when its HP falls below 50%.

### 4.4 Observation → inference → response table

| # | Observation (by time) | Inference | Response (DefensePlan) |
|---|---|---|---|
| 1 | ≥ 5 enemy workers near our main before 2:00 | Worker rush | Worker-rush plan |
| 2 | Enemy probe lingering in our base after 1:15, or an enemy Pylon near our base | Cannon rush / proxy Pylon | Cannon-rush plan; kill the probe |
| 3 | Enemy Forge seen before a Gateway at 1:30 (P) | Cannon rush likely (or a Forge-first expand, if the natural exists) | Patrol probe on; save 150 minerals |
| 4 | Spawning Pool started before Hatchery; lings seen < 2:20 | 12-pool | 12-pool plan |
| 5 | No Hatchery at the Zerg natural by 1:45 and Pool done | 1-base ling/roach | One-base plan; Batteries |
| 6 | Roach Warren before 2:45, or ≥ 2 gases with no 3rd Hatchery by 3:00 | Roach/ravager all-in | One-base plan; Immortals; 2 Batteries |
| 7 | Terran main: no Barracks at 1:30, or SCV count ≤ 12 at 1:30 | Proxy Barracks | Proxy plan |
| 8 | ≥ 2 Barracks and no CC at the natural by 2:30 | 2–3 rax all-in | One-base plan |
| 9 | Factory + Starport with no expansion by 3:00 | Banshee/Cyclone/drop | Air-threat plan (Cannon + Battery, Observer) |
| 10 | Protoss main: no Gateway by 1:30, or probe count short by ≥ 2 | Proxy Gateways | Proxy plan |
| 11 | ≥ 3 Gateways and no Nexus by 3:00 (P) | 4-gate | One-base plan; Batteries at the ramp |
| 12 | Twilight Council + no expansion, or a Dark Shrine seen | DTs/Blink | Robo → Observer at home; Forge → Cannon |
| 13 | Stargate seen (P), Spire seen (Z) | Air harassment | Air-threat plan |
| 14 | Natural on time + 3rd base by 4:30 | Macro game | Normal macro; 3rd Nexus on time |
| 15 | Scouting probe killed before reaching the enemy main | Unknown; likely aggression | Assume the worst: +1 Battery, delay the 3rd; re-scout with the first Adept/Stalker |
| 16 | Enemy army value > 1.3× ours and moving toward us | Timing attack | Pull the army to the natural choke next to Batteries; keep producing; don't expand |

### 4.5 Transition to the win condition
- **Army composition** (production targets as ratios):
  - vs T: Stalker 30% / Zealot 20% / Immortal 15% / Colossus 25% / Observer 2 fixed / Sentry 1.
  - vs Z: Zealot 25% / Stalker 25% / Immortal 25% / Archon 15% / Colossus 10%.
  - vs P: Stalker 40% / Immortal 25% / Colossus 25% / Zealot 10%.
  - Air switch: if enemy air supply is ≥ 30% of their army, shift the Stalker share up and add Archons/Phoenix.
- **Upgrades:** Forge weapons first, then armour. Twilight → Charge (vs Z, T) or Blink (vs P), then Colossus range.
- **Attack gate:** supply ≥ 150 and `can_win_fight` is True against the remembered enemy army (sightings younger than 45 s), **or** supply ≥ 190.
- **Retreat gate:** the simulator flips to losing during an engagement, or the army falls below 40% of its starting value.
- **Targets:** closest known enemy expansion → next → main.
- Rally reinforcements in groups of ≥ 8 supply; never trickle them in.

## 5. Data structures

```python
from dataclasses import dataclass, field
from enum import Enum, auto

class Threat(Enum):
    WORKER_RUSH = auto(); CANNON_RUSH = auto(); POOL_12 = auto()
    PROXY = auto(); ONE_BASE_ALLIN = auto(); AIR_HARASS = auto()
    DT = auto(); TIMING_ATTACK = auto(); MACRO = auto()

@dataclass
class Sighting:
    tag: int
    type_id: "UnitTypeId"
    position: tuple[float, float]
    first_seen: float        # game seconds
    last_seen: float
    is_structure: bool
    is_snapshot: bool        # seen only as structure snapshot
    health_frac: float

@dataclass
class Hypothesis:
    threat: Threat
    score: float = 0.0       # log-odds; P = 1/(1+exp(-score))
    last_evidence: float = 0.0
    locked: bool = False     # hard triggers (e.g., enemy pylon in our main) lock True until resolved

@dataclass
class IntelState:
    enemy_race: "Race"
    sightings: dict[int, Sighting] = field(default_factory=dict)
    dead_tags: set[int] = field(default_factory=set)
    hypotheses: dict[Threat, Hypothesis] = field(default_factory=dict)
    enemy_bases_seen: dict[tuple, float] = field(default_factory=dict)   # expansion loc -> last_seen
    last_main_scout: float = 0.0
    def prob(self, t: Threat) -> float: ...
    def confidence_of(self, s: Sighting, now: float) -> float:
        # structures decay slowly (half-life 180s), units fast (half-life 20s)
        ...

@dataclass
class DefensePlan:
    active: set[Threat]
    allow_expand: bool
    batteries_needed: dict[str, int]    # "main"/"natural" -> count
    cannons_needed: dict[str, int]
    probe_pull: int                     # number of probes assigned to DEFENDING role
    army_hold_point: "Point2"
```

**Evidence rules:** each rule in §4.4 adds log-odds, e.g. +2.5 for a strong tell and +1.0 for a weak one. Scores decay by 0.05 per second without new evidence, except `locked`. A plan activates at P ≥ 0.6 and deactivates at P ≤ 0.3; this hysteresis prevents flapping. The re-scout trigger fires when the top two non-MACRO hypotheses are both between 0.35 and 0.65, or `now - last_main_scout > 60` after 3:00.

**Opponent memory:** `./data/opponents/<OpponentId>.json` holds `{games, wins, losses, last_threats_seen: [..], first_aggression_time, results_by_opener}`. Load it in `on_start` from the `--OpponentId` argument, which the template's ladder entry parses. Write it in `on_end`. If the opponent cheesed in ≥ 2 of their last 3 games, begin the game with that hypothesis pre-seeded at +1.5.

## 6. Performance

- **Budget:** mean step ≤ 15 ms, p99 ≤ 40 ms, and no step above 100 ms. The ladder's exact timeout is unconfirmed; the legacy client used roughly 40 ms per frame with a strike allowance. Log `time.perf_counter()` per step, and log a warning for any step above 30 ms.
- **Every step:** sightings update, worker-defense micro, squad micro for engaged units.
- **Every 4 steps:** production and economy.
- **Every 8 steps:** hypotheses, defense planner, scout planner.
- **Every 16 steps:** attack decision / combat sim.
- **Every 32 steps:** expansion and building-placement searches.
- Use the ares KD-tree queries (`get_units_in_range`) instead of nested distance loops. Cache pathing results for static targets. Never call `await self.client.query_pathing` in a loop.
- Keep APM moderate: don't re-issue an identical order to a unit that already has it. This avoids the known order-lag bug, seen around 120k (and sometimes 60k) APM.

## 7. Milestones (each produces a runnable bot)

| M | Days | Deliverable | Acceptance criteria |
|---|---|---|---|
| M0 | 1–2 | Environment: Ubuntu VM, SC2 4.10, maps, template bot runs; GitHub Actions builds the ladder zip; local-play-bootstrap runs the test match | `poetry run python run.py` finishes a game; the zip passes the root-layout check |
| M1 | 3–4 | Economy: Standard opener via the build runner, chrono, saturation, supply, 3-base expansion, basic Gateway army with attack-move at 170 supply | Beats Easy and Medium AI 10/10 on 3 maps; no supply block > 10 s before 6:00; 44 probes by 6:00 |
| M2 | 5–7 | Defense: worker-rush pull, cannon-rush response, 12-pool plan, ramp wall, Batteries | ≥ 8/10 vs a local worker-rush bot, a cannon-rush bot (sharpy SharpCannons) and a 12-pool bot (sharpy BluntCheese or equivalent); beats Hard AI with `AIBuild.Rush` 9/10 |
| M3 | 8–10 | Intel: sightings, hypotheses, scouting schedule (probe/Adept/Observer/Oracle/Hallucination), opener branching per race, `Tag:` chat of the detected threat | Correct threat logged in ≥ 80% of scripted-cheese test games; no scouting unit lost before 4:00 in ≥ 70% of games |
| M4 | 11–12 | Army: squads, ares combat maneuvers, combat-sim attack/retreat gates, composition targets, upgrades | Beats VeryHard AI ≥ 8/10 across all races; beats Harder with `AIBuild.Timing` and `AIBuild.Power` ≥ 7/10 |
| M5 | 13–14 | Ladder: opponent memory in `./data`, telemetry, step-time guard, upload | Runs in local-play-bootstrap vs 3 downloaded ladder bots without errors; uploaded and activated on AI Arena; first 20 ladder games show no crashes or timeouts |

## 8. Testing plan

- **Built-in AI:** difficulties Medium → Hard → Harder → VeryHard; builds `AIBuild.Rush`, `Timing`, `Power`, `Macro`, `Air`; all 3 races plus Random; at least 3 current AIE maps. Always use `realtime=False`.
- **Scripted cheese:**
  - sharpy-sc2 dummy bots: SharpCannons, BluntCheese, BluntWorkers, the proxy zealot rush, RustyMarines/OldRusty and RustyOneBaseTurtle.
  - The AI Arena "House Bots" (downloadable, originally by Infy & Merfolk).
  - The local-play-bootstrap test bots.
- **Ladder environment:** local-play-bootstrap with Citadel's actual ladder zip before every upload.
- **Metrics per game** (JSON line in `./data/logs/`, capped at the last 200 games; also stdout):
  - result, opponent id/race, map, game length, opener, threats detected (with time);
  - probes at 4:00/6:00/8:00, bases at 6:00/10:00, supply-block seconds, unspent resources at 6:00/10:00;
  - first enemy aggression time; army value lost vs killed; attack decisions and sim results;
  - mean/p99/max step ms.

## 9. Risks and known pitfalls

1. **Storing `Unit` objects across steps** causes crashes and stale positions. Store tags only (AI Arena wiki).
2. **Windows-built zips:** Cython binaries won't run on the Linux ladder. Build the zip on Linux or with GitHub Actions (ares template).
3. **Zipping the folder instead of its contents** breaks the upload (AI Arena wiki).
4. **Hard-coded balance numbers:** the AIE maps carry newer patches on the 4.10 engine. Query game data instead.
5. **Localhost connection in Docker:** honour `--LadderServer` (local-play-bootstrap).
6. **Season resets deactivate bots.** Re-activate and re-test on the new maps.
7. **APM order lag at extreme action counts.** Avoid duplicate orders.
8. **Over-pulling probes** wrecks the economy. Always release them once the threat score drops, and keep building probes.
9. **Scouting-unit deaths** starve intel. Use influence-grid pathing and retreat thresholds.
10. **Flapping between plans.** Use hysteresis and minimum plan durations (≥ 20 s).
11. **Trickling reinforcements into fights** is the classic bot loss. Group them and gate them with the simulator.
12. **Step-time spikes from pathing queries.** Throttle and cache them.

## 10. Out of scope for v1
- Machine learning, and any network calls.
- Offensive cheese builds, proxy play and Oracle/Adept harass as a win condition (Oracle is for scouting only).
- Skytoss / Carrier late game, Disruptors, High Templar storms, Warp Prism play.
- Per-opponent build selection beyond pre-seeding hypotheses (planned for v2).
- Custom speed-mining beyond what ares provides.
- Human-vs-bot realtime executables.

---

## Caveats
- The strategy timings and supply counts are standard LotV practice from domain knowledge, not re-verified against pro guides in this pass. Treat them as starting values and tune them with telemetry.
- The current map pool, the exact step-time limits, the ladder's Python version and the identities of today's top Protoss bots could not be confirmed. These are listed under Open Questions and are the first things to settle in the AI Arena Discord.
- The Blizzard Linux archive password is confirmed by the s2client-proto README, and the download URL is the one community guides use. A few python-sc2 helper names (e.g. `protoss_wall_pylon`) are from memory. Verify them against the python-sc2 source before relying on them.