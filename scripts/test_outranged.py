"""M7 staged tests: our army at its hold point under fire from out-ranging air (docs/M7_PLAN.md
B2 and C1; DESIGN.md §4.5.2-4.5.3).

    poetry run python scripts/test_outranged.py [--case idle_hold|hold_vs_tempest|committed] [--map PylonAIE_v4]

One local game (realtime=False) of Citadel against `TempestEnemy`, a scripted Protoss bot that
only holds the Tempests the test gives it in place (hold position: they shoot what comes into
their reach and never move). Setup with debug commands (dev only; scripts/ is not in the ladder
zip):
- a Nexus of ours at our natural, so the army's anchor (the defensive position) is the natural
  moved toward the enemy, outside our main;
- STALKERS Stalkers of ours at the anchor;
- TEMPESTS Tempests TEMPEST_DIST from the anchor toward the enemy main: just outside
  HOLD_ENGAGE_RADIUS, so the holding squad's micro leaves them alone, but in reach of the
  Stalkers on that side. With this many, home defense holds rather than engages (logged).

Case `idle_hold` (B2's VERIFY: does a unit standing at its hold point get drawn out after an
attacker beyond the leash?): watch WATCH_S, or until every Stalker is dead. FAIL if a Stalker gets
closer to the Tempests than CHASE_MARGIN inside the anchor's starting distance (drawn out).
Reports each Stalker's closest approach, its orders then, deaths, and whether the Tempests took
damage.

Case `hold_vs_tempest` (C1, same set-up): also FAIL if more than HOLD_MAX_DEATHS Stalkers die, or
if the defensive position doesn't move back from the Tempests by at least HOLD_FALLBACK_STEP
(units not committed step out of out-rangers' reach; the position falls back).

Case `committed` (C1): COMMITTED_STALKERS Stalkers and COMMITTED_TEMPESTS Tempests, so home
defense engages. FAIL if home defense doesn't engage or no Tempest dies within WATCH_S: committed
units keep fighting.
"""

import argparse
import os
import sys
from pathlib import Path
from typing import Optional

ROOT: Path = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

import run  # noqa: E402,F401  (puts ares-sc2 on sys.path)
from sc2.bot_ai import BotAI  # noqa: E402
from sc2.data import Race  # noqa: E402
from sc2.ids.unit_typeid import UnitTypeId  # noqa: E402
from sc2.player import Bot  # noqa: E402
from sc2.position import Point2  # noqa: E402

from bot.constants import HOLD_ENGAGE_RADIUS, HOLD_FALLBACK_STEP  # noqa: E402
from bot.main import CitadelBot  # noqa: E402
from scripts.run_matches import run_bot_game  # noqa: E402

OWN, ENEMY = 1, 2
CASES = ("idle_hold", "hold_vs_tempest", "committed")
STALKERS: int = 6
TEMPESTS: int = 10
COMMITTED_STALKERS: int = 12
COMMITTED_TEMPESTS: int = 2
HOLD_MAX_DEATHS: int = 2
TEMPEST_DIST: float = HOLD_ENGAGE_RADIUS + 0.5  # from the anchor, toward the enemy main
CHASE_MARGIN: float = 4.0
SETTLE_STEPS: int = 24  # after our Nexus exists, before the army spawns (the anchor moves to the natural)
WATCH_S: float = 40.0
TIME_LIMIT_S: int = 4 * 60


class TempestEnemy(BotAI):
    """Puts every Tempest it gets on hold position; does nothing else."""

    def __init__(self) -> None:
        super().__init__()
        self.held: set[int] = set()

    async def on_step(self, iteration: int) -> None:
        for t in self.units(UnitTypeId.TEMPEST):
            if t.tag not in self.held:
                t.hold_position()
                self.held.add(t.tag)


