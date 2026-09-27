"""M0 in-game checks: can_win_fight vs static defence (§4.5.2, §11.3) and §11.7 abilities.

Plays one local game (realtime=False) driven by python-sc2 debug commands, so it is
dev-only (scripts/ is not in the ladder zip). Run from anywhere:

    poetry run python scripts/test_can_win_fight.py [--map PylonAIE_v4]

Phase 1 (§4.5.2 Day-1 test): reveal the map; spawn 6 own Stalkers and, ARMY_SEPARATION
away, an enemy group of 6 Stalkers and 6 Photon Cannons powered by a Pylon. Each scenario
passes a subset of that group to mediator.can_win_fight, REPEATS times with ares's default
arguments and REPEATS times with timing_adjust=False (the simulator is not deterministic).
The spec's two scenarios come first; the rest check whether adding Cannons moves the result
at all. The raw simulator output is printed as well, because ares divides it by our HP
without shields (§11.3).

Phase 2 (§11.7): spawn an own Pylon, Gateway, Cybernetics Core, Sentry and Oracle in our
main and record under this map's game data: costs from game data (and ares's hard-coded
cost table beside them), which abilities are available and whether energy gates that,
the energy Hallucination (Phoenix) and Revelation actually use, and the minerals/gas
actually charged for Warp Gate research and for each Gateway <-> Warp Gate morph.
"""

import argparse
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Callable, List, Optional, Tuple

ROOT: Path = Path(__file__).resolve().parent.parent
# run.py resolves config.yml and the ares-sc2 import paths relative to the working directory
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

import run  # noqa: E402,F401  (puts ares-sc2 on sys.path)
from sc2 import maps  # noqa: E402
from sc2.bot_ai import BotAI  # noqa: E402
from sc2.data import Difficulty, Race  # noqa: E402
from sc2.ids.ability_id import AbilityId  # noqa: E402
from sc2.ids.unit_typeid import UnitTypeId  # noqa: E402
from sc2.ids.upgrade_id import UpgradeId  # noqa: E402
from sc2.main import run_game  # noqa: E402
from sc2.player import Bot, Computer  # noqa: E402
from sc2.position import Point2  # noqa: E402
from sc2.unit import Unit  # noqa: E402
from sc2.units import Units  # noqa: E402

from ares.consts import EngagementResult  # noqa: E402

from bot.main import CitadelBot  # noqa: E402

# test fixture values (not bot tuning)
OWN, ENEMY = 1, 2  # debug_create_unit owner ids: us, the built-in AI
ARMY_SEPARATION: float = 14.0  # own Stalkers to the enemy group centre; outside every weapon range
ENEMY_STALKER_OFFSET: float = 3.0  # enemy Stalkers stand this far from the centre toward us
CANNON_OFFSETS: List[Tuple[int, int]] = [(3, 0), (-3, 0), (0, 3), (0, -3), (3, 3), (-3, -3)]
ARENA_HALF_SIZE: int = 5  # the enemy group needs a placeable square of this half-size
PHASE_TIMEOUT_LOOPS: int = 672  # 30 game seconds
REPEATS: int = 20  # can_win_fight calls per scenario and setting
AUTOMORPH_WAIT_LOOPS: int = 90  # ~4 game seconds for Gateways to morph on their own
DEBUG_ENERGY: int = 1  # debug_set_unit_value: 1 energy, 2 life, 3 shields
TEST_ENERGY: float = 200.0
PROTOSS_COST_CHECK: List[UnitTypeId] = [
    UnitTypeId.NEXUS, UnitTypeId.PYLON, UnitTypeId.GATEWAY, UnitTypeId.WARPGATE,
    UnitTypeId.CYBERNETICSCORE, UnitTypeId.PHOTONCANNON, UnitTypeId.SHIELDBATTERY,
    UnitTypeId.ZEALOT, UnitTypeId.STALKER, UnitTypeId.SENTRY, UnitTypeId.ADEPT,
    UnitTypeId.ORACLE, UnitTypeId.IMMORTAL, UnitTypeId.COLOSSUS, UnitTypeId.OBSERVER,
]


