# Audit: bot/army/ (read-only)

Game step is 2 loops (config.yml:18). Army tick every 4 steps (~0.36 s), decisions every 16 steps (~1.4 s), micro every step, per-unit orders staggered on a unit's "own tick" (army.py:802-873).

## Findings (worst first)

### ARMY-1  Small raids are answered only by units at home; the main army is recalled only for a big one (design gap)  [spec/bug, Verified]
army.py:272-283 recalls the whole ATTACK+REINFORCE squad only if `value(enemies within 20 of threat) >= ARMY_RECALL_FRACTION (0.3, constants.py:448) * value(attackers)`. Otherwise the attack carries on (army.py:284-289). A drop, runby, 2 Oracles or 4 Banshees (about 600-1000 value against a squad of thousands) never reaches 30%. The only responder is the DEFEND squad, which at that moment is just the units built since the last launch, because `_evaluate_launch` assigns every DEFEND fighter to ATTACK (army.py:303). REINFORCE groups already walking out ignore the raid (army.py:347-362 only joins or turns back for enemies on the route). The recall is all-or-nothing and has no partial split.
Impact: harassment can run unanswered for the whole attack. Fix: send a detachment sized from the threat's value (or keep a home-guard share at launch).

### ARMY-2  Only ONE home threat at a time, chosen by distance to a base, not danger  [bug/design, Verified]
army.py:559-564: `best` is the single (enemy, home) pair with the smallest distance, and `_home_defense` handles only that one. Two simultaneous prongs (drop in main plus army at natural) leave the second ignored until the first is gone; a lone probe or zergling nearer a Nexus outranks a real army further out. The DEFEND squad is one blob (army.py:703-706).

### ARMY-3  Any visible enemy unit within 22 of a base blocks launch and reinforcement, even if unreachable  [bug, Likely]
army.py:290 `elif self.threat is None and ...: _evaluate_launch` and army.py:363 `if self.threat is not None: return` (no reinforcements). `_home_threat` accepts every visible enemy unit not in HARMLESS (army.py:106-115), which lacks Warp Prism, Medivac, Raven, Liberator, Viking, a scouting zergling, etc. If no defender can hit it, `_able` is empty (army.py:451); `level()` with empty `own` and empty `enemy` returns TIE = 5 (engagement.py:224-227), which is >= ATTACK_CONTINUE (5), so state becomes "engage" with `_defend_tags = set()` (army.py:452-466) and nobody is ordered, while `threat` stays set. Launch and reinforcement stay blocked as long as it is visible.
Fix: exclude unreachable or non-combat units from `threat` for the launch gate, or time-limit it.

### ARMY-4  Enemy structures count as home threats once the squad has 8 supply, including creep tumors and other trivia  [bug, Likely]
army.py:517-530: when `strong_enough` (supply >= ARMY_CLEAR_STRUCTURES_SUPPLY), `candidates += list(bot.enemy_structures)`, including snapshots. Any structure within 22 of a base (Zerg creep tumor, a lone Pylon, a Spore) becomes `found`; with no guard the level is VICTORY_EMPHATIC (army.py:431), so "clearing X" is chosen. A burrowed (cloaked) tumor cannot be shot (ShootTargetInRange filters unrevealed cloaked, shoot_target_in_range.py:65-67), so the squad a-moves to it forever and `threat` never clears, which blocks ARMY-3's launch gate. No CREEPTUMOR handling anywhere in bot/ (grep). Likelihood depends on seeing a tumor (Observer present).
Fix: exclude tumors (and cloaked or untargetable structures) from candidates.

