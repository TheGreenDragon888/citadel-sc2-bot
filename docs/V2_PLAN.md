# V2 plan: from rank 48 to the top 10

**Status: DRAFT IN PROGRESS (2026-11-11).** Parts 1 and 2 are complete and verified. Parts 3-8 are
partly written; items marked PENDING are still being checked. Nothing in the bot has been changed.

**What this file is.** An audit and a plan, asked for by the user on 2026-11-10. No bot code
changes, no uploads. Every claim is labelled **Verified** (evidence given), **Likely** or
**Uncertain**, as in `docs/DESIGN.md`.

**Where the evidence comes from.**
- AI Arena API (read-only, `UPLOAD_API_TOKEN` / `UPLOAD_BOT_ID`), fetched 2026-11-11 00:40 UTC:
  all 702 of Citadel's match records, the Season 2 standings (186 entries, 165 active), and
  Citadel's own log for 700 matches.
- 367 games played by the current zip (md5 `650fd9ec`, uploaded 2026-10-16) that have a full
  `METRIC game` record (version 7): 190 wins, 177 losses. All counts in Part 2 are over these.
- The code at `84d6f88`, ares-sc2 v3.13.1 (`8730865`), python-sc2 (burnysc2 7.1.0) from the
  Poetry environment on Python 3.12.
- **SC2 is not installed in this session** (`~/StarCraftII` does not exist, `SC2PATH` unset), so
  no games were run. Checks that need games are listed in Part 7 as acceptance tests.

---

## Part 1. Standing

| | Value | Label |
|---|---|---|
| Competition | Sc2 AI Arena 2026 Season 2 (opened 2026-10-26), 165 active bots, 7 divisions of ~23 | Verified (API `competitions/38`) |
| Citadel | **Elo 1654, rank 48 of 165, division 3** | Verified (API `competition-participations`) |
| 10th place | **Elo 1791** (JimmyBotP). Gap: **137 Elo** | Verified |
| 5th / 1st | 1870 (Zozo) / 2190 (Atlas) | Verified |
| 20th place | 1744 | Verified |
| Division 1 (ranks 1-23 roughly) | Elo 1723-2190 | Verified |

- **What 137 Elo means.** Against the same opponents, +137 Elo is an expected score of about 69%
  instead of 50% (logistic Elo formula). Citadel's current zip scores 51% (190-178-2 over 370
  games). So the target is roughly "win 2 of every 3 games against today's opponents", and then
  hold about 50% against division 1. **Likely** (formula is exact; the ladder's pairing by
  division makes the real path stepwise).
- **Citadel has almost no games against the top 25**: 3 games, 3 losses (JRT twice at 5:42 and
  6:12, AutoClicker at 4:58), all rushes. **Verified.** Its results come from divisions 2-5.
- **Top 10 by Elo:** Atlas (Z, C++) 2190, Eris (Z, Python) 2009, Phobos (T, Python) 1998, Deimos
  (P, Python) 1958, Zozo (P, Python) 1870, Horizon (T, Python) 1862, Xena (Random, C++) 1830,
  ArgoBot (P, .NET) 1827, SharpenedEdge (P, C++) 1801, JimmyBotP (P, Python) 1791. **Verified.**
  Six of the ten are Python bots, so the language is not the limit.

## Part 2. Loss diagnosis

### 2.1 The three impressions, checked

| Impression | Verdict | Evidence (367 games, current zip) |
|---|---|---|
| "Falls quickly to harassment" | **Confirmed, and it is bigger than harassment.** Citadel loses its mineral lines at home | 11,542 mining probes lost in 177 losses (median 62 per loss) against 1,383 in 190 wins (median 1). When harass air units (Oracle, Banshee, Void Ray, Phoenix, Liberator, Mutalisk) kill 5 or more mining probes, the record is **9-50**; when Oracles do, **2-26** |
| "Gets out-strategized" | **Confirmed, but the main cause is self-inflicted.** Citadel's own threat flags put it on one base against opponents who are not rushing | One base at 5:00: **37-90 (29%)**. Two bases: 125-78 (62%). Three: 28-6 (82%). See 2.3 |
| "Gets out-micro'd" | **Partly.** Micro in open fights is not where most games are lost; the attack decision is | Only 33 of 177 losses (19%) came after Citadel attacked at all. But of 302 launch→retreat pairs, 264 (87%) retreated after meeting more than double the enemy value seen at launch (median seen at launch: 100; at retreat: 3,725; median 31 s later). See 2.4 |

All **Verified** from the game records and log lines (`METRIC game`, `METRIC snap`, `PROBE lost`,
`ENGAGE`, `DEFEND`).

