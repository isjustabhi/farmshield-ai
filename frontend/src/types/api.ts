export interface HealthResponse {
  status: string
  service: string
  version: string
}

export type ApiConnectionState = 'checking' | 'connected' | 'disconnected'

export type AgOpenWebStatus = 'connected' | 'disconnected' | 'unsupported'

export interface AgOpenWebIntegration {
  status: AgOpenWebStatus
  mode: string
  message: string
  integrated: string[]
  remains_simulated: string[]
  field: {
    name: string | null
    origin_latitude: number | null
    origin_longitude: number | null
    format_version: number | null
    outer_boundary_points: number
    inner_boundary_count: number
    track_count: number
    flag_count: number
    source_path: string | null
  } | null
}

export type TractorStatus = 'idle' | 'traveling' | 'working' | 'refueling' | 'broken'
export type JobStatus = 'pending' | 'assigned' | 'in_progress' | 'completed' | 'blocked'

export interface Position {
  x: number
  y: number
}

export interface FieldModel {
  id: string
  name: string
  position: Position
  job_ids: string[]
}

export interface Tractor {
  id: string
  name: string
  implement_type: 'spraying' | 'mowing'
  fuel_level: number
  fuel_capacity: number
  working_speed: number
  travel_speed: number
  position: Position
  status: TractorStatus
  assigned_job_id: string | null
  path: Position[]
  path_index: number
  travel_cell_progress: number
}

export interface Job {
  id: string
  field_id: string
  job_type: 'spraying' | 'mowing'
  priority: number
  deadline_minute: number
  estimated_work_units: number
  completed_work_units: number
  status: JobStatus
  assigned_tractor_id: string | null
  sequence: number
  depends_on_job_id: string | null
}

export interface SimulationState {
  scenario_name: string
  seed: number
  sim_time: number
  playing: boolean
  grid: { width: number; height: number }
  fields: FieldModel[]
  tractors: Tractor[]
  jobs: Job[]
  obstacles: Position[]
  fuel: { travel_per_cell: number; work_per_unit: number; safety_reserve: number }
  depot: Position
  event_count: number
  tick_count: number
}

export interface SimEvent {
  id: number
  sim_time: number
  event_type: string
  message: string
  tractor_id: string | null
  job_id: string | null
  field_id: string | null
  data: Record<string, unknown>
}

export interface ScoreComponents {
  priority_reward: number
  deadline_urgency: number
  lateness_penalty: number
  travel_penalty: number
  unproductive_penalty: number
  total: number
}

export interface AssignmentDecision {
  tractor_id: string
  job_id: string
  estimated_travel_time: number
  estimated_work_time: number
  estimated_fuel_used: number
  predicted_finish: number
  deadline_margin: number
  score_components: ScoreComponents
  selection_reason: string
  sim_time: number
  decision_id: number
  applied: boolean
}

export interface RecoveryLogEntry {
  id: number
  sim_time: number
  correlation_id: string
  event_type: string
  tractor_id: string
  job_id: string | null
  field_id?: string | null
  explanation: string
  preserved_work_units: number
  percent_complete: number | null
  reassigned_to: string | null
  blocking_reason: string | null
  feasible: boolean
}

export interface AgentTrace {
  correlation_id: string
  decision_id: string | null
  sender: string
  receiver: string
  request_type: string
  response_type: string
  duration_ms: number
  status: string
  simulation_timestamp: number
  transport: string
  start_wall_time?: number
  end_wall_time?: number
  detail?: Record<string, unknown>
}

export interface AgentMetrics {
  total_agent_calls: number
  average_latency_ms: number
  p95_latency_ms: number
  failed_calls: number
  validation_rejection_count: number
  committed_scheduling_decisions: number
  calls_per_committed_decision: number
  overall_replanning_latency_ms: number
  replan_count: number
}

export interface IncidentAgentMessage {
  id: string
  correlation_id: string
  sim_time: number
  sender: string
  receiver: string
  content: string
  wall_time: number
  source: 'llm' | 'fallback' | string
}

export interface IncidentDialogue {
  correlation_id: string
  sim_time: number
  incident_type: string
  tractor_id: string
  job_id: string | null
  preserved_work_units: number
  messages: IncidentAgentMessage[]
  llm_used: boolean
  note: string
}

export interface LlmAgentStatus {
  enabled: boolean
  configured: boolean
  provider: string
  model: string
  base_url: string
  api_key_present: boolean
  dialogue_count: number
  note: string
}

export interface ProductivityMetrics {
  sim_time: number
  run_id: string | null
  tractor_filter: string | null
  definitions: Record<string, string>
  total_jobs_completed: number
  jobs_completed_before_deadline: number
  missed_deadlines: number
  priority_weighted_work_completed: number
  fleet_utilization_pct: number
  productive_work_time: number
  total_travel_time: number
  idle_time: number
  broken_unavailable_time: number
  available_operational_time: number
  fuel_consumed: number
  per_tractor: Array<{
    tractor_id: string
    work_minutes: number
    travel_minutes: number
    idle_minutes: number
    broken_minutes: number
    fuel_consumed: number
    available_operational_time: number
    utilization_pct: number
  }>
}