class StagedCitadel(CitadelBot):
    def __init__(self, case: str):
        super().__init__()
        self.case = case
        self.phase = "nexus"
        self.finished = False
        self.lines: list[str] = []
        self.verdict: list[tuple[str, bool, str]] = []
        self.anchor_at_spawn: Optional[Point2] = None
        self.spawned: int = 0
        self.watch_from: Optional[float] = None
        self.nexus_at: Optional[int] = None
        self.stalkers: dict[int, dict] = {}  # tag -> {"near": closest to the Tempests, "orders": str, "dead": bool}
        self.tempest_damaged: bool = False
        self.tempests_dead: int = 0
        self.tempest_spot: Optional[Point2] = None
        self.defend_states: set[str] = set()
        self.anchor_moved: float = 0.0  # how much farther from the Tempests the anchor got

    def log(self, text: str) -> None:
        line = f"[{self.time_formatted}] {text}"
        self.lines.append(line)
        print(f"CHECK {line}", flush=True)

    async def on_step(self, iteration: int) -> None:
        await super().on_step(iteration)
        if self.finished:
            return
        if self.phase == "nexus":
            if iteration >= 2:
                await self.client.debug_create_unit([[UnitTypeId.NEXUS, 1, self.mediator.get_own_nat, OWN]])
                self.nexus_at = iteration
                self.phase = "settle"
            return
        if self.phase == "settle":
            if iteration >= self.nexus_at + SETTLE_STEPS:
                anchor = self.army.anchor
                spot = anchor.towards(self.enemy_start_locations[0], TEMPEST_DIST)
                stalkers, tempests = (COMMITTED_STALKERS, COMMITTED_TEMPESTS) if self.case == "committed" else (STALKERS, TEMPESTS)
                await self.client.debug_create_unit(
                    [[UnitTypeId.STALKER, stalkers, anchor, OWN], [UnitTypeId.TEMPEST, tempests, spot, ENEMY]]
                )
                self.anchor_at_spawn, self.tempest_spot, self.spawned = anchor, spot, stalkers
                self.log(
                    f"setup: {stalkers} Stalkers at the anchor {anchor.rounded} (natural {self.mediator.get_own_nat.rounded}); "
                    f"{tempests} Tempests on hold position at {spot.rounded}, {TEMPEST_DIST:g} from it"
                )
                self.phase = "spawned"
            return
        if self.phase == "spawned":
            fresh = [u for u in self.units(UnitTypeId.STALKER) if u.distance_to(self.anchor_at_spawn) < 6]
            if len(fresh) >= self.spawned:
                start = self.anchor_at_spawn.distance_to(self.tempest_spot)
                for u in fresh:
                    self.stalkers[u.tag] = {"near": start, "orders": "", "dead": False}
                self.watch_from = self.time
                self.phase = "watch"
            return
        self.watch()
        alive = [tag for tag, s in self.stalkers.items() if not s["dead"]]
        if not alive or self.time - self.watch_from >= WATCH_S:
            self.judge()
            await self.end()

    def watch(self) -> None:
        spot = self.tempest_spot
        for tag, s in self.stalkers.items():
            if s["dead"]:
                continue
            u = self.unit_tag_dict.get(tag)
            if u is None:
                s["dead"] = True
                self.log(f"Stalker {tag} died (closest {s['near']:.1f} to the Tempests)")
                continue
            d = u.distance_to(spot)
            if d < s["near"]:
                order = u.orders[0].ability.id.name if u.orders else "idle"
                s["near"] = d
                s["orders"] = f"{order}, engaged_target={'yes' if u.engaged_target_tag else 'no'}, intent={self.army.intents.get(tag, ('-',))[0]}"
        for t in self.enemy_units(UnitTypeId.TEMPEST):
            if not t.is_memory and t.health + t.shield < t.health_max + t.shield_max:
                self.tempest_damaged = True
        self.anchor_moved = max(
            self.anchor_moved, self.army.anchor.distance_to(spot) - self.anchor_at_spawn.distance_to(spot)
        )
        state = self.army._defend_state
        if state and state not in self.defend_states:
            self.defend_states.add(state)
            self.log(f"home defense: {state}")

    def judge(self) -> None:
        start = self.anchor_at_spawn.distance_to(self.tempest_spot)
        limit = start - CHASE_MARGIN
        closest = min(self.stalkers.values(), key=lambda s: s["near"], default=None)
        dead = sum(s["dead"] for s in self.stalkers.values())
        tempests_left = len(self.enemy_units(UnitTypeId.TEMPEST))
        spawned_tempests = COMMITTED_TEMPESTS if self.case == "committed" else TEMPESTS
        checks = []
        for tag, s in self.stalkers.items():
            self.log(f"Stalker {tag}: closest {s['near']:.1f} to the Tempests ({s['orders']}){' dead' if s['dead'] else ''}")
        engaged = any(s.startswith("engage") for s in self.defend_states)
        states = ", ".join(sorted(self.defend_states)) or "no threat"
        if self.case == "committed":
            checks.append(("home defense engaged", engaged, states))
            checks.append((
                "committed Stalkers killed a Tempest", tempests_left < spawned_tempests,
                f"{spawned_tempests - tempests_left} of {spawned_tempests} Tempests dead; Stalkers dead {dead}/{len(self.stalkers)}",
            ))
        else:
            drawn = [s for s in self.stalkers.values() if s["near"] < limit]
            checks.append((
                f"no Stalker drawn toward the Tempests (closer than {limit:.1f})",
                not drawn,
                f"{len(drawn)} of {len(self.stalkers)}; closest {closest['near']:.1f}" if closest else "no Stalkers",
            ))
            checks.append(("home defense held (did not engage)", not engaged, states))
            if self.case == "hold_vs_tempest":
                checks.append((f"at most {HOLD_MAX_DEATHS} Stalkers died", dead <= HOLD_MAX_DEATHS, f"{dead}/{len(self.stalkers)}"))
                checks.append((
                    f"the defensive position moved back at least {HOLD_FALLBACK_STEP:g}",
                    self.anchor_moved >= HOLD_FALLBACK_STEP, f"{self.anchor_moved:.1f} farther from the Tempests",
                ))
        self.log(f"Tempests damaged: {self.tempest_damaged}; Tempests left {tempests_left}; Stalkers dead: {dead}/{len(self.stalkers)}")
        self.verdict = checks

    async def end(self) -> None:
        if not self.finished:
            self.finished = True
            await self.client.leave()


