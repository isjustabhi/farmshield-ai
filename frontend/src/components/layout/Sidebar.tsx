import {
  Activity,
  BrainCircuit,
  FlaskConical,
  LayoutDashboard,
  Network,
  Radar,
  ShieldAlert,
  Tractor,
} from 'lucide-react'
import type { AppView } from '../../types/api'

const items: Array<{ id: AppView; label: string; icon: typeof LayoutDashboard }> = [
  { id: 'command', label: 'Command Center', icon: LayoutDashboard },
  { id: 'fleet', label: 'Fleet Monitor', icon: Tractor },
  { id: 'missions', label: 'Mission Queue', icon: Radar },
  { id: 'chaos', label: 'Chaos Lab', icon: FlaskConical },
  { id: 'intelligence', label: 'Fleet Intelligence', icon: BrainCircuit },
  { id: 'agents', label: 'Agent Network', icon: Network },
  { id: 'memory', label: 'Incident Memory', icon: ShieldAlert },
  { id: 'benchmark', label: 'Benchmark Lab', icon: Activity },
]

interface SidebarProps {
  view: AppView
  onChange: (view: AppView) => void
}

export function Sidebar({ view, onChange }: SidebarProps) {
  return (
    <aside className="fs-glass flex w-60 shrink-0 flex-col rounded-none border-y-0 border-l-0">
      <div className="border-b border-white/5 px-5 py-5">
        <div className="flex items-center gap-2 text-[var(--fs-emerald)]">
          <Tractor size={22} strokeWidth={1.8} />
          <div>
            <p className="text-sm font-semibold tracking-wide text-slate-100">FarmShield AI</p>
            <p className="text-[11px] uppercase tracking-[0.16em] text-slate-500">Mission Control</p>
          </div>
        </div>
      </div>
      <nav className="flex flex-1 flex-col gap-1 p-3">
        {items.map((item) => {
          const Icon = item.icon
          const active = view === item.id
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => onChange(item.id)}
              className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm transition ${
                active
                  ? 'bg-[var(--fs-emerald-dim)] text-[var(--fs-emerald)]'
                  : 'text-slate-400 hover:bg-white/5 hover:text-slate-200'
              }`}
            >
              <Icon size={16} />
              {item.label}
            </button>
          )
        })}
      </nav>
    </aside>
  )
}