export interface AgentCallStats {
  agent: string
  total_calls: number
  successful_calls: number
  failed_calls: number
  median_latency_ms: number
  p95_latency_ms: number
}

export interface FleetAgentMetrics {
  sim_time: number
  run_id: string | null
  agent_filter: string | null
  definitions: Record<string, string>
  total_calls: number
  successful_calls: number
  failed_calls: number
  median_latency_ms: number
  p95_latency_ms: number
  calls_per_completed_scheduling_decision: number
  safety_validation_rejections: number
  total_replanning_latency_ms: number
  replan_count: number
  recovery_attempts: number
  successful_recoveries: number
  per_agent: AgentCallStats[]
  total_agent_calls: number
  average_latency_ms: number
  validation_rejection_count: number
  committed_scheduling_decisions: number
  calls_per_committed_decision: number
  overall_replanning_latency_ms: number
}

export interface TimelinePoint {
  sim_time: number
  jobs_completed: number
  work_minutes: number
  travel_minutes: number
  idle_minutes: number
  broken_minutes: number
  fuel_consumed_cumulative: number
}

export interface DecisionTraceEntry {
  decision_id: string | null
  correlation_id: string
  sim_time: number
  tractor_id: string | null
  job_id: string | null
  selection_reason: string | null
  traces: AgentTrace[]
}

export interface MetricsTimeline {
  sim_time: number
  run_id: string | null
  tractor_filter: string | null
  agent_filter: string | null
  event_type_filter: string | null
  productivity_series: TimelinePoint[]
  jobs_completed_series: Array<{
    sim_time: number
    jobs_completed_cumulative: number
    job_id: string
    tractor_id: string
    on_time: boolean
  }>
  time_breakdown_series: Array<{
    sim_time: number
    work: number
    travel: number
    idle: number
    broken: number
  }>
  replan_latency_history_ms: number[]
  agent_communication_timeline: Array<{
    sim_time: number
    correlation_id: string
    decision_id: string | null
    sender: string
    receiver: string
    request_type: string
    status: string
    duration_ms: number
  }>
  recovery_stats: {
    recovery_attempts: number
    successful_recoveries: number
    by_event_type: Record<string, number>
    logs: unknown[]
  }
  decision_traces: DecisionTraceEntry[]
}

export interface MemoryIncident {
  id: number
  run_id: string
  simulation_time: number
  tractor_id: string
  job_id: string | null
  event_type: string
  explanation: string
  preserved_work_units: number
  reassigned_to: string | null
  blocking_reason: string | null
}

export interface MemoryTractorProfile {
  tractor_id: string
  breakdown_count: number
  repair_count: number
  runs_with_breakdowns: number
  warnings: string[]
  recent_incidents: MemoryIncident[]
  similar_historical_outcomes: Array<{
    run_id: string
    simulation_time: number
    explanation: string
    recovery_action: string | null
  }>
  notes: string
}

export interface MemoryRun {
  run_id: string
  scenario_name: string
  seed: number
  started_at: string
  ended_at: string | null
  status: string
}

export interface BenchmarkRunMetrics {
  jobs_completed: number
  on_time_completions: number
  priority_weighted_work: number
  travel_time: number
  idle_time: number
  missed_deadlines: number
  fuel_consumed: number
  safety_violations: number
  breakdown_recovery_success: number
  breakdown_recovery_attempts: number
}

export interface BenchmarkScenarioResult {
  scenario_id: string
  label: string
  seed: number
  horizon: number
  incidents: Array<{ sim_time: number; kind: string; params: Record<string, unknown> }>
  baseline: BenchmarkRunMetrics
  farmshield: BenchmarkRunMetrics
  deltas: Record<string, number | null>
  pct_changes: Record<string, number | null>
  winners: Record<string, string>
  notes: string[]
}

export interface BenchmarkReport {
  generated_at: string
  methodology: string
  horizon: number
  variant_count: number
  scenario_path: string
  definitions: Record<string, string>
  scenarios: BenchmarkScenarioResult[]
  averages: {
    baseline: Record<string, number>
    farmshield: Record<string, number>
    pct_changes: Record<string, number | null>
    deltas: Record<string, number>
  }
  wins: {
    farmshield: number
    baseline: number
    tie: number
    per_metric?: Record<string, { farmshield: number; baseline: number; tie: number }>
  }
  explanations: string[]
}

export type AppView =
  | 'command'
  | 'fleet'
  | 'missions'
  | 'chaos'
  | 'intelligence'
  | 'agents'
  | 'memory'
  | 'benchmark'

export interface AssignmentSnapshot {
  job_id: string
  tractor_id: string | null
  status: string
  completed_work_units: number
  percent_complete: number
}

export interface ChaosEventResult {
  ok: boolean
  event_type: string
  explanation: string
  correlation_id: string
  seed: number | null
  sim_time: number
  affected_jobs: string[]
  preserved_work: Record<string, number>
  unreachable_jobs: string[]
  before_assignments: AssignmentSnapshot[]
  after_assignments: AssignmentSnapshot[]
  safety_notes: string[]
  why_changed: string
  estimated_outcome: string
  state: SimulationState
}