def run_case(case: str, map_name: str) -> bool:
    ours = StagedCitadel(case)
    print(f"\n=== case {case} on {map_name} ===", flush=True)
    try:
        run_bot_game(map_name, [Bot(Race.Protoss, ours, "Citadel"), Bot(Race.Protoss, TempestEnemy(), "StagedEnemy")], None, TIME_LIMIT_S)
    except Exception as e:  # noqa: BLE001
        # leaving the game after the checks sometimes closes the connection with an error
        if not ours.finished:
            print(f"CHECK case {case}: game error {e!r}")
            return False
        print(f"CHECK case {case}: (connection closed after leaving: {e!r})")
    if not ours.verdict:
        ours.judge()
    ok = all(good for _, good, _ in ours.verdict)
    for name, good, detail in ours.verdict:
        print(f"CHECK {case}: {'PASS' if good else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
    print(f"CHECK case {case}: {'PASS' if ok else 'FAIL'}", flush=True)
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--case", choices=CASES + ("all",), default="all")
    parser.add_argument("--map", default="PylonAIE_v4")
    args = parser.parse_args()
    cases = CASES if args.case == "all" else (args.case,)
    results = {case: run_case(case, args.map) for case in cases}
    print("\n" + "\n".join(f"CHECK SUMMARY {case}: {'PASS' if ok else 'FAIL'}" for case, ok in results.items()))
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
