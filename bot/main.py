import time
from typing import Optional

from ares import AresBot
from ares.behaviors.macro import MacroPlan
from loguru import logger
from sc2.bot_ai import BotAI
from sc2.data import Result
from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import Unit

from bot.army.army import Army
from bot.army.endgame import EndGame
from bot.constants import (
    ARMY_EVERY_STEPS,
    INTEL_EVERY_STEPS,
    MACRO_EVERY_STEPS,
    MEMORY_KEEPS_OPENER,
    MEMORY_LAST_GAMES,
    MEMORY_SOURCE,
    OPENER_TIMEOUT_S,
    PROBE_TARGET,
    RULESET_12_WORKER,
    STARTUP_WARN_MS,
    STEP_GUARD_MS,
    STEP_GUARD_STEPS,
    STEP_SECTION_LOG_MS,
    STEP_WARN_MS,
)
from bot.defense.defense_planner import DefensePlanner
from bot.defense.static_defense import StaticDefense
from bot.defense.wall_fallback import WallFallback
from bot.defense.worker_defense import WorkerDefense
from bot.error_guard import ErrorGuard
from bot.intel.ares_bridge import AresBridge
from bot.intel.detectors import Detectors
from bot.intel.scout_planner import ScoutPlanner
from bot.intel.threat_flags import Evidence, FlagStore, Threat
from bot.macro.build_executor import BuildExecutor
from bot.macro.economy import Economy, KeepBank, ReserveForPending
from bot.macro.production import Production
from bot.macro.supply import supply_behavior
from bot.memory.opponent_store import OpponentStore
from bot.ruleset import detect_ruleset
from bot.telemetry.logger import Telemetry


