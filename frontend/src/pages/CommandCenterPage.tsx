import { useMemo, useState } from 'react'
import { AgentDashboard } from '../components/agents/AgentDashboard'
import { FarmGrid } from '../components/grid/FarmGrid'
import { DetailsPanel } from '../components/panels/DetailsPanel'
import { TimelinePanel } from '../components/panels/TimelinePanel'
import { GlassPanel } from '../components/ui/GlassPanel'
import { jobProgressPct } from '../lib/fleetDerived'
import type {
  AgentTrace,
  AssignmentDecision,
  IncidentDialogue,
  LlmAgentStatus,
  SimulationState,
} from '../types/api'

interface CommandCenterPageProps {
  state: SimulationState
  decisions: AssignmentDecision[]
  events: Parameters<typeof TimelinePanel>[0]['events']
  recoveryLogs: Parameters<typeof TimelinePanel>[0]['recoveryLogs']
  traces: AgentTrace[]
  dialogues: IncidentDialogue[]
  llmStatus: LlmAgentStatus | null
  busy: boolean
  onBreakdown: (id: string) => void
  onRepair: (id: string) => void
}

export function CommandCenterPage({
  state,
  decisions,
  events,
  recoveryLogs,
  traces,
  dialogues,
  llmStatus,
  busy,
  onBreakdown,
  onRepair,
}: CommandCenterPageProps) {
  const [selectedTractorId, setSelectedTractorId] = useState<string | null>(
    state.tractors[0]?.id ?? null,
  )
  const [selectedFieldId, setSelectedFieldId] = useState<string | null>(null)
  const [inspectedJobId, setInspectedJobId] = useState<string | null>(null)

  const selectedTractor = useMemo(
    () => state.tractors.find((t) => t.id === selectedTractorId) ?? null,
    [state.tractors, selectedTractorId],
  )

  const inspectedJob = state.jobs.find((j) => j.id === inspectedJobId) ?? null

  return (
    <div className="space-y-4">
      <AgentDashboard
        traces={traces}
        dialogues={dialogues}
        llmStatus={llmStatus}
        compact
      />

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.6fr)_minmax(320px,0.9fr)]">
        <GlassPanel
          title="Live farm grid"
          action={
            <p className="text-[11px] text-slate-500">
              {state.fields.length} fields · {state.tractors.length} tractors · seed {state.seed}
            </p>
          }
        >
          <FarmGrid
            state={state}
            selectedTractorId={selectedTractorId}
            selectedFieldId={selectedFieldId}
            onSelectTractor={(id) => {
              setSelectedTractorId(id)
              const tractor = state.tractors.find((t) => t.id === id)
              if (tractor?.assigned_job_id) {
                const job = state.jobs.find((j) => j.id === tractor.assigned_job_id)
                if (job) setSelectedFieldId(job.field_id)
              }
            }}
            onSelectField={(id) => {
              setSelectedFieldId(id)
              const assigned = state.tractors.find((t) => {
                const job = state.jobs.find((j) => j.id === t.assigned_job_id)
                return job?.field_id === id
              })
              if (assigned) setSelectedTractorId(assigned.id)
            }}
          />
          <div className="mt-3 flex flex-wrap gap-3 text-[11px] text-slate-400">
            <Legend swatch="rgba(16,185,129,0.5)" label="Completed field" />
            <Legend swatch="rgba(245,158,11,0.5)" label="Active field" />
            <Legend swatch="rgba(239,68,68,0.45)" label="Blocked / risk" />
            <Legend swatch="#10b981" label="Working tractor" />
            <Legend swatch="#f59e0b" label="Traveling" />
            <Legend swatch="#ef4444" label="Broken" />
          </div>
        </GlassPanel>

        <DetailsPanel
          state={state}
          tractor={selectedTractor}
          decisions={decisions}
          busy={busy}
          onBreakdown={onBreakdown}
          onRepair={onRepair}
          onInspectJob={setInspectedJobId}
        />
      </div>

      {inspectedJob && (
        <GlassPanel
          title={`Inspect job ${inspectedJob.id}`}
          action={
            <button
              type="button"
              className="text-[11px] text-slate-400 hover:text-slate-200"
              onClick={() => setInspectedJobId(null)}
            >
              Close
            </button>
          }
        >
          <div className="grid gap-3 sm:grid-cols-4 text-xs">
            <Meta label="Type" value={inspectedJob.job_type} />
            <Meta label="Status" value={inspectedJob.status} />
            <Meta label="Progress" value={`${jobProgressPct(inspectedJob).toFixed(1)}%`} />
            <Meta
              label="Owner"
              value={inspectedJob.assigned_tractor_id ?? 'unassigned'}
            />
            <Meta label="Field" value={inspectedJob.field_id} />
            <Meta label="Priority" value={String(inspectedJob.priority)} />
            <Meta label="Deadline" value={`t=${inspectedJob.deadline_minute}`} />
            <Meta
              label="Work units"
              value={`${inspectedJob.completed_work_units.toFixed(2)} / ${inspectedJob.estimated_work_units.toFixed(2)}`}
            />
          </div>
        </GlassPanel>
      )}

      <TimelinePanel events={events} recoveryLogs={recoveryLogs} />
    </div>
  )
}

function Legend({ swatch, label }: { swatch: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: swatch }} />
      {label}
    </span>
  )
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-white/5 bg-black/20 px-3 py-2">
      <p className="text-[10px] uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-1 text-slate-200">{value}</p>
    </div>
  )
}
