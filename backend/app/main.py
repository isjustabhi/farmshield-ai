"""FarmShield AI FastAPI entrypoint."""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .benchmark import (
    DEFAULT_HORIZON,
    DEFAULT_VARIANT_COUNT,
    get_last_report,
    load_export_files,
    run_benchmark,
)
from .metrics import (
    agent_observability,
    build_timeline_response,
    FleetProductivityLedger,
)
from .memory import recovery_memory
from .chaos import (
    chaos_block_route,
    chaos_fuel_change,
    chaos_priority_change,
    chaos_random,
    chaos_unblock_route,
)
from .models import (
    AgentMetricsResponse,
    AgentTracesResponse,
    AssignmentsResponse,
    BenchmarkRunRequest,
    BlockRouteRequest,
    BreakdownRequest,
    BreakdownResponse,
    ChaosEventResult,
    ControlResponse,
    DecisionsResponse,
    EventsResponse,
    FleetAgentMetrics,
    FuelChangeRequest,
    HealthResponse,
    MemoryDecisionsResponse,
    MemoryIncidentsResponse,
    MemoryRunsResponse,
    MemoryTractorProfile,
    MetricsTimelineResponse,
    PriorityChangeRequest,
    ProductivityMetrics,
    RandomChaosRequest,
    RecoveryLogsResponse,
    RepairRequest,
    RepairResponse,
    ReplanResponse,
    Scenario,
    ScheduleResponse,
    SimulationState,
    StepResponse,
    UnblockRouteRequest,
)
from .memory import operational_memory
from .orchestration import (
    breakdown_and_recover,
    repair_and_log,
    replan_unfinished,
    schedule_and_apply,
)
from .scheduler import fleet_agent
from .simulation import SimulationError, simulation

