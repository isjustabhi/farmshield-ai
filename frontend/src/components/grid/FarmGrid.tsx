import { Tractor as TractorIcon } from 'lucide-react'
import { fieldStatus, jobProgressPct, tractorDisplayPosition } from '../../lib/fleetDerived'
import type { FieldModel, Job, SimulationState, Tractor } from '../../types/api'

interface FarmGridProps {
  state: SimulationState
  selectedTractorId: string | null
  selectedFieldId: string | null
  onSelectTractor: (id: string) => void
  onSelectField: (id: string) => void
}

const CELL = 28
const PAD = 24

export function FarmGrid({
  state,
  selectedTractorId,
  selectedFieldId,
  onSelectTractor,
  onSelectField,
}: FarmGridProps) {
  const width = state.grid.width * CELL + PAD * 2
  const height = state.grid.height * CELL + PAD * 2

  return (
    <div className="overflow-auto rounded-lg border border-white/5 bg-[#070d18]">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="h-auto min-h-[420px] w-full"
        role="img"
        aria-label="Farm simulation grid"
      >
        <defs>
          <pattern id="grid" width={CELL} height={CELL} patternUnits="userSpaceOnUse">
            <path
              d={`M ${CELL} 0 L 0 0 0 ${CELL}`}
              fill="none"
              stroke="var(--fs-grid)"
              strokeWidth="1"
            />
          </pattern>
        </defs>
        <rect x={0} y={0} width={width} height={height} fill="#070d18" />
        <rect x={PAD} y={PAD} width={state.grid.width * CELL} height={state.grid.height * CELL} fill="url(#grid)" />

        {/* Depot */}
        <rect
          x={PAD + state.depot.x * CELL + 4}
          y={PAD + state.depot.y * CELL + 4}
          width={CELL - 8}
          height={CELL - 8}
          rx={4}
          fill="rgba(59,130,246,0.25)"
          stroke="rgba(96,165,250,0.7)"
        />
        <text
          x={PAD + state.depot.x * CELL + CELL / 2}
          y={PAD + state.depot.y * CELL + CELL / 2 + 3}
          textAnchor="middle"
          fontSize="8"
          fill="#93c5fd"
        >
          DEPOT
        </text>

        {state.obstacles.map((o) => (
          <rect
            key={`obs-${o.x}-${o.y}`}
            x={PAD + o.x * CELL + 3}
            y={PAD + o.y * CELL + 3}
            width={CELL - 6}
            height={CELL - 6}
            rx={3}
            fill="rgba(239,68,68,0.45)"
            stroke="#f87171"
          />
        ))}

        {state.fields.map((field) => (
          <FieldGlyph
            key={field.id}
            field={field}
            state={state}
            selected={selectedFieldId === field.id}
            onSelect={() => onSelectField(field.id)}
          />
        ))}

        {state.tractors.map((tractor) => (
          <TractorGlyph
            key={tractor.id}
            tractor={tractor}
            jobs={state.jobs}
            selected={selectedTractorId === tractor.id}
            onSelect={() => onSelectTractor(tractor.id)}
          />
        ))}
      </svg>
    </div>
  )
}

function FieldGlyph({
  field,
  state,
  selected,
  onSelect,
}: {
  field: FieldModel
  state: SimulationState
  selected: boolean
  onSelect: () => void
}) {
  const status = fieldStatus(state, field)
  const jobs = state.jobs.filter((j) => j.field_id === field.id)
  const progress =
    jobs.length === 0
      ? 0
      : jobs.reduce((sum, j) => sum + jobProgressPct(j), 0) / jobs.length

  const fill =
    status === 'done'
      ? 'rgba(16,185,129,0.28)'
      : status === 'active'
        ? 'rgba(245,158,11,0.24)'
        : status === 'blocked'
          ? 'rgba(239,68,68,0.2)'
          : 'rgba(148,163,184,0.12)'
  const stroke =
    status === 'done'
      ? '#34d399'
      : status === 'active'
        ? '#fbbf24'
        : status === 'blocked'
          ? '#f87171'
          : '#64748b'

  const x = PAD + field.position.x * CELL - CELL
  const y = PAD + field.position.y * CELL - CELL

  return (
    <g
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') onSelect()
      }}
      className="cursor-pointer"
    >
      <rect
        x={x}
        y={y}
        width={CELL * 3}
        height={CELL * 3}
        rx={8}
        fill={fill}
        stroke={selected ? '#e2e8f0' : stroke}
        strokeWidth={selected ? 2.5 : 1.4}
      />
      <text x={x + 10} y={y + 16} fontSize="9" fill="#e2e8f0" fontWeight={600}>
        {field.name}
      </text>
      <text x={x + 10} y={y + 30} fontSize="8" fill="#94a3b8">
        {status.toUpperCase()} · {progress.toFixed(0)}%
      </text>
      <text x={x + 10} y={y + 42} fontSize="8" fill="#64748b">
        ({field.position.x},{field.position.y})
      </text>
    </g>
  )
}

function TractorGlyph({
  tractor,
  jobs,
  selected,
  onSelect,
}: {
  tractor: Tractor
  jobs: Job[]
  selected: boolean
  onSelect: () => void
}) {
  const display = tractorDisplayPosition(tractor)
  const cx = PAD + display.x * CELL + CELL / 2
  const cy = PAD + display.y * CELL + CELL / 2
  const job = jobs.find((j) => j.id === tractor.assigned_job_id)
  const tone =
    tractor.status === 'broken'
      ? '#ef4444'
      : tractor.status === 'working'
        ? '#10b981'
        : tractor.status === 'traveling'
          ? '#f59e0b'
          : '#94a3b8'

  return (
    <g>
      {tractor.status === 'traveling' && tractor.path.length > 1 && (
        <polyline
          points={tractor.path
            .map((p) => `${PAD + p.x * CELL + CELL / 2},${PAD + p.y * CELL + CELL / 2}`)
            .join(' ')}
          fill="none"
          stroke={tone}
          strokeWidth={1.5}
          opacity={0.55}
          className="fs-path-animate"
        />
      )}
      <g
        role="button"
        tabIndex={0}
        onClick={onSelect}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') onSelect()
        }}
        className="cursor-pointer"
        style={{ transition: 'transform 0.45s linear' }}
      >
        <circle
          cx={cx}
          cy={cy}
          r={selected ? 14 : 12}
          fill="#0f172a"
          stroke={tone}
          strokeWidth={selected ? 2.5 : 1.8}
          className={tractor.status === 'working' ? 'fs-pulse' : undefined}
        />
        <foreignObject x={cx - 8} y={cy - 8} width={16} height={16}>
          <div className="flex h-full w-full items-center justify-center text-slate-100">
            <TractorIcon size={12} color={tone} />
          </div>
        </foreignObject>
        <text x={cx} y={cy + 24} textAnchor="middle" fontSize="8" fill="#cbd5e1">
          {tractor.name.replace('Shield-', '')}
        </text>
        {job && (
          <text x={cx} y={cy + 34} textAnchor="middle" fontSize="7" fill="#64748b">
            {job.id} {jobProgressPct(job).toFixed(0)}%
          </text>
        )}
      </g>
    </g>
  )
}
