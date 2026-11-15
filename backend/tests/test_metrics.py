"""Fleet Intelligence productivity and agent metric tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.metrics import (
    FleetProductivityLedger,
    agent_observability,
)
from app.models import AgentTrace, JobStatus
from app.simulation import SimulationService

SCENARIO = Path(__file__).resolve().parent.parent / "data" / "scenario.json"
client = TestClient(app)


@pytest.fixture()
def sim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimulationService:
    from app import memory as memory_service
    from app.memory import OperationalMemory

    mem = OperationalMemory(db_path=tmp_path / "metrics.db")
    monkeypatch.setattr(memory_service, "operational_memory", mem)
    monkeypatch.setattr(memory_service, "recovery_memory", mem)

    service = SimulationService(SCENARIO, play_interval_sec=0.01, isolated=True)
    service.auto_schedule = False
    service.auto_recover = False
    service.analytics.clear()
    agent_observability.clear()
    yield service
    service.pause()
    service.analytics.clear()
    agent_observability.clear()
    mem.close()


def test_empty_productivity_is_zero_safe() -> None:
    ledger = FleetProductivityLedger()
    metrics = ledger.compute(sim_time=0, jobs=[], run_id=None, tractor_filter=None)
    assert metrics.total_jobs_completed == 0
    assert metrics.fleet_utilization_pct == 0.0
    assert metrics.available_operational_time == 0.0
    assert metrics.productive_work_time == 0.0
    assert metrics.fuel_consumed == 0.0
    assert metrics.missed_deadlines == 0


def test_utilization_excludes_broken_and_separates_travel() -> None:
    ledger = FleetProductivityLedger()
    ledger.record_tick(1, {"t1": "working", "t2": "traveling"})
    ledger.record_tick(2, {"t1": "idle", "t2": "broken"})
    ledger.record_tick(3, {"t1": "working", "t2": "broken"})
    ledger.add_fuel("t1", 1.5)
    ledger.add_fuel("t2", 0.5)

    metrics = ledger.compute(sim_time=3, jobs=[])
    # t1: work=2, idle=1; t2: travel=1, broken=2
    assert metrics.productive_work_time == 2.0
    assert metrics.total_travel_time == 1.0
    assert metrics.idle_time == 1.0
    assert metrics.broken_unavailable_time == 2.0
    assert metrics.available_operational_time == 4.0  # 2+1+1
    assert metrics.fleet_utilization_pct == pytest.approx(50.0)
    assert metrics.fuel_consumed == pytest.approx(2.0)


def test_completion_deadline_and_priority_weight() -> None:
    ledger = FleetProductivityLedger()
    ledger.record_completion(
        job_id="job_a",
        tractor_id="t1",
        sim_time=10,
        deadline_minute=20,
        priority=1,
        work_units=4.0,
    )
    ledger.record_completion(
        job_id="job_b",
        tractor_id="t1",
        sim_time=30,
        deadline_minute=25,
        priority=3,
        work_units=2.0,
    )
    # Incomplete job past deadline
    class FakeJob:
        id = "job_c"
        deadline_minute = 5
        status = JobStatus.PENDING
        assigned_tractor_id = None

    metrics = ledger.compute(sim_time=40, jobs=[FakeJob()])
    assert metrics.total_jobs_completed == 2
    assert metrics.jobs_completed_before_deadline == 1
    assert metrics.missed_deadlines == 2  # late completion + open past deadline
    # weight = 6-min(p,5): job_a 4*5=20, job_b 2*3=6
    assert metrics.priority_weighted_work_completed == pytest.approx(26.0)


def test_simulation_records_real_time_and_fuel(sim: SimulationService) -> None:
    sim.reset()
    sim.analytics.clear()

    sim.assign_job("tractor_01", "job_01", reason="test")
    for _ in range(40):
        sim.step()
        state = sim.get_state()
        if any(j.status == JobStatus.COMPLETED and j.id == "job_01" for j in state.jobs):
            break

    metrics = sim.analytics.compute(
        sim_time=sim.sim_time,
        jobs=list(sim.jobs.values()),
    )
    assert metrics.productive_work_time + metrics.total_travel_time + metrics.idle_time > 0
    assert metrics.fuel_consumed > 0
    # Travel counted separately from work
    assert metrics.definitions["total_travel_time"]
    if metrics.total_jobs_completed:
        assert metrics.total_jobs_completed >= 1


def test_agent_metrics_empty_and_from_traces() -> None:
    agent_observability.clear()
    empty = agent_observability.fleet_agent_metrics(sim_time=0, recovery_logs=[])
    assert empty.total_calls == 0
    assert empty.median_latency_ms == 0.0
    assert empty.p95_latency_ms == 0.0
    assert empty.calls_per_completed_scheduling_decision == 0.0

    for i, status in enumerate(["ok", "ok", "error", "rejected"]):
        agent_observability.record_trace(
            AgentTrace(
                correlation_id="c1",
                decision_id="1",
                sender="fleet_agent",
                receiver="safety_agent" if status == "rejected" else "navigation_agent",
                request_type="RouteRequest",
                response_type="RouteResponse",
                start_wall_time=1.0 + i,
                end_wall_time=1.0 + i + 0.01,
                duration_ms=float((i + 1) * 2),
                status=status,
                simulation_timestamp=i,
            )
        )
    agent_observability.record_commit(1)
    agent_observability.record_replan_latency(12.5)

    m = agent_observability.fleet_agent_metrics(
        sim_time=3,
        recovery_logs=[
            {
                "event_type": "recovery_plan",
                "reassigned_to": "tractor_02",
                "feasible": True,
            },
            {"event_type": "breakdown", "reassigned_to": None, "feasible": False},
        ],
    )
    assert m.total_calls == 4
    assert m.failed_calls == 1
    assert m.successful_calls == 3
    assert m.safety_validation_rejections == 1
    assert m.calls_per_completed_scheduling_decision == pytest.approx(4.0)
    assert m.total_replanning_latency_ms == pytest.approx(12.5)
    assert m.recovery_attempts == 2
    assert m.successful_recoveries == 1
    assert len(m.per_agent) >= 1


def test_metrics_api_endpoints_empty() -> None:
    # Use live app simulation; ensure graceful empty/zero responses.
    r1 = client.get("/api/metrics/productivity")
    assert r1.status_code == 200
    body = r1.json()
    assert "fleet_utilization_pct" in body
    assert body["fleet_utilization_pct"] >= 0

    r2 = client.get("/api/metrics/agents")
    assert r2.status_code == 200
    assert "total_calls" in r2.json()

    r3 = client.get("/api/metrics/timeline")
    assert r3.status_code == 200
    tl = r3.json()
    assert "productivity_series" in tl
    assert "decision_traces" in tl
    assert "recovery_stats" in tl


def test_metrics_api_with_filters_after_steps() -> None:
    client.post("/api/simulation/reset")
    client.post("/api/schedule")
    for _ in range(15):
        client.post("/api/simulation/step")

    prod = client.get("/api/metrics/productivity").json()
    assert prod["sim_time"] >= 15
    assert prod["available_operational_time"] + prod["broken_unavailable_time"] > 0

    agents = client.get("/api/metrics/agents").json()
    assert agents["total_calls"] >= 0

    timeline = client.get(
        "/api/metrics/timeline",
        params={"agent": "fleet_agent"},
    ).json()
    assert timeline["agent_filter"] == "fleet_agent"
    assert isinstance(timeline["productivity_series"], list)
