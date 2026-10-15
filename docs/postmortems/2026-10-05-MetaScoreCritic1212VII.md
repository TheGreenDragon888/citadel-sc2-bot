# Postmortem: Citadel vs MetaScoreCritic1212VII (Protoss), UltraloveAIE_v2, 2026-10-05

Defeat at 16:14. Opener C_2GateRobo; no flags except a 45 s false CANNON_RUSH (1:30-2:15) and ARMY_OUT_OF_POSITION at 14:59. The opponent played Forge-first cannon expand into Stargate (2:57), Fleet Beacon (5:42) and a Zealot/Immortal/Void Ray/**Tempest** army on 5 bases.

**Method.** Tracker events (births, deaths with killer, upgrades, player stats, position samples) were read with sc2reader 1.9.0, patched in a scratch venv to accept a bot replay. Command events (every Citadel move/attack order, with the units it went to) were read with Blizzard's s2protocol (build 75689). Both were cross-referenced with the bot's stdout log and the code at `8036973`. No matches were run.

**Why the game was lost.** Tempests killed 95 of the 128 army units Citadel lost (20,500 of ~26,400 resources). Citadel killed **0 of 16** Tempests. Citadel had the bigger army until 12:37 (stats: 5,625 vs 3,500 at 8:34; 8,875 vs 8,375 at 12:37), then lost it in two ways:
- **Attacks:** 4 attacks, each launched at level 8-10 into an army the bot had not seen. Losses: Citadel 10,150, opponent 4,650 (8:40-12:08).
- **Home defense:** the army held a position inside Tempest range. Losses: Citadel 15,750, opponent 5,600 (12:37-15:00), about one Stalker every 2-3 s.

## Summary

| # | Issue | Verdict | Impact on this loss | Scope | Milestone |
|---|---|---|---|---|---|
| 1 | Retreat isn't unanimous | BUG | low | S | M4 |
| 2 | Straggler engagements (~11:00) | BUG | **high** | S-M | M4 |
| 3 | Target-type mismatch | DESIGN GAP (partly right) | med | S | M4 |
| 4 | Shield Batteries ignored | DESIGN GAP | low | M | M4 |
| 5 | Low-HP enemies escape | UNCLEAR | low | S | M4 |
| 6 | No Blink research | NOT AN ISSUE as stated / DESIGN GAP | med | S (queue), M (micro) | M1 / post-v1 |
| 7 | Colossus usage | DESIGN GAP (positioning: NOT AN ISSUE) | med | S | M1 (§4.5.1) |
| 8 | No mid-game scouting | DESIGN GAP | **high** | M | M3 |
| 9 | Slow natural | NOT AN ISSUE | low | S | M1 |
| 10 | Early Oracle harass | NOT AN ISSUE (damage) / DESIGN GAP (detector) | low | S | M2/M3 |
| A | *Not on your list:* launch gate blind to the enemy army | DESIGN GAP | **high** | M | M4 |
| B | *Not on your list:* no answer to mass Tempest | DESIGN GAP | **high** | L | §4.5.1 / post-v1 |
| C | *Not on your list:* sim says "win" vs out-ranging air | UNCLEAR | **high** | S (log), M (fix) | M4 |
| D | *Not on your list:* 1.4-2.9k mineral float, gas-starved, 3-base cap | DESIGN GAP | med | M | M1 |
| E | *Not on your list:* one research at a time across all buildings | DESIGN GAP | med | S | M1 |
| F | *Not on your list:* missing observability | finding | n/a | S | M5 (telemetry) |

## 1. Retreat isn't unanimous [9:32]
- **Evidence:** `ENGAGE 09:32 retreat level=4` and `ARMY reinforcements out at 09:32: 3 units, 10 supply` are logged in the same tick. The 3 units (Stalkers 82051074 and 107741189, Colossus 100663299) attack-moved toward the old fight at (87-95, 63-72) and died at 9:48, 9:55 and 9:57. Retreating units also kept shooting: after the retreat, Stalker 97779713 shot a Probe (9:34.4) and only moved home at 9:37.8. Colossus 108003330 shot the Nexus (9:33.5), then alternated move and attack-Zealot until a Tempest killed it at 9:39.6.
- **Cause:** `army.py:_decide` (l.232-234) calls `_reinforce(defenders)` right after `_evaluate_attack` flipped the state to GATHER. `attack_center` (l.257) is never cleared, so the new REINFORCE group gets `(MOVE, attack_center)` (l.564) and, since `_reinforce` only runs during ATTACK, it is never recalled. Separately, `micro.retreat` (`micro.py:122-127`) fires at anything in range, including workers and buildings, whenever the weapon is ready.
- **Verdict:** BUG (the first part). Shooting while retreating is an undesigned implementation choice.
- **Take:** Yes, make the retreat unanimous. Skip `_reinforce` after a flip, clear `attack_center` on retreat, and send REINFORCE home on any retreat or recall. In retreat micro, shoot only units that fight back, and only when the unit is faster than the nearest threat. Never shoot workers or buildings.
- **Scope:** S, M4 follow-up. The current M4 design doesn't cover this; it's an implementation bug.

## 2. Straggler engagements [~11:00]
- **Evidence:** After the 10:51 retreat, `DEFEND 11:08 engage (level 9) vs VOIDRAY`. At 11:11.5-11:13.1, 8 Stalkers were ordered to attack-move to the hold point (113,108). All 8 died to Tempests between 11:13 and 11:32 (7 of them with that order still their last). Their death positions moved **away** from the hold point: (106,102), (107,99), (103,100), (101,97), (97,100), (92,99), (89,103), (88,98). The same pattern bled ~50 Stalkers from 13:05 to 15:00. Position samples put Stalkers 8-13 cells from the nearest Tempest: inside its ground range (10), outside their own (6).
- **Cause:** Units heading back to a hold point use **attack-move** (`army.py:635`, `attack=mode != MOVE`). When a Tempest shoots one, the engine's auto-acquire makes it chase, one unit at a time. `micro.move` then won't re-issue the order, because the order's target is still the hold point (`micro.py:142`, `MOVE_REISSUE_DIST`). Separately, FIGHT micro engages any visible enemy within 12 of *each unit*, not just the threat being defended. Stalker 101449730 ran at Tempests near (81-89, 90-98) during a fight against a Zealot at (99,121), and died at 11:32.
- **Verdict:** BUG. It breaks §4.5.2 "home defence … never leaves the battery radius".
- **Take:** Regrouping is right but not enough. (a) Use a plain move, not attack-move, back to the hold point. (b) Add an "out-ranged" rule: a unit taking fire from something it can't reach backs out of that enemy's range unless the squad decides to commit. (c) If the enemy out-ranges the hold point, move the hold point back.
- **Scope:** S for (a), M for (b) and (c). M4 follow-up; the current M4 design wouldn't fix it.

## 3. Target-type mismatch
- **Evidence:** Partly right. Immortals and Zealots chased the Oracle twice (6:07-6:16 and 7:22-7:33). At 12:42, `engage vs VOIDRAY` sent all 39 defenders, including Colossi, Immortals and Zealots, to the Void Ray's position. Four Colossi died to Tempests there (12:44-12:58). But the enemy army was **not** all-air: it had 56 Zealots and 14 Immortals, and Colossi killed 26 Zealots.
- **Cause:** `army.py:_home_defense` sets `defend_target` to the nearest threat's position, air or ground (l.358/366). `_set_intents` gives every DEFEND fighter `(FIGHT, defend_target)` (l.537). With nothing it can hit, `micro.fight` attack-moves to that point anyway (`micro.py:67`).
- **Verdict:** DESIGN GAP. §4.5.2 doesn't say which units answer which threat.
- **Take:** Agree for pure-air groups. A unit that can't hit anything in the threat group holds at the hold point, out of the enemy's range, and doesn't count as a defender in that fight. Against mixed armies, ground-only units should still fight the ground part.
- **Scope:** S, M4 follow-up.

## 4. Shield Batteries ignored
- **Evidence:** The first fight (8:59-9:31) was next to the enemy third's Battery (75,67) and Cannon (72,63). Citadel killed both (9:26, 9:29). It was the closest trade of the game: 3,025 lost vs 2,350. Tempests did most of the damage there, not Battery healing. Citadel itself built 1 Battery and 0 Cannons all game.
- **Cause:** `engagement.py` passes enemy Batteries to the sim as plain units; VERIFY_NOTES §11.3 records that "nothing models battery healing". For our side, `_home_defense` only lowers the engage level from 5 to 4 when any ready Battery is within 8 (`BATTERY_COVER_RADIUS`), ignoring count and energy.
- **Verdict:** DESIGN GAP. The spec says outright that batteries aren't simulated.
- **Take:** Right idea, wrong priority for this loss. A cheap model: add each Battery's remaining restorable shields (energy × the restore rate from game data) as extra shield HP spread over the units it covers. Do this for both sides.
- **Scope:** M, M4 follow-up. The current M4 design wouldn't change it.

## 5. Low-HP enemies escape
- **Evidence:** Can't check. The replay's tracker data has no HP, and the bot logs none. What we do know: 0 of 16 Tempests died, 6 of 9 Void Rays and 7 of 14 Immortals died, and 47 of 56 Zealots died.
- **Cause:** Each unit already shoots the lowest-HP enemy in range (ares `ShootTargetInRange`, "only picks lowest health"). Nothing chases a target out of range.
- **Verdict:** UNCLEAR. It would be settled by a log of the HP+shield fraction of enemies leaving a fight (or one replay viewing at 12:50-13:05).
- **Take:** Sending one unit to finish a target is risky against AI Arena bots. Many pull hurt units back into their army or Batteries, which is bait. Better: `ShootTargetInRange(extra_range=…)` for targets one volley from death (ares documents this use), shared focus across the group, and chase only when the chaser is faster and the sim says the local fight is safe. Against Tempests it doesn't apply: they out-range us, so they never get low.
- **Scope:** S, M4 follow-up.

## 6. No Blink research
- **Evidence:** Your premise is wrong: Blink **was** researched, 12:57 to 14:21. But Citadel never cast it (0 Blink commands in the replay). The Twilight Council was done at 8:20, so it sat idle for 4.5 minutes.
- **Cause:** Blink micro is on the §7 "Cut from v1" list. `production.py:_next_upgrade` runs one research at a time across all buildings (l.159, "wait for the one in progress"). Blink is 4th in `UPGRADES_VS_P`, behind +1 weapons, +2 weapons and +1 armor (see E).
- **Verdict:** NOT AN ISSUE as stated. DESIGN GAP for the micro and the research queue.
- **Take:** Research without a Blink behavior is wasted gas. A minimal blink-in on out-ranging air (Tempests) and blink-back for shieldless Stalkers would directly answer B. Bots rarely punish blink-ins.
- **Scope:** S for the queue (M1). M for blink micro, which needs taking it off the cut list (post-v1).

## 7. Colossus usage
- **Evidence:** 11 Colossi made, all lost, 9 of them to Tempests. Their air attack out-ranges everything Citadel has, and Colossi are hit by air weapons. Per resource spent, though, Colossi were the best killers: ~2,800 killed for 5,500 invested, vs Stalkers' ~6,100 for ~16,300. Extended Thermal Lance started 14:26, 8 minutes after the Robotics Bay finished (6:30). Position samples put Colossi *behind* the Stalkers (9:06: 22 vs 10 from the enemy centre; 13:02: 16 vs 13), but still within Tempest range.
- **Cause:** `ARMY_COMPOSITION_PCT["Protoss"]` holds Colossus at 25%, with top production priority, whatever the opponent builds. Lance is late because of E.
- **Verdict:** DESIGN GAP (no counter adaptation; the §4.5.1 air switch was never built). Positioning: NOT AN ISSUE.
- **Take:** Fewer Colossi is right against Tempests or Carriers, wrong against Zealot-heavy armies, so make the share depend on what's been scouted. Earlier Lance: yes (fix E). Keeping them at the back doesn't help against 14 air range.
- **Scope:** S, M1 (§4.5.1 composition).

## 8. No mid-game scouting
- **Evidence:** Scouting ran (22 tasks), but the enemy main went unseen from 5:43 to 11:01, which covered the Fleet Beacon (5:42) and the 2nd Stargate (8:40). Observers were busy with expansion checks. At 9:00 the bot's never-expiring army cache held **~700** value against an actual army of 3,625 (`ARMY 09:00 … army value 700 < 800`). The §4.3 PvP 4:30 Hallucinated Phoenix scout never fired: the vs-P mix has no Sentry, and hallucination needs an existing Sentry (user decision).
- **Cause:** `scout_planner.py` schedules rescouts and expansion checks, but nothing reads tech or composition. STATUS lists the AIR_HARASS, DT, MACRO and TIMING detectors as "not in any milestone yet".
- **Verdict:** DESIGN GAP. There's also a spec contradiction: §4.3 PvP hallucination vs a §4.5.1 vs-P mix with no Sentry. It needs your decision.
- **Take:** Agree, but the real need is to *act* on what's seen. (1) Keep one Observer on the enemy army's likely path from 6:00 and rescout the main every 90 s. (2) Add a tech detector: Stargate, Fleet Beacon, Tempest/Carrier seen → AIR flag → composition switch (B). (3) Require fresh army intel before launching (A).
- **Scope:** M. M3 for scouting, M2 for the detector.

## 9. Slow natural [~2:29]
- **Evidence:** From 2:15, probes were ordered to gather the natural's mineral field (116,148) while still returning to the main Nexus. That is ares long-distance mining for an oversaturated main (23 probes on 16 mineral + 6 gas slots). `SCHEDULE … bases x2 reached at 03:10 (planned 3:10)`; the Nexus went down at 3:19. Bank: 240 at 2:30, 265 at 3:00.
- **Cause:** Opener C (2-Gate Robo) puts the Nexus at 3:10 by spec (§4.1 C step 10, `_C_SCHEDULE`).
- **Verdict:** NOT AN ISSUE. The code matches the design: it wasn't bank-limited or a worker-assignment bug, and the probes were mining, not waiting.
- **Take:** The economy was fine (50 probes vs their 39 at 6:00). Optional: after scouting a Forge and Cannons (a defensive opponent), switch to C2 timing (~2:30 Nexus). That's a design change.
- **Scope:** S, M1.

## 10. Early Oracle harass [~6:06]
- **Evidence:** The Oracle arrived at 5:25 and died at 7:32 to Stalkers. Citadel lost **nothing** to it: no unit died before 8:59 and no probe before 13:29. The cost was the whole DEFEND squad, ground units included, chasing it twice (see #3). The Stargate went up at 2:57, after the probe scout left the main (1:21). Observer rescouts at 4:17-4:43 and 5:17-5:43 probably saw it, but nothing logs enemy tech seen.
- **Cause:** No AIR_HARASS detector exists (§4.4 row 13). The chase is #3.
- **Verdict:** NOT AN ISSUE for damage. DESIGN GAP for the detector.
- **Take:** Agree: only units that can hit air respond, and a Stargate sighting raises AIR_HARASS (§4.2 plan: Forge, Cannon and Battery per mineral line). Its bigger value in this game would have been feeding B.
- **Scope:** S, M2/M3.

## A. Launch gate blind to the enemy army (not on your list)
- **Evidence:** Launches at 8:40 (level 10), 10:30 (10), 11:37 (10) and 12:57 (8). They retreated or were recalled after 52 s, 21 s, 20 s and 5 s, at levels 4, 3, 1 and 0. Enemy value near the squad at retreat: 2,375, 4,000 and 6,575. Level 10 means the sim expected to keep ≥ 90% of our HP+shields, so at launch it saw at most a token force.
- **Cause:** `engagement.py:attack_inputs` counts only enemies within 20 of the squad or its target (§4.5.2 as specified), and ghosts expire after 30 s. STATUS already notes "Launch inputs are local". The 12:57 launch fired 0 s after a home fight ended, because the enemy had just left the 22-cell home radius.
- **Verdict:** DESIGN GAP.
- **Take:** Gate the launch against the cached whole enemy army (scaled by how stale it is) as well as the target's defenders. Refuse to launch on stale intel. Wait some seconds after a home fight. The cache only helps once #8 feeds it.
- **Scope:** M, M4 follow-up.

## B. No answer to mass Tempest (not on your list)
- **Evidence:** 16 Tempests, 0 killed. Tempests killed 95 of the 128 army units Citadel lost, including 73 of its 93 Stalkers (all 93 died). The Fleet Beacon (5:42) and the first Tempest (7:36; in fights from 9:00) changed nothing in production.
- **Cause:** `production.py` docstring: "The air switch … come[s] later". It was never built. Even as designed (more Stalkers, plus Archons), it wouldn't beat Tempests: Archon range is 3 and Stalkers lack Blink micro. Skytoss is cut from v1.
- **Verdict:** DESIGN GAP.
- **Take:** Against out-ranging air, you need units that can reach it: Blink Stalkers with a commit rule (#6), or Void Rays and your own Tempests. Pair that with A and #2, so the army never sits in range while the counter builds.
- **Scope:** L. §4.5.1, or take Skytoss off the v1 cut list.

## C. Sim says "win" against out-ranging air (not on your list)
- **Evidence:** Over 12:42-12:57, home defense logged engage levels 7-10 every evaluation. Army deaths from 12:40 to 12:58 cost Citadel 3,675 against the opponent's 2,100.
- **Cause:** Either the Tempests weren't in the inputs (out of vision, or more than 20 cells from the threat), or the sim can't model the range gap. VERIFY_NOTES §11.3: positions are never passed to the core, and ares warns to use it only "when all units involved can attack each other".
- **Verdict:** UNCLEAR. It would be settled by logging the enemy unit types and counts passed to each evaluation, or by a staged debug-spawn test (e.g. 8 Tempests + 6 Zealots vs 30 Stalkers + 4 Colossi).
- **Take:** If the sim is the problem, apply an out-range penalty: lower the level when enemies that out-range all our anti-air (or all our anti-ground) units make up a big share of the enemy's value.
- **Scope:** S (logging), M (penalty). M4 follow-up.

## D. Mineral float, gas starvation, 3-base cap (not on your list)
- **Evidence:** Minerals ≥ 1,400 from 7:30 to 13:05 (2,900 at 11:32), gas ≤ 466, and supply 136-158 of a 181-189 cap during 9:30-11:40. Gas income ~1,000/min on 6 geysers vs the opponent's ~1,500 on 5 bases.
- **Cause:** §1 "macro to 3 bases". The mineral-float spawner (`production.py`, `MINERAL_FLOAT_BANK`) still respects the mix's proportions (Zealots 10%), so it can't spend minerals while gas runs out.
- **Verdict:** DESIGN GAP.
- **Take:** With minerals above ~1,000 and gas starved, take a 4th Nexus. Let Zealots exceed their share (or build Cannons and Batteries at home) until the bank clears.
- **Scope:** M, M1.

## E. One research at a time across all buildings (not on your list)
- **Evidence:** Upgrades ran strictly one after another: +1 weapons 5:38, +2 weapons 8:21, +1 armor 10:46, Blink 12:57, Lance 14:26. The Robotics Bay sat idle 6:30-14:26, the Twilight 8:20-12:57.
- **Cause:** `production.py:_next_upgrade` (l.159), added to stop ares from starting every tech building at once.
- **Verdict:** DESIGN GAP. §4.5.1 gives an order but says nothing about concurrency.
- **Take:** Keep one queue per research building (Forge, Twilight, Robotics Bay), each starting once its building exists and gas allows.
- **Scope:** S, M1.

## F. Missing observability (not on your list)
- Fight evaluations log the level but not the enemy units counted (this blocks C). Launches don't log the enemy value.
- Enemy tech seen isn't logged (would have shown when the Stargate or Fleet Beacon was seen).
- Nothing records units that left their leash or died far from their order's target.
- Each is a one-line telemetry addition (M5).

## Issues sharing a root cause
- **Attack-move as the default move order, plus per-unit engagement with no squad-level "can we reach them?" check:** #2, #3, #10 (the chase), and part of #1.
- **The sim's inputs and blind spots** (local inputs, 30 s ghosts, no positions or ranges, no Batteries): A, C, #4.
- **Nothing turns scouting into decisions** (no tech detector, no air switch, static composition): #8, #10, B, #7, #6.
- **Opener-era macro rules never revisited** (3-base cap, mix proportions bound the float, one research at a time): D, E, #6 (late Blink), #7 (late Lance).

## The 3 changes that would most have changed this game's outcome
1. **Stop fighting from inside an out-ranging enemy's reach** (#2, plus #3): plain move back to the hold point, back out from attackers we can't reach, move the hold point back. This alone covers most of the 13:05-15:00 bleed (10,525 lost vs 2,750) and the 11:13-11:32 stragglers.
2. **Launch only on fresh, whole-army intel** (A, plus #8): an Observer on the enemy army, the cached army in the gate, a cooldown after home fights. This avoids most of the 10,150 lost in four attacks that each read 8-10 at launch.
3. **React to Fleet Beacon / Tempest / Stargate sightings** (B, plus D and E): cut Colossi, research Blink in parallel and use it, add units that can reach Tempests, and spend the 2k+ mineral float on a 4th base. Without this, 1 and 2 only delay the loss.
