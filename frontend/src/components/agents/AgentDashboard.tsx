import { useMemo } from 'react'
import { GlassPanel } from '../ui/GlassPanel'
import type { AgentTrace, IncidentDialogue, LlmAgentStatus } from '../../types/api'
import { AssignmentHandshake } from './AssignmentHandshake'

const CORE_AGENTS = [
  { id: 'fleet_agent', name: 'Fleet', role: 'Dispatcher' },
  { id: 'navigation_agent', name: 'Nav', role: 'Pathfinder' },
  { id: 'safety_agent', name: 'Safety', role: 'Final say' },
  { id: 'recovery_agent', name: 'Recovery', role: 'After break' },
] as const

type AgentId = (typeof CORE_AGENTS)[number]['id']

function normalizeAgent(name: string): AgentId | null {
  const n = name.toLowerCase()
  if (n.includes('fleet') && !n.includes('llm')) return 'fleet_agent'
  if (n.includes('nav')) return 'navigation_agent'
  if (n.includes('safety') && !n.includes('llm')) return 'safety_agent'
  if (n.includes('recovery') && !n.includes('llm')) return 'recovery_agent'
  return null
}

export function AgentDashboard({
  traces,
  dialogues,
  llmStatus,
  compact = false,
}: {
  traces: AgentTrace[]
  dialogues?: IncidentDialogue[]
  llmStatus?: LlmAgentStatus | null
  compact?: boolean
}) {
  const latest = traces[0] ?? null

  const activity = useMemo(() => {
    const map: Record<AgentId, { hot: boolean; seen: boolean }> = {
      fleet_agent: { hot: false, seen: false },
      navigation_agent: { hot: false, seen: false },
      safety_agent: { hot: false, seen: false },
      recovery_agent: { hot: false, seen: false },
    }
    for (const t of traces.slice(0, 40)) {
      for (const side of [t.sender, t.receiver]) {
        const id = normalizeAgent(side)
        if (id) map[id].seen = true
      }
    }
    if (latest) {
      const a = normalizeAgent(latest.sender)
      const b = normalizeAgent(latest.receiver)
      if (a) map[a].hot = true
      if (b) map[b].hot = true
    }
    return map
  }, [traces, latest])

  const latestDialogue = dialogues?.[0] ?? null

  return (
    <GlassPanel title="Agents talking">
      <div className="space-y-3">
        <div className="flex flex-wrap gap-2">
          {CORE_AGENTS.map((agent) => {
            const a = activity[agent.id]
            return (
              <span
                key={agent.id}
                className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-[11px] ${
                  a.hot
                    ? 'border-emerald-400/40 bg-emerald-500/10 text-emerald-100'
                    : 'border-white/10 text-slate-400'
                }`}
              >
                <span
                  className={`h-1.5 w-1.5 rounded-full ${
                    a.hot ? 'fs-pulse bg-emerald-400' : a.seen ? 'bg-slate-500' : 'bg-slate-700'
                  }`}
                />
                {agent.name}
                <span className="text-slate-600">· {agent.role}</span>
              </span>
            )
          })}
        </div>

        <AssignmentHandshake traces={traces} />

        {!compact && latestDialogue && (
          <p className="truncate text-[11px] text-slate-500">
            Incident:{' '}
            <span className="text-slate-400">
              {latestDialogue.messages[0]
                ? `${latestDialogue.messages[0].sender.replace(/_/g, ' ')} — ${latestDialogue.messages[0].content.slice(0, 80)}`
                : '—'}
            </span>
            {llmStatus?.configured ? '' : ' (fallback)'}
          </p>
        )}
      </div>
    </GlassPanel>
  )
}
