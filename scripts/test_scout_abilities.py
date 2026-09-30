"""M3 in-game checks of the scouting abilities (DESIGN.md §4.3, §11.7), for docs/VERIFY_NOTES.md.

Plays one local game (realtime=False) as a bare AresBot (no Citadel logic, so nothing else moves
the spawned units) driven by python-sc2 debug commands. Dev-only (scripts/ is not in the ladder
zip):

    poetry run python scripts/test_scout_abilities.py [--map PylonAIE_v4]

Checks:
1. Adept shade: the ability ids on the Adept and on the shade, the shade's unit type, whether it
   takes move orders, how long it lives, whether the Adept teleports when it ends, whether
   cancelling keeps the Adept in place, and whether `on_unit_destroyed` fires for the shade.
2. Hallucination (Phoenix): how to find the new Phoenix, whether it takes move orders, how long
   it lives, and whether `on_unit_destroyed` fires for it.
3. Oracle Pulsar Beam: the on/off ability ids, the energy the activation and the beam use, and
   whether the Oracle can then attack a Drone.
4. Detection: `mediator.get_is_detected(unit=...)` for an own Observer beside an enemy Photon
   Cannon and far from it.
"""

import argparse
import os
import sys
from pathlib import Path
from typing import Callable, List, Optional

ROOT: Path = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

import run  # noqa: E402,F401  (puts ares-sc2 on sys.path)
from ares import AresBot  # noqa: E402
from sc2 import maps  # noqa: E402
from sc2.data import Difficulty, Race  # noqa: E402
from sc2.ids.ability_id import AbilityId  # noqa: E402
from sc2.ids.unit_typeid import UnitTypeId  # noqa: E402
from sc2.main import run_game  # noqa: E402
from sc2.player import Bot, Computer  # noqa: E402
from sc2.position import Point2  # noqa: E402
from sc2.unit import Unit  # noqa: E402

OWN, ENEMY = 1, 2  # debug_create_unit owner ids
DEBUG_ENERGY: int = 1  # debug_set_unit_value field
FULL_ENERGY: float = 200.0
PHASE_TIMEOUT_LOOPS: int = 22 * 60
CANCEL_AFTER_LOOPS: int = 45  # ~2 s after the second shade appears
SCOUT_ABILITIES = {
    AbilityId.ADEPTPHASESHIFT_ADEPTPHASESHIFT, AbilityId.CANCEL_ADEPTPHASESHIFT,
    AbilityId.CANCEL_ADEPTSHADEPHASESHIFT, AbilityId.BEHAVIOR_PULSARBEAMON,
    AbilityId.BEHAVIOR_PULSARBEAMOFF, AbilityId.HALLUCINATION_PHOENIX,
    AbilityId.ORACLEREVELATION_ORACLEREVELATION, AbilityId.MOVE_MOVE, AbilityId.ATTACK_ATTACK,
}


