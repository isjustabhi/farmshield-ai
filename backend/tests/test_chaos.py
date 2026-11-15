"""Chaos Lab event tests — genuine simulation disruptions."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.chaos import (
    chaos_block_route,
    chaos_fuel_change,
    chaos_priority_change,
    chaos_random,
    chaos_unblock_route,
)
from app.main import app
from app.models import JobStatus, TractorStatus
from app.navigation import plan_path
from app.orchestration import breakdown_and_recover, schedule_and_apply
from app.scheduler import FleetAgent
from app.simulation import SimulationError, SimulationService

SCENARIO = Path(__file__).resolve().parent.parent / "data" / "scenario.json"
client = TestClient(app)


@pytest.fixture()
def sim() -> SimulationService:
    service = SimulationService(SCENARIO, play_interval_sec=0.01)
    service.auto_schedule = False
    service.auto_recover = False
    yield service
    service.pause()


def test_block_route_forces_astar_detour_or_release(sim: SimulationService) -> None:
    if sim.tractors["tractor_01"].assigned_job_id is None and sim.jobs["job_01"].assigned_tractor_id is None:
        sim.assign_job("tractor_01", "job_01", reason="chaos_setup")
    for _ in range(5):
        if sim.tractors["tractor_01"].status == TractorStatus.TRAVELING:
            break
        sim.step()

    t = sim.tractors["tractor_01"]
    assert t.status == TractorStatus.TRAVELING
    assert len(t.path) > 2
    mid = t.path[1]
    result = chaos_block_route(sim, mid.x, mid.y)
    assert result.event_type == "block_route"
    assert (mid.x, mid.y) in sim.obstacle_set
    t = sim.tractors["tractor_01"]
    if t.status == TractorStatus.TRAVELING and t.path:
        remaining = t.path[t.path_index :]
        assert all(not (p.x == mid.x and p.y == mid.y) for p in remaining[1:])
    assert result.explanation
    assert result.why_changed


def test_unblock_route(sim: SimulationService) -> None:
    chaos_block_route(sim, 4, 4)
    assert (4, 4) in sim.obstacle_set
    result = chaos_unblock_route(sim, 4, 4)
    assert (4, 4) not in sim.obstacle_set
    assert result.event_type == "unblock_route"


def test_priority_change_keeps_in_progress(sim: SimulationService) -> None:
    schedule_and_apply(sim, FleetAgent())
    working = None
    for tractor in sim.tractors.values():
        if not tractor.assigned_job_id:
            continue
        job = sim.jobs[tractor.assigned_job_id]
        job.completed_work_units = max(0.5, job.completed_work_units)
        job.status = JobStatus.IN_PROGRESS
        tractor.status = TractorStatus.WORKING
        tractor.path = []
        working = (tractor.id, job.id, job.completed_work_units)
        break
    assert working
    tractor_id, job_id, progress = working
    pending = next(j for j in sim.jobs.values() if j.status == JobStatus.PENDING)
    result = chaos_priority_change(sim, pending.id, 1)
    assert sim.jobs[job_id].assigned_tractor_id == tractor_id
    assert sim.jobs[job_id].status == JobStatus.IN_PROGRESS
    assert sim.jobs[job_id].completed_work_units == progress
    assert sim.jobs[pending.id].priority == 1
    assert "without preempting" in result.explanation


def test_fuel_change_idle_only_and_blocks_unsafe_assign(sim: SimulationService) -> None:
    with pytest.raises(SimulationError):
        # Not idle with assignment after schedule
        schedule_and_apply(sim, FleetAgent())
        busy = next(t for t in sim.tractors.values() if t.assigned_job_id)
        sim.change_tractor_fuel(busy.id, 1.0)

    sim.reset()
    sim.auto_schedule = False
    result = chaos_fuel_change(sim, "tractor_01", 1.0)
    assert sim.tractors["tractor_01"].fuel_level == pytest.approx(1.0)
    assert result.event_type == "fuel_change"
    # Low fuel should prevent spray jobs being assigned to this tractor
    assert sim.tractors["tractor_01"].assigned_job_id is None or sim.tractors[
        "tractor_01"
    ].fuel_level >= sim.fuel.safety_reserve


def test_random_chaos_seeded_replay(sim: SimulationService) -> None:
    sim.reset()
    sim.auto_schedule = False
    a = chaos_random(sim, seed=12345)
    state_a = (
        sorted((o.x, o.y) for o in sim.obstacles),
        {tid: (t.status.value, t.fuel_level, t.assigned_job_id) for tid, t in sim.tractors.items()},
        {jid: (j.priority, j.status.value) for jid, j in sim.jobs.items()},
        a.event_type,
    )

    sim.reset()
    sim.auto_schedule = False
    b = chaos_random(sim, seed=12345)
    state_b = (
        sorted((o.x, o.y) for o in sim.obstacles),
        {tid: (t.status.value, t.fuel_level, t.assigned_job_id) for tid, t in sim.tractors.items()},
        {jid: (j.priority, j.status.value) for jid, j in sim.jobs.items()},
        b.event_type,
    )
    assert a.seed == b.seed == 12345
    assert state_a == state_b


def test_breakdown_recovery_still_works(sim: SimulationService) -> None:
    schedule_and_apply(sim, FleetAgent())
    tractor = next(t for t in sim.tractors.values() if t.assigned_job_id)
    job_id = tractor.assigned_job_id
    assert job_id
    sim.jobs[job_id].completed_work_units = sim.jobs[job_id].estimated_work_units * 0.4
    result = breakdown_and_recover(sim, tractor.id)
    assert sim.tractors[tractor.id].status == TractorStatus.BROKEN
    assert abs(sim.jobs[job_id].completed_work_units - sim.jobs[job_id].estimated_work_units * 0.4) < 1e-9
    assert result.recovery.explanation


def test_api_chaos_endpoints() -> None:
    client.post("/api/simulation/reset")
    blocked = client.post("/api/events/block-route", json={"x": 6, "y": 6})
    assert blocked.status_code == 200
    body = blocked.json()
    assert body["event_type"] == "block_route"
    assert "before_assignments" in body and "after_assignments" in body

    unblocked = client.post("/api/events/unblock-route", json={"x": 6, "y": 6})
    assert unblocked.status_code == 200

    prio = client.post("/api/events/priority-change", json={"job_id": "job_09", "priority": 1})
    assert prio.status_code == 200

    client.post("/api/simulation/reset")
    fuel = client.post("/api/events/fuel-change", json={"tractor_id": "tractor_01", "fuel_level": 8.0})
    assert fuel.status_code == 200

    rnd = client.post("/api/chaos/random", json={"seed": 99})
    assert rnd.status_code == 200
    assert rnd.json()["seed"] == 99
