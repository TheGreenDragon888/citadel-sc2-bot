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

PENDING (research running). Direction so far, from Part 2: the biggest losses are **missing
behaviours and wrong rules**, which tuning numbers cannot fix. Automatic tuning becomes useful
after M8-M10 below, and it first needs opponents that attack the way ladder bots do.

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