### ARMY-5  Attack/retreat level only sees enemies within 20 of the squad centre or the target; the army the squad will actually meet is not counted  [design flaw, Verified]
engagement.py:205-215 (`attack_inputs`) and :182-196. An enemy army parked 25+ from both the squad and the target (their natural ramp while the target is a third) or out of vision for over 30 s is invisible, so launch at level 10 is possible; the check only changes once the squad walks within 20. attack_decision.py:15-18 says the whole-army check was removed on purpose (M7 D38). Consequences:
- The retreat then happens mid-fight; `held` (attack_decision.py:77, 99) suppresses a level 3-4 retreat for 20 s after launch (only level <= 2 flips immediately).
- `level(attackers, ...)` uses all ATTACK fighters including stragglers far from the fight (army.py:325), so the sim is optimistic.
- Retreat is a whole-army walk home (army.py:337-340); slow units (Colossus, Immortal, Archon, HT) die to faster pursuers. No fighting retreat or stand.

### ARMY-6  Launch gate uses total supply (workers included)  [spec-ish, Verified]
attack_decision.py:84 `supply_used >= ATTACK_START_SUPPLY (150)`; `bot.supply_used` is total supply, so about 70 probes means about 80 army supply. Spec 4.5.2 has the same wording, so it matches the spec, but it is a weak army gate against a strong opponent. Level >= 5 at 190 (attack_decision.py:86) is "TIE launches".

### ARMY-7  Recall leaves no relaunch wait and the units may turn around  [bug, Likely, low]
`AttackDecision.recall` (attack_decision.py:111-114) sets no `retreated_at`. After 20 s (the `held` window, which only blocks when level > 2) and with `threat` None, `_evaluate_launch(defenders)` can relaunch while units are still walking home with RETREAT intent; it reassigns them to ATTACK and drops their intents (army.py:303-307). The spec says no re-launch for 45 s after retreating.

### ARMY-8  Spec mismatch: home defence "never leaves the battery radius"  [spec, Verified]
DESIGN.md 4.5.2: "Home defence engages at >= DEFEND_ENGAGE and never leaves the battery radius". Code: engages at ATTACK_CONTINUE (5) anywhere within 22 of a base (army.py:457), at 4 only when a ready battery covers the point (army.py:456-457), and pursues with FIGHT attack-move (army.py:466, 706). Also, the spec's target rule "nearest expansion -> next -> main" is implemented as "townhall nearest the squad" (army.py:627-636). Stale or undocumented deviation.

### ARMY-9  Stale docs: micro.py says kiting is ares `StutterUnitBack`; it is `KeepUnitSafe`  [spec/doc, Verified]
micro.py:4-5 docstring vs micro.py:250 `KeepUnitSafe(...)`. KeepUnitSafe (keep_unit_safe.py:36-49) returns False when the unit's cell is "safe" on the influence grid and otherwise paths to the nearest low-cost cell, which is a danger-grid dodge, not a stutter step (no shoot-then-step timing). Out-ranging is decided by weapon reach (ranges.py) but the step-out is decided by grid cost, so the two can disagree (Uncertain: depends on ares influence ranges vs real ranges).

### ARMY-10  Dead code  [dead, Verified by grep over bot/ and scripts/]
- `Decision.flipped` (attack_decision.py:54-56): 0 uses.
- `NO_DEFENDER` (engagement.py:68): defined, never used.
- micro.py:30 imports `blink_ready`, unused there.

### ARMY-11  Hard-coded thresholds not in constants.py  [rule, Verified]
army.py:524 `HOLD_RADIUS + 1.0`; army.py:536 `+ 1`; army.py:759 `longest + 30`; micro.py:127 `< 2.0`; micro.py:167 `max(r - 1.0, 0.5)`; micro.py:297 `BLINK_RANGE / 2`; micro.py:326 `success_at_distance=2.0`; blink.py:48 landing angles and blink.py:67 `reach - 1.0`; micro.py:338 `< 1.0`. Minor but contradicts "every TUNE value lives in constants".

### ARMY-12  Retreating or holding units may stand still in danger (Uncertain, low)
army.py:844-848: for HOLD/MOVE/RETREAT units with out-rangers, a non-own-tick unit `continue`s with no order, and an own-tick unit that `step_out` returns False for falls through. A retreating unit is therefore diverted from its path home by step_out. The retreat-shoot rule (micro.py:314-322) lets a retreating Stalker stop to shoot when there are no threats that can hit it (empty `speeds` -> `all([])` True).