class AbilityProbe(AresBot):
    def __init__(self) -> None:
        super().__init__()
        self.phase: str = "spawn"
        self.phase_started: int = 0
        self.finished: bool = False
        self.lines: List[str] = []
        self.s: dict = {}  # per-phase scratch
        self.destroyed: dict[int, int] = {}  # tag -> loop of on_unit_destroyed

    def log(self, text: str) -> None:
        line = f"[{self.state.game_loop:>5}] {text}"
        self.lines.append(line)
        print(f"CHECK {line}", flush=True)

    def goto(self, phase: str) -> None:
        self.phase = phase
        self.phase_started = self.state.game_loop

    def timed_out(self) -> bool:
        if self.state.game_loop - self.phase_started > PHASE_TIMEOUT_LOOPS:
            self.log(f"TIMEOUT in phase `{self.phase}`")
            self.goto("finish")
            return True
        return False

    def own(self, type_id: UnitTypeId, hallucination: Optional[bool] = None) -> Optional[Unit]:
        units = self.all_own_units(type_id)
        if hallucination is not None:
            units = units.filter(lambda u: u.is_hallucination == hallucination)
        return units.first if units else None

    async def abilities(self, unit: Unit) -> list[str]:
        found = (await self.get_available_abilities([unit]))[0]
        return sorted(a.name for a in found if a in SCOUT_ABILITIES)

    async def on_unit_destroyed(self, unit_tag: int) -> None:
        await super().on_unit_destroyed(unit_tag)
        self.destroyed[unit_tag] = self.state.game_loop

    async def on_step(self, iteration: int) -> None:
        await super().on_step(iteration)
        if not self.finished:
            handler: Callable = getattr(self, f"_{self.phase}")
            await handler()

    # --- setup ------------------------------------------------------------------------------

    async def _spawn(self) -> None:
        await self.client.debug_show_map()
        centre = self.game_info.map_center
        spot = self.mediator.get_own_nat.towards(centre, 6)
        self.s["spot"] = spot
        away = centre.towards(self.start_location, 25)
        self.s["away"] = away
        cannon_at = await self.find_placement(UnitTypeId.PYLON, centre, max_distance=20)  # same 2x2 footprint; a Cannon spot needs power
        pylon_at = await self.find_placement(UnitTypeId.PYLON, cannon_at.towards(self.enemy_start_locations[0], 3), max_distance=10)
        self.s["cannon_at"] = cannon_at
        await self.client.debug_create_unit([
            [UnitTypeId.ADEPT, 1, spot, OWN],
            [UnitTypeId.SENTRY, 1, spot.towards(self.start_location, 3), OWN],
            [UnitTypeId.ORACLE, 1, away, OWN],
            [UnitTypeId.DRONE, 1, away.towards(centre, 3), ENEMY],
            [UnitTypeId.PYLON, 1, pylon_at, ENEMY],
            [UnitTypeId.PHOTONCANNON, 1, cannon_at, ENEMY],
        ])
        self.log(f"spawned; Cannon at {cannon_at.rounded}, Pylon at {pylon_at.rounded}")
        self.goto("energy")

    async def _energy(self) -> None:
        tags = [u.tag for t in (UnitTypeId.SENTRY, UnitTypeId.ORACLE) if (u := self.own(t))]
        if len(tags) < 2:
            self.timed_out()
            return
        await self.client.debug_set_unit_value(tags, DEBUG_ENERGY, FULL_ENERGY)
        self.goto("shade_cast")

    # --- 1. Adept shade -------------------------------------------------------------------------

    async def _shade_cast(self) -> None:
        adept = self.own(UnitTypeId.ADEPT)
        if adept is None or self.timed_out():
            return
        self.log(f"Adept abilities: {await self.abilities(adept)}")
        target = adept.position.towards(self.game_info.map_center, 10)
        self.s.update(adept=adept.tag, adept_pos=adept.position, cast_loop=self.state.game_loop, target=target)
        adept(AbilityId.ADEPTPHASESHIFT_ADEPTPHASESHIFT, target)
        self.goto("shade_watch")

    async def _shade_watch(self) -> None:
        adept = self.unit_tag_dict.get(self.s["adept"])
        shade = self.own(UnitTypeId.ADEPTPHASESHIFT)
        if "shade" not in self.s:
            if shade is None:
                self.timed_out()
                return
            self.s.update(shade=shade.tag, shade_seen=self.state.game_loop)
            self.log(
                f"shade appeared {self.state.game_loop - self.s['cast_loop']} loops after the cast: type "
                f"{shade.type_id.name}, abilities {await self.abilities(shade)}; Adept now {await self.abilities(adept)}"
            )
            shade.move(self.s["target"].towards(self.game_info.map_center, 8))
            return
        if shade is not None:
            self.s["shade_last"] = shade.position
            return
        moved = self.s["shade_last"].distance_to(self.s["target"])
        self.log(
            f"shade gone {self.state.game_loop - self.s['shade_seen']} loops after it appeared "
            f"(it moved {moved:.1f} past the cast target); on_unit_destroyed fired: "
            f"{self.s['shade'] in self.destroyed}; Adept {adept.position.distance_to(self.s['adept_pos']):.1f} "
            f"from where it cast (teleported if large)"
        )
        self.s["adept_pos"] = adept.position
        self.goto("shade_cast_again")

    async def _shade_cast_again(self) -> None:
        adept = self.unit_tag_dict.get(self.s["adept"])
        if AbilityId.ADEPTPHASESHIFT_ADEPTPHASESHIFT not in (await self.get_available_abilities([adept]))[0]:
            self.timed_out()
            return
        self.log(f"shade ready again {self.state.game_loop - self.s['cast_loop']} loops after the first cast")
        adept(AbilityId.ADEPTPHASESHIFT_ADEPTPHASESHIFT, adept.position.towards(self.game_info.map_center, 10))
        self.s.pop("shade")
        self.goto("shade_cancel")

    async def _shade_cancel(self) -> None:
        adept = self.unit_tag_dict.get(self.s["adept"])
        shade = self.own(UnitTypeId.ADEPTPHASESHIFT)
        if "shade" not in self.s:
            if shade is None:
                self.timed_out()
                return
            self.s.update(shade=shade.tag, shade_seen=self.state.game_loop)
            return
        if shade is not None and self.state.game_loop - self.s["shade_seen"] >= CANCEL_AFTER_LOOPS:
            if "cancelled" not in self.s:
                self.s["cancelled"] = self.state.game_loop
                self.log(f"cancelling with CANCEL_ADEPTPHASESHIFT on the Adept; the shade offers {await self.abilities(shade)}")
                adept(AbilityId.CANCEL_ADEPTPHASESHIFT)
            elif self.state.game_loop - self.s["cancelled"] > 10 and "cancel_shade" not in self.s:
                self.s["cancel_shade"] = True
                self.log("shade still there 10 loops after the Adept's cancel; trying CANCEL_ADEPTSHADEPHASESHIFT on the shade")
                shade(AbilityId.CANCEL_ADEPTSHADEPHASESHIFT)
            return
        if shade is None:
            self.log(
                f"after cancelling: shade gone {self.state.game_loop - self.s['shade_seen']} loops after it "
                f"appeared; on_unit_destroyed fired: {self.s['shade'] in self.destroyed}; Adept "
                f"{adept.position.distance_to(self.s['adept_pos']):.1f} from where it cast"
            )
            self.goto("hallucinate")

    # --- 2. Hallucination -------------------------------------------------------------------------

    async def _hallucinate(self) -> None:
        sentry = self.own(UnitTypeId.SENTRY)
        self.log(f"Sentry energy {sentry.energy:.0f}, abilities {await self.abilities(sentry)}")
        self.s.update(cast_loop=self.state.game_loop, energy=sentry.energy)
        sentry(AbilityId.HALLUCINATION_PHOENIX)
        self.goto("phoenix_watch")

    async def _phoenix_watch(self) -> None:
        phoenix = self.own(UnitTypeId.PHOENIX, hallucination=True)
        if "phoenix" not in self.s:
            if phoenix is None:
                self.timed_out()
                return
            sentry = self.own(UnitTypeId.SENTRY)
            self.s.update(phoenix=phoenix.tag, phoenix_seen=self.state.game_loop, start=phoenix.position)
            self.log(
                f"hallucinated Phoenix appeared {self.state.game_loop - self.s['cast_loop']} loops after the cast, "
                f"{phoenix.distance_to(sentry):.1f} from the Sentry; in self.units: {phoenix.tag in self.units.tags}; "
                f"is_hallucination {phoenix.is_hallucination}; orders {[o.ability.id.name for o in phoenix.orders]}; "
                f"Sentry energy used {self.s['energy'] - sentry.energy:.1f}"
            )
            phoenix.move(self.enemy_start_locations[0])
            return
        if phoenix is not None:
            self.s["last"] = phoenix.position
            return
        self.log(
            f"hallucinated Phoenix gone {self.state.game_loop - self.s['phoenix_seen']} loops after it appeared, "
            f"after flying {self.s['last'].distance_to(self.s['start']):.1f}; on_unit_destroyed fired: "
            f"{self.s['phoenix'] in self.destroyed}"
        )
        self.goto("oracle_beam")

    # --- 3. Oracle -------------------------------------------------------------------------------

    async def _oracle_beam(self) -> None:
        oracle = self.own(UnitTypeId.ORACLE)
        drone = self.enemy_units(UnitTypeId.DRONE).first if self.enemy_units(UnitTypeId.DRONE) else None
        self.log(f"Oracle energy {oracle.energy:.1f}, abilities {await self.abilities(oracle)}; Drone found: {drone is not None}")
        self.s.update(energy=oracle.energy, beam_loop=self.state.game_loop, drone=drone.tag if drone else None)
        oracle(AbilityId.BEHAVIOR_PULSARBEAMON)
        self.goto("oracle_attack")

    async def _oracle_attack(self) -> None:
        oracle = self.own(UnitTypeId.ORACLE)
        loops = self.state.game_loop - self.s["beam_loop"]
        if "on_energy" not in self.s and loops >= 4:
            self.s["on_energy"] = oracle.energy
            self.log(
                f"after BEHAVIOR_PULSARBEAMON: energy {self.s['energy']:.1f} -> {oracle.energy:.1f}; "
                f"abilities {await self.abilities(oracle)}"
            )
            # unit_tag_dict holds own units only; the Drone is an enemy
            drone = self.enemy_units.find_by_tag(self.s["drone"]) if self.s["drone"] else None
            self.log(f"Drone {'in vision, attacking it' if drone is not None else 'not in vision'}")
            if drone is not None:
                oracle.attack(drone)
            return
        if "on_energy" in self.s and loops in (4 + 45, 4 + 90):
            drone = self.enemy_units.find_by_tag(self.s["drone"]) if self.s["drone"] else None
            self.log(
                f"Oracle orders {[(o.ability.id.name, o.target) for o in oracle.orders]}, weapon cooldown "
                f"{oracle.weapon_cooldown}; Drone {'gone from vision' if drone is None else f'{drone.distance_to(oracle):.1f} away, HP {drone.health:.0f}'}"
            )
        if "on_energy" in self.s and loops >= 4 + 224:
            drone_alive = self.s["drone"] in self.enemy_units.tags if self.s["drone"] else None
            self.log(
                f"beam on for 10 s: energy {self.s['on_energy']:.1f} -> {oracle.energy:.1f}; Drone alive: {drone_alive}"
            )
            oracle(AbilityId.BEHAVIOR_PULSARBEAMOFF)
            self.goto("detection")

    # --- 4. Detection -----------------------------------------------------------------------------

    async def _detection(self) -> None:
        cannon_at = self.s["cannon_at"]
        if "observer_spawned" not in self.s:
            # spawned now: the Cannon detects and kills an Observer left beside it
            self.s["observer_spawned"] = True
            await self.client.debug_create_unit([[UnitTypeId.OBSERVER, 1, cannon_at.towards(self.start_location, 3), OWN]])
            return
        observer = self.own(UnitTypeId.OBSERVER)
        if observer is None:
            self.timed_out()
            return
        if "near" not in self.s:
            cannon = self.enemy_structures(UnitTypeId.PHOTONCANNON)
            self.s["near"] = self.mediator.get_is_detected(unit=observer)
            self.log(
                f"enemy Cannons seen: {cannon.amount} (powered {[c.is_powered for c in cannon]}); Observer "
                f"{observer.distance_to(cannon_at):.1f} from the Cannon spot: get_is_detected {self.s['near']}, "
                f"is_revealed {observer.is_revealed}"
            )
            observer.move(self.start_location)
            return
        if observer.distance_to(cannon_at) > 20:
            self.log(
                f"Observer {observer.distance_to(cannon_at):.1f} from the Cannon: get_is_detected "
                f"{self.mediator.get_is_detected(unit=observer)}, is_revealed {observer.is_revealed}"
            )
            self.goto("finish")

    async def _finish(self) -> None:
        self.finished = True
        await self.client.leave()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--map", default="PylonAIE_v4")
    args = parser.parse_args()
    probe = AbilityProbe()
    run_game(
        maps.get(args.map),
        [Bot(Race.Protoss, probe, "AbilityProbe"), Computer(Race.Zerg, Difficulty.VeryEasy)],
        realtime=False,
        game_time_limit=600,
    )
    print(f"\n=== scouting ability checks on {args.map} ===")
    for line in probe.lines:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
