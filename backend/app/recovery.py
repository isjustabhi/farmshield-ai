"""Recovery Agent — incident handling, explanations, and replan proposals."""

from __future__ import annotations

from .models import (
    AssignmentDecision,
    IncidentRequest,
    RecoveryLogEntry,
    RecoveryProposal,
)


def percent_complete(completed: float, estimated: float) -> float:
    if estimated <= 0:
        return 0.0
    return max(0.0, min(100.0, (completed / estimated) * 100.0))


def build_breakdown_explanation(
    *,
    tractor_id: str,
    job_id: str | None,
    percent: float | None,
    remaining_percent: float | None,
    preserved_work_units: float,
    reassigned_to: str | None,
    blocking_reason: str | None,
    prior_status: str | None,
) -> str:
    """Factual explanation derived only from actual recovery state."""
    if job_id is None:
        return (
            f"Tractor {tractor_id} failed while {prior_status or 'idle'} with no active job. "
            "No assignment was released. The tractor is marked broken and excluded from scheduling."
        )

    pct = 0.0 if percent is None else percent
    rem = 0.0 if remaining_percent is None else remaining_percent
    base = (
        f"Tractor {tractor_id} failed at {pct:.0f}% completion of Job {job_id} "
        f"({preserved_work_units:.3f} work units preserved)."
    )

    if reassigned_to:
        return (
            f"{base} The remaining {rem:.0f}% has been reassigned to Tractor {reassigned_to}. "
            "The replacement was selected because it has a compatible implement, "
            "sufficient fuel and a feasible route."
        )

    reason = blocking_reason or "no_compatible_replacement"
    return (
        f"{base} The remaining {rem:.0f}% could not be reassigned ({reason}). "
        f"Job {job_id} remains waiting/unassigned with preserved progress."
    )


class RecoveryAgent:
    """Deterministic recovery proposals after tractor/job incidents."""

    name = "recovery_agent"

    def handle_incident(self, request: IncidentRequest) -> RecoveryProposal:
        rem_pct = None
        if request.percent_complete is not None:
            rem_pct = max(0.0, 100.0 - request.percent_complete)

        recommend = bool(request.job_id) and (
            request.percent_complete is None or request.percent_complete < 100.0 - 1e-9
        )
        notes = (
            f"Incident on {request.tractor_id}"
            + (f"/{request.job_id}" if request.job_id else "")
            + f": {request.reason}. "
            f"Preserving completed_work_units={request.completed_work_units:.6f}. "
            + (
                "Recommend Fleet Agent reschedule for remaining free tractors."
                if recommend
                else "No unfinished job to reassign."
            )
        )
        return RecoveryProposal(
            accept=True,
            released_job_id=request.job_id,
            failed_tractor_id=request.tractor_id,
            preserved_work_units=request.completed_work_units,
            recommend_reschedule=recommend,
            notes=notes,
            percent_complete=request.percent_complete,
            remaining_percent=rem_pct,
        )

    def make_log(
        self,
        *,
        sim_time: int,
        correlation_id: str,
        event_type: str,
        tractor_id: str,
        job_id: str | None,
        field_id: str | None = None,
        prior_status: str | None,
        preserved_work_units: float,
        percent: float | None,
        remaining_percent: float | None,
        reassigned_to: str | None,
        retained_assignment_job_ids: list[str],
        new_assignments: list[AssignmentDecision],
        blocking_reason: str | None,
        explanation: str,
        feasible: bool,
    ) -> RecoveryLogEntry:
        return RecoveryLogEntry(
            id=0,
            sim_time=sim_time,
            correlation_id=correlation_id,
            event_type=event_type,
            tractor_id=tractor_id,
            job_id=job_id,
            field_id=field_id,
            prior_status=prior_status,
            preserved_work_units=preserved_work_units,
            percent_complete=percent,
            remaining_percent=remaining_percent,
            reassigned_to=reassigned_to,
            retained_assignment_job_ids=retained_assignment_job_ids,
            new_assignment_job_ids=[a.job_id for a in new_assignments],
            blocking_reason=blocking_reason,
            explanation=explanation,
            feasible=feasible,
        )


recovery_agent = RecoveryAgent()
