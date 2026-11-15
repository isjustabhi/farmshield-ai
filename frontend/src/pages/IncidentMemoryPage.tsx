import { GlassPanel } from '../components/ui/GlassPanel'
import type { MemoryIncident, MemoryRun } from '../types/api'

export function IncidentMemoryPage({
  incidents,
  runs,
}: {
  incidents: MemoryIncident[]
  runs: MemoryRun[]
}) {
  return (
    <div className="grid gap-4 lg:grid-cols-[0.85fr_1.25fr]">
      <GlassPanel title="Simulation runs">
        <ul className="fs-scroll max-h-[28rem] space-y-2 overflow-y-auto text-xs">
          {runs.length === 0 && <li className="text-slate-500">No runs recorded yet.</li>}
          {runs.map((run) => (
            <li key={run.run_id} className="rounded-lg border border-white/5 bg-black/20 px-3 py-2">
              <p className="font-medium text-slate-200">{run.scenario_name}</p>
              <p className="mt-1 text-slate-400">
                {run.status} · seed {run.seed}
              </p>
              <p className="mt-1 truncate text-[11px] text-slate-500">{run.run_id}</p>
            </li>
          ))}
        </ul>
      </GlassPanel>
      <GlassPanel title="Persisted incidents">
        <ul className="fs-scroll max-h-[28rem] space-y-2 overflow-y-auto">
          {incidents.length === 0 && (
            <li className="text-xs text-slate-500">No incidents in SQLite memory yet.</li>
          )}
          {incidents.map((incident) => (
            <li key={`${incident.run_id}-${incident.id}`} className="rounded-lg border border-white/5 bg-black/20 px-3 py-2 text-xs">
              <p className="font-medium text-slate-200">
                t={incident.simulation_time} · {incident.event_type} · {incident.tractor_id}
              </p>
              <p className="mt-1 leading-relaxed text-slate-300">{incident.explanation}</p>
              {incident.reassigned_to && (
                <p className="mt-1 text-[var(--fs-emerald)]">Reassigned to {incident.reassigned_to}</p>
              )}
              {incident.blocking_reason && (
                <p className="mt-1 text-[var(--fs-amber)]">Blocked: {incident.blocking_reason}</p>
              )}
            </li>
          ))}
        </ul>
      </GlassPanel>
    </div>
  )
}