app = FastAPI(
    title="FarmShield AI",
    description="Autonomous tractor fleet coordinator for the ATC Run the Fleet challenge.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Return API health for frontend connectivity checks."""
    return HealthResponse(status="ok")


@app.get("/api/state", response_model=SimulationState)
def get_state() -> SimulationState:
    return simulation.get_state()


@app.get("/api/scenario", response_model=Scenario)
def get_scenario() -> Scenario:
    return simulation.get_scenario()


@app.get("/api/events", response_model=EventsResponse)
def get_events(after_id: int = Query(default=0, ge=0)) -> EventsResponse:
    state = simulation.get_state()
    return EventsResponse(events=simulation.get_events(after_id=after_id), sim_time=state.sim_time)


@app.post("/api/simulation/step", response_model=StepResponse)
def simulation_step() -> StepResponse:
    state, new_events = simulation.step()
    return StepResponse(state=state, new_events=new_events)


@app.post("/api/simulation/reset", response_model=ControlResponse)
def simulation_reset() -> ControlResponse:
    state = simulation.reset()
    return ControlResponse(state=state)


@app.post("/api/simulation/play", response_model=ControlResponse)
def simulation_play() -> ControlResponse:
    state = simulation.play()
    return ControlResponse(state=state)


@app.post("/api/simulation/pause", response_model=ControlResponse)
def simulation_pause() -> ControlResponse:
    state = simulation.pause()
    return ControlResponse(state=state)


@app.post("/api/simulation/assign", response_model=ControlResponse)
def simulation_assign(tractor_id: str, job_id: str, reason: str = "api_assign") -> ControlResponse:
    """Manual assign helper for headless demos and tests."""
    try:
        simulation.assign_job(tractor_id, job_id, reason=reason)
    except SimulationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ControlResponse(state=simulation.get_state())


@app.post("/api/schedule", response_model=ScheduleResponse)
def run_schedule() -> ScheduleResponse:
    """Run the Fleet Agent against live simulation state and apply assignments."""
    return schedule_and_apply(simulation, fleet_agent)


@app.get("/api/assignments", response_model=AssignmentsResponse)
def get_assignments() -> AssignmentsResponse:
    state = simulation.get_state()
    fleet_agent.sync_active_with_state(state)
    active_job_ids = sorted(
        j.id
        for j in state.jobs
        if j.assigned_tractor_id is not None
        or j.status.value in {"assigned", "in_progress"}
    )
    return AssignmentsResponse(
        sim_time=state.sim_time,
        active=fleet_agent.active_assignments(),
        active_job_ids=active_job_ids,
    )


@app.get("/api/decisions", response_model=DecisionsResponse)
def get_decisions() -> DecisionsResponse:
    state = simulation.get_state()
    return DecisionsResponse(decisions=fleet_agent.decisions, sim_time=state.sim_time)


@app.get("/api/agents/traces", response_model=AgentTracesResponse)
def get_agent_traces(after_index: int = Query(default=0, ge=0)) -> AgentTracesResponse:
    traces = agent_observability.traces(after_index=after_index)
    return AgentTracesResponse(traces=traces, count=len(traces))


@app.get("/api/agents/metrics", response_model=AgentMetricsResponse)
def get_agent_metrics() -> AgentMetricsResponse:
    return agent_observability.metrics()


def _resolve_productivity_ledger(run_id: str | None) -> tuple[FleetProductivityLedger, str | None, int]:
    """Return ledger + effective run_id + sim_time for productivity queries."""
    state = simulation.get_state()
    current = operational_memory.current_run_id
    if run_id is None or run_id == current:
        return simulation.analytics, current, state.sim_time

    snapshot = operational_memory.get_performance_summary(
        run_id=run_id, summary_key="productivity"
    )
    ledger = FleetProductivityLedger()
    if snapshot:
        ledger.load_dict(snapshot)
        sim_time = int(snapshot.get("timeline", [{}])[-1].get("sim_time", 0)) if snapshot.get("timeline") else 0
    else:
        sim_time = 0
    return ledger, run_id, sim_time


@app.get("/api/metrics/productivity", response_model=ProductivityMetrics)
def metrics_productivity(
    tractor_id: str | None = None,
    run_id: str | None = None,
) -> ProductivityMetrics:
    ledger, effective_run, sim_time = _resolve_productivity_ledger(run_id)
    state = simulation.get_state()
    jobs = state.jobs if (run_id is None or run_id == operational_memory.current_run_id) else []
    # For historical runs without live job state, missed open deadlines use completions only.
    return ledger.compute(
        sim_time=sim_time if run_id and run_id != operational_memory.current_run_id else state.sim_time,
        jobs=jobs,
        run_id=effective_run,
        tractor_filter=tractor_id,
    )


@app.get("/api/metrics/agents", response_model=FleetAgentMetrics)
def metrics_agents(
    agent: str | None = None,
    run_id: str | None = None,
) -> FleetAgentMetrics:
    state = simulation.get_state()
    current = operational_memory.current_run_id
    if run_id is None or run_id == current:
        traces = agent_observability.traces()
        commits = agent_observability.metrics().committed_scheduling_decisions
        replans = agent_observability.replan_latencies()
        logs = recovery_memory.logs()
        effective = current
        sim_time = state.sim_time
    else:
        traces = operational_memory.query_agent_traces(run_id=run_id, agent=agent)
        commits = len(operational_memory.query_decisions(run_id=run_id, limit=1000))
        # Historical replans are not stored as a separate series; leave empty rather than invent.
        replans = []
        logs = operational_memory.query_incidents(run_id=run_id, limit=1000)
        effective = run_id
        sim_time = state.sim_time

    return agent_observability.fleet_agent_metrics(
        sim_time=sim_time,
        run_id=effective,
        agent_filter=agent,
        traces=traces,
        committed_decisions=commits,
        replan_latencies_ms=replans,
        recovery_logs=logs,
    )


@app.get("/api/metrics/timeline", response_model=MetricsTimelineResponse)
def metrics_timeline(
    tractor_id: str | None = None,
    run_id: str | None = None,
    agent: str | None = None,
    event_type: str | None = None,
) -> MetricsTimelineResponse:
    ledger, effective_run, hist_sim = _resolve_productivity_ledger(run_id)
    state = simulation.get_state()
    current = operational_memory.current_run_id
    if run_id is None or run_id == current:
        traces = agent_observability.traces()
        decisions = fleet_agent.decisions
        logs = recovery_memory.logs()
        replans = agent_observability.replan_latencies()
        sim_time = state.sim_time
    else:
        traces = operational_memory.query_agent_traces(run_id=run_id, agent=agent)
        mem_decisions = operational_memory.query_decisions(run_id=run_id, limit=500)
        decisions = []
        for md in mem_decisions:
            for sel in md.selected:
                decisions.append(sel)
        logs = operational_memory.query_incidents(run_id=run_id, limit=500)
        replans = []
        sim_time = hist_sim

    return build_timeline_response(
        sim_time=sim_time,
        run_id=effective_run,
        tractor_filter=tractor_id,
        agent_filter=agent,
        event_type_filter=event_type,
        ledger=ledger,
        traces=traces,
        decisions=decisions,
        recovery_logs=logs,
        replan_latencies_ms=replans,
    )


@app.post("/api/events/breakdown", response_model=BreakdownResponse)
def event_breakdown(body: BreakdownRequest) -> BreakdownResponse:
    try:
        return breakdown_and_recover(simulation, body.tractor_id, reason=body.reason)
    except SimulationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/events/repair", response_model=RepairResponse)
def event_repair(body: RepairRequest) -> RepairResponse:
    try:
        return repair_and_log(simulation, body.tractor_id)
    except SimulationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/replan", response_model=ReplanResponse)
def run_replan() -> ReplanResponse:
    return replan_unfinished(simulation)


@app.post("/api/events/block-route", response_model=ChaosEventResult)
def event_block_route(body: BlockRouteRequest) -> ChaosEventResult:
    try:
        return chaos_block_route(simulation, body.x, body.y, reason=body.reason)
    except SimulationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/events/unblock-route", response_model=ChaosEventResult)
def event_unblock_route(body: UnblockRouteRequest) -> ChaosEventResult:
    try:
        return chaos_unblock_route(simulation, body.x, body.y)
    except SimulationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/events/priority-change", response_model=ChaosEventResult)
def event_priority_change(body: PriorityChangeRequest) -> ChaosEventResult:
    try:
        return chaos_priority_change(simulation, body.job_id, body.priority)
    except SimulationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/events/fuel-change", response_model=ChaosEventResult)
def event_fuel_change(body: FuelChangeRequest) -> ChaosEventResult:
    try:
        return chaos_fuel_change(simulation, body.tractor_id, body.fuel_level)
    except SimulationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/chaos/random", response_model=ChaosEventResult)
def event_chaos_random(body: RandomChaosRequest | None = None) -> ChaosEventResult:
    payload = body or RandomChaosRequest()
    try:
        return chaos_random(simulation, seed=payload.seed)
    except SimulationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/recovery/logs", response_model=RecoveryLogsResponse)
def get_recovery_logs() -> RecoveryLogsResponse:
    logs = recovery_memory.logs()
    return RecoveryLogsResponse(logs=logs, count=len(logs))


@app.get("/api/memory/incidents", response_model=MemoryIncidentsResponse)
def memory_incidents(
    tractor_id: str | None = None,
    field_id: str | None = None,
    event_type: str | None = None,
    run_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
) -> MemoryIncidentsResponse:
    incidents = operational_memory.query_incidents(
        tractor_id=tractor_id,
        field_id=field_id,
        event_type=event_type,
        run_id=run_id,
        limit=limit,
    )
    return MemoryIncidentsResponse(incidents=incidents, count=len(incidents))


@app.get("/api/memory/decisions", response_model=MemoryDecisionsResponse)
def memory_decisions(
    run_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
) -> MemoryDecisionsResponse:
    decisions = operational_memory.query_decisions(run_id=run_id, limit=limit)
    return MemoryDecisionsResponse(decisions=decisions, count=len(decisions))


@app.get("/api/memory/tractor/{tractor_id}", response_model=MemoryTractorProfile)
def memory_tractor(tractor_id: str) -> MemoryTractorProfile:
    return operational_memory.tractor_profile(tractor_id)


@app.get("/api/memory/runs", response_model=MemoryRunsResponse)
def memory_runs() -> MemoryRunsResponse:
    runs = operational_memory.list_runs()
    return MemoryRunsResponse(
        runs=runs,
        count=len(runs),
        current_run_id=operational_memory.current_run_id,
    )


@app.get("/api/benchmark")
def benchmark_get() -> dict:
    report = get_last_report()
    if report is None:
        return {
            "available": False,
            "message": "No benchmark results yet. POST /api/benchmark/run to execute.",
            "definitions": None,
            "report": None,
        }
    return {"available": True, "report": report.as_dict()}


@app.post("/api/benchmark/run")
def benchmark_run(body: BenchmarkRunRequest | None = None) -> dict:
    req = body or BenchmarkRunRequest()
    report = run_benchmark(
        horizon=req.horizon,
        variant_count=req.variant_count,
        include_main=req.include_main,
    )
    return {"ok": True, "report": report.as_dict()}


@app.get("/api/benchmark/export")
def benchmark_export() -> dict:
    payload = load_export_files()
    if not payload.get("json_exists"):
        raise HTTPException(
            status_code=404,
            detail="No benchmark export found. Run POST /api/benchmark/run first.",
        )
    return payload

