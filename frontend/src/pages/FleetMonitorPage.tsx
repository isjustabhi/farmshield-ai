import { FuelGauge } from '../components/ui/FuelGauge'
import { GlassPanel } from '../components/ui/GlassPanel'
import { jobProgressPct } from '../lib/fleetDerived'
import type { SimulationState } from '../types/api'

export function FleetMonitorPage({ state }: { state: SimulationState }) {
  return (
    <GlassPanel title="Fleet Monitor">
      <div className="grid gap-3 md:grid-cols-3">
        {state.tractors.map((tractor) => {
          const job = state.jobs.find((j) => j.id === tractor.assigned_job_id)
          return (
            <article key={tractor.id} className="rounded-xl border border-white/5 bg-black/20 p-4">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <h3 className="font-semibold text-slate-100">{tractor.name}</h3>
                  <p className="text-xs text-slate-400">
                    {tractor.implement_type} · {tractor.status}
                  </p>
                </div>
                <span className="text-[11px] text-slate-500">
                  ({tractor.position.x},{tractor.position.y})
                </span>
              </div>
              <div className="mt-3">
                <FuelGauge level={tractor.fuel_level} capacity={tractor.fuel_capacity} />
              </div>
              <p className="mt-3 text-xs text-slate-400">
                {job
                  ? `${job.id} · ${jobProgressPct(job).toFixed(1)}% · deadline t=${job.deadline_minute}`
                  : 'No assignment'}
              </p>
            </article>
          )
        })}
      </div>
    </GlassPanel>
  )
}