### 2.2 Every loss sorted by cause

Rules, applied in order: (1) game shorter than 7:00; (2) at least 60% of the first 20 mining
probes lost were killed by harass air units, before any launch; (3) no attack ever launched;
(4) launched, army value lost / killed above 1.3; (5) the rest.

| # | Cause | Losses | Share | Races (P/T/Z) | Median length | Who does it |
|---|---|---|---|---|---|---|
| 3 | **Ground attack at home; Citadel never launched** | 105 | 59% | 40/48/17 | 11.4 min | Voltron 10, sludgement2-revived 9, norman 7, PiG_Bot 6, Reynard 6 |
| 2 | **Air harassment emptied the mineral line first** | 31 | 18% | 28/2/0 (+1 R) | 11.1 min | Thssprtssbt 12, VoidCrush 7, Thssprtssbt2 5 |
| 5 | Attacked, traded evenly or better, still lost | 19 | 11% | 4/8/7 | 18.3 min | ANI_dev 4, Top_Forty 4, Snow 3 |
| 4 | Attacked and traded badly | 14 | 8% | 7/5/2 | 16.4 min | spread |
| 1 | Rush or cheese, dead before 7:00 | 8 | 5% | 5/3/0 | 5.9 min | sitri 3, JRT 2 |

- **81% of losses end without Citadel ever attacking** (wins: 1%). **Verified.**
- In cause 3 the first 20 mining probes are killed by Marines (373), Stalkers (311), Zealots
  (206), Zerglings (161), Roaches (106), Marauders (96), Reapers (84). The 10th mining probe dies
  before 6:00 in 17 games, 6:00-8:00 in 33, 8:00-10:00 in 41, later in 13. **Verified.**
- In cause 2 the killers are Oracles (372 of the first 620) and Void Rays (116). Median army at
  home at 5:00 was 21 supply, mostly units that cannot shoot up. **Verified.**
- **Losses are concentrated on a few opponents that beat Citadel the same way every time:**
  Voltron 0-13, PiG_Bot 0-6, sitri 0-4, Thssprtssbt 2-13, VoidCrush 1-7, Thssprtssbt2 1-5,
  Mulebot 1-5, Reynard 2-6, 27turtles 1-4. That is 9 opponents and 63 of the 177 losses.
  **Verified.**
- **Game length.** Games that end before 10:00: 3 wins, 52 losses. Citadel never wins early.
  **Verified** (all 370 games).

### 2.3 Self-inflicted: false alarms that cost the second base

| Finding | Evidence | Label |
|---|---|---|
| A normal Terran Reaper opening raises the PROXY flag | `bot/intel/ares_bridge.py:67`: `Bridge("get_enemy_went_reaper", (Threat.PROXY,), ...)` | Verified |
| Opponent memory then pre-raises PROXY at 0:00 in every later game against that opponent, which ends the opener | `bot/main.py:147`; `MEMORY_KEEPS_OPENER = ("POOL_12",)` at `bot/constants.py:875` | Verified |
| Result vs Terran: PROXY pre-raised **11-38 (22%)**; not pre-raised **54-28 (66%)** | game records | Verified |
| In those 49 pre-raised Terran games a proxy structure was actually seen in **4**; the Reaper flag fired in 39 | game records | Verified |
| Every one of the 49 was on one base at 5:00 (not pre-raised: 76 of 82 on two). Median probes at 6:00: 38 against 57 | `METRIC snap` | Verified |
| Voltron (0-13) had PROXY pre-raised in 10 games | game records | Verified |
| An enemy scouting probe raises CANNON_RUSH (`cannon_probe`) in 119 of 367 games; a Cannon was actually seen in 12 | game records; `bot/intel/detectors.py:11` | Verified |
| Opener `C_2GateRobo` vs Protoss: **19-46 (29%)**; `C2_1GateExpand`: 73-38 (66%). `C_2GateRobo` was on one base at 5:00 in 37 of 65 games | game records | Verified |
| That the pre-raise *causes* the losses (rather than marking strong opponents) | the same opponents are beaten when it is not raised only in a few games; needs an A/B with games | Likely |

**Estimated size:** if the 49 pre-raised Terran games had gone at the 66% of the others, that is
about 21 more wins in 370 games, roughly +40 Elo from one bridge line and one memory rule.
**Likely** (assumes the opponents are comparable).

### 2.4 The attack decision

