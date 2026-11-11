# Audit: bot/intel (read-only)

## Findings (worst first)

INT-1 | detectors.py (absent), threat_flags.py:40-42 | spec | Verified
Threat.DT, Threat.TIMING_ATTACK, Threat.MACRO are never raised. grep "Threat.DT|TIMING_ATTACK|MACRO" over bot/ hits only the enum (threat_flags.py:40-42), a TTL entry (constants.py:484) and a comment. Spec §4.4 rows 12 (DT: Twilight w/o expansion, Dark Shrine), 14, 16 and §4.2 `detectors.timing`/DT half of `detectors.tech` have no code. defense_planner PLAN_ORDER (defense_planner.py:80-87) has no DT/TIMING plan. DARKSHRINE appears only in a cancel list (worker_defense.py:274).
Impact: no DT response beyond fixed OBSERVER_COUNT=2 (constants.py:366, production.py:536-545) and a PvP-only home Observer (scout_planner.py:418-425); no "pull army to choke, don't expand" on a timing attack.
Fix: add detectors for Dark Shrine / Twilight-no-expansion and for army-value+approach (or delete the enum members/TTL and update the spec). docs/STATUS.md:323 is stale: it says AIR_HARASS is not built; it is (detectors.py:609).

INT-2 | detectors.py:117-122, 647-675 | spec/bug | Verified
Zerg one-base detection is structurally weak. PRODUCTION has no Zerg structure (Spawning Pool, Roach Warren, Baneling Nest), so `production >= NO_NATURAL_MIN_PRODUCTION(3)` (constants.py:540) can never hold vs Zerg; only `gas >= 2` can. Rows 5/6 (Roach Warren before 2:45; Pool done and no natural at 1:45) have no structure detector; deadline is 2:15 (constants.py:538) not 1:45, and "Pool done" is not tested. Row 8 wants >=2 Barracks by 2:30; code needs >=3 production at 2:45.
Impact: roach/ling one-base all-ins are caught only when Roaches show (ares roach flag, ares intel_manager.py:316-... t<180/240) i.e. ~3:30-4:30.
Fix: add Roach Warren / Baneling Nest checks; align thresholds with §4.4 or amend the spec.

INT-3 | scout_planner.py:505-510, scout_tasks.py:169-180 | bug | Likely
Main re-scout is `LookTask(... [enemy_start_locations[0]])`: one waypoint, finished the moment that tile is visible (Waypoints.current, scout_tasks.py:175), then the Observer goes home. Observer sight is ~11, MAIN_RADIUS is 22 (constants.py:508), so Stargate/Starport/Dark Shrine/Robo near the main edge are often not seen.
Fix: use main sample points / a lap (Detectors._main_samples) as waypoints.

INT-4 | ares_bridge.py:106-125 (vs docstring 7-10) | bug | Verified
The "units must be near home" gate applies only to confirming and re-raising. The FIRST raise needs only the ares boolean (`if not value ... continue` then raise; the `raised_before` guard at 113-115 is skipped on first raise). ares flags are not location-gated: `enemy_went_reaper` = any Reaper ever in the army dict (intel_manager.py:402-407); ling flag counts lings seen anywhere (>4 by t<90, >7 by t<180; :431-441). So a Reaper or lings seen at THEIR base by the scout raises PROXY / POOL_12 with 0 matching units; override_for returns True for PROXY and POOL_12 (defense_planner.py:223-230), ending the opener. Flag lasts 45 s TTL (constants.py:482-491). docs/STATUS.md:320 admits it.
Fix: require `len(evidence) >= min_units` (home-gated) for the first raise of unit-based bridges, at least for the reaper and ling bridges.

INT-5 | detectors.py:561-562 | spec | Uncertain
Terran: `workers <= PROXY_TERRAN_MAX_SCVS(12)` alone raises PROXY (a reason is enough), even with Barracks and townhall seen. `workers` = distinct SCV tags the lap happened to see (detectors.py:289-292). A partial lap can read <=12 on a normal build. PROXY ends the opener (override True).

INT-6 | enemy_mix.py:145 | bug | Verified
`bot.calculate_supply_cost` returns the morph delta (python-sc2 bot_ai.py:410-421): Zergling 1, Baneling 0, Ravager 1, Brood Lord 2, Lurker 1. Mix shares are "by supply" so Zerg ground morphs are mis-weighted (lings 2x, banes 0), skewing `air_share` (the air switch, constants.py:1025) and Zerg Archon logic.
Fix: use food_required from game data (game_data.units[...]._proto.food_required), halve Zerglings.

INT-7 | constants.py:930-932, production.py:148-156 | spec | Likely
AIR_HARASS_TECH = Stargate, Spire, Greater Spire, StarportTechLab. Starport with Reactor (Liberator/Viking/Medivac drops) and spec row 9 (Factory+Starport, no expansion) raise nothing. `mix_mode` needs AIR_HARASS active AND air share on, so vs Terran mass reactor-air the mix never changes.

