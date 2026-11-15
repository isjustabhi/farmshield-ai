import {
  CheckCircle2,
  Pause,
  Play,
  RotateCcw,
  SkipForward,
  Tractor,
  Wifi,
  WifiOff,
} from 'lucide-react'
import type { AgOpenWebIntegration, ApiConnectionState, SimulationState } from '../../types/api'

interface TopNavProps {
  connection: ApiConnectionState
  agopenweb: AgOpenWebIntegration | null
  state: SimulationState | null
  busy: boolean
  onPlay: () => void
  onPause: () => void
  onStep: () => void
  onReset: () => void
  onSchedule: () => void
}

export function TopNav({
  connection,
  agopenweb,
  state,
  busy,
  onPlay,
  onPause,
  onStep,
  onReset,
  onSchedule,
}: TopNavProps) {
  const activeTractors =
    state?.tractors.filter((t) => t.status === 'traveling' || t.status === 'working').length ?? 0
  const completed = state?.jobs.filter((j) => j.status === 'completed').length ?? 0
  const healthOk = connection === 'connected'

  return (
    <header className="fs-glass flex flex-wrap items-center gap-4 rounded-none border-x-0 border-t-0 px-5 py-3">
      <div className="min-w-[160px]">
        <p className="text-sm font-semibold text-slate-100">FarmShield AI</p>
        <p className="text-[11px] uppercase tracking-[0.14em] text-slate-500">
          ATC Run the Fleet
        </p>
      </div>

      <div className="flex flex-1 flex-wrap items-center gap-3 text-xs">
        <Metric label="Sim time" value={state ? `t=${state.sim_time}m` : '—'} />
        <Metric
          label="System"
          value={healthOk ? 'Healthy' : 'Offline'}
          icon={healthOk ? <Wifi size={12} /> : <WifiOff size={12} />}
          tone={healthOk ? 'ok' : 'bad'}
        />
        <Metric
          label="AgOpenWeb"
          value={
            agopenweb?.status === 'connected'
              ? 'Connected'
              : agopenweb?.status === 'disconnected'
                ? 'Disconnected'
                : 'Unsupported'
          }
          tone={
            agopenweb?.status === 'connected'
              ? 'ok'
              : agopenweb?.status === 'disconnected'
                ? 'bad'
                : 'neutral'
          }
          title={agopenweb?.message}
        />
        <Metric
          label="Active"
          value={`${activeTractors}`}
          icon={<Tractor size={12} />}
        />
        <Metric
          label="Completed"
          value={`${completed}/${state?.jobs.length ?? 0}`}
          icon={<CheckCircle2 size={12} />}
        />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <ControlButton disabled={busy || !!state?.playing} onClick={onPlay} icon={<Play size={14} />} label="Start" />
        <ControlButton disabled={busy || !state?.playing} onClick={onPause} icon={<Pause size={14} />} label="Pause" />
        <ControlButton disabled={busy} onClick={onStep} icon={<SkipForward size={14} />} label="Advance" />
        <ControlButton disabled={busy} onClick={onReset} icon={<RotateCcw size={14} />} label="Reset" />
        <button
          type="button"
          disabled={busy}
          onClick={onSchedule}
          className="rounded-lg bg-[var(--fs-emerald)] px-3 py-2 text-xs font-semibold text-slate-950 transition hover:brightness-110 disabled:opacity-50"
        >
          Schedule Jobs
        </button>
      </div>
    </header>
  )
}

function Metric({
  label,
  value,
  icon,
  tone = 'neutral',
  title,
}: {
  label: string
  value: string
  icon?: React.ReactNode
  tone?: 'neutral' | 'ok' | 'bad'
  title?: string
}) {
  const color =
    tone === 'ok' ? 'text-[var(--fs-emerald)]' : tone === 'bad' ? 'text-[var(--fs-red)]' : 'text-slate-200'
  return (
    <div className="rounded-lg border border-white/5 bg-black/20 px-3 py-2" title={title}>
      <p className="text-[10px] uppercase tracking-wide text-slate-500">{label}</p>
      <p className={`mt-0.5 flex items-center gap-1.5 font-medium ${color}`}>
        {icon}
        {value}
      </p>
    </div>
  )
}

function ControlButton({
  label,
  icon,
  onClick,
  disabled,
}: {
  label: string
  icon: React.ReactNode
  onClick: () => void
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-xs text-slate-200 transition hover:bg-white/10 disabled:opacity-40"
    >
      {icon}
      {label}
    </button>
  )
}
