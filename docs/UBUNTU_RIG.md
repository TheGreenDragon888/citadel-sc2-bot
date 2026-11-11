# The test rig on the Ubuntu boot

How to set up the desktop's Ubuntu Server install to play batches of test games while you are
away. Written for someone new to Linux: every command is followed by what each part does.

**What this gives you today:** the existing batch runner (`scripts/run_matches.py`) against the
built-in AI and the four scripted cheese bots, one game after another. **Not built yet (M8 a):**
several games at once, downloaded ladder bots as opponents, and a results file.

**Where things were checked:** the SC2 and Poetry steps are the ones this project already uses in
cloud sessions (README "Setup", `docs/M7_PLAN.md` "Step S"). The Claude Code commands are from its
documentation (setup and remote-control pages, read 2026-11-11). None of this was run on your
machine, so tell me the first error you hit.

A few terms first:
- **Terminal / shell:** the text prompt where you type commands.
- **`sudo`:** "run this as the administrator". It asks for your password. Needed to install software.
- **`apt`:** Ubuntu's software installer. It downloads programs from Ubuntu's own servers.
- **`~`:** shorthand for your home folder, `/home/<your-user>`.

## 1. Look at what you have

```bash
lsb_release -a
```
Prints the Ubuntu version. `-a` means "all fields". Note the number (22.04 or 24.04); step 2 differs.

```bash
nproc && free -h && df -h ~
```
- `nproc` prints the number of CPU threads (12 on a Ryzen 5 7600X).
- `free -h` prints memory. `-h` means human-readable units (GB instead of bytes).
- `df -h ~` prints free disk space where your home folder lives. You need about 15 GB.
- `&&` runs the next command only if the one before it succeeded.

## 2. Install the tools

```bash
sudo apt update
```
Refreshes the list of software apt knows about. It installs nothing.

```bash
sudo apt install -y git gh unzip wget curl tmux pipx build-essential
```
- `install` installs the named programs; `-y` answers "yes" to the confirmation.
- `git`: version control, to fetch and update the bot's code.
- `gh`: GitHub's tool, used once to log in so git can read your private repository.
- `unzip`, `wget`, `curl`: unpack and download files.
- `tmux`: keeps programs running after you disconnect (step 7).
- `pipx`: installs Python tools, each in its own box so they can't break one another.
- `build-essential`: a compiler, which some Python packages need while installing.

