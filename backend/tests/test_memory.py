"""SQLite operational memory: persistence, restart, and run isolation."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.memory import OperationalMemory
from app.models import JobStatus, TractorStatus
from app.orchestration import breakdown_and_recover, schedule_and_apply
from app.scheduler import FleetAgent
from app.simulation import SimulationService

SCENARIO = Path(__file__).resolve().parent.parent / "data" / "scenario.json"
client = TestClient(app)


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
    mem = OperationalMemory(tmp_path / "farmshield_test.db")
    monkeypatch.setattr("app.memory.operational_memory", mem)
    monkeypatch.setattr("app.memory.recovery_memory", mem)
    sim = SimulationService(SCENARIO, play_interval_sec=0.01)
    sim.auto_schedule = False
    sim.auto_recover = False
    yield sim, mem
    sim.pause()
    mem.close()


def test_persist_incidents_and_decisions(isolated) -> None:
    sim, mem = isolated
    agent = FleetAgent()
    schedule_and_apply(sim, agent)
    tractor = next(t for t in sim.tractors.values() if t.assigned_job_id)
    job = sim.jobs[tractor.assigned_job_id]
    job.completed_work_units = job.estimated_work_units * 0.5
    result = breakdown_and_recover(sim, tractor.id)

    incidents = mem.query_incidents(tractor_id=tractor.id, event_type="breakdown")
    assert incidents
    assert incidents[0].explanation == result.recovery.explanation
    assert incidents[0].preserved_work_units == pytest.approx(job.estimated_work_units * 0.5)

    decisions = mem.query_decisions()
    assert decisions
    assert decisions[0].selected or decisions[0].rejections is not None

    runs = mem.list_runs()
    assert len(runs) >= 1
    assert mem.current_run_id in {r.run_id for r in runs}


def test_restart_preserves_history(tmp_path, monkeypatch) -> None:
    db = tmp_path / "restart.db"
    mem1 = OperationalMemory(db)
    monkeypatch.setattr("app.memory.operational_memory", mem1)
    monkeypatch.setattr("app.memory.recovery_memory", mem1)
    sim = SimulationService(SCENARIO, play_interval_sec=0.01)
    sim.auto_schedule = False
    sim.auto_recover = False
    run_a = mem1.current_run_id
    breakdown_and_recover(sim, "tractor_01", reason="restart_case")
    assert mem1.query_incidents(tractor_id="tractor_01")
    sim.pause()
    mem1.close()

    mem2 = OperationalMemory(db)
    monkeypatch.setattr("app.memory.operational_memory", mem2)
    monkeypatch.setattr("app.memory.recovery_memory", mem2)
    assert mem2.query_incidents(tractor_id="tractor_01")
    assert any(i.run_id == run_a for i in mem2.query_incidents(tractor_id="tractor_01"))
    # Live state is not loaded from DB — new service starts fresh scenario.
    sim2 = SimulationService(SCENARIO, play_interval_sec=0.01)
    sim2.auto_schedule = False
    assert sim2.tractors["tractor_01"].status == TractorStatus.IDLE
    assert sim2.jobs["job_01"].status == JobStatus.PENDING
    assert sim2.jobs["job_01"].completed_work_units == 0.0
    sim2.pause()
    mem2.close()


def test_run_isolation_on_reset(isolated) -> None:
    sim, mem = isolated
    run1 = mem.current_run_id
    breakdown_and_recover(sim, "tractor_02", reason="run1")
    assert mem.query_incidents(run_id=run1)

    sim.reset()
    run2 = mem.current_run_id
    assert run2 != run1
    # History for run1 remains; current live log is empty.
    assert mem.logs() == []
    assert mem.query_incidents(run_id=run1)
    assert mem.query_incidents(run_id=run2) == []

    breakdown_and_recover(sim, "tractor_03", reason="run2")
    only_run2 = mem.query_incidents(run_id=run2, tractor_id="tractor_03")
    assert only_run2
    assert all(i.run_id == run2 for i in only_run2)
    # Live authoritative state is idle/broken for current run only.
    assert sim.tractors["tractor_03"].status == TractorStatus.BROKEN
    # Prior-run tractor is restored by scenario reset, not history.
    assert sim.tractors["tractor_02"].status == TractorStatus.IDLE


def test_no_duplicate_events_on_reset_replay(isolated) -> None:
    sim, mem = isolated
    sim.emit_event(event_type="probe", message="one", tractor_id="tractor_01")
    run1 = mem.current_run_id
    with mem._lock:
        count1 = mem._conn.execute(
            "SELECT COUNT(*) AS c FROM tractor_events WHERE run_id = ?",
            (run1,),
        ).fetchone()["c"]

    # Re-emitting same logical id in same run is ignored via UNIQUE(run_id, event_id)
    # Reset creates new run; event ids restart without colliding across runs.
    sim.reset()
    sim.emit_event(event_type="probe", message="two", tractor_id="tractor_01")
    run2 = mem.current_run_id
    with mem._lock:
        count_run1 = mem._conn.execute(
            "SELECT COUNT(*) AS c FROM tractor_events WHERE run_id = ?",
            (run1,),
        ).fetchone()["c"]
        count_run2 = mem._conn.execute(
            "SELECT COUNT(*) AS c FROM tractor_events WHERE run_id = ?",
            (run2,),
        ).fetchone()["c"]
    assert count_run1 == count1
    assert count_run2 >= 1
    assert run1 != run2


def test_recurring_failure_warning_from_db(isolated) -> None:
    sim, mem = isolated
    breakdown_and_recover(sim, "tractor_01")
    sim.reset()
    repair_needed = sim.tractors["tractor_01"]
    assert repair_needed.status == TractorStatus.IDLE
    breakdown_and_recover(sim, "tractor_01")

    profile = mem.tractor_profile("tractor_01")
    assert profile.breakdown_count >= 2
    assert profile.warnings
    assert "Tractor tractor_01 experienced" in profile.warnings[0]
    assert "Operator inspection recommended" in profile.warnings[0]
    assert profile.similar_historical_outcomes
    assert "No unvalidated failure prediction" in profile.notes


def test_search_incidents_by_filters(isolated) -> None:
    sim, mem = isolated
    agent = FleetAgent()
    schedule_and_apply(sim, agent)
    tractor = next(t for t in sim.tractors.values() if t.assigned_job_id)
    job_id = tractor.assigned_job_id
    field_id = sim.jobs[job_id].field_id
    breakdown_and_recover(sim, tractor.id)

    by_field = mem.query_incidents(field_id=field_id, event_type="breakdown")
    assert by_field
    by_tractor = mem.query_incidents(tractor_id=tractor.id)
    assert by_tractor
    by_run = mem.query_incidents(run_id=mem.current_run_id)
    assert by_run


def test_api_memory_endpoints() -> None:
    client.post("/api/simulation/reset")
    client.post("/api/schedule")
    state = client.get("/api/state").json()
    victim = next((t for t in state["tractors"] if t["assigned_job_id"]), None)
    if victim:
        client.post("/api/events/breakdown", json={"tractor_id": victim["id"]})

    runs = client.get("/api/memory/runs")
    assert runs.status_code == 200
    assert runs.json()["count"] >= 1
    assert runs.json()["current_run_id"]

    incidents = client.get("/api/memory/incidents")
    assert incidents.status_code == 200

    decisions = client.get("/api/memory/decisions")
    assert decisions.status_code == 200

    profile = client.get("/api/memory/tractor/tractor_01")
    assert profile.status_code == 200
    body = profile.json()
    assert body["tractor_id"] == "tractor_01"
    assert "notes" in body
