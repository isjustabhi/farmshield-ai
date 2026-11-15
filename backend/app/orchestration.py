"""Multi-agent orchestration — explicit Fleet/Nav/Safety/Recovery decision flow."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from typing import Any, TypeVar

from . import memory as memory_service
from .metrics import agent_observability
from .models import (
    AgentTrace,
    AssignmentDecision,
    BreakdownResponse,
    IncidentRequest,
    JobStatus,
    ProposedAssignment,
    RecoveryProposal,
    RepairResponse,
    ReplanResponse,
    RouteRequest,
    RouteResponse,
    SafetyValidationRequest,
    SafetyValidationResponse,
    ScheduleResponse,
)
from .navigation import navigation_agent
from .recovery import (
    build_breakdown_explanation,
    percent_complete,
    recovery_agent,
)
from .safety import field_position, safety_agent
from .scheduler import FleetAgent, fleet_agent

R = TypeVar("R")


class AgentBus:
    """Records real wall-clock processing latency for in-process agent calls."""

    def call(
        self,
        *,
        sender: str,
        receiver: str,
        request_type: str,
        response_type: str,
        request: Any,
        handler: Callable[[Any], R],
        simulation_timestamp: int,
        correlation_id: str,
        decision_id: str | None = None,
        status_from_response: Callable[[R], str] | None = None,
    ) -> R:
        start_wall = time.time()
        start_perf = time.perf_counter()
        status = "ok"
        detail: dict[str, Any] = {
            "request": request.model_dump() if hasattr(request, "model_dump") else str(request),
        }
        try:
            response = handler(request)
            if status_from_response is not None:
                status = status_from_response(response)
            detail["response"] = (
                response.model_dump() if hasattr(response, "model_dump") else str(response)
            )
            return response
        except Exception as exc:  # noqa: BLE001 — recorded as failed agent call
            status = "error"
            detail["error"] = str(exc)
            raise
        finally:
            end_perf = time.perf_counter()
            end_wall = time.time()
            trace = AgentTrace(
                correlation_id=correlation_id,
                decision_id=decision_id,
                sender=sender,
                receiver=receiver,
                request_type=request_type,
                response_type=response_type,
                start_wall_time=start_wall,
                end_wall_time=end_wall,
                duration_ms=(end_perf - start_perf) * 1000.0,
                status=status,
                simulation_timestamp=simulation_timestamp,
                transport="in_process",
                detail=detail,
            )
            agent_observability.record_trace(trace)


agent_bus = AgentBus()


def _safety_status(response: SafetyValidationResponse) -> str:
    if not response.approved:
        return "rejected"
    if response.unavoidable_lateness:
        return "ok_with_lateness"
    return "ok"


def _route_status(response: RouteResponse) -> str:
    return "ok" if response.reachable else "rejected"


def _active_assignment_job_ids(sim: Any) -> list[str]:
    state = sim.get_state()
    return sorted(
        j.id
        for j in state.jobs
        if j.assigned_tractor_id is not None
        and j.status in {JobStatus.ASSIGNED, JobStatus.IN_PROGRESS}
    )


def schedule_and_apply(
    sim: Any,
    agent: FleetAgent | None = None,
    *,
    correlation_id: str | None = None,
    trigger: str = "schedule",
    record_replan: bool | None = None,
) -> ScheduleResponse:
    """Fleet plans, then Nav+Safety validate each assignment before commit."""
    from .simulation import SimulationError

    agent = agent or getattr(sim, "scheduler_agent", None) or fleet_agent
    correlation_id = correlation_id or str(uuid.uuid4())
    cycle_start = time.perf_counter()
    if record_replan is None:
        record_replan = trigger == "recovery"
    isolated = bool(getattr(sim, "isolated", False))
    agent_label = getattr(agent, "name", agent.__class__.__name__)

    state = sim.get_state()
    agent.sync_active_with_state(state)
    plan = agent.plan(state)

    applied: list[AssignmentDecision] = []
    reserved_tractors: list[str] = []
    reserved_jobs: list[str] = []
    rejected_reports = list(plan.infeasible_jobs)

    for decision in plan.assignments:
        decision_id = str(decision.decision_id)
        tractor = next(t for t in state.tractors if t.id == decision.tractor_id)
        job = next(j for j in state.jobs if j.id == decision.job_id)
        goal = field_position(state.fields, job.field_id)
        if goal is None:
            continue

        # Fleet -> Navigation -> Fleet
        route = agent_bus.call(
            sender="fleet_agent",
            receiver="navigation_agent",
            request_type="RouteRequest",
            response_type="RouteResponse",
            request=RouteRequest(
                tractor_id=tractor.id,
                job_id=job.id,
                start=tractor.position,
                goal=goal,
                grid=state.grid,
                obstacles=state.obstacles,
                travel_speed=tractor.travel_speed,
            ),
            handler=navigation_agent.route,
            simulation_timestamp=state.sim_time,
            correlation_id=correlation_id,
            decision_id=decision_id,
            status_from_response=_route_status,
        )

        remaining = max(0.0, job.estimated_work_units - job.completed_work_units)
        work_time = remaining / tractor.working_speed if tractor.working_speed > 0 else float("inf")
        travel_fuel = route.travel_cells * state.fuel.travel_per_cell
        work_fuel = remaining * state.fuel.work_per_unit
        estimated_fuel = travel_fuel + work_fuel + state.fuel.safety_reserve
        predicted_finish = state.sim_time + route.travel_time + work_time
        deadline_margin = job.deadline_minute - predicted_finish

        proposal = ProposedAssignment(
            tractor_id=tractor.id,
            job_id=job.id,
            completed_work_units=job.completed_work_units,
            estimated_work_units=job.estimated_work_units,
            predicted_finish=predicted_finish,
            deadline_minute=job.deadline_minute,
            estimated_fuel_used=estimated_fuel,
            route=route,
            expected_completed_work_units=job.completed_work_units,
        )

        # Fleet -> Safety -> Fleet
        validation = agent_bus.call(
            sender="fleet_agent",
            receiver="safety_agent",
            request_type="SafetyValidationRequest",
            response_type="SafetyValidationResponse",
            request=SafetyValidationRequest(
                proposal=proposal,
                state=state,
                reserved_tractor_ids=list(reserved_tractors),
                reserved_job_ids=list(reserved_jobs),
            ),
            handler=safety_agent.validate,
            simulation_timestamp=state.sim_time,
            correlation_id=correlation_id,
            decision_id=decision_id,
            status_from_response=_safety_status,
        )

        if not validation.approved:
            counters = getattr(sim, "benchmark_counters", None)
            if isinstance(counters, dict):
                counters["safety_violations"] = int(counters.get("safety_violations", 0)) + 1
            continue

        enriched = decision.model_copy(
            update={
                "estimated_travel_time": route.travel_time,
                "estimated_work_time": work_time,
                "estimated_fuel_used": estimated_fuel,
                "predicted_finish": predicted_finish,
                "deadline_margin": deadline_margin,
                "selection_reason": (
                    f"{decision.selection_reason} | validated "
                    f"corr={correlation_id[:8]} trigger={trigger}"
                    + (
                        " | unavoidable_lateness"
                        if validation.unavoidable_lateness
                        else ""
                    )
                ),
            }
        )

        try:
            sim.assign_job(
                enriched.tractor_id,
                enriched.job_id,
                reason=f"{agent_label}:{enriched.selection_reason}",
            )
        except SimulationError:
            continue

        reserved_tractors.append(enriched.tractor_id)
        reserved_jobs.append(enriched.job_id)
        applied.append(enriched)

        for t in state.tractors:
            if t.id == enriched.tractor_id:
                t.assigned_job_id = enriched.job_id
        for j in state.jobs:
            if j.id == enriched.job_id:
                j.assigned_tractor_id = enriched.tractor_id
                j.status = JobStatus.ASSIGNED

    response = ScheduleResponse(
        sim_time=plan.sim_time,
        assignments=applied,
        infeasible_jobs=rejected_reports,
        considered_pairs=plan.considered_pairs,
        matching_score=plan.matching_score,
    )

    if applied:
        agent.record_applied(applied)
        if not isolated:
            agent_observability.record_commit(len(applied))

    if not isolated:
        memory_service.operational_memory.persist_schedule_cycle(
            schedule=response,
            correlation_id=correlation_id,
            trigger=trigger,
            applied=applied,
        )
        memory_service.operational_memory.persist_performance_summary(
            simulation_time=plan.sim_time,
            metrics=agent_observability.metrics().model_dump(),
            summary_key=f"after_{trigger}",
        )

    if record_replan and not isolated:
        agent_observability.record_replan_latency((time.perf_counter() - cycle_start) * 1000.0)

    return response


def _field_id_for_job(sim: Any, job_id: str | None) -> str | None:
    if not job_id:
        return None
    job = getattr(sim, "jobs", {}).get(job_id)
    return getattr(job, "field_id", None) if job is not None else None


def _blocking_reason_for_job(schedule: ScheduleResponse, job_id: str | None) -> str | None:
    if job_id is None:
        return None
    for report in schedule.infeasible_jobs:
        if report.job_id == job_id and report.reasons:
            return "; ".join(report.reasons)
    # Job may be feasible but unmatched due to tractor scarcity in this cycle.
    assigned = {a.job_id for a in schedule.assignments}
    if job_id not in assigned:
        return "no_compatible_replacement"
    return None


def breakdown_and_recover(
    sim: Any,
    tractor_id: str,
    reason: str = "manual_breakdown",
) -> BreakdownResponse:
    """API/self-healing path: stop tractor, preserve work, replan unfinished jobs."""
    correlation_id = str(uuid.uuid4())
    replan_start = time.perf_counter()

    retained_before = set(_active_assignment_job_ids(sim))
    snapshot = sim.breakdown_tractor(tractor_id, reason=reason)

    job_id = snapshot.get("job_id")
    preserved = float(snapshot.get("preserved_work_units") or 0.0)
    percent = snapshot.get("percent_complete")
    if percent is None and snapshot.get("estimated_work_units"):
        percent = percent_complete(preserved, float(snapshot["estimated_work_units"]))
    remaining_percent = None if percent is None else max(0.0, 100.0 - float(percent))
    prior_status = snapshot.get("prior_status")

    proposal = agent_bus.call(
        sender="simulation",
        receiver="recovery_agent",
        request_type="IncidentRequest",
        response_type="RecoveryProposal",
        request=IncidentRequest(
            tractor_id=tractor_id,
            job_id=job_id,
            reason=reason,
            completed_work_units=preserved,
            simulation_timestamp=snapshot["sim_time"],
            prior_status=prior_status,
            percent_complete=percent,
        ),
        handler=recovery_agent.handle_incident,
        simulation_timestamp=snapshot["sim_time"],
        correlation_id=correlation_id,
        decision_id=None,
    )

    schedule: ScheduleResponse | None = None
    if proposal.recommend_reschedule and not snapshot.get("already_broken"):
        bound = getattr(sim, "scheduler_agent", None) or fleet_agent
        schedule = schedule_and_apply(
            sim,
            bound,
            correlation_id=correlation_id,
            trigger="recovery",
            record_replan=False,
        )
        agent_observability.record_replan_latency((time.perf_counter() - replan_start) * 1000.0)
    else:
        schedule = ScheduleResponse(
            sim_time=snapshot["sim_time"],
            assignments=[],
            infeasible_jobs=[],
            considered_pairs=0,
            matching_score=0.0,
        )

    reassigned_to = None
    if job_id:
        for decision in schedule.assignments:
            if decision.job_id == job_id:
                reassigned_to = decision.tractor_id
                break

    retained_after = set(_active_assignment_job_ids(sim))
    retained = sorted((retained_before & retained_after) - ({job_id} if job_id else set()))
    blocking = None
    if job_id and reassigned_to is None and proposal.recommend_reschedule:
        blocking = _blocking_reason_for_job(schedule, job_id)

    explanation = build_breakdown_explanation(
        tractor_id=tractor_id,
        job_id=job_id,
        percent=percent,
        remaining_percent=remaining_percent,
        preserved_work_units=preserved,
        reassigned_to=reassigned_to,
        blocking_reason=blocking,
        prior_status=prior_status,
    )

    log = memory_service.recovery_memory.append(
        recovery_agent.make_log(
            sim_time=snapshot["sim_time"],
            correlation_id=correlation_id,
            event_type="breakdown",
            tractor_id=tractor_id,
            job_id=job_id,
            field_id=_field_id_for_job(sim, job_id),
            prior_status=prior_status,
            preserved_work_units=preserved,
            percent=None if percent is None else float(percent),
            remaining_percent=remaining_percent,
            reassigned_to=reassigned_to,
            retained_assignment_job_ids=retained,
            new_assignments=schedule.assignments,
            blocking_reason=blocking,
            explanation=explanation,
            feasible=reassigned_to is not None or job_id is None or not proposal.recommend_reschedule,
        )
    )

    sim.emit_event(
        event_type="recovery_plan",
        message=explanation,
        tractor_id=tractor_id,
        job_id=job_id,
        data={
            "correlation_id": correlation_id,
            "reassigned_to": reassigned_to,
            "blocking_reason": blocking,
            "preserved_work_units": preserved,
            "percent_complete": percent,
        },
    )

    return BreakdownResponse(
        ok=True,
        state=sim.get_state(),
        recovery=log,
        schedule=schedule,
    )


def repair_and_log(sim: Any, tractor_id: str) -> RepairResponse:
    correlation_id = str(uuid.uuid4())
    info = sim.repair_tractor(tractor_id)
    explanation = (
        f"Tractor {tractor_id} repaired at sim_time={info['sim_time']} "
        "and returned to idle for future scheduling."
    )
    proposal = agent_bus.call(
        sender="simulation",
        receiver="recovery_agent",
        request_type="RepairNotice",
        response_type="RecoveryProposal",
        request=IncidentRequest(
            tractor_id=tractor_id,
            job_id=None,
            reason="repair",
            completed_work_units=0.0,
            simulation_timestamp=info["sim_time"],
            prior_status="broken",
            percent_complete=None,
        ),
        handler=recovery_agent.handle_incident,
        simulation_timestamp=info["sim_time"],
        correlation_id=correlation_id,
        decision_id=None,
    )
    _ = proposal
    log = memory_service.recovery_memory.append(
        recovery_agent.make_log(
            sim_time=info["sim_time"],
            correlation_id=correlation_id,
            event_type="repair",
            tractor_id=tractor_id,
            job_id=None,
            prior_status="broken",
            preserved_work_units=0.0,
            percent=None,
            remaining_percent=None,
            reassigned_to=None,
            retained_assignment_job_ids=_active_assignment_job_ids(sim),
            new_assignments=[],
            blocking_reason=None,
            explanation=explanation,
            feasible=True,
        )
    )
    return RepairResponse(ok=True, state=sim.get_state(), recovery=log)


def replan_unfinished(sim: Any) -> ReplanResponse:
    """Reassign pending/interrupted jobs without disturbing safe active work."""
    correlation_id = str(uuid.uuid4())
    replan_start = time.perf_counter()
    retained_before = _active_assignment_job_ids(sim)

    bound = getattr(sim, "scheduler_agent", None) or fleet_agent
    schedule = schedule_and_apply(
        sim,
        bound,
        correlation_id=correlation_id,
        trigger="recovery",
        record_replan=False,
    )
    if not getattr(sim, "isolated", False):
        agent_observability.record_replan_latency((time.perf_counter() - replan_start) * 1000.0)

    retained_after = set(_active_assignment_job_ids(sim))
    retained = sorted(set(retained_before) & retained_after)
    explanation = (
        f"Replan committed {len(schedule.assignments)} new assignment(s) "
        f"while retaining {len(retained)} safe active assignment(s)."
    )
    if schedule.infeasible_jobs:
        waiting = ", ".join(r.job_id for r in schedule.infeasible_jobs)
        explanation += f" Waiting/unassigned jobs: {waiting}."

    log = memory_service.recovery_memory.append(
        recovery_agent.make_log(
            sim_time=schedule.sim_time,
            correlation_id=correlation_id,
            event_type="replan",
            tractor_id="fleet",
            job_id=None,
            prior_status=None,
            preserved_work_units=0.0,
            percent=None,
            remaining_percent=None,
            reassigned_to=None,
            retained_assignment_job_ids=retained,
            new_assignments=schedule.assignments,
            blocking_reason=None,
            explanation=explanation,
            feasible=True,
        )
    )
    return ReplanResponse(
        ok=True,
        state=sim.get_state(),
        recovery=log,
        schedule=schedule,
    )


def handle_simulation_incident(
    sim: Any,
    *,
    tractor_id: str,
    job_id: str | None,
    reason: str,
    completed_work_units: float,
    simulation_timestamp: int,
    prior_status: str | None = None,
    percent_complete: float | None = None,
) -> RecoveryProposal:
    """Failure flow used by internal sim fuel failures after atomic release."""
    correlation_id = str(uuid.uuid4())
    replan_start = time.perf_counter()

    if percent_complete is None and job_id:
        job = sim.jobs.get(job_id)
        if job is not None and job.estimated_work_units > 0:
            percent_complete = (
                completed_work_units / job.estimated_work_units
            ) * 100.0

    proposal = agent_bus.call(
        sender="simulation",
        receiver="recovery_agent",
        request_type="IncidentRequest",
        response_type="RecoveryProposal",
        request=IncidentRequest(
            tractor_id=tractor_id,
            job_id=job_id,
            reason=reason,
            completed_work_units=completed_work_units,
            simulation_timestamp=simulation_timestamp,
            prior_status=prior_status,
            percent_complete=percent_complete,
        ),
        handler=recovery_agent.handle_incident,
        simulation_timestamp=simulation_timestamp,
        correlation_id=correlation_id,
        decision_id=None,
    )

    schedule = ScheduleResponse(
        sim_time=simulation_timestamp,
        assignments=[],
        infeasible_jobs=[],
        considered_pairs=0,
        matching_score=0.0,
    )
    if proposal.recommend_reschedule:
        bound = getattr(sim, "scheduler_agent", None) or fleet_agent
        schedule = schedule_and_apply(
            sim,
            bound,
            correlation_id=correlation_id,
            trigger="recovery",
            record_replan=False,
        )
        if not getattr(sim, "isolated", False):
            agent_observability.record_replan_latency(
                (time.perf_counter() - replan_start) * 1000.0
            )

    reassigned_to = None
    if job_id:
        for decision in schedule.assignments:
            if decision.job_id == job_id:
                reassigned_to = decision.tractor_id
                break
    remaining = None if percent_complete is None else max(0.0, 100.0 - percent_complete)
    blocking = None
    if job_id and reassigned_to is None and proposal.recommend_reschedule:
        blocking = _blocking_reason_for_job(schedule, job_id)
    explanation = build_breakdown_explanation(
        tractor_id=tractor_id,
        job_id=job_id,
        percent=percent_complete,
        remaining_percent=remaining,
        preserved_work_units=completed_work_units,
        reassigned_to=reassigned_to,
        blocking_reason=blocking,
        prior_status=prior_status,
    )
    memory_service.recovery_memory.append(
        recovery_agent.make_log(
            sim_time=simulation_timestamp,
            correlation_id=correlation_id,
            event_type="breakdown",
            tractor_id=tractor_id,
            job_id=job_id,
            field_id=_field_id_for_job(sim, job_id),
            prior_status=prior_status,
            preserved_work_units=completed_work_units,
            percent=percent_complete,
            remaining_percent=remaining,
            reassigned_to=reassigned_to,
            retained_assignment_job_ids=_active_assignment_job_ids(sim),
            new_assignments=schedule.assignments,
            blocking_reason=blocking,
            explanation=explanation,
            feasible=reassigned_to is not None or job_id is None,
        )
    )
    return proposal


def clear_fleet_memory(agent: FleetAgent | None = None) -> None:
    (agent or fleet_agent).clear()
    agent_observability.clear()
    memory_service.recovery_memory.clear()
    # Does not wipe SQLite historical runs.
