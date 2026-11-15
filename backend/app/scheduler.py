"""Fleet Agent — deterministic matching scheduler for small tractor fleets."""

from __future__ import annotations

import itertools
from dataclasses import dataclass

from .models import (
    AssignmentDecision,
    InfeasibleJobReport,
    Job,
    ScheduleResponse,
    ScoreComponents,
    SimulationState,
    Tractor,
)
from .safety import FeasibilityResult, evaluate_pair, free_tractors, schedulable_jobs

# Weights: higher total score is better. Deterministic and transparent.
W_PRIORITY = 40.0
W_DEADLINE_URGENCY = 25.0
W_LATENESS = 50.0
W_TRAVEL = 3.0
W_UNPRODUCTIVE = 2.0


@dataclass(frozen=True)
class ScoredPair:
    tractor_id: str
    job_id: str
    feasibility: FeasibilityResult
    predicted_finish: float
    deadline_margin: float
    score: ScoreComponents
    selection_reason: str


class FleetAgent:
    """Assigns free tractors to pending/interrupted jobs via exhaustive matching."""

    name = "farmshield"

    def __init__(self) -> None:
        self._decisions: list[AssignmentDecision] = []
        self._next_decision_id = 1
        self._active: dict[str, AssignmentDecision] = {}  # job_id -> decision

    def clear(self) -> None:
        self._decisions.clear()
        self._active.clear()
        self._next_decision_id = 1

    @property
    def decisions(self) -> list[AssignmentDecision]:
        return list(self._decisions)

    def active_assignments(self) -> list[AssignmentDecision]:
        return [self._active[k] for k in sorted(self._active)]

    def forget_job(self, job_id: str) -> None:
        self._active.pop(job_id, None)

    def plan(self, state: SimulationState) -> ScheduleResponse:
        """Compute a conflict-free assignment set without mutating simulation."""
        tractors = free_tractors(state.tractors)
        jobs = schedulable_jobs(state.jobs)
        obstacles = {(o.x, o.y) for o in state.obstacles}

        candidates: list[ScoredPair] = []
        infeasible_map: dict[str, list[str]] = {job.id: [] for job in jobs}

        for tractor in tractors:
            for job in jobs:
                feas = evaluate_pair(
                    tractor,
                    job,
                    fields=state.fields,
                    grid=state.grid,
                    fuel=state.fuel,
                    obstacles=obstacles,
                )
                if not feas.ok:
                    infeasible_map[job.id].append(f"{tractor.id}:{feas.reason}")
                    continue
                scored = self._score_pair(tractor, job, feas, state.sim_time)
                candidates.append(scored)

        # Jobs with zero feasible pairs keep aggregated tractor reasons.
        # Jobs that have at least one feasible pair are not "infeasible".
        feasible_job_ids = {c.job_id for c in candidates}
        infeasible_jobs = [
            InfeasibleJobReport(job_id=job_id, reasons=sorted(set(reasons)))
            for job_id, reasons in sorted(infeasible_map.items())
            if job_id not in feasible_job_ids and reasons
        ]
        # Also report schedulable jobs that had no free compatible tractor at all.
        for job in jobs:
            if job.id in feasible_job_ids:
                continue
            if job.id in {r.job_id for r in infeasible_jobs}:
                continue
            if not tractors:
                infeasible_jobs.append(
                    InfeasibleJobReport(
                        job_id=job.id,
                        reasons=["no_free_tractors"],
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

        chosen, matching_score = self._best_matching(candidates, tractors, jobs)

        assignments: list[AssignmentDecision] = []
        for pair in chosen:
            decision = AssignmentDecision(
                tractor_id=pair.tractor_id,
                job_id=pair.job_id,
                estimated_travel_time=pair.feasibility.travel_time,
                estimated_work_time=pair.feasibility.work_time,
                estimated_fuel_used=pair.feasibility.estimated_fuel,
                predicted_finish=pair.predicted_finish,
                deadline_margin=pair.deadline_margin,
                score_components=pair.score,
                selection_reason=pair.selection_reason,
                sim_time=state.sim_time,
                decision_id=self._next_decision_id,
                applied=False,
            )
            self._next_decision_id += 1
            assignments.append(decision)

        return ScheduleResponse(
            sim_time=state.sim_time,
            assignments=assignments,
            infeasible_jobs=infeasible_jobs,
            considered_pairs=len(candidates),
            matching_score=matching_score,
        )

    def record_applied(self, decisions: list[AssignmentDecision]) -> None:
        for decision in decisions:
            applied = decision.model_copy(update={"applied": True})
            self._decisions.append(applied)
            self._active[applied.job_id] = applied

    def sync_active_with_state(self, state: SimulationState) -> None:
        """Drop active decisions for jobs that are no longer owned."""
        owned = {
            j.id
            for j in state.jobs
            if j.assigned_tractor_id is not None
            or j.status.value in {"assigned", "in_progress"}
        }
        for job_id in list(self._active):
            if job_id not in owned:
                self._active.pop(job_id, None)

    def _score_pair(
        self,
        tractor: Tractor,
        job: Job,
        feas: FeasibilityResult,
        sim_time: int,
    ) -> ScoredPair:
        predicted_finish = sim_time + feas.travel_time + feas.work_time
        deadline_margin = job.deadline_minute - predicted_finish

        # Lower priority number = more important in the seed scenario.
        priority_reward = W_PRIORITY * (6 - min(job.priority, 5))

        if deadline_margin < 0:
            lateness_penalty = W_LATENESS * (-deadline_margin)
            deadline_urgency = 0.0
        else:
            lateness_penalty = 0.0
            # Tight deadlines (small positive margin) score higher.
            deadline_urgency = W_DEADLINE_URGENCY / (1.0 + deadline_margin)

        travel_penalty = W_TRAVEL * feas.travel_time
        # Unproductive time ≈ travel before productive work starts.
        unproductive_penalty = W_UNPRODUCTIVE * feas.travel_time

        total = (
            priority_reward
            + deadline_urgency
            - lateness_penalty
            - travel_penalty
            - unproductive_penalty
        )

        reason = (
            f"match score={total:.3f} priority={job.priority} "
            f"travel={feas.travel_time:.2f}m work={feas.work_time:.2f}m "
            f"finish={predicted_finish:.2f} margin={deadline_margin:.2f} "
            f"fuel={feas.estimated_fuel:.2f}"
        )

        score = ScoreComponents(
            priority_reward=priority_reward,
            deadline_urgency=deadline_urgency,
            lateness_penalty=lateness_penalty,
            travel_penalty=travel_penalty,
            unproductive_penalty=unproductive_penalty,
            total=total,
        )
        return ScoredPair(
            tractor_id=tractor.id,
            job_id=job.id,
            feasibility=feas,
            predicted_finish=predicted_finish,
            deadline_margin=deadline_margin,
            score=score,
            selection_reason=reason,
        )

    def _best_matching(
        self,
        candidates: list[ScoredPair],
        tractors: list[Tractor],
        jobs: list[Job],
    ) -> tuple[list[ScoredPair], float]:
        if not candidates:
            return [], 0.0

        by_pair = {(c.tractor_id, c.job_id): c for c in candidates}
        tractor_ids = sorted(t.id for t in tractors)
        job_ids = sorted(j.id for j in jobs)
        max_k = min(len(tractor_ids), len(job_ids), len({c.tractor_id for c in candidates}))

        best_pairs: list[ScoredPair] = []
        best_score = float("-inf")
        best_key: tuple = ()

        # Exhaustive matchings for small fleets (3×10 is trivial).
        for k in range(max_k, 0, -1):
            for job_subset in itertools.combinations(job_ids, k):
                for tractor_subset in itertools.combinations(tractor_ids, k):
                    for job_perm in itertools.permutations(job_subset, k):
                        pairs: list[ScoredPair] = []
                        ok = True
                        total = 0.0
                        for tractor_id, job_id in zip(tractor_subset, job_perm, strict=True):
                            scored = by_pair.get((tractor_id, job_id))
                            if scored is None:
                                ok = False
                                break
                            pairs.append(scored)
                            total += scored.score.total
                        if not ok:
                            continue
                        # Maximize assignment count, then score; lex-smaller pair
                        # list wins deterministic ties.
                        candidate_key = (
                            k,
                            total,
                            tuple(sorted((p.tractor_id, p.job_id) for p in pairs)),
                        )
                        better = best_score == float("-inf") or (
                            candidate_key[0] > best_key[0]
                            or (
                                candidate_key[0] == best_key[0]
                                and candidate_key[1] > best_key[1]
                            )
                            or (
                                candidate_key[0] == best_key[0]
                                and candidate_key[1] == best_key[1]
                                and candidate_key[2] < best_key[2]
                            )
                        )
                        if better:
                            best_score = total
                            best_pairs = pairs
                            best_key = candidate_key

            if best_pairs and best_key and best_key[0] == k:
                break

        best_pairs_sorted = sorted(best_pairs, key=lambda p: (p.tractor_id, p.job_id))
        return best_pairs_sorted, (best_score if best_pairs else 0.0)


fleet_agent = FleetAgent()
