import type {
  AgentMetrics,
  AgentTrace,
  AssignmentDecision,
  BenchmarkReport,
  ChaosEventResult,
  FleetAgentMetrics,
  HealthResponse,
  MemoryIncident,
  MemoryRun,
  MemoryTractorProfile,
  MetricsTimeline,
  ProductivityMetrics,
  RecoveryLogEntry,
  SimEvent,
  SimulationState,
} from '../types/api'

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    ...init,
  })
  if (!response.ok) {
    let detail = `API ${path} failed with ${response.status}`
    try {
      const body = (await response.json()) as { detail?: string }
      if (body.detail) detail = body.detail
    } catch {
      /* ignore */
    }
    throw new Error(detail)
  }
  return response.json() as Promise<T>
}

export const api = {
  getHealth: () => request<HealthResponse>('/health'),
  getState: () => request<SimulationState>('/state'),
  getEvents: (afterId = 0) =>
    request<{ events: SimEvent[]; sim_time: number }>(`/events?after_id=${afterId}`),
  getDecisions: () =>
    request<{ decisions: AssignmentDecision[]; sim_time: number }>('/decisions'),
  getAssignments: () =>
    request<{ active: AssignmentDecision[]; active_job_ids: string[]; sim_time: number }>(
      '/assignments',
    ),
  getRecoveryLogs: () =>
    request<{ logs: RecoveryLogEntry[]; count: number }>('/recovery/logs'),
  getAgentTraces: () =>
    request<{ traces: AgentTrace[]; count: number }>('/agents/traces'),
  getAgentMetrics: () => request<AgentMetrics>('/agents/metrics'),
  getProductivityMetrics: (params?: { tractor_id?: string; run_id?: string }) => {
    const q = new URLSearchParams()
    if (params?.tractor_id) q.set('tractor_id', params.tractor_id)
    if (params?.run_id) q.set('run_id', params.run_id)
    const suffix = q.toString() ? `?${q}` : ''
    return request<ProductivityMetrics>(`/metrics/productivity${suffix}`)
  },
  getFleetAgentMetrics: (params?: { agent?: string; run_id?: string }) => {
    const q = new URLSearchParams()
    if (params?.agent) q.set('agent', params.agent)
    if (params?.run_id) q.set('run_id', params.run_id)
    const suffix = q.toString() ? `?${q}` : ''
    return request<FleetAgentMetrics>(`/metrics/agents${suffix}`)
  },
  getMetricsTimeline: (params?: {
    tractor_id?: string
    run_id?: string
    agent?: string
    event_type?: string
  }) => {
    const q = new URLSearchParams()
    if (params?.tractor_id) q.set('tractor_id', params.tractor_id)
    if (params?.run_id) q.set('run_id', params.run_id)
    if (params?.agent) q.set('agent', params.agent)
    if (params?.event_type) q.set('event_type', params.event_type)
    const suffix = q.toString() ? `?${q}` : ''
    return request<MetricsTimeline>(`/metrics/timeline${suffix}`)
  },
  getMemoryIncidents: (params?: { tractor_id?: string; event_type?: string }) => {
    const q = new URLSearchParams()
    if (params?.tractor_id) q.set('tractor_id', params.tractor_id)
    if (params?.event_type) q.set('event_type', params.event_type)
    const suffix = q.toString() ? `?${q}` : ''
    return request<{ incidents: MemoryIncident[]; count: number }>(`/memory/incidents${suffix}`)
  },
  getMemoryTractor: (tractorId: string) =>
    request<MemoryTractorProfile>(`/memory/tractor/${tractorId}`),
  getMemoryRuns: () =>
    request<{ runs: MemoryRun[]; count: number; current_run_id: string | null }>('/memory/runs'),
  getMemoryDecisions: () =>
    request<{ decisions: unknown[]; count: number }>('/memory/decisions'),

  play: () => request<{ ok: boolean; state: SimulationState }>('/simulation/play', { method: 'POST' }),
  pause: () =>
    request<{ ok: boolean; state: SimulationState }>('/simulation/pause', { method: 'POST' }),
  step: () =>
    request<{ state: SimulationState; new_events: SimEvent[] }>('/simulation/step', {
      method: 'POST',
    }),
  reset: () =>
    request<{ ok: boolean; state: SimulationState }>('/simulation/reset', { method: 'POST' }),
  schedule: () =>
    request<{
      assignments: AssignmentDecision[]
      infeasible_jobs: Array<{ job_id: string; reasons: string[] }>
      considered_pairs: number
      matching_score: number
    }>('/schedule', { method: 'POST' }),
  replan: () =>
    request<{
      ok: boolean
      state: SimulationState
      recovery: RecoveryLogEntry
    }>('/replan', { method: 'POST' }),
  breakdown: (tractorId: string, reason = 'dashboard_breakdown') =>
    request<{
      ok: boolean
      state: SimulationState
      recovery: RecoveryLogEntry
    }>('/events/breakdown', {
      method: 'POST',
      body: JSON.stringify({ tractor_id: tractorId, reason }),
    }),
  repair: (tractorId: string) =>
    request<{ ok: boolean; state: SimulationState; recovery: RecoveryLogEntry }>(
      '/events/repair',
      {
        method: 'POST',
        body: JSON.stringify({ tractor_id: tractorId }),
      },
    ),
  blockRoute: (x: number, y: number) =>
    request<ChaosEventResult>('/events/block-route', {
      method: 'POST',
      body: JSON.stringify({ x, y, reason: 'dashboard_block' }),
    }),
  unblockRoute: (x: number, y: number) =>
    request<ChaosEventResult>('/events/unblock-route', {
      method: 'POST',
      body: JSON.stringify({ x, y }),
    }),
  priorityChange: (jobId: string, priority: number) =>
    request<ChaosEventResult>('/events/priority-change', {
      method: 'POST',
      body: JSON.stringify({ job_id: jobId, priority }),
    }),
  fuelChange: (tractorId: string, fuelLevel: number) =>
    request<ChaosEventResult>('/events/fuel-change', {
      method: 'POST',
      body: JSON.stringify({ tractor_id: tractorId, fuel_level: fuelLevel }),
    }),
  chaosRandom: (seed?: number) =>
    request<ChaosEventResult>('/chaos/random', {
      method: 'POST',
      body: JSON.stringify({ seed: seed ?? null }),
    }),
  getBenchmark: () =>
    request<{ available: boolean; report: BenchmarkReport | null; message?: string }>(
      '/benchmark',
    ),
  runBenchmark: (body?: { horizon?: number; variant_count?: number; include_main?: boolean }) =>
    request<{ ok: boolean; report: BenchmarkReport }>('/benchmark/run', {
      method: 'POST',
      body: JSON.stringify(body ?? {}),
    }),
  exportBenchmark: () =>
    request<{
      json_path: string
      csv_path: string
      json_exists: boolean
      csv_exists: boolean
      report: BenchmarkReport
      csv_text?: string
    }>('/benchmark/export'),
}
