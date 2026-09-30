# Citadel status

Where the project stands, for picking up the next milestone. The spec is `docs/DESIGN.md`; API
findings and Citadel's choices are in `docs/VERIFY_NOTES.md`.

## Milestones

| M | State | Where |
|---|---|---|
| M0 | Done | `docs/VERIFY_NOTES.md` §11 |
| M1 | Done | openers, economy, supply, 3 bases, wall fallback (`bot/macro/`, `bot/defense/wall_fallback.py`) |
| M2 | Done (see the evidence in `docs/VERIFY_NOTES.md`, "M2 acceptance evidence") | ares bridge, detectors, ThreatFlag expiry, defense plans |
| M3 | Next | per-matchup scout planner (DESIGN.md §4.3, §7) |

## Code map (M2 additions)

| File | What it does |
|---|---|
| `bot/intel/threat_flags.py` | `FlagStore`: flags keyed by (threat, source), §5 expiry rules, history for the end-of-game report |
| `bot/intel/ares_bridge.py` | ares intel flags → ThreatFlags (`BRIDGES` table) |
| `bot/intel/detectors.py` | Citadel's detectors: worker rush, cannon structures/probe, early Pool, early lings, proxy (missing/far production), no natural; also the §5 phase rules (`expiry_context`) and scouting state (`main_scouted_at`, `enemy_workers_in_main`, `natural_seen_at`) |
| `bot/intel/scout_planner.py` | `NaturalScout`: takes ares's worker scout back after its lap and watches the enemy natural until the one-base deadline (M3 replaces/extends this) |
| `bot/defense/defense_planner.py` | active flags → one `DefensePlan` (per-threat `_plan_*`), ends the ares opener on override flags |
| `bot/defense/worker_defense.py` | probe pulls (worker rush, cannon rush, lings in a mineral line) and the cancel-when-dying rule |
| `bot/defense/static_defense.py` | main/natural Batteries, extra Gateways, Core first vs 12-pool, Cannon-range placement blocking, build-order retargeting, dead-builder handling |
| `bot/army/basic_army.py` | M1 scaffolding army plus hold point / leash, home-threat and don't-feed rules (M4 replaces the supply-count gates with `EngagementResult`) |
| `scripts/test_bots/` | scripted cheese opponents (plain python-sc2): `worker_rush`, `cannon_rush` (natural/main), `twelve_pool`, `proxy_rax` (third/center) |

Every threshold is in `bot/constants.py`.

## Test commands

| Check | Command |
|---|---|
| ThreatFlag expiry unit test (no game) | `poetry run python scripts/test_threat_flags.py` |
| M2 acceptance, one batch per cheese bot | `poetry run python scripts/run_matches.py --opponent worker_rush --map all --total 10 --seed 100` (also `cannon_rush`, `twelve_pool`, `proxy_rax`) |
| One cheese variant | add `--variant natural`/`main` (`cannon_rush`) or `third`/`center` (`proxy_rax`) |
| One-base plan vs the built-in AI | `poetry run python scripts/run_matches.py --difficulty Harder --build Rush --race Terran Zerg Protoss --map all --total 3` |
| M1 regression | `poetry run python scripts/run_matches.py --difficulty Hard --map all --total 10 --race Terran Zerg Protoss Random` |
| Wall fallback | `poetry run python scripts/test_wall_fallback.py --case ramp` (and `--case choke --map TorchesAIE_v4 --race Zerg`) |
| Opener cycling | `poetry run python scripts/test_opener_cycle.py` |
| Ladder zip | `poetry run python scripts/create_ladder_zip.py`, then `unzip -l publish/*.zip \| head` |

Four batches can run in parallel on a 4-core machine (about 40 minutes for 10 games each).
To stop batches, use a pattern that can't match your own shell, e.g.
`pkill -f "opponent twelve_poo[l]"`, in a command of its own.

## Carry-forward for M3 (scout planner)

