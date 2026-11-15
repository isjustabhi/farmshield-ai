import { useMemo, useState } from 'react'
import { FarmGrid } from '../components/grid/FarmGrid'
import { GlassPanel } from '../components/ui/GlassPanel'
import type {
  AgentTrace,
  ChaosEventResult,
  RecoveryLogEntry,
  SimEvent,
  SimulationState,
} from '../types/api'

interface ChaosLabPageProps {
  state: SimulationState
  busy: boolean
  events: SimEvent[]
  recoveryLogs: RecoveryLogEntry[]
  traces: AgentTrace[]
  lastChaos: ChaosEventResult | null
  onBreakdown: (id: string) => void
  onRepair: (id: string) => void
  onReset: () => void
  onBlock: (x: number, y: number) => void
  onUnblock: (x: number, y: number) => void
  onPriority: (jobId: string, priority: number) => void
  onFuel: (tractorId: string, fuel: number) => void
  onRandom: (seed?: number) => void
}

export function ChaosLabPage({
  state,
  busy,
  events,
  recoveryLogs,
  traces,
  lastChaos,
  onBreakdown,
  onRepair,
  onReset,
  onBlock,
  onUnblock,
  onPriority,
  onFuel,
  onRandom,
}: ChaosLabPageProps) {
  const [tractorId, setTractorId] = useState(state.tractors[0]?.id ?? '')
  const [jobId, setJobId] = useState(state.jobs.find((j) => j.status !== 'completed')?.id ?? '')
  const [priority, setPriority] = useState(1)
  const [blockX, setBlockX] = useState(5)
  const [blockY, setBlockY] = useState(5)
  const [fuel, setFuel] = useState(8)
  const [seed, setSeed] = useState(42)
  const [selectedTractorId, setSelectedTractorId] = useState<string | null>(null)
  const [selectedFieldId, setSelectedFieldId] = useState<string | null>(null)

  const selectedTractor = useMemo(
    () => state.tractors.find((t) => t.id === tractorId) ?? state.tractors[0],
    [state.tractors, tractorId],
  )

  return (
    <div className="space-y-4">
      <div className="grid gap-4 xl:grid-cols-[300px_minmax(0,1.2fr)_340px]">
        <GlassPanel title="Event selection">
          <div className="space-y-3 text-xs">
            <Field label="Tractor">
              <select
                className="w-full rounded-md border border-white/10 bg-black/30 px-2 py-1.5"
                value={tractorId}
                onChange={(e) => setTractorId(e.target.value)}
              >
                {state.tractors.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name} ({t.status})
                  </option>
                ))}
              </select>
            </Field>

            <div className="grid grid-cols-2 gap-2">
              <Action disabled={busy || selectedTractor?.status === 'broken'} onClick={() => onBreakdown(tractorId)}>
                Break tractor
              </Action>
              <Action disabled={busy || selectedTractor?.status !== 'broken'} onClick={() => onRepair(tractorId)}>
                Repair tractor
              </Action>
            </div>

            <Field label={`Block cell (${blockX},{blockY})`}>
              <div className="flex gap-2">
                <Num value={blockX} set={setBlockX} max={state.grid.width - 1} />
                <Num value={blockY} set={setBlockY} max={state.grid.height - 1} />
              </div>
            </Field>
            <div className="grid grid-cols-2 gap-2">
              <Action disabled={busy} onClick={() => onBlock(blockX, blockY)}>
                Block route
              </Action>
              <Action disabled={busy} onClick={() => onUnblock(blockX, blockY)}>
                Unblock
              </Action>
            </div>

            <Field label="Job priority">
              <select
                className="mb-2 w-full rounded-md border border-white/10 bg-black/30 px-2 py-1.5"
                value={jobId}
                onChange={(e) => setJobId(e.target.value)}
              >
                {state.jobs.map((j) => (
                  <option key={j.id} value={j.id}>
                    {j.id} p={j.priority} ({j.status})
                  </option>
                ))}
              </select>
              <div className="flex gap-2">
                <Num value={priority} set={setPriority} min={1} max={10} />
                <Action disabled={busy} onClick={() => onPriority(jobId, priority)}>
                  Apply priority
                </Action>
              </div>
            </Field>

            <Field label="Idle tractor fuel">
              <div className="flex gap-2">
                <Num value={fuel} set={setFuel} min={0} max={100} />
                <Action disabled={busy} onClick={() => onFuel(tractorId, fuel)}>
                  Set fuel
                </Action>
              </div>
            </Field>

            <Field label="Random chaos seed">
              <div className="flex gap-2">
                <Num value={seed} set={setSeed} min={1} max={999999} />
                <Action disabled={busy} onClick={() => onRandom(seed)}>
                  Trigger random
                </Action>
              </div>
            </Field>

            <Action disabled={busy} onClick={onReset} tone="amber">
              Reset scenario
            </Action>
          </div>
        </GlassPanel>

        <GlassPanel title="Live farm map" action={<span className="text-[11px] text-slate-500">{state.obstacles.length} blocks</span>}>
          <FarmGrid
            state={state}
            selectedTractorId={selectedTractorId}
            selectedFieldId={selectedFieldId}
            onSelectTractor={setSelectedTractorId}
            onSelectField={setSelectedFieldId}
          />
        </GlassPanel>

        <GlassPanel title="Before vs After plan">
          {!lastChaos ? (
            <p className="text-xs text-slate-500">Trigger a chaos event to compare plans.</p>
          ) : (
            <div className="space-y-3 text-xs">
              <p className="rounded-lg border border-[var(--fs-amber)]/30 bg-[var(--fs-amber-dim)] px-3 py-2 text-[var(--fs-amber)]">
                Detected: {lastChaos.event_type}
                {lastChaos.seed != null ? ` · seed ${lastChaos.seed}` : ''}
              </p>
              <p className="leading-relaxed text-slate-300">{lastChaos.explanation}</p>
              <KV label="Why it changed" value={lastChaos.why_changed} />
              <KV label="Estimated outcome" value={lastChaos.estimated_outcome} />
              <KV
                label="Affected jobs"
                value={lastChaos.affected_jobs.join(', ') || 'none'}
              />
              <KV
                label="Preserved work"
                value={
                  Object.entries(lastChaos.preserved_work)
                    .map(([k, v]) => `${k}=${v.toFixed(2)}`)
                    .join(', ') || 'none'
                }
              />
              <KV
                label="Unreachable"
                value={lastChaos.unreachable_jobs.join(', ') || 'none'}
              />
              <CompareTable title="Before" rows={lastChaos.before_assignments} />
              <CompareTable title="After" rows={lastChaos.after_assignments} />
              <div>
                <p className="mb-1 text-[10px] uppercase tracking-wide text-slate-500">Safety checks</p>
                <ul className="space-y-1 text-slate-300">
                  {lastChaos.safety_notes.map((n) => (
                    <li key={n}>✓ {n}</li>
                  ))}
                </ul>
              </div>
            </div>
          )}
        </GlassPanel>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <GlassPanel title="Event timeline">
          <Feed
            items={events.slice(0, 12).map((e) => ({
              key: String(e.id),
              title: `t=${e.sim_time} · ${e.event_type}`,
              body: e.message,
            }))}
          />
        </GlassPanel>
        <GlassPanel title="Recovery / safety">
          <Feed
            items={recoveryLogs.slice(0, 10).map((l) => ({
              key: `r-${l.id}`,
              title: `t=${l.sim_time} · ${l.event_type}`,
              body: l.explanation,
            }))}
          />
        </GlassPanel>
        <GlassPanel title="Agent trace">
          <Feed
            items={traces.slice(0, 12).map((t, i) => ({
              key: `${t.correlation_id}-${i}`,
              title: `${t.sender} → ${t.receiver}`,
              body: `${t.request_type} · ${t.status} · ${t.duration_ms.toFixed(2)}ms`,
            }))}
          />
        </GlassPanel>
      </div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="text-[10px] uppercase tracking-wide text-slate-500">{label}</span>
      {children}
    </label>
  )
}

