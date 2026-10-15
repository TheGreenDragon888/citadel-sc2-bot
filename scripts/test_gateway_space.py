"""M7 staged test: extra Gateways keep going up once the powered spots run out (D34, D35).

    poetry run python scripts/test_gateway_space.py [--case plain|no_power|all] [--map PersephoneAIE_v4] [--end-s 900]

One local game (realtime=False) of Citadel against an idle Zerg that is invulnerable
(`client.debug_god()`, so the game doesn't end when Citadel attacks). Debug commands (dev only;
scripts/ is not in the ladder zip): from GIFT_FROM_S, `client.debug_fast_build()` for Citadel, and
while it has fewer than GIFT_BELOW minerals, `client.debug_minerals()` (+5,000) every GIFT_EVERY_S,
so the bank that D34 turns into Gateways is always there; every CULL_EVERY_S its army units are
removed (`debug_kill_unit`), so supply (and its Pylons) stays low and no 200-supply fight against
the invulnerable base slows the game down (a first version ran at about 5 real minutes per game
minute from 11:00). The powered Gateway spots run out within a few minutes.

Cases (one game each):
- `plain`: as above. PASS: Gateways + Warp Gates reach MAX_GATEWAYS by `--end-s`.
- `no_power`: also, at GIFT_FROM_S, a Gateway is created (`debug_create_unit`) on each of the first
  FILL_MAX free powered Gateway spots ares offers (`request_building_placement`, reserved one by
  one), so the powered spots run out within a few extra Gateways and the rest need D35 Pylons.
  (Filling every one, 16-17 at the top spawn of PersephoneAIE_v4, left a free powered spot where a
  worker never managed to build in 3 of 3 runs; the 8-9 at the bottom spawn worked every time.) A debug-created structure never reaches ares's
  `on_building_construction_started`, so its spot isn't booked and workers were sent to build on
  it (a first run): the test hands each one to `manager_hub.on_building_started`, as a built one
  is. This case raises the cap to NO_POWER_CAP (the module's `extra_gateway` is wrapped; test
  only), so the Gateways after the fill don't hit MAX_GATEWAYS first. PASS: at least one Pylon for Gateway space, and at least NO_POWER_MORE Gateways
  built after the fill.

Also reported (the `production` counters): extra-Gateway orders, D35's Pylons for Gateway space,
and whether "no Gateway space left" was hit.
"""

import argparse
import functools
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

from bot.constants import MAX_GATEWAYS  # noqa: E402
from bot.macro import production  # noqa: E402
from bot.main import CitadelBot  # noqa: E402
from scripts.run_matches import run_bot_game  # noqa: E402

_extra_gateway = production.extra_gateway
GIFT_FROM_S: float = 300.0
GIFT_EVERY_S: float = 30.0
GIFT_BELOW: int = 3000
CULL_EVERY_S: float = 20.0
REPORT_EVERY_S: float = 60.0
WORKERS = {UnitTypeId.PROBE}
FILL_MAX: int = 8
OWN: int = 1
CASES = ("plain", "no_power")
NO_POWER_CAP: int = 30
NO_POWER_MORE: int = 5


class GodEnemy(BotAI):
    """Invulnerable, does nothing else."""

    async def on_step(self, iteration: int) -> None:
        if iteration == 2:
            await self.client.debug_god()


