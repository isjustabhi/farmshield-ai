"""Chaos Lab — genuine simulation disruptions with explainable before/after plans."""

from __future__ import annotations

import random
import uuid
from typing import Any

from .models import (
    AssignmentSnapshot,
    ChaosEventResult,
    JobStatus,
    ScheduleResponse,
    SimulationState,
    TractorStatus,
)
from .orchestration import (
    breakdown_and_recover,
    repair_and_log,
    replan_unfinished,
    schedule_and_apply,
)
from .recovery import percent_complete
from .scheduler import fleet_agent
from .simulation import SimulationError


def _snapshots(state: SimulationState) -> list[AssignmentSnapshot]:
    out: list[AssignmentSnapshot] = []
    for job in state.jobs:
        if job.status == JobStatus.COMPLETED:
            continue
        if job.assigned_tractor_id is None and job.status == JobStatus.PENDING:
            continue
        if job.assigned_tractor_id is None and job.status == JobStatus.BLOCKED:
            continue
        if job.assigned_tractor_id is None:
            continue
        out.append(
            AssignmentSnapshot(
                job_id=job.id,
                tractor_id=job.assigned_tractor_id,
                status=job.status.value,
                completed_work_units=job.completed_work_units,
                percent_complete=percent_complete(
                    job.completed_work_units, job.estimated_work_units
                ),
            )
        )
    return sorted(out, key=lambda s: s.job_id)


def _active_map(snaps: list[AssignmentSnapshot]) -> dict[str, str | None]:
    return {s.job_id: s.tractor_id for s in snaps}


def _diff_explanation(
    before: list[AssignmentSnapshot],
    after: list[AssignmentSnapshot],
    event_type: str,
) -> str:
    b = _active_map(before)
    a = _active_map(after)
    changes: list[str] = []
    for job_id in sorted(set(b) | set(a)):
        old = b.get(job_id)
        new = a.get(job_id)
        if old != new:
            changes.append(f"{job_id}: {old or 'unassigned'} → {new or 'unassigned'}")
    if not changes:
        return (
            f"Event `{event_type}` applied. No active assignment ownership changed; "
            "in-progress work was retained where safe."
        )
    return f"Event `{event_type}` changed assignments: " + "; ".join(changes)


def _estimated_outcome(state: SimulationState, unreachable: list[str]) -> str:
    active = sum(1 for j in state.jobs if j.assigned_tractor_id)
    pending = sum(1 for j in state.jobs if j.status == JobStatus.PENDING)
    completed = sum(1 for j in state.jobs if j.status == JobStatus.COMPLETED)
    parts = [
        f"{active} active assignments",
        f"{pending} pending",
        f"{completed} completed",
    ]
    if unreachable:
        parts.append(f"{len(unreachable)} unreachable/unresolved")
    return ", ".join(parts)


def _result(
    *,
    sim: Any,
    event_type: str,
    explanation: str,
    correlation_id: str,
    before: list[AssignmentSnapshot],
    affected_jobs: list[str],
    preserved_work: dict[str, float],
    unreachable_jobs: list[str],
    safety_notes: list[str],
    schedule: ScheduleResponse | None,
    seed: int | None = None,
) -> ChaosEventResult:
    after_state = sim.get_state()
    after = _snapshots(after_state)
    why = _diff_explanation(before, after, event_type)
    return ChaosEventResult(
        ok=True,
        event_type=event_type,
        explanation=explanation,
        correlation_id=correlation_id,
        seed=seed,
        sim_time=after_state.sim_time,
        affected_jobs=sorted(set(affected_jobs)),
        preserved_work=preserved_work,
        unreachable_jobs=sorted(set(unreachable_jobs)),
        before_assignments=before,
        after_assignments=after,
        safety_notes=safety_notes,
        why_changed=why,
        estimated_outcome=_estimated_outcome(after_state, unreachable_jobs),
        state=after_state,
        schedule=schedule,
    )


def chaos_block_route(sim: Any, x: int, y: int, reason: str = "chaos_block") -> ChaosEventResult:
    correlation_id = str(uuid.uuid4())
    before = _snapshots(sim.get_state())
    impact = sim.block_cell(x, y, reason=reason)
    schedule = replan_unfinished(sim).schedule
    preserved = dict(impact.get("preserved_work") or {})
    unreachable = list(impact.get("unreachable_jobs") or [])
    explanation = (
        f"Blocked cell ({x},{y}). Recomputed {len(impact.get('recomputed_tractors') or [])} "
        f"route(s). Unreachable jobs released with preserved progress: {unreachable or 'none'}."
    )
    notes = [
        "Navigation A* excludes blocked cells",
        "Traveling tractors detoured or released if unreachable",
        "New assignments validated by Safety Agent during replan",
    ]
    return _result(
        sim=sim,
        event_type="block_route",
        explanation=explanation,
        correlation_id=correlation_id,
        before=before,
        affected_jobs=unreachable + list(preserved),
        preserved_work=preserved,
        unreachable_jobs=unreachable,
        safety_notes=notes,
        schedule=schedule,
    )