## No problems found (API checks)
sc2_helper `predict_engage(own, enemy, optimistic=False, defender_player=0)` exists and the side swap is consistent (ares-sc2/sc2_helper/combat_simulator.py:113-147). `get_squads(role, squad_radius, unit_type)` matches squad_manager.py:187; `assign_role` removes from squads (unit_role_manager.py:168-192). `find_closest_safe_spot(from_pos, grid, radius)`, `is_position_safe(grid, position, weight_safety_limit)`, KeepUnitSafe, PathUnitToTarget, ShootTargetInRange, AutoUseAOEAbility (min 4 targets, avoids own units), `request_archon_morph(list)`, `get_units_in_range` (list aligned to start_points), `unit.abilities` (per-step query), `Unit.age`/`is_memory`, `order_target`, `unit_tag_dict` (includes enemies and ghosts): all exist with the used arguments. No Unit objects are stored across steps (only tags, Points and floats). No network or writes in these files.

## Capability summary

Squads (squads.py:26-40; roles mirrored to ares UnitRole):
- DEFEND (BASE_DEFENDER): new units, retreaters, home defence.
- ATTACK (ATTACKING): the main attack.
- REINFORCE (CONTROL_GROUP_ONE): groups of >= 8 supply going out.
- HARASS: the counterattack squad.
- SCOUT: owned by the scout planner; held units (wall holder and external) are in no squad.
- Assignment: `Squads.update` (new units -> DEFEND, scouts -> SCOUT, army.py:240); `_evaluate_launch` (all DEFEND fighters -> ATTACK, army.py:303); `_reinforce` (>= 8 supply at the anchor -> REINFORCE, :366-367); `Counterattack._launch` (picks Adepts, Charge Zealots, Stalkers from DEFEND, up to 35% of army supply -> HARASS); `merge` and `send_home` move units back.
- Independent groups: yes. DEFEND, ATTACK, REINFORCE and SCOUT act at once. HARASS never runs during ATTACK (counterattack.py:302) and merges on launch. Each group has one target, and home defence handles one threat at a time (ARMY-2).

Small group hits a base while the army is out or gathered elsewhere:
- Detection: army.py:500-564. Visible enemy units (army types not in HARMLESS) within ARMY_DEFEND_RADIUS (22) of a townhall or natural spot, workers within 12, structures once the squad has 8 supply. Nearest to any base wins. With a defense-plan leash only enemies near the hold point, in the main, or shooting the holders count.
- Response: only DEFEND units that can hit something in the group (`_able`, :378-381) count in the simulation and are ordered (`_defend_tags`). Engage at level >= 5 (>= 4 under a ready battery within 8), or always if inside the main or within 8 of the hold point ("last stand", :438-446). Once engaged, it fights until level <= 2, then falls the hold point back and waits 20 s (:459-477, :488-498).
- Main army: not involved unless the enemy group is worth >= 30% of the attack squad AND the home squad chose to hold (:272-283); then the entire ATTACK and REINFORCE squad retreats home and the attack ends (state GATHER). Otherwise the attack continues. While the army is gathered, it is the DEFEND squad itself and engages as above.
- The deciding values: simulator level (HP+shields, penalised for out-ranging and weaponless-unit value cap, engagement.py:219-249), the 0.3 value fraction, and battery cover.

