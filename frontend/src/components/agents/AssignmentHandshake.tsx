import { useEffect, useMemo, useState } from 'react'
import type { AgentTrace } from '../../types/api'

interface HandshakeCycle {
  key: string
  decisionId: string
  simTime: number
  wallTime: number
  tractorId: string | null
  jobId: string | null
  travelTime: number | null
  travelCells: number | null
  nav: AgentTrace | null
  safety: AgentTrace | null
  committed: boolean
  rejected: boolean
}

interface Bubble {
  key: string
  who: string
  text: string
  done: boolean
  mood: 'neutral' | 'ok' | 'bad'
}

/** Compact Fleet → Nav → Safety assignment dialogue from AgentBus traces. */
export function AssignmentHandshake({ traces }: { traces: AgentTrace[] }) {
  const cycles = useMemo(() => buildCycles(traces), [traces])
  const newestKey = cycles[0]?.key ?? null
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const [followLatest, setFollowLatest] = useState(true)

  useEffect(() => {
    if (followLatest && newestKey) setSelectedKey(newestKey)
  }, [newestKey, followLatest])

  const activeKey = followLatest ? newestKey : selectedKey ?? newestKey
  const cycle = cycles.find((c) => c.key === activeKey) ?? cycles[0] ?? null
  const bubbles = cycle ? bubblesForCycle(cycle) : []

  return (
    <div className="rounded-lg border border-white/10 bg-[#0d1524]/80 px-3 py-2.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs font-medium text-slate-200">Assignment handshake</p>
        {cycle ? (
          <p className="text-[11px] text-slate-500">
            {friendlyTractor(cycle.tractorId)}
            {cycle.jobId ? ` · ${friendlyJob(cycle.jobId)}` : ''} · min {cycle.simTime}
            {cycle.rejected ? ' · held' : cycle.committed ? ' · sent' : ''}
          </p>
        ) : (
          <p className="text-[11px] text-slate-500">Run Schedule to generate traces</p>
        )}
      </div>

      {cycles.length > 1 && (
        <div className="mt-1.5 flex flex-wrap gap-1">
          <button
            type="button"
            className={`rounded px-1.5 py-0.5 text-[10px] ${
              followLatest ? 'bg-emerald-500/20 text-emerald-200' : 'text-slate-500'
            }`}
            onClick={() => setFollowLatest(true)}
          >
            Latest
          </button>
          {cycles.slice(0, 4).map((c) => (
            <button
              key={c.key}
              type="button"
              className={`rounded px-1.5 py-0.5 text-[10px] ${
                c.key === activeKey ? 'bg-white/10 text-slate-200' : 'text-slate-500'
              }`}
              onClick={() => {
                setFollowLatest(false)
                setSelectedKey(c.key)
              }}
            >
              {friendlyTractor(c.tractorId)} · {c.simTime}
            </button>
          ))}
        </div>
      )}

      {!cycle ? (
        <p className="mt-2 text-[11px] text-slate-500">
          Fleet → Navigation → Safety → commit.
        </p>
      ) : (
        <ul className="mt-2 max-h-40 space-y-1.5 overflow-y-auto fs-scroll">
          {bubbles.map((b) => (
            <li
              key={`${cycle.key}-${b.key}`}
              className={`rounded-md px-2 py-1.5 text-[11px] leading-snug ${
                b.done ? 'bg-[#152238] text-slate-200' : 'bg-black/20 text-slate-500'
              } ${
                b.mood === 'ok' && b.done
                  ? 'ring-1 ring-emerald-500/30'
                  : b.mood === 'bad' && b.done
                    ? 'ring-1 ring-red-400/35'
                    : ''
              }`}
            >
              <span className="font-medium text-slate-400">{b.who}: </span>
              {b.text}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function friendlyTractor(id: string | null | undefined): string {
  if (!id) return 'Tractor'
  const m = id.match(/(\d+)/)
  return m ? `Tractor ${Number(m[1])}` : id.replace(/_/g, ' ')
}

function friendlyJob(id: string | null | undefined): string | null {
  if (!id) return null
  const m = id.match(/(\d+)/)
  return m ? `job ${Number(m[1])}` : id.replace(/_/g, ' ')
}

function bubblesForCycle(cycle: HandshakeCycle): Bubble[] {
  const tractor = friendlyTractor(cycle.tractorId)
  const job = friendlyJob(cycle.jobId) ?? 'that job'
  const navOk = cycle.nav ? !['rejected', 'error'].includes(cycle.nav.status) : false
  const pathBit =
    cycle.travelCells != null && cycle.travelTime != null
      ? `${cycle.travelCells} cells, ~${Math.round(cycle.travelTime)} min travel.`
      : 'Path and fuel look fine.'

  return [
    {
      key: 'ask_nav',
      who: 'Fleet',
      text: `Nav, can you get ${tractor} on ${job}?`,
      done: Boolean(cycle.nav),
      mood: 'neutral',
    },
    {
      key: 'nav_reply',
      who: 'Nav',
      text: navOk ? `Yes. ${pathBit}` : 'No route from here.',
      done: Boolean(cycle.nav),
      mood: navOk ? 'ok' : 'bad',
    },
    {
      key: 'ask_safety',
      who: 'Fleet',
      text: navOk ? `Safety — clear to assign ${tractor}?` : 'Holding — Nav can’t reach it.',
      done: Boolean(cycle.safety) || (Boolean(cycle.nav) && !navOk),
      mood: 'neutral',
    },
    {
      key: 'safety_reply',
      who: 'Safety',
      text: cycle.rejected
        ? 'No. Don’t send them.'
        : cycle.committed
          ? cycle.safety?.status === 'ok_with_lateness'
            ? 'Yes, even if they finish late.'
            : 'Yes. Send them.'
          : 'Standing by…',
      done: Boolean(cycle.safety),
      mood: cycle.rejected ? 'bad' : cycle.committed ? 'ok' : 'neutral',
    },
    {
      key: 'commit',
      who: 'Fleet',
      text: cycle.committed
        ? `${tractor} is on ${job}.`
        : cycle.rejected
          ? 'Holding that assign.'
          : 'Waiting on Safety.',
      done: cycle.committed || cycle.rejected,
      mood: cycle.committed ? 'ok' : cycle.rejected ? 'bad' : 'neutral',
    },
  ]
}

function buildCycles(traces: AgentTrace[]): HandshakeCycle[] {
  const chronological = [...traces].reverse()
  const byDecision = new Map<string, { nav: AgentTrace | null; safety: AgentTrace | null }>()

  for (const t of chronological) {
    const isNav =
      t.request_type === 'RouteRequest' ||
      (t.receiver.includes('navigation') && t.sender.includes('fleet'))
    const isSafety =
      t.request_type === 'SafetyValidationRequest' ||
      (t.receiver.includes('safety') && t.sender.includes('fleet'))
    if (!isNav && !isSafety) continue

    const key =
      t.decision_id != null && String(t.decision_id) !== ''
        ? `d:${t.decision_id}`
        : `c:${t.correlation_id}`

    const slot = byDecision.get(key) ?? { nav: null, safety: null }
    if (isNav) slot.nav = t
    if (isSafety) slot.safety = t
    byDecision.set(key, slot)
  }

  const cycles: HandshakeCycle[] = []
  for (const [key, slot] of byDecision) {
    const anchor = slot.safety ?? slot.nav
    if (!anchor) continue
    const ids = extractIds(slot.nav) ?? extractIds(slot.safety)
    const route = extractRoute(slot.nav)
    const safetyApproved =
      !!slot.safety &&
      (slot.safety.status === 'ok' || slot.safety.status === 'ok_with_lateness')
    const rejected =
      !!slot.safety &&
      (slot.safety.status === 'rejected' || slot.safety.status === 'error')

    cycles.push({
      key,
      decisionId: String(anchor.decision_id ?? key.replace(/^d:/, '')),
      simTime: anchor.simulation_timestamp,
      wallTime: anchor.end_wall_time ?? anchor.start_wall_time ?? 0,
      tractorId: ids?.tractorId ?? null,
      jobId: ids?.jobId ?? null,
      travelTime: route?.travelTime ?? null,
      travelCells: route?.travelCells ?? null,
      nav: slot.nav,
      safety: slot.safety,
      committed: safetyApproved,
      rejected,
    })
  }

  cycles.sort((a, b) => {
    if (a.wallTime !== b.wallTime) return b.wallTime - a.wallTime
    const an = Number(a.decisionId)
    const bn = Number(b.decisionId)
    if (!Number.isNaN(an) && !Number.isNaN(bn)) return bn - an
    return b.simTime - a.simTime
  })

  return cycles
}

function extractIds(
  trace: AgentTrace | null,
): { tractorId: string; jobId: string } | null {
  if (!trace?.detail) return null
  const req = trace.detail.request
  if (!req || typeof req !== 'object') return null
  const r = req as Record<string, unknown>
  if (typeof r.tractor_id === 'string' && typeof r.job_id === 'string') {
    return { tractorId: r.tractor_id, jobId: r.job_id }
  }
  const proposal = r.proposal
  if (proposal && typeof proposal === 'object') {
    const p = proposal as Record<string, unknown>
    if (typeof p.tractor_id === 'string' && typeof p.job_id === 'string') {
      return { tractorId: p.tractor_id, jobId: p.job_id }
    }
  }
  return null
}

function extractRoute(
  trace: AgentTrace | null,
): { travelTime: number; travelCells: number } | null {
  if (!trace?.detail) return null
  const res = trace.detail.response
  if (!res || typeof res !== 'object') return null
  const r = res as Record<string, unknown>
  const travelTime = typeof r.travel_time === 'number' ? r.travel_time : null
  const travelCells = typeof r.travel_cells === 'number' ? r.travel_cells : null
  if (travelTime == null || travelCells == null) return null
  return { travelTime, travelCells }
}
