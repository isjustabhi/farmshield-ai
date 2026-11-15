"""Deterministic 2D grid fleet simulation — single authoritative state."""

from __future__ import annotations

import json
import threading
from copy import deepcopy
from pathlib import Path

from .events import EventLog
from .metrics import FleetProductivityLedger
from .models import (
    Job,
    JobStatus,
    Position,
    Scenario,
    SimEvent,
    SimulationState,
    Tractor,
    TractorStatus,
)
from .navigation import plan_path

SCENARIO_PATH = Path(__file__).resolve().parent.parent / "data" / "scenario.json"
MILESTONE_FRACTIONS = (0.25, 0.5, 0.75)
DEFAULT_PLAY_INTERVAL_SEC = 0.05


class SimulationError(Exception):
    """Raised when an invalid simulation control action is requested."""


class SimulationService:
    """Owns the seeded scenario, sim clock, and tractor/job state."""

    def __init__(
        self,
        scenario_path: Path | None = None,
        *,
        play_interval_sec: float = DEFAULT_PLAY_INTERVAL_SEC,
        isolated: bool = False,
    ) -> None:
        self._scenario_path = scenario_path or SCENARIO_PATH
        self._play_interval_sec = play_interval_sec
        self.isolated = isolated
        self._lock = threading.RLock()
        self._play_stop = threading.Event()
        self._play_thread: threading.Thread | None = None
        self._seed_scenario: Scenario | None = None
        self._events = EventLog(
            on_emit=None if isolated else self._persist_event
        )
        self.sim_time = 0
        self.tick_count = 0
        self.playing = False
        self.fields: list = []
        self.tractors: dict[str, Tractor] = {}
        self.jobs: dict[str, Job] = {}
        self.grid = None
        self.obstacles: list[Position] = []
        self.obstacle_set: set[tuple[int, int]] = set()
        self.fuel = None
        self.depot = Position(x=0, y=0)
        self.scenario_name = ""
        self.seed = 0
        self._milestone_emitted: dict[str, set[float]] = {}
        self.auto_schedule = True
        self.auto_recover = True
        self.analytics = FleetProductivityLedger()
        self.scheduler_agent = None
        self.benchmark_counters: dict[str, int] = {
            "safety_violations": 0,
            "recovery_attempts": 0,
            "recovery_successes": 0,
        }
        self.reset()

    # ------------------------------------------------------------------ load / reset
    def load_scenario(self) -> Scenario:
        raw = json.loads(self._scenario_path.read_text(encoding="utf-8"))
        return Scenario.model_validate(raw)

    def reset(self) -> SimulationState:
        with self._lock:
            self._stop_play_thread()
            from . import memory as memory_service
            from .metrics import agent_observability
            from .scheduler import fleet_agent

            # Snapshot productivity for the outgoing live run before wiping the clock.
            if (
                not self.isolated
                and self.analytics.has_data()
            ):
                memory_service.operational_memory.persist_performance_summary(
                    simulation_time=self.sim_time,
                    metrics=self.analytics.export_dict(),
                    summary_key="productivity",
                )

            scenario = self.load_scenario()
            self._seed_scenario = scenario
            self._apply_scenario(deepcopy(scenario))
            self.sim_time = 0
            self.tick_count = 0
            self.playing = False
            self._events.clear()
            self._milestone_emitted = {job_id: set() for job_id in self.jobs}
            self.analytics.clear()
            self.benchmark_counters = {
                "safety_violations": 0,
                "recovery_attempts": 0,
                "recovery_successes": 0,
            }

            if not self.isolated:
                fleet_agent.clear()
                agent_observability.clear()
                # New simulation run: clear ephemeral logs, keep SQLite history intact.
                memory_service.operational_memory.clear()
                memory_service.operational_memory.start_run(
                    scenario_name=self.scenario_name,
                    seed=self.seed,
                )
                run_id = memory_service.operational_memory.current_run_id
            else:
                run_id = None

            self._events.emit(
                sim_time=0,
                event_type="simulation_reset",
                message=f"Scenario '{self.scenario_name}' loaded (seed={self.seed})",
                data={
                    "seed": self.seed,
                    "scenario": self.scenario_name,
                    "run_id": run_id,
                    "isolated": self.isolated,
                },
            )
            return self.get_state_unlocked()

    def _apply_scenario(self, scenario: Scenario) -> None:
        self.scenario_name = scenario.name
        self.seed = scenario.seed
        self.grid = scenario.grid
        self.fields = list(scenario.fields)
        self.tractors = {t.id: t for t in scenario.tractors}
        self.jobs = {j.id: j for j in scenario.jobs}
        self.obstacles = list(scenario.obstacles)
        self.obstacle_set = {(o.x, o.y) for o in self.obstacles}
        self.fuel = scenario.fuel
        self.depot = scenario.depot

    # ------------------------------------------------------------------ queries
    def get_scenario(self) -> Scenario:
        with self._lock:
            assert self._seed_scenario is not None
            return deepcopy(self._seed_scenario)

    def get_state(self) -> SimulationState:
        with self._lock:
            return self.get_state_unlocked()

    def get_state_unlocked(self) -> SimulationState:
        assert self.grid is not None and self.fuel is not None
        return SimulationState(
            scenario_name=self.scenario_name,
            seed=self.seed,
            sim_time=self.sim_time,
            playing=self.playing,
            grid=self.grid,
            fields=deepcopy(self.fields),
            tractors=[deepcopy(t) for t in self.tractors.values()],
            jobs=[deepcopy(j) for j in self.jobs.values()],
            obstacles=deepcopy(self.obstacles),
            fuel=self.fuel,
            depot=self.depot,
            event_count=len(self._events.events),
            tick_count=self.tick_count,
        )

    def get_events(self, after_id: int = 0) -> list[SimEvent]:
        with self._lock:
            if after_id <= 0:
                return self._events.events
            return self._events.since(after_id)

    def emit_event(
        self,
        *,
        event_type: str,
        message: str,
        tractor_id: str | None = None,
        job_id: str | None = None,
        field_id: str | None = None,
        data: dict | None = None,
    ) -> SimEvent:
        with self._lock:
            return self._events.emit(
                sim_time=self.sim_time,
                event_type=event_type,
                message=message,
                tractor_id=tractor_id,
                job_id=job_id,
                field_id=field_id,
                data=data,
            )

    def _persist_event(self, event: SimEvent) -> None:
        from . import memory as memory_service

        memory_service.operational_memory.persist_sim_event(event)

    # ------------------------------------------------------------------ control
    def play(self) -> SimulationState:
        with self._lock:
            if self.playing:
                return self.get_state_unlocked()
            self.playing = True
            self._play_stop.clear()
            self._events.emit(
                sim_time=self.sim_time,
                event_type="simulation_play",
                message="Simulation playing",
            )
            thread = threading.Thread(target=self._play_loop, name="farmshield-sim", daemon=True)
            self._play_thread = thread
            thread.start()
            return self.get_state_unlocked()

    def pause(self) -> SimulationState:
        with self._lock:
            return self.pause_unlocked()

    def pause_unlocked(self) -> SimulationState:
        was_playing = self.playing
        self._stop_play_thread()
        if was_playing:
            self._events.emit(
                sim_time=self.sim_time,
                event_type="simulation_pause",
                message="Simulation paused",
            )
        return self.get_state_unlocked()

    def _stop_play_thread(self) -> None:
        self.playing = False
        self._play_stop.set()
        thread = self._play_thread
        self._play_thread = None
        if thread is not None and thread is not threading.current_thread():
            # Drop lock while joining to avoid deadlock with the play loop.
            self._lock.release()
            try:
                thread.join(timeout=1.0)
            finally:
                self._lock.acquire()

    def _play_loop(self) -> None:
        while not self._play_stop.is_set():
            self.step()
            if self._play_stop.wait(self._play_interval_sec):
                break

    def step(self) -> tuple[SimulationState, list[SimEvent]]:
        with self._lock:
            before = self._events.events[-1].id if self._events.events else 0
            self._tick()
            new_events = self._events.since(before)
            return self.get_state_unlocked(), new_events

    # ------------------------------------------------------------------ assignment (for scheduler / tests)
    def assign_job(self, tractor_id: str, job_id: str, reason: str = "assign") -> None:
        with self._lock:
            self._assign_job_unlocked(tractor_id, job_id, reason)

    def breakdown_tractor(self, tractor_id: str, reason: str = "breakdown") -> dict:
        """Atomically stop a tractor, preserve progress, and release its job.

        Does not invoke recovery/replan — callers orchestrate that separately.
        """
        with self._lock:
            return self._breakdown_tractor_unlocked(tractor_id, reason=reason, invoke_recover=False)

    def repair_tractor(self, tractor_id: str) -> dict:
        """Return a repaired tractor to idle so it can re-enter scheduling."""
        with self._lock:
            tractor = self.tractors.get(tractor_id)
            if tractor is None:
                raise SimulationError(f"Unknown tractor {tractor_id}")
            if tractor.status != TractorStatus.BROKEN:
                raise SimulationError(f"Tractor {tractor_id} is not broken ({tractor.status.value})")
            if tractor.assigned_job_id is not None:
                raise SimulationError(f"Broken tractor {tractor_id} still holds an assignment")

            tractor.status = TractorStatus.IDLE
            tractor.path = []
            tractor.path_index = 0
            tractor.travel_cell_progress = 0.0
            self._events.emit(
                sim_time=self.sim_time,
                event_type="repair",
                message=f"{tractor_id} repaired and returned to idle",
                tractor_id=tractor_id,
                data={"status": TractorStatus.IDLE.value},
            )
            return {
                "tractor_id": tractor_id,
                "status": tractor.status.value,
                "sim_time": self.sim_time,
            }

    def block_cell(self, x: int, y: int, reason: str = "chaos_block") -> dict:
        """Block a traversable cell; recompute routes that intersect it."""
        with self._lock:
            assert self.grid is not None
            if not (0 <= x < self.grid.width and 0 <= y < self.grid.height):
                raise SimulationError(f"Cell ({x},{y}) outside grid")
            if (x, y) == (self.depot.x, self.depot.y):
                raise SimulationError("Cannot block depot cell")
            for field in self.fields:
                if field.position.x == x and field.position.y == y:
                    raise SimulationError(f"Cannot block field cell {field.id}")
            for tractor in self.tractors.values():
                if tractor.position.x == x and tractor.position.y == y:
                    raise SimulationError(f"Cannot block cell occupied by {tractor.id}")
            if (x, y) in self.obstacle_set:
                raise SimulationError(f"Cell ({x},{y}) already blocked")

            self.obstacles.append(Position(x=x, y=y))
            self.obstacle_set.add((x, y))
            self._events.emit(
                sim_time=self.sim_time,
                event_type="route_blocked",
                message=f"Blocked cell ({x},{y}): {reason}",
                data={"x": x, "y": y, "reason": reason},
            )
            impact = self._recompute_routes_for_obstacles()
            return {"x": x, "y": y, "sim_time": self.sim_time, **impact}

    def unblock_cell(self, x: int, y: int) -> dict:
        with self._lock:
            if (x, y) not in self.obstacle_set:
                raise SimulationError(f"Cell ({x},{y}) is not blocked")
            self.obstacle_set.discard((x, y))
            self.obstacles = [o for o in self.obstacles if not (o.x == x and o.y == y)]
            self._events.emit(
                sim_time=self.sim_time,
                event_type="route_unblocked",
                message=f"Unblocked cell ({x},{y})",
                data={"x": x, "y": y},
            )
            impact = self._recompute_routes_for_obstacles()
            return {"x": x, "y": y, "sim_time": self.sim_time, **impact}

    def change_job_priority(self, job_id: str, priority: int) -> dict:
        with self._lock:
            job = self.jobs.get(job_id)
            if job is None:
                raise SimulationError(f"Unknown job {job_id}")
            if job.status == JobStatus.COMPLETED:
                raise SimulationError(f"Cannot change priority of completed job {job_id}")
            old = job.priority
            job.priority = priority
            self._events.emit(
                sim_time=self.sim_time,
                event_type="priority_change",
                message=f"{job_id} priority {old} → {priority}",
                job_id=job_id,
                field_id=job.field_id,
                data={"old_priority": old, "new_priority": priority},
            )
            return {
                "job_id": job_id,
                "old_priority": old,
                "new_priority": priority,
                "status": job.status.value,
                "sim_time": self.sim_time,
            }

    def change_tractor_fuel(self, tractor_id: str, fuel_level: float) -> dict:
        """Set fuel on an idle tractor to a physically valid level."""
        with self._lock:
            assert self.fuel is not None
            tractor = self.tractors.get(tractor_id)
            if tractor is None:
                raise SimulationError(f"Unknown tractor {tractor_id}")
            if tractor.status != TractorStatus.IDLE or tractor.assigned_job_id is not None:
                raise SimulationError("Fuel change only allowed on idle unassigned tractors")
            if fuel_level < 0 or fuel_level > tractor.fuel_capacity + 1e-9:
                raise SimulationError(
                    f"Fuel must be within [0, {tractor.fuel_capacity}] (got {fuel_level})"
                )
            # Keep at least safety reserve as operationally available floor warning,
            # but allow lower values so assignments become infeasible (honest sim).
            old = tractor.fuel_level
            tractor.fuel_level = float(fuel_level)
            note = None
            if tractor.fuel_level + 1e-9 < self.fuel.safety_reserve:
                note = (
                    f"fuel_below_safety_reserve:"
                    f"{tractor.fuel_level:.3f}<{self.fuel.safety_reserve:.3f}"
                )
            self._events.emit(
                sim_time=self.sim_time,
                event_type="fuel_change",
                message=f"{tractor_id} fuel {old:.2f} → {tractor.fuel_level:.2f}",
                tractor_id=tractor_id,
                data={"old_fuel": old, "new_fuel": tractor.fuel_level, "note": note},
            )
            return {
                "tractor_id": tractor_id,
                "old_fuel": old,
                "new_fuel": tractor.fuel_level,
                "safety_reserve": self.fuel.safety_reserve,
                "note": note,
                "sim_time": self.sim_time,
            }

    def _recompute_routes_for_obstacles(self) -> dict:
        """Replan traveling tractors; release jobs that become unreachable."""
        assert self.grid is not None and self.fuel is not None
        recomputed: list[str] = []
        unreachable: list[str] = []
        preserved: dict[str, float] = {}

        for tractor in list(self.tractors.values()):
            if tractor.status != TractorStatus.TRAVELING or not tractor.assigned_job_id:
                continue
            job = self.jobs[tractor.assigned_job_id]
            field = next(f for f in self.fields if f.id == job.field_id)
            # Drop remaining path if it intersects a blocked cell.
            path_cells = {(p.x, p.y) for p in tractor.path[tractor.path_index :]}
            if path_cells.isdisjoint(self.obstacle_set) and tractor.path:
                continue

            new_path = plan_path(
                tractor.position,
                field.position,
                self.grid.width,
                self.grid.height,
                self.obstacle_set,
            )
            if not new_path:
                preserved[job.id] = job.completed_work_units
                unreachable.append(job.id)
                job.assigned_tractor_id = None
                job.status = JobStatus.PENDING
                tractor.assigned_job_id = None
                tractor.status = TractorStatus.IDLE
                tractor.path = []
                tractor.path_index = 0
                tractor.travel_cell_progress = 0.0
                self._events.emit(
                    sim_time=self.sim_time,
                    event_type="unreachable_after_block",
                    message=f"{job.id} unreachable after route block; progress preserved",
                    tractor_id=tractor.id,
                    job_id=job.id,
                    field_id=job.field_id,
                    data={"completed_work_units": job.completed_work_units},
                )
                continue

            distance = max(0, len(new_path) - 1)
            need = distance * self.fuel.travel_per_cell + self.fuel.safety_reserve
            if tractor.fuel_level + 1e-9 < need:
                preserved[job.id] = job.completed_work_units
                unreachable.append(job.id)
                job.assigned_tractor_id = None
                job.status = JobStatus.PENDING
                tractor.assigned_job_id = None
                tractor.status = TractorStatus.IDLE
                tractor.path = []
                tractor.path_index = 0
                tractor.travel_cell_progress = 0.0
                self._events.emit(
                    sim_time=self.sim_time,
                    event_type="unreachable_after_block",
                    message=f"{tractor.id} lacks fuel for detour to {job.id}",
                    tractor_id=tractor.id,
                    job_id=job.id,
                    field_id=job.field_id,
                    data={"required_fuel": need, "fuel_level": tractor.fuel_level},
                )
                continue

            tractor.path = new_path
            tractor.path_index = 0
            tractor.travel_cell_progress = 0.0
            recomputed.append(tractor.id)
            self._events.emit(
                sim_time=self.sim_time,
                event_type="route_recomputed",
                message=f"{tractor.id} detour to {job.id} ({distance} cells)",
                tractor_id=tractor.id,
                job_id=job.id,
                field_id=job.field_id,
                data={"distance": distance},
            )
            if distance == 0:
                self._arrive(tractor, job)

        return {
            "recomputed_tractors": recomputed,
            "unreachable_jobs": unreachable,
            "preserved_work": preserved,
        }

    def _breakdown_tractor_unlocked(
        self,
        tractor_id: str,
        *,
        reason: str,
        invoke_recover: bool,
    ) -> dict:
        tractor = self.tractors.get(tractor_id)
        if tractor is None:
            raise SimulationError(f"Unknown tractor {tractor_id}")

        prior_status = tractor.status.value
        job_id = tractor.assigned_job_id
        job = self.jobs.get(job_id) if job_id else None
        completed = float(job.completed_work_units) if job is not None else 0.0
        estimated = float(job.estimated_work_units) if job is not None else 0.0
        percent = (completed / estimated * 100.0) if estimated > 0 else None

        # Already broken: idempotent snapshot, no double-release.
        if tractor.status == TractorStatus.BROKEN:
            return {
                "tractor_id": tractor_id,
                "job_id": None,
                "prior_status": prior_status,
                "preserved_work_units": completed,
                "percent_complete": percent,
                "already_broken": True,
                "sim_time": self.sim_time,
                "reason": reason,
            }

        # Stop active travel/work immediately.
        tractor.path = []
        tractor.path_index = 0
        tractor.travel_cell_progress = 0.0
        tractor.status = TractorStatus.BROKEN
        tractor.assigned_job_id = None

        released_job_id = None
        if job is not None:
            # Never disturb completed jobs; only release active ownership.
            if job.status == JobStatus.COMPLETED:
                released_job_id = None
            else:
                released_job_id = job.id
                # Preserve exact fractional progress; mark pending/waiting.
                job.completed_work_units = completed
                job.assigned_tractor_id = None
                job.status = JobStatus.PENDING

        self._events.emit(
            sim_time=self.sim_time,
            event_type="breakdown",
            message=f"{tractor_id} breakdown ({reason}) prior_status={prior_status}",
            tractor_id=tractor_id,
            job_id=released_job_id,
            field_id=job.field_id if job is not None else None,
            data={
                "reason": reason,
                "prior_status": prior_status,
                "completed_work_units": completed,
                "percent_complete": percent,
            },
        )
        if released_job_id is not None:
            self._events.emit(
                sim_time=self.sim_time,
                event_type="reassignment",
                message=(
                    f"{released_job_id} released from {tractor_id} after breakdown "
                    f"(progress={completed})"
                ),
                tractor_id=tractor_id,
                job_id=released_job_id,
                field_id=job.field_id if job is not None else None,
                data={
                    "reason": "breakdown_release",
                    "completed_work_units": completed,
                    "percent_complete": percent,
                },
            )

        snapshot = {
            "tractor_id": tractor_id,
            "job_id": released_job_id,
            "prior_status": prior_status,
            "preserved_work_units": completed,
            "percent_complete": percent,
            "already_broken": False,
            "sim_time": self.sim_time,
            "reason": reason,
            "estimated_work_units": estimated,
        }

        if invoke_recover and released_job_id is not None:
            from .orchestration import handle_simulation_incident

            handle_simulation_incident(
                self,
                tractor_id=tractor_id,
                job_id=released_job_id,
                reason=reason,
                completed_work_units=completed,
                simulation_timestamp=self.sim_time,
                prior_status=prior_status,
                percent_complete=percent,
            )
        return snapshot

    def _assign_job_unlocked(self, tractor_id: str, job_id: str, reason: str) -> None:
        tractor = self.tractors.get(tractor_id)
        job = self.jobs.get(job_id)
        if tractor is None:
            raise SimulationError(f"Unknown tractor {tractor_id}")
        if job is None:
            raise SimulationError(f"Unknown job {job_id}")
        if tractor.status == TractorStatus.BROKEN:
            raise SimulationError(f"Tractor {tractor_id} is broken")
        if tractor.assigned_job_id is not None:
            raise SimulationError(f"Tractor {tractor_id} already has a job")
        if job.assigned_tractor_id is not None:
            raise SimulationError(f"Job {job_id} already has an owner")
        if job.status == JobStatus.BLOCKED:
            raise SimulationError(f"Job {job_id} is blocked by dependency")
        if job.status != JobStatus.PENDING:
            raise SimulationError(f"Job {job_id} is not assignable ({job.status.value})")
        if job.depends_on_job_id:
            dep = self.jobs[job.depends_on_job_id]
            if dep.status != JobStatus.COMPLETED:
                raise SimulationError(f"Job {job_id} dependency {dep.id} incomplete")
        if tractor.implement_type.value != job.job_type.value:
            raise SimulationError(
                f"Incompatible equipment: {tractor.implement_type.value} vs {job.job_type.value}"
            )

        job.status = JobStatus.ASSIGNED
        job.assigned_tractor_id = tractor.id
        tractor.assigned_job_id = job.id
        if tractor.status not in {TractorStatus.TRAVELING, TractorStatus.WORKING}:
            tractor.status = TractorStatus.IDLE

        self._events.emit(
            sim_time=self.sim_time,
            event_type="reassignment" if "reassign" in reason else "assignment",
            message=f"Assigned {job.id} to {tractor.id}: {reason}",
            tractor_id=tractor.id,
            job_id=job.id,
            field_id=job.field_id,
            data={"reason": reason},
        )

    # ------------------------------------------------------------------ tick
    def _tick(self) -> None:
        assert self.grid is not None and self.fuel is not None
        if self.auto_schedule:
            from .orchestration import schedule_and_apply
            from .scheduler import fleet_agent

            agent = self.scheduler_agent or fleet_agent
            schedule_and_apply(self, agent)

        self.sim_time += 1
        self.tick_count += 1

        for tractor in list(self.tractors.values()):
            if tractor.status == TractorStatus.BROKEN:
                continue
            if tractor.status == TractorStatus.REFUELING:
                self._tick_refuel(tractor)
                continue
            if tractor.assigned_job_id is None:
                tractor.status = TractorStatus.IDLE
                continue

            job = self.jobs[tractor.assigned_job_id]
            field = next(f for f in self.fields if f.id == job.field_id)

            if tractor.status == TractorStatus.IDLE and job.status == JobStatus.ASSIGNED:
                self._begin_travel(tractor, job, field.position)
            elif tractor.status == TractorStatus.TRAVELING:
                self._tick_travel(tractor, job)
            elif tractor.status == TractorStatus.WORKING:
                self._tick_work(tractor, job)

        self._unlock_dependent_jobs()
        self._record_tick_analytics()

    def _begin_travel(self, tractor: Tractor, job: Job, goal: Position) -> None:
        assert self.grid is not None and self.fuel is not None
        path = plan_path(
            tractor.position,
            goal,
            self.grid.width,
            self.grid.height,
            self.obstacle_set,
        )
        if not path:
            job.status = JobStatus.BLOCKED
            job.assigned_tractor_id = None
            tractor.assigned_job_id = None
            tractor.status = TractorStatus.IDLE
            self._events.emit(
                sim_time=self.sim_time,
                event_type="failure",
                message=f"Job {job.id} unreachable from {tractor.id}",
                tractor_id=tractor.id,
                job_id=job.id,
                field_id=job.field_id,
                data={"reason": "unreachable"},
            )
            return

        distance = max(0, len(path) - 1)
        required_fuel = distance * self.fuel.travel_per_cell + self.fuel.safety_reserve
        if tractor.fuel_level < required_fuel:
            self._fail_tractor(
                tractor,
                job,
                reason="insufficient_fuel_for_travel",
                message=f"{tractor.id} lacks fuel to reach {job.id}",
            )
            return

        tractor.path = path
        tractor.path_index = 0
        tractor.travel_cell_progress = 0.0
        tractor.status = TractorStatus.TRAVELING
        self._events.emit(
            sim_time=self.sim_time,
            event_type="travel_start",
            message=f"{tractor.id} traveling to {job.id} ({distance} cells)",
            tractor_id=tractor.id,
            job_id=job.id,
            field_id=job.field_id,
            data={"distance": distance, "path_cells": len(path)},
        )

        if distance == 0:
            self._arrive(tractor, job)

    def _tick_travel(self, tractor: Tractor, job: Job) -> None:
        assert self.fuel is not None
        if not tractor.path or tractor.path_index >= len(tractor.path) - 1:
            self._arrive(tractor, job)
            return
        # Refuse to enter newly blocked cells; recompute or release.
        next_idx = min(tractor.path_index + 1, len(tractor.path) - 1)
        nxt = tractor.path[next_idx]
        if (nxt.x, nxt.y) in self.obstacle_set:
            self._recompute_routes_for_obstacles()
            if tractor.status != TractorStatus.TRAVELING:
                return

        remaining_budget = tractor.travel_speed
        while remaining_budget > 1e-9 and tractor.path_index < len(tractor.path) - 1:
            need = 1.0 - tractor.travel_cell_progress
            step = min(need, remaining_budget)
            if tractor.fuel_level < self.fuel.travel_per_cell * step:
                self._fail_tractor(
                    tractor,
                    job,
                    reason="out_of_fuel_travel",
                    message=f"{tractor.id} ran out of fuel while traveling to {job.id}",
                )
                return

            burned = self.fuel.travel_per_cell * step
            tractor.fuel_level -= burned
            self.analytics.add_fuel(tractor.id, burned)
            tractor.travel_cell_progress += step
            remaining_budget -= step

            if tractor.travel_cell_progress >= 1.0 - 1e-9:
                tractor.path_index += 1
                tractor.position = deepcopy(tractor.path[tractor.path_index])
                tractor.travel_cell_progress = 0.0

        if tractor.path_index >= len(tractor.path) - 1:
            self._arrive(tractor, job)

    def _arrive(self, tractor: Tractor, job: Job) -> None:
        tractor.status = TractorStatus.WORKING
        tractor.path = []
        tractor.path_index = 0
        tractor.travel_cell_progress = 0.0
        previous_completed = job.completed_work_units
        job.status = JobStatus.IN_PROGRESS
        self._events.emit(
            sim_time=self.sim_time,
            event_type="arrival",
            message=f"{tractor.id} arrived at {job.field_id} for {job.id}",
            tractor_id=tractor.id,
            job_id=job.id,
            field_id=job.field_id,
            data={"position": tractor.position.model_dump()},
        )
        self._events.emit(
            sim_time=self.sim_time,
            event_type="job_start",
            message=f"{tractor.id} started {job.id} (completed={previous_completed})",
            tractor_id=tractor.id,
            job_id=job.id,
            field_id=job.field_id,
            data={"completed_work_units": previous_completed},
        )

    def _tick_work(self, tractor: Tractor, job: Job) -> None:
        assert self.fuel is not None
        remaining = job.estimated_work_units - job.completed_work_units
        if remaining <= 1e-9:
            self._complete_job(tractor, job)
            return

        units = min(remaining, tractor.working_speed)
        fuel_needed = units * self.fuel.work_per_unit
        if tractor.fuel_level < fuel_needed + 1e-9:
            # Partial progress if some fuel remains.
            affordable = tractor.fuel_level / self.fuel.work_per_unit
            if affordable <= 1e-9:
                self._fail_tractor(
                    tractor,
                    job,
                    reason="out_of_fuel_work",
                    message=f"{tractor.id} ran out of fuel while working {job.id}",
                )
                return
            units = min(units, affordable)
            fuel_needed = units * self.fuel.work_per_unit

        before = job.completed_work_units
        tractor.fuel_level -= fuel_needed
        self.analytics.add_fuel(tractor.id, fuel_needed)
        job.completed_work_units = min(
            job.estimated_work_units,
            job.completed_work_units + units,
        )
        self._emit_milestones(job, before, job.completed_work_units)

        if job.completed_work_units + 1e-9 >= job.estimated_work_units:
            job.completed_work_units = job.estimated_work_units
            self._complete_job(tractor, job)
        elif tractor.fuel_level <= 1e-9:
            self._fail_tractor(
                tractor,
                job,
                reason="out_of_fuel_work",
                message=f"{tractor.id} ran out of fuel while working {job.id}",
            )

    def _emit_milestones(self, job: Job, before: float, after: float) -> None:
        emitted = self._milestone_emitted.setdefault(job.id, set())
        for fraction in MILESTONE_FRACTIONS:
            threshold = job.estimated_work_units * fraction
            if before < threshold <= after and fraction not in emitted:
                emitted.add(fraction)
                self._events.emit(
                    sim_time=self.sim_time,
                    event_type="progress_milestone",
                    message=f"{job.id} reached {int(fraction * 100)}% ({after:.3f} units)",
                    job_id=job.id,
                    field_id=job.field_id,
                    tractor_id=job.assigned_tractor_id,
                    data={
                        "fraction": fraction,
                        "completed_work_units": after,
                        "estimated_work_units": job.estimated_work_units,
                    },
                )

    def _complete_job(self, tractor: Tractor, job: Job) -> None:
        job.status = JobStatus.COMPLETED
        job.completed_work_units = job.estimated_work_units
        job.assigned_tractor_id = None
        tractor.assigned_job_id = None
        tractor.status = TractorStatus.IDLE
        tractor.path = []
        tractor.path_index = 0
        tractor.travel_cell_progress = 0.0
        self.analytics.record_completion(
            job_id=job.id,
            tractor_id=tractor.id,
            sim_time=self.sim_time,
            deadline_minute=job.deadline_minute,
            priority=job.priority,
            work_units=job.completed_work_units,
        )
        self._events.emit(
            sim_time=self.sim_time,
            event_type="completion",
            message=f"Completed {job.id} by {tractor.id}",
            tractor_id=tractor.id,
            job_id=job.id,
            field_id=job.field_id,
            data={
                "completed_work_units": job.completed_work_units,
                "deadline_minute": job.deadline_minute,
                "on_time": self.sim_time <= job.deadline_minute,
            },
        )

    def _record_tick_analytics(self) -> None:
        status_by_tractor = {
            tid: tractor.status.value for tid, tractor in self.tractors.items()
        }
        self.analytics.record_tick(self.sim_time, status_by_tractor)
        # Persist a compact productivity snapshot periodically for live runs.
        if (
            not self.isolated
            and self.tick_count > 0
            and self.tick_count % 30 == 0
        ):
            from . import memory as memory_service

            memory_service.operational_memory.persist_performance_summary(
                simulation_time=self.sim_time,
                metrics=self.analytics.export_dict(),
                summary_key="productivity",
            )

    def _fail_tractor(self, tractor: Tractor, job: Job, *, reason: str, message: str) -> None:
        self._events.emit(
            sim_time=self.sim_time,
            event_type="failure",
            message=message,
            tractor_id=tractor.id,
            job_id=job.id,
            field_id=job.field_id,
            data={
                "reason": reason,
                "completed_work_units": job.completed_work_units,
                "fuel_level": tractor.fuel_level,
            },
        )
        self._breakdown_tractor_unlocked(
            tractor.id,
            reason=reason,
            invoke_recover=bool(getattr(self, "auto_recover", True)),
        )

    def _tick_refuel(self, tractor: Tractor) -> None:
        assert self.fuel is not None
        # Simple: fill completely in one minute when at depot.
        if tractor.position.x == self.depot.x and tractor.position.y == self.depot.y:
            tractor.fuel_level = tractor.fuel_capacity
            tractor.status = TractorStatus.IDLE
            self._events.emit(
                sim_time=self.sim_time,
                event_type="refuel_complete",
                message=f"{tractor.id} refueled to {tractor.fuel_capacity}",
                tractor_id=tractor.id,
            )

    def _unlock_dependent_jobs(self) -> None:
        for job in self.jobs.values():
            if job.status != JobStatus.BLOCKED or not job.depends_on_job_id:
                continue
            dep = self.jobs.get(job.depends_on_job_id)
            if dep is not None and dep.status == JobStatus.COMPLETED:
                job.status = JobStatus.PENDING
                self._events.emit(
                    sim_time=self.sim_time,
                    event_type="job_unblocked",
                    message=f"{job.id} unblocked after {dep.id} completed",
                    job_id=job.id,
                    field_id=job.field_id,
                    data={"depends_on_job_id": dep.id},
                )


# Process-wide singleton used by the API.
simulation = SimulationService()