def chaos_unblock_route(sim: Any, x: int, y: int) -> ChaosEventResult:
    correlation_id = str(uuid.uuid4())
    before = _snapshots(sim.get_state())
    sim.unblock_cell(x, y)
    schedule = replan_unfinished(sim).schedule
    explanation = (
        f"Unblocked cell ({x},{y}). Pending jobs reconsidered for free compatible tractors."
    )
    return _result(
        sim=sim,
        event_type="unblock_route",
        explanation=explanation,
        correlation_id=correlation_id,
        before=before,
        affected_jobs=[a.job_id for a in schedule.assignments],
        preserved_work={},
        unreachable_jobs=[],
        safety_notes=["Cleared obstacle; A* may recover previously unreachable fields"],
        schedule=schedule,
    )


def chaos_priority_change(sim: Any, job_id: str, priority: int) -> ChaosEventResult:
    correlation_id = str(uuid.uuid4())
    before = _snapshots(sim.get_state())
    info = sim.change_job_priority(job_id, priority)
    # Do not interrupt in-progress/traveling owners — only schedule free capacity.
    schedule = schedule_and_apply(
        sim,
        fleet_agent,
        correlation_id=correlation_id,
        trigger="priority_change",
    )
    explanation = (
        f"Job {job_id} priority {info['old_priority']} → {info['new_priority']} "
        f"(status={info['status']}). Pending work reconsidered without preempting "
        f"in-progress assignments."
    )
    return _result(
        sim=sim,
        event_type="priority_change",
        explanation=explanation,
        correlation_id=correlation_id,
        before=before,
        affected_jobs=[job_id, *[a.job_id for a in schedule.assignments]],
        preserved_work={},
        unreachable_jobs=[],
        safety_notes=[
            "In-progress and traveling jobs retained",
            "Only free tractors considered for pending jobs",
        ],
        schedule=schedule,
    )


def chaos_fuel_change(sim: Any, tractor_id: str, fuel_level: float) -> ChaosEventResult:
    correlation_id = str(uuid.uuid4())
    before = _snapshots(sim.get_state())
    info = sim.change_tractor_fuel(tractor_id, fuel_level)
    schedule = schedule_and_apply(
        sim,
        fleet_agent,
        correlation_id=correlation_id,
        trigger="fuel_change",
    )
    notes = [
        "Fuel change restricted to idle unassigned tractors",
        "Assignments still require travel+work+safety reserve",
    ]
    if info.get("note"):
        notes.append(str(info["note"]))
    rejected = [r.job_id for r in schedule.infeasible_jobs if any("insufficient_fuel" in x for x in r.reasons)]
    explanation = (
        f"Tractor {tractor_id} fuel set to {info['new_fuel']:.2f} "
        f"(was {info['old_fuel']:.2f}). "
        + (
            f"Jobs remaining fuel-infeasible: {rejected}."
            if rejected
            else "Compatible assignments still validated against reserve."
        )
    )
    return _result(
        sim=sim,
        event_type="fuel_change",
        explanation=explanation,
        correlation_id=correlation_id,
        before=before,
        affected_jobs=[a.job_id for a in schedule.assignments] + rejected,
        preserved_work={},
        unreachable_jobs=rejected,
        safety_notes=notes,
        schedule=schedule,
    )