class InGameProbe(CitadelBot):
    """CitadelBot plus a debug-command state machine; each phase is a `_<name>` coroutine."""

    def __init__(self) -> None:
        super().__init__()
        self.phase: str = "spawn_armies"
        self.phase_started: int = 0
        self.finished: bool = False
        self.lines: List[str] = []
        self.fight_rows: List[Tuple[str, List[int], bool, float, List[int]]] = []
        self.pending: dict = {}
        self.morph_plan: List[Tuple[str, UnitTypeId, AbilityId, UnitTypeId]] = [
            ("Gateway -> Warp Gate", UnitTypeId.GATEWAY, AbilityId.MORPH_WARPGATE, UnitTypeId.WARPGATE),
            ("Warp Gate -> Gateway", UnitTypeId.WARPGATE, AbilityId.MORPH_GATEWAY, UnitTypeId.GATEWAY),
            ("Gateway -> Warp Gate (again)", UnitTypeId.GATEWAY, AbilityId.MORPH_WARPGATE, UnitTypeId.WARPGATE),
        ]

    # --- plumbing -------------------------------------------------------------------------

    def log(self, text: str) -> None:
        self.lines.append(text)

    def goto(self, phase: str) -> None:
        self.phase = phase
        self.phase_started = self.state.game_loop

    def timed_out(self) -> bool:
        if self.state.game_loop - self.phase_started > PHASE_TIMEOUT_LOOPS:
            self.log(f"TIMEOUT waiting in phase `{self.phase}`")
            self.goto("finish")
            return True
        return False

    def bank(self) -> Tuple[int, int]:
        return self.minerals, self.vespene

    def one(self, type_id: UnitTypeId, ready: bool = True) -> Optional[Unit]:
        units = self.structures(type_id) if type_id in {
            UnitTypeId.PYLON, UnitTypeId.GATEWAY, UnitTypeId.WARPGATE, UnitTypeId.CYBERNETICSCORE
        } else self.units(type_id)
        units = units.ready if ready else units
        return units.first if units else None

    async def abilities_of(self, unit: Unit) -> List[AbilityId]:
        return (await self.get_available_abilities([unit]))[0]

    async def on_step(self, iteration: int) -> None:
        await super(InGameProbe, self).on_step(iteration)
        if self.finished:
            return
        handler: Callable = getattr(self, f"_{self.phase}")
        await handler()

    # --- phase 1: can_win_fight -----------------------------------------------------------

    def find_arena(self) -> Tuple[Point2, Point2]:
        """Enemy group centre (placeable square) nearest the map centre, and our Stalkers' spot."""
        area = self.game_info.playable_area
        margin = ARENA_HALF_SIZE + 1
        centre = self.game_info.map_center
        candidates = sorted(
            (
                Point2((x, y))
                for x in range(int(area.x) + margin, int(area.right) - margin)
                for y in range(int(area.y) + margin, int(area.top) - margin)
            ),
            key=lambda p: p.distance_to(centre),
        )
        span = range(-ARENA_HALF_SIZE, ARENA_HALF_SIZE + 1)
        for p in candidates:
            own = p.towards(self.start_location, ARMY_SEPARATION)
            if self.in_pathing_grid(own) and all(
                self.in_placement_grid(Point2((p.x + dx, p.y + dy))) for dx in span for dy in span
            ):
                return p, own
        raise RuntimeError("no open area for the combat-sim arena")

    async def _spawn_armies(self) -> None:
        await self.client.debug_show_map()
        centre, own_pos = self.find_arena()
        spawns = [
            [UnitTypeId.STALKER, 6, own_pos, OWN],
            [UnitTypeId.STALKER, 6, centre.towards(own_pos, ENEMY_STALKER_OFFSET), ENEMY],
            [UnitTypeId.PYLON, 1, centre, ENEMY],
        ] + [[UnitTypeId.PHOTONCANNON, 1, centre.offset(o), ENEMY] for o in CANNON_OFFSETS]
        await self.client.debug_create_unit(spawns)
        self.log(f"arena: enemy group centre {centre.rounded}, own Stalkers {own_pos.rounded}")
        self.goto("evaluate_fights")

    async def _evaluate_fights(self) -> None:
        own: Units = self.units(UnitTypeId.STALKER)
        stalkers: Units = self.enemy_units(UnitTypeId.STALKER)
        cannons: Units = self.enemy_structures(UnitTypeId.PHOTONCANNON)
        if not (len(own) == 6 and len(stalkers) == 6 and len(cannons) == len(CANNON_OFFSETS)):
            self.timed_out()
            return

        own_centre = own.center
        cannons = cannons.sorted(lambda c: c.distance_to(own_centre))
        everything = own + stalkers + cannons
        self.log(
            f"at game loop {self.state.game_loop}: {len(own)} own Stalkers, {len(stalkers)} enemy "
            f"Stalkers, {len(cannons)} Cannons (ready {cannons.ready.amount}, powered "
            f"{sum(c.is_powered for c in cannons)}); every unit at full HP+shields: "
            f"{all(u.health == u.health_max and u.shield == u.shield_max for u in everything)}"
        )
        self.log(
            f"distances: own Stalkers to enemy Stalkers {own_centre.distance_to(stalkers.center):.1f}, "
            f"to nearest Cannon {cannons.first.distance_to(own_centre):.1f}"
        )
        own_hp = sum(u.health for u in own)
        own_hp_shield = sum(u.health + u.shield for u in own)
        self.log(f"own side: HP {own_hp:.0f}, HP+shields {own_hp_shield:.0f}")

        scenarios: List[Tuple[str, List[Unit]]] = [
            ("6 Stalkers vs nothing [spec]", []),
            ("6 Stalkers vs 1 Cannon [spec]", cannons[:1]),
            ("6 Stalkers vs 3 Cannons", cannons[:3]),
            ("6 Stalkers vs 6 Cannons", cannons[:6]),
            ("6 Stalkers vs 6 Stalkers", list(stalkers)),
            ("6 Stalkers vs 6 Stalkers + 1 Cannon", list(stalkers) + cannons[:1]),
            ("6 Stalkers vs 6 Stalkers + 2 Cannons", list(stalkers) + cannons[:2]),
            ("6 Stalkers vs 6 Stalkers + 4 Cannons", list(stalkers) + cannons[:4]),
        ]
        simulator = self.manager_hub.combat_sim_manager.combat_sim
        for label, enemy_list in scenarios:
            enemy = Units(enemy_list, self)
            # the simulator is not deterministic, so sample every scenario REPEATS times
            default = [
                self.mediator.can_win_fight(own_units=own, enemy_units=enemy).value
                for _ in range(REPEATS)
            ]
            # same settings as the calls above: can_win_fight sets them on this simulator
            won, health_left = simulator.predict_engage(own, enemy)
            no_timing = [
                self.mediator.can_win_fight(own_units=own, enemy_units=enemy, timing_adjust=False).value
                for _ in range(REPEATS)
            ]
            self.fight_rows.append((label, default, won, health_left, no_timing))

        await self.client.debug_kill_unit(everything.tags | self.enemy_structures(UnitTypeId.PYLON).tags)
        self.goto("spawn_tech")

    # --- phase 2: §11.7 abilities and costs -----------------------------------------------

    async def _spawn_tech(self) -> None:
        # freeze income so every resource delta below is exactly what the game charged
        for worker in self.workers:
            worker.stop()
        await self.client.debug_all_resources()
        near = self.start_location.towards(self.game_info.map_center, 9)
        pylon_pos = await self.find_placement(UnitTypeId.PYLON, near=near, random_alternative=False)
        caster_pos = pylon_pos.towards(self.start_location, 3)
        await self.client.debug_create_unit([
            [UnitTypeId.PYLON, 1, pylon_pos, OWN],
            [UnitTypeId.SENTRY, 1, caster_pos, OWN],
            [UnitTypeId.ORACLE, 1, caster_pos, OWN],
        ])
        self.goto("spawn_gateway")

    async def _spawn_gateway(self) -> None:
        pylon = self.one(UnitTypeId.PYLON)
        if pylon is None or not pylon.is_ready:
            self.timed_out()
            return
        pos = await self.find_placement(
            UnitTypeId.GATEWAY, near=pylon.position, max_distance=10, random_alternative=False
        )
        await self.client.debug_create_unit([[UnitTypeId.GATEWAY, 1, pos, OWN]])
        self.goto("spawn_core")

    async def _spawn_core(self) -> None:
        pylon = self.one(UnitTypeId.PYLON)
        if self.one(UnitTypeId.GATEWAY) is None:
            self.timed_out()
            return
        pos = await self.find_placement(
            UnitTypeId.CYBERNETICSCORE, near=pylon.position, max_distance=10, random_alternative=False
        )
        await self.client.debug_create_unit([[UnitTypeId.CYBERNETICSCORE, 1, pos, OWN]])
        self.goto("check_abilities")

    async def _check_abilities(self) -> None:
        core = self.one(UnitTypeId.CYBERNETICSCORE)
        gateway = self.one(UnitTypeId.GATEWAY)
        sentry, oracle = self.one(UnitTypeId.SENTRY), self.one(UnitTypeId.ORACLE)
        if not (core and gateway and sentry and oracle):
            self.timed_out()
            return

        upgrade = self.game_data.upgrades[UpgradeId.WARPGATERESEARCH.value]
        self.log(
            f"game data: WARPGATERESEARCH upgrade cost {upgrade.cost.minerals}/{upgrade.cost.vespene}, "
            f"research time {upgrade.cost.time} loops; RESEARCH_WARPGATE ability cost "
            f"{self.calculate_cost(AbilityId.RESEARCH_WARPGATE)}"
        )
        self.log(
            f"game data: MORPH_WARPGATE {self.game_data.calculate_ability_cost(AbilityId.MORPH_WARPGATE)}, "
            f"MORPH_GATEWAY {self.game_data.calculate_ability_cost(AbilityId.MORPH_GATEWAY)}, "
            f"HALLUCINATION_PHOENIX {self.calculate_cost(AbilityId.HALLUCINATION_PHOENIX)}, "
            f"ORACLEREVELATION {self.calculate_cost(AbilityId.ORACLEREVELATION_ORACLEREVELATION)}"
        )
        differ = []
        for type_id in PROTOSS_COST_CHECK:
            ares_cost = self.calculate_cost(type_id)  # AresBot override: hard-coded COST_DICT
            data_cost = BotAI.calculate_cost(self, type_id)  # python-sc2: this map's game data
            if ares_cost != data_cost:
                differ.append(f"{type_id.name} ares {ares_cost} vs game data {data_cost}")
        self.log(
            "ares COST_DICT vs game data: "
            + ("; ".join(differ) if differ else f"identical for all {len(PROTOSS_COST_CHECK)} types checked")
        )

        self.log(f"spawned energy: Sentry {sentry.energy:.1f}, Oracle {oracle.energy:.1f}")
        abilities = await self.get_available_abilities([core, gateway, sentry, oracle])
        checks = [
            ("Cybernetics Core has RESEARCH_WARPGATE", AbilityId.RESEARCH_WARPGATE in abilities[0]),
            ("Gateway has RESEARCH_WARPGATE", AbilityId.RESEARCH_WARPGATE in abilities[1]),
            ("Gateway has MORPH_WARPGATE before research", AbilityId.MORPH_WARPGATE in abilities[1]),
            (f"Sentry has HALLUCINATION_PHOENIX at {sentry.energy:.0f} energy",
             AbilityId.HALLUCINATION_PHOENIX in abilities[2]),
            (f"Oracle has ORACLEREVELATION at {oracle.energy:.0f} energy",
             AbilityId.ORACLEREVELATION_ORACLEREVELATION in abilities[3]),
        ]
        for text, ok in checks:
            self.log(f"available: {text}: {ok}")
        await self.client.debug_set_unit_value([sentry.tag, oracle.tag], DEBUG_ENERGY, TEST_ENERGY)
        self.goto("cast_spells")

    async def _cast_spells(self) -> None:
        sentry, oracle = self.one(UnitTypeId.SENTRY), self.one(UnitTypeId.ORACLE)
        if sentry.energy < TEST_ENERGY - 1 or oracle.energy < TEST_ENERGY - 1:
            self.timed_out()
            return
        abilities = await self.get_available_abilities([sentry, oracle])
        self.log(
            f"available at {TEST_ENERGY:.0f} energy: HALLUCINATION_PHOENIX "
            f"{AbilityId.HALLUCINATION_PHOENIX in abilities[0]}, ORACLEREVELATION "
            f"{AbilityId.ORACLEREVELATION_ORACLEREVELATION in abilities[1]}"
        )
        self.pending = {"loop": self.state.game_loop, "sentry": sentry.energy, "oracle": oracle.energy}
        sentry(AbilityId.HALLUCINATION_PHOENIX)
        oracle(AbilityId.ORACLEREVELATION_ORACLEREVELATION, oracle.position.towards(self.game_info.map_center, 4))
        self.goto("measure_energy")

    async def _measure_energy(self) -> None:
        sentry, oracle = self.one(UnitTypeId.SENTRY), self.one(UnitTypeId.ORACLE)
        used_sentry = self.pending["sentry"] - sentry.energy
        used_oracle = self.pending["oracle"] - oracle.energy
        if used_sentry < 1 or used_oracle < 1:
            self.timed_out()
            return
        phoenixes = self.units(UnitTypeId.PHOENIX).filter(lambda u: u.is_hallucination)
        self.log(
            f"energy used (over {self.state.game_loop - self.pending['loop']} loops, regen not "
            f"subtracted): Hallucination {used_sentry:.2f}, Revelation {used_oracle:.2f}; "
            f"hallucinated Phoenixes present: {phoenixes.amount}"
        )
        self.goto("research_warpgate")

    async def _research_warpgate(self) -> None:
        core = self.one(UnitTypeId.CYBERNETICSCORE)
        await self.client.debug_fast_build()  # zero build/research time; costs unchanged
        self.pending = {"resources": self.bank()}
        core.research(UpgradeId.WARPGATERESEARCH)
        self.goto("await_warpgate")

    async def _await_warpgate(self) -> None:
        if UpgradeId.WARPGATERESEARCH not in self.state.upgrades:
            self.timed_out()
            return
        m0, g0 = self.pending["resources"]
        m1, g1 = self.bank()
        self.log(f"charged for Warp Gate research: {m0 - m1}/{g0 - g1}")
        self.pending = {"resources": self.bank()}
        self.goto("watch_automorph")

    async def _watch_automorph(self) -> None:
        if self.one(UnitTypeId.WARPGATE, ready=False) is not None:
            m0, g0 = self.pending["resources"]
            m1, g1 = self.bank()
            self.log(f"Gateway morphed to Warp Gate on its own after research; charged {m0 - m1}/{g0 - g1}")
            self.morph_plan.pop(0)
            self.goto("morph")
        elif self.state.game_loop - self.phase_started > AUTOMORPH_WAIT_LOOPS:
            self.log(f"Gateway did not morph on its own within {AUTOMORPH_WAIT_LOOPS} loops of research")
            self.goto("morph")

    async def _morph(self) -> None:
        if not self.morph_plan:
            self.goto("finish")
            return
        label, from_type, ability, to_type = self.morph_plan[0]
        if not self.pending.get("issued"):
            unit = self.one(from_type)
            if unit is None:
                self.timed_out()
                return
            available = ability in await self.abilities_of(unit)
            self.pending = {"issued": True, "resources": self.bank(), "tag": unit.tag}
            self.log(f"{label}: {ability.name} available {available}")
            unit(ability)
            return
        unit = self.unit_tag_dict.get(self.pending["tag"])
        if unit is None or unit.type_id != to_type:
            self.timed_out()
            return
        m0, g0 = self.pending["resources"]
        m1, g1 = self.bank()
        self.log(f"{label}: charged {m0 - m1}/{g0 - g1}")
        self.morph_plan.pop(0)
        self.pending = {}
        self.phase_started = self.state.game_loop

    async def _finish(self) -> None:
        self.finished = True
        await self.client.debug_leave()