class StagedCitadel(CitadelBot):
    def __init__(self, case: str, end_s: float):
        super().__init__()
        self.case = case
        self.end_s = end_s
        self.filled: Optional[int] = None
        self.before_fill: set[int] = set()
        self.after_fill: Optional[int] = None  # Gateways + Warp Gates once the fill is booked
        self.booked: set[int] = set()
        self.last_gift = -GIFT_EVERY_S
        self.last_cull = 0.0
        self.fast = False
        self.last_report = 0.0
        self.max_gateways = 0
        self.reached_at = None
        self.done = False
        self.passed = False
        self.debug_orders = os.environ.get("GS_DEBUG") == "1"  # dev: the building tracker while an order stands

    def gateways(self) -> int:
        return len(self.structures.of_type({UnitTypeId.GATEWAY, UnitTypeId.WARPGATE}).ready)

    async def on_step(self, iteration: int) -> None:
        await super().on_step(iteration)
        if self.done:
            return
        if self.time >= GIFT_FROM_S and not self.fast:
            await self.client.debug_fast_build()
            self.fast = True
            if self.case == "no_power":
                spots = []
                while len(spots) < FILL_MAX and (spot := self.mediator.request_building_placement(
                    base_location=self.start_location, structure_type=UnitTypeId.GATEWAY,
                    within_psionic_matrix=True, reserve_placement=True, production=True,
                )) is not None:
                    spots.append(spot)
                self.before_fill = set(self.structures(UnitTypeId.GATEWAY).tags)
                if spots:
                    await self.client.debug_create_unit([[UnitTypeId.GATEWAY, 1, spot, OWN] for spot in spots])
                self.filled = len(spots)
                print(f"CHECK [{self.time_formatted}] no_power: Gateways created on {len(spots)} powered spots", flush=True)
        if self.time >= GIFT_FROM_S and self.minerals < GIFT_BELOW and self.time - self.last_gift >= GIFT_EVERY_S:
            await self.client.debug_minerals()
            self.last_gift = self.time
        if self.time >= GIFT_FROM_S and self.time - self.last_cull >= CULL_EVERY_S:
            self.last_cull = self.time
            army = self.units.filter(lambda u: u.type_id not in WORKERS)
            if army:
                await self.client.debug_kill_unit(army)
        if self.filled and len(self.booked) < self.filled:
            for gate in self.structures(UnitTypeId.GATEWAY):
                if gate.tag not in self.booked and gate.tag not in self.before_fill:
                    self.manager_hub.on_building_started(gate)
                    self.booked.add(gate.tag)
        count = self.gateways()
        self.max_gateways = max(self.max_gateways, count)
        if self.filled is not None and self.after_fill is None and len(self.booked) >= self.filled:
            self.after_fill = count
        if count >= (NO_POWER_CAP if self.case == "no_power" else MAX_GATEWAYS) and self.reached_at is None:
            self.reached_at = self.time_formatted
        if self.debug_orders and self.production.gateway_order is not None and iteration % 45 == 0:
            tracker = {t: (str(v.get("id")), v.get("target")) for t, v in self.mediator.get_building_tracker_dict.items()}
            spot = self.mediator.request_building_placement(
                base_location=self.start_location, structure_type=UnitTypeId.GATEWAY,
                within_psionic_matrix=True, reserve_placement=False, production=True,
            )
            near = [(s.type_id.name, s.position, s.build_progress) for s in self.structures if spot is not None and s.distance_to(spot) < 2.5]
            if spot is not None:
                worker = self.mediator.select_worker(target_position=spot, force_close=True)
                print(f"CHECK debug [{self.time_formatted}] on route {self.not_started_but_in_building_tracker(UnitTypeId.GATEWAY)}, "
                      f"tech {self.tech_requirement_progress(UnitTypeId.GATEWAY)}, worker for the spot {worker.tag if worker else None}, "
                      f"can place {self.mediator.can_place_structure(position=spot, structure_type=UnitTypeId.GATEWAY)}, "
                      f"waiting for money {self.executor.waiting_for_money}", flush=True)
            print(f"CHECK debug [{self.time_formatted}] order {self.production.gateway_order}, counter "
                  f"{self.mediator.get_building_counter[UnitTypeId.GATEWAY]}, tracker {tracker}; powered spot {spot}, "
                  f"structures there {near}", flush=True)
        if self.time - self.last_report >= REPORT_EVERY_S:
            self.last_report = self.time
            p = self.production
            print(f"CHECK [{self.time_formatted}] Gateways {count} (pending {self.already_pending(UnitTypeId.GATEWAY):.0f}), "
                  f"Pylons {self.structures(UnitTypeId.PYLON).amount}, minerals {self.minerals}, supply {self.supply_used}; "
                  f"orders {p.extra_gateways}, space Pylons {p.space_pylons}, no space {p.no_gateway_space}", flush=True)
        cap = NO_POWER_CAP if self.case == "no_power" else MAX_GATEWAYS
        if self.time >= self.end_s or self.reached_at is not None:
            self.done = True
            p = self.production
            if self.case == "no_power":
                built = self.max_gateways - self.after_fill if self.after_fill is not None else 0
                ok = p.space_pylons > 0 and built >= NO_POWER_MORE
                what = f"{built} Gateways built after the fill ({self.after_fill} then; need {NO_POWER_MORE})"
            else:
                ok = self.reached_at is not None
                what = "reached" if ok else "not reached"
            print(f"CHECK result: {'PASS' if ok else 'FAIL'}  Gateways + Warp Gates {self.max_gateways} of {cap}"
                  f"{f' at {self.reached_at}' if self.reached_at else f' by {self.time_formatted}'}, {what}; extra-Gateway orders {p.extra_gateways}, "
                  f"Pylons for Gateway space {p.space_pylons}, no space left {p.no_gateway_space}", flush=True)
            print(f"CHECK SUMMARY {self.case}: {'PASS' if ok else 'FAIL'}", flush=True)
            self.passed = ok
            await self.client.leave()


def run_case(case: str, map_name: str, end_s: float) -> bool:
    production.extra_gateway = (
        functools.partial(_extra_gateway, max_gateways=NO_POWER_CAP) if case == "no_power" else _extra_gateway
    )
    bot = StagedCitadel(case, end_s)
    try:
        run_bot_game(map_name, [Bot(Race.Protoss, bot, "Citadel"), Bot(Race.Zerg, GodEnemy(), "GodEnemy")], None,
                     int(end_s) + 120)
    except Exception as e:  # noqa: BLE001  (the leave can surface as a closed connection)
        print(f"CHECK game ended: {e!r}", flush=True)
    return bot.passed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", choices=CASES + ("all",), default="all")
    ap.add_argument("--map", default="PersephoneAIE_v4")
    ap.add_argument("--end-s", type=float, default=900.0)
    args = ap.parse_args()
    cases = CASES if args.case == "all" else (args.case,)
    results = {case: run_case(case, args.map, args.end_s) for case in cases}
    for case, ok in results.items():
        print(f"CHECK case {case}: {'PASS' if ok else 'FAIL'}", flush=True)
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
