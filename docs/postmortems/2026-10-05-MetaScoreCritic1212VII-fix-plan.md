# M7 plan: fixes from the MetaScoreCritic1212VII postmortem

> **Where M7 is executed from:** `docs/M7_PLAN.md`, which has the file-level steps and the final decisions:
> - D7 and D11 accepted;
> - D9: respond to capital air for every race in M7;
> - D10: High Templar and Archons allowed (Storm and Archon splash for PvZ; small Archon shares vs Terran bio and vs Zealot-heavy Protoss; Archons are not used as anti-air, so the air switch only raises Stalkers).
>
> Where this file differs (the D9 "respond vs Protoss only" recommendation, D10's Void Ray/Phoenix suggestion), `docs/M7_PLAN.md` wins.

Source: `docs/postmortems/2026-10-05-MetaScoreCritic1212VII.md` (finding numbers below match it). Code references are at `8036973`.

## Ground rules this plan follows
- **The spec decides.** Items marked *spec change* need your approval of a DESIGN.md edit before any code is written. Items marked *bug* bring the code back to what DESIGN.md already says, so they need no spec change. The DESIGN.md edits are listed at the end.
- **One phase at a time.** Each phase ends with evidence for its acceptance criteria, then stops.
- **New API uses get checked first.** Every API this plan leans on is checked in the ares or python-sc2 source and recorded in `docs/VERIFY_NOTES.md` before use (marked **VERIFY** below).
- **No hard-coded numbers.** Thresholds go in `bot/constants.py` as TUNE values, and unit stats (ranges, speeds, costs) are read from game data. The AIE maps carry newer balance data than the 4.10 engine.
- **M6 is still open.** The 20-ladder-game check on the uploaded zip has 10 games left, and a new upload restarts the count. Develop on a branch now; upload only after M6 passes, unless you say otherwise.
- **This container can't run games.** It has no `~/StarCraftII`, so every batch below needs SC2 installed per the README (~4 GB) or another machine.

## Decisions

| # | Question | State |
|---|---|---|
| D1 | Drop the §4.3 PvP 4:30 Hallucinated Phoenix scout | **Decided: drop.** Phase 1 (B5). |
| D2 | Drop the §4.3 PvZ ~6:30 Hallucinated Phoenix scout (same problem: no Sentry in the vs-Z mix) | **Decided: drop.** Phase 1 (B5). |
| D3 | Blink | **Decided: Blink Stalkers are used**, for basic combat and against capital ships. Blink micro comes off the v1 cut list; research and micro are Phase 3. |
| D4 | The answer to capital air | **Decided: Blink Stalkers in every matchup, plus Void Rays and/or Tempests against capital air in PvP.** Phase 4 (E3). "Skytoss" on the cut list narrows to "Carriers / Skytoss as the main army". |
| D5 | A 4th base when gas-starved with a mineral bank | **Decided: yes.** Phase 4 (E1). |
| D6 | Milestone label | **Decided: M7.** M4's acceptance evidence stays as recorded. |
| D7 | Twilight Council research order: Blink first everywhere, or Charge first vs Z? | Open. Recommend: Blink first vs P and T; Charge first vs Z (its mix leans on Zealots), then Blink. |
| D8 | Void Rays or Tempests first against enemy Tempests | Open; settled by measurement (E0). My expectation is in the box below. |
| D9 | Capital air from other races (Battlecruisers, Brood Lords) | Open. Recommend: **detection and measurement for all races, the capital-air army response vs Protoss only** in M7. Exact rules in E2 ("What D9 means exactly"). |
| D10 | §4.5.1's air switch says "add Archons", but High Templar are cut, so Archons can't be made | Open. Recommend: replace Archons with Blink Stalkers plus Void Rays vs P and T, and Phoenix vs Z (the spec already allows Phoenix vs Z). Mutalisks are light, and the Void Ray's bonus is against armored, so Void Rays are a poor answer to Zerg air. |
| D11 | M7's target against built-in Protoss Air (VeryHard × 10) | Open. To be proposed after the baseline batch (Phase 1). |

**D8, my expectation (to be checked by measurement).** For enemy Tempests specifically, Void Rays should be the better first answer:
- **Speed:** Void Rays are faster than Tempests, so they can catch a Tempest bot that kites. Our Stalkers never caught one in this game.
- **Damage:** the Tempest's air bonus is against *massive* units. Void Rays aren't massive, so they don't take it. The Void Ray's bonus is against *armored*, and Tempests are armored.
- **Tech:** Void Rays need only a Stargate. Tempests also need a Fleet Beacon (more gas, about a minute later).
- **Tempest against Tempest** is an even trade at equal range, so the side that already has more wins. Against this opponent that's them.

Tempests are the better answer to Carriers, Battlecruisers and Brood Lords, where their range and anti-massive bonus pay off. These are standard-patch values, and the AIE maps may differ; E0 measures it on the real map data before E3 sets the shares.

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
| 1 | B5 Drop the PvP and PvZ hallucination scouts (D1, D2) | 8 | spec change (decided) | S |
| 2 | C1 Out-ranged rule and hold-point fallback | 2, B | spec change | M |
| 2 | C2 Only units that can hit the threat answer it | 3, 10 | spec change | S |
| 2 | C3 Retreat stops shooting | 1 | spec change | S |
| 2 | C4 Launch gate: whole army, fresh intel, cooldown | A | spec change | M |
| 2 | C5 Out-range penalty in the fight level (only if O1 confirms) | C | spec change | M |
| 3 | K1 One research queue per building (Blink, Lance in parallel) | E, 6, 7 | spec change | S |
| 3 | K2 Blink micro | 6, 2, 5, B | spec change (decided) | M |
| 4 | E0 Staged test: what beats Tempests on the AIE data | B, D8 | test only | M |
| 4 | E1 Mineral sink and conditional 4th base | D | spec change (decided) | M |
| 4 | E2 Tech detector: AIR_HARASS and CAPITAL_AIR | 10, 8 | spec change | M |
| 4 | E3 Capital-air response: composition and air-unit micro | B, 7 | spec change (decided) | L |
| later | Batteries in the fight model (#4); low-HP pursuit by ground units (#5) | 4, 5 | spec change | M each |

Why this order:
- Phase 0 is cheap and lets every later phase be measured. It also settles C, which decides whether C5 is needed.
- Phase 1 needs no spec change and fixes the code that matches the spec worst.
- Phase 2 stops the bleeding: about 26k of army value was thrown away this game.
- Phase 3 (Blink) helps in every matchup, and it's half of the capital-air answer.
- Phase 4 needs the detector to trigger the switch, and the 4th base's gas to pay for Void Rays and Tempests.
- E0 is a dev-only script and can run as early as you like.

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
- **Ramifications:** None for behavior. These sightings become E2's trigger later.
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

**B5. Drop the PvP and PvZ hallucination scouts** (D1, D2).
- **Where:**
  - DESIGN.md §4.3, the PvP "~4:30" and PvZ "~6:30" Hallucinated Phoenix rows
  - `constants.py:HALLUCINATION_AT_S` (`"Protoss"`, `"Zerg"`)
  - `scout_planner.py:_hallucinate` (l.514, the matchup branch)
- **Fix:** Remove both entries. Kept as they are:
  - the PvT 5:30 row;
  - the stale-main branch, which needs an existing Sentry, so in practice it only fires vs T;
  - the §4.7 hunt Phoenix.
- **Ramifications:** No behavior change in practice: neither row ever fired, because the vs-P and vs-Z mixes have no Sentry. The spec and code stop disagreeing. `test_scout_abilities.py` is unaffected; it tests the ability, not the schedule.
- **Verify:** M3 checks (`test_m3_checks.py`) pass; M2/M3 cheese batches still show the correct flag 40/40.

**Phase 1 acceptance:**
- **Wins hold:** M1 Hard × 10, M2/M3 cheese bots × 10 each, and M4 VeryHard × 10 per race stay at their recorded levels.
- **Baseline batch for D11:** the A/B vs built-in Protoss Air shows no reinforcement-at-retreat lines and fewer HOLD deaths far from the hold point. Its numbers become the baseline for D11.

---

## Phase 2: combat (spec changes to §4.5.2 and §3 micro)

**C1. Out-ranged rule and hold-point fallback** (finding 2, part c).
- **Where:**
  - `micro.py:fight`, which steps back only when *we* out-range the threat (l.~75)
  - `army.py` anchor selection (`hold_point` / `_rally_point`)
- **Fix, unit level:**
  - **Out-ranged:** a unit that is not committed (HOLD, MOVE or RETREAT intent) and is inside the reach of a visible enemy it can't reach backs out with ares `KeepUnitSafe` on the influence grid.
  - "Can't reach" means it can't hit that enemy at all, or that enemy's range minus ours is at least `OUTRANGED_MARGIN` (TUNE). Ranges come from game data (`air_range` / `ground_range`).
- **Fix, squad level:** when out-rangers that home defense can't beat (level < engage threshold) cover the anchor, the anchor moves to a fallback point out of their reach, toward the main, by `HOLD_FALLBACK_STEP` (TUNE). The hold point already shifts like this for Cannons (`HOLD_SHIFT_*`).
- **Ramifications:**
  - **It applies to everything that out-ranges us:** sieged tanks, Lurkers, Brood Lords, Liberators, Tempests, Carriers, Planetary Fortresses. Uncommitted units back off all of them, which is right unless the squad has decided to fight.
  - **Committed squads are unchanged.** FIGHT (ATTACK squad, engaged home defense) keeps today's behavior until K2, when committed Blink Stalkers blink onto out-rangers instead of walking in under fire.
  - **A base under siege can be given up.** Tempests out-range Cannons, so the army keeps its units but may lose that base. Phases 3-4 are what turn that saved army into a fight it can win.
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
  - After K2, a retreating Blink Stalker blinks away first.
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
  - The sim doesn't model Blink either, so once K2 lands, Blink Stalkers read weaker than they are. That's conservative, not dangerous.
  - It needs tuning batches.
- **Verify:** an offline penalty test; the `test_engagement.py` scenario; M4 and M5 regressions.

**Phase 2 acceptance:**
- **Air batch, same seeds:** against the Phase 1 baseline, a lower value-lost / value-killed ratio and fewer launch-then-retreat-within-60-s events.
- **Regressions hold:** M1, M2/M3, M4 VeryHard × 10 per race (≥ 7 each), and the M5 staged 7/7.

---

## Phase 3: Blink (spec changes to §3 micro, §4.5.1, §7 cut list)

**K1. One research queue per building** (findings E, 6, 7).
- **Where:** `production.py:_next_upgrade` l.151-160 is one global queue, "wait for the one in progress". It was added because ares's `UpgradeController`, given the full list, started every tech building at 5:00.
- **Fix:**
  - Split `UPGRADES_VS_P` / `UPGRADES_VS_ZT` into per-building chains: Forge (weapons/armor), Twilight (Blink/Charge, order per D7), Robotics Bay (Extended Thermal Lance).
  - Each chain issues its next upgrade **only when its building already exists**, so upgrades never create buildings.
  - The Twilight Council gets its own schedule item (`TWILIGHT_AT_S`, TUNE; earlier vs P, since Blink is now core).
  - The Robotics Bay keeps coming from Colossus production.
- **Ramifications:**
  - In this game, Blink would have started ~8:20 (or earlier with the new Twilight timing) instead of 12:57, and Lance ~6:30 instead of 14:26.
  - More gas on research from 6:00-10:00 means fewer units in that window. The bot was gas-starved, so E1's 4th base matters here too.
  - The "all tech at 5:00" regression stays prevented.
  - Make `_next_upgrade` a pure function so it can be tested offline.
- **Verify:** an offline chain test; logs show parallel research; M1 Hard × 10.

**K2. Blink micro** (findings 6, 2, 5, B; D3).
- **Where:** a new `micro.blink(...)` used from `micro.fight` and `micro.retreat`, plus the army's commit state.
- **Facts checked:**
  - ares has no Blink behavior. Its ability tracker's Blink entry is commented out.
  - Blink readiness is `AbilityId.EFFECT_BLINK_STALKER in unit.abilities`. `Unit.abilities` is filled each step and leaves out abilities on cooldown (VERIFY_NOTES, python-sc2 `unit.py:598`).
  - The command goes through ares `UseAbility` or `unit(AbilityId.EFFECT_BLINK_STALKER, point)`.
- **Fix, three uses:**
  1. **Blink back** (basic combat; standard and high-value against bots): when shields fall below `BLINK_BACK_SHIELD_FRACTION` (TUNE) and an enemy is targeting or close to the unit, blink toward the squad's rear. The landing spot must be safe on the influence grid (ares safe-spot query, **VERIFY** the accessor) and in our vision.
  2. **Blink in on out-rangers when committed** (vs Tempests, Siege Tanks, Colossi, Brood Lords): when the squad is in FIGHT and an out-ranger (C1's test) is within blink range plus weapon range, blink to a point inside weapon range of it, at most `BLINK_IN_MAX` Stalkers per out-ranger per second (TUNE), so the group arrives together rather than one by one.
  3. **Blink to finish** a fleeing target that one volley would kill, only when the landing spot is safe and the local sim level is ≥ engage (the guarded form of #5).
- **Never blink:**
  - into fog (unseen cells),
  - onto a cell with ground influence above `BLINK_DANGER_MAX` (TUNE),
  - up a cliff without vision of the landing spot (terrain height tells which side is higher).
- **Ramifications:**
  - **The biggest change to Stalker behavior so far.** Every matchup's fights change, so the full M4 regression is needed.
  - **More commands per step** (a few blink commands a second at most), with no new path queries. The safe-spot lookup is one grid read.
  - **Interactions:**
    - C1: uncommitted units still walk out of range; blink back covers the urgent cases.
    - C3: blink back replaces stutter-step when available.
    - Counterattack: HARASS Stalkers get blink back.
  - **The sim doesn't model Blink**, so fight levels stay conservative.
  - **Bait risk:** blink-to-finish into a bot's retreating army. That's why it needs the safe-landing and local-sim gates.
- **Verify:**
  - An offline test of the blink decision function (fake units, shield fractions, ranges, grid values).
  - An in-game staged test: debug-spawned Stalkers with Blink vs Tempests and vs Stalkers, with blink counts and value traded in the log.
  - Air batch and M4 VeryHard × 10 per race.

**Phase 3 acceptance:** Blink is researched by its schedule time in every PvP game of the batches. The Air batch (same seeds) improves on Phase 2's value ratio, and all regressions hold.

---

## Phase 4: economy and capital-air response (spec changes to §1, §4.2, §4.4, §4.5.1, §5)

**E0. Staged test: what beats Tempests on the AIE balance data** (D8).
- **Where:** a new dev-only `scripts/test_air_counters.py` (not in the ladder zip), modeled on `test_counterattack.py` (scripted `StagedEnemy`) and `test_engagement.py` (debug spawn).
- **Fix:** On one pool map, the enemy gets N Tempests that kite (hold range, back off from anything closing in). Our side gets the same resource value of each candidate group in turn:
  - Void Rays
  - Tempests
  - Stalkers without Blink
  - Blink Stalkers (once K2 exists)
  - Void Rays + Blink Stalkers

  Record value lost and killed, and time to kill. Unit costs come from game data. Run each case 5 times (fights vary).
- **Ramifications:** Dev-only, no bot behavior change. It settles D8 with numbers from the real map data instead of the standard-patch values in the D8 box.
- **Verify:** the table goes into VERIFY_NOTES "M7 findings".

**E1. Mineral sink and a conditional 4th base** (finding D; D5 decided).
- **Where:**
  - `constants.py:MAX_BASES = 3`
  - `economy.py:132` (`ExpansionController(to_count=min(to_count, MAX_BASES))`)
  - `production.py` l.209-212: the mineral-float spawner still respects the mix's proportions (Zealot 10%)
- **Fix:**
  - **4th base:** allow one when minerals ≥ `FOURTH_BASE_BANK` and gas income is below what production needs for `FOURTH_BASE_GAS_STARVED_S` (TUNE), only after 3 bases are saturated, and only while `DefensePlan.allow_expand`. Raise `PROBE_TARGET` accordingly.
  - **Sink:** when gas-starved with minerals ≥ `MINERAL_FLOAT_BANK`, Zealots may exceed their share. With AIR_HARASS (E2) active, the bank first buys a Cannon and Battery per mineral line.
- **Ramifications:**
  - A 4th base spreads the army: more home threats and longer defense distances. The counterattack's "base under attack" checks see more bases.
  - Probes rise from 66 to ~75: slightly more step time and more supply in workers.
  - More Zealots reach supply 150 sooner, so the launch gate (C4) is evaluated earlier.
  - Zealots are fodder against Tempests and good against ground armies.
  - Void Rays, Tempests and Blink all need the gas, so E3 depends on this.
- **Verify:** batches show unspent minerals at 10:00 well below this game's 2,670, with no M1 or M4 regression.

**E2. Tech detector: AIR_HARASS and CAPITAL_AIR** (findings 10, 8; D9).
- **Where:** `detectors.py`. `Threat.AIR_HARASS` exists in `threat_flags.py:36`, but nothing raises it, and STATUS lists AIR_HARASS, DT, MACRO and TIMING as "not in any milestone".
- **Fix:**
  - **AIR_HARASS** (STRUCTURE evidence): raised on a Stargate (P), Spire (Z) or Starport with a Tech Lab (T), per §4.2 and §4.4 rows 9 and 13.
  - **CAPITAL_AIR** (new threat, race-agnostic per D9). See "What D9 means exactly" below.
  - **Defense plan for AIR_HARASS** per §4.2: Forge now, then 1 Cannon + 1 Battery per mineral line, with §5's "satisfied" state (detection at every mineral line stops forcing builds).
- **Ramifications:**
  - Every Stargate opener, common among bots, now costs ~900 minerals of static defense at 3 bases. That's standard play, and the floats show there's room.
  - The Forge comes earlier, which also helps upgrades.
  - `Threat` gains a member and `FlagStore` a state, so `test_threat_flags.py` gets cases. The opponent memory's `MEMORY_CHEESE` list is unaffected (CAPITAL_AIR isn't cheese).
  - `m3_checks.M3_EXPECTED_FLAGS` is unaffected (no cheese bot builds air), but built-in AI Air games now raise both flags, which is the point.
- **Verify:** offline flag tests; built-in Protoss Air games raise AIR_HARASS at the Stargate sighting and CAPITAL_AIR at the Fleet Beacon; M2/M3 cheese batches still show the correct flag 40/40.

**What D9 means exactly** (CAPITAL_AIR, the same rules for every race):
1. **What counts.** Capital air is an explicit list, `CAPITAL_AIR_TYPES` in `constants.py`:
   - Protoss: Tempest, Carrier, Mothership.
   - Terran: Battlecruiser.
   - Zerg: Brood Lord, including the cocoon it morphs from.

   Everything else that flies (Void Ray, Phoenix, Oracle, Viking, Liberator, Banshee, Mutalisk, Corruptor, Viper) is "air" for the §4.5.1 air switch, not capital air. The list is explicit because python-sc2 reports a Carrier as unable to attack: its interceptors do the damage, so it has no weapon in the game data (`unit.py:230-273` special-cases only Battlecruisers and Oracles). A test like "flying and can attack" would miss Carriers.
2. **Two states:**
   - **WARNING:** an unlocking building is seen: Fleet Beacon (P), Fusion Core (T) or Greater Spire (Z). It's STRUCTURE evidence, so per §5 it never expires on a timer, only when the building is seen destroyed. A building alone isn't proof of capital ships: a Fleet Beacon also unlocks Phoenix and Void Ray upgrades.
   - **ACTIVE:** the capital air the bot has seen recently is worth at least `CAPITAL_AIR_MIN_VALUE` (TUNE; about one unit's worth). It ends `CAPITAL_AIR_UNIT_TTL` after the value drops below that.
3. **How the enemy's air is measured.** Every intel tick, from ares's army cache (every enemy unit seen and not known dead):
   - **capital air value:** the cost of cached units in the list;
   - **air value:** the cost of cached flying fighters (flying, not support, and able to attack or in the capital list);
   - **air share:** air value divided by the whole cached army value.

   Costs come from game data (`calculate_unit_value`). A cached unit counts at full value only if it was seen within `CAPITAL_AIR_FRESH_S` (TUNE), using python-sc2's `Unit.age`, the seconds since the bot last saw it (`unit.py:471`). Older entries fade, because the cache keeps units that died out of our sight.
4. **What gets logged.**
   - **State changes:** an `INTEL capital air WARNING/ACTIVE <race> value=… air share=…` line.
   - **Game record:** a `capital_air` entry with the race, first WARNING and ACTIVE times, and peak values.
   - **Effect:** every ladder game shows what the enemy flew and when, even where M7 doesn't respond to it.
5. **What the bot does in M7:**
   - **Vs Protoss:**
     - **WARNING:** prepare. One Stargate goes down and Blink research moves ahead in the Twilight chain.
     - **ACTIVE:** the full E3 mix: Colossi cut, Void Rays/Tempests at E0's shares, more Stalkers.
   - **Vs Terran and Zerg:** the flag and measurements only, with no capital-air mix. The general rules still apply:
     - the §4.5.1 air switch at ≥ 30% air share (D10);
     - C1 out-ranged handling (Brood Lords out-range Stalkers; Battlecruisers don't);
     - C4's launch gate counts them in the cached army;
     - K2's blink-in covers Brood Lords.
6. **Why not respond vs T and Z in M7.**
   - **No measurement:** E0 only tests answers to Tempests.
   - **No ladder losses to them yet.**
   - **A wrong counter is expensive:** Corruptors guard Brood Lords against air, and Battlecruisers can teleport away.

   After M7, E0 gets Battlecruiser and Brood Lord cases, and the logged ladder data shows how often these opponents fly them.

**E3. Capital-air response: composition and air-unit micro** (findings B, 7; D4, D8, D10).
- **Where:**
  - `production.py:composition` is static per race; the docstring says "the air switch … come[s] later".
  - `constants.py:ARMY_COMPOSITION_PCT`, `ARMY_PRIORITY`, `MAX_PRODUCTION_STRUCTURES`.
  - `micro.py:KITERS` and targeting.
- **Fix, composition:**
  - **CAPITAL_AIR active, enemy Protoss:** Stalker share up, Colossus down to `CAPITAL_AIR_COLOSSUS_PCT` (TUNE, ~0-10%), and Void Rays and/or Tempests at shares set from E0's result.
  - **Air switch** (§4.5.1: enemy air ≥ 30% of the cached army value, with AIR_HARASS active): Stalker share up, plus Void Rays in place of Archons (D10).
  - **Switching back:** return to the race's normal mix when the cached enemy air falls below the threshold for `AIR_SWITCH_HOLD_S` (hysteresis), so one Oracle doesn't swing the army.
  - ares's ProductionController adds the Stargates and Fleet Beacon the mix needs. Check `MAX_PRODUCTION_STRUCTURES = 12`.
- **Fix, air-unit micro:**
  - **Void Rays:** target capital and armored units first. Use Prismatic Alignment when ≥ `VOIDRAY_ALIGN_MIN_ARMORED` (TUNE) armored enemies are in range (**VERIFY** the ability's id and availability under AIE data via `unit.abilities`; ares lists `EFFECT_VOIDRAYPRISMATICALIGNMENT`). They're out-ranged by Tempests, so under C1 they close in only when committed.
  - **Tempests:** added to `KITERS` (they out-range almost everything), and they target massive units first.
  - Flyers already retreat on the air grid (`micro.retreat`).
- **Ramifications:**
  - **Tech cost and a weak window:** a Stargate (and a Fleet Beacon if Tempests) plus the first units take ~1.5-2 min of reduced ground production.
  - **A mixed-speed army:** Void Rays and Blink Stalkers are faster than Immortals and Colossi. The ares spatial groups already split them, and the regroup rule (`REGROUP_FRACTION`) waits for stragglers, which slows the squad when it goes out.
  - **The sim handles air units:** they pass through `engagement.level` with no change.
  - **False triggers:** a single Tempest is real evidence, but the switch back needs the hysteresis.
  - **The spec changes:** "Skytoss" on the §7 cut list narrows; §1's "Beyond v1" line changes.
- **Verify:** E0 numbers guide the shares; Air batch wins and value ratio beat Phase 3; M4 VeryHard Protoss (non-air builds) doesn't regress.

**Phase 4 acceptance:** the Air batch (same seeds) meets D11's target, and every regression holds.

---

## Later (not needed for this loss)
- **Batteries in the fight model (#4).** Add each Battery's restorable shields (energy × restore rate from game data) as extra shield HP, for both sides. It touches every gate, like C5.
- **Low-HP pursuit by ground units (#5).** `ShootTargetInRange(extra_range=…)` for targets one volley from death, plus shared focus across a group. Chase only when faster and the local sim is safe. First settle with a log whether hurt enemies actually escape (UNCLEAR today). K2's blink-to-finish covers the Stalker case.

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
1. Run this on the current code first (the baseline), then after each phase.
2. **Full regression after each phase:** STATUS.md "Test commands" lists them: M1, M2/M3, M4, M5 staged, plus the offline scripts. That's about 5-7 hours of games on 4 cores.
3. **Before each upload:** rebuild the zip on Python 3.12, run `ladder_env_test.py`, upload, then follow the games with `ladder_watch.py`.

**Rollout:**
1. **M7 kickoff:** the DESIGN.md edits below, for your approval (the decided items can go in at once).
2. **Phases 0 + 1** ship together after M6 passes. They are low-risk and make the next ladder losses readable.
3. **Phase 2** goes in a second upload.
4. **Phase 3** goes in a third.
5. **Phase 4** goes in a fourth. E0 can run any time, and it settles D8 before E3 starts.

**Docs:** each phase records its VERIFY items and evidence in VERIFY_NOTES ("M7 findings", "M7 acceptance evidence") and updates STATUS.md.

## DESIGN.md edits for M7

Decided items, ready to write:
- **§4.3:** delete the PvP "~4:30 Hallucinated Phoenix" and PvZ "~6:30 Hallucinated Phoenix" rows (D1, D2).
- **§1 Win condition:** "macro to 3 bases" becomes "3 bases, and a 4th when gas-starved with a mineral bank" (D5). "Beyond v1" keeps Carriers and Skytoss-as-main-army only.
- **§7:**
  - add the M7 row (deliverable: Phases 0-4; acceptance: each phase's criteria above, D11's target, and no crash or time-out in the first 20 ladder games after each upload);
  - cut list: remove "Blink micro"; "Skytoss" becomes "Carriers and Skytoss as the main army (Void Rays/Tempests only as the capital-air answer)" (D3, D4, D6).

Written with each phase, for approval then:
- **§3 `micro.py`:** the out-ranged rule (C1), retreat shooting (C3), and Blink (K2).
- **§4.5.2:**
  - launch inputs: whole cached army, fresh intel, cooldown after a home fight (C4);
  - which units answer a threat (C2);
  - the hold-point fallback (C1);
  - the out-range penalty, only if O1 confirms it (C5).
- **§4.2 and §4.4:** detector rows 9 and 13 become real; add a capital-air row (E2).
- **§4.5.1:**
  - per-building research chains and the Twilight order (K1, D7);
  - the air switch with Void Rays in place of Archons (D10);
  - the capital-air mix (E3).
- **§5:** `Threat.CAPITAL_AIR` and its expiry (E2).
- **§8:** the new telemetry fields (O1-O3).
