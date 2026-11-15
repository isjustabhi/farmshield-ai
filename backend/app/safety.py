"""Safety Agent — validates complete proposed assignments."""

from __future__ import annotations

from dataclasses import dataclass

from .models import (
    FieldModel,
    FuelModel,
    GridConfig,
    Job,
    JobStatus,
    Position,
    SafetyValidationRequest,
    SafetyValidationResponse,
    Tractor,
    TractorStatus,
)
from .navigation import path_length, plan_path


@dataclass(frozen=True)
class FeasibilityResult:
    ok: bool
    reason: str | None = None
    path: list[Position] | None = None
    travel_cells: int = 0
    remaining_work: float = 0.0
    travel_fuel: float = 0.0
    work_fuel: float = 0.0
    estimated_fuel: float = 0.0
    travel_time: float = 0.0
    work_time: float = 0.0


def free_tractors(tractors: list[Tractor]) -> list[Tractor]:
    """Tractors that can accept a new job."""
    return [
        t
        for t in tractors
        if t.status == TractorStatus.IDLE
        and t.assigned_job_id is None
        and t.status != TractorStatus.BROKEN
    ]


def schedulable_jobs(jobs: list[Job]) -> list[Job]:
    """Pending jobs (including interrupted progress) whose dependencies are met."""
    by_id = {j.id: j for j in jobs}
    ready: list[Job] = []
    for job in jobs:
        if job.status != JobStatus.PENDING:
            continue
        if job.assigned_tractor_id is not None:
            continue
        if job.depends_on_job_id:
            dep = by_id.get(job.depends_on_job_id)
            if dep is None or dep.status != JobStatus.COMPLETED:
                continue
        ready.append(job)
    return ready


def field_position(fields: list[FieldModel], field_id: str) -> Position | None:
    for field in fields:
        if field.id == field_id:
            return field.position
    return None


def evaluate_pair(
    tractor: Tractor,
    job: Job,
    *,
    fields: list[FieldModel],
    grid: GridConfig,
    fuel: FuelModel,
    obstacles: set[tuple[int, int]],
) -> FeasibilityResult:
    """Validate hard constraints and compute travel/work/fuel estimates."""
    if tractor.status == TractorStatus.BROKEN:
        return FeasibilityResult(ok=False, reason="tractor_broken")
    if tractor.status != TractorStatus.IDLE or tractor.assigned_job_id is not None:
        return FeasibilityResult(ok=False, reason="tractor_not_free")
    if job.assigned_tractor_id is not None:
        return FeasibilityResult(ok=False, reason="job_already_owned")
    if job.status == JobStatus.BLOCKED:
        return FeasibilityResult(ok=False, reason="job_blocked_dependency")
    if job.status != JobStatus.PENDING:
        return FeasibilityResult(ok=False, reason=f"job_not_pending:{job.status.value}")
    if tractor.implement_type.value != job.job_type.value:
        return FeasibilityResult(
            ok=False,
            reason=(
                f"incompatible_equipment:"
                f"{tractor.implement_type.value}!={job.job_type.value}"
            ),
        )

    goal = field_position(fields, job.field_id)
    if goal is None:
        return FeasibilityResult(ok=False, reason="unknown_field")

    path = plan_path(tractor.position, goal, grid.width, grid.height, obstacles)
    if not path:
        return FeasibilityResult(ok=False, reason="unreachable_field")

    travel_cells = path_length(path)
    remaining_work = max(0.0, job.estimated_work_units - job.completed_work_units)
    if remaining_work <= 0:
        return FeasibilityResult(ok=False, reason="job_already_complete")

    travel_fuel = travel_cells * fuel.travel_per_cell
    work_fuel = remaining_work * fuel.work_per_unit
    estimated_fuel = travel_fuel + work_fuel + fuel.safety_reserve
    if tractor.fuel_level + 1e-9 < estimated_fuel:
        return FeasibilityResult(
            ok=False,
            reason=(
                f"insufficient_fuel:have={tractor.fuel_level:.3f},"
                f"need={estimated_fuel:.3f}"
            ),
            path=path,
            travel_cells=travel_cells,
            remaining_work=remaining_work,
            travel_fuel=travel_fuel,
            work_fuel=work_fuel,
            estimated_fuel=estimated_fuel,
        )

    travel_time = travel_cells / tractor.travel_speed if tractor.travel_speed > 0 else float("inf")
    work_time = remaining_work / tractor.working_speed if tractor.working_speed > 0 else float("inf")

    return FeasibilityResult(
        ok=True,
        path=path,
        travel_cells=travel_cells,
        remaining_work=remaining_work,
        travel_fuel=travel_fuel,
        work_fuel=work_fuel,
        estimated_fuel=estimated_fuel,
        travel_time=travel_time,
        work_time=work_time,
    )


