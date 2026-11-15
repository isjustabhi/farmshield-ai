import type {
  AgentMetrics,
  AgentTrace,
  AgOpenWebIntegration,
  AssignmentDecision,
  IncidentDialogue,
  LlmAgentStatus,
  MemoryIncident,
  MemoryRun,
  RecoveryLogEntry,
  SimEvent,
  SimulationState,
} from '../types/api'

export interface ExampleSnapshot {
  note?: string
  state: SimulationState
  events: SimEvent[]
  decisions: AssignmentDecision[]
  traces: AgentTrace[]
  metrics: AgentMetrics
  dialogues: IncidentDialogue[]
  llmStatus: LlmAgentStatus
  recoveryLogs: RecoveryLogEntry[]
  agopenweb: AgOpenWebIntegration
  incidents: MemoryIncident[]
  runs: MemoryRun[]
  currentRunId: string
}

let cached: ExampleSnapshot | null = null

export async function loadExampleSnapshot(): Promise<ExampleSnapshot> {
  if (cached) return structuredClone(cached)
  const base = import.meta.env.BASE_URL || '/'
  const url = `${base}demo/example-snapshot.json`
  const res = await fetch(url)
  if (!res.ok) throw new Error(`Could not load example snapshot (${res.status})`)
  cached = (await res.json()) as ExampleSnapshot
  return structuredClone(cached)
}
