"""Fair benchmark harness: FCFS baseline vs FarmShield Fleet Agent.

Both coordinators run on independent SimulationService copies with identical
scenarios, horizons, seeded incidents, simulator physics, and Safety/Nav gates.
Results are measured — never hardcoded.
"""

from __future__ import annotations

import csv
import json
import random
import threading
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from .baseline import FCFSBaselineAgent, submission_order_from_scenario_jobs
from .metrics import FleetProductivityLedger, agent_observability
from .models import JobStatus, Scenario
from .orchestration import schedule_and_apply
from .scheduler import FleetAgent
from .simulation import SCENARIO_PATH, SimulationService

RESULTS_DIR = Path(__file__).resolve().parent.parent / "data"
RESULTS_JSON = RESULTS_DIR / "benchmark_results.json"
RESULTS_CSV = RESULTS_DIR / "benchmark_results.csv"

DEFAULT_HORIZON = 300
DEFAULT_VARIANT_COUNT = 20

CoordinatorName = Literal["fcfs_baseline", "farmshield"]

METRIC_DEFS: dict[str, str] = {
    "jobs_completed": "Jobs that reached COMPLETED status within the horizon.",
    "on_time_completions": "Completed jobs with completion_sim_time <= deadline_minute.",
    "priority_weighted_work": "Sum of completed work_units * (6 - min(priority, 5)).",
    "travel_time": "Simulated minutes in TRAVELING status (not counted as productive work).",
    "idle_time": "Simulated minutes operational but neither traveling nor working.",
    "missed_deadlines": "Late completions plus incomplete jobs past deadline at horizon.",
    "fuel_consumed": "Fuel burned during travel and work (chaos fuel edits excluded).",
    "safety_violations": "Safety Agent hard rejections during schedule_and_apply commits.",
    "breakdown_recovery_success": (
        "Seeded/injected breakdown recoveries where the released job was reassigned "
        "or no job needed reassignment."
    ),
}

# Higher is better unless listed here.
LOWER_IS_BETTER = {
    "travel_time",
    "idle_time",
    "missed_deadlines",
    "fuel_consumed",
    "safety_violations",
}


@dataclass
class SeededIncident:
    sim_time: int
    kind: str
    params: dict[str, Any]


@dataclass
class RunMetrics:
    jobs_completed: int = 0
    on_time_completions: int = 0
    priority_weighted_work: float = 0.0
    travel_time: float = 0.0
    idle_time: float = 0.0
    missed_deadlines: int = 0
    fuel_consumed: float = 0.0
    safety_violations: int = 0
    breakdown_recovery_success: int = 0
    breakdown_recovery_attempts: int = 0

    def as_dict(self) -> dict[str, float | int]:
        return {
            "jobs_completed": self.jobs_completed,
            "on_time_completions": self.on_time_completions,
            "priority_weighted_work": self.priority_weighted_work,
            "travel_time": self.travel_time,
            "idle_time": self.idle_time,
            "missed_deadlines": self.missed_deadlines,
            "fuel_consumed": self.fuel_consumed,
            "safety_violations": self.safety_violations,
            "breakdown_recovery_success": self.breakdown_recovery_success,
            "breakdown_recovery_attempts": self.breakdown_recovery_attempts,
        }


@dataclass
class ScenarioComparison:
    scenario_id: str
    label: str
    seed: int
    horizon: int
    incidents: list[dict[str, Any]]
    baseline: RunMetrics
    farmshield: RunMetrics
    deltas: dict[str, float | None]
    pct_changes: dict[str, float | None]
    winners: dict[str, str]
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "label": self.label,
            "seed": self.seed,
            "horizon": self.horizon,
            "incidents": self.incidents,
            "baseline": self.baseline.as_dict(),
            "farmshield": self.farmshield.as_dict(),
            "deltas": self.deltas,
            "pct_changes": self.pct_changes,
            "winners": self.winners,
            "notes": self.notes,
        }


@dataclass
class BenchmarkReport:
    generated_at: str
    methodology: str
    horizon: int
    variant_count: int
    scenario_path: str
    definitions: dict[str, str]
    scenarios: list[ScenarioComparison]
    averages: dict[str, Any]
    wins: dict[str, Any]
    explanations: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "methodology": self.methodology,
            "horizon": self.horizon,
            "variant_count": self.variant_count,
            "scenario_path": self.scenario_path,
            "definitions": self.definitions,
            "scenarios": [s.as_dict() for s in self.scenarios],
            "averages": self.averages,
            "wins": self.wins,
            "explanations": self.explanations,
        }


