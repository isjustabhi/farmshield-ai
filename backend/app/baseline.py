"""First-come, first-served scheduling baseline.

Jobs are considered in scenario submission order and assigned to the first
available feasible tractor (scenario tractor order). Feasibility uses the same
`evaluate_pair` gate as the Fleet Agent; commits still go through Navigation +
Safety validation in `schedule_and_apply`.
"""

from __future__ import annotations

from .models import (
    AssignmentDecision,
    InfeasibleJobReport,
    Job,
    ScheduleResponse,
    ScoreComponents,
    SimulationState,
)
from .safety import evaluate_pair, free_tractors, schedulable_jobs
from .scheduler import FleetAgent


class FCFSBaselineAgent(FleetAgent):
    """FCFS planner with the same apply/sync interface as FleetAgent."""

    name = "fcfs_baseline"

    def __init__(self, submission_order: list[str] | None = None) -> None:
        super().__init__()
        self._submission_order = list(submission_order or [])

    def set_submission_order(self, job_ids: list[str]) -> None:
        self._submission_order = list(job_ids)

    def plan(self, state: SimulationState) -> ScheduleResponse:
        """Assign earliest-submitted schedulable jobs to the first feasible free tractor."""
        tractors = free_tractors(state.tractors)
        jobs = schedulable_jobs(state.jobs)
        obstacles = {(o.x, o.y) for o in state.obstacles}

        order_index = {
            job_id: idx for idx, job_id in enumerate(self._submission_order)
        }
        # Unknown ids sort after known submission order, then by id for stability.
        jobs_ordered = sorted(
            jobs,
            key=lambda j: (order_index.get(j.id, 10_000 + hash(j.id) % 10_000), j.id),
        )
        # Tractor preference: scenario / state list order (not score-optimized).
        tractor_order = {t.id: i for i, t in enumerate(state.tractors)}
        tractors_ordered = sorted(
            tractors,
            key=lambda t: (tractor_order.get(t.id, 10_000), t.id),
        )

        used_tractors: set[str] = set()
        assignments: list[AssignmentDecision] = []
        infeasible_jobs: list[InfeasibleJobReport] = []
        considered = 0

        for job in jobs_ordered:
            assigned = False
            reject_reasons: list[str] = []
            for tractor in tractors_ordered:
                if tractor.id in used_tractors:
                    continue
                feas = evaluate_pair(
                    tractor,
                    job,
                    fields=state.fields,
                    grid=state.grid,
                    fuel=state.fuel,
                    obstacles=obstacles,
                )
                considered += 1
                if not feas.ok:
                    reject_reasons.append(f"{tractor.id}:{feas.reason}")
                    continue

                predicted_finish = state.sim_time + feas.travel_time + feas.work_time
                deadline_margin = job.deadline_minute - predicted_finish
                reason = (
                    f"fcfs submission_order={order_index.get(job.id, -1)} "
                    f"first_feasible={tractor.id} travel={feas.travel_time:.2f}m "
                    f"work={feas.work_time:.2f}m finish={predicted_finish:.2f} "
                    f"margin={deadline_margin:.2f}"
                )
                decision = AssignmentDecision(
                    tractor_id=tractor.id,
                    job_id=job.id,
                    estimated_travel_time=feas.travel_time,
                    estimated_work_time=feas.work_time,
                    estimated_fuel_used=feas.estimated_fuel,
                    predicted_finish=predicted_finish,
                    deadline_margin=deadline_margin,
                    score_components=ScoreComponents(
                        priority_reward=0.0,
                        deadline_urgency=0.0,
                        lateness_penalty=0.0,
                        travel_penalty=0.0,
                        unproductive_penalty=0.0,
                        total=0.0,
                    ),
                    selection_reason=reason,
                    sim_time=state.sim_time,
                    decision_id=self._next_decision_id,
                    applied=False,
                )
                self._next_decision_id += 1
                assignments.append(decision)
                used_tractors.add(tractor.id)
                assigned = True
                break

            if not assigned:
                if not tractors_ordered:
                    infeasible_jobs.append(
                        InfeasibleJobReport(job_id=job.id, reasons=["no_free_tractors"])
                    )
                elif reject_reasons:
                    infeasible_jobs.append(
                        InfeasibleJobReport(
                            job_id=job.id,
                            reasons=sorted(set(reject_reasons)),
                        )
                    )
                else:
                    infeasible_jobs.append(
                        InfeasibleJobReport(
                            job_id=job.id,
                            reasons=["no_feasible_tractor"],
                        )
                    )

        infeasible_jobs.sort(key=lambda r: r.job_id)
        return ScheduleResponse(
            sim_time=state.sim_time,
            assignments=assignments,
            infeasible_jobs=infeasible_jobs,
            considered_pairs=considered,
            matching_score=float(len(assignments)),
        )


def submission_order_from_scenario_jobs(jobs: list[Job]) -> list[str]:
    """Stable FCFS order = scenario JSON job array order."""
    return [j.id for j in jobs]