def chaos_random(sim: Any, seed: int | None = None) -> ChaosEventResult:
    """Choose one currently valid chaos event using a seeded RNG for replay."""
    rng_seed = int(seed) if seed is not None else random.randrange(1, 10_000_000)
    rng = random.Random(rng_seed)
    state = sim.get_state()
    candidates: list[tuple[str, dict[str, Any]]] = []

    for tractor in state.tractors:
        if tractor.status != TractorStatus.BROKEN:
            candidates.append(("breakdown", {"tractor_id": tractor.id}))
        else:
            candidates.append(("repair", {"tractor_id": tractor.id}))
        if tractor.status == TractorStatus.IDLE and tractor.assigned_job_id is None:
            # Reduce toward reserve/2 but stay within capacity.
            reduced = max(0.0, min(tractor.fuel_level, state.fuel.safety_reserve * 0.5))
            if reduced + 1e-9 < tractor.fuel_level:
                candidates.append(
                    ("fuel_change", {"tractor_id": tractor.id, "fuel_level": reduced})
                )

    for job in state.jobs:
        if job.status != JobStatus.COMPLETED:
            new_priority = 1 if job.priority > 1 else min(5, job.priority + 1)
            if new_priority != job.priority:
                candidates.append(
                    ("priority_change", {"job_id": job.id, "priority": new_priority})
                )

    occupied = {(t.position.x, t.position.y) for t in state.tractors}
    occupied.add((state.depot.x, state.depot.y))
    occupied.update((f.position.x, f.position.y) for f in state.fields)
    blocked = {(o.x, o.y) for o in state.obstacles}
    free_cells = [
        (x, y)
        for x in range(state.grid.width)
        for y in range(state.grid.height)
        if (x, y) not in occupied and (x, y) not in blocked
    ]
    if free_cells:
        x, y = rng.choice(free_cells)
        candidates.append(("block_route", {"x": x, "y": y}))
    for obs in state.obstacles:
        candidates.append(("unblock_route", {"x": obs.x, "y": obs.y}))

    if not candidates:
        raise SimulationError("No valid chaos events available in current state")

    event_type, payload = rng.choice(candidates)
    if event_type == "breakdown":
        before = _snapshots(state)
        result = breakdown_and_recover(sim, payload["tractor_id"], reason="chaos_random")
        after_state = result.state
        snaps_after = _snapshots(after_state)
        return ChaosEventResult(
            ok=True,
            event_type="random_breakdown",
            explanation=f"[seed={rng_seed}] " + result.recovery.explanation,
            correlation_id=result.recovery.correlation_id,
            seed=rng_seed,
            sim_time=after_state.sim_time,
            affected_jobs=[result.recovery.job_id] if result.recovery.job_id else [],
            preserved_work=(
                {result.recovery.job_id: result.recovery.preserved_work_units}
                if result.recovery.job_id
                else {}
            ),
            unreachable_jobs=[],
            before_assignments=before,
            after_assignments=snaps_after,
            safety_notes=["Seeded random breakdown via Recovery Agent"],
            why_changed=_diff_explanation(before, snaps_after, "random_breakdown"),
            estimated_outcome=_estimated_outcome(after_state, []),
            state=after_state,
            schedule=result.schedule,
        )
    if event_type == "repair":
        repaired = repair_and_log(sim, payload["tractor_id"])
        schedule = schedule_and_apply(sim, fleet_agent, trigger="chaos_repair")
        return _result(
            sim=sim,
            event_type="random_repair",
            explanation=f"[seed={rng_seed}] " + repaired.recovery.explanation,
            correlation_id=repaired.recovery.correlation_id,
            before=_snapshots(state),
            affected_jobs=[a.job_id for a in schedule.assignments],
            preserved_work={},
            unreachable_jobs=[],
            safety_notes=["Repaired tractor re-entered idle pool"],
            schedule=schedule,
            seed=rng_seed,
        )
    if event_type == "block_route":
        out = chaos_block_route(sim, payload["x"], payload["y"], reason="chaos_random")
        return out.model_copy(
            update={
                "seed": rng_seed,
                "event_type": "random_block_route",
                "explanation": f"[seed={rng_seed}] " + out.explanation,
            }
        )
    if event_type == "unblock_route":
        out = chaos_unblock_route(sim, payload["x"], payload["y"])
        return out.model_copy(
            update={
                "seed": rng_seed,
                "event_type": "random_unblock_route",
                "explanation": f"[seed={rng_seed}] " + out.explanation,
            }
        )
    if event_type == "priority_change":
        out = chaos_priority_change(sim, payload["job_id"], payload["priority"])
        return out.model_copy(
            update={
                "seed": rng_seed,
                "event_type": "random_priority_change",
                "explanation": f"[seed={rng_seed}] " + out.explanation,
            }
        )
    if event_type == "fuel_change":
        out = chaos_fuel_change(sim, payload["tractor_id"], payload["fuel_level"])
        return out.model_copy(
            update={
                "seed": rng_seed,
                "event_type": "random_fuel_change",
                "explanation": f"[seed={rng_seed}] " + out.explanation,
            }
        )
    raise SimulationError(f"Unhandled chaos event {event_type}")
