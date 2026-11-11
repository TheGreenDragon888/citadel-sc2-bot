# V2 plan: from rank 48 to the top 10

**Status: complete, waiting on the decisions in Part 8 (2026-11-11).** One item is still open:
the command-by-command Ubuntu setup (6.7), which depends on D5 and D6. Nothing in the bot has
been changed.

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

Labels in Parts 3-5: **Verified** means I re-read the cited lines myself after the helper audit
reported them. **Reported** means a helper audit quoted the lines and I have not re-read them
(the full reports, with quotes, are in `docs/v2_evidence/helper_reports/`). Nothing
here was observed in a game.

### 3.1 What the bot plans for

| Threat | Plan | Label |
|---|---|---|
| Worker rush, cannon rush, 12-pool, proxy, one-base all-in, air harass, unknown aggression | Yes (`bot/defense/defense_planner.py`, one `_plan_*` each) | Reported |
| Dark Templar, cloaked Banshee, burrow | **Barely.** `Threat.DT` is never raised anywhere in `bot/`. The only answer is one home Observer, vs Protoss only, once a Twilight Council is seen (`scout_planner.py:419-425`) | Verified (no `Threat.DT` use outside the enum) |
| Two-base timing attack | **None.** `Threat.TIMING_ATTACK` and `Threat.MACRO` are never raised; spec §4.4 rows 12, 14, 16 have no code | Verified |
| Runbys (Hellion, Adept, Zergling) after 4:00 | **None.** Probes fight Zerglings only while POOL_12 is active (`worker_defense.py:83`), and that flag expires at 4:00 | Verified (line 83); expiry Reported |
| Drops (Medivac, Warp Prism, Overlord), Widow Mines, Nydus, Swarm Hosts, Disruptors | **None** | Reported |
| Zerg one-base Roach all-in | Late: no Zerg structure is in the production list, so it is caught when Roaches appear, about 3:30-4:30 | Reported |

### 3.2 What costs more than it saves

| Finding | Evidence | Label |
|---|---|---|
| A Reaper seen anywhere raises PROXY and ends the opener | `ares_bridge.py:67`; the first raise needs only the ares boolean, the "units near home" test applies only to later confirms (`ares_bridge.py:104-126`) | Verified. Cost measured in 2.3 |
| Memory pre-raise of PROXY ends the opener at 0:00 | `bot/main.py:147` | Verified. Cost measured in 2.3 |
| A lingering enemy probe raises CANNON_RUSH | `detectors.py:11` | Verified. In 119 games; a Cannon followed in 12 |
| One visible Zergling before 2:20 raises POOL_12 and ends the opener | `detectors.py:485-492` | Reported |
| AIR_HARASS (any Stargate, Spire or Starport tech lab) builds Forge, Pylon, Cannon and Battery at every mineral line, about 350 minerals per base | `static_defense.py` | Reported. Note the opposite failure in cause 2: against Oracles this arrives too late |
| Fogged enemy Cannons are ignored by the planner: `completed_enemy_cannons()` requires `is_powered`, which is False in the fog | `defense_planner.py:331-335` | Verified (the line); fog behaviour per `VERIFY_NOTES.md:1025` |

### 3.3 Where it is thin

- **Probes never flee.** Nothing moves mining probes away from an attacker. **Verified** (no such
  code in `bot/defense/`, `bot/macro/`, `bot/main.py`; the defense audit found the same).
- **Nothing answers an Oracle in time.** 197 games have a `DEFEND ... hold, nothing can hit it`
  line; their record is 28-169. **Verified** (logs).
- **Static defense:** one Battery at the main ramp under 12-pool or proxy, up to 3 at the natural
  for a one-base all-in, Cannons only through AIR_HARASS. No Cannon or Battery by time alone.
  **Reported.**
- **Enemy tech is seen 2-3 minutes late.** The main re-scout is one point at the enemy Nexus
  (`scout_planner.py:509`) and counts as done once that point is visible, so buildings at the
  edge of the main are missed. After 5:00 the enemy main is re-seen every 100-150 s at best.
  **Reported.**