**Python 3.12** (the ladder's version; the bot must be tested on the same one):

```bash
python3.12 --version
```
If that prints `Python 3.12.x`, install its two add-ons and skip to Poetry:

```bash
sudo apt install -y python3.12-venv python3.12-dev
```
- `python3.12-venv` lets Python make isolated environments; `python3.12-dev` has files compilers need.

If `python3.12` is "not found" (Ubuntu 22.04), add the standard source for newer Pythons first:

```bash
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3.12-dev
```
- `add-apt-repository` adds another software source. `ppa:deadsnakes/ppa` is the widely used one
  for Python versions Ubuntu doesn't ship.

**Poetry** (installs the bot's exact Python packages):

```bash
pipx install poetry
pipx ensurepath
```
- `pipx install poetry` installs Poetry for your user.
- `pipx ensurepath` adds its folder to your `PATH`, the list of folders the shell searches for
  commands. Log out and back in (or run `exec bash`) so the change takes effect.

## 3. Get the code

```bash
gh auth login
```
Logs this machine in to GitHub. Choose "GitHub.com", "HTTPS", and "Login with a web browser". It
prints a short code and a web address; open the address on your phone or another computer and
type the code. No browser is needed on the server.

```bash
cd ~ && git clone --recursive https://github.com/TheGreenDragon888/citadel-sc2-bot.git
```
- `cd ~` moves to your home folder.
- `git clone` downloads the repository into a new folder `citadel-sc2-bot`.
- `--recursive` also downloads the ares-sc2 framework, which lives inside it as a "submodule".

```bash
cd ~/citadel-sc2-bot
poetry env use python3.12
poetry install
poetry run python --version
```
- `poetry env use python3.12` tells Poetry to build the environment on Python 3.12.
- `poetry install` downloads the packages listed in `poetry.lock` (the exact tested versions).
  A few minutes.
- `poetry run <command>` runs a command inside that environment. The last line must print 3.12.

## 4. Install StarCraft II (headless Linux build 4.10)

```bash
cd ~
wget http://blzdistsc2-a.akamaihd.net/Linux/SC2.4.10.zip
unzip -P iagreetotheeula SC2.4.10.zip
rm SC2.4.10.zip
cp ~/citadel-sc2-bot/maps/*.SC2Map ~/StarCraftII/Maps/
ln -s Maps ~/StarCraftII/maps
```
- `wget <address>` downloads Blizzard's Linux package (about 4 GB).
- `unzip -P iagreetotheeula` unpacks it; `-P` gives the password, which stands for accepting
  Blizzard's AI and Machine Learning Licence. The result is `~/StarCraftII`.
- `rm` deletes the zip to free 4 GB.
- `cp ... *.SC2Map ...` copies the 7 ladder maps into the game's map folder. `*` matches any name.
- `ln -s Maps ~/StarCraftII/maps` makes a link named `maps` pointing at `Maps`. Linux file names
  are case-sensitive and this game version looks for the lowercase name.

This build draws nothing on screen and does not use the graphics card.

## 5. Check that it works

```bash
cd ~/citadel-sc2-bot
poetry run python scripts/test_ares_bridge.py
```
A test that needs no game. The last line should be `PASS: 0 failed`.

```bash
poetry run python scripts/run_matches.py --difficulty Hard --race Terran --map PylonAIE_v4 --total 1
```
One real game against the built-in AI. It prints a `ROW` line with the result when it ends
(a few minutes). If it fails, send me the last 20 lines.

## 6. Keep the code current

```bash
cd ~/citadel-sc2-bot && git pull && git submodule update --init && poetry install
```
- `git pull` fetches the newest commits of the branch you are on.
- `git submodule update --init` moves ares-sc2 to the version the bot expects.
- `poetry install` installs anything that changed.

To test a work branch instead of `main`: `git fetch origin <branch> && git switch <branch>`.

## 7. Run a batch that survives you leaving

```bash
tmux new -s rig
```
Starts a `tmux` session named `rig`. Anything started inside keeps running if you close the
terminal or your connection drops.

```bash
cd ~/citadel-sc2-bot
poetry run python scripts/run_matches.py --difficulty VeryHard --race Terran Zerg Protoss --map all --total 30 --game-seed 9000 2>&1 | tee data/rig-$(date +%F).log
```
- `--game-seed 9000` fixes the randomness, so the same 30 games can be replayed on a later version.
- `2>&1` sends error messages to the same place as normal output.
- `| tee <file>` shows the output and also saves it to a file. `$(date +%F)` becomes today's date.
  `data/` is ignored by git, so the log stays local.

Leave it running: press `Ctrl+b`, let go, then press `d` ("detach"). Come back later with:

```bash
tmux attach -t rig
```

Count the results so far from any terminal:

```bash
grep -c "^ROW" ~/citadel-sc2-bot/data/rig-*.log
```
`grep -c` counts the lines that match; `^ROW` means "lines starting with ROW".

## 8. Docker (only needed for ladder bots as opponents, M8 a)

```bash
sudo apt install -y docker.io
sudo usermod -aG docker $USER
```
- `docker.io` is Docker, which runs AI Arena's own match containers.
- `usermod -aG docker $USER` adds you to the `docker` group so you can use it without `sudo`.
  Log out and back in afterwards.

## 9. Claude Code on this machine: worth it, for two things

1. **Fixing the rig in place.** When a step above fails, a session on the machine can read the
   error and the files directly, instead of you copying text into a cloud session.
2. **Running and reading batches from your phone.** With Remote Control you start a session at
   home and steer it from the Claude app between classes: "start tonight's batch", "how did the
   last 50 games go?".

It is **not** worth using for unattended code changes yet. That waits for M14, after the rig can
judge a change by itself.

```bash
curl -fsSL https://claude.ai/install.sh | bash
```
- `curl -fsSL <address>` downloads the installer script (`-f` fail on errors, `-s` quiet, `-S` still
  show errors, `-L` follow redirects); `| bash` runs it. Open a new terminal afterwards.

```bash
claude --version
```
Prints a version number if the install worked.

```bash
cd ~/citadel-sc2-bot
tmux new -s claude
claude --remote-control "Citadel rig"
```
- The first start asks you to log in with your claude.ai account (it shows a link and a code,
  like `gh` did). Remote Control needs a claude.ai subscription login, not an API key.
- `--remote-control "Citadel rig"` makes the session appear under that name at claude.ai/code and
  in the Claude phone app.
- Detach with `Ctrl+b` then `d`; the session keeps running. It makes outgoing connections only,
  so nothing on your network needs opening.

It uses the same usage allowance as your other Claude sessions.

## 10. The local model (Ollama, qwen3.5:9b)

You are right that the games would not get in its way: this SC2 build runs on the CPU only, so
the graphics card is free. My assessment, by size class (I have not tested that model):

| Possible use | Verdict |
|---|---|
| Inside the bot on the ladder | Not possible. The ladder has no graphics card, no Ollama, and a 50 MB zip limit |
| Writing or changing bot code unattended | No. This codebase depends on exact ares and python-sc2 details; a 9-billion-parameter model will get those wrong often, and nothing would catch it before the games do |
| Summarising batch results | Not needed. The results are numbers; a script counts them exactly |
| Reading one long game log and describing what happened in plain words | Possible, low value. Worth trying only if you find yourself reading logs by hand |

So: leave it installed, don't build anything around it now. The graphics card's real job comes in
M14, if training a fight-outcome model turns out to be worth doing.
