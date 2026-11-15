interface FuelGaugeProps {
  level: number
  capacity: number
}

export function FuelGauge({ level, capacity }: FuelGaugeProps) {
  const pct = capacity > 0 ? Math.max(0, Math.min(100, (level / capacity) * 100)) : 0
  const tone =
    pct < 20 ? 'bg-[var(--fs-red)]' : pct < 40 ? 'bg-[var(--fs-amber)]' : 'bg-[var(--fs-emerald)]'

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-xs text-slate-400">
        <span>Fuel</span>
        <span className="font-medium text-slate-200">
          {level.toFixed(1)} / {capacity.toFixed(0)} ({pct.toFixed(0)}%)
        </span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-slate-800">
        <div className={`h-full rounded-full transition-all duration-500 ${tone}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}