class CitadelBot(AresBot):
    def __init__(self, game_step_override: Optional[int] = None):
        """Citadel: Protoss bot for the AI Arena ladder (docs/DESIGN.md).

        Parameters
        ----------
        game_step_override :
            If provided, set the game_step to this value regardless of how it was
            specified elsewhere
        """
        super().__init__(game_step_override)
        self.ruleset: Optional[str] = None
        self.opener: str = ""
        self.economy: Optional[Economy] = None
        self.executor: Optional[BuildExecutor] = None
        self.telemetry: Optional[Telemetry] = None
        self.production: Optional[Production] = None
        self.army: Optional[Army] = None  # M4: squads, EngagementResult gates (§4.5.2)
        self.endgame: Optional[EndGame] = None  # M4: §4.7 end-game rules
        self.wall: Optional[WallFallback] = None
        self.wall_ok: Optional[bool] = None
        self.pylon_fallback_scan_at: Optional[float] = None  # macro/supply.py
        # M2: intel and defense (§3, §4.2, §5)
        self.flags: Optional[FlagStore] = None
        self.planner: Optional[DefensePlanner] = None
        self.bridge: Optional[AresBridge] = None
        self.detectors: Optional[Detectors] = None
        self.scouts: Optional[ScoutPlanner] = None  # M3: §4.3 scouting schedule
        self.static_defense: Optional[StaticDefense] = None
        self.worker_defense: Optional[WorkerDefense] = None
        # units a dev test script drives itself (scripts/test_counterattack.py's Observer): held
        # like the wall-gap holder, so no squad or scouting task takes them
        self.external_tags: set[int] = set()
        self.memory: Optional[OpponentStore] = None  # M5: §5 opponent memory
        self.preraised: list[str] = []  # threats pre-raised from memory at 0:00
        # §6 step guard: through this iteration, skip the non-critical modules
        self.guard_until: int = -1
        # M6 error guard (user decision): an error in one part of a step is logged and counted,
        # and the game goes on (an unhandled one is a Crash on the ladder)
        self.errors: ErrorGuard = ErrorGuard(self)

    async def on_start(self) -> None:
        started = time.perf_counter()
        # §4.0: loop-0 state is parsed here, before ares picks an opener in super().on_start()
        self.ruleset = detect_ruleset(self)
        if self.ruleset != RULESET_12_WORKER:
            # M1 ships 12-worker openers only (every pool map is 12-worker, VERIFY_NOTES §11.8)
            logger.error(f"RULESET {self.ruleset}: no openers for it; playing the 12-worker ones")
        # §4.8: must run before ares's placement solver, which crashes on an unusable ramp wall
        self.wall = WallFallback(self)
        self.wall_ok = self.wall.prepare()
        await super(CitadelBot, self).on_start()
        self.wall.after_start()
        self.opener = self.build_order_runner.chosen_opening
        logger.info(f"OPENER {self.opener} (enemy race at start: {self.enemy_race.name})")
        yaml_probes = self.config["Builds"][self.opener].get("ConstantWorkerProductionTill")
        if yaml_probes != PROBE_TARGET:
            logger.warning(
                f"protoss_builds.yml {self.opener} ConstantWorkerProductionTill={yaml_probes} "
                f"but constants.PROBE_TARGET={PROBE_TARGET}"
            )
        self.flags = FlagStore()
        self.planner = DefensePlanner(self, self.flags)
        self.bridge = AresBridge(self, self.flags, self.planner.override_for)
        self.detectors = Detectors(self, self.flags, self.planner.override_for)
        self.telemetry = Telemetry(self)
        self.endgame = EndGame(self)
        self.scouts = ScoutPlanner(self, self.detectors, self.flags, self.telemetry, self.endgame)
        self.static_defense = StaticDefense(self, self.planner)
        self.worker_defense = WorkerDefense(self, self.planner)
        self.economy = Economy(self)
        self.executor = BuildExecutor(self, self.opener, self.planner)
        self.production = Production(self)
        self.army = Army(self, self.endgame, self.flags)
        self._load_memory()
        # §6: keep on_start under 5 s and log its duration
        self.telemetry.startup_ms = (time.perf_counter() - started) * 1000
        log = logger.warning if self.telemetry.startup_ms > STARTUP_WARN_MS else logger.info
        log(f"STARTUP on_start took {self.telemetry.startup_ms:.0f} ms")

    def _load_memory(self) -> None:
        """§5: load the opponent's record; pre-raise the cheese it showed in 2 of its last 3 games
        as STRUCTURE evidence (phase-only expiry) that acts like the same flag raised in game,
        ending the opener where that flag would (user decision), except MEMORY_KEEPS_OPENER
        threats, whose plan applies while the opener runs on (`DefensePlanner._maybe_end_opener`)."""
        try:
            self.memory = OpponentStore(self.opponent_id)
            self.memory.load()
            for name, games in self.memory.preraise().items():
                threat = Threat[name]
                self.flags.raise_flag(
                    threat,
                    Evidence.STRUCTURE,
                    MEMORY_SOURCE,
                    self.time,
                    reason=f"opponent memory: raised in {games} of the last {MEMORY_LAST_GAMES} games",
                    override_opener=(
                        self.planner.override_for(threat, Evidence.STRUCTURE) and name not in MEMORY_KEEPS_OPENER
                    ),
                )
                self.preraised.append(name)
        except Exception:  # noqa: BLE001 - memory must never stop the game
            logger.exception("MEMORY load failed; playing without opponent memory")

    def _save_memory(self, game_result: Result) -> None:
        if self.memory is None or self.flags is None:
            return
        try:
            result = game_result.name if isinstance(game_result, Result) else str(game_result)
            first = self.telemetry.first_aggression[0] if self.telemetry and self.telemetry.first_aggression else None
            self.memory.save(result, [(r.threat.name, r.source, r.raised_at) for r in self.flags.history], first)
        except Exception:  # noqa: BLE001 - never crash at the end of a game
            logger.exception("MEMORY save failed")

    async def on_step(self, iteration: int) -> None:
        started = time.perf_counter()
        # §6 step guard: after a step over STEP_GUARD_MS, the scout planner, the counterattack's
        # detection and launch, and the telemetry snapshots wait STEP_GUARD_STEPS steps
        guarded = iteration <= self.guard_until
        # M6 error guard: each part runs in `guard(<part>)`, so an error skips only that part
        guard = self.errors.guard
        marks: list[tuple[str, float]] = []
        with guard("ares step"):
            await super(CitadelBot, self).on_step(iteration)
        marks.append(("ares", time.perf_counter()))
        # ares only moves workers that a Mining behavior tells to mine; register it every step.
        # No long-distance mining while rush Cannons may cover other bases' minerals (§4.2), or
        # while our unit holds the wall gap (the probes would walk out past it into the lings)
        plan = self.planner.plan
        with guard("mining"):
            self.register_behavior(
                self.economy.mining_behavior(
                    long_distance=Threat.CANNON_RUSH not in plan.active and not plan.hold_wall_gap
                )
            )

        with guard("opener timeout"):
            if not self.build_order_runner.build_completed and self.time > OPENER_TIMEOUT_S:
                logger.warning(
                    f"OPENER {self.opener} still running at {self.time_formatted} "
                    f"(step {self.build_order_runner.build_step}); ending it"
                )
                self.build_order_runner.set_build_completed()
                self.planner.opener_ended_by = "timeout"  # BuildExecutor adds the opener essentials

        # §3 step 2: intel, flag expiry and the defense plan
        if iteration % INTEL_EVERY_STEPS == 0:
            with guard("ares bridge"):
                self.bridge.update()
            with guard("detectors"):
                self.detectors.update()
            with guard("flag expiry"):
                self.flags.expire(self.time, self.detectors.expiry_context(self.supply_army))
            with guard("defense planner"):
                self.planner.update()
        marks.append(("intel", time.perf_counter()))
        plan = self.planner.plan
        if iteration % MACRO_EVERY_STEPS == 0 and not guarded:
            # §3 step 4; the ATTACK/REINFORCE/HARASS squads and the army's Observer are not free to scout
            with guard("scouts"):
                self.scouts.step(pinned=self.army.held_tags | plan.pinned_unit_tags | self.army.busy_tags)
        marks.append(("scouts", time.perf_counter()))
        with guard("worker defense"):
            self.worker_defense.step(plan)  # §3 step 5: every step
        marks.append(("worker_defense", time.perf_counter()))

        if iteration % MACRO_EVERY_STEPS == 0:
            with guard("static defense"):
                self.static_defense.step(plan)
            with guard("gateway upkeep"):
                self.production.gateway_upkeep()
            # units before structures: in test games Batteries and Pylons took every mineral
            # while Marines walked in
            defense: list = []
            with guard("defense behaviors"):
                defense = self.production.defense_behaviors(plan) + self.static_defense.behaviors(plan)
            with guard("chrono"):
                await self.economy.chrono(gateways_first=plan.chrono_gateways)
            with guard("macro plan"):
                if self.build_order_runner.build_completed:
                    self._register_macro_plan(defense)
                elif defense:
                    # during the opener the build runner makes Pylons; defense spends before it
                    # can act again (Defense > Economy, §3)
                    defense_plan = MacroPlan()
                    for behavior in defense:
                        defense_plan.add(behavior)
                    self.register_behavior(defense_plan)
        marks.append(("macro", time.perf_counter()))

        if iteration % ARMY_EVERY_STEPS == 0:
            holder = None
            with guard("wall"):
                holder = self.wall.step(hold_gap=plan.hold_wall_gap)
            with guard("army"):
                # the wall-gap holder and scouts are controlled elsewhere
                self.army.held_tags = ({holder} if holder is not None else set()) | self.external_tags
                self.army.scout_tags = self.scouts.tags
                plan.pinned_unit_tags = self.army.held_tags | self.scouts.tags | set(self.worker_defense.jobs)
                self.army.hold_point = plan.army_hold_point
                self.army.leash = plan.army_leash
                with guard("endgame"):
                    self.endgame.update()
                self.army.step(iteration, guarded)
        marks.append(("army", time.perf_counter()))
        with guard("micro"):
            self.army.micro(iteration)  # §3 step 5: squad micro every step
        marks.append(("micro", time.perf_counter()))

        with guard("telemetry"):
            self.telemetry.step(snapshot=not guarded)
        marks.append(("telemetry", time.perf_counter()))
        with guard("step time"):
            if guarded:
                self.telemetry.guarded_steps += 1
            self._check_step_time(iteration, self.telemetry.record_step_time(started), started, marks)

    async def _after_step(self) -> int:
        """M6 error guard over ares's after-step, which runs every registered behavior (Citadel's
        among them) after `on_step` and outside python-sc2's error handling; python-sc2's own
        after-step at its end sends the step's actions."""
        sent_at = self._time_after_step  # python-sc2 sets it when its after-step starts
        with self.errors.guard("ares after step"):
            return await super(CitadelBot, self)._after_step()
        if self._time_after_step != sent_at:
            return self.state.game_loop  # the error came from python-sc2's part
        # ares's part stopped early. Its behavior list is emptied only after every behavior ran
        # (`BehaviorExecutioner.execute`), so drop what is left, or next step would run it again;
        # then still reset ares's grids and send this step's actions
        self.behavior_executioner.behaviors = []
        with self.errors.guard("ares grid reset"):
            self.manager_hub.grid_manager.reset_grids(self.actual_iteration)
        return await BotAI._after_step(self)

    def _check_step_time(self, iteration: int, ms: float, started: float, marks: list[tuple[str, float]]) -> None:
        """§6: a warning for any step over STEP_WARN_MS (with the parts that took the time); a
        step over STEP_GUARD_MS turns the guard on for the next STEP_GUARD_STEPS steps."""
        if ms <= STEP_WARN_MS:
            return
        self.telemetry.steps_over_warn += 1
        parts, prev = [], started
        for name, at in marks:
            if (at - prev) * 1000 >= STEP_SECTION_LOG_MS:
                parts.append(f"{name} {(at - prev) * 1000:.0f}")
            prev = at
        logger.warning(f"STEP {ms:.0f} ms at {self.time_formatted} (step {iteration}): {', '.join(parts) or 'spread out'}")
        if ms > STEP_GUARD_MS:
            self.guard_until = iteration + STEP_GUARD_STEPS
            self.telemetry.guard_activations += 1
            logger.warning(
                f"STEP guard on: steps {iteration + 1}-{self.guard_until} skip the scout planner, "
                f"counterattack evaluation and telemetry snapshot"
            )

    def _register_macro_plan(self, defense: list) -> None:
        """After the opener. A MacroPlan stops at the first behavior that acts (or, for
        Pylon timing and a prioritised expansion, that is still waiting for money), so the
        order below is the spending priority: supply, the DefensePlan's structures and units
        (Defense > Economy, §3), probes, a Nexus a probe is waiting to build, timed opener
        steps, gas, bases, a mineral bank the DefensePlan asks for, then army production
        (skipped while a timed step is waiting for money)."""
        executor = self.executor
        plan = MacroPlan()
        plan.add(supply_behavior(self, other_bases=not self.planner.plan.hold_wall_gap))
        for behavior in defense:
            plan.add(behavior)
        plan.add(self.economy.worker_behavior(expansion_allowed=self.planner.plan.allow_expand))
        plan.add(ReserveForPending(UnitTypeId.NEXUS))  # a probe waiting at an expansion
        for behavior in executor.behaviors():
            plan.add(behavior)
        plan.add(self.economy.gas_behavior(executor.gas_target()))
        bases = executor.bases_target()
        plan.add(self.economy.expansion_behavior(bases, prioritize=not executor.finished))
        if self.planner.plan.bank_minerals:
            plan.add(KeepBank(self.planner.plan.bank_minerals))
        if not executor.waiting_for_money:
            for behavior in self.production.behaviors(
                schedule_finished=executor.finished, plan=self.planner.plan
            ):
                plan.add(behavior)
        self.register_behavior(plan)

    async def on_unit_destroyed(self, unit_tag: int) -> None:
        # python-sc2 still holds last step's own units here, so the type is known
        own = self._units_previous_map.get(unit_tag)
        enemy = self._enemy_units_previous_map.get(unit_tag)
        enemy_structure = self._enemy_structures_previous_map.get(unit_tag)
        role = "?"
        guard = self.errors.guard
        with guard("unit destroyed"):
            if own is not None and self.static_defense is not None:
                role = next((str(r) for r, tags in self.mediator.get_unit_role_dict.items() if unit_tag in tags), "?")
                self.static_defense.on_worker_died(unit_tag, own.position)  # before ares hands its order on
        with guard("ares unit destroyed"):
            await super(CitadelBot, self).on_unit_destroyed(unit_tag)
        # one guard per call, so an error in one doesn't skip the others (e.g. §5 expiry rule (a))
        if self.army is not None:
            with guard("unit destroyed"):
                self.army.forget(unit_tag)
        if self.scouts is not None:
            with guard("unit destroyed"):
                self.scouts.on_unit_destroyed(unit_tag)
        if self.flags is not None:
            with guard("unit destroyed"):
                self.flags.on_unit_destroyed(unit_tag, self.time)  # §5 expiry rule (a)
        if own is not None and self.telemetry is not None:
            with guard("unit destroyed"):
                self.telemetry.on_own_unit_destroyed(own, role)
        if enemy is not None and self.telemetry is not None:
            with guard("unit destroyed"):
                self.telemetry.on_enemy_unit_destroyed(enemy)
        if self.army is not None and (enemy or enemy_structure) is not None:
            with guard("unit destroyed"):
                self.army.counter.on_enemy_destroyed(enemy or enemy_structure)  # §8 counterattack outcomes

    async def on_unit_took_damage(self, unit: Unit, amount_damage_taken: float) -> None:
        with self.errors.guard("ares unit took damage"):
            await super(CitadelBot, self).on_unit_took_damage(unit, amount_damage_taken)
        with self.errors.guard("unit took damage"):
            if self.worker_defense is not None:
                self.worker_defense.on_structure_damaged(unit)

    # ares's other event hooks, under the M6 error guard (python-sc2 calls them outside on_step)
    async def on_unit_created(self, unit: Unit) -> None:
        with self.errors.guard("ares unit created"):
            await super(CitadelBot, self).on_unit_created(unit)

    async def on_building_construction_started(self, unit: Unit) -> None:
        with self.errors.guard("ares construction started"):
            await super(CitadelBot, self).on_building_construction_started(unit)

    async def on_building_construction_complete(self, unit: Unit) -> None:
        with self.errors.guard("ares construction complete"):
            await super(CitadelBot, self).on_building_construction_complete(unit)

    async def on_end(self, game_result: Result) -> None:
        if self.telemetry is not None:
            try:
                self.telemetry.end_report(self.flags, self.army)
                result = game_result.name if isinstance(game_result, Result) else str(game_result)
                record = self.telemetry.game_record(
                    result, self.flags, self.army, self.opener, self.ruleset, self.wall_ok, self.memory, self.preraised,
                    self.errors,
                )
                self.telemetry.write_game_record(record)  # §8: ./data/logs
            except Exception:  # noqa: BLE001 - never crash at the end of a game
                logger.exception("LOG game record failed")
        self._save_memory(game_result)
        with self.errors.guard("ares on_end"):
            await super(CitadelBot, self).on_end(game_result)
