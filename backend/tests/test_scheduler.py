"""Fleet Agent scheduling constraint and matching tests."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import JobStatus, TractorStatus
from app.orchestration import schedule_and_apply
from app.scheduler import FleetAgent, fleet_agent
from app.simulation import SimulationService

SCENARIO = Path(__file__).resolve().parent.parent / "data" / "scenario.json"
client = TestClient(app)


@pytest.fixture()
def sim() -> SimulationService:
    service = SimulationService(SCENARIO, play_interval_sec=0.01)
    service.auto_schedule = False
    service.auto_recover = False
    agent = FleetAgent()
    yield service, agent
    service.pause()


def test_wrong_equipment_is_infeasible(sim) -> None:
    service, agent = sim
    # Only free tractor is spraying; leave only a mowing job pending.
    for job in service.jobs.values():
        if job.job_type.value != "mowing":
            job.status = JobStatus.COMPLETED
        elif job.status == JobStatus.BLOCKED:
            job.status = JobStatus.PENDING
            job.depends_on_job_id = None
    for tractor in service.tractors.values():
        if tractor.implement_type.value != "spraying":
            tractor.status = TractorStatus.BROKEN

    result = schedule_and_apply(service, agent)
    assert result.assignments == []
    assert result.infeasible_jobs
    assert any(
        "incompatible_equipment" in reason
        for report in result.infeasible_jobs
        for reason in report.reasons
    )


def test_low_fuel_is_infeasible(sim) -> None:
    service, agent = sim
    for tractor in service.tractors.values():
        tractor.fuel_level = 0.5
    result = schedule_and_apply(service, agent)
    assert result.assignments == []
    assert any(
        "insufficient_fuel" in reason
        for report in result.infeasible_jobs
        for reason in report.reasons
    )


def test_broken_tractor_excluded(sim) -> None:
    service, agent = sim
    for tractor in service.tractors.values():
        tractor.status = TractorStatus.BROKEN
    result = schedule_and_apply(service, agent)
    assert result.assignments == []
    assert any(
        report.reasons == ["no_free_tractors"] or "no_feasible_tractor" in report.reasons
        for report in result.infeasible_jobs
    )


def test_duplicate_assignment_prevented(sim) -> None:
    service, agent = sim
    first = schedule_and_apply(service, agent)
    assert first.assignments
    owned = {(a.tractor_id, a.job_id) for a in first.assignments}
    second = schedule_and_apply(service, agent)
    for decision in second.assignments:
        assert (decision.tractor_id, decision.job_id) not in owned
        assert decision.job_id not in {a.job_id for a in first.assignments}
        assert decision.tractor_id not in {a.tractor_id for a in first.assignments}


def test_deadline_urgency_prefers_sooner_deadline(sim) -> None:
    service, agent = sim
    # Isolate one spraying tractor and two equal spraying jobs with different deadlines.
    for tractor_id, tractor in list(service.tractors.items()):
        if tractor_id != "tractor_01":
            tractor.status = TractorStatus.BROKEN
    for job in service.jobs.values():
        job.status = JobStatus.COMPLETED

    near = service.jobs["job_01"]
    far = service.jobs["job_03"]
    near.status = JobStatus.PENDING
    far.status = JobStatus.PENDING
    near.completed_work_units = 0.0
    far.completed_work_units = 0.0
    near.estimated_work_units = 5.0
    far.estimated_work_units = 5.0
    near.priority = 2
    far.priority = 2
    near.deadline_minute = 30
    far.deadline_minute = 500
    # Place tractor equidistant-ish by putting it at origin; fields differ but
    # deadline gap dominates travel difference under our weights.
    service.tractors["tractor_01"].position.x = 0
    service.tractors["tractor_01"].position.y = 0

    result = schedule_and_apply(service, agent)
    assert len(result.assignments) == 1
    assert result.assignments[0].job_id == "job_01"
    assert result.assignments[0].deadline_margin < (
        far.deadline_minute - result.assignments[0].predicted_finish
    )


def test_deterministic_tie_breaking(sim) -> None:
    service, agent = sim
    state = service.get_state()
    # Two spraying tractors, one job — lower tractor_id must win when scores tie path.
    for job in state.jobs:
        job.status = JobStatus.COMPLETED
    job = next(j for j in state.jobs if j.id == "job_07")
    job.status = JobStatus.PENDING
    job.depends_on_job_id = None
    job.priority = 3
    job.deadline_minute = 1000
    job.estimated_work_units = 4.0
    job.completed_work_units = 0.0

    for tractor in state.tractors:
        if tractor.implement_type.value != "spraying":
            tractor.status = TractorStatus.BROKEN
            continue
        tractor.status = TractorStatus.IDLE
        tractor.assigned_job_id = None
        tractor.fuel_level = 100.0
        # Identical pose so travel estimates match.
        tractor.position.x = 10
        tractor.position.y = 10
        tractor.travel_speed = 2.0
        tractor.working_speed = 1.0

    plan_a = agent.plan(state)
    plan_b = agent.plan(deepcopy(state))
    assert plan_a.assignments
    assert plan_a.assignments[0].tractor_id == plan_b.assignments[0].tractor_id
    assert plan_a.assignments[0].tractor_id == "tractor_01"


def test_no_feasible_tractor_reports_reason(sim) -> None:
    service, agent = sim
    for tractor in service.tractors.values():
        tractor.status = TractorStatus.BROKEN
    for job in service.jobs.values():
        if job.status == JobStatus.BLOCKED:
            continue
        job.status = JobStatus.PENDING
    result = agent.plan(service.get_state())
    assert result.assignments == []
    assert result.infeasible_jobs
    assert all(r.reasons for r in result.infeasible_jobs)


def test_assignment_payload_fields(sim) -> None:
    service, agent = sim
    result = schedule_and_apply(service, agent)
    assert result.assignments
    decision = result.assignments[0]
    assert decision.tractor_id
    assert decision.job_id
    assert decision.estimated_travel_time >= 0
    assert decision.estimated_work_time > 0
    assert decision.estimated_fuel_used > 0
    assert decision.predicted_finish > service.sim_time
    assert decision.score_components.total == (
        decision.score_components.priority_reward
        + decision.score_components.deadline_urgency
        - decision.score_components.lateness_penalty
        - decision.score_components.travel_penalty
        - decision.score_components.unproductive_penalty
    )
    assert decision.selection_reason
    assert service.jobs[decision.job_id].assigned_tractor_id == decision.tractor_id
    assert service.tractors[decision.tractor_id].assigned_job_id == decision.job_id


def test_api_schedule_assignments_decisions() -> None:
    fleet_agent.clear()
    reset = client.post("/api/simulation/reset")
    assert reset.status_code == 200

    scheduled = client.post("/api/schedule")
    assert scheduled.status_code == 200
    body = scheduled.json()
    assert body["assignments"]
    assert "infeasible_jobs" in body
    decision = body["assignments"][0]
    for key in (
        "tractor_id",
        "job_id",
        "estimated_travel_time",
        "estimated_work_time",
        "estimated_fuel_used",
        "predicted_finish",
        "deadline_margin",
        "score_components",
        "selection_reason",
    ):
        assert key in decision

    assignments = client.get("/api/assignments")
    assert assignments.status_code == 200
    assert assignments.json()["active"]
    assert assignments.json()["active_job_ids"]

    decisions = client.get("/api/decisions")
    assert decisions.status_code == 200
    assert len(decisions.json()["decisions"]) >= 1


def test_auto_schedule_on_step_integrates() -> None:
    fleet_agent.clear()
    client.post("/api/simulation/reset")
    stepped = client.post("/api/simulation/step")
    assert stepped.status_code == 200
    state = stepped.json()["state"]
    assigned = [j for j in state["jobs"] if j["assigned_tractor_id"]]
    assert assigned
    decisions = client.get("/api/decisions").json()["decisions"]
    assert decisions
