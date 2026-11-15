import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { GlassPanel } from '../components/ui/GlassPanel'
import { api } from '../services/api'
import type { AssignmentDecision, BenchmarkReport, SimulationState } from '../types/api'

const TOOLTIP_STYLE = {
  background: '#0f172a',
  border: '1px solid rgba(148,163,184,0.2)',
  fontSize: 12,
}

const METRIC_KEYS = [
  'jobs_completed',
  'on_time_completions',
  'priority_weighted_work',
  'travel_time',
  'idle_time',
  'missed_deadlines',
  'fuel_consumed',
  'safety_violations',
  'breakdown_recovery_success',
] as const

function fmt(n: number | null | undefined, digits = 2): string {
  if (n == null || Number.isNaN(n)) return '—'
  return Number.isInteger(n) ? String(n) : n.toFixed(digits)
}

function pctLabel(n: number | null | undefined): string {
  if (n == null) return 'n/a (baseline 0)'
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(1)}%`
}

export function BenchmarkLabPage({
  state,
  decisions,
}: {
  state: SimulationState
  decisions: AssignmentDecision[]
}) {
  const [report, setReport] = useState<BenchmarkReport | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [horizon, setHorizon] = useState(300)
  const [variants, setVariants] = useState(20)
  const [selectedScenario, setSelectedScenario] = useState<string>('')

  const refresh = useCallback(async () => {
    try {
      const payload = await api.getBenchmark()
      if (payload.available && payload.report) {
        setReport(payload.report)
        setSelectedScenario((prev) => prev || payload.report!.scenarios[0]?.scenario_id || '')
      }
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load benchmark')
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const run = async () => {
    setBusy(true)
    setError(null)
    try {
      const payload = await api.runBenchmark({
        horizon,
        variant_count: variants,
        include_main: true,
      })
      setReport(payload.report)
      setSelectedScenario(payload.report.scenarios[0]?.scenario_id ?? '')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Benchmark run failed')
    } finally {
      setBusy(false)
    }
  }

  const download = async (format: 'json' | 'csv') => {
    try {
      const payload = await api.exportBenchmark()
      if (format === 'json') {
        const blob = new Blob([JSON.stringify(payload.report, null, 2)], {
          type: 'application/json',
        })
        triggerDownload(blob, 'benchmark_results.json')
      } else {
        const blob = new Blob([payload.csv_text ?? ''], { type: 'text/csv' })
        triggerDownload(blob, 'benchmark_results.csv')
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Export failed')
    }
  }

  const avgChart = useMemo(() => {
    if (!report?.averages) return []
    return METRIC_KEYS.map((key) => ({
      metric: key.replace(/_/g, ' '),
      baseline: Number(report.averages.baseline?.[key] ?? 0),
      farmshield: Number(report.averages.farmshield?.[key] ?? 0),
    }))
  }, [report])

  const scenario = report?.scenarios.find((s) => s.scenario_id === selectedScenario)

  const liveCompleted = state.jobs.filter((j) => j.status === 'completed').length

  return (
    <div className="space-y-4">
      <GlassPanel title="Benchmark Lab controls">
        <p className="mb-3 text-xs leading-relaxed text-slate-500">
          Fair head-to-head: FCFS baseline vs FarmShield on independent simulation copies. Same
          scenario, tractors, fuel, jobs, deadlines, routes, horizon, seeded incidents, and Safety
          Agent. Results are measured — never hardcoded.
        </p>
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-xs text-slate-400">
            Horizon (sim minutes)
            <input
              type="number"
              min={10}
              max={2000}
              value={horizon}
              onChange={(e) => setHorizon(Number(e.target.value))}
              className="mt-1 block w-28 rounded-md border border-white/10 bg-slate-950/60 px-2 py-2 text-sm"
            />
          </label>
          <label className="text-xs text-slate-400">
            Seeded variants
            <input
              type="number"
              min={0}
              max={50}
              value={variants}
              onChange={(e) => setVariants(Number(e.target.value))}
              className="mt-1 block w-28 rounded-md border border-white/10 bg-slate-950/60 px-2 py-2 text-sm"
            />
          </label>
          <button
            type="button"
            disabled={busy}
            onClick={() => void run()}
            className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {busy ? 'Running benchmark…' : 'Run benchmark'}
          </button>
          <button
            type="button"
            disabled={!report}
            onClick={() => void download('json')}
            className="rounded-md border border-white/15 px-3 py-2 text-sm text-slate-200 disabled:opacity-40"
          >
            Download JSON
          </button>
          <button
            type="button"
            disabled={!report}
            onClick={() => void download('csv')}
            className="rounded-md border border-white/15 px-3 py-2 text-sm text-slate-200 disabled:opacity-40"
          >
            Download CSV
          </button>
        </div>
        {error ? <p className="mt-3 text-xs text-red-300">{error}</p> : null}
        <p className="mt-2 text-[11px] text-slate-500">
          Live Command Center snapshot (not the benchmark): {liveCompleted}/{state.jobs.length} jobs
          completed · {decisions.length} fleet decisions · t={state.sim_time}
        </p>
      </GlassPanel>

      {!report ? (
        <GlassPanel title="No results yet">
          <p className="text-sm text-slate-400">
            Run the benchmark to compare FCFS vs FarmShield across the main demo scenario and seeded
            variants. Exports write to <code className="text-emerald-300">benchmark_results.json</code>{' '}
            / <code className="text-emerald-300">benchmark_results.csv</code>.
          </p>
        </GlassPanel>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-3">
            <Stat
              label="Scenarios won (FarmShield)"
              value={String(report.wins?.farmshield ?? 0)}
            />
            <Stat label="Scenarios won (FCFS)" value={String(report.wins?.baseline ?? 0)} />
            <Stat label="Scenario ties" value={String(report.wins?.tie ?? 0)} />
          </div>

          <GlassPanel title="Average metrics (side-by-side)">
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {METRIC_KEYS.map((key) => {
                const b = report.averages.baseline?.[key]
                const f = report.averages.farmshield?.[key]
                const pct = report.averages.pct_changes?.[key]
                return (
                  <div
                    key={key}
                    className="rounded-lg border border-white/5 bg-black/20 px-3 py-3 text-sm"
                  >
                    <p className="text-[10px] uppercase tracking-wide text-slate-500">
                      {key.replace(/_/g, ' ')}
                    </p>
                    <div className="mt-2 grid grid-cols-2 gap-2">
                      <div>
                        <p className="text-[10px] text-slate-500">FCFS</p>
                        <p className="font-mono text-slate-100">{fmt(b)}</p>
                      </div>
                      <div>
                        <p className="text-[10px] text-slate-500">FarmShield</p>
                        <p className="font-mono text-emerald-300">{fmt(f)}</p>
                      </div>
                    </div>
                    <p className="mt-2 text-[11px] text-slate-400">Δ% {pctLabel(pct ?? null)}</p>
                  </div>
                )
              })}
            </div>
          </GlassPanel>

          <GlassPanel title="Comparison bar chart (averages)">
            <div className="h-80">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={avgChart} margin={{ left: 8, right: 8 }}>
                  <CartesianGrid stroke="rgba(148,163,184,0.12)" vertical={false} />
                  <XAxis dataKey="metric" stroke="#94a3b8" fontSize={10} interval={0} angle={-20} textAnchor="end" height={70} />
                  <YAxis stroke="#94a3b8" fontSize={11} />
                  <Tooltip contentStyle={TOOLTIP_STYLE} />
                  <Legend />
                  <Bar dataKey="baseline" name="FCFS" fill="#94a3b8" />
                  <Bar dataKey="farmshield" name="FarmShield" fill="#10b981" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </GlassPanel>

          <GlassPanel title="Per-scenario results">
            <label className="mb-3 block text-xs text-slate-400">
              Scenario
              <select
                className="mt-1 w-full max-w-lg rounded-md border border-white/10 bg-slate-950/60 px-2 py-2 text-sm"
                value={selectedScenario}
                onChange={(e) => setSelectedScenario(e.target.value)}
              >
                {report.scenarios.map((s) => (
                  <option key={s.scenario_id} value={s.scenario_id}>
                    {s.scenario_id} — {s.label}
                  </option>
                ))}
              </select>
            </label>
            {scenario ? (
              <div className="space-y-3">
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[640px] text-left text-xs text-slate-300">
                    <thead className="text-[10px] uppercase tracking-wide text-slate-500">
                      <tr>
                        <th className="py-2 pr-3">Metric</th>
                        <th className="py-2 pr-3">FCFS</th>
                        <th className="py-2 pr-3">FarmShield</th>
                        <th className="py-2 pr-3">Δ</th>
                        <th className="py-2 pr-3">Δ%</th>
                        <th className="py-2">Winner</th>
                      </tr>
                    </thead>
                    <tbody>
                      {METRIC_KEYS.map((key) => (
                        <tr key={key} className="border-t border-white/5">
                          <td className="py-2 pr-3">{key.replace(/_/g, ' ')}</td>
                          <td className="py-2 pr-3 font-mono">
                            {fmt(scenario.baseline[key] as number)}
                          </td>
                          <td className="py-2 pr-3 font-mono text-emerald-300">
                            {fmt(scenario.farmshield[key] as number)}
                          </td>
                          <td className="py-2 pr-3 font-mono">
                            {fmt(scenario.deltas[key] ?? null)}
                          </td>
                          <td className="py-2 pr-3 font-mono">
                            {pctLabel(scenario.pct_changes[key] ?? null)}
                          </td>
                          <td className="py-2">{scenario.winners[key] ?? '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {scenario.notes.length > 0 ? (
                  <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-xs text-amber-100/90">
                    <p className="mb-1 font-medium text-amber-200">Where FarmShield was worse</p>
                    <ul className="list-disc space-y-1 pl-4">
                      {scenario.notes.map((n) => (
                        <li key={n}>{n}</li>
                      ))}
                    </ul>
                  </div>
                ) : (
                  <p className="text-xs text-slate-500">
                    No metrics where FarmShield underperformed FCFS in this scenario.
                  </p>
                )}
              </div>
            ) : null}
          </GlassPanel>

          <GlassPanel title="Explanations & definitions">
            <div className="grid gap-4 lg:grid-cols-2">
              <div>
                <p className="mb-2 text-[10px] uppercase tracking-wide text-slate-500">
                  Average outcomes
                </p>
                <ul className="space-y-2 text-xs leading-relaxed text-slate-400">
                  {(report.explanations ?? []).map((e) => (
                    <li key={e}>• {e}</li>
                  ))}
                </ul>
              </div>
              <div>
                <p className="mb-2 text-[10px] uppercase tracking-wide text-slate-500">
                  Metric definitions
                </p>
                <ul className="space-y-2 text-xs leading-relaxed text-slate-400">
                  {Object.entries(report.definitions ?? {}).map(([k, v]) => (
                    <li key={k}>
                      <span className="text-slate-200">{k.replace(/_/g, ' ')}</span> — {v}
                    </li>
                  ))}
                </ul>
                <p className="mt-3 text-[11px] text-slate-500">{report.methodology}</p>
              </div>
            </div>
          </GlassPanel>
        </>
      )}
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-white/5 bg-black/20 px-3 py-3">
      <p className="text-[10px] uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-1 text-lg font-semibold text-slate-100">{value}</p>
    </div>
  )
}

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}