class SafetyAgent:
    """Validates full proposed assignments before Fleet commit."""

    name = "safety_agent"

    def validate(self, request: SafetyValidationRequest) -> SafetyValidationResponse:
        proposal = request.proposal
        state = request.state
        violations: list[str] = []
        warnings: list[str] = []

        tractor = next((t for t in state.tractors if t.id == proposal.tractor_id), None)
        job = next((j for j in state.jobs if j.id == proposal.job_id), None)

        if tractor is None:
            violations.append("tractor_missing")
        if job is None:
            violations.append("job_missing")
        if violations:
            return SafetyValidationResponse(approved=False, violations=violations)

        assert tractor is not None and job is not None

        # Availability
        if tractor.status == TractorStatus.BROKEN:
            violations.append("tractor_broken")
        if tractor.status != TractorStatus.IDLE or tractor.assigned_job_id is not None:
            violations.append("tractor_unavailable")
        if proposal.tractor_id in request.reserved_tractor_ids:
            violations.append("conflicting_tractor_reservation")

        # Job ownership / conflict
        if job.assigned_tractor_id is not None:
            violations.append("job_already_owned")
        if proposal.job_id in request.reserved_job_ids:
            violations.append("conflicting_job_reservation")
        if job.status != JobStatus.PENDING:
            violations.append(f"job_not_assignable:{job.status.value}")

        # Implement compatibility
        if tractor.implement_type.value != job.job_type.value:
            violations.append(
                f"incompatible_equipment:{tractor.implement_type.value}!={job.job_type.value}"
            )

        # Preserve completed work
        expected = proposal.expected_completed_work_units
        if expected is not None and abs(job.completed_work_units - expected) > 1e-9:
            violations.append(
                f"completed_work_mismatch:have={job.completed_work_units},expected={expected}"
            )
        if job.completed_work_units + 1e-9 < proposal.completed_work_units:
            violations.append("completed_work_regression")

        # Route reachability (from Navigation Agent response)
        if not proposal.route.reachable:
            violations.append(proposal.route.reason or "unreachable_field")

        # Fuel reserve (travel + remaining work + safety reserve)
        remaining = max(0.0, job.estimated_work_units - job.completed_work_units)
        travel_fuel = proposal.route.travel_cells * state.fuel.travel_per_cell
        work_fuel = remaining * state.fuel.work_per_unit
        need = travel_fuel + work_fuel + state.fuel.safety_reserve
        if tractor.fuel_level + 1e-9 < need:
            violations.append(
                f"insufficient_fuel:have={tractor.fuel_level:.3f},need={need:.3f}"
            )

        # Deadline risk: report unavoidable lateness; do not fake feasibility.
        deadline_margin = proposal.deadline_minute - proposal.predicted_finish
        unavoidable = deadline_margin < 0
        if unavoidable:
            warnings.append(
                f"unavoidable_lateness:margin={deadline_margin:.3f},"
                f"deadline={proposal.deadline_minute},finish={proposal.predicted_finish:.3f}"
            )

        approved = not violations
        return SafetyValidationResponse(
            approved=approved,
            violations=violations,
            warnings=warnings,
            unavoidable_lateness=unavoidable,
            deadline_margin=deadline_margin,
        )


safety_agent = SafetyAgent()
