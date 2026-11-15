import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { GlassPanel } from '../components/ui/GlassPanel'
import { api } from '../services/api'
import type {
  DecisionTraceEntry,
  FleetAgentMetrics,
  MemoryRun,
  MetricsTimeline,
  ProductivityMetrics,
  SimulationState,
} from '../types/api'

const TOOLTIP_STYLE = {
  background: '#0f172a',
  border: '1px solid rgba(148,163,184,0.2)',
  fontSize: 12,
}

const AGENTS = [
  'fleet_agent',
  'navigation_agent',
  'safety_agent',
  'recovery_agent',
] as const

const EVENT_TYPES = [
  '',
  'RouteRequest',
  'SafetyValidationRequest',
  'IncidentRequest',
  'rejected',
  'error',
  'ok',
] as const

interface IntelligencePageProps {
  state: SimulationState
  runs: MemoryRun[]
  currentRunId: string | null
}

function Kpi({
  label,
  value,
  hint,
}: {
  label: string
  value: string
  hint?: string
}) {
  return (
    <div className="rounded-lg border border-white/5 bg-white/[0.03] px-3 py-3">
      <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500">
        {label}
      </p>
      <p className="mt-1 font-mono text-lg text-emerald-300 tabular-nums">{value}</p>
      {hint ? <p className="mt-1 text-[10px] leading-snug text-slate-500">{hint}</p> : null}
    </div>
  )
}

