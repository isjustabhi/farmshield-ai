"""Deterministic simulation smoke and behavior tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import JobStatus, TractorStatus
from app.navigation import plan_path
from app.simulation import SimulationService

SCENARIO = Path(__file__).resolve().parent.parent / "data" / "scenario.json"
client = TestClient(app)


@pytest.fixture()
def sim() -> SimulationService:
    service = SimulationService(SCENARIO, play_interval_sec=0.01)
    service.auto_schedule = False
    service.auto_recover = False
    yield service
    service.pause()


def test_scenario_counts(sim: SimulationService) -> None:
    scenario = sim.get_scenario()
    assert scenario.grid.width == 20
    assert scenario.grid.height == 20
    assert len(scenario.tractors) == 3
    assert len(scenario.fields) == 8
    assert len(scenario.jobs) == 10
    assert {t.implement_type.value for t in scenario.tractors} == {"spraying", "mowing"}


def test_reset_is_deterministic(sim: SimulationService) -> None:
    sim.assign_job("tractor_01", "job_01", reason="test")
    for _ in range(5):
        sim.step()
    mid = sim.get_state()
    assert mid.sim_time == 5
    assert mid.tick_count == 5

    first = sim.reset()
    second = sim.reset()
    assert first.sim_time == 0
    assert first.model_dump() == second.model_dump()
    assert first.tractors[0].position == second.tractors[0].position
    assert first.jobs[0].completed_work_units == 0


def test_step_advances_sim_time_not_wall_clock(sim: SimulationService) -> None:
    before = sim.get_state()
    state, _ = sim.step()
    assert state.sim_time == before.sim_time + 1
    assert state.tick_count == before.tick_count + 1


def test_travel_work_completion_and_events(sim: SimulationService) -> None:
    sim.assign_job("tractor_01", "job_01", reason="test_assign")
    events_types: set[str] = set()
    completed = False
    for _ in range(200):
        _, new_events = sim.step()
        events_types.update(e.event_type for e in new_events)
        job = next(j for j in sim.get_state().jobs if j.id == "job_01")
        if job.status == JobStatus.COMPLETED:
            completed = True
            break

    assert completed
    assert "travel_start" in events_types
    assert "arrival" in events_types
    assert "job_start" in events_types
    assert "completion" in events_types
    assert "progress_milestone" in events_types

    # Sequential dependent job becomes pending after completion.
    job_02 = next(j for j in sim.get_state().jobs if j.id == "job_02")
    assert job_02.status == JobStatus.PENDING


def test_fractional_progress_preserved_on_failure(sim: SimulationService) -> None:
    sim.assign_job("tractor_01", "job_01", reason="test")
    # Drive tractor to field and start work.
    for _ in range(50):
        sim.step()
        tractor = sim.tractors["tractor_01"]
        job = sim.jobs["job_01"]
        if tractor.status == TractorStatus.WORKING and job.completed_work_units > 0:
            break

    job = sim.jobs["job_01"]
    assert job.status == JobStatus.IN_PROGRESS
    progress = job.completed_work_units
    assert progress > 0

    # Force fuel failure mid-job.
    tractor = sim.tractors["tractor_01"]
    tractor.fuel_level = 0.0
    sim.step()

    job = sim.jobs["job_01"]
    tractor = sim.tractors["tractor_01"]
    assert tractor.status == TractorStatus.BROKEN
    assert job.assigned_tractor_id is None
    assert job.status == JobStatus.PENDING
    assert job.completed_work_units == progress

    event_types = {e.event_type for e in sim.get_events()}
    assert "failure" in event_types
    assert "reassignment" in event_types


def test_incompatible_assignment_rejected(sim: SimulationService) -> None:
    with pytest.raises(Exception):
        sim.assign_job("tractor_01", "job_04", reason="bad")  # spraying tractor, mowing job


def test_astar_path_length(sim: SimulationService) -> None:
    path = plan_path(
        sim.tractors["tractor_01"].position,
        next(f.position for f in sim.fields if f.id == "field_01"),
        20,
        20,
        set(),
    )
    assert path[0].x == 0 and path[0].y == 0
    assert path[-1].x == 2 and path[-1].y == 2
    assert len(path) - 1 == 4


def test_api_state_scenario_step_reset() -> None:
    reset = client.post("/api/simulation/reset")
    assert reset.status_code == 200
    assert reset.json()["state"]["sim_time"] == 0

    scenario = client.get("/api/scenario")
    assert scenario.status_code == 200
    body = scenario.json()
    assert body["grid"]["width"] == 20
    assert len(body["tractors"]) == 3
    assert len(body["fields"]) == 8
    assert len(body["jobs"]) == 10

    state = client.get("/api/state")
    assert state.status_code == 200
    assert state.json()["sim_time"] == 0

    assign = client.post(
        "/api/simulation/assign",
        params={"tractor_id": "tractor_01", "job_id": "job_01", "reason": "api_test"},
    )
    assert assign.status_code == 200

    stepped = client.post("/api/simulation/step")
    assert stepped.status_code == 200
    assert stepped.json()["state"]["sim_time"] == 1

    events = client.get("/api/events")
    assert events.status_code == 200
    assert len(events.json()["events"]) >= 1

    paused = client.post("/api/simulation/pause")
    assert paused.status_code == 200
    assert paused.json()["state"]["playing"] is False


def test_api_play_pause() -> None:
    client.post("/api/simulation/reset")
    play = client.post("/api/simulation/play")
    assert play.status_code == 200
    assert play.json()["state"]["playing"] is True
    pause = client.post("/api/simulation/pause")
    assert pause.status_code == 200
    assert pause.json()["state"]["playing"] is False