- **What exists.** `NaturalScout` reuses ares's `worker_scout` probe (role `BUILD_RUNNER_SCOUT`,
  then `SCOUTING`). The detectors already track when the enemy main counts as scouted
  (`MAIN_SCOUTED_FRACTION` of sample points seen), enemy workers seen in the main, and when the
  enemy natural was last in vision. `FlagStore.expire` logs `RESCOUT wanted: ...` when
  structure evidence goes stale; that is the hook §5 gives the scout planner.
- **M3 acceptance needs.** `run_matches.py` already prints each game's flags (`flags=` column and
  the end-of-game `METRIC flag` lines), which covers "correct flag logged". "No scout lost
  before 4:00" needs a metric: `Telemetry.on_own_unit_destroyed` logs `PROBE lost` with the
  unit's role, so a scout loss is a `SCOUTING`/`BUILD_RUNNER_SCOUT` role in that line; other
  scout unit types need adding.
- **VERIFY items for §4.3.** `KeepUnitSafe`, `find_path_next_point` and the grid accessors are
  covered in `docs/VERIFY_NOTES.md` §11.5–§11.6; Hallucination and Revelation IDs/costs in
  §11.7. Re-check any other ares/python-sc2 call before use.
- **Detection timing depends on scouting.** POOL_12 and PROXY were raised between 1:19 and 1:44
  in M2 test games, when ares's scout reached the enemy main. A natural Nexus the opener placed
  before then is kept (§4.2 cancels or delays it only "if it is not yet started") and can die
  to the lings; earlier scouting in M3 moves the flag before the Nexus.

## Open question for the user

- **A natural Nexus started before POOL_12 is raised.** §4.2 says to "cancel or delay the natural
  Nexus if it is not yet started", so Citadel keeps one that is already placed. Both 12-pool
  acceptance losses came from it: the opener placed it at ~1:20, the Pool was seen at 1:20-1:21,
  and once the Nexus finished, ares's Mining sent probes out past the wall-gap holder to its
  minerals. Cancelling a started Nexus on the flag would refund 75% and keep probes home, but it
  goes beyond §4.2 as written, so it waits for a decision.

## Known issues (not blocking M2)

- Cannon rush, main variant, Persephone (opponent seed 106): the rusher's first Cannon finishes
  next to our main Nexus by 2:00 and six more follow; §4.2 stops the probe attack once a Cannon
  completes, and the army never gets going (the Cannons also cover a Gateway). Lost in two of
  three runs.
- M1 Hard game 9 (Ultralove vs Terran) was lost twice on intermediate commits: the army sat idle
  in "attack" state for minutes while a Terran tank/Banshee/Raven contain picked at our bases.
  It won on the final commit and a debug replay of the matchup (the AI's build is random), so
  the cause is unconfirmed. `BasicArmy` does not skip lifted (flying) Terran buildings as
  targets, which ground units can't hit; M4 replaces this army code.
- §4.4's proxy rules raise PROXY vs some built-in AI builds (no production at 1:30, or few
  workers seen by a partial scout); that costs a little economy. M3's scouting should see more.

- The PROXY plan's expansion gate and hold point have no hysteresis: with units dying and
  being replaced they flip every few seconds (seen vs Harder Rush Terran), walking the army
  between the ramp and the natural. The 12-pool gate has hysteresis (`POOL_12_GATE_HOLD_S`);
  the proxy one could use the same.
- With Zerglings loitering near our natural, POOL_12 stays active on its lings source and ares's
  expansion can stall: a Persephone 12-pool game was still on one base with 56 probes at 10:00
  (it had 131 supply and would attack at the M1 150-supply gate).
- `BasicArmy`'s engage rules count supply (`ARMY_SUPPLY_PER_CANNON`, `ARMY_ENGAGE_RATIO`, ...);
  M4's `EngagementResult` gates should replace them.
- The scripted 12-pool bot never expands or drones past 13, so it is harsher than most
  12-pools; the cannon bot builds up to 8 Cannons.