Per-unit micro (micro.py, army.py:802-874, blink.py, templar.py):
- Generic `fight`: blink-back if Stalker is low on shields; shoot lowest-HP target in range via ares ShootTargetInRange (units that fight back first); kite via KeepUnitSafe when on cooldown and out-ranging the closest threat (KITERS: Stalker, Adept, Immortal, Colossus, Sentry, Phoenix, Void Ray, Oracle, Tempest); otherwise attack-move. Melee units attack-move.
- Stalker: Blink back (low shields), blink in onto out-rangers in waves of >= 3, blink to finish a one-volley kill when level >= 7, blink away while retreating. Landing spots must be visible, pathable and low danger.
- Zealot, Adept, Immortal, Colossus, Archon: generic only. Adept shade is used only by the scout planner. No splitting, no target priority beyond lowest HP and fights-back first.
- Sentry: kiting only. Void Ray and Sentry have no weapon in this game data, so ares ranges are used. Void Ray: prefers armored or capital targets and uses Prismatic Alignment at >= 3 armored (micro.py:193-212). Tempest: prefers massive or capital, kites.
- High Templar: Storm via ares AutoUseAOEAbility (needs >= 4 enemies, avoids own units, spaced, one new Storm per step), stays 2 behind squad centre and dodges via KeepUnitSafe, and morphs into Archons in pairs (templar.py).
- Observer: one travels with the army, KeepUnitSafe on the air grid.
- Retreat: PathUnitToTarget on the danger grid (own tick only), shoots only if faster than all threats and the target fights back. Out-ranged holders step out of reach.
- Counterattack squad (harass): shoots what can fight back, then workers, production, townhall.
- ABSENT (no code, grep of bot/ for FORCEFIELD, GUARDIAN, DISRUPTOR, DARKTEMPLAR, WARPPRISM, PHOENIX micro): Guardian Shield, Force Field, Hallucination in combat; Phoenix, Oracle, Disruptor, Dark Templar and Warp Prism control (production never builds them, apart from the scout planner's opener Oracle and hallucinated Phoenix); Colossus targeting priorities; splitting against splash (Storm, Bile, Tank, Disruptor); dodging Storms, Biles, Disruptor shots; focus-fire on high-value targets (Medivacs, Tanks, Templar, casters); Stalker/Immortal focus on armored; Archon splash positioning; Immortal Barrier; Charge/Zealot surrounds; unit-type-aware retreat; Observer/detector protection for fighting cloaked units; Storm only with >= 4 targets.

Attack and retreat decisions:
- Launch: DECISION_EVERY_STEPS tick, GATHER, no home threat, no relaunch within 45 s of a retreat, level >= 8 with supply_used >= 150, or level >= 5 at 190; end game rules (attack_decision.py:72-93). Level = simulator on DEFEND fighters versus remembered enemies near their centre or the target plus static defence, defender = enemy.
- Retreat: level <= 4 (not within 20 s of launch unless <= 2), or squad value < 40% of start value, or a home recall. Whole army, no relaunch for 45 s (except recall).
- How it goes wrong against a strong opponent: ARMY-5 (blind to the army beyond 20, optimistic sim with stragglers, no spells or upgrades modelled by the sim, 20 s lock), ARMY-6 (workers count toward supply), ARMY-1 (home left empty at launch), ARMY-3/4 (stuck gates), slow units lost on retreat, ghosts expire after 30 s so a hidden army reads as nothing.

## (a) Files read fully
bot/army/army.py, attack_decision.py, squads.py, micro.py, engagement.py, ranges.py, counterattack.py, blink.py, templar.py, endgame.py; bot/main.py lines 190-265 and 340-375 plus an army grep; the army-related parts of bot/constants.py by grep and range reads; DESIGN.md 4.5-4.7.

## (b) Library calls checked and found correct
CombatSimulator.predict_engage, get_squads, assign_role, find_closest_safe_spot, is_position_safe, KeepUnitSafe, PathUnitToTarget, ShootTargetInRange, AutoUseAOEAbility, request_archon_morph, get_units_in_range, get_cached_enemy_army, unit_tag_dict, Unit.abilities, Unit.age, Unit.is_memory, Unit.order_target, Unit.is_using_ability, AOE_ABILITY_SPELLS_INFO, WEIGHT_COSTS keys.

## (c) Not checked
Compiled sc2_helper/cython_extensions internals (sim ignores abilities? upgrades?) and cy_attack_ready, cy_in_attack_range behaviour; ares influence-grid ranges versus the bot's reach maths; bot/intel (army_position, threat_flags) and bot/defense; worker_defense (probe pulls vs raids); whether burrowed tumors appear in enemy_structures (ARMY-4 is therefore Likely). No game can run here, so none of the in-game behaviour was observed.
