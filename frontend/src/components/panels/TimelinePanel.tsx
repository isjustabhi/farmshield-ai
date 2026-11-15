import { AlertTriangle, History, Shield } from 'lucide-react'
import type { RecoveryLogEntry, SimEvent } from '../../types/api'
import { GlassPanel } from '../ui/GlassPanel'

interface TimelinePanelProps {
  events: SimEvent[]
  recoveryLogs: RecoveryLogEntry[]
}

export function TimelinePanel({ events, recoveryLogs }: TimelinePanelProps) {
  const safetyAlerts = events.filter((e) =>
    ['failure', 'breakdown', 'reassignment'].includes(e.event_type),
  )
  const recoveries = recoveryLogs.filter((l) =>
    ['breakdown', 'repair', 'replan'].includes(l.event_type),
  )

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <GlassPanel title="Event timeline" className="min-h-[220px]">
        <Feed
          empty="No events yet."
          icon={<History size={14} />}
          items={events.slice(0, 12).map((e) => ({
            key: String(e.id),
            title: `t=${e.sim_time} · ${e.event_type}`,
            body: e.message,
            tone: eventTone(e.event_type),
          }))}
        />
      </GlassPanel>

      <GlassPanel title="Safety alerts" className="min-h-[220px]">
        <Feed
          empty="No safety alerts."
          icon={<AlertTriangle size={14} />}
          items={safetyAlerts.slice(0, 10).map((e) => ({
            key: `s-${e.id}`,
            title: `t=${e.sim_time} · ${e.event_type}`,
            body: e.message,
            tone: 'warn',
          }))}
        />
      </GlassPanel>

      <GlassPanel title="Recovery explanations" className="min-h-[220px]">
        <Feed
          empty="No recovery actions yet."
          icon={<Shield size={14} />}
          items={recoveries.slice(0, 10).map((l) => ({
            key: `r-${l.id}`,
            title: `t=${l.sim_time} · ${l.event_type}`,
            body: l.explanation,
            tone: l.feasible ? 'ok' : 'bad',
          }))}
        />
      </GlassPanel>
    </div>
  )
}

function Feed({
  items,
  empty,
  icon,
}: {
  items: Array<{ key: string; title: string; body: string; tone: 'ok' | 'warn' | 'bad' | 'neutral' }>
  empty: string
  icon: React.ReactNode
}) {
  if (items.length === 0) {
    return <p className="text-xs text-slate-500">{empty}</p>
  }
  return (
    <ul className="fs-scroll max-h-52 space-y-2 overflow-y-auto pr-1">
      {items.map((item) => (
        <li key={item.key} className="rounded-lg border border-white/5 bg-black/20 px-3 py-2">
          <p className={`flex items-center gap-1.5 text-[11px] font-medium ${toneClass(item.tone)}`}>
            {icon}
            {item.title}
          </p>
          <p className="mt-1 text-xs leading-relaxed text-slate-300">{item.body}</p>
        </li>
      ))}
    </ul>
  )
}

function eventTone(type: string): 'ok' | 'warn' | 'bad' | 'neutral' {
  if (['failure', 'breakdown'].includes(type)) return 'bad'
  if (['reassignment', 'recovery_plan'].includes(type)) return 'warn'
  if (['completion', 'assignment', 'repair'].includes(type)) return 'ok'
  return 'neutral'
}

function toneClass(tone: 'ok' | 'warn' | 'bad' | 'neutral') {
  if (tone === 'ok') return 'text-[var(--fs-emerald)]'
  if (tone === 'warn') return 'text-[var(--fs-amber)]'
  if (tone === 'bad') return 'text-[var(--fs-red)]'
  return 'text-slate-400'
}