INT-8 | scout_planner.py:415, scout_tasks.py:580 | bug | Likely
"observer_post" goes into `self.sent` when given (415). If the Observer is hurt/detected-out (PostTask.step -> back_step -> "done") the post is never re-issued (PvT/PvP post only lasts to 6:00, constants.py:722, so impact small).

INT-9 | scout_tasks.py:101; scout_planner.py:269,475,551; detectors.py:225; constants.py:714,743 | rule | Verified
Literals outside constants.py: `or 7.0` Bunker range, `< 3`, `< 8`, `> 2.0`, `22.4`; ORACLE_BEAM_MIN_ENERGY=50 and the 43 s Phoenix life are unit stats typed in. Low impact.

INT-10 | ares_bridge.py:75-76,126-129 | dead | Verified
LATCHES are read and logged only; nothing else uses them.

Docs: STATUS.md:323 stale (AIR_HARASS now exists). DESIGN §4.2 still says ares triggers are Uncertain although ARES_INTEL (constants.py:38-111) is filled and matches intel_manager.py (windows and "on read" latching checked).

## ares flags vs intel_manager.py (all names exist on the mediator)
worker_rushed (:441-449 >6 workers in 15/16 range, t<180; latched; bridge window (0,180)); ling (:431-441, latched); roach (:443-462, latched); went_reaper (:402-407, any time, latched; bridge uses BRIDGE_RAISE_UNTIL_S=330); ravager_rush (:300-314, t<240, NOT latched); marine_rush (:253-298, False after t>210/factory/2 townhalls; latch went_marine_rush set only on read); marauder_rush (:194-223, t<=240); four_gate (:225-251, counts GATEWAY only, t<200/210); is_proxy_zealot (:367-394, t<=240, not latched). Only the worker/ling/roach/reaper flags and the went_* latches never reset; bridge handles it by TTL. Flags are read every INTEL_EVERY_STEPS=8 steps (config GameStep 2 => ~0.7 s); on-read latches therefore only update then.

## Capability summary

Threat flags (threat_flags.py:33-47; raisers):
- WORKER_RUSH: ares worker_rushed (ares_bridge.py:49), detectors.py:329 (>=5 in main, <2:00). UNIT, TTL 20 s.
- CANNON_RUSH: cannon_structures (detectors.py:348, Pylon/Forge/Cannon within 25 of main/nat, <4:00); cannon_probe (:372-390, 1:00-3:00, 10 s); forge_first (:392).
- POOL_12: early_pool (:449-483) STRUCTURE, early_lings (:485-492) UNIT, ares ling (bridge :53).
- PROXY: proxy_missing (:502-577), proxy_structure (:579-593), ares marine/reaper/proxy-zealot bridges (:63-73).
- ONE_BASE_ALLIN: no_natural (:647), ares roach/ravager/marine/marauder (UNIT) and four_gate (STRUCTURE).
- AIR_HARASS: air_tech (:609). CAPITAL_AIR: tech WARNING (:617) and units ACTIVE (:619-632). UNKNOWN_AGGRO: scout_killed (:429, from scout_planner.py:317-321). ARMY_OUT_OF_POSITION: army_position.py:170 (via counterattack.py:202).
- Never raised: DT, TIMING_ATTACK, MACRO.
§4.4 rows with no (or partial) detector: 5, 6, 8 partial (INT-2); 9 (INT-7); 12 DT; 14 MACRO; 16 TIMING_ATTACK. Rows 1-4, 7, 10, 11, 13, 15, 17, 18 present.

Scouting as built (scout_planner.py, constants.py:640-760):
- All: main probe = opener's `16 worker_scout` (protoss_builds.yml:56 etc., about Gateway time; fallback 0:45) -> enemy natural -> lap of main (<=50 s) -> hold at natural until natural_resolved or 2:45(+30 s) -> proxy spots near our natural -> home (scout_tasks.py:247-333). Patrol probe 1:00-1:40 if enemy main has no Barracks/Gateway, or Forge-first (:306-315). Retry probe once if main unscouted before 2:30.
- PvT: Adept shade into main at Core+40 s; Observer post (35% from enemy nat toward ours) from Robo+30 s to 6:00; Hallucinated Phoenix 5:30 only if a Sentry exists.
- PvZ: Adept shade 3:00; Oracle 3:45 (only if the opener built one: schedule item at 165 s); nothing else scheduled.
- PvP: Stalker poke at enemy natural Core+30 s (does not see the main); Observer at enemy-nat choke after Robo to 6:00; home Observer if Twilight seen.
- Random: probe; after race resolves, matchup rows. The vRandom openers build a Stalker, not an Adept (protoss_builds.yml:158,173), so vs Terran/Zerg-Random the adept_shade finds no Adept and is skipped after 90 s (Likely).
- Re-seeing after 5:00: expansion checks every 60 s from 4:30 (scout_planner.py:431-463); probes exclude the enemy main and natural (:476), and ares' enemy_expansions list already excludes the main (terrain_manager.py:547) and unpathable (island) bases. Enemy main: only the §5 rescout (:505-510), needs a FREE Observer, only after 3:00 and only when main unseen >60 s; with OBSERVER_COUNT=2 and the army taking one from 6:00 (army.py:785-798) there is one free Observer shared by rescout, expansion trips, stale-evidence trips and end-game hunt; observer_trip_ok (:160-165) stops it going on expansion trips when the main is due. Realistic main/natural/third revisit: >= 100-150 s each, none after the Observer dies until it is rebuilt; no Pylon/probe/watchtower vision; no attack-path posts after 6:00.
- Enemy army position: ArmyPosition.update (army_position.py:141-171) from ares' army cache (remembered, age-weighted); the flag needs >=60% of value seen within 15 s, so it only works while something sees the army (army Observer, fights).