- **No standing map vision:** no Pylon, probe or Observer on attack paths or at expansions, and no
  record of where the enemy army is unless something sees it right now. **Reported.**

## Part 4. Capability gaps

### 4.1 Army separation

| Fact | Evidence | Label |
|---|---|---|
| Roles exist (DEFEND, ATTACK, REINFORCE, HARASS, SCOUT), but at launch **every** home fighter joins ATTACK | `army.py:300-303` | Verified |
| So during an attack the home guard is only what was built since the launch | follows from the line above | Verified |
| The army comes home, all of it, only if enemies at home are worth 30% of the attack squad | `army.py:272-283`, `ARMY_RECALL_FRACTION` | Verified |
| Only one home threat is handled at a time: the enemy nearest any base. A second prong is ignored | `army.py:556-565` | Verified |
| Any visible enemy unit within 22 of a base blocks both the launch and new reinforcements; Warp Prisms, Medivacs and Ravens are not on the harmless list | `army.py:290`, `:363` | Reported |
| HARASS exists only as the §4.6 counterattack, and never runs during an attack | `counterattack.py` | Reported; 2.4 shows it achieves nothing |

**What is needed** (the three jobs from the request):
- **(a) A standing home guard** sized by what the scouts have seen (air or ground, how many),
  that stays home at launch, answers each base separately, and includes units that can shoot up.
- **(b) Map vision:** Observers and cheap Pylons or probes on the attack paths and at free
  expansions, plus a remembered enemy-army position that the launch and recall rules read.
- **(c) Raiders:** small groups (Adepts, Oracles, Dark Templar, a Warp Prism) with their own
  target choice and their own retreat rule, running while the main army does something else.
  This needs the spec's cut list changed (Part 8, D2).

### 4.2 Micro

| Exists | Label |
|---|---|
| Lowest-HP target choice, units that fight back first; kiting through ares's `KeepUnitSafe` (Stalker, Adept, Immortal, Colossus, Sentry, Phoenix, Void Ray, Oracle, Tempest) | Reported |
| Blink: back on low shields, in as a group, finishing a kill, away on retreat | Reported |
| Storm at 4+ targets, Templar stay behind and merge to Archons; Void Ray and Tempest target preferences | Reported |

| Absent | Why it matters |
|---|---|
| **Shoot-then-step kiting.** `micro.py:4-5` says it uses ares's `StutterUnitBack`; the code uses `KeepUnitSafe` (`micro.py:250`), which only steps out of danger and has no weapon-cooldown timing | Stalkers lose damage every cycle against Marines, Zerglings, Zealots |
| Target priority beyond lowest HP (Siege Tanks, Medivacs, Banelings, casters, detectors) | fights vs Terran bio and tank lines (causes 3, 5) |
| Guardian Shield, Force Field (the Sentry share is 1%, so no Sentry is built) | holding a ramp at 5:00-9:00 (cause 3) |
| Splitting against splash; dodging Storms, Biles, Disruptor shots, Widow Mines, Liberator zones | probes and army both |
| Control for Phoenix, Oracle, Disruptor, Dark Templar, Warp Prism | needed for 4.1 (c) |
| Fighting next to Shield Batteries and Cannons on purpose | cause 3 |

The simulator's blind spots also matter: it ignores spells, and enemy memory lasts 30 s
(`engagement.py:182-215` reads only enemies within 20 of the squad or the target). **Reported.**

## Part 5. Code audit

**Summary.** No invented API was found. Every ares and python-sc2 name the bot uses exists with
a matching signature in the sources actually installed, and every option in `protoss_builds.yml`
and `config.yml` is one ares parses (**Reported** by all four module audits). All 7 offline test
scripts pass (16/16, 36/36, 14/14, 234/234, 31/31, 38/38, 7/7; **Reported**, outputs saved). What
the audit did find is wrong assumptions, rules that fire on too little evidence, and some dead
weight. The risk in this codebase is behaviour, not hallucinated calls.

### 5.1 Bugs and wrong assumptions