_lock = threading.Lock()
_last_report: BenchmarkReport | None = None


METHODOLOGY = (
    "Fair head-to-head: FCFS baseline vs FarmShield Fleet Agent on independent "
    "SimulationService copies. Identical scenario JSON, tractors, fuel, jobs, "
    "deadlines, A* routes, simulator ticks, time horizon, seeded incidents, "
    "job progress rules, and Safety Agent validator. Assignments commit only after "
    "Navigation + Safety approval. Metrics are computed from each copy's private "
    "productivity ledger and counters — never invented or hardcoded."
)


def _pct_change(baseline: float, optimized: float) -> float | None:
    if baseline == 0:
        if optimized == 0:
            return 0.0
        return None
    return ((optimized - baseline) / abs(baseline)) * 100.0


def _winner(metric: str, baseline: float, optimized: float) -> str:
    if abs(baseline - optimized) < 1e-9:
        return "tie"
    lower_better = metric in LOWER_IS_BETTER
    if lower_better:
        return "farmshield" if optimized < baseline else "baseline"
    return "farmshield" if optimized > baseline else "baseline"


def build_incident_script(seed: int, scenario: Scenario) -> list[SeededIncident]:
    """Deterministic chaos script from seed — same script applied to both coordinators."""
    if seed == 0:
        return []

    rng = random.Random(seed)
    tractor_ids = [t.id for t in scenario.tractors]
    job_ids = [j.id for j in scenario.jobs if j.status.value != "blocked"]
    incidents: list[SeededIncident] = []

    # Always include a mid-horizon breakdown + later repair when seed > 0.
    t_break = 40 + (seed % 30)
    t_repair = t_break + 25 + (seed % 15)
    victim = tractor_ids[seed % len(tractor_ids)]
    incidents.append(
        SeededIncident(t_break, "breakdown", {"tractor_id": victim, "reason": f"bench_seed_{seed}"})
    )
    incidents.append(
        SeededIncident(t_repair, "repair", {"tractor_id": victim})
    )

    # Fuel pressure on an idle tractor early (may no-op if busy — applied only when idle).
    if seed % 2 == 1:
        fuel_t = 15 + (seed % 10)
        fuel_tractor = tractor_ids[(seed + 1) % len(tractor_ids)]
        level = 8.0 + (seed % 5)
        incidents.append(
            SeededIncident(
                fuel_t,
                "fuel_change",
                {"tractor_id": fuel_tractor, "fuel_level": level},
            )
        )

    # Block a non-depot, non-field cell.
    if seed % 3 != 0:
        block_t = 55 + (seed % 40)
        # Deterministic free-ish cell away from depot
        x = 5 + (seed % 10)
        y = 5 + ((seed * 3) % 10)
        incidents.append(SeededIncident(block_t, "block", {"x": x, "y": y}))
        incidents.append(
            SeededIncident(block_t + 40, "unblock", {"x": x, "y": y})
        )

    # Priority bump on a pending-capable job.
    if job_ids and seed % 4 == 0:
        job_id = job_ids[seed % len(job_ids)]
        incidents.append(
            SeededIncident(
                20 + (seed % 20),
                "priority",
                {"job_id": job_id, "priority": 1},
            )
        )

    incidents.sort(key=lambda i: (i.sim_time, i.kind))
    return incidents


