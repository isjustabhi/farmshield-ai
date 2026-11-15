import { AlertTriangle, Info } from 'lucide-react'
import { deadlineTone, jobProgressPct, latestDecisionFor } from '../../lib/fleetDerived'
import type { AssignmentDecision, Job, SimulationState, Tractor } from '../../types/api'
import { FuelGauge } from '../ui/FuelGauge'
import { GlassPanel } from '../ui/GlassPanel'

interface DetailsPanelProps {
  state: SimulationState
  tractor: Tractor | null
  decisions: AssignmentDecision[]
  onBreakdown: (tractorId: string) => void
  onRepair: (tractorId: string) => void
  onInspectJob: (jobId: string) => void
  busy: boolean
}

export function DetailsPanel({
  state,
  tractor,
  decisions,
  onBreakdown,
  onRepair,
  onInspectJob,
  busy,
}: DetailsPanelProps) {
  if (!tractor) {
    return (
      <GlassPanel title="Selection details" className="h-full">
        <p className="text-sm text-slate-400">
          Select a tractor or field on the grid to inspect live assignment data.
        </p>
      </GlassPanel>
    )
  }

  const job = state.jobs.find((j) => j.id === tractor.assigned_job_id) ?? null
  const decision = latestDecisionFor(decisions, tractor.id, tractor.assigned_job_id) as
    | AssignmentDecision
    | undefined
  const field = job ? state.fields.find((f) => f.id === job.field_id) : null

  return (
    <GlassPanel
      title="Selection details"
      className="h-full"
      action={
        <div className="flex gap-2">
          {tractor.status === 'broken' ? (
            <button
              type="button"
              disabled={busy}
              onClick={() => onRepair(tractor.id)}
              className="rounded-md bg-[var(--fs-emerald)] px-2 py-1 text-[11px] font-semibold text-slate-950 disabled:opacity-40"
            >
              Repair
            </button>
          ) : (
            <button
              type="button"
              disabled={busy}
              onClick={() => onBreakdown(tractor.id)}
              className="rounded-md bg-[var(--fs-red)]/90 px-2 py-1 text-[11px] font-semibold text-white disabled:opacity-40"
            >
              Break Tractor
            </button>
          )}
        </div>
      }
    >
      <div className="space-y-4 text-sm">
        <div>
          <p className="text-lg font-semibold text-slate-100">{tractor.name}</p>
          <p className="text-xs text-slate-400">
            {tractor.id} · <StatusPill status={tractor.status} />
          </p>
        </div>

        <dl className="grid grid-cols-2 gap-3 text-xs">
          <Item label="Equipment" value={tractor.implement_type} />
          <Item label="Position" value={`(${tractor.position.x}, ${tractor.position.y})`} />
          <Item label="Travel speed" value={`${tractor.travel_speed} cells/min`} />
          <Item label="Work speed" value={`${tractor.working_speed} units/min`} />
        </dl>

        <FuelGauge level={tractor.fuel_level} capacity={tractor.fuel_capacity} />

        {job ? (
          <div className="space-y-2 rounded-lg border border-white/5 bg-black/20 p-3">
            <div className="flex items-center justify-between gap-2">
              <p className="font-medium text-slate-100">Job {job.id}</p>
              <button
                type="button"
                onClick={() => onInspectJob(job.id)}
                className="text-[11px] text-[var(--fs-emerald)] hover:underline"
              >
                Inspect job
              </button>
            </div>
            <p className="text-xs text-slate-400">
              {job.job_type} · {field?.name ?? job.field_id} · priority {job.priority}
            </p>
            <ProgressBar pct={jobProgressPct(job)} />
            <DeadlineRow job={job} simTime={state.sim_time} />
            <p className="text-xs text-slate-400">
              Work units {job.completed_work_units.toFixed(2)} / {job.estimated_work_units.toFixed(2)}
            </p>
          </div>
        ) : (
          <p className="rounded-lg border border-dashed border-white/10 px-3 py-4 text-xs text-slate-500">
            No active job assignment.
          </p>
        )}

        <div className="space-y-2 rounded-lg border border-white/5 bg-black/20 p-3">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
            <Info size={12} />
            Why this assignment?
          </div>
          {decision ? (
            <>
              <p className="text-xs leading-relaxed text-slate-300">{decision.selection_reason}</p>
              <dl className="grid grid-cols-2 gap-2 text-[11px] text-slate-400">
                <Item label="Travel est." value={`${decision.estimated_travel_time.toFixed(1)}m`} />
                <Item label="Work est." value={`${decision.estimated_work_time.toFixed(1)}m`} />
                <Item label="Fuel est." value={decision.estimated_fuel_used.toFixed(1)} />
                <Item label="Finish" value={`t=${decision.predicted_finish.toFixed(1)}`} />
                <Item label="Deadline margin" value={decision.deadline_margin.toFixed(1)} />
                <Item label="Score" value={decision.score_components.total.toFixed(1)} />
              </dl>
              <ConstraintHints decision={decision} />
            </>
          ) : (
            <p className="text-xs text-slate-500">
              No fleet-agent decision recorded for the current assignment yet. Run Schedule Jobs.
            </p>
          )}
        </div>
      </div>
    </GlassPanel>
  )
}

function ConstraintHints({ decision }: { decision: AssignmentDecision }) {
  const late = decision.deadline_margin < 0
  return (
    <ul className="space-y-1 text-[11px]">
      <li className="text-[var(--fs-emerald)]">✓ Validated via Safety Agent before commit</li>
      <li className="text-[var(--fs-emerald)]">✓ Route + fuel estimates from Navigation Agent</li>
      {late ? (
        <li className="flex items-center gap-1 text-[var(--fs-amber)]">
          <AlertTriangle size={11} />
          Unavoidable lateness reported (margin {decision.deadline_margin.toFixed(1)})
        </li>
      ) : (
        <li className="text-[var(--fs-emerald)]">✓ Deadline currently feasible</li>
      )}
    </ul>
  )
}

function DeadlineRow({ job, simTime }: { job: Job; simTime: number }) {
  const tone = deadlineTone(job, simTime)
  const color =
    tone === 'late' ? 'text-[var(--fs-red)]' : tone === 'warn' ? 'text-[var(--fs-amber)]' : 'text-slate-300'
  return (
    <p className={`text-xs ${color}`}>
      Deadline t={job.deadline_minute} · remaining {job.deadline_minute - simTime}m
    </p>
  )
}

function ProgressBar({ pct }: { pct: number }) {
  return (
    <div>
      <div className="mb-1 flex justify-between text-[11px] text-slate-400">
        <span>Progress</span>
        <span>{pct.toFixed(1)}%</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-slate-800">
        <div
          className="h-full rounded-full bg-[var(--fs-emerald)] transition-all duration-500"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}

function Item({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[10px] uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className="mt-0.5 text-slate-200">{value}</dd>
    </div>
  )
}

function StatusPill({ status }: { status: string }) {
  const tone =
    status === 'broken'
      ? 'text-[var(--fs-red)]'
      : status === 'working'
        ? 'text-[var(--fs-emerald)]'
        : status === 'traveling'
          ? 'text-[var(--fs-amber)]'
          : 'text-slate-300'
  return <span className={tone}>{status}</span>
}
