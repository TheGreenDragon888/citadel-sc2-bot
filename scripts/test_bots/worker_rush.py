"""Worker rush: every starting worker attacks the opponent's main at 0:00 (DESIGN.md §4.2).

Micro: each worker hits the lowest HP+shield enemy in reach (workers and units before
structures) and otherwise attack-moves toward the opponent's mineral line, then its structures.
New workers from the townhall mine; every `REINFORCE_BATCH` of them beyond `HOME_MINERS` joins
the rush. Works as any race.
"""

from sc2.ids.unit_typeid import UnitTypeId

from scripts.test_bots.common import WORKER_TYPES, CheeseBot

HOME_MINERS: int = 4  # new workers kept mining before any join the rush
REINFORCE_BATCH: int = 3
WORKER_TARGET: int = 16


class WorkerRushBot(CheeseBot):
    name = "worker_rush"

    def __init__(self, seed=None, variant=None):
        super().__init__(seed, variant)
        self.rushers: set[int] = set()

    def busy_tags(self) -> set[int]:
        return set(self.rushers)

    async def on_start(self) -> None:
        self.client.game_step = 2
        self.rushers = {w.tag for w in self.workers}
        target = self.their_mineral_line()
        for worker in self.workers:
            worker.attack(target)

    async def on_step(self, iteration: int) -> None:
        await self.macro_basics(WORKER_TARGET)
        alive = self.workers.tags_in(self.rushers)
        self.rushers = set(alive.tags)

        miners = self.workers.tags_not_in(self.rushers)
        if len(miners) >= HOME_MINERS + REINFORCE_BATCH:
            joining = miners.furthest_n_units(self.start_location, REINFORCE_BATCH)
            for worker in joining:
                self.rushers.add(worker.tag)
                worker.attack(self.their_mineral_line())

        enemies = self.enemy_units.not_flying | self.enemy_structures
        for worker in alive:
            target = self.focus_target(worker, enemies)
            if target is not None:
                if worker.weapon_cooldown == 0 or not worker.is_attacking:
                    worker.attack(target)
                continue
            if worker.is_idle or iteration % 16 == 0:
                if self.enemy_units.not_flying.exclude_type({UnitTypeId.LARVA, UnitTypeId.EGG}):
                    near = self.enemy_units.not_flying.closest_to(worker)
                    if near.distance_to(worker) < 15 or near.type_id in WORKER_TYPES:
                        worker.attack(near.position)
                        continue
                if worker.distance_to(self.their_mineral_line()) > 6:
                    worker.attack(self.their_mineral_line())
                elif self.enemy_structures:
                    worker.attack(self.enemy_structures.closest_to(worker))
                else:
                    worker.attack(self.their_main)