def _apply_incident(sim: SimulationService, incident: SeededIncident) -> None:
    from .simulation import SimulationError

    kind = incident.kind
    p = incident.params
    try:
        if kind == "breakdown":
            # Atomic break without nested recovery — benchmark loop recovers via schedule.
            snap = sim.breakdown_tractor(p["tractor_id"], reason=p.get("reason", "benchmark"))
            counters = sim.benchmark_counters
            counters["recovery_attempts"] = int(counters.get("recovery_attempts", 0)) + 1
            job_id = snap.get("job_id")
            # Immediate replan with the bound scheduler agent (same as both sides).
            agent = sim.scheduler_agent
            if agent is not None and job_id:
                schedule = schedule_and_apply(
                    sim, agent, trigger="benchmark_recovery", record_replan=False
                )
                reassigned = any(d.job_id == job_id for d in schedule.assignments)
                if reassigned or job_id is None:
                    counters["recovery_successes"] = int(counters.get("recovery_successes", 0)) + 1
            elif job_id is None:
                counters["recovery_successes"] = int(counters.get("recovery_successes", 0)) + 1
        elif kind == "repair":
            if sim.tractors.get(p["tractor_id"]) and sim.tractors[p["tractor_id"]].status.value == "broken":
                sim.repair_tractor(p["tractor_id"])
        elif kind == "fuel_change":
            tractor = sim.tractors.get(p["tractor_id"])
            if tractor and tractor.status.value == "idle" and tractor.assigned_job_id is None:
                sim.change_tractor_fuel(p["tractor_id"], float(p["fuel_level"]))
        elif kind == "block":
            sim.block_cell(int(p["x"]), int(p["y"]), reason="benchmark_block")
        elif kind == "unblock":
            if (int(p["x"]), int(p["y"])) in sim.obstacle_set:
                sim.unblock_cell(int(p["x"]), int(p["y"]))
        elif kind == "priority":
            job = sim.jobs.get(p["job_id"])
            if job and job.status != JobStatus.COMPLETED:
                sim.change_job_priority(p["job_id"], int(p["priority"]))
    except SimulationError:
        # Incident may be invalid for current state (e.g. cell occupied); skip fairly on both sides
        # only when state diverged — for identical scripts early on both match. Late no-ops OK.
        pass


def _collect_metrics(sim: SimulationService) -> RunMetrics:
    prod = sim.analytics.compute(
        sim_time=sim.sim_time,
        jobs=list(sim.jobs.values()),
        run_id=None,
    )
    counters = sim.benchmark_counters
    return RunMetrics(
        jobs_completed=prod.total_jobs_completed,
        on_time_completions=prod.jobs_completed_before_deadline,
        priority_weighted_work=prod.priority_weighted_work_completed,
        travel_time=prod.total_travel_time,
        idle_time=prod.idle_time,
        missed_deadlines=prod.missed_deadlines,
        fuel_consumed=prod.fuel_consumed,
        safety_violations=int(counters.get("safety_violations", 0)),
        breakdown_recovery_success=int(counters.get("recovery_successes", 0)),
        breakdown_recovery_attempts=int(counters.get("recovery_attempts", 0)),
    )


def run_single(
    *,
    scenario_path: Path,
    coordinator: CoordinatorName,
    horizon: int,
    incidents: list[SeededIncident],
    agent_factory: Callable[[], FleetAgent],
) -> RunMetrics:
    """Run one coordinator on an isolated sim copy."""
    sim = SimulationService(scenario_path, play_interval_sec=0.01, isolated=True)
    sim.auto_schedule = False
    sim.auto_recover = False  # benchmark injects recovery via bound agent
    assert sim._seed_scenario is not None
    submission = submission_order_from_scenario_jobs(sim._seed_scenario.jobs)
    agent = agent_factory()
    if isinstance(agent, FCFSBaselineAgent):
        agent.set_submission_order(submission)
    sim.scheduler_agent = agent

    by_time: dict[int, list[SeededIncident]] = {}
    for inc in incidents:
        by_time.setdefault(inc.sim_time, []).append(inc)

    for _ in range(horizon):
        # Incidents at current sim_time (before schedule/step advance).
        for inc in by_time.get(sim.sim_time, []):
            _apply_incident(sim, inc)
        schedule_and_apply(sim, agent, trigger="benchmark", record_replan=False)
        sim.step()

    return _collect_metrics(sim)