def spread(values: List[int]) -> str:
    """Most common EngagementResult, plus the value range when the samples differ."""
    mode = Counter(values).most_common(1)[0][0]
    lo, hi = min(values), max(values)
    return f"{EngagementResult(mode).name} {mode}" + (f" ({lo}-{hi})" if lo != hi else "")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--map", default="PylonAIE_v4", help="map name (default PylonAIE_v4)")
    args = parser.parse_args()

    bot_name, bot_race = run.load_bot_config()
    probe = InGameProbe()
    run_game(
        maps.get(args.map),
        [Bot(bot_race, probe, bot_name), Computer(Race.Zerg, Difficulty.VeryEasy)],
        realtime=False,
        game_time_limit=600,
    )

    print(f"\n=== can_win_fight static-defence test on {args.map} (ruleset {probe.ruleset}) ===")
    print(f"(each result is the most common of {REPEATS} calls; the range is shown when calls differed)")
    print(
        f"{'scenario':<38} {'default args':<27} {'raw: won, health_left':>22}  {'timing_adjust=False':<27}"
    )
    for label, default, won, health_left, no_timing in probe.fight_rows:
        print(
            f"{label:<38} {spread(default):<27} {str(won):>8}, {health_left:>11.1f}  {spread(no_timing):<27}"
        )
    print("\n=== notes (phase 1 setup, then §11.7) ===")
    for line in probe.lines:
        print(f"- {line}")
    complete = len(probe.fight_rows) == 8 and not any("TIMEOUT" in line for line in probe.lines)
    print(f"\nall checks completed: {complete}")
    return 0 if complete else 1


if __name__ == "__main__":
    sys.exit(main())
