# Fix plan: findings from the MetaScoreCritic1212VII postmortem

Source: `docs/postmortems/2026-10-05-MetaScoreCritic1212VII.md` (finding numbers below match it). Code references are at `8036973`.

## Ground rules this plan follows
- **The spec decides.** Items marked *spec change* need your approval of a DESIGN.md edit before any code is written. Items marked *bug* bring the code back to what DESIGN.md already says, so they need no spec change.
- **One phase at a time.** Each phase ends with evidence for its acceptance criteria, then stops.
- **New API uses get checked first.** Every API this plan leans on is checked in the ares or python-sc2 source and recorded in `docs/VERIFY_NOTES.md` before use (marked **VERIFY** below).
- **No hard-coded numbers.** Thresholds go in `bot/constants.py` as TUNE values, and unit stats (ranges, speeds) are read from game data.
- **M6 is still open.** The 20-ladder-game check on the uploaded zip has 10 games left, and a new upload restarts the count. Develop on a branch now; upload only after M6 passes, unless you say otherwise.
- **This container can't run games.** It has no `~/StarCraftII`, so every batch below needs SC2 installed per the README (~4 GB) or another machine.

## Decisions

| # | Question | State |
|---|---|---|
| D1 | Drop the §4.3 PvP 4:30 Hallucinated Phoenix scout | **Decided: drop** (your answer). Done in Phase 1. |
| D2 | The same contradiction exists for **PvZ**: the §4.3 ~6:30 Hallucinated Phoenix needs a Sentry, and the vs-Z mix has none. The stale-main hallucination rule also never fires vs P or Z. Drop both, keeping hallucination vs T only? | Open. Recommend: drop the PvZ row; the stale-main rule stays but in practice only fires vs T (vs P and Z the Observer rescout covers it). |
| D3 | §4.5.1 researches Blink vs P, but Blink micro is on the v1 cut list, so the research is wasted (#6). Remove Blink from the vs-P upgrades, or add minimal blink micro? | Open. Recommend: remove it now and revisit with B. |
| D4 | Which unit answers capital air (Tempest, Carrier, Battlecruiser, Brood Lord)? Options: (a) Blink Stalkers plus blink micro, (b) Void Rays / own Tempests (Skytoss is on the cut list), (c) Stalker-heavy with Cannons and Batteries at home, buying time only. | Open. Needed before B. Recommend (a) or (b). (c) only delays the loss. |
| D5 | A 4th base when gas-starved with a big mineral bank (D). §1 says "macro to 3 bases". | Open. Recommend yes, conditional (see D). |
| D6 | Milestone label for this work: "M7: ladder fixes" with the phases as sub-steps, or reopen M4? | Open. Recommend M7, so M4's acceptance evidence stays as recorded. |

## Overview

| Phase | Item | Finding | Type | Scope |
|---|---|---|---|---|
| 0 | O1 Log the sim's inputs | C, F | observability | S |
| 0 | O2 Log enemy tech and capital units first seen | 8, 10, F | observability | S |
| 0 | O3 Log where and why army units die | 2, F | observability | S |
| 1 | B1 No reinforcements after a retreat | 1 | bug | S |
| 1 | B2 Plain move back to the hold point | 2 | bug | S |
| 1 | B3 Home-defense micro fights only the evaluated enemy group | 2 | bug | S |
| 1 | B4 Main rescout before expansion checks | 8 | bug | S |
| 1 | B5 Drop the PvP hallucination scout (D1) | 8 | spec change (decided) | S |
| 2 | C1 Out-ranged rule and hold-point fallback | 2, B | spec change | M |
| 2 | C2 Only units that can hit the threat answer it | 3, 10 | spec change | S |
| 2 | C3 Retreat stops shooting | 1 | spec change | S |
| 2 | C4 Launch gate: whole army, fresh intel, cooldown | A | spec change | M |
| 2 | C5 Out-range penalty in the fight level (only if O1 confirms) | C | spec change | M |
| 3 | M1 One research queue per building | E, 6, 7 | spec change | S |
| 3 | M2 Mineral sink and conditional 4th base | D | spec change | M |
| 3 | M3 Tech detector: AIR_HARASS and capital-air flags | 10, 8 | spec change | M |
| 3 | M4 Air switch / capital-air composition (D4) | B, 7 | spec change | L |
| later | Batteries in the fight model (#4), low-HP pursuit (#5), Blink micro (#6) | 4, 5, 6 | spec change | M each |

Why this order:
- Phase 0 is cheap and lets every later phase be measured. It also settles C, which decides whether C5 is needed.
- Phase 1 needs no spec change and fixes the code that matches the spec worst.
- Phase 2 stops the bleeding: about 26k of army value was thrown away this game.
- Phase 3 gives the bot something to win with.

---

## Phase 0: observability

**O1. Log the sim's inputs.** Settles C.
- **Where:** `army.py:_evaluate_launch`, `_evaluate_attack` and `_home_defense`. `engagement.py:level` already receives both unit lists.
- **Fix:** `Engagement.level` remembers the last call's inputs as a compact summary (type × count, resource value, one per side). Then:
  - `ENGAGE` and `DEFEND` lines append it, e.g. `vs 8 TEMPEST 4 ZEALOT (4,200) | ours 22 STALKER 3 COLOSSUS (5,900)`.
  - The §8 `engage` entries in `games.jsonl` get `enemy_value` and `own_value`.
- **Ramifications:**
  - About one extra stdout line per decision change, no extra sim calls.
  - The game record gets a new field: bump `"version"` to 3 and make `scripts/check_game_log.py` accept both versions.
  - Old `games.jsonl` lines stay valid.
- **Verify:** one local game; a `DEFEND`/`ENGAGE` line shows the counts; `check_game_log.py --last 1` passes.

**O2. Log enemy tech and capital units, first sighting.**
- **Where:** `bot/intel/detectors.py`, which already reads `enemy_structures` every intel tick.
- **Fix:** One `INTEL first seen <TYPE> at <time> <pos>` line per new enemy structure type, plus one per capital unit type (Tempest, Carrier, Battlecruiser, Brood Lord, Mothership). Add a `tech_seen` list to the game record.
- **Ramifications:** None for behavior. These lines become M3's trigger later.
- **Verify:** a game vs built-in Protoss `--build Air` logs Stargate and Fleet Beacon lines.

**O3. Log where and why army units die.**
- **Where:** `telemetry/logger.py:on_own_unit_destroyed` (today it logs probes only) and `army.intents`.
- **Fix:** For army units, record the intent at death (`fight`/`hold`/`retreat`/`move`/`harass`) and its distance from the intent's point. Add a `lost_by_intent` count to the game record.
- **Ramifications:** None for behavior. The bot can't know the killer, so "out-ranged" deaths aren't visible here. The replay remains the check for that.
- **Verify:** a game with a home fight shows counts per intent.

**Phase 0 acceptance:** the three log types appear in a local game, `check_game_log.py` passes, and the M1 regression (Hard × 10) is unchanged. This phase can ship in the same zip as Phase 1.

---

## Phase 1: bugs (code doesn't match the spec)

**B1. No reinforcements after a retreat** (finding 1).
- **Where:** `army.py:_decide` l.232-234. `_evaluate_attack` can flip the state to GATHER, and `_reinforce(defenders)` runs right after it anyway. Also, `attack_center` (set at l.257) is never cleared, and `_set_intents` sends REINFORCE units to it (l.564).
- **Fix:**
  - Call `_reinforce` only if `self.decision.state == ATTACK` after `_evaluate_attack`.
  - `_retreat_attack_squad` clears `attack_center`.
  - As a guard, `_set_intents` moves any REINFORCE unit to DEFEND whenever the state isn't ATTACK.
- **Ramifications:** REINFORCE can only exist during an attack, which is the spec's intent (§4.5.2). New units after a retreat stay home and join the next launch. Nothing else reads `attack_center` (checked: only `army.py`).
- **Verify:** in the batch logs, no `reinforcements out` line in the same tick as a `retreat` or `recall`. No change in the M4 VeryHard win rate.

**B2. Plain move back to the hold point** (finding 2, part a).
- **Where:** `army.py:micro` l.634-635 issues `micro.move(unit, point, attack=mode != MOVE)`, an attack-move for HOLD units walking back. When a Tempest shoots one, the engine's auto-acquire makes it chase. `micro.move` then never re-issues, because the order's target is still the hold point (`micro.py:142`).
- **Fix:**
  - HOLD units more than `HOLD_RADIUS` from the point walk back with a plain move.
  - FIGHT keeps attack-move, since it is walking *to* a fight.
  - **VERIFY in game** whether an *idle* unit at the hold point also chases an attacker beyond the leash. If it does, also re-issue when `unit.engaged_target_tag` (python-sc2 `unit.py:1290`, meaning not documented, hence the check) is set and the unit is past the leash.
- **Ramifications:**
  - Units walking back ignore enemies outside the leash, which is the leash's point (§4.5.2 "never leaves the battery radius").
  - Enemies inside the leash are still fought (micro's per-step `visible` check).
  - Risk: an enemy just outside the leash can shoot units at the hold point. B2 doesn't solve that; C1 does.
- **Verify:** O3 shows no HOLD-intent deaths more than leash + 4 from the hold point in the Air batch.

**B3. Home-defense micro fights only the evaluated enemy group** (finding 2, part b).
- **Where:** `army.py:micro` gives FIGHT units every visible enemy within `MICRO_RADIUS` of *the unit*. `_home_defense` evaluated only enemies within `ENGAGE_ENEMY_RADIUS` of the threat (l.360). Stalker 101449730 ran at Tempests while the squad fought a Zealot elsewhere.
- **Fix:** For home-defense FIGHT intents, filter micro targets to enemies within `ENGAGE_ENEMY_RADIUS` of `defend_target`. The ATTACK squad is unchanged.
- **Ramifications:** A second enemy group elsewhere becomes the next threat on the following decision tick (~1.4 s at `GameStep: 2`) instead of being chased by whichever unit sees it. Cannon-rush clearing (structure targets) is unchanged: Cannons near the target are inside the radius.
- **Verify:** M2 cannon-rush batch (≥ 8/10 still); O3 FIGHT deaths stay near `defend_target`.

**B4. Main rescout before expansion checks** (finding 8).
- **Where:** `scout_planner.py` l.396-397 runs `_expansion_checks()` before `_rescouts()`. Each expansion trip takes the only free Observer for 1-2 minutes, so the §5 trigger ("enemy main unseen > 60 s after 3:00") found no unit from 5:43 to 11:01.
- **Fix:** Run `_rescouts()` first. While the main rescout is due, expansion checks use a probe on our half of the map, or wait.
- **Ramifications:**
  - Expansion intel arrives somewhat later.
  - More probe trips: STATUS notes probe expansion checks sometimes cost the probe.
  - Alternative: raise `OBSERVER_COUNT` 2 → 3 (25/75 and 21 s of Robotics Facility time).
- **Verify:** Air batch logs show `rescout … enemy main unseen` at least every ~90 s from 6:00 whenever an Observer is free. M3's "no scout lost before 4:00" still holds.

**B5. Drop the PvP hallucination scout** (D1, plus D2 if you approve).
- **Where:**
  - DESIGN.md §4.3 PvP row "~4:30 Hallucinated Phoenix"
  - `constants.py:HALLUCINATION_AT_S["Protoss"]`
  - `scout_planner.py:_hallucinate` (l.514, the matchup branch)
- **Fix:** Remove the Protoss entry (and Zerg with D2). The stale-main branch and the §4.7 hunt Phoenix stay.
- **Ramifications:** No behavior change in practice: it never fired vs P, since there's no Sentry. The spec and code stop disagreeing. `test_scout_abilities.py` is unaffected; it tests the ability, not the schedule.
- **Verify:** M3 checks (`test_m3_checks.py`) pass.

**Phase 1 acceptance:**
- **Wins hold:** M1 Hard × 10, M2/M3 cheese bots × 10 each, and M4 VeryHard × 10 per race stay at their recorded levels.
- **New baseline batch:** an A/B vs built-in Protoss Air shows no reinforcement-at-retreat lines and fewer HOLD deaths far from the hold point.

---

## Phase 2: combat (spec changes to §4.5.2 and §3 micro)

**C1. Out-ranged rule and hold-point fallback** (finding 2, part c; the main lever against B).
- **Where:**
  - `micro.py:fight`, which steps back only when *we* out-range the threat (l.~75)
  - `army.py` anchor selection (`hold_point` / `_rally_point`)
- **Fix, unit level:**
  - **Out-ranged:** a unit that is not committed (HOLD, MOVE or RETREAT intent) and is inside the reach of a visible enemy it can't reach backs out with ares `KeepUnitSafe` on the influence grid.
  - "Can't reach" means it can't hit that enemy at all, or that enemy's range minus ours is at least `OUTRANGED_MARGIN` (TUNE). Ranges come from game data (`air_range` / `ground_range`).
- **Fix, squad level:** when out-rangers that home defense can't beat (level < engage threshold) cover the anchor, the anchor moves to a fallback point out of their reach, toward the main, by `HOLD_FALLBACK_STEP` (TUNE). The hold point already shifts like this for Cannons (`HOLD_SHIFT_*`).
- **Ramifications:**
  - **It applies to everything that out-ranges us:** sieged tanks, Lurkers, Brood Lords, Liberators, Tempests, Carriers, Planetary Fortresses. Uncommitted units back off all of them, which is right unless the squad has decided to fight.
  - **Committed squads are unchanged.** FIGHT (ATTACK squad, engaged home defense) keeps today's behavior.
  - **A base under siege can be given up.** Tempests out-range Cannons, so the army keeps its units but may lose that base, which is why M4 (Phase 3) matters.
  - **It is only as good as vision.** Only visible enemies add grid influence (VERIFY_NOTES §11.6), so the army's Observer must stay at the anchor while the army is home. It already does (`_set_intents` l.571).
  - **Blind spots:** Spine Crawlers and Shield Batteries add no influence (VERIFY_NOTES); ranges are still known for them.
  - **Step time:** one range comparison per nearby enemy, inside micro's existing `near` lists, plus one grid query per affected unit.
- **VERIFY:** the influence of a Tempest's ground attack on ares's ground grid, and `KeepUnitSafe`'s behavior when no safe cell is near.
- **Verify:**
  - An offline test for the pure classification helper (fake units with ranges and flying flags).
  - Air batch: Stalkers lost in HOLD drop sharply against the baseline.
  - VeryHard Terran: no new losses to tanks.

**C2. Only units that can hit the threat answer it** (findings 3, 10).
- **Where:** `army.py:_set_intents` l.536-537 gives every DEFEND fighter `(FIGHT, defend_target)`. With nothing hittable, `micro.fight` attack-moves to that point anyway (`micro.py:67`). The level in `_home_defense` counts those units as defenders.
- **Fix:**
  - Classify the evaluated threat group (air, ground, mixed).
  - Units that can hit nothing in it keep `(HOLD, anchor)`, and the "last stand" branch too.
  - They are left out of the defenders passed to `engagement.level` for that threat.
- **Ramifications:**
  - Against Oracles, Banshees and Mutalisks, only anti-air goes. The level drops when anti-air is scarce, so the squad may hold instead of engage. That's honest: Zealots never could help.
  - Mixed threats (drops, Void Ray plus Zealots) are unchanged.
  - Structures and workers are ground targets; cannon-rush clearing is unchanged.
- **Verify:** an Oracle-harass log shows only Stalkers moving (O3); M2 and M4 regressions hold.

**C3. Retreat stops shooting** (finding 1, second half).
- **Where:** `micro.py:retreat` l.122-127 shoots anything in range, including workers and buildings, when the weapon is ready.
- **Fix:** While retreating, shoot only enemies that fight back (`_fights_back`), and only if the unit's `movement_speed` (game data, python-sc2 `unit.py:322`; **VERIFY**: it excludes upgrades and buffs) is greater than every visible threat's that can hit it. Otherwise just run.
- **Ramifications:**
  - Less damage dealt while retreating from equal-speed or faster enemies (Stalker vs Stalker, anything vs Void Rays), and fewer units lost.
  - Retreats from slower units (Zealots without Charge, Immortals, Tempests) keep stutter-stepping.
  - Counterattack recalls (`send_home`) use the same function, so they change the same way.
- **Verify:** an offline test of the rule; the M5 staged counterattack 7 cases (recalls) still pass.

**C4. Launch gate: whole army, fresh intel, cooldown** (finding A).
- **Where:**
  - `army.py:_evaluate_launch` l.238-252
  - `engagement.py:attack_inputs` (only within 20 of squad or target, §4.5.2 as written)
- **Fix:** A launch also needs all three of these:
  1. **Whole army:** level ≥ `ATTACK_START` against the cached enemy army (`get_cached_enemy_army`, never expires), each unit weighted down with its age (`LAUNCH_CACHE_HALF_LIFE_S`, TUNE; **VERIFY** the age field on cached units, VERIFY_NOTES l.183).
  2. **Fresh intel:** enemy army value seen within `LAUNCH_INTEL_FRESH_S`. Otherwise the army Observer goes to look first, and after `LAUNCH_INTEL_WAIT_S` the launch goes ahead anyway, so the bot never deadlocks.
  3. **Cooldown:** no launch within `LAUNCH_AFTER_DEFEND_S` of a home fight. This removes the 12:57 launch / 13:02 recall.
- **Ramifications:**
  - **Fewer and later launches.** Against the built-in AI, which rarely hides, little changes. Against bots that turtle, attacks wait for real superiority, so ties at 60:00 become more likely. The §4.7 end-game gates still apply (45:00 lowers `ATTACK_START`).
  - **Phantom units:** the cache keeps units that died out of our vision. The age weighting limits the over-caution this causes.
  - **One extra sim call per launch evaluation**, inside §3's "≤ 2 per evaluation".
  - `AttackDecision` (pure) gains a cooldown input, so `test_attack_decision.py` gets new cases.
  - **It only works once B4 and O2 feed the cache.** In this game the cache held ~700 of ~3,600 enemy army value before the first attack.
- **Verify:** offline gate tests; M4 VeryHard × 10 per race (≥ 7 each); the Air batch logs fewer launches followed by a retreat within 60 s.

**C5. Out-range penalty in the fight level** (finding C; only if O1 shows the Tempests *were* in the sim's inputs while it read 8-10).
- **Where:** `engagement.py:level`. VERIFY_NOTES §11.3: positions are never passed to the core, and ares warns the sim is only reliable "when all units involved can attack each other".
- **Fix:** Add a pure function `outrange_penalty(own, enemy)`: the value share of enemy units that out-range all our units able to hit them (or that none of ours can hit), mapped to whole levels (`OUTRANGE_PENALTY_PER_SHARE`, TUNE). Subtract it from the sim level, floor 0. First, add a Tempest scenario to `test_engagement.py` (debug spawn, e.g. 8 Tempests + 6 Zealots vs 30 Stalkers + 4 Colossi) to measure the raw sim.
- **Ramifications:**
  - It shifts **every** gate: launch, continue, home defense, counterattack.
  - Against Terran, sieged tanks trigger it (arguably correct, but a behavior change against VeryHard Terran: re-run all of M4).
  - It needs tuning batches.
- **Verify:** an offline penalty test; the `test_engagement.py` scenario; M4 and M5 regressions.

**Phase 2 acceptance:**
- **Air batch, same seeds:** the Phase 1 baseline (built-in Protoss Air, VeryHard × 10) shows a lower value-lost / value-killed ratio and fewer launch-then-retreat-within-60-s events.
- **Regressions hold:** M1, M2/M3, M4 VeryHard × 10 per race (≥ 7 each), and the M5 staged 7/7.

---

## Phase 3: macro and tech (spec changes to §1, §4.2, §4.5.1)

**M1. One research queue per building** (findings E, 6, 7).
- **Where:** `production.py:_next_upgrade` l.151-160 is one global queue, "wait for the one in progress". It was added because ares's `UpgradeController`, given the full list, started every tech building at 5:00.
- **Fix:**
  - Split `UPGRADES_VS_P` / `UPGRADES_VS_ZT` into per-building chains (Forge / Twilight / Robotics Bay).
  - Each chain issues its next upgrade **only when its building already exists**. The Robotics Bay comes from Colossus production; the Twilight from a time or base gate (`TWILIGHT_FROM_S`, TUNE).
  - Blink goes, per D3.
- **Ramifications:**
  - Lance would have started ~6:30 instead of 14:26.
  - More gas on research from 6:00-10:00 means slightly fewer units in that window. The bot was gas-starved, so this is a real trade.
  - The "all tech at 5:00" regression stays prevented, because buildings aren't created for upgrades.
  - Make `_next_upgrade` a pure function so it can be tested offline.
- **Verify:** an offline chain test; logs show parallel research; M1 Hard × 10.

**M2. Mineral sink and a conditional 4th base** (finding D; needs D5).
- **Where:**
  - `constants.py:MAX_BASES = 3`
  - `economy.py:132` (`ExpansionController(to_count=min(to_count, MAX_BASES))`)
  - `production.py` l.209-212: the mineral-float spawner still respects the mix's proportions (Zealot 10%)
- **Fix:**
  - **4th base:** allow one when minerals ≥ `FOURTH_BASE_BANK` and gas income is below what production needs for `FOURTH_BASE_GAS_STARVED_S` (TUNE), only after 3 bases are saturated, and only while `DefensePlan.allow_expand`. Raise `PROBE_TARGET` accordingly.
  - **Sink:** when gas-starved with minerals ≥ `MINERAL_FLOAT_BANK`, Zealots may exceed their share, and with the AIR flag (M3) the bank first buys a Cannon and Battery per mineral line.
- **Ramifications:**
  - A 4th base spreads the army: more home threats and longer defense distances. The counterattack's "base under attack" checks see more bases.
  - Probes rise from 66 to ~75: slightly more step time and more supply in workers.
  - More Zealots reach supply 150 sooner, so the launch gate (now C4) is evaluated earlier.
  - Zealots are fodder against Tempests and good against ground armies.
- **Verify:** batches show unspent minerals at 10:00 well below this game's 2,670, with no M1 or M4 regression.

**M3. Tech detector: AIR_HARASS and capital-air flags** (findings 10, 8).
- **Where:** `detectors.py`. `Threat.AIR_HARASS` exists in `threat_flags.py:36`, but nothing raises it, and STATUS lists AIR_HARASS, DT, MACRO and TIMING as "not in any milestone".
- **Fix:**
  - Raise AIR_HARASS (STRUCTURE evidence) on a Stargate (P), Spire (Z) or Starport with a Tech Lab (T), per §4.2 and §4.4 rows 9 and 13.
  - Add a new CAPITAL_AIR threat (*spec change*) on a Fleet Beacon, Fusion Core, Greater Spire, or any capital unit seen (O2's lines).
  - Defense plan per §4.2: Forge now, then 1 Cannon + 1 Battery per mineral line.
  - Implement §5's "satisfied" state (detection at every mineral line stops forcing builds).
- **Ramifications:**
  - Every Stargate opener, common among bots, now costs ~900 minerals of static defense at 3 bases. That's standard play, and the floats show there's room.
  - The Forge comes earlier, which also helps upgrades.
  - `FlagStore` gains a state, so `test_threat_flags.py` gets cases.
  - `m3_checks.M3_EXPECTED_FLAGS` is unaffected (no cheese bot builds air), but built-in AI Air games will now raise it, which is the point.
- **Verify:** offline flag tests; built-in Protoss Air games raise both flags by the Stargate or Fleet Beacon sighting; M2/M3 cheese batches still show the correct flag 40/40.

**M4. Air switch / capital-air composition** (findings B, 7; needs D4).
- **Where:** `production.py:composition` is static per race; the docstring says "the air switch … come[s] later". `constants.py:ARMY_COMPOSITION_PCT`.
- **Fix:**
  - **Air switch:** while AIR_HARASS is active and enemy air is ≥ 30% of the cached enemy army value (§4.5.1), shift the share to anti-air.
  - **Capital air:** while CAPITAL_AIR is active, cut Colossus to ~0-10% and add the D4 counter unit.
  - **Switching back:** return when the cached enemy air falls below the threshold for `AIR_SWITCH_HOLD_S` (hysteresis).
- **Ramifications:**
  - **Tech cost:** a Stargate or Fleet Beacon for option (b), Blink micro for option (a).
  - **A weak window** while the switch completes.
  - **False triggers:** one Oracle must not swing the army, which is why the share threshold and hysteresis exist.
  - **ProductionController adds the new production buildings itself.** Check `MAX_PRODUCTION_STRUCTURES = 12`.
  - **Option (b) takes Skytoss off the cut list:** a §7 change.
- **Verify:** Air batch wins and value ratio against the Phase 2 numbers; M4 VeryHard Protoss (non-air builds) doesn't regress.

**Phase 3 acceptance:** the Air batch (same seeds) beats the Phase 2 numbers on wins and value ratio, and every regression holds.

---

## Later (not needed for this loss)
- **Batteries in the fight model (#4).** Add each Battery's restorable shields (energy × restore rate from game data) as extra shield HP, for both sides. It touches every gate, like C5.
- **Low-HP pursuit (#5).** `ShootTargetInRange(extra_range=…)` for targets one volley from death, plus shared focus across a group. Chase only when faster and the local sim is safe. First settle with a log whether hurt enemies actually escape (UNCLEAR today).
- **Blink micro (#6).** Blink in on out-rangers when committed, blink back for shieldless Stalkers. Needs it off the cut list, and is likely part of D4 (a).

## Verification and rollout

**Batches use the existing runner.** `scripts/run_matches.py` with `--game-seed` replays the same games on two commits (an A/B test):

```
poetry run python scripts/run_matches.py --difficulty VeryHard --race Protoss --build Air --map all --total 10 --game-seed 7000
```

What each part does:
- `poetry run` runs it inside the project's Python environment.
- `--difficulty VeryHard --race Protoss --build Air` picks the built-in Protoss AI's air build, the closest local stand-in for this opponent.
- `--map all --total 10` plays 10 games, cycling through the 7 pool maps.
- `--game-seed 7000` fixes the randomness, so the same 10 games can be replayed after a change.

**Steps:**
1. Run this on the current code first, as the baseline, then after each phase.
2. **Full regression after each phase:** STATUS.md "Test commands" lists them: M1, M2/M3, M4, M5 staged, plus the offline scripts. That's about 5-7 hours of games on 4 cores.
3. **Before each upload:** rebuild the zip on Python 3.12, run `ladder_env_test.py`, upload, then follow the games with `ladder_watch.py`.

**Rollout:**
1. Phases 0 + 1 ship together after M6 passes. They are low-risk and make the next ladder losses readable.
2. Phase 2 follows in a second upload.
3. Phase 3 needs D4 and D5 first.

**Docs:** each phase updates DESIGN.md (approved edits only), VERIFY_NOTES (the VERIFY items above and the evidence), and STATUS.md.