def compare_scenario(
    *,
    scenario_id: str,
    label: str,
    seed: int,
    scenario_path: Path,
    horizon: int,
    base_scenario: Scenario,
) -> ScenarioComparison:
    incidents = build_incident_script(seed, base_scenario)
    incident_dicts = [
        {"sim_time": i.sim_time, "kind": i.kind, "params": i.params} for i in incidents
    ]

    baseline = run_single(
        scenario_path=scenario_path,
        coordinator="fcfs_baseline",
        horizon=horizon,
        incidents=deepcopy(incidents),
        agent_factory=lambda: FCFSBaselineAgent(),
    )
    farmshield = run_single(
        scenario_path=scenario_path,
        coordinator="farmshield",
        horizon=horizon,
        incidents=deepcopy(incidents),
        agent_factory=lambda: FleetAgent(),
    )

    deltas: dict[str, float | None] = {}
    pct_changes: dict[str, float | None] = {}
    winners: dict[str, str] = {}
    notes: list[str] = []

    b = baseline.as_dict()
    f = farmshield.as_dict()
    for key in b:
        if key == "breakdown_recovery_attempts":
            continue
        bv = float(b[key])
        fv = float(f[key])
        deltas[key] = fv - bv
        pct_changes[key] = _pct_change(bv, fv)
        winners[key] = _winner(key, bv, fv)
        if winners[key] == "baseline":
            direction = "lower" if key in LOWER_IS_BETTER else "higher"
            notes.append(
                f"FarmShield worse on {key}: baseline={bv:g} farmshield={fv:g} "
                f"(better is {direction})."
            )

    return ScenarioComparison(
        scenario_id=scenario_id,
        label=label,
        seed=seed,
        horizon=horizon,
        incidents=incident_dicts,
        baseline=baseline,
        farmshield=farmshield,
        deltas=deltas,
        pct_changes=pct_changes,
        winners=winners,
        notes=notes,
    )


def _aggregate(scenarios: list[ScenarioComparison]) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    keys = [
        "jobs_completed",
        "on_time_completions",
        "priority_weighted_work",
        "travel_time",
        "idle_time",
        "missed_deadlines",
        "fuel_consumed",
        "safety_violations",
        "breakdown_recovery_success",
    ]
    n = len(scenarios) or 1
    avg_baseline: dict[str, float] = {}
    avg_farm: dict[str, float] = {}
    avg_pct: dict[str, float | None] = {}
    wins = {"farmshield": 0, "baseline": 0, "tie": 0, "per_metric": {}}

    for key in keys:
        b_sum = sum(float(s.baseline.as_dict()[key]) for s in scenarios)
        f_sum = sum(float(s.farmshield.as_dict()[key]) for s in scenarios)
        avg_baseline[key] = b_sum / n
        avg_farm[key] = f_sum / n
        avg_pct[key] = _pct_change(avg_baseline[key], avg_farm[key])
        fw = sum(1 for s in scenarios if s.winners.get(key) == "farmshield")
        bw = sum(1 for s in scenarios if s.winners.get(key) == "baseline")
        tw = sum(1 for s in scenarios if s.winners.get(key) == "tie")
        wins["per_metric"][key] = {"farmshield": fw, "baseline": bw, "tie": tw}

    # Scenario won if FarmShield wins more metrics than baseline (ties ignored).
    for s in scenarios:
        f_w = sum(1 for k, w in s.winners.items() if w == "farmshield")
        b_w = sum(1 for k, w in s.winners.items() if w == "baseline")
        if f_w > b_w:
            wins["farmshield"] += 1
        elif b_w > f_w:
            wins["baseline"] += 1
        else:
            wins["tie"] += 1

    explanations: list[str] = []
    for key in keys:
        pct = avg_pct[key]
        if pct is None:
            explanations.append(
                f"{key}: baseline average is 0; FarmShield average={avg_farm[key]:.3f} "
                "(percentage change undefined)."
            )
            continue
        better = _winner(key, avg_baseline[key], avg_farm[key])
        if better == "baseline":
            explanations.append(
                f"FarmShield average is worse on {key}: "
                f"baseline={avg_baseline[key]:.3f} farmshield={avg_farm[key]:.3f} "
                f"({pct:+.2f}%). See methodology — not a hardcoded claim."
            )
        elif better == "farmshield":
            explanations.append(
                f"FarmShield average improves {key}: "
                f"baseline={avg_baseline[key]:.3f} farmshield={avg_farm[key]:.3f} "
                f"({pct:+.2f}%)."
            )

    averages = {
        "baseline": avg_baseline,
        "farmshield": avg_farm,
        "pct_changes": avg_pct,
        "deltas": {k: avg_farm[k] - avg_baseline[k] for k in keys},
    }
    return averages, wins, explanations