Tech -> response and delay: Stargate/Spire/StarportTechLab -> AIR_HARASS -> Forge + Pylon/Cannon/Battery per mineral line (defense_planner.py:443-452, static_defense.py:254-305); Fleet Beacon/Fusion Core/Greater Spire -> CAPITAL_AIR WARNING (Stargate early, Blink) and ACTIVE by value. Robotics/Twilight/Dark Shrine: no response except PvP home Observer. Delay: the lap sees what exists at ~1:30-2:30; a Stargate/Starport/Dark Shrine started after ~2:30 is not seen until the first Adept shade (~3:30), Oracle (~4:00) or first free Observer rescout (~4:30-5:30, and see INT-3), so tech typically arrives 2-3 min after it is built; Oracles/Banshees/DTs are often already out.

Harassment while it happens: only reactive, no intel flag. Army._home_threat (army.py:500-560) takes visible enemy units within ARMY_DEFEND_RADIUS=22 of a base (constants.py:440) or lone workers within 12 (:588) and sends the DEFEND squad; relies on vision from own buildings/units; OVERLORD/OBSERVER/changeling are HARMLESS (army.py:107-115) so Overlord/Overseer drop carriers are ignored until their cargo lands. No detection of an approaching drop/Warp Prism/Medivac, no worker-death counter (main.py:346 only drops a dead builder's order, static_defense.py:367; main.py:371-376 only cancels unfinished structures, worker_defense.py:251). Lings in mineral line only while POOL_12 is active (worker_defense.py:211-245).

enemy_mix.py -> production: EnemyMixTracker.update (main.py:200) feeds three ShareSwitches: vs_bio (Terran only, share >=0.5 -> +10% Archon, production.py:426), vs_zealots (Protoss only, >=0.3 -> +10% Archon, :428), air (>=0.3 on, <0.15 off after 60 s) which changes mix only with AIR_HARASS active (mix_mode, :148-156) or for Zerg's Templar-to-Stalker swap (:159-169, :452); capital_value drives CAPITAL_AIR ACTIVE (detectors.py:621). Not recognised: Zerg ground comps (Roach/Hydra, Ling/Bane, Lurker, Swarm Host, Infestor), Terran mech (tanks/Thor/Hellbat) and Marauder-heavy, Protoss Colossus/Immortal/Disruptor/DT/Archon or Stargate comps without a Stargate seen, cloaked units, mass reactor-air Terran, Mutalisk-only air vs P/T (no Spire/Stargate-type flag path for Terran Viking/Liberator). Banelings weigh 0 (INT-6).

## Files read fully
bot/intel/{ares_bridge,army_position,detectors,enemy_mix,scout_planner,scout_tasks,threat_flags}.py; bot/main.py; ares intel_manager.py; spec §4.2-4.4, §5; the intel-related parts of constants.py (ARES_INTEL, 470-560, 625-760, 810-880, 905-945, 1005-1030) and army.py/production.py/defense_planner.py excerpts.

## Library calls checked and found correct (names)
mediator: get_enemy_worker_rushed, get_enemy_ling_rushed, get_enemy_roach_rushed, get_enemy_ravager_rush, get_enemy_marine_rush, get_enemy_marauder_rush, get_enemy_four_gate, get_enemy_went_reaper, get_is_proxy_zealot, get_enemy_went_{marine_rush,marauder_rush,four_gate}, get_enemy_nat/third/ramp/expansions, get_own_nat, get_cached_enemy_army, get_map_data_object, select_worker(target_position), find_path_next_point, find_raw_path, is_position_safe, get_is_detected, get_air_grid/get_ground_grid/get_cached_ground_grid, assign_role, get_units_from_role(role, unit_type), get_own_structures_dict. KeepUnitSafe(unit, grid).execute(ai, config, mediator). python-sc2: Unit.is_memory/age/abilities/is_hallucination/shield_health_percentage/order_target/ground_range/air_range/can_attack_*/radius/build_progress/movement_speed/is_biological, bot.calculate_unit_value, is_visible, get_terrain_z_height, in_pathing_grid, enemy_race (updates from Random, bot_ai_internal.py:733), unit_tag_dict (ares main.py:124). UnitTypeId/AbilityId names used by scouts all exist.

## Not checked
No game can run (SC2 absent), so timings (Observer travel, lap times, when tech first becomes visible) are estimated from constants, not measured. Whether ares' `get_units_in_range` for the worker-rush flag includes remembered units (constants.py:43 says it does) was not traced. Telemetry/defense modules were read only where they consume intel output.
