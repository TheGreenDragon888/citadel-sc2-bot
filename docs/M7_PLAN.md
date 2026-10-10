# M7 execution plan (codebase)

**M7 (user decision): fixes and additions from the first ladder losses.**
- **The what and why** is in `docs/postmortems/2026-10-05-MetaScoreCritic1212VII-fix-plan.md`, with the evidence in the postmortem next to it.
- **This file is the how:** the order of work, the files and functions each step touches, new constants, tests, VERIFY items, commits and the evidence each phase ends with.
- **Item IDs** (O1, B1, C1, K1, E1 …) match the fix plan.

## Decisions this plan builds on

| # | Decision |
|---|---|
| D1, D2 | Drop the PvP 4:30 and PvZ 6:30 Hallucinated Phoenix scouts. |
| D3 | Blink Stalkers, with Blink micro, for basic combat and against capital ships. Blink micro comes off the v1 cut list. |
| D4, D8 | The capital-air answer includes Void Rays and/or Tempests. Void Rays are expected to be best vs Tempests; Tempests vs Carriers, Battlecruisers and Brood Lords. The staged test E0 sets the shares. |
| D5 | A 4th base when gas-starved with a mineral bank. |
| D6 | The milestone is M7. |
| D7 | Twilight order: Blink first vs P and T; Charge first vs Z, then Blink. |
| D9 | CAPITAL_AIR is detected for every race, **and M7 responds to it for every race** (vs P: Tempest/Carrier/Mothership; vs T: Battlecruiser; vs Z: Brood Lord). |
| D10 | **High Templar and Archons are allowed.** Psionic Storm and Archon splash are core vs Z. **Archons are not an anti-air tool**: the §4.5.1 air switch only raises the Stalker share (this replaces the spec's "add Archons"). **Small Archon shares:** vs T while the enemy army is mostly bio; vs P while it's Zealot-heavy. |
| D11 | **Targets (user accepted, 2026-10-06), on the baseline seeds:** Protoss Air VeryHard ≥ 7/10 (baseline 2/10, seed 7000); Terran Air VeryHard ≥ 9/10 with no loss to Battlecruisers (baseline 9/10, seed 7100); Zerg Air VeryHard ≥ 9/10 (baseline 10/10, seed 7200). CheatInsane Air vs Terran and Zerg (seeds 7300/7400) exercise Battlecruisers and Brood Lords. **Their targets (user accepted, 2026-10-07):** Terran Air CheatInsane ≥ 7/10, the M4 bar (baseline 2/10); Zerg Air CheatInsane ≥ 9/10 (baseline 8/10). |
| D12 | **B6 (user accepted):** the §4.4 rows 7/10 missing-production test waits for the enemy natural to be seen and doesn't count an expansion-first opening (it raised a false PROXY in 7 of the 8 baseline losses vs Protoss Air). |
| D14 | **B7 (user decision, 2026-10-07):** while an enemy Cannon stands within 25 of our main or natural, the army holds at the top of the main ramp, as the proxy plan does. In the Phase 1 cannon-rush batches, every unit sent to the natural's hold point walked past the rush Cannons and died; the Phase-0 code lost the same game that way. |
| D15 | **B8 (user decision, 2026-10-07):** an Observer starts an expansion check only if the enemy main won't fall due for its re-scout before the trip ends, or another Observer stays free; otherwise a probe goes. After B4, the enemy main still went unseen for up to ~2.5 minutes while the only free Observer was on a 90-110 s expansion trip. |
| D16 | **The HOLD `lost_far` criterion moves to Phase 2 (user decision, 2026-10-07).** Phase 1 had 8 against the Phase-0 code's 2, all in two losses to mass air, while HOLD deaths overall fell from 45 to 17. C1/C2 target those deaths. |
| D17 | **B9 (user decision, 2026-10-08):** while PROXY is active and a proxy production structure is known, the DEFEND squad kills it once it can win that fight, as it clears Cannons near our bases. Two proxy-rax games tied at 60:00: one base, under the 150-supply launch gate, and the proxy Barracks never killed, so the flag never expired. |
| D18 | **Melee units and the out-ranged rule (user decision, 2026-10-08):** a unit whose game-data range is at most `MELEE_RANGE_MAX` is out-ranged only by enemies it can't hit, in C1 (step-out and hold-point fallback) and C5 (penalty). On `79fdd0e`, C1/C5 treated Zealots as out-ranged by Marines: proxy rax fell from 10/10 to 7/10, losing the two games without opponent memory. |
| D19 | **Weaponless units (user decision, 2026-10-08):** 12 types have no weapon in this game data. (a) The range rules use ares's `WEIGHT_COSTS` range for a type without a game-data weapon, on both sides. (b) When weaponless damage dealers (`WEAPONLESS_DAMAGE_TYPES`) make up at least `WEAPONLESS_CAP_SHARE` of the enemy's value, `Engagement.level` is capped by the value level (§4.5.2). (c) Our units with a range from neither source keep their pre-M7 behaviour (no step-out, not left out by C2). |
| D20 | **The one-base proxy stalemate is investigated now (user decision, 2026-10-08):** in proxy-rax game 8 on `703b084` and `79fdd0e`, no Nexus was started although the plan allowed one, and Adepts at the ramp were picked off one at a time with no home threat logged; the game tied at 60:00 both times. |
| D21 | **The C4 home-fight threshold `LAUNCH_HOME_FIGHT_MIN_FRACTION` is accepted (user decision, 2026-10-08).** |
| D22 | **Home-defense hysteresis (user decision, 2026-10-09):** once engaged, the DEFEND squad keeps fighting until the level is at most `DEFEND_DISENGAGE_AT`; then the defensive position falls back all `HOLD_FALLBACK_STEPS` at once, and the squad doesn't engage again outside the defensive position for `MIN_STATE_SECONDS`. On `4c39bbf`, 35-76 HOLD deaths per Protoss Air batch came within 30 s of an engage → hold flip. |
| D23 | **C5 and melee units (user decision, 2026-10-09):** in the out-range share, our melee units count only when they are the only units of ours able to hit that enemy. Under D18 alone, sieged Siege Tanks added nothing to the penalty while Zealots were in the army (VeryHard Terran game 4 lost to four launches into tank lines). |
| D24 | **Nexus priority under the PROXY and ONE_BASE_ALLIN plans stays as it is (user decision, 2026-10-09):** proxy rax went 20/20 on `641cf24`. |
| D25 | **C8, the leash gap, is accepted (user decision, 2026-10-09).** |
| D26 | **Pull back as a retreat: tried and reverted (user decision to try, 2026-10-10).** After a lost home fight, DEFEND units away from the fallen-back position got RETREAT intent for `HOLD_FALLBACK_KEEP_S` (`f7aed30`). With the same seeds and openers, Protoss Air went 3, 7 and 6 of 10 against `f2bab76`'s 7, 9 and 7, at value lost/killed 1.17 against 0.82. Units lost per disengage didn't fall (14-19 against 9-14). Reverted to `f2bab76`'s behaviour (VERIFY_NOTES "M7 acceptance evidence"). |
| D13 | **E0 gets a mass-Void-Ray case (user accepted).** Whether Void Ray masses also trigger the Void Ray/Tempest response is decided with those numbers. Void Rays were our top killer in 7 of 10 baseline games vs Protoss Air. |

**Defaults (accepted by the user):**
- **R1. High Templar and Storm vs Zerg only** in M7. Against Terran, Storm is strong against bio, but it's extra scope and Colossi already cover it. Archons follow §4.5.1's mixes:
  - **Vs Z:** in the normal army (the spec's Archon 15%), next to the Storm Templar.
  - **Vs T:** a small share while the cached Terran army is mostly biological (`ARCHON_VS_BIO_PCT`, on at `BIO_SHARE_FOR_ARCHONS`).
  - **Vs P:** a small share while it's Zealot-heavy (`ARCHON_VS_ZEALOT_PCT`, on at `ZEALOT_SHARE_FOR_ARCHONS`).
  - **Never through the air switch** (user decision).
  - Vs P and T the High Templar morph straight into Archons, with no Storm research.
- **R2. No Phoenix in M7.** Blink Stalkers, Storm and the vs-Z Archon share cover Mutalisks; Phoenix would be one more unit to control.
- **R3. One ladder upload per finished phase, after M6 passes.** Each upload restarts the 20-game no-crash count, but development of the next phase continues meanwhile.

## How the work runs
- **Commits:** one per working step (CLAUDE.md), on the session's development branch. `main` is brought up to date after M7's acceptance, or when you decide, as with M5/M6.
- **One review stop at kickoff:** DESIGN.md is the source of truth, so its M7 diff is shown to you before any bot code changes. After that, each phase ends with its evidence and a stop. Ambiguities found on the way get asked, not picked.
- **Rules:**
  - every threshold is a TUNE value in `bot/constants.py`;
  - unit stats are read from game data;
  - Unit objects are never stored across steps (tags only);
  - no new dependencies;
  - nothing is written outside `./data`;
  - the `ares-sc2` submodule isn't edited.
- **VERIFY items** are checked in the ares or python-sc2 source (or with a staged game when the source can't answer) and written to `docs/VERIFY_NOTES.md` "M7 findings" before the code relies on them.
- **Testable code:** new rules go in plain functions that take plain values, as in `attack_decision.py` and `counterattack.py`, so they can be tested offline by a `scripts/test_*.py` that prints PASS/FAIL and exits 1 on failure.

## Step S: environment and baseline (once per session that runs games)

```bash
cd ~
wget http://blzdistsc2-a.akamaihd.net/Linux/SC2.4.10.zip
unzip -P iagreetotheeula SC2.4.10.zip
cp ~/citadel-sc2-bot/maps/*.SC2Map ~/StarCraftII/Maps/
ln -s Maps ~/StarCraftII/maps
```

What each line does (from `docs/RESEARCH.md` and the README):
- `cd ~` goes to your home folder.
- `wget …` downloads Blizzard's Linux SC2 4.10 (about 4 GB).
- `unzip -P iagreetotheeula …` extracts it. The password stands for accepting Blizzard's AI licence. The result is `~/StarCraftII`.
- `cp …` copies the 7 pool maps into SC2's map folder.
- `ln -s Maps ~/StarCraftII/maps` makes a link named `maps` pointing at `Maps`, because the 4.10 client looks for the lowercase name.

Then the Poetry environment on Python 3.12 (README "Setup"; STATUS has the cloud-container workaround), and the offline tests as a smoke check: `poetry run python scripts/test_attack_decision.py` (and the other offline scripts in STATUS "Test commands").

**Baseline batches** run on the current code (`8036973`) and are recorded in VERIFY_NOTES "M7 baseline". Each repeats with the same games on every later phase:

```bash
poetry run python scripts/run_matches.py --difficulty VeryHard --race Protoss --build Air --map all --total 10 --game-seed 7000
poetry run python scripts/run_matches.py --difficulty VeryHard --race Terran  --build Air --map all --total 10 --game-seed 7100
poetry run python scripts/run_matches.py --difficulty VeryHard --race Zerg    --build Air --map all --total 10 --game-seed 7200
```

- `--build Air` picks the built-in AI's air build.
- `--game-seed` fixes the randomness so the same 10 games replay on later commits.
- The 4-core machine runs about four batches at once, 40-70 minutes each (STATUS).
- The existing M4/M5 numbers in STATUS serve as the regression baseline.
- After these runs I propose D11's targets.

## Step K0: kickoff (docs only, then the review stop)

| File | Change |
|---|---|
| `docs/DESIGN.md` §1 | Win condition: "3 bases, and a 4th when gas-starved with a mineral bank". Army: Stalker/Immortal/Colossus/Zealot, with High Templar/Archons vs Z. "Beyond v1" keeps only Carriers and Skytoss as the main army. |
| §3 | Architecture: add `army/blink.py`, `army/templar.py`, `intel/enemy_mix.py`. `micro.py`'s line gains "out-ranged rule, blink". |
| §4.2, §4.4 | Air/cloak detector rows (9, 13) are M7. New "Capital air" row: Fleet Beacon / Fusion Core / Greater Spire → WARNING; capital units seen → ACTIVE; response per race. |
| §4.3 | Delete the PvP ~4:30 and PvZ ~6:30 Hallucinated Phoenix rows. The hallucination rule notes it needs an existing Sentry (the vs-T mix). |
| §4.5.1 | Vs Z mix gets High Templar next to the Archon share. Vs T: a small Archon share while the enemy army is mostly bio. Vs P: a small Archon share while it's Zealot-heavy. Air switch: more Stalkers only, no Archons (replaces "add Archons"), with hysteresis. Capital-air mixes per race (shares from E0). Upgrades: per-building chains, Twilight order (D7), Psionic Storm vs Z. |
| §4.5.2 | Launch inputs (cached whole army, fresh intel, cooldown after a home fight); which units answer a threat; the out-ranged rule and hold-point fallback; retreat shooting; the out-range penalty marked "only if O1's evidence shows the simulator misjudges". |
| §5 | `Threat.CAPITAL_AIR` with its expiry (WARNING: STRUCTURE rules; ACTIVE: unit TTL). AIR_HARASS's "satisfied" state, which §5 already describes, is implemented. |
| §7 | M7 row (deliverable: Phases 0-4; acceptance below). Cut list: remove "High Templar" and "Blink micro"; "Skytoss" becomes "Carriers and Skytoss as the main army". |
| §8 | New metrics: fight inputs, tech seen, losses by intent, blinks, storms, Archon morphs, capital-air entries. |
| `docs/STATUS.md` | M7 row "In progress", links to this file. |
| `docs/VERIFY_NOTES.md` | Empty "M7 findings", "M7 baseline" and "M7 acceptance evidence" sections. |

Commit: `M7 kickoff: DESIGN.md for the user's M7 decisions`. **Stop for your review of the DESIGN.md diff.**

---

## Phase 0: observability

| Item | Files and functions | Change |
|---|---|---|
| O1 | `bot/army/engagement.py:level` | Store the last call's inputs: `(own_text, own_value, enemy_text, enemy_value)`, where the text is unit counts by type, highest value first, at most `FIGHT_LOG_TYPES` (TUNE, 6) types. A new pure helper `composition_text(pairs)` builds it from `(type_name, value)` pairs. |
| O1 | `bot/army/army.py:_log`, `_home_defense` | `ENGAGE`/`DEFEND` lines append the stored inputs. `self.decisions` entries become `(t, action, level, reason, own_value, enemy_value)`. |
| O1 | `bot/telemetry/logger.py:end_report`, `game_record` | Unpack the 6-tuple. Engage entries get `own_value`/`enemy_value`. Record `"version": 3`. |
| O1 | `scripts/check_game_log.py` | Accept versions 2 and 3. |
| O2 | `bot/intel/detectors.py:update` | `self.first_seen: dict[str, float]`. A new enemy structure type logs `INTEL first seen <TYPE> at <t> <pos>`; so does a cached unit in `CAPITAL_AIR_TYPES`, a new constant also used by E2: Tempest, Carrier, Mothership, Battlecruiser, Brood Lord, Brood Lord cocoon. |
| O2 | `logger.py:game_record` | `tech_seen: [{type, t}]`, capped by `GAME_LOG_MAX_EVENTS`. |
| O3 | `bot/main.py:on_unit_destroyed` | Read `self.army.intents.get(tag)` **before** `self.army.forget(tag)` (forget drops it) and pass it to `telemetry.on_own_unit_destroyed(own, role, intent)`. |
| O3 | `logger.py:on_own_unit_destroyed` | For army units: an `UNIT lost <TYPE> at <pos> (<t>, <intent> <d> from its point)` line; `lost_by_intent` and `lost_far` counts (distance > `LOST_FAR_DISTANCE`, TUNE 12) in the game record. |
| all | `scripts/run_matches.py:format_row` | A new `m7` column with the fields that later phases fill (`far=` deaths far from their point, `blink=`, `storm=`, `archon=`, `cap=` capital-air state). |

- **Tests:** `check_game_log.py --last 1` on a local game; an offline case for `composition_text` in a new `scripts/test_m7_rules.py`, which later phases extend.
- **Acceptance:** one local game shows the three new line types; `check_game_log.py` passes; M1 regression (Hard × 10, T/Z/P/Random) unchanged.
- **Commits:** O1, O2, O3 each.

## Phase 1: bugs (spec changes: K0's §4.3 rows; B7 and B8 in §4.2 and §4.3, user decisions D14 and D15)

| Item | Files and functions | Change |
|---|---|---|
| B1 | `army.py:_decide` (l.232-234) | `_reinforce(defenders)` only if `self.decision.state == ATTACK` after `_evaluate_attack`. |
| B1 | `army.py:_retreat_attack_squad` (l.276) | Also set `self.attack_center = None`. |
| B1 | `army.py:_set_intents` | When the state isn't ATTACK, `squads.assign(squads.tags(Role.REINFORCE), Role.DEFEND)` first. |
| B1 | `logger.py` | Count `reinforce_after_retreat` (a `reinforcements out` in the same decision tick as a retreat or recall). It must stay 0. |
| B2 | `army.py:micro` (l.635) | `micro.move(unit, point, attack=mode == FIGHT)`, so HOLD walks back with a plain move. |
| B2 | `micro.py:move` | A `force: bool = False` parameter that skips the "same target" check (used below). |
| B2 | VERIFY + `army.py:micro` | Staged test `scripts/test_outranged.py --case idle_hold`: does an idle unit at the hold point chase a Tempest beyond the leash? If yes: a HOLD unit beyond the leash with `unit.engaged_target_tag` set gets `micro.move(..., attack=False, force=True)`. |
| B3 | `army.py:micro` | For DEFEND units in FIGHT with `self.defend_target`: keep only visible enemies within `ENGAGE_ENEMY_RADIUS` of `defend_target`. |
| B4 | `scout_planner.py:step` (l.396-397) | Call `_rescouts()` before `_expansion_checks()`. New helper `_main_rescout_due()` (the condition at l.457-461). While it's true, `_expansion_checks` doesn't take an Observer (it uses a probe, or waits). |
| B4 | `logger.py` | Count main rescouts in the game record. |
| B5 | `constants.py:HALLUCINATION_AT_S` | `{"Terran": 330.0}`; update the `scout_planner.py` docstring (l.18-25). |
| B6 | `detectors.py:_proxy` (l.433-486) | For P and T, when the main has no Barracks/Gateway: if a townhall has been seen at their natural (`natural_townhall_seen_at`), drop that reason and log `SCOUT proxy check: expansion first`. If the natural hasn't been in vision since `PROXY_NATURAL_FROM_S` (`natural_seen_at`), leave `proxy_checked` False and decide on a later tick, at the latest at `PROXY_NATURAL_WAIT_UNTIL_S` (TUNE). This mirrors the Forge-first rule (`FORGE_FIRST_UNTIL_S`). The worker-count reasons and the far-production detector are unchanged. |
| B7 | `defense_planner.py:_plan_cannon_rush` | Pure `rush_cannon_near(cannons, homes, radius) -> bool`: an enemy Photon Cannon (finished or not, snapshots included) within `CANNON_RUSH_RADIUS` of our main or natural spot. While it's true: `plan.army_hold_point = self._ramp_hold()`, which `_safe` already keeps out of finished Cannons' reach. No leash, so home defense still clears Cannons near our bases once it can beat them (`army.py` l.436-446). CANNON_RUSH comes before the plans that set a hold point only when none is set. |
| B7 (follow-up) | `defense_planner.py:_safe` | Pure `safe_hold_point(point, toward, cover_count, step, steps)`. The hold point steps toward our main until no finished Cannon covers anything within `HOLD_RADIUS` of it (it was 1.0): holding units stand anywhere in that radius without moving. If every step is covered, it takes the step the fewest Cannons cover, so Cannons inside the main don't pull it toward them. Found in the first B7 batches: one game lost 32 holding units within 8 of the ramp hold point to a Cannon. |
| B9 | `army.py:_home_defense`, new `_proxy_clear` | With no other home threat, while the PROXY flag's `proxy_structure` source stands: its evidence structure nearest our natural becomes the threat and `defend_target`, if the DEFEND squad has `PROXY_CLEAR_SUPPLY` (TUNE) and beats the structure's guard (static defense and units near it) at `CLEAR_STATIC_LEVEL`. Otherwise it isn't a threat, so it doesn't stop launches, reinforcements or recalls. It ignores the plan's leash and `ARMY_DEFEND_RADIUS` (proxies stand 30-50 from our natural). Killing it ends the flag by rule (a). |
| B8 | `scout_planner.py:_expansion_checks` | Pure `observer_trip_ok(now, trip_s, main_seen_at, last_rescout_at, free_observers) -> bool`: true if another Observer stays free, or if `main_rescout_due(now + trip_s, …)` is false. `trip_s` is the straight-line path from the Observer through the trip's points, divided by `movement_speed × NORMAL_TO_FASTER`. That speed is base game data without upgrades, so the estimate errs long. When it's false, the trip goes to a probe as before (the probe skips the enemy main and natural), and the log says the Observer was kept for the re-scout. |

- **Tests:**
  - `test_m7_rules.py` gains `_main_rescout_due` cases (pure version) and the B6 decision as a pure function (main production, natural townhall seen, natural in vision, time → raise / skip / wait).
  - It also gains `rush_cannon_near`, `safe_hold_point` (B7) and `observer_trip_ok` (B8) cases.
  - `test_m3_checks.py`, `test_attack_decision.py` and `test_threat_flags.py` unchanged and passing.
  - `scripts/test_outranged.py` (new, staged, case `idle_hold`): Citadel vs a scripted Protoss `StagedEnemy` (as in `test_counterattack.py`); a debug-spawned Tempest attacks our hold point.
- **Acceptance:**
  - Air batches on the same seeds: `reinforce_after_retreat` = 0. (The HOLD `lost_far` criterion moved to Phase 2, D16.)
  - Main rescouts at least every ~90 s from 6:00 while an Observer is free.
  - B8: in the Protoss Air batch, no gap over 90 s between main re-scouts from 6:00 while an Observer is alive and not held by the army or a post (Observer deaths aside).
  - B7: cannon rush ≥ 8/10 on two runs of the seeds (one run swung 5/10 to 8/10 on the same code), and no unit lost walking to a hold point past rush Cannons.
  - B9: proxy rax ≥ 8/10 on two runs, no 60:00 tie, and the log shows the proxy structure cleared (`clearing proxy …`) in the games where it stood.
  - B6: no PROXY flag in Protoss Air games where the enemy opened Nexus first (the baseline's `PROXY@01:30` games), and the cheese batches still raise PROXY vs `proxy_rax` (correct flag 40/40).
  - Regressions at their recorded levels: M1 Hard × 10; M2/M3 cheese × 10 each (≥ 8/10, flags 40/40, no scout lost before 4:00); M4 VeryHard × 10 per race (≥ 7 each).
- **Ladder:** after M6 passes, Phases 0 + 1 are the first M7 upload: zip on Python 3.12, `ladder_env_test.py`, upload, `ladder_watch.py`.

## Phase 2: combat

| Item | Files and functions | Change |
|---|---|---|
| C1 | new `bot/army/ranges.py`, `micro.py` | **As built:** pure `outranged(our_range, their_range, margin) -> bool` and the game-data adapters `can_hit`, `reach` and `outranges` live in `ranges.py`, which both `micro.py` and `engagement.py` import (C5 needs them, and `micro.py` already imports `engagement.py`). `micro.out_rangers(unit, enemies)` lists the out-rangers that have the unit in reach (+ `OUTRANGED_REACH_BUFFER`); `micro.step_out` runs `KeepUnitSafe` on the influence grid. |
| C1 | `army.py:micro` | HOLD, MOVE and RETREAT units with an out-ranger in reach step out first, on their own tick, and don't shoot or walk on meanwhile; FIGHT and HARASS units (committed) are unchanged. This replaces the planned `fight(committed)` parameter: same rule, one place. |
| C1 | `army.py` (anchor) | New `_fallback_anchor(anchor)`: while enemies that out-range every DEFEND unit type, seen within `HOLD_FALLBACK_MEMORY_S`, have the anchor in reach and home defense isn't fighting (`defend_target` is None), step it toward the main by `HOLD_FALLBACK_STEP`, at most `HOLD_FALLBACK_STEPS` times. Logged as `ARMY … hold point back to …` / `restored`. |
| C2 | `army.py:_home_defense` | Keep the evaluated threat group's tags. Defenders that can't hit any of it (`micro._can_hit`) are left out of the `engagement.level` call. |
| C2 | `army.py:_set_intents` | Those units get `(HOLD, anchor)`, in the last-stand branch too. |
| C3 | `micro.py:retreat` | Pure `retreat_may_shoot(own_speed, threat_speeds, target_fights_back) -> bool`. Shoot only units that fight back, and only if `unit.movement_speed` (game data) beats every visible threat's. |
| C4 | `attack_decision.py:evaluate` | New input `since_home_fight_s`; no launch while it's < `LAUNCH_AFTER_DEFEND_S`. **As built (`79fdd0e`):** a "home fight" is one against a group worth at least `LAUNCH_HOME_FIGHT_MIN_FRACTION` (TUNE, 0.2) of the DEFEND squad's value. Without it, a 12-pool bot's trickle of 1-8 Zerglings every 15-20 s held a 200-supply army at home from 9:00 to 21:50 in a test game, which tied. |
| C4 | `army.py:_evaluate_launch` | Second simulation vs the cached army: `get_cached_enemy_army` fighters with `age ≤ LAUNCH_CACHE_MAX_AGE_S` (TUNE). Its level must also be ≥ `ATTACK_START`. Fresh intel: the cached army's fresh fraction (as in `army_position.py`, `OUT_OF_POSITION_FRESH_S`) must be ≥ `LAUNCH_INTEL_FRESH_FRACTION`. If it isn't, set `self.wants_intel = True`, and launch anyway after `LAUNCH_INTEL_WAIT_S`. |
| C4 | `army.py:_set_intents` | **As built (DESIGN §4.5.2: "the army's Observer goes to look first"):** while `wants_intel`, the army's own Observer moves to the remembered enemy army's centre (else the enemy main), danger-aware as always (`keep_safe`). No scout-planner task. The decision logs `ARMY … launch waits, the Observer looks` once per wait. |
| C5 | `engagement.py`, `ranges.py` | **Built: the Phase 1 batch logs show it** (64 home engagements against armies with 2+ Tempests rated ≥ 7, some at a third of the enemy's value). `Engagement.outranged_share(own, enemy)` (value share of enemies that out-range every unit of ours able to hit them, or that none can hit) → pure `ranges.outrange_penalty(share, OUTRANGE_PENALTY_PER_SHARE)` levels, subtracted in `level()` and logged in the fight inputs (`-N out-ranged`). Carriers have no weapon in game data, so they don't count (their capital-air answer is Phase 4). |
| C5 | `scripts/test_engagement.py` | New scenario: 8 Tempests + 6 Zealots vs 30 Stalkers + 4 Colossi, to measure the raw simulator first. |
| C6 (D18) | `ranges.py` | Pure `outranged(our_range, their_range, margin, melee_max)`: never true when `our_range` (not None) is at most `melee_max` (`MELEE_RANGE_MAX`). C1's step-out, the hold-point fallback and C5's share all go through `outranges`, so they follow. |
| C7 (D19) | `ranges.py` | `weapon_range(unit, flying)`: python-sc2's `can_attack_*`/`*_range` (its Battlecruiser and Oracle special cases included), else ares `WEIGHT_COSTS[type]`'s `GroundRange`/`AirRange` when above 0, else None. `can_hit`, `range_vs` and `reach` use it; new `has_weapon(unit)`. |
| C7 (D19) | `micro.py`, `army.py` | `threats_to`, `_fights_back`, the kite and harass reach checks, the MOVE filter and the fallback's longest range use `ranges` instead of `can_attack_*`/`*_range`. Own units without `has_weapon` get no out-rangers (no step-out) and stay in `_able`. |
| C7 (D19) | `engagement.py` | Pure `value_level(own_value, enemy_value)` (ares's mapping with values as health). `level()`: if `WEAPONLESS_DAMAGE_TYPES` hold ≥ `WEAPONLESS_CAP_SHARE` of the enemy's value, the raw level is capped at the value level before C5's penalty; the fight inputs log `value cap N` when it lowers the level. |
| C8 (D20) | `army.py:_home_threat` | **As built (`641cf24`):** at a leashed hold point, an enemy beyond the leash that has one of our holders (DEFEND units within `HOLD_RADIUS` + 1 of the point) in its reach counts as a home threat, so the squad evaluates it like any other (engage as a group at the gate, else hold). **Found:** Marines below the main ramp, 10-11 from the hold point (leash 8), shot holders standing up to `HOLD_RADIUS` (6) from it, and nothing answered them (debug rerun: `threat=None` at every death). Their presence also re-confirmed ares's marine-rush flags all game, so PROXY and ONE_BASE_ALLIN never expired. Rerun of the stalled game 8 spawn with C8: no army unit lost, launch at 10:51 at 150 supply, won at 12:11 (before: 37 hold deaths, tie). |
| (finding) | `main.py:_register_macro_plan` | **Decided (D24): unchanged.** Under the PROXY and ONE_BASE_ALLIN plans the plan's unit production comes before the waiting Nexus (§3 Defense > Economy), so every proxy-rax game stays on one base until 10:00 or later (debug rerun: a Nexus order waited from 2:13 with minerals at 5-250 the whole game). §4.2 says only "skip the natural until 2 units are out". |
| C9 (D22) | `army.py:_home_defense`, `_fallback_anchor` | Pure `home_engages(level, needed, engaged, disengage_at) -> bool`. The squad remembers it engaged (`_home_engaged`); on a disengage it sets the fallback to `HOLD_FALLBACK_STEPS` for `HOLD_FALLBACK_KEEP_S`, logs `ARMY … hold point back to … (disengaged)`, and holds re-engagement outside the leash and the main until `MIN_STATE_SECONDS` later. |
| C10 (D23) | `ranges.py`, `engagement.py` | Pure `ranges.outranges_hitters(enemy, hitters)`: the hitters' melee units are left out unless all of them are melee. `Engagement.outranged_share` uses it. |

- **VERIFY:**
  - Do Tempests' ground attacks add influence to ares's ground grid?
  - What does `KeepUnitSafe` do with no safe cell nearby?
  - Does `Unit.movement_speed` exclude upgrades (python-sc2 `unit.py:322` says so)?
  - Is the `age` of cached army units the time since last seen (`unit.py:471`)?
- **Tests:**
  - `test_m7_rules.py`: `outranged`, `retreat_may_shoot`, the C2 eligibility function, and `outrange_penalty` if built.
  - `test_attack_decision.py`: cooldown cases.
  - `test_outranged.py`: new cases `hold_vs_tempest` (no unit dies beyond the leash; the hold point moves back) and `committed` (FIGHT units still engage).
  - D22/D23: `test_m7_rules.py` gains `home_engages` and `outranges_hitters` (stand-ins); `test_engagement.py` gains sieged tanks against Stalkers + Zealots (penalised) and against Zealots alone (not).
  - D18/D19: `test_m7_rules.py` gains the melee cut-off, `weapon_range` fallbacks (stand-ins) and `value_level`; `test_engagement.py` checks 2 Zealots vs 4 Marines (no penalty) and the weaponless rows (capped).
- **Acceptance:**
  - Air batches (same seeds): value lost/killed ratio and launch-then-retreat-within-60-s count better than Phase 1.
  - HOLD `lost_far` in the Air batches lower than Phase 1's (8 in the Protoss Air batch; D16).
  - Regressions: M1, M2/M3, M4 (≥ 7 each), M5 staged counterattack 7/7.
  - D18: proxy rax ≥ 8/10 on two runs.
- **Ladder:** second upload.

## Phase 3: Blink and Templar

| Item | Files and functions | Change |
|---|---|---|
| K1 | `constants.py` | Replace `UPGRADES_VS_P` / `UPGRADES_VS_ZT` with `UPGRADE_CHAINS[race][building] = (upgrades…)`: Forge (weapons/armor), Twilight (P, T: Blink → Charge; Z: Charge → Blink, D7), Robotics Bay (Extended Thermal Lance), Templar Archives (Z: Psionic Storm). |
| K1 | `production.py:_next_upgrade` → `next_upgrades(chains, ready_buildings, pending) -> list[UpgradeId]` | Pure. One upgrade per chain, issued only when that chain's building is ready, so an upgrade never makes ares build a tech building. `behaviors()` adds one `UpgradeController([u])` per returned upgrade. |
| K1 | `constants.py:OPENER_SCHEDULES` | A shared post-opener `ScheduleItem` for the Twilight Council (`TWILIGHT_AT_S` per race, TUNE) and, vs Z, the Templar Archives (`TEMPLAR_ARCHIVES_AT_S`). The executor already handles "structure" items after the opener (`build_executor.py:_behavior`). |
| K2 | `bot/army/blink.py` (new) | Pure rules: `blink_back(shield_fraction, threatened) -> bool`; `blink_in_point(unit_pos, target_pos, weapon_range, blink_range)`; `blink_finish(target_hp_shield, our_volley, landing_safe, local_level)`. Landing check: `landing_ok(point)` = pathable, visible (`bot.is_visible`), grid influence ≤ `BLINK_DANGER_MAX`, and not up a cliff without vision (`get_terrain_z_height`). |
| K2 | `micro.py` | `fight` (committed) tries blink-in on out-rangers. Its per-out-ranger budget `BLINK_IN_PER_TARGET_S` is held by the army as tag → last blink time. `retreat` and `harass` try blink-back first. Readiness: `AbilityId.EFFECT_BLINK_STALKER in unit.abilities`. The command is `unit(AbilityId.EFFECT_BLINK_STALKER, point)`. |
| K2 | `logger.py` | Count blinks by kind. |
| K3 | `constants.py:ARMY_COMPOSITION_PCT["Zerg"]` | Add `HIGHTEMPLAR` (TUNE) next to an Archon share (the spec's 15%). Archons are **not** given to ares's SpawnController: its Archon morph merges any two idle Templar (`spawn_controller.py:_handle_archon_morph`), which would eat the storm casters. |
| K3 | `bot/army/templar.py` (new) | `TemplarController`, run every step after army micro. **Storm:** an HT with Storm available uses ares `AutoUseAOEAbility` (avoids our own ground and air units; won't stack storms). **Positioning:** otherwise it stays `TEMPLAR_BEHIND` behind its squad's centre with `KeepUnitSafe`, never in front. **Morph:** pairs of HTs below the storm energy for `TEMPLAR_MORPH_AFTER_S`, or HTs beyond `TEMPLAR_MAX_CASTERS`, morph into Archons (two-tag command, VERIFY which path below). |
| K3 | `army.py` | HTs belong to squads like other fighters, but their micro goes to `TemplarController` (skipped in `micro()` like `SUPPORT`). Archons are ordinary fighters (not kiters; splash isn't simulated). |
| K3 | `bot/intel/enemy_mix.py` (new) | Pure core: `measure(cached: list[(type_name, supply, value, biological, flying, can_attack, age)], now) -> EnemyMix(army_supply, bio_share, zealot_share)`. Shares are by supply, as §4.5.1's air switch is (supply and value from game data). Biological comes from game data (python-sc2 `Unit.is_biological` reads the type's attributes, `unit.py:180`). Entries older than `MIX_FRESH_S` fade. An adapter reads `get_cached_enemy_army` each intel tick. E2 adds the air and capital-air fields. |
| K3 | `production.py:composition` | Vs T: add `ARCHON_VS_BIO_PCT` while `bio_share ≥ BIO_SHARE_FOR_ARCHONS`. Vs P: add `ARCHON_VS_ZEALOT_PCT` while `zealot_share ≥ ZEALOT_SHARE_FOR_ARCHONS`. Both with hysteresis (`MIX_SWITCH_HOLD_S`). Vs P and T the HTs morph straight into Archons, with no Storm research there (R1). That needs a Templar Archives, which ProductionController's tech_up adds once HTs are in the mix. |
| K3 | `logger.py` | Count storms cast and Archons morphed. |

- **VERIFY:**
  - the Blink and Psionic Storm ability ids and their energy/cooldown behaviour in `unit.abilities` under AIE data (energy costs are measured, VERIFY_NOTES §11.7 style);
  - the safe-spot accessor if one exists in ares;
  - the Archon morph command: ares `_do_archon_morph` (`custom_bot_ai.py:365`) vs python-sc2 combining two identical `MORPH_ARCHON` commands;
  - `client.debug_upgrade` (python-sc2 `client.py:881`) for the staged tests.
- **Tests:**
  - Offline in `test_m7_rules.py`: `next_upgrades` chain cases (every race, buildings missing or ready), Blink rules, morph-pair selection (pure); `enemy_mix.measure` bio and Zealot shares, fading, and the Archon-share hysteresis.
  - New staged `scripts/test_blink.py` (debug-spawned, all upgrades on): Blink Stalkers vs Tempests and vs Stalkers; blink counts and value traded.
  - New staged `scripts/test_templar.py`: storm on a ling/hydra clump; no storm on our own units; low-energy pair morphs.
- **Acceptance:**
  - Blink researched by its schedule time in every P/T game; Charge then Blink vs Z.
  - Storms cast in VeryHard Zerg games.
  - Archons appear vs bio-heavy built-in Terran and Zealot-heavy built-in Protoss (`archon=` column), and none come from the air switch.
  - VeryHard Terran and Protoss × 10 stay at their recorded 10/10 (M4/M5).
  - Air batches (same seeds) better than Phase 2.
  - VeryHard Zerg × 10 at least M4's 9/10.
  - All regressions hold.
- **Ladder:** third upload.

## Phase 4: economy, detector, capital-air response

| Item | Files and functions | Change |
|---|---|---|
| E0 | `scripts/test_air_counters.py` (new, staged, dev-only) | Scripted enemy (as `test_counterattack.py:StagedEnemy`) with kiting Tempests (P), Battlecruisers (T), Brood Lords + Corruptors (Z), or a mass of Void Rays (P, D13). Our side gets the same resource value (game-data costs) of each candidate: Void Rays, Tempests, Stalkers, Blink Stalkers, and mixes (no Archons: they aren't an anti-air tool, D10). 5 runs per case. Result table → VERIFY_NOTES; it sets the E3 shares. Can run as early as Phase 3 (it needs K2 for the Blink case). |
| E1 | `constants.py:MAX_BASES` → `bases_cap()` in `build_executor.py:bases_target` | 3, or 4 when minerals ≥ `FOURTH_BASE_BANK` and gas-starved for `FOURTH_BASE_GAS_STARVED_S`, 3 bases saturated, and `DefensePlan.allow_expand`. `economy.py:132` uses it. `PROBE_TARGET` follows the cap. |
| E1 | `production.py` (l.209-212) | Gas-starved with minerals ≥ `MINERAL_FLOAT_BANK`: Zealots may exceed their share (`freeflow`, capped by supply). |
| E2 | `bot/intel/enemy_mix.py` (from K3) | `EnemyMix` gains `air_share` (by supply, §4.5.1) and `capital_value` (by value, for `CAPITAL_AIR_MIN_VALUE`). Fading by `CAPITAL_AIR_FRESH_S`; explicit capital list (Carriers have no weapons in game data). |
| E2 | `threat_flags.py` | `Threat.CAPITAL_AIR`. Expiry: WARNING (STRUCTURE, never on a timer); ACTIVE (UNIT, `CAPITAL_AIR_UNIT_TTL`). AIR_HARASS "satisfied" state. |
| E2 | `detectors.py` | `air_harass` source (Stargate / Spire / Starport with Tech Lab) and `capital_air` source (Fleet Beacon / Fusion Core / Greater Spire → WARNING; `AirReading.capital_value ≥ CAPITAL_AIR_MIN_VALUE` → ACTIVE). Logs `INTEL capital air …`. |
| E2 | `defense_planner.py`, `static_defense.py` | `_plan_air_harass`: Forge now, then 1 Cannon + 1 Battery per mineral line (new placement helper next to `_main_batteries`, l.197); satisfied once every mineral line has detection. With E1's mineral sink, the bank pays for it first. |
| E3 | `production.py:composition` | Mix selection: normal (with K3's Archon shares) → air switch (AIR_HARASS active and air share ≥ `AIR_SWITCH_SHARE`, 0.30: Stalker share up, nothing else) → capital air (CAPITAL_AIR ACTIVE). Hysteresis `AIR_SWITCH_HOLD_S`. Capital-air tables per race in `ARMY_COMPOSITION_PCT` (vs P: Void Rays (+ Tempests vs Carriers); vs T and Z: Tempests; Blink Stalkers up and Colossi cut in all three), shares from E0. WARNING (any race): one Stargate goes down early and Blink moves up the Twilight chain. ACTIVE adds the Fleet Beacon when the mix needs Tempests. |
| E3 | `micro.py` | `TEMPEST` and `VOIDRAY` targeting: capital or massive first (Tempest), armored or capital first (Void Ray). Prismatic Alignment via `UseAbility` when ≥ `VOIDRAY_ALIGN_MIN_ARMORED` armored enemies are in range. `TEMPEST` added to `KITERS`. |
| E3 | `logger.py` | `capital_air` entries (race, first WARNING and ACTIVE, peak values) and the mix changes. |

- **VERIFY:**
  - the Prismatic Alignment ability id and availability under AIE data;
  - Carriers' empty weapon list in game data (python-sc2 `unit.py:230-273` special-cases only Battlecruiser and Oracle);
  - `BROODLORDCOCOON` in the cache;
  - whether ares's ProductionController adds Stargate, Fleet Beacon and Templar Archives for the mix (`MAX_PRODUCTION_STRUCTURES` = 12).
- **Tests:**
  - Offline: `enemy_mix.measure` air cases (Carrier counted, fading, air share); `test_threat_flags.py` CAPITAL_AIR expiry and AIR_HARASS satisfied; `bases_cap` cases; mix-selection hysteresis.
  - Staged: E0.
- **Acceptance (M7's):**
  - The three VeryHard Air batches (same seeds) meet D11's targets: Protoss ≥ 7/10, Terran ≥ 9/10 with no loss to Battlecruisers, Zerg ≥ 9/10. The CheatInsane Terran/Zerg Air batches meet the targets set from their baseline.
  - Unspent minerals at 10:00 well below the postmortem's 2,670.
  - All regressions hold: M1; M2/M3; M4 (≥ 7 each); M5 7/7.
  - No crash or time-out in the first 20 ladder games after the final upload.

---

## New and changed files at a glance
- **New, in the bot:**
  - `bot/army/blink.py`
  - `bot/army/templar.py`
  - `bot/intel/enemy_mix.py`
- **New dev-only scripts** (not in the ladder zip):
  - `scripts/test_m7_rules.py` (offline)
  - `scripts/test_outranged.py`, `scripts/test_blink.py`, `scripts/test_templar.py`, `scripts/test_air_counters.py` (staged)
- **Changed:**
  - `bot/army/army.py`, `micro.py`, `engagement.py`, `attack_decision.py`
  - `bot/intel/detectors.py`, `threat_flags.py`, `scout_planner.py`
  - `bot/defense/defense_planner.py`, `static_defense.py`
  - `bot/macro/production.py`, `economy.py`, `build_executor.py`
  - `bot/telemetry/logger.py`, `bot/main.py`, `bot/constants.py`
  - `scripts/run_matches.py`, `check_game_log.py`, `test_attack_decision.py`, `test_threat_flags.py`, `test_engagement.py`
- **Docs:** DESIGN.md (K0), VERIFY_NOTES, STATUS.

## Main risks and how the plan handles them
- **Regressions in matchups the postmortem didn't touch.** Every phase reruns the full M1-M5 regression on recorded seeds.
- **The out-ranged rule and the stricter launch gate make the army passive.** Measured as launches per game and 60:00 ties in the batches. The §4.7 end-game gates still apply.
- **Gas.** Blink, Storm, Lance, Templar Archives, Void Rays and Tempests all compete for it. E1 adds the 4th base and mineral sink; until Phase 4 lands, the gas pressure shows up as later units in the batches.
- **Ares's Archon morph would merge storm casters.** The plan keeps Archons out of ares's SpawnController and morphs them itself (K3).
- **Ghosts' EMP strips Archon shields** (an Archon is almost all shields). Vs Terran the Archon share is small and only on while the enemy is mostly bio. Batches vs VeryHard Terran show whether it costs games.
- **Simulator blind spots** (no Blink, Storm, splash or range gap). Levels err conservative after C5 (if needed), and the logged inputs (O1) show where they're wrong.
- **Step time.** The new per-unit checks run inside micro's existing nearby-enemy lists. The §6 step guard and the `step=` column in batches catch spikes.

## Rough effort

| Part | Effort |
|---|---|
| K0 + S | half a session (S includes the 4 GB download and the baseline batches) |
| Phase 0 + 1 | 1 session plus a regression run |
| Phase 2 | 1-2 sessions plus tuning batches |
| Phase 3 | 2 sessions (Blink and Templar are the largest new code) |
| Phase 4 | 2-3 sessions, including E0 |

Each regression run is about 5-7 hours of games on 4 cores. Batches can overlap with writing the next step.