export function IntelligencePage({ state, runs, currentRunId }: IntelligencePageProps) {
  const [tractorId, setTractorId] = useState('')
  const [runId, setRunId] = useState('')
  const [agent, setAgent] = useState('')
  const [eventType, setEventType] = useState('')
  const [productivity, setProductivity] = useState<ProductivityMetrics | null>(null)
  const [agentMetrics, setAgentMetrics] = useState<FleetAgentMetrics | null>(null)
  const [timeline, setTimeline] = useState<MetricsTimeline | null>(null)
  const [selectedTrace, setSelectedTrace] = useState<DecisionTraceEntry | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const params = {
        tractor_id: tractorId || undefined,
        run_id: runId || undefined,
        agent: agent || undefined,
        event_type: eventType || undefined,
      }
      const [prod, agents, tl] = await Promise.all([
        api.getProductivityMetrics({
          tractor_id: params.tractor_id,
          run_id: params.run_id,
        }),
        api.getFleetAgentMetrics({ agent: params.agent, run_id: params.run_id }),
        api.getMetricsTimeline(params),
      ])
      setProductivity(prod)
      setAgentMetrics(agents)
      setTimeline(tl)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load metrics')
    }
  }, [tractorId, runId, agent, eventType])

  useEffect(() => {
    void load()
    const id = window.setInterval(() => void load(), 1200)
    return () => window.clearInterval(id)
  }, [load, state.sim_time, state.tick_count])

  const replanHistory = useMemo(
    () =>
      (timeline?.replan_latency_history_ms ?? []).map((ms, i) => ({
        index: i + 1,
        latency_ms: Number(ms.toFixed(3)),
      })),
    [timeline],
  )

  const agentBars = useMemo(
    () =>
      (agentMetrics?.per_agent ?? []).map((a) => ({
        agent: a.agent.replace('_agent', ''),
        calls: a.total_calls,
        success: a.successful_calls,
        failed: a.failed_calls,
        median: Number(a.median_latency_ms.toFixed(3)),
      })),
    [agentMetrics],
  )

  return (
    <div className="space-y-4">
      <GlassPanel title="Fleet Intelligence filters">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <label className="text-xs text-slate-400">
            Tractor
            <select
              className="mt-1 w-full rounded-md border border-white/10 bg-slate-950/60 px-2 py-2 text-sm text-slate-100"
              value={tractorId}
              onChange={(e) => setTractorId(e.target.value)}
            >
              <option value="">All tractors</option>
              {state.tractors.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-slate-400">
            Simulation run
            <select
              className="mt-1 w-full rounded-md border border-white/10 bg-slate-950/60 px-2 py-2 text-sm text-slate-100"
              value={runId}
              onChange={(e) => setRunId(e.target.value)}
            >
              <option value="">Current run{currentRunId ? ` (${currentRunId.slice(0, 8)})` : ''}</option>
              {runs.map((r) => (
                <option key={r.run_id} value={r.run_id}>
                  {r.scenario_name} · {r.status} · {r.run_id.slice(0, 8)}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-slate-400">
            Agent
            <select
              className="mt-1 w-full rounded-md border border-white/10 bg-slate-950/60 px-2 py-2 text-sm text-slate-100"
              value={agent}
              onChange={(e) => setAgent(e.target.value)}
            >
              <option value="">All agents</option>
              {AGENTS.map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-slate-400">
            Event type
            <select
              className="mt-1 w-full rounded-md border border-white/10 bg-slate-950/60 px-2 py-2 text-sm text-slate-100"
              value={eventType}
              onChange={(e) => setEventType(e.target.value)}
            >
              {EVENT_TYPES.map((et) => (
                <option key={et || 'all'} value={et}>
                  {et || 'All event types'}
                </option>
              ))}
            </select>
          </label>
        </div>
        {error ? <p className="mt-3 text-xs text-red-300">{error}</p> : null}
        <p className="mt-3 text-[11px] text-slate-500">
          Utilization = work / (work + travel + idle). Broken time excluded. Agent latency is
          wall-clock (perf_counter), not simulated minutes.
        </p>
      </GlassPanel>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <Kpi
          label="Jobs completed"
          value={String(productivity?.total_jobs_completed ?? 0)}
          hint={`${productivity?.jobs_completed_before_deadline ?? 0} before deadline`}
        />
        <Kpi
          label="Fleet utilization"
          value={`${(productivity?.fleet_utilization_pct ?? 0).toFixed(1)}%`}
          hint={`Avail ${ (productivity?.available_operational_time ?? 0).toFixed(0)} min`}
        />
        <Kpi
          label="Priority-weighted work"
          value={(productivity?.priority_weighted_work_completed ?? 0).toFixed(1)}
        />
        <Kpi
          label="Fuel consumed"
          value={(productivity?.fuel_consumed ?? 0).toFixed(2)}
        />
        <Kpi
          label="Missed deadlines"
          value={String(productivity?.missed_deadlines ?? 0)}
        />
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Kpi label="Work time" value={`${(productivity?.productive_work_time ?? 0).toFixed(0)} min`} />
        <Kpi label="Travel time" value={`${(productivity?.total_travel_time ?? 0).toFixed(0)} min`} />
        <Kpi label="Idle time" value={`${(productivity?.idle_time ?? 0).toFixed(0)} min`} />
        <Kpi
          label="Broken time"
          value={`${(productivity?.broken_unavailable_time ?? 0).toFixed(0)} min`}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <GlassPanel title="Fleet productivity (cumulative)">
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={timeline?.productivity_series ?? []}>
                <CartesianGrid stroke="rgba(148,163,184,0.12)" vertical={false} />
                <XAxis dataKey="sim_time" stroke="#94a3b8" fontSize={11} />
                <YAxis stroke="#94a3b8" fontSize={11} />
                <Tooltip contentStyle={TOOLTIP_STYLE} />
                <Legend />
                <Line
                  type="monotone"
                  dataKey="work_minutes"
                  name="Work"
                  stroke="#10b981"
                  dot={false}
                  strokeWidth={2}
                />
                <Line
                  type="monotone"
                  dataKey="travel_minutes"
                  name="Travel"
                  stroke="#38bdf8"
                  dot={false}
                  strokeWidth={2}
                />
                <Line
                  type="monotone"
                  dataKey="idle_minutes"
                  name="Idle"
                  stroke="#f59e0b"
                  dot={false}
                  strokeWidth={2}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </GlassPanel>

        <GlassPanel title="Jobs completed over simulated time">
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={timeline?.jobs_completed_series ?? []}>
                <CartesianGrid stroke="rgba(148,163,184,0.12)" vertical={false} />
                <XAxis dataKey="sim_time" stroke="#94a3b8" fontSize={11} />
                <YAxis stroke="#94a3b8" fontSize={11} allowDecimals={false} />
                <Tooltip contentStyle={TOOLTIP_STYLE} />
                <Area
                  type="stepAfter"
                  dataKey="jobs_completed_cumulative"
                  name="Completed"
                  stroke="#10b981"
                  fill="rgba(16,185,129,0.2)"
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </GlassPanel>

        <GlassPanel title="Travel vs idle vs work">
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={timeline?.time_breakdown_series ?? []}>
                <CartesianGrid stroke="rgba(148,163,184,0.12)" vertical={false} />
                <XAxis dataKey="sim_time" stroke="#94a3b8" fontSize={11} />
                <YAxis stroke="#94a3b8" fontSize={11} />
                <Tooltip contentStyle={TOOLTIP_STYLE} />
                <Legend />
                <Area
                  type="monotone"
                  dataKey="work"
                  stackId="1"
                  stroke="#10b981"
                  fill="rgba(16,185,129,0.45)"
                />
                <Area
                  type="monotone"
                  dataKey="travel"
                  stackId="1"
                  stroke="#38bdf8"
                  fill="rgba(56,189,248,0.35)"
                />
                <Area
                  type="monotone"
                  dataKey="idle"
                  stackId="1"
                  stroke="#f59e0b"
                  fill="rgba(245,158,11,0.3)"
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </GlassPanel>

        <GlassPanel title="Agent calls comparison">
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={agentBars}>
                <CartesianGrid stroke="rgba(148,163,184,0.12)" vertical={false} />
                <XAxis dataKey="agent" stroke="#94a3b8" fontSize={11} />
                <YAxis stroke="#94a3b8" fontSize={11} allowDecimals={false} />
                <Tooltip contentStyle={TOOLTIP_STYLE} />
                <Legend />
                <Bar dataKey="success" name="Success" stackId="a" fill="#10b981" />
                <Bar dataKey="failed" name="Failed" stackId="a" fill="#ef4444" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </GlassPanel>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Kpi label="Agent calls" value={String(agentMetrics?.total_calls ?? 0)} />
        <Kpi
          label="Median / P95 latency"
          value={`${(agentMetrics?.median_latency_ms ?? 0).toFixed(2)} / ${(agentMetrics?.p95_latency_ms ?? 0).toFixed(2)} ms`}
        />
        <Kpi
          label="Calls / decision"
          value={(agentMetrics?.calls_per_completed_scheduling_decision ?? 0).toFixed(2)}
        />
        <Kpi
          label="Safety rejections"
          value={String(agentMetrics?.safety_validation_rejections ?? 0)}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <GlassPanel title="Agent communication timeline">
          <div className="fs-scroll max-h-72 space-y-1 overflow-auto text-xs">
            {(timeline?.agent_communication_timeline ?? []).length === 0 ? (
              <p className="text-slate-500">No agent calls recorded yet.</p>
            ) : (
              [...(timeline?.agent_communication_timeline ?? [])]
                .slice()
                .reverse()
                .slice(0, 40)
                .map((row, idx) => (
                  <div
                    key={`${row.correlation_id}-${idx}`}
                    className="flex flex-wrap items-center gap-2 rounded border border-white/5 px-2 py-1.5 text-slate-300"
                  >
                    <span className="font-mono text-emerald-400/90">t={row.sim_time}</span>
                    <span>
                      {row.sender} → {row.receiver}
                    </span>
                    <span className="text-slate-500">{row.request_type}</span>
                    <span
                      className={
                        row.status === 'error' || row.status === 'failed'
                          ? 'text-red-300'
                          : row.status === 'rejected'
                            ? 'text-amber-300'
                            : 'text-slate-400'
                      }
                    >
                      {row.status}
                    </span>
                    <span className="ml-auto font-mono text-slate-500">
                      {row.duration_ms.toFixed(2)} ms
                    </span>
                  </div>
                ))
            )}
          </div>
        </GlassPanel>

        <GlassPanel title="Replanning latency history">
          <div className="h-64">
            {(replanHistory.length === 0 && (
              <p className="text-xs text-slate-500">No recovery replans recorded yet.</p>
            )) || (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={replanHistory}>
                  <CartesianGrid stroke="rgba(148,163,184,0.12)" vertical={false} />
                  <XAxis dataKey="index" stroke="#94a3b8" fontSize={11} />
                  <YAxis stroke="#94a3b8" fontSize={11} unit=" ms" />
                  <Tooltip contentStyle={TOOLTIP_STYLE} />
                  <Line
                    type="monotone"
                    dataKey="latency_ms"
                    name="Replan ms"
                    stroke="#f59e0b"
                    strokeWidth={2}
                    dot
                  />
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-slate-400">
            <p>
              Recovery attempts:{' '}
              <span className="font-mono text-slate-200">
                {timeline?.recovery_stats.recovery_attempts ??
                  agentMetrics?.recovery_attempts ??
                  0}
              </span>
            </p>
            <p>
              Successful recoveries:{' '}
              <span className="font-mono text-slate-200">
                {timeline?.recovery_stats.successful_recoveries ??
                  agentMetrics?.successful_recoveries ??
                  0}
              </span>
            </p>
            <p>
              Total replan latency:{' '}
              <span className="font-mono text-slate-200">
                {(agentMetrics?.total_replanning_latency_ms ?? 0).toFixed(2)} ms
              </span>
            </p>
            <p>
              Replan count:{' '}
              <span className="font-mono text-slate-200">
                {agentMetrics?.replan_count ?? 0}
              </span>
            </p>
          </div>
        </GlassPanel>
      </div>

      <GlassPanel title="Decision trace explorer">
        <div className="grid gap-4 lg:grid-cols-[1fr_1.2fr]">
          <div className="fs-scroll max-h-80 space-y-1 overflow-auto">
            {(timeline?.decision_traces ?? []).length === 0 ? (
              <p className="text-xs text-slate-500">
                No scheduling decision traces yet. Run schedule or play the simulation.
              </p>
            ) : (
              [...(timeline?.decision_traces ?? [])]
                .slice()
                .reverse()
                .map((entry) => (
                  <button
                    key={`${entry.correlation_id}-${entry.decision_id}`}
                    type="button"
                    onClick={() => setSelectedTrace(entry)}
                    className={`w-full rounded border px-3 py-2 text-left text-xs transition ${
                      selectedTrace?.correlation_id === entry.correlation_id &&
                      selectedTrace?.decision_id === entry.decision_id
                        ? 'border-emerald-500/40 bg-emerald-500/10'
                        : 'border-white/5 hover:border-white/15'
                    }`}
                  >
                    <div className="flex flex-wrap gap-2 text-slate-300">
                      <span className="font-mono text-emerald-400">t={entry.sim_time}</span>
                      <span>{entry.tractor_id ?? '—'}</span>
                      <span>{entry.job_id ?? '—'}</span>
                      <span className="text-slate-500">
                        {entry.traces.length} call{entry.traces.length === 1 ? '' : 's'}
                      </span>
                    </div>
                    <p className="mt-1 line-clamp-2 text-[11px] text-slate-500">
                      {entry.selection_reason ?? entry.correlation_id}
                    </p>
                  </button>
                ))
            )}
          </div>
          <div className="rounded-lg border border-white/5 bg-black/20 p-3 text-xs text-slate-300">
            {!selectedTrace ? (
              <p className="text-slate-500">Select a decision to inspect correlated agent traces.</p>
            ) : (
              <div className="space-y-3">
                <div>
                  <p className="text-[10px] uppercase tracking-wider text-slate-500">Decision</p>
                  <p className="font-mono text-emerald-300">
                    {selectedTrace.decision_id ?? 'uncommitted'} · {selectedTrace.correlation_id.slice(0, 12)}
                  </p>
                  <p className="mt-1 text-slate-400">
                    {selectedTrace.tractor_id ?? '—'} → {selectedTrace.job_id ?? '—'} @ t=
                    {selectedTrace.sim_time}
                  </p>
                  <p className="mt-2 leading-relaxed text-slate-400">
                    {selectedTrace.selection_reason ?? 'No selection reason recorded.'}
                  </p>
                </div>
                <div className="space-y-1">
                  <p className="text-[10px] uppercase tracking-wider text-slate-500">
                    Correlated traces
                  </p>
                  {selectedTrace.traces.map((t, i) => (
                    <div
                      key={`${t.sender}-${t.receiver}-${i}`}
                      className="rounded border border-white/5 px-2 py-1.5"
                    >
                      <div className="flex flex-wrap gap-2">
                        <span>
                          {t.sender} → {t.receiver}
                        </span>
                        <span className="text-slate-500">{t.request_type}</span>
                        <span className="ml-auto font-mono text-slate-500">
                          {t.duration_ms.toFixed(3)} ms
                        </span>
                      </div>
                      <p className="text-slate-500">
                        status={t.status} · sim_t={t.simulation_timestamp}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </GlassPanel>
    </div>
  )
}