- 578 launches in 367 games; 239 (41%) retreat within 60 s, 148 within 30 s. **Verified.**
- The launch reads only what is near the squad or the target (`docs/STATUS.md` "Launch inputs are
  local"; M7's launch gate C4 was removed in D38). The numbers above are the cost. **Verified.**
- **Counterattacks (§4.6) do nothing:** 417 launched, 347 ended within 10 s, 12 killed anything,
  51 workers killed in total over 367 games. **Verified.**
- Units lost while on HOLD intent: median 7 per loss, 0 per win. **Verified.**

### 2.5 Other measured facts

- No crash in the current zip's 370 games; one time-out (the Voltron match, see the postmortem).
  No guarded errors in any game record. **Verified.**
- Step time: median of game means 6.3 ms; 18 games had a step of 300 ms or more, one of 2,500 ms;
  the step guard came on in 25 games. **Verified.**
- Storms were cast in 43 of 58 games vs Zerg. **Verified.**

---

## Part 3. Defense review

PENDING (module audit running). Confirmed so far:
- **Probes never flee.** No code in `bot/defense/`, `bot/macro/` or `bot/main.py` moves mining
  probes away from an attacker (grep for flee / evacuate / safe: no match). **Verified.**
- **Nothing answers an Oracle in time.** 197 games have a `DEFEND ... hold, nothing can hit it`
  line; their record is 28-169. **Verified.**

## Part 4. Capability gaps

PENDING (module audit running).

## Part 5. Code audit

- `bot/constants.py`: 385 module-level names, **none unused**. 13 are used only to build other
  constants; 5 (`M1_PROBES_AT_6_MIN`, `M3_EXPECTED_FLAGS`, `M3_ALWAYS_ALLOWED`, `M3_FLAG_RATE`,
  `M3_SCOUT_SAFE_RATE`) are read only by `scripts/`, so they are test settings living in the bot's
  file. **Verified** (name search over `bot/`, `scripts/`, `run.py`, `ladder.py`).
- Module-by-module findings: PENDING.

## Part 6. Unattended improvement on the desktop

### 6.1 Recommendation

**Use the Ubuntu boot first as a test rig, second as a tuner, and not for a model in the bot yet.**

| Option | Expected ladder gain | Risk | Effort | Verdict |
|---|---|---|---|---|
| **Test rig**: replay every code change against the real ladder bots that beat Citadel | High. It makes M8-M12 measurable; today no local opponent attacks the way ladder bots do | Low | Medium (one-time setup) | **Do first (part of M8)** |
| **A. Auto-tune the TUNE values** | Medium, later. Part 2 shows the losses come from missing behaviours and wrong rules, which numbers cannot fix | Medium: tuning to a small opponent pool can lower ladder results | Medium | **After M10**, on small groups of related constants |
| **C. Unattended Claude Code session** | High while the work is rule fixes with a clear test | Medium: it needs strict permissions and a branch of its own; it uses your plan's usage window | Medium | **Try in M14**, restricted (6.5) |
| **B. A trained model inside the bot** | Unknown. No public write-up of a top ladder bot using one was found | High: new dependency in the zip, hard to debug, needs thousands of labelled fights | High | **Not now.** Revisit after M12 for one narrow use: predicting fight outcome from the fight telemetry |

### 6.2 What the ladder allows

| Fact | Label |
|---|---|
| Bot image is Python 3.12, **CPU only** (CPU builds of torch and tensorflow); no GPU is documented | Verified (aiarena-docker `Dockerfile.bot`, `pyproject.toml`) |
| Packages listed in the image's lock file on master: numpy, scipy, scikit-learn, pandas, torch (CPU), tensorflow-cpu. onnxruntime is not listed. The image the live ladder runs may be older (`docs/VERIFY_NOTES.md:1408-1414` found other versions in v0.8.0) | Verified for master; live tag Uncertain |
| Zip limit 50 MB (Citadel's is 5.5 MB) | Verified (AI Arena wiki, Getting Started) |
| Network access is forbidden apart from the local game connection; `./data` persists between games | Verified (wiki) |
| The controller enforces a 30 s per-request timeout; the 40 ms frame time in the sample config is not enforced | Verified (`docs/VERIFY_NOTES.md:1422-1436`, controller source) |
| Cores and RAM per bot | Not found |

So the RTX 4070 SUPER can only help **offline** (training). Anything the bot runs on the ladder
runs on a CPU inside the step budget.

### 6.3 What the games are played against, and why it should carry over

- **9 of the 165 active ladder bots have a publicly downloadable zip. Four of them are among the
  opponents Citadel loses to most:** Thssprtssbt (P, Oracle harassment, Citadel 2-13),
  Mulebot (T, 1-5), norman (P, 4-7), sludgement2-revived (Z, 4-9). Also who (rank 11, Random),
  Creepy_strategies (rank 25, P), mini-puck, CryptBotRevival, monsterbot. **Verified** (API
  `bots/<id>/`, field `bot_zip_publicly_downloadable`).
- These are the real programs, so a fix that beats them locally should beat them on the ladder.
  That is the reason to expect carry-over. **Likely.**
- Citadel's own test bots (`scripts/test_bots/`) cover four cheeses; none harasses. The built-in
  AI stays as the regression check, not as the target.
- `scripts/ladder_env_test.py` already runs the official AI Arena images locally. It is the
  natural way to run downloaded zips, since they expect the ladder's layout. Whether it can run
  several matches at once is PENDING (scripts audit).
- **Guard against tuning to the pool:** tune on one set of games, accept a change only on a
  separate set, and confirm on the ladder before keeping it.

### 6.4 How many games, and what that buys

- **Throughput is not measured yet.** No published figure was found. `docs/STATUS.md` reports
  about 40 games in 40-70 minutes on a 4-core cloud machine against the built-in AI. On 6 cores
  and 12 threads, 5 or 6 games at once is a fair first guess, so about **600-900 games per
  20-hour day**. **Uncertain** until M8 measures it.
- **What a day can detect** (95% confidence, 80% power, comparing two versions):

| True improvement | Games needed (both versions together) | Days at ~750 games |
|---|---|---|
| 50% → 70% (about +147 Elo) | 186 | under 1 |
| 50% → 60% (+70 Elo) | 776 | 1 |
| 50% → 55% (+35 Elo) | 3,130 | 4 |
| +10 Elo | about 19,000 | 25 |

- So the rig can confirm a real fix overnight, and cannot see small tweaks. Tuning 385 constants
  at once would chase noise. The method that fits is **SPSA** (two evaluations per step whatever
  the number of parameters) on groups of 5-20 related constants, then a separate acceptance run.
  **Likely** (chessprogramming.org SPSA; fishtest wiki warns that tuning many values together
  drifts at random).

### 6.5 An unattended Claude Code session

From the Claude Code docs (headless, permission-modes, sandboxing, remote-control pages, read
2026-11-11). **Verified** as what the docs say; the combination is this plan's reading.
- `claude -p "<task>"` runs without a terminal. `--permission-mode dontAsk` is the mode the docs
  call "designed for unattended use": anything not pre-approved is denied instead of asked.
- A short allow-list (run the match scripts, edit files under `bot/` and `scripts/`, commit to
  one branch) keeps it from doing anything else. `--max-budget-usd` caps spend.
- Remote Control lets you watch from your phone. It needs your claude.ai login on the machine.
- It never uploads to the ladder and never touches `main`; you review the branch after class.

### 6.6 How results get back into the repo

Each run writes a results file under `data/tuning/<date>/` (ignored by git) and a summary under
`docs/tuning/`. The summary is committed and pushed to a branch named `tuning/<date>`. A cloud
session, or you, reads that branch. Nothing merges by itself.

### 6.7 Setup on the Ubuntu boot

PENDING: written out command by command, with what each part does, once D5 and D6 (Part 8) are
decided, because the steps differ if Claude Code is installed there. The outline:
1. Install git, Python 3.12, Poetry and Docker.
2. Clone the repo with its submodule; `poetry install`.
3. Download headless SC2 4.10 and copy the maps (the commands are already in
   `docs/M7_PLAN.md` "Step S").
4. Run one offline test and one game as a smoke check.
5. Start a batch inside `tmux`, so it keeps running after you disconnect.

## Part 7. Roadmap (draft order, by losses each should remove)

| M | Deliverable | Losses it targets |
|---|---|---|
| M8 | **Stop the false alarms.** Reaper ≠ PROXY; a scouting probe ≠ CANNON_RUSH; memory pre-raises only on confirmed structures; retire or fix `C_2GateRobo` | up to ~38 of 177 (2.3) |
| M9 | **Hold the mineral lines.** Probes flee and return; anti-air at each mineral line on the first air-tech sighting; a standing home-defense group that can shoot up | 31 (cause 2) plus part of cause 3 |
| M10 | **Survive the 6:00-10:00 attack.** Army size and static defense by time, driven by what the scouts see; fight at the right place with Batteries | 105 (cause 3) |
| M11 | **Independent groups.** Home guard, main army, scouts, raiders, each with its own decision | causes 2, 3, 5 |
| M12 | **Attack decision on whole-army intel**; replace or remove the counterattack | 33 (causes 4, 5); 239 wasted launches |
| M13 | **Code cleanup** from Part 5 | none directly |
| M14 | **Tuning rig on the Ubuntu boot** | Elo from numbers, after the rules are right |

Acceptance criteria per milestone: PENDING.

## Part 8. Decisions needed

PENDING.