| ID | File:line | What is wrong | Proposed fix | Label |
|---|---|---|---|---|
| INT-4 | `bot/intel/ares_bridge.py:104-126` | A unit-based ares flag raises its threat on the boolean alone, with no matching unit near home | Require evidence near our bases for the first raise | Verified |
| DEF-2 | `ares_bridge.py:67` | Reaper seen → PROXY | Remove the bridge, or map it to a harassment note | Verified |
| DEF-3 | `bot/defense/defense_planner.py:331-335` | `is_powered` drops Cannons in the fog | Drop the test, as `engagement.py` already did | Verified |
| ARMY-1 | `bot/army/army.py:272-283, 300-303` | No home guard during an attack; all-or-nothing recall | M11 | Verified |
| ARMY-2 | `army.py:556-565` | One home threat at a time | M11 | Verified |
| MAC-1 | `bot/main.py:165, 267` | Step time covers `on_step` only; ares's after-step (mining, production, warp-ins) is not timed, so the step guard never sees it | Time the after-step too | Verified (the timing lines); what runs in after-step Reported |
| INT-6 | `bot/intel/enemy_mix.py:145` | `calculate_supply_cost` returns the morph difference, so a Baneling counts 0 and a Brood Lord 2; this skews the air share | Read supply from game data per unit type | Verified (the call); library behaviour Reported |
| INT-3 | `bot/intel/scout_planner.py:509` | Main re-scout is one point | Lap points around the main | Reported |
| ARMY-3/4 | `army.py:290, 363, 517-530` | Harmless flyers and unshootable structures can block launches | Extend the harmless list; skip targets nothing can hit | Reported |
| MAC-2 | `bot/error_guard.py` | A part that fails every step leaves 3 tracebacks, then one line a minute; nothing reacts. Seven different calls share the part name "unit destroyed" | Separate names; fail loudly in local runs | Reported. Note: 0 guarded errors in 367 ladder games |
| MAC-3 | `bot/main.py` `on_start` | Component construction is unguarded; an exception there forfeits the game | Guard it | Reported |
| MAC-4/5 | ares DataManager; `bot/main.py:147` | Opener win rates start with a fake win, and a game whose opener was ended at 0:00 is still booked under that opener | Do not book pre-raised games; see D4 | Reported. Consistent with `C_2GateRobo` staying in use at 29% |
| MAC-6 | `bot/macro/build_executor.py` | `finished` can never become true if one conditional item never fires; gas stays at 4 and the 4th base never unlocks | Add a time fallback | Reported |
| SCR-1/2 | `scripts/create_ladder_zip.py:41-52` | A zip built on Windows would carry `.pyd` files the Linux ladder cannot load; only the Python version is checked | Refuse to build off Linux | Reported |
| MAC-9 | `ladder.py:84` | Arguments to `_play_game` in the wrong positions (both None today) | Fix the call | Reported, not re-checked |

### 5.2 Dead or stale

| What | Evidence | Proposed | Label |
|---|---|---|---|
| `Threat.DT`, `TIMING_ATTACK`, `MACRO` and their TTL entry | never raised | Build in M10 or delete | Verified |
| `Decision.flipped`, `NO_DEFENDER`, `DefensePlan.cannons_needed`, unused `blink_ready` import in `micro.py:30` | 1-2 references each, definitions only | Delete | Verified (reference counts) |
| Wall fallback branch | unused on all 7 pool maps (`VERIFY_NOTES.md:605`) | Keep only if a new map needs it | Reported |
| `LATCHES` in `ares_bridge.py:75-76` | read and logged only | Delete or use | Reported |
| Opponent record fields `wins`, `losses`, `first_aggression_time` | logged, never used | Use in M10 (expected attack time) | Reported |
| `scripts/m7_d37_switch_back.py` | its C4 edits match nothing since D38; running `ALL` leaves a half-edited worktree | Remove | Reported |
| `scripts/update_ares.py` | moves the pinned submodule; nothing references it; against CLAUDE.md | Remove | Reported |
| `scripts/create_pyinstaller_exe.py`, `.github/workflows/build_windows_exe.yaml` | spec §10 puts executables out of scope | Remove (D7) | Reported |
| `test_air_counters.py`, `test_scout_abilities.py`, `test_can_win_fight.py`, `check_ramp_walls.py` | always exit 0, so they are experiments | Give them a pass/fail or move to `scripts/experiments/` | Reported |
| `docs/STATUS.md:323` says AIR_HARASS has no detector; the Voltron postmortem names two scripts that do not exist | stale | Correct | Reported |

