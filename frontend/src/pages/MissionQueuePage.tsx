import { GlassPanel } from '../components/ui/GlassPanel'
import { deadlineTone, jobProgressPct } from '../lib/fleetDerived'
import type { SimulationState } from '../types/api'

export function MissionQueuePage({ state }: { state: SimulationState }) {
  const jobs = [...state.jobs].sort((a, b) => a.priority - b.priority || a.deadline_minute - b.deadline_minute)
  return (
    <GlassPanel title="Mission Queue">
      <div className="overflow-x-auto">
        <table className="min-w-full text-left text-xs">
          <thead className="text-[10px] uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-2 py-2">Job</th>
              <th className="px-2 py-2">Field</th>
              <th className="px-2 py-2">Type</th>
              <th className="px-2 py-2">Status</th>
              <th className="px-2 py-2">Owner</th>
              <th className="px-2 py-2">Progress</th>
              <th className="px-2 py-2">Deadline</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((job) => {
              const tone = deadlineTone(job, state.sim_time)
              return (
                <tr key={job.id} className="border-t border-white/5 text-slate-300">
                  <td className="px-2 py-2 font-medium text-slate-100">{job.id}</td>
                  <td className="px-2 py-2">{job.field_id}</td>
                  <td className="px-2 py-2">{job.job_type}</td>
                  <td className="px-2 py-2">{job.status}</td>
                  <td className="px-2 py-2">{job.assigned_tractor_id ?? '—'}</td>
                  <td className="px-2 py-2">{jobProgressPct(job).toFixed(1)}%</td>
                  <td
                    className={`px-2 py-2 ${
                      tone === 'late'
                        ? 'text-[var(--fs-red)]'
                        : tone === 'warn'
                          ? 'text-[var(--fs-amber)]'
                          : ''
                    }`}
                  >
                    t={job.deadline_minute}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </GlassPanel>
  )
}
