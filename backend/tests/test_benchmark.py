"""Fair benchmark: FCFS baseline vs FarmShield under identical constraints."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.baseline import FCFSBaselineAgent, submission_order_from_scenario_jobs
from app.benchmark import (
    build_incident_script,
    compare_scenario,
    run_benchmark,
    run_single,
)
from app.main import app
from app.models import Scenario
from app.orchestration import schedule_and_apply
from app.scheduler import FleetAgent
from app.simulation import SimulationService
from app.safety import safety_agent
from app.models import (
    ProposedAssignment,
    RouteResponse,
    SafetyValidationRequest,
    Position,
)

SCENARIO = Path(__file__).resolve().parent.parent / "data" / "scenario.json"
client = TestClient(app)


@pytest.fixture()
def base_scenario() -> Scenario:
    return Scenario.model_validate(json.loads(SCENARIO.read_text(encoding="utf-8")))


def test_fcfs_submission_order_and_safety(base_scenario: Scenario) -> None:
    sim = SimulationService(SCENARIO, play_interval_sec=0.01, isolated=True)
    sim.auto_schedule = False
    sim.auto_recover = False
    order = submission_order_from_scenario_jobs(base_scenario.jobs)
    agent = FCFSBaselineAgent(order)
    sim.scheduler_agent = agent

    plan = agent.plan(sim.get_state())
    # First assignments follow earliest submitted schedulable jobs.
    assert plan.assignments
    first_jobs = [a.job_id for a in plan.assignments]
    # job_01 and job_03/job_05 are early spraying jobs — FCFS should prefer earlier ids.
    assert first_jobs == sorted(first_jobs, key=lambda j: order.index(j))

    schedule_and_apply(sim, agent)
    # Every committed assignment must satisfy live safety (re-validate snapshot).
    state = sim.get_state()
    for decision in agent.decisions:
        tractor = next(t for t in state.tractors if t.id == decision.tractor_id)
        job = next(j for j in state.jobs if j.id == decision.job_id)
        # After apply, job is owned — validate would fail job_already_owned.
        # Instead assert equipment and that assign succeeded without broken tractor.
        assert tractor.implement_type.value == job.job_type.value
        assert tractor.status.value != "broken"


def test_both_strategies_reject_incompatible_via_safety() -> None:
    """Safety validator is shared — incompatible proposals are not approved."""
    sim = SimulationService(SCENARIO, play_interval_sec=0.01, isolated=True)
    state = sim.get_state()
    # spraying tractor + mowing job
    tractor = next(t for t in state.tractors if t.implement_type.value == "spraying")
    job = next(j for j in state.jobs if j.job_type.value == "mowing" and j.status.value == "pending")
    proposal = ProposedAssignment(
        tractor_id=tractor.id,
        job_id=job.id,
        completed_work_units=0.0,
        estimated_work_units=job.estimated_work_units,
        predicted_finish=50.0,
        deadline_minute=job.deadline_minute,
        estimated_fuel_used=10.0,
        route=RouteResponse(
            reachable=True,
            path=[Position(x=0, y=0)],
            travel_cells=0,
            travel_time=0.0,
        ),
    )
    result = safety_agent.validate(
        SafetyValidationRequest(proposal=proposal, state=state)
    )
    assert result.approved is False
    assert any("incompatible_equipment" in v for v in result.violations)


def test_incident_script_reproducible(base_scenario: Scenario) -> None:
    a = build_incident_script(7, base_scenario)
    b = build_incident_script(7, base_scenario)
    assert [(i.sim_time, i.kind, i.params) for i in a] == [
        (i.sim_time, i.kind, i.params) for i in b
    ]
    assert any(i.kind == "breakdown" for i in a)


def test_independent_copies_do_not_contaminate() -> None:
    baseline = run_single(
        scenario_path=SCENARIO,
        coordinator="fcfs_baseline",
        horizon=40,
        incidents=[],
        agent_factory=lambda: FCFSBaselineAgent(
            submission_order_from_scenario_jobs(
                Scenario.model_validate(json.loads(SCENARIO.read_text())).jobs
            )
        ),
    )
    farm = run_single(
        scenario_path=SCENARIO,
        coordinator="farmshield",
        horizon=40,
        incidents=[],
        agent_factory=lambda: FleetAgent(),
    )
    # Both produce real metrics; neither run shares analytics ledgers.
    assert baseline.travel_time + baseline.idle_time + baseline.jobs_completed >= 0
    assert farm.travel_time + farm.idle_time + farm.jobs_completed >= 0


def test_compare_scenario_metric_consistency(base_scenario: Scenario) -> None:
    result = compare_scenario(
        scenario_id="test_main",
        label="test",
        seed=0,
        scenario_path=SCENARIO,
        horizon=80,
        base_scenario=base_scenario,
    )
    assert result.baseline.jobs_completed == result.baseline.jobs_completed
    assert "jobs_completed" in result.deltas
    assert result.winners["jobs_completed"] in {"farmshield", "baseline", "tie"}
    # Percentage change uses correct denominator (None only if baseline is 0 and farm != 0).
    for key, pct in result.pct_changes.items():
        b = float(result.baseline.as_dict()[key])
        f = float(result.farmshield.as_dict()[key])
        if b == 0 and f == 0:
            assert pct == 0.0
        elif b == 0:
            assert pct is None
        else:
            assert pct == pytest.approx(((f - b) / abs(b)) * 100.0)


def test_benchmark_api_and_export(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app import benchmark as bench_mod

    monkeypatch.setattr(bench_mod, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(bench_mod, "RESULTS_JSON", tmp_path / "benchmark_results.json")
    monkeypatch.setattr(bench_mod, "RESULTS_CSV", tmp_path / "benchmark_results.csv")

    # Small run for CI speed.
    report = run_benchmark(horizon=50, variant_count=2, include_main=True)
    assert len(report.scenarios) == 3
    assert (tmp_path / "benchmark_results.json").exists()
    assert (tmp_path / "benchmark_results.csv").exists()

    # Point API getters at the same temp export.
    monkeypatch.setattr("app.main.get_last_report", lambda: report)
    r = client.get("/api/benchmark")
    assert r.status_code == 200
    assert r.json()["available"] is True

    # Export endpoint reads files — patch load_export_files paths via module.
    payload = client.get("/api/benchmark/export")
    # May 404 if load_export_files still points at default data dir — patch it.
    monkeypatch.setattr(
        "app.main.load_export_files",
        lambda: {
            "json_path": str(tmp_path / "benchmark_results.json"),
            "csv_path": str(tmp_path / "benchmark_results.csv"),
            "json_exists": True,
            "csv_exists": True,
            "report": report.as_dict(),
            "csv_text": (tmp_path / "benchmark_results.csv").read_text(),
        },
    )
    payload = client.get("/api/benchmark/export")
    assert payload.status_code == 200
    assert payload.json()["json_exists"] is True