### 5.3 Rule and housekeeping items

- `bot/constants.py`: 385 module-level names, **none unused**. 5 are read only by `scripts/`
  (`M1_PROBES_AT_6_MIN`, `M3_EXPECTED_FLAGS`, `M3_ALWAYS_ALLOWED`, `M3_FLAG_RATE`,
  `M3_SCOUT_SAFE_RATE`): test settings living in the bot's file. **Verified** (name search).
- Thresholds outside `constants.py`: `army.py:524, 536, 759`; `micro.py:127, 167, 297, 326, 338`;
  `scout_tasks.py:101`; `scout_planner.py:269, 475, 551`; `detectors.py:225`. Two unit stats are
  typed in (`constants.py:714` Oracle beam energy, `:743` hallucination life). **Reported.**
- `test_attack_decision.py` and `test_counterattack_rules.py` hard-code TUNE values, so tuning
  those constants would fail the tests while the logic is right. Fix before M14. **Reported.**
- `scripts/run_matches.py` runs games one after another, takes only the built-in AI or the four
  scripted cheeses, writes no result file, and has no way to override a constant. All four are
  needed for a test rig. **Reported.**
- The GitHub Action runs no tests before building the zip. **Reported.**
- `docs/VERIFY_NOTES.md` is 2,927 lines and mixes API findings with acceptance evidence. Split it
  (D8).

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
  natural way to run downloaded zips, since they expect the ladder's layout. It sets no CPU or
  memory limits and runs one match at a time; running several at once is M8 work (**Reported**).
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

## Part 7. Roadmap

Ordered by how many of the 177 losses each milestone should remove. Each one follows CLAUDE.md:
one at a time, spec diff first, evidence for every criterion, then stop. "Rig" means the batch
runner built in M8. Every milestone also keeps the existing regressions (STATUS "Test commands")
and ends with the ladder check: `poetry run python scripts/ladder_watch.py --first 20`.

| M | Deliverable | Losses targeted | Acceptance (each checked by a command) | Runs where |
|---|---|---|---|---|
| **M8** | **Test rig and false alarms.** (a) `run_matches.py`: parallel games, a JSON result file, downloaded ladder zips as opponents through the `ladder_env_test.py` setup, constant overrides. (b) Reaper no longer raises PROXY; ares unit flags need a unit near home; a scouting probe alone does not raise CANNON_RUSH; memory pre-raises only on a confirmed structure; `C_2GateRobo` fixed or retired | up to 38 (2.3) | Rig: 20 games vs each of Thssprtssbt, Mulebot, norman, sludgement2-revived finish with a result file, and the baseline is recorded. False alarms: replaying the 49 pre-raised Terran logs' flag inputs through the offline flag test raises PROXY only in the 4 with a proxy structure. Ladder: over the next 100 games, one-base-at-5:00 falls from 35% of games to under 15% (`docs/v2_evidence/classify.py`) | Rig on Ubuntu; code in cloud |
| **M9** | **Hold the mineral lines.** Probes leave a mineral line under attack and return when it is clear; anti-air at each mineral line from the first air-tech sighting or by time vs Protoss; fogged Cannons counted (DEF-3) | 31 (cause 2), part of 105 | Rig: vs Thssprtssbt, at least 12 of 20 (ladder today 2-13). Median mining probes lost in losses under 30 (today 62). New offline test for the flee rule passes | Cloud; rig on Ubuntu |
| **M10** | **Survive 5:00-10:00.** Expected-attack time from memory and scouting drives army size, Batteries and Sentries; lap re-scout of the enemy main; DT and timing-attack detectors built or the dead enums removed; shoot-then-step kiting and target priority | 105 (cause 3) | Rig: vs Mulebot, norman, sludgement2-revived, at least 10 of 20 each (ladder today 1-5, 4-7, 4-9). Ladder: losses with no launch fall from 81% to under 60% of losses | Cloud; rig on Ubuntu |
| **M11** | **Independent groups.** A home guard that stays at launch and answers each base; map vision posts; a remembered enemy-army position; raiders if D2 allows | causes 2, 3, 5 | Staged tests: two simultaneous raids on two bases are both answered while the main army stays out; a drop does not block a launch. Rig: no drop in M9 and M10 results | Cloud; rig on Ubuntu |
| **M12** | **Attack decision.** Launch and retreat read the remembered whole army, not the local view; the counterattack is replaced by M11's raiders or removed | 33 (causes 4, 5) | Ladder: launches that retreat within 60 s fall from 41% to under 20%; value lost / killed in losses under 1.3 (today 1.88) | Cloud |
| **M13** | **Cleanup** from Part 5.2 and 5.3, after D7 and D8 | none directly | `git grep` finds none of the removed names; all offline tests pass; the zip's content hash is unchanged by doc-only and script-only commits | Cloud |
| **M14** | **Tuning and unattended runs.** SPSA on one group of constants at a time, with a separate acceptance set; a restricted unattended Claude Code session if D6 allows | Elo from numbers | A tuned group is kept only if it wins the acceptance set at 95% confidence (6.4) and the next 100 ladder games do not fall | Ubuntu |

