# Defense audit (bot/defense/*, parts of main.py, constants.py, threat_flags.py, detectors.py, ares_bridge.py; spec 4.2, 4.4, 4.8, 5)

## Findings (worst first)

DEF-1 | bot/intel/threat_flags.py:41-42, bot/intel/detectors.py:243-253 | spec/dead | Verified
Threat.DT, TIMING_ATTACK, MACRO are never raised anywhere in bot/ (grep: only the enum and UNIT_TTL_S["TIMING_ATTACK"], constants.py:484). Detectors.update() runs only _worker_rush, _cannon_rush, _forge_first, _early_pool, _proxy, _no_natural, _air_harass, _capital_air. PLAN_ORDER (defense_planner.py:80-88) has no DT/TIMING/MACRO/CAPITAL_AIR/ARMY_OUT entry. docs/STATUS.md:323 admits it ("not in any milestone").
Impact: spec 4.2 "Timing attack" row (pull army to natural choke, don't expand) and 4.4 rows 12, 14, 16 do nothing. No plan reacts to a 2-base timing, 2-base roach/ravager push after 4:00, or a Dark Shrine/Twilight cloak build beyond the Observer rule in DEF-6.
Fix: implement detectors.timing/dt or delete the enum values and TTL entries and update spec/STATUS.

DEF-2 | bot/intel/ares_bridge.py:58-67,110-123 + defense_planner.py:223-224 | bug/economy | Verified
"get_enemy_went_reaper" (ares intel_manager.py:402-407: any Reaper in enemy_army_dict, i.e. one seen by our scouting probe at their base) raises PROXY with no evidence needed (ares_bridge.py:112-123 only checks `value and now <= raise_until`; no window, so BRIDGE_RAISE_UNTIL_S=330, constants.py:506). override_for(PROXY, ...) returns True for every evidence (defense_planner.py:223-224) so the ares opener is ended (set_build_completed, :278). _plan_proxy then holds expansion until 2 ground units (:425-426), 2 Gateways, main Battery, hold_tech until 8 supply (:427-428).
Impact: a standard Reaper-expand Terran ends our opener and delays the natural for ~45 s (UNIT TTL, constants.py:488) or longer. STATUS.md:320-322 knows about it and accepted it.
Fix: require a Reaper near our bases (evidence non-empty) or a missing-production flag before PROXY; do not end the opener on UNIT-only PROXY.

DEF-3 | bot/defense/defense_planner.py:331-335 | bug | Verified
completed_enemy_cannons() requires `s.is_powered`. VERIFY_NOTES.md:1025-1029 records that fogged snapshots report is_powered False; bot/army/engagement.py:86-89 was fixed (visible-only power check), the planner was not. A Cannon out of vision is treated as not existing in cannon_covers / cannons_covering, hence in _safe hold points (:306-314), _plan_cannon_rush cancel/no-expand (:361-374), static_defense._candidates/_line_spots (:220,274) and worker_defense (:165,179).
Impact: rush Cannons that drop out of vision stop shaping hold points, building spots and probe targets (the M7 B7 "32 units died near ramp" case can recur). The 'sources'-based natural cancel also misses them.
Fix: same rule as engagement.is_static_defense: need is_powered only when s.is_visible. (army.py:397 has the same pattern; outside my files.)

DEF-4 | bot/defense/worker_defense.py:83 + constants.py:502 | spec/gap | Verified
Probe-vs-Zergling defense (_lings_in_mineral_line) runs only while POOL_12 is active; POOL_12 phase-ends at 4:00 (POOL_12_PHASE_END_S) and its ares flag window is (0,180) (constants.py ARES_INTEL). After that no code pulls probes, moves them or builds anything for Zergling/Hellion/Adept runbys. Only the generic army home defense (army.py _home_defense, ARMY_DEFEND_RADIUS 22, constants.py:440) answers.
Impact: mid-game ling floods/runbys into a mineral line are answered only by the army, one group, wherever it is.

DEF-5 | bot/defense/wall_fallback.py:158-162, 112-132 | dead / risk | Verified (dead), Uncertain (crash)
VERIFY_NOTES.md:605-608: no pool map uses the fallback (all 14 spawns wall_ok True), so the whole `not wall_ok` branch (_build_battery, _hold with WALL_HOLD_UNTIL_S, ramp_wrong choke) is dead on the current pool. If a map did use it, step() holds the first Zealot/Adept at the ramp until 6:00 whatever the threat (line 162), plus a Pylon and Battery. Also _make_wall_spots_unusable indexes spots[0] and spots[1:3] after a loop that may find fewer than 3 unbuildable edge tiles (:129-130): IndexError would be raised inside prepare(), which main.py:98 does not guard, so on_start would crash.
Fix: guard len(spots) < 3; keep branch but note it is untested on the ladder.

DEF-6 | docs/DESIGN.md 4.2 "Air / cloak", 4.4 row 12; bot/intel/scout_planner.py:419-425 | spec | Verified
Cloak detection is thin. DT: no Dark Shrine / Twilight detector (DEF-1). The only DT-specific response is "home_observer" (scout_planner.py:419-425): only vs Protoss, only if a Twilight Council is seen, one Observer posted 8 toward the main from the natural (HOME_OBSERVER_OFFSET, constants.py:723). No Observer near the main mineral line, none vs Terran (Banshee/Ghost/mines) or Zerg (burrow, Lurker). Observer count is fixed at 2 (constants.py:366, production.py:539-546): one is the watch post, one joins the army from 6:00 (constants.py:811), so the home Observer competes with them.
No Robotics Facility is forced when a cloak threat is seen (spec says build one).

DEF-7 | bot/defense/defense_planner.py:443-457, constants.py:930-932 | economy | Verified
AIR_HARASS fires on any enemy Stargate/Spire/Greater Spire/Starport TechLab. Plan: Forge now, then at every ready Nexus a Pylon + Photon Cannon + Shield Battery (about 350 minerals per base + 150 Forge), only "satisfied" when every line has a finished Cannon (:446-455). set_satisfied flips back off whenever a new base finishes, so each new base gets the same spend. Never expires by phase (spec 5 agrees) but PvP Stargate openings, a Phoenix/Void Ray macro build, or one Terran Starport TechLab (Raven, Cyclone? no: Banshee/Raven/BC) all trigger it. Battery requires Cyber Core only (static_defense.line_next).
Impact: heavy over-build against a suspected (not confirmed) air threat; no confirmation by an actual air unit.
Fix: gate on air units seen, or on tech + time, or cap to the main/natural lines.

DEF-8 | bot/defense/worker_defense.py:131-136 | economy | Verified
Worker-rush pull is fixed at `len(workers) - WORKER_RUSH_KEEP_MINING` as soon as more than WORKER_RUSH_END_AT (=1) enemy workers are near. Two enemy workers (scout + builder) with a flag active pulls every probe but 2. Spec says "all except 2" so it follows the spec, but the pull is not scaled to the enemy count.

DEF-9 | bot/intel/detectors.py:485-492 + defense_planner.py:227-230 | economy | Verified
_early_pool raises POOL_12 (UNIT) when ANY visible Zergling exists before 2:20 (EARLY_LINGS_UNTIL_S=140), with no distance filter (_visible_enemy_units, detectors.py:212). Our scouting probe seeing the standard pair of scouting lings at their base counts. override_for(POOL_12) returns True (:227-230): opener ended, expansion blocked until 3 units and no lings within 20 for 10 s, 2 Gateways, Core first, Battery, hold_tech, chrono on Gateways (:383-422). Spec 4.2 says "lings seen before 2:20", so this matches spec; the cost is a false positive vs normal Zerg openers. (Fix: require lings within BRIDGE_HOME_RADIUS of our bases.)

DEF-10 | bot/intel/detectors.py:663-676, defense_planner.py:459-480 | economy | Likely
no_natural fires when the enemy natural was in vision at the deadline (2:45 P/T, 2:15 Z) with no townhall AND (>= 2 gas OR >= 3 production). Any late expand with 2 gas triggers ONE_BASE_ALLIN: 3 Batteries (225), no 3rd Nexus, no Forge, hold_tech under 8 army supply, all Gateways producing. Ends only when the enemy natural townhall is seen, or 7:00 with 3 Batteries and 20 army supply (detectors.py:696-703).

DEF-11 | bot/main.py:130-153, constants.py:864-878 | economy | Verified (user decision)
Opponent-memory pre-raise at 0:00 of PROXY or WORKER_RUSH (override_for True, not in MEMORY_KEEPS_OPENER) ends the opener on the first intel tick (defense_planner.py:268-278), before the first Pylon. WORKER_RUSH pre-raise also blocks expansion and reserves a Zealot until 2:30. ONE_BASE_ALLIN pre-raise removes 3rd and Forge for up to 7:00.

DEF-12 | bot/defense/defense_planner.py:136-165, 355 | dead/spec | Verified
DefensePlan.cannons_needed is never written or read (grep: only the field, and spec 5 lists it). DefensePlan.probe_pull is written at :355 and printed in summary(), never read by worker_defense (which recomputes its own pull). No Cannon count exists in the plan; Cannons come only from the AIR_HARASS mineral-line code. Also roaches_seen / reapers_seen (:207-208, 237-241) latch for the whole game and never reset.

DEF-13 | bot/defense/static_defense.py:279-305 | perf | Uncertain
_line_defense runs every macro tick (4 steps) while AIR_HARASS is unsatisfied: per base it builds _line_spots (13x13 tiles, each with can_place_structure, a segment-distance test against ~10 resources, and planner.cannon_covers which rescans enemy_structures) before checking can_afford (:295-300). Probably some ms per tick; not measured.

DEF-14 | bot/defense/worker_defense.py:251-263, static_defense.py:316-322 | API | Uncertain (low)
Cancels use unit(AbilityId.CANCEL_BUILDINPROGRESS) directly. ares mediator.cancel_structure (building_manager.py:439-458) says to use it so the tracker forgets the order. For Protoss the tracker entry is already removed once the structure exists (building_manager.py:310-316, build_progress >= 1e-16), so the risk is small; ares build-runner/other behaviors might re-order the structure.

DEF-15 | docs/STATUS.md:323 | stale doc
Says AIR_HARASS detector is not in any milestone; M7 E2 added it (detectors.py:609-611). DT, MACRO, TIMING_ATTACK are still missing.

## Capability summary

Threat | trigger (file:line) | response
- WORKER_RUSH | >=5 enemy workers within 30 of main before 2:00 (detectors.py:329-346) or ares worker flag (ares_bridge.py:50) | plan :350-355: no expand, Zealot first, reserve 1 unit, 1 Gateway; worker_defense.py:120-138 pulls all probes but 2, healthiest first, swap below 15 HP; ends opener (:223)
- CANNON_RUSH | enemy Pylon/Forge/Cannon within 25 of main/natural before 4:00 (detectors.py:348-368); probe >=10 s in main 1:00-3:00 (:377-390); Forge-first (:392-427) | plan :357-381: bank 150 (forge-first), Immortal/Stalker after a Cannon finishes, cancel natural, no expand, hold at ramp top; worker_defense.py:149-209: 3 probes per Pylon, 4 per Cannon, 1 per enemy probe, max 12; cancel dying structures (:251-263); static_defense blocks Cannon-range spots (:405-438)
- POOL_12 | pool before natural / any ling before 2:20 / ares ling flag (detectors.py:449-492) | plan :383-422: no expand until 3 units, 2 Gateways, Core first, Zealot then Adept, 1 main Battery, wall-gap holder, ramp hold; probes pulled 2 per ling in mineral line only (worker_defense.py:213-247)
- PROXY | missing Gateway/Barracks or short workers (detectors.py:502-577); far production (:579-593); ares marine/reaper/proxy-zealot flags | plan :424-441: no expand until 2 units, 2 Gateways, 1 main Battery, Stalkers vs Reapers, chrono, ramp hold
- ONE_BASE_ALLIN | no natural at deadline + 2 gas/3 production (detectors.py:647-677); ares roach/ravager/marine/marauder/four-gate flags | plan :459-480: 3 Batteries natural (main if none), no 3rd, no Forge, all Gateways, Immortal vs Roach, natural/ramp hold
- AIR_HARASS | Stargate/Spire/Greater Spire/Starport TechLab seen (constants.py:930) | plan :443-457: Forge, then Pylon+Cannon+Battery at every mineral line (static_defense.py:279-305)
- UNKNOWN_AGGRO | scout probe killed before enemy main (detectors.py:429-447) | plan :482-487: +1 Battery, no 3rd
- CAPITAL_AIR | Fleet Beacon/Fusion Core/Greater Spire (WARNING), ships worth >=400 (ACTIVE) (detectors.py:613-632) | no defense plan; production.py:481,549 (Stargate early, Twilight chain, mix)
- ARMY_OUT_OF_POSITION | army_position.py:170 | no defense plan (counterattack)
- DT, TIMING_ATTACK, MACRO | never raised | none (DEF-1)

Common threats without/with partial plan:
- DT: partly. Home Observer only PvP after Twilight seen (scout_planner.py:419). Cannons only if AIR_HARASS fired.
- Cloaked Banshee: partly. Starport TechLab triggers AIR_HARASS (constants.py:930) -> Cannons at lines (detection). No Observer response.
- Burrowed units/Lurkers/mines: none (army Observer from 6:00 only, constants.py:811).
- Oracle/Banshee/Muta/Liberator worker harass: partly (AIR_HARASS Cannon+Battery per line; Liberator without TechLab never triggers; no probe movement).
- Hellion/Adept/Zergling runbys: none after 4:00 (DEF-4); POOL_12 early lings: planned.
- Medivac/Warp Prism/Overlord drops, Widow Mine drops: none. Reapers: partly (PROXY plan, DEF-2). Nydus, Swarm Hosts, Disruptors: none.
- Proxy Stargate/Void Ray rush: partly (PROXY far-production test uses PRODUCTION set, check detectors.py PRODUCTION; Stargate then triggers AIR_HARASS).
- Two-base timing: none (DEF-1). 4-gate: planned (ares four-gate flag, one-base plan). Roach/Ravager all-in: planned only before 4:00 and 1-base (ares windows 0-240). Mid-game ling floods: none (DEF-4).

Static defense: Batteries only: main 1 near ramp top (POOL_12, PROXY; static_defense.py:225-252), natural 3 (ONE_BASE_ALLIN, main if no natural), +1 UNKNOWN_AGGRO, plus opener-scheduled 1-2 natural Batteries (constants.py:223-287). Cannons only via AIR_HARASS (1 per mineral line with Pylon and Battery). Mineral-line detection exists only through those Cannons and the single home Observer (PvP/Twilight).

Probe pulls/moves: worker rush (all but 2), cannon rush (max 12), lings in mineral line while POOL_12 (2 per ling, max 16). Nothing moves probes away from harassment or relocates a mineral line (grep for flee/evacuate in bot/: none).

Expensive responses to suspected threats: DEF-2 (Reaper ends opener), DEF-9 (any early ling ends opener), DEF-7 (Cannon+Battery per base for any Stargate), DEF-10 (3 Batteries, no 3rd/Forge for late 2-gas expand), DEF-11 (memory pre-raise ends opener at 0:00), DEF-8 (pull scaled to nothing).

## (a) Files read fully
bot/defense/defense_planner.py, static_defense.py, wall_fallback.py, worker_defense.py; bot/main.py; bot/intel/threat_flags.py. Partly: bot/constants.py (grep + ranges), bot/intel/detectors.py (lines 1-110 headers, 196-255, 329-735), bot/intel/ares_bridge.py (30-200), scout_planner.py 405-430, production.py 525-555; docs/DESIGN.md 4.2, 4.4, 4.8, 5.
## (b) Library calls checked and correct
ares: BUILDING_SIZE_ENUM_TO_RADIUS, STRUCTURE_TO_BUILDING_SIZE, ID/TARGET, UnitRole, WORKER_TYPES, BuildStructure(base_location, structure_id, static_defence, find_alternative, wall), mediator get_own_nat, get_own_structures_dict, get_building_counter, get_building_tracker_dict, get_placements_dict, can_place_structure, select_worker(target_position, force_close), build_with_specific_worker(worker, structure_type, pos), request_building_placement, get_units_from_role(role, unit_type), assign_role, get_own_army_dict, get_unit_role_dict, get_map_data_object.map_chokes, build_order_runner.set_build_completed/build_completed/build_step/build_order/chosen_opening, BuildOrderStep.command/start_at_supply, unit_tag_dict. python-sc2: Unit.order_target, is_memory, is_powered, ground_range, is_visible, build_progress, is_ready, is_attacking, hold_position, Units.find_by_tag, tech_requirement_progress, get_terrain_z_height, calculate_supply_cost, on_unit_took_damage (called bot_ai_internal.py:917,952), Ramp.protoss_wall_* (cached_property, assignable), _units_previous_map etc. cython_extensions.cy_pylon_matrix_covers(position, pylons, height_grid, pylon_build_progress).
## (c) Not checked
No game can run (SC2 not installed), so runtime behavior (is_powered for visible enemy Cannons, ares flag timing, placement dict contents beyond docs) is from source only. Did not read army.py, production.py, build_executor.py, scout_planner.py in full (other helpers' files). DEF-13 not measured.