function Num({
  value,
  set,
  min = 0,
  max = 100,
}: {
  value: number
  set: (n: number) => void
  min?: number
  max?: number
}) {
  return (
    <input
      type="number"
      className="w-full rounded-md border border-white/10 bg-black/30 px-2 py-1.5"
      value={value}
      min={min}
      max={max}
      onChange={(e) => set(Number(e.target.value))}
    />
  )
}

function Action({
  children,
  onClick,
  disabled,
  tone = 'default',
}: {
  children: React.ReactNode
  onClick: () => void
  disabled?: boolean
  tone?: 'default' | 'amber'
}) {
  const cls =
    tone === 'amber'
      ? 'bg-[var(--fs-amber)] text-slate-950'
      : 'border border-white/10 bg-white/5 text-slate-200 hover:bg-white/10'
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={`rounded-md px-3 py-2 text-xs font-semibold disabled:opacity-40 ${cls}`}
    >
      {children}
    </button>
  )
}

function KV({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-0.5 leading-relaxed text-slate-200">{value}</p>
    </div>
  )
}

function CompareTable({
  title,
  rows,
}: {
  title: string
  rows: ChaosEventResult['before_assignments']
}) {
  return (
    <div>
      <p className="mb-1 text-[10px] uppercase tracking-wide text-slate-500">{title}</p>
      {rows.length === 0 ? (
        <p className="text-slate-500">No active assignments</p>
      ) : (
        <ul className="space-y-1">
          {rows.map((r) => (
            <li key={`${title}-${r.job_id}`} className="rounded border border-white/5 bg-black/20 px-2 py-1">
              {r.job_id} → {r.tractor_id ?? 'none'} · {r.status} · {r.percent_complete.toFixed(0)}%
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function Feed({ items }: { items: Array<{ key: string; title: string; body: string }> }) {
  if (items.length === 0) return <p className="text-xs text-slate-500">No entries.</p>
  return (
    <ul className="fs-scroll max-h-56 space-y-2 overflow-y-auto text-xs">
      {items.map((item) => (
        <li key={item.key} className="rounded-lg border border-white/5 bg-black/20 px-3 py-2">
          <p className="font-medium text-slate-200">{item.title}</p>
          <p className="mt-1 text-slate-400">{item.body}</p>
        </li>
      ))}
    </ul>
  )
}