def run_benchmark(
    *,
    horizon: int = DEFAULT_HORIZON,
    variant_count: int = DEFAULT_VARIANT_COUNT,
    scenario_path: Path | None = None,
    include_main: bool = True,
) -> BenchmarkReport:
    """Execute the full fair comparison and persist JSON/CSV exports."""
    path = scenario_path or SCENARIO_PATH
    raw = json.loads(path.read_text(encoding="utf-8"))
    base_scenario = Scenario.model_validate(raw)

    # Pause global observability so benchmark traces do not pollute the live Command Center.
    agent_observability.set_recording(False)
    scenarios: list[ScenarioComparison] = []
    try:
        if include_main:
            scenarios.append(
                compare_scenario(
                    scenario_id="main_demo",
                    label="Main demo scenario (no injected incidents)",
                    seed=0,
                    scenario_path=path,
                    horizon=horizon,
                    base_scenario=base_scenario,
                )
            )
        for seed in range(1, max(0, variant_count) + 1):
            scenarios.append(
                compare_scenario(
                    scenario_id=f"variant_{seed:02d}",
                    label=f"Seeded variant {seed} (breakdowns/fuel/blocks)",
                    seed=seed,
                    scenario_path=path,
                    horizon=horizon,
                    base_scenario=base_scenario,
                )
            )
    finally:
        agent_observability.set_recording(True)

    averages, wins, explanations = _aggregate(scenarios)
    report = BenchmarkReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        methodology=METHODOLOGY,
        horizon=horizon,
        variant_count=variant_count,
        scenario_path=str(path),
        definitions=dict(METRIC_DEFS),
        scenarios=scenarios,
        averages=averages,
        wins=wins,
        explanations=explanations,
    )
    export_report(report)
    global _last_report
    with _lock:
        _last_report = report
    return report


def export_report(report: BenchmarkReport) -> tuple[Path, Path]:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_JSON.write_text(
        json.dumps(report.as_dict(), indent=2, sort_keys=False),
        encoding="utf-8",
    )

    fieldnames = [
        "scenario_id",
        "label",
        "seed",
        "horizon",
        "coordinator",
        "jobs_completed",
        "on_time_completions",
        "priority_weighted_work",
        "travel_time",
        "idle_time",
        "missed_deadlines",
        "fuel_consumed",
        "safety_violations",
        "breakdown_recovery_success",
        "breakdown_recovery_attempts",
    ]
    with RESULTS_CSV.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for s in report.scenarios:
            for name, metrics in (
                ("fcfs_baseline", s.baseline),
                ("farmshield", s.farmshield),
            ):
                row = {
                    "scenario_id": s.scenario_id,
                    "label": s.label,
                    "seed": s.seed,
                    "horizon": s.horizon,
                    "coordinator": name,
                    **metrics.as_dict(),
                }
                writer.writerow(row)

    return RESULTS_JSON, RESULTS_CSV


def get_last_report() -> BenchmarkReport | None:
    with _lock:
        if _last_report is not None:
            return _last_report
    if RESULTS_JSON.exists():
        data = json.loads(RESULTS_JSON.read_text(encoding="utf-8"))
        return _report_from_dict(data)
    return None


def _report_from_dict(data: dict[str, Any]) -> BenchmarkReport:
    scenarios: list[ScenarioComparison] = []
    for s in data.get("scenarios", []):
        scenarios.append(
            ScenarioComparison(
                scenario_id=s["scenario_id"],
                label=s["label"],
                seed=s["seed"],
                horizon=s["horizon"],
                incidents=s.get("incidents", []),
                baseline=RunMetrics(**s["baseline"]),
                farmshield=RunMetrics(**s["farmshield"]),
                deltas=s.get("deltas", {}),
                pct_changes=s.get("pct_changes", {}),
                winners=s.get("winners", {}),
                notes=s.get("notes", []),
            )
        )
    return BenchmarkReport(
        generated_at=data.get("generated_at", ""),
        methodology=data.get("methodology", METHODOLOGY),
        horizon=int(data.get("horizon", DEFAULT_HORIZON)),
        variant_count=int(data.get("variant_count", 0)),
        scenario_path=data.get("scenario_path", ""),
        definitions=data.get("definitions", METRIC_DEFS),
        scenarios=scenarios,
        averages=data.get("averages", {}),
        wins=data.get("wins", {}),
        explanations=data.get("explanations", []),
    )


def load_export_files() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "json_path": str(RESULTS_JSON),
        "csv_path": str(RESULTS_CSV),
        "json_exists": RESULTS_JSON.exists(),
        "csv_exists": RESULTS_CSV.exists(),
    }
    if RESULTS_JSON.exists():
        payload["report"] = json.loads(RESULTS_JSON.read_text(encoding="utf-8"))
    if RESULTS_CSV.exists():
        payload["csv_text"] = RESULTS_CSV.read_text(encoding="utf-8")
    return payload
