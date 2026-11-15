"""Self-healing recovery: breakdown, repair, replan invariants and special cases."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.memory import recovery_memory
from app.metrics import agent_observability
from app.models import JobStatus, TractorStatus
from app.orchestration import breakdown_and_recover, repair_and_log, schedule_and_apply
from app.scheduler import FleetAgent, fleet_agent
from app.simulation import SimulationService

SCENARIO = Path(__file__).resolve().parent.parent / "data" / "scenario.json"
client = TestClient(app)


@pytest.fixture()
def sim() -> SimulationService:
    service = SimulationService(SCENARIO, play_interval_sec=0.01)
    service.auto_schedule = False
    service.auto_recover = False
    agent_observability.clear()
    recovery_memory.clear()
    yield service
    service.pause()
    agent_observability.clear()
    recovery_memory.clear()


def _assert_no_conflicts(service: SimulationService) -> None:
    owners: dict[str, str] = {}
    for job in service.jobs.values():
        if job.assigned_tractor_id:
            assert job.id not in owners
            owners[job.assigned_tractor_id] = job.id
    for tractor in service.tractors.values():
        if tractor.assigned_job_id:
            job = service.jobs[tractor.assigned_job_id]
            assert job.assigned_tractor_id == tractor.id
            assert tractor.status != TractorStatus.BROKEN
        if tractor.status == TractorStatus.BROKEN:
            assert tractor.assigned_job_id is None


def test_failure_while_idle(sim: SimulationService) -> None:
    tractor = sim.tractors["tractor_01"]
    assert tractor.status == TractorStatus.IDLE
    result = breakdown_and_recover(sim, "tractor_01", reason="idle_fail")
    assert sim.tractors["tractor_01"].status == TractorStatus.BROKEN
    assert result.recovery.job_id is None
    assert "no active job" in result.recovery.explanation
    _assert_no_conflicts(sim)


def test_failure_while_traveling(sim: SimulationService) -> None:
    agent = FleetAgent()
    schedule_and_apply(sim, agent)
    tractor = next(t for t in sim.tractors.values() if t.assigned_job_id)
    # Force traveling state before work starts.
    job = sim.jobs[tractor.assigned_job_id]
    job.completed_work_units = 0.0
    tractor.status = TractorStatus.TRAVELING
    tractor.path = [tractor.position, sim.fields[0].position]
    tractor.path_index = 0

    preserved_jobs = {
        j.id: j.completed_work_units for j in sim.jobs.values() if j.status == JobStatus.COMPLETED
    }
    result = breakdown_and_recover(sim, tractor.id, reason="travel_fail")
    assert sim.tractors[tractor.id].status == TractorStatus.BROKEN
    assert sim.tractors[tractor.id].path == []
    assert result.recovery.percent_complete == 0.0
    for job_id, units in preserved_jobs.items():
        assert sim.jobs[job_id].status == JobStatus.COMPLETED
        assert sim.jobs[job_id].completed_work_units == units
    _assert_no_conflicts(sim)


def test_failure_at_zero_progress(sim: SimulationService) -> None:
    agent = FleetAgent()
    schedule_and_apply(sim, agent)
    tractor = next(t for t in sim.tractors.values() if t.assigned_job_id)
    job_id = tractor.assigned_job_id
    sim.jobs[job_id].completed_work_units = 0.0
    result = breakdown_and_recover(sim, tractor.id)
    assert result.recovery.percent_complete == 0.0
    assert sim.jobs[job_id].completed_work_units == 0.0
    assert abs(result.recovery.remaining_percent - 100.0) < 1e-6
    _assert_no_conflicts(sim)


def test_failure_at_fifty_percent(sim: SimulationService) -> None:
    agent = FleetAgent()
    schedule_and_apply(sim, agent)
    tractor = next(
        t
        for t in sim.tractors.values()
        if t.assigned_job_id and sim.jobs[t.assigned_job_id].job_type.value == "spraying"
    )
    job = sim.jobs[tractor.assigned_job_id]
    estimated = job.estimated_work_units
    job.completed_work_units = estimated * 0.5
    job.status = JobStatus.IN_PROGRESS
    tractor.status = TractorStatus.WORKING

    result = breakdown_and_recover(sim, tractor.id)
    assert abs(result.recovery.percent_complete - 50.0) < 1e-6
    assert abs(sim.jobs[job.id].completed_work_units - estimated * 0.5) < 1e-9
    assert "50%" in result.recovery.explanation
    if result.recovery.reassigned_to:
        assert result.recovery.reassigned_to != tractor.id
        assert "reassigned to Tractor" in result.recovery.explanation
        assert sim.jobs[job.id].assigned_tractor_id == result.recovery.reassigned_to
        assert abs(sim.jobs[job.id].completed_work_units - estimated * 0.5) < 1e-9
    _assert_no_conflicts(sim)


def test_failure_near_100_percent(sim: SimulationService) -> None:
    agent = FleetAgent()
    schedule_and_apply(sim, agent)
    tractor = next(t for t in sim.tractors.values() if t.assigned_job_id)
    job = sim.jobs[tractor.assigned_job_id]
    estimated = job.estimated_work_units
    job.completed_work_units = estimated * 0.99
    job.status = JobStatus.IN_PROGRESS
    tractor.status = TractorStatus.WORKING
    result = breakdown_and_recover(sim, tractor.id)
    assert result.recovery.percent_complete is not None
    assert result.recovery.percent_complete >= 99.0
    assert sim.jobs[job.id].completed_work_units == pytest.approx(estimated * 0.99)
    _assert_no_conflicts(sim)


def test_failure_after_completion(sim: SimulationService) -> None:
    # Complete one job then break the idle tractor.
    agent = FleetAgent()
    sim.assign_job("tractor_01", "job_01", reason="test")
    for _ in range(200):
        sim.step()
        if sim.jobs["job_01"].status == JobStatus.COMPLETED:
            break
    assert sim.jobs["job_01"].status == JobStatus.COMPLETED
    completed_units = sim.jobs["job_01"].completed_work_units
    sim.tractors["tractor_01"].status = TractorStatus.IDLE
    sim.tractors["tractor_01"].assigned_job_id = None

    result = breakdown_and_recover(sim, "tractor_01", reason="post_complete")
    assert sim.jobs["job_01"].status == JobStatus.COMPLETED
    assert sim.jobs["job_01"].completed_work_units == completed_units
    assert result.recovery.job_id is None
    _assert_no_conflicts(sim)


def test_multiple_tractor_failures(sim: SimulationService) -> None:
    sim.assign_job("tractor_01", "job_01", reason="multi")
    sim.assign_job("tractor_02", "job_04", reason="multi")
    sim.jobs["job_01"].completed_work_units = 2.0
    sim.jobs["job_04"].completed_work_units = 3.0
    progress = {"job_01": 2.0, "job_04": 3.0}

    breakdown_and_recover(sim, "tractor_01", reason="multi_fail")
    breakdown_and_recover(sim, "tractor_02", reason="multi_fail")

    for job_id, units in progress.items():
        assert sim.jobs[job_id].completed_work_units == units
    assert sim.tractors["tractor_01"].status == TractorStatus.BROKEN
    assert sim.tractors["tractor_02"].status == TractorStatus.BROKEN
    assert sim.tractors["tractor_01"].assigned_job_id is None
    assert sim.tractors["tractor_02"].assigned_job_id is None
    _assert_no_conflicts(sim)


def test_no_compatible_replacement(sim: SimulationService) -> None:
    agent = FleetAgent()
    schedule_and_apply(sim, agent)
    spraying = [t for t in sim.tractors.values() if t.implement_type.value == "spraying"]
    victim = next(t for t in spraying if t.assigned_job_id)
    job = sim.jobs[victim.assigned_job_id]
    job.completed_work_units = job.estimated_work_units * 0.4
    # Break every other spraying tractor first so no replacement remains.
    for t in spraying:
        if t.id != victim.id:
            t.status = TractorStatus.BROKEN
            t.assigned_job_id = None

    result = breakdown_and_recover(sim, victim.id)
    assert result.recovery.reassigned_to is None
    assert sim.jobs[job.id].status == JobStatus.PENDING
    assert sim.jobs[job.id].assigned_tractor_id is None
    assert abs(sim.jobs[job.id].completed_work_units - job.estimated_work_units * 0.4) < 1e-9
    assert result.recovery.blocking_reason
    assert "waiting/unassigned" in result.recovery.explanation
    _assert_no_conflicts(sim)


def test_repeated_breakdown_same_tractor(sim: SimulationService) -> None:
    first = breakdown_and_recover(sim, "tractor_02", reason="first")
    second = breakdown_and_recover(sim, "tractor_02", reason="second")
    assert sim.tractors["tractor_02"].status == TractorStatus.BROKEN
    assert first.recovery.event_type == "breakdown"
    assert second.recovery.event_type == "breakdown"
    _assert_no_conflicts(sim)


def test_repair_reenters_scheduling(sim: SimulationService) -> None:
    breakdown_and_recover(sim, "tractor_01")
    assert sim.tractors["tractor_01"].status == TractorStatus.BROKEN
    repaired = repair_and_log(sim, "tractor_01")
    assert repaired.recovery.event_type == "repair"
    assert sim.tractors["tractor_01"].status == TractorStatus.IDLE

    agent = FleetAgent()
    result = schedule_and_apply(sim, agent)
    assert any(a.tractor_id == "tractor_01" for a in result.assignments) or result.assignments == []
    # If spraying work remains, repaired tractor should be eligible.
    pending_spray = [
        j
        for j in sim.jobs.values()
        if j.status == JobStatus.PENDING and j.job_type.value == "spraying"
    ]
    if pending_spray and sim.tractors["tractor_01"].assigned_job_id is None:
        # Force a schedule opportunity
        schedule_and_apply(sim, agent)
    _assert_no_conflicts(sim)


def test_recovery_integrates_agent_traces(sim: SimulationService) -> None:
    agent = FleetAgent()
    schedule_and_apply(sim, agent)
    tractor = next(t for t in sim.tractors.values() if t.assigned_job_id)
    agent_observability.clear()
    result = breakdown_and_recover(sim, tractor.id)
    traces = agent_observability.traces()
    assert traces
    assert any(t.correlation_id == result.recovery.correlation_id for t in traces)
    assert any(t.receiver == "recovery_agent" for t in traces)


def test_api_breakdown_repair_replan() -> None:
    fleet_agent.clear()
    agent_observability.clear()
    recovery_memory.clear()
    client.post("/api/simulation/reset")
    client.post("/api/schedule")

    state = client.get("/api/state").json()
    victim = next(t for t in state["tractors"] if t["assigned_job_id"])
    broken = client.post(
        "/api/events/breakdown",
        json={"tractor_id": victim["id"], "reason": "api_break"},
    )
    assert broken.status_code == 200
    body = broken.json()
    assert body["recovery"]["explanation"]
    assert body["state"]["tractors"]

    logs = client.get("/api/recovery/logs")
    assert logs.status_code == 200
    assert logs.json()["count"] >= 1

    repaired = client.post("/api/events/repair", json={"tractor_id": victim["id"]})
    assert repaired.status_code == 200
    assert repaired.json()["state"]["tractors"]

    replan = client.post("/api/replan")
    assert replan.status_code == 200
    assert "schedule" in replan.json()
