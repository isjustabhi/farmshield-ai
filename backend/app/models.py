"""Shared Pydantic models and typed schemas for FarmShield AI."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Liveness / readiness payload for the API."""

    status: str = Field(..., description="Service health status")
    service: str = Field(default="FarmShield AI", description="Service name")
    version: str = Field(default="0.1.0", description="API version")


class TractorStatus(str, Enum):
    IDLE = "idle"
    TRAVELING = "traveling"
    WORKING = "working"
    REFUELING = "refueling"
    BROKEN = "broken"


class JobStatus(str, Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"


class JobType(str, Enum):
    SPRAYING = "spraying"
    MOWING = "mowing"


class ImplementType(str, Enum):
    SPRAYING = "spraying"
    MOWING = "mowing"


class Position(BaseModel):
    x: int = Field(..., ge=0)
    y: int = Field(..., ge=0)


class GridConfig(BaseModel):
    width: int = Field(..., gt=0)
    height: int = Field(..., gt=0)


class FieldModel(BaseModel):
    id: str
    name: str
    position: Position
    job_ids: list[str] = Field(default_factory=list)


class Tractor(BaseModel):
    id: str
    name: str
    implement_type: ImplementType
    fuel_level: float = Field(..., ge=0)
    fuel_capacity: float = Field(..., gt=0)
    working_speed: float = Field(..., gt=0, description="Work units per simulated minute")
    travel_speed: float = Field(..., gt=0, description="Grid cells per simulated minute")
    position: Position
    status: TractorStatus = TractorStatus.IDLE
    assigned_job_id: str | None = None
    path: list[Position] = Field(default_factory=list)
    path_index: int = 0
    travel_cell_progress: float = 0.0
    """Fractional progress (0..1) toward the next path cell."""


class Job(BaseModel):
    id: str
    field_id: str
    job_type: JobType
    priority: int = Field(..., ge=1)
    deadline_minute: int = Field(..., ge=0, description="Simulated minute deadline")
    estimated_work_units: float = Field(..., gt=0)
    completed_work_units: float = Field(default=0.0, ge=0)
    status: JobStatus = JobStatus.PENDING
    assigned_tractor_id: str | None = None
    sequence: int = Field(default=1, ge=1, description="Order within a field (1 = first)")
    depends_on_job_id: str | None = None


class FuelModel(BaseModel):
    travel_per_cell: float = Field(default=0.4, gt=0)
    work_per_unit: float = Field(default=0.35, gt=0)
    safety_reserve: float = Field(default=5.0, ge=0)


class Scenario(BaseModel):
    name: str
    seed: int = 42
    grid: GridConfig
    fields: list[FieldModel]
    tractors: list[Tractor]
    jobs: list[Job]
    obstacles: list[Position] = Field(default_factory=list)
    fuel: FuelModel = Field(default_factory=FuelModel)
    depot: Position = Field(default_factory=lambda: Position(x=0, y=0))


class SimEvent(BaseModel):
    id: int
    sim_time: int
    event_type: str
    message: str
    tractor_id: str | None = None
    job_id: str | None = None
    field_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class SimulationState(BaseModel):
    scenario_name: str
    seed: int
    sim_time: int
    playing: bool
    grid: GridConfig
    fields: list[FieldModel]
    tractors: list[Tractor]
    jobs: list[Job]
    obstacles: list[Position]
    fuel: FuelModel
    depot: Position
    event_count: int
    tick_count: int


class StepResponse(BaseModel):
    state: SimulationState
    new_events: list[SimEvent]


class ControlResponse(BaseModel):
    ok: bool = True
    state: SimulationState


class EventsResponse(BaseModel):
    events: list[SimEvent]
    sim_time: int


class AssignRequest(BaseModel):
    """Internal/test helper schema for deterministic assignment."""

    tractor_id: str
    job_id: str
    reason: str = "manual_assign"


class ScoreComponents(BaseModel):
    priority_reward: float
    deadline_urgency: float
    lateness_penalty: float
    travel_penalty: float
    unproductive_penalty: float
    total: float


class AssignmentDecision(BaseModel):
    tractor_id: str
    job_id: str
    estimated_travel_time: float
    estimated_work_time: float
    estimated_fuel_used: float
    predicted_finish: float
    deadline_margin: float
    score_components: ScoreComponents
    selection_reason: str
    sim_time: int
    decision_id: int
    applied: bool = True


class InfeasibleJobReport(BaseModel):
    job_id: str
    reasons: list[str]


class ScheduleResponse(BaseModel):
    sim_time: int
    assignments: list[AssignmentDecision]
    infeasible_jobs: list[InfeasibleJobReport]
    considered_pairs: int
    matching_score: float


class AssignmentsResponse(BaseModel):
    sim_time: int
    active: list[AssignmentDecision]
    """Active jobs that have a recorded fleet-agent decision."""
    active_job_ids: list[str]
    """All currently assigned / in-progress job IDs from simulation state."""


class DecisionsResponse(BaseModel):
    decisions: list[AssignmentDecision]
    sim_time: int


class AgentTrace(BaseModel):
    """Structured in-process agent interaction record (not a fake network hop)."""

    correlation_id: str
    decision_id: str | None
    sender: str
    receiver: str
    request_type: str
    response_type: str
    start_wall_time: float
    end_wall_time: float
    duration_ms: float
    status: str
    simulation_timestamp: int
    transport: str = "in_process"
    detail: dict[str, Any] = Field(default_factory=dict)


class RouteRequest(BaseModel):
    tractor_id: str
    job_id: str
    start: Position
    goal: Position
    grid: GridConfig
    obstacles: list[Position] = Field(default_factory=list)
    travel_speed: float


class RouteResponse(BaseModel):
    reachable: bool
    path: list[Position] = Field(default_factory=list)
    travel_cells: int = 0
    travel_time: float = 0.0
    reason: str | None = None


class ProposedAssignment(BaseModel):
    tractor_id: str
    job_id: str
    completed_work_units: float
    estimated_work_units: float
    predicted_finish: float
    deadline_minute: int
    estimated_fuel_used: float
    route: RouteResponse
    expected_completed_work_units: float | None = None
    """If set, safety requires job progress to be preserved at this value."""


class SafetyValidationRequest(BaseModel):
    proposal: ProposedAssignment
    state: SimulationState
    reserved_tractor_ids: list[str] = Field(default_factory=list)
    reserved_job_ids: list[str] = Field(default_factory=list)


class SafetyValidationResponse(BaseModel):
    approved: bool
    violations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    unavoidable_lateness: bool = False
    deadline_margin: float = 0.0


class IncidentRequest(BaseModel):
    tractor_id: str
    job_id: str | None
    reason: str
    completed_work_units: float
    simulation_timestamp: int
    prior_status: str | None = None
    percent_complete: float | None = None


class RecoveryProposal(BaseModel):
    accept: bool
    released_job_id: str | None
    failed_tractor_id: str
    preserved_work_units: float
    recommend_reschedule: bool
    notes: str
    percent_complete: float | None = None
    remaining_percent: float | None = None


class BreakdownRequest(BaseModel):
    tractor_id: str
    reason: str = "manual_breakdown"


class RepairRequest(BaseModel):
    tractor_id: str


class BlockRouteRequest(BaseModel):
    x: int = Field(..., ge=0)
    y: int = Field(..., ge=0)
    reason: str = "chaos_block"


class UnblockRouteRequest(BaseModel):
    x: int = Field(..., ge=0)
    y: int = Field(..., ge=0)


class PriorityChangeRequest(BaseModel):
    job_id: str
    priority: int = Field(..., ge=1, le=10)


class FuelChangeRequest(BaseModel):
    tractor_id: str
    fuel_level: float = Field(..., ge=0)


class RandomChaosRequest(BaseModel):
    seed: int | None = None


class AssignmentSnapshot(BaseModel):
    job_id: str
    tractor_id: str | None
    status: str
    completed_work_units: float
    percent_complete: float


class ChaosEventResult(BaseModel):
    ok: bool
    event_type: str
    explanation: str
    correlation_id: str
    seed: int | None = None
    sim_time: int
    affected_jobs: list[str] = Field(default_factory=list)
    preserved_work: dict[str, float] = Field(default_factory=dict)
    unreachable_jobs: list[str] = Field(default_factory=list)
    before_assignments: list[AssignmentSnapshot] = Field(default_factory=list)
    after_assignments: list[AssignmentSnapshot] = Field(default_factory=list)
    safety_notes: list[str] = Field(default_factory=list)
    why_changed: str
    estimated_outcome: str
    state: SimulationState
    schedule: ScheduleResponse | None = None


class RecoveryLogEntry(BaseModel):
    id: int
    sim_time: int
    correlation_id: str
    event_type: str
    tractor_id: str
    job_id: str | None = None
    field_id: str | None = None
    prior_status: str | None = None
    preserved_work_units: float = 0.0
    percent_complete: float | None = None
    remaining_percent: float | None = None
    reassigned_to: str | None = None
    retained_assignment_job_ids: list[str] = Field(default_factory=list)
    new_assignment_job_ids: list[str] = Field(default_factory=list)
    blocking_reason: str | None = None
    explanation: str
    feasible: bool = True


class BreakdownResponse(BaseModel):
    ok: bool
    state: SimulationState
    recovery: RecoveryLogEntry
    schedule: ScheduleResponse | None = None


class RepairResponse(BaseModel):
    ok: bool
    state: SimulationState
    recovery: RecoveryLogEntry


class ReplanResponse(BaseModel):
    ok: bool
    state: SimulationState
    recovery: RecoveryLogEntry
    schedule: ScheduleResponse


class RecoveryLogsResponse(BaseModel):
    logs: list[RecoveryLogEntry]
    count: int


class AgentTracesResponse(BaseModel):
    traces: list[AgentTrace]
    count: int


class AgentMetricsResponse(BaseModel):
    total_agent_calls: int
    average_latency_ms: float
    p95_latency_ms: float
    failed_calls: int
    validation_rejection_count: int
    committed_scheduling_decisions: int
    calls_per_committed_decision: float
    overall_replanning_latency_ms: float
    replan_count: int


class ProductivityMetrics(BaseModel):
    sim_time: int
    run_id: str | None = None
    tractor_filter: str | None = None
    definitions: dict[str, str]
    total_jobs_completed: int
    jobs_completed_before_deadline: int
    missed_deadlines: int
    priority_weighted_work_completed: float
    fleet_utilization_pct: float
    productive_work_time: float
    total_travel_time: float
    idle_time: float
    broken_unavailable_time: float
    available_operational_time: float
    fuel_consumed: float
    per_tractor: list[dict[str, Any]] = Field(default_factory=list)


class AgentCallStats(BaseModel):
    agent: str
    total_calls: int
    successful_calls: int
    failed_calls: int
    median_latency_ms: float
    p95_latency_ms: float


class FleetAgentMetrics(BaseModel):
    sim_time: int
    run_id: str | None = None
    agent_filter: str | None = None
    definitions: dict[str, str]
    total_calls: int
    successful_calls: int
    failed_calls: int
    median_latency_ms: float
    p95_latency_ms: float
    calls_per_completed_scheduling_decision: float
    safety_validation_rejections: int
    total_replanning_latency_ms: float
    replan_count: int
    recovery_attempts: int
    successful_recoveries: int
    per_agent: list[AgentCallStats] = Field(default_factory=list)
    # Backward-compatible fields used by existing /api/agents/metrics consumers
    total_agent_calls: int = 0
    average_latency_ms: float = 0.0
    validation_rejection_count: int = 0
    committed_scheduling_decisions: int = 0
    calls_per_committed_decision: float = 0.0
    overall_replanning_latency_ms: float = 0.0


class TimelinePoint(BaseModel):
    sim_time: int
    jobs_completed: int
    work_minutes: float
    travel_minutes: float
    idle_minutes: float
    broken_minutes: float
    fuel_consumed_cumulative: float


class DecisionTraceEntry(BaseModel):
    decision_id: str | None
    correlation_id: str
    sim_time: int
    tractor_id: str | None = None
    job_id: str | None = None
    selection_reason: str | None = None
    traces: list[AgentTrace] = Field(default_factory=list)


class MetricsTimelineResponse(BaseModel):
    sim_time: int
    run_id: str | None = None
    tractor_filter: str | None = None
    agent_filter: str | None = None
    event_type_filter: str | None = None
    productivity_series: list[TimelinePoint]
    jobs_completed_series: list[dict[str, Any]]
    time_breakdown_series: list[dict[str, Any]]
    replan_latency_history_ms: list[float]
    agent_communication_timeline: list[dict[str, Any]]
    recovery_stats: dict[str, Any]
    decision_traces: list[DecisionTraceEntry]


class MemoryRunRecord(BaseModel):
    run_id: str
    scenario_name: str
    seed: int
    started_at: str
    ended_at: str | None
    status: str


class MemoryIncidentRecord(BaseModel):
    id: int
    run_id: str
    simulation_time: int
    correlation_id: str | None
    tractor_id: str
    job_id: str | None
    field_id: str | None
    event_type: str
    preserved_work_units: float
    percent_complete: float | None
    reassigned_to: str | None
    blocking_reason: str | None
    recovery_action: str | None
    explanation: str


class MemoryDecisionRecord(BaseModel):
    run_id: str
    cycle_key: str
    simulation_time: int
    correlation_id: str | None
    trigger: str
    considered_pairs: int
    matching_score: float
    selected: list[dict[str, Any]]
    rejections: list[dict[str, Any]]
    explanation: str


class SimilarIncidentOutcome(BaseModel):
    run_id: str
    simulation_time: int
    event_type: str
    job_id: str | None
    recovery_action: str | None
    explanation: str
    reassigned_to: str | None
    blocking_reason: str | None


class MemoryTractorProfile(BaseModel):
    tractor_id: str
    breakdown_count: int
    repair_count: int
    runs_with_breakdowns: int
    warnings: list[str]
    recent_incidents: list[MemoryIncidentRecord]
    similar_historical_outcomes: list[SimilarIncidentOutcome]
    notes: str


class MemoryIncidentsResponse(BaseModel):
    incidents: list[MemoryIncidentRecord]
    count: int


class MemoryDecisionsResponse(BaseModel):
    decisions: list[MemoryDecisionRecord]
    count: int


class MemoryRunsResponse(BaseModel):
    runs: list[MemoryRunRecord]
    count: int
    current_run_id: str | None


class BenchmarkRunRequest(BaseModel):
    horizon: int = Field(default=300, ge=10, le=2000)
    variant_count: int = Field(default=20, ge=0, le=50)
    include_main: bool = True


class AgOpenWebConfigureRequest(BaseModel):
    """Path to an AgOpenWeb field.geojson, or null/empty to clear (unsupported)."""

    path: str | None = None


PlayMode = Literal["play", "pause"]