**Target check after M10:** if causes 2 and 3 are halved and 2.3 is fixed, about 85 of 177 losses
become wins, which is about 74% over the same games, above the 69% that +137 Elo needs.
**Uncertain**: opponents get harder with each division, so expect the gain to arrive in steps.

**Not attempted in this run:** any game (no SC2 here), the Windows zip build, the GitHub Action,
and any ladder upload.

## Part 8. Decisions needed

**Decided 2026-11-11 (user): D1 yes, D4 yes, D6 yes. M8 started.**

| # | Decision | My recommendation |
|---|---|---|
| D1 | Accept this plan's order (M8 first)? | Yes. M8's two fixes are small and measured |
| D2 | Spec §7 cut list: allow offensive harassment (Adept, Oracle, Dark Templar, Warp Prism raids)? | Yes, but not before M11. Defense first, because that is where the games are lost |
| D3 | Spec §1 "defense-first": change the style? | Keep it. The data says Citadel fails at defending, not that defending is the wrong idea. Add "and it must be able to raid" when D2 lands |
| D4 | Opponent memory: pre-raise only on a confirmed structure, and never end the opener from memory alone? | Yes |
| D5 | Spec §10 "no machine learning": lift it? | Not yet. Lift only for offline tuning tools in M14; no model in the bot until a narrow case is proven |
| D6 | New dependencies: allow tuning packages on the dev side (not in the zip)? Allow an unattended Claude Code session on the Ubuntu boot? | Dev-side packages yes, asked one by one. Unattended session: try once in M14 with the restrictions in 6.5 |
| D7 | Remove the Windows executable script and workflow, `update_ares.py`, `m7_d37_switch_back.py`? | Yes |
| D8 | Split `docs/VERIFY_NOTES.md` into API findings and an evidence archive, and trim `docs/STATUS.md`? | Yes, in M13 |
| D9 | Downloading other authors' public bot zips to use as sparring partners | Allowed by their setting; ask on the AI Arena Discord first if you want to be courteous |

### Proposed wording (nothing is changed until approved)

- **CLAUDE.md, Environment**, add: "The desktop also dual-boots Ubuntu Server (NVIDIA drivers
  installed). It is the test rig: headless SC2 4.10, batches of games, unattended during school
  hours and overnight. It is never used for uploads."
- **CLAUDE.md, Rules**, change the dependency line to: "Bot code adds no dependencies beyond the
  template's without asking me. Tools that only run on the test rig may, also after asking."
- **DESIGN.md §4.4 and `ares_bridge.py`**: "A Reaper is not proxy evidence. A unit-based ares
  flag raises a threat only with a matching unit near our bases."
- **DESIGN.md §5**: "A flag pre-raised from memory needs a structure sighting in the earlier
  games and never ends the opener by itself."
- **DESIGN.md §7**: milestones M8-M14 as above; the cut list loses "Oracle harass as a plan" and
  "Warp Prism" when D2 is approved.
