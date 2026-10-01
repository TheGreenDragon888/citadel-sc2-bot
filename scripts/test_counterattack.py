"""M5 staged tests of the §4.6 counterattack (DESIGN.md §8 "staged counterattack tests").

    poetry run python scripts/test_counterattack.py [--case all|return|timeout|defense|abort|in_position]
                                                    [--map PylonAIE_v4]

Each case is one local game (realtime=False) of Citadel against `StagedEnemy`, a scripted Terran
bot that only mines and moves the units it is given. The setup uses debug commands (dev only;
scripts/ is not in the ladder zip), at the start of the game:
- enemy bases: its main, plus a natural Command Center with 6 SCVs and no defence; the main gets
  2 Bunkers and 6 Marines, so the natural is the base with the lowest local defence;
- the enemy army: 16 Marines and 4 Marauders (1300 value) at a spot at least SPOT_MIN_PATH ground
  path from both enemy townhalls, away from our bases and from the way between the two naturals
  (`in_position`: next to the enemy natural instead);
- our army at the defensive position: 6 Adepts, 6 Stalkers and 4 Immortals (40 supply), and an
  Observer the test keeps over the enemy army (`CitadelBot.external_tags`, so the army and the scout
  planner leave it alone);
- the map is revealed for a few steps so the enemy structures are known (they stay as snapshots).
COUNTER_FROM_S is shortened to TEST_COUNTER_FROM_S inside this test only.

Every positive case must:
1. raise ARMY_OUT_OF_POSITION and launch a counterattack at the enemy natural;
2. take a squad of Adepts first, then Stalkers (no Immortals), of at least 8 supply and at most 35%
   of our army supply, with no unit the test holds;
3. recall for the case's reason (below);
4. bring the squad home: every survivor within HOME_RADIUS of the defensive position, or at least
   half way back from where it was at the recall, within HOME_TIMEOUT_S.
Cases:
- `return`: once the squad is near the target, the enemy army walks back to it -> "enemy army within".
- `timeout`: the enemy army stays away -> "out for" (> 60 s); the first enemy the squad kills
  at the base must be a worker.
- `defense`: once the squad is well on its way, a strong enemy force appears in our main ->
  "defense" (a home threat the units left at home can't hold).
- `abort`: as the squad nears the target, Marauders and sieged Tanks appear there -> "level".
- `merge`: once the squad is out, the main attack's supply gate is lowered so it launches -> the
  squad joins the ATTACK squad ("merged"), with no recall (§4.6 interactions).
Negative cases (no trigger, no launch):
- `in_position`: the enemy army waits next to its natural, watched until NEGATIVE_WATCH_S after
  TEST_COUNTER_FROM_S.
- `early`: the real COUNTER_FROM_S (5:00) is kept; watched until EARLY_WATCH_S.
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

import bot.army.army as army_module  # noqa: E402
import bot.army.attack_decision as decision_module  # noqa: E402
import bot.army.counterattack as counter_module  # noqa: E402
from bot.army.counterattack import OUT  # noqa: E402
from bot.army.squads import Role  # noqa: E402
from bot.constants import (  # noqa: E402
    ATTACK_START_SUPPLY,
    COUNTER_FROM_S,
    COUNTER_SQUAD_MAX_FRACTION,
    COUNTER_SQUAD_MIN_SUPPLY,
)
from bot.intel.threat_flags import Threat  # noqa: E402
from bot.main import CitadelBot  # noqa: E402
from scripts.run_matches import run_bot_game  # noqa: E402

OWN, ENEMY = 1, 2
CASES = ("return", "timeout", "defense", "abort", "merge", "in_position", "early")
NEGATIVE = ("in_position", "early")
EARLY_WATCH_S: float = 90.0
MERGE_ATTACK_SUPPLY: int = 20  # `merge`: the main attack's supply gate while the squad is out
TEST_COUNTER_FROM_S: float = 30.0
TIME_LIMIT_S: int = 6 * 60
SPOT_MIN_PATH: float = 75.0  # the enemy army's spot: at least this far (ground path) from its townhalls ...
SPOT_MIN_FROM_US: float = 50.0  # ... this far from our start and natural ...
SPOT_MIN_FROM_ROUTE: float = 20.0  # ... and this far from the line between the two naturals
HOME_RADIUS: float = 20.0
HOME_TIMEOUT_S: float = 60.0
NEGATIVE_WATCH_S: float = 60.0
RETURN_TRIGGER_DIST: float = 25.0  # `return`: the enemy army turns back once the squad is this close to the target
DEFENSE_AFTER_S: float = 15.0  # `defense`: the home attackers appear in our main this long after the launch
ABORT_TRIGGER_DIST: float = 30.0  # `abort`: the defenders appear once the squad is this close to the target

ARMY = [(UnitTypeId.MARINE, 16), (UnitTypeId.MARAUDER, 4)]
HOME_ATTACK = [(UnitTypeId.MARAUDER, 16), (UnitTypeId.MARINE, 12), (UnitTypeId.SIEGETANKSIEGED, 3)]
DEFENDERS = [(UnitTypeId.MARAUDER, 10), (UnitTypeId.SIEGETANKSIEGED, 3)]
OURS = [(UnitTypeId.ADEPT, 6), (UnitTypeId.STALKER, 6), (UnitTypeId.IMMORTAL, 4)]


class Script:
    """Orders the test gives the enemy bot, by unit group (the group is the nearest spawn point)."""

    def __init__(self) -> None:
        self.spawns: dict[str, Point2] = {}
        self.orders: dict[str, tuple[str, Point2]] = {}  # group -> ("hold" | "attack", point)
        self.groups: dict[int, str] = {}  # enemy unit tag -> group


class StagedEnemy(BotAI):
    """Mines with its SCVs; moves its other units as `script` says, nothing else."""

    def __init__(self, script: Script):
        super().__init__()
        self.script = script

    async def on_step(self, iteration: int) -> None:
        if iteration % 8 == 0:
            await self.distribute_workers()
        script = self.script
        for u in self.units:
            if u.type_id == UnitTypeId.SCV or u.tag in script.groups or not script.spawns:
                continue
            script.groups[u.tag] = min(script.spawns, key=lambda g: script.spawns[g].distance_to(u))
        for u in self.units:
            group = script.groups.get(u.tag)
            if group is None or group not in script.orders:
                continue
            verb, point = script.orders[group]
            if u.type_id == UnitTypeId.SIEGETANKSIEGED:
                continue
            if verb == "attack":
                if not u.orders or u.distance_to(point) > 3 and u.order_target != point:
                    u.attack(point)
            elif u.distance_to(point) > 6 and not u.orders:
                u.move(point)


class StagedCitadel(CitadelBot):
    def __init__(self, case: str, script: Script):
        super().__init__()
        self.case = case
        self.script = script
        self.phase = "setup"
        self.lines: list[str] = []
        self.spot: Optional[Point2] = None
        self.observer: Optional[int] = None
        self.launched: Optional[dict] = None
        self.recalled: Optional[dict] = None
        self.home_result: Optional[str] = None
        self.event_done = False
        self.finished = False
        self.verdict: list[tuple[str, bool, str]] = []

    def log(self, text: str) -> None:
        line = f"[{self.time_formatted}] {text}"
        self.lines.append(line)
        print(f"CHECK {line}", flush=True)

    # -- setup -----------------------------------------------------------------------------------

    def path_length(self, a: Point2, b: Point2) -> float:
        path = self.mediator.find_raw_path(start=a, target=b, grid=self.mediator.get_cached_ground_grid, sensitivity=1)
        if not path:
            return float("inf")
        total, prev = 0.0, a
        for p in path:
            total += prev.distance_to(p)
            prev = p
        return total

    def army_spot(self) -> Point2:
        enemy_bases = [self.enemy_start_locations[0], self.mediator.get_enemy_nat]
        if self.case == "in_position":
            spot = self.mediator.get_enemy_nat.towards(self.game_info.map_center, 14)
            return spot if self.in_pathing_grid(spot) else self.mediator.get_enemy_nat.towards(self.game_info.map_center, 10)
        ours = [self.start_location, self.mediator.get_own_nat]
        a, b = self.mediator.get_own_nat, self.mediator.get_enemy_nat
        candidates = list(self.expansion_locations_list) + [
            Point2(r.center) for r in self.mediator.get_map_data_object.regions.values()
        ]
        best: Optional[tuple[float, Point2]] = None
        for p in candidates:
            if not self.in_pathing_grid(p) or min(p.distance_to(o) for o in ours) < SPOT_MIN_FROM_US:
                continue
            route = _segment_distance(p, a, b)
            if route < SPOT_MIN_FROM_ROUTE:
                continue
            if min(self.path_length(p, e) for e in enemy_bases) < SPOT_MIN_PATH:
                continue
            if best is None or route > best[0]:
                best = (route, p)
        if best is None:
            raise RuntimeError("no spot for the enemy army on this map")
        return best[1]

    def home_attack_spot(self) -> Point2:
        """Inside our main, toward its mineral line (away from the squad's way out)."""
        return self.start_location.towards(self.main_base_ramp.top_center, -6)

    async def setup(self) -> None:
        enemy_main = self.enemy_start_locations[0]
        enemy_nat = self.mediator.get_enemy_nat
        self.spot = self.army_spot()
        ramp_side = enemy_main.towards(self.game_info.map_center, 7)
        anchor = self.army.anchor
        self.script.spawns = {"army": self.spot, "main": ramp_side, "home_attack": self.home_attack_spot(), "defenders": enemy_nat}
        self.script.orders = {"army": ("hold", self.spot), "main": ("hold", ramp_side)}
        create = [
            [UnitTypeId.COMMANDCENTER, 1, enemy_nat, ENEMY],
            [UnitTypeId.SCV, 6, enemy_nat.towards(enemy_main, 3), ENEMY],
            [UnitTypeId.BUNKER, 1, ramp_side.towards(enemy_main, -2).offset((3, 0)), ENEMY],
            [UnitTypeId.BUNKER, 1, ramp_side.towards(enemy_main, -2).offset((-3, 0)), ENEMY],
            [UnitTypeId.MARINE, 6, ramp_side, ENEMY],
            [UnitTypeId.OBSERVER, 1, self.spot, OWN],
        ]
        create += [[t, n, self.spot, ENEMY] for t, n in ARMY]
        create += [[t, n, anchor, OWN] for t, n in OURS]
        await self.client.debug_create_unit(create)
        self.log(
            f"setup: enemy army ({', '.join(f'{n} {t.name}' for t, n in ARMY)}) at {self.spot.rounded} "
            f"(path {min(self.path_length(self.spot, e) for e in (enemy_main, enemy_nat)):.0f} from its townhalls); "
            f"enemy natural CC + 6 SCVs at {enemy_nat.rounded}; 2 Bunkers + 6 Marines in the main; our army at {anchor.rounded}"
        )

    # -- per step --------------------------------------------------------------------------------

    def squad_units(self) -> list:
        return self.army.squads.units(Role.HARASS)

    async def on_step(self, iteration: int) -> None:
        await super().on_step(iteration)
        if self.finished:
            return
        if self.phase == "setup":
            if iteration >= 2:
                await self.setup()
                self.phase = "reveal"
            return
        if self.phase == "reveal":
            await self.client.debug_show_map()
            self.phase = "unreveal"
            self.reveal_at = iteration
            return
        if self.phase == "unreveal":
            if iteration >= self.reveal_at + 6:
                await self.client.debug_show_map()
                self.phase = "watch"
            return
        # the Observer: found once, then kept over the enemy army
        if self.observer is None:
            obs = [u for u in self.units(UnitTypeId.OBSERVER) if self.spot is not None and u.distance_to(self.spot) < 5]
            if obs:
                self.observer = obs[0].tag
                self.external_tags = {self.observer}
        else:
            obs = self.unit_tag_dict.get(self.observer)
            enemy = [u for u in self.enemy_units if not u.is_memory and u.type_id in (UnitTypeId.MARINE, UnitTypeId.MARAUDER)]
            follow = [u for u in enemy if self.script.orders.get("army", ("", None))[0] == "attack" or u.distance_to(self.spot) < 20]
            if obs is not None and iteration % 4 == 0:
                goal = Point2.center([u.position for u in follow]) if follow else self.spot
                if obs.distance_to(goal) > 2:
                    obs.move(goal)
        await self.watch()

    async def watch(self) -> None:
        counter = self.army.counter
        now = self.time
        if self.case in NEGATIVE:
            if now > (EARLY_WATCH_S if self.case == "early" else TEST_COUNTER_FROM_S + NEGATIVE_WATCH_S):
                raised = self.flags.was_raised(Threat.ARMY_OUT_OF_POSITION)
                reading = counter.position.last
                self.verdict = [
                    ("no ARMY_OUT_OF_POSITION", not raised, "raised" if raised else "never raised"),
                    ("no counterattack", not counter.outcomes and counter.state != OUT, f"{len(counter.outcomes)} launched"),
                ]
                if self.case == "in_position":
                    self.verdict.append(("the detector ran", reading is not None, reading.why if reading is not None else "no reading"))
                else:
                    self.verdict.append(("the detector didn't run before 5:00", reading is None, "no reading" if reading is None else reading.why))
                await self.end()
            return
        if self.launched is None and counter.state == OUT:
            squad = self.squad_units()
            supply = sum(self.calculate_supply_cost(u.type_id) for u in squad)
            army_supply = sum(
                self.calculate_supply_cost(u.type_id) for u in self.units
                if u.type_id not in (UnitTypeId.PROBE, UnitTypeId.OBSERVER) and not u.is_structure
            )
            kinds = sorted(u.type_id.name for u in squad)
            self.launched = {
                "t": now, "target": counter.target, "tags": {u.tag for u in squad}, "supply": supply,
                "army_supply": army_supply, "kinds": kinds,
            }
            raised = [r for r in self.flags.history if r.threat == Threat.ARMY_OUT_OF_POSITION]
            self.log(
                f"launch -> {counter.target.rounded}: {len(squad)} units {kinds}, {supply:g} of {army_supply:g} supply; "
                f"ARMY_OUT_OF_POSITION raised at {raised[0].raised_at:.0f} s" if raised else "launch without the flag"
            )
        if self.launched is not None and not self.event_done:
            await self.case_event()
        if self.case == "merge" and counter.outcomes:
            outcome = counter.outcomes[-1]
            tags = self.launched["tags"] if self.launched else set()
            roles = {self.army.squads.roles.get(t) for t in tags if t in self.army.squads.roles}
            self.recalled = {"t": now, "reason": outcome["reason"], "outcome": outcome, "start": {}, "roles": {}}
            self.home_result = f"squad roles after the merge: {sorted(r.value for r in roles if r)}"
            self.merged_roles = roles
            self.log(f"end: {outcome['reason']}; {self.home_result}")
            self.judge()
            await self.end()
            return
        if self.recalled is None and counter.outcomes:
            outcome = counter.outcomes[-1]
            survivors = [u for tag in self.launched["tags"] if (u := self.unit_tag_dict.get(tag)) is not None] if self.launched else []
            self.recalled = {
                "t": now, "reason": outcome["reason"], "outcome": outcome,
                "start": {u.tag: u.distance_to(self.army.anchor) for u in survivors},
                "roles": {u.tag: self.army.squads.roles.get(u.tag) for u in survivors},
            }
            self.log(f"recall: {outcome['reason']} (out {outcome['launched']:.0f}-{outcome['ended']:.0f} s, "
                     f"killed {outcome['workers_killed']} workers, first kill {outcome['first_kill']})")
        if self.recalled is not None and self.home_result is None:
            survivors = [u for tag in self.recalled["start"] if (u := self.unit_tag_dict.get(tag)) is not None]
            anchor = self.army.anchor
            home = [
                u for u in survivors
                if u.distance_to(anchor) <= HOME_RADIUS or u.distance_to(anchor) <= 0.5 * self.recalled["start"][u.tag]
            ]
            if len(home) == len(survivors):
                self.home_result = f"{len(survivors)} survivors home after {now - self.recalled['t']:.0f} s"
            elif now - self.recalled["t"] > HOME_TIMEOUT_S:
                self.home_result = f"FAIL: {len(home)}/{len(survivors)} survivors home after {HOME_TIMEOUT_S:g} s"
            if self.home_result is not None:
                self.log(f"home: {self.home_result}")
                self.judge()
                await self.end()
        if now > TIME_LIMIT_S - 5:
            self.judge()
            await self.end()

    async def case_event(self) -> None:
        counter = self.army.counter
        squad = self.squad_units()
        center = Point2.center([u.position for u in squad]) if squad else None
        target = self.launched["target"]
        if self.case == "return":
            if center is not None and center.distance_to(target) <= RETURN_TRIGGER_DIST:
                self.script.orders["army"] = ("attack", target)
                self.event_done = True
                self.log(f"event: the enemy army walks back to {target.rounded}")
        elif self.case == "defense":
            if self.time - self.launched["t"] >= DEFENSE_AFTER_S:
                spot = self.home_attack_spot()
                await self.client.debug_create_unit([[t, n, spot, ENEMY] for t, n in HOME_ATTACK])
                self.script.orders["home_attack"] = ("attack", self.start_location)
                self.event_done = True
                self.log(
                    f"event: {', '.join(f'{n} {t.name}' for t, n in HOME_ATTACK)} in our main {spot.rounded}; "
                    f"squad at {center.rounded if center is not None else '-'}"
                )
        elif self.case == "merge":
            army_module.ATTACK_START_SUPPLY = MERGE_ATTACK_SUPPLY
            decision_module.ATTACK_START_SUPPLY = MERGE_ATTACK_SUPPLY
            self.event_done = True
            self.log(f"event: main attack supply gate lowered to {MERGE_ATTACK_SUPPLY}")
        elif self.case == "abort":
            if center is not None and center.distance_to(target) <= ABORT_TRIGGER_DIST:
                await self.client.debug_create_unit([[t, n, target, ENEMY] for t, n in DEFENDERS])
                self.script.orders["defenders"] = ("hold", target)
                self.event_done = True
                self.log(f"event: {', '.join(f'{n} {t.name}' for t, n in DEFENDERS)} at the target")
        else:
            self.event_done = True
        if counter.state != OUT and not self.event_done:
            self.event_done = True  # recalled before the event

    def judge(self) -> None:
        launched = self.launched
        recalled = self.recalled
        checks: list[tuple[str, bool, str]] = []
        raised = self.flags.was_raised(Threat.ARMY_OUT_OF_POSITION)
        checks.append(("ARMY_OUT_OF_POSITION raised", raised, ""))
        checks.append(("counterattack launched", launched is not None, ""))
        if launched is not None:
            nat = self.mediator.get_enemy_nat
            checks.append(("target is the enemy natural", launched["target"].distance_to(nat) < 6,
                           f"{launched['target'].rounded} vs natural {nat.rounded}"))
            kinds = launched["kinds"]
            adepts_first = "STALKER" not in kinds or kinds.count("ADEPT") == 6
            checks.append(("squad: Adepts first, then Stalkers, nothing else",
                           set(kinds) <= {"ADEPT", "STALKER"} and adepts_first, f"{kinds}"))
            cap = COUNTER_SQUAD_MAX_FRACTION * launched["army_supply"]
            checks.append(("squad: >= 8 supply and <= 35% of army supply",
                           COUNTER_SQUAD_MIN_SUPPLY <= launched["supply"] <= cap + 1e-6,
                           f"{launched['supply']:g} of {launched['army_supply']:g} (cap {cap:.1f})"))
            checks.append(("squad: no held unit", self.observer not in launched["tags"], ""))
        expected = {
            "return": "enemy army within", "timeout": "out for", "defense": "defense", "abort": "level", "merge": "merged",
        }[self.case]
        reason = recalled["reason"] if recalled is not None else "no recall"
        checks.append((f"recall reason '{expected}'", recalled is not None and reason.startswith(expected), reason))
        if self.case == "timeout" and recalled is not None:
            first = recalled["outcome"]["first_kill"]
            checks.append(("first kill at the base is a worker", first == "SCV", f"first kill {first}"))
        if self.case == "merge":
            roles = getattr(self, "merged_roles", set())
            checks.append(("merged squad is in the ATTACK squad", roles == {Role.ATTACK}, self.home_result or ""))
            checks.append(("main attack launched", self.army.attacking or any(a == "launch" for _, a, _, _ in self.army.decisions), ""))
            self.verdict = checks
            return
        if recalled is not None:
            roles_ok = all(r == Role.DEFEND for r in recalled["roles"].values())
            checks.append(("recalled units back in the DEFEND squad", roles_ok, ""))
        home = self.home_result or "not checked"
        checks.append(("squad home", self.home_result is not None and not home.startswith("FAIL"), home))
        self.verdict = checks

    async def end(self) -> None:
        if not self.finished:
            self.finished = True
            await self.client.leave()


def _segment_distance(p: Point2, a: Point2, b: Point2) -> float:
    ab = b - a
    length2 = ab.x * ab.x + ab.y * ab.y
    if length2 == 0:
        return p.distance_to(a)
    t = max(0.0, min(1.0, ((p.x - a.x) * ab.x + (p.y - a.y) * ab.y) / length2))
    return p.distance_to(Point2((a.x + t * ab.x, a.y + t * ab.y)))


def run_case(case: str, map_name: str) -> bool:
    counter_module.COUNTER_FROM_S = COUNTER_FROM_S if case == "early" else TEST_COUNTER_FROM_S
    army_module.ATTACK_START_SUPPLY = ATTACK_START_SUPPLY
    decision_module.ATTACK_START_SUPPLY = ATTACK_START_SUPPLY
    script = Script()
    ours = StagedCitadel(case, script)
    theirs = StagedEnemy(script)
    print(f"\n=== case {case} on {map_name} ===", flush=True)
    try:
        run_bot_game(map_name, [Bot(Race.Protoss, ours, "Citadel"), Bot(Race.Terran, theirs, "StagedEnemy")], None, TIME_LIMIT_S)
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
    positive = [c for c in results if c not in NEGATIVE and c != "merge"]
    passed = sum(results[c] for c in positive)
    others = [c for c in results if c not in positive]
    print(f"CHECK SUMMARY trigger+recall cases passed: {passed}/{len(positive)}"
          + "".join(f"; {c}: {'PASS' if results[c] else 'FAIL'}" for c in others))
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
