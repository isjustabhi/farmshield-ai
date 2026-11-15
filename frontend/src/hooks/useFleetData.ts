import { useCallback, useEffect, useRef, useState } from 'react'
import { loadExampleSnapshot } from '../demo/loadExampleSnapshot'
import { api } from '../services/api'
import type {
  AgentMetrics,
  AgentTrace,
  AgOpenWebIntegration,
  ApiConnectionState,
  AssignmentDecision,
  ChaosEventResult,
  IncidentDialogue,
  LlmAgentStatus,
  MemoryIncident,
  MemoryRun,
  RecoveryLogEntry,
  SimEvent,
  SimulationState,
} from '../types/api'

const EXAMPLE_NOTE =
  'Static example snapshot. Start FastAPI on port 8000 for live control.'

interface FleetData {
  connection: ApiConnectionState
  agopenweb: AgOpenWebIntegration | null
  state: SimulationState | null
  events: SimEvent[]
  decisions: AssignmentDecision[]
  recoveryLogs: RecoveryLogEntry[]
  traces: AgentTrace[]
  metrics: AgentMetrics | null
  dialogues: IncidentDialogue[]
  llmStatus: LlmAgentStatus | null
  incidents: MemoryIncident[]
  runs: MemoryRun[]
  currentRunId: string | null
  error: string | null
  busy: boolean
  refresh: () => Promise<void>
  play: () => Promise<void>
  pause: () => Promise<void>
  step: () => Promise<void>
  reset: () => Promise<void>
  schedule: () => Promise<void>
  replan: () => Promise<void>
  breakdown: (tractorId: string) => Promise<void>
  repair: (tractorId: string) => Promise<void>
  lastChaos: ChaosEventResult | null
  blockRoute: (x: number, y: number) => Promise<ChaosEventResult | null>
  unblockRoute: (x: number, y: number) => Promise<ChaosEventResult | null>
  priorityChange: (jobId: string, priority: number) => Promise<ChaosEventResult | null>
  fuelChange: (tractorId: string, fuelLevel: number) => Promise<ChaosEventResult | null>
  chaosRandom: (seed?: number) => Promise<ChaosEventResult | null>
}

export function useFleetData(pollMs = 800): FleetData {
  const [connection, setConnection] = useState<ApiConnectionState>('checking')
  const [agopenweb, setAgopenweb] = useState<AgOpenWebIntegration | null>(null)
  const [state, setState] = useState<SimulationState | null>(null)
  const [events, setEvents] = useState<SimEvent[]>([])
  const [decisions, setDecisions] = useState<AssignmentDecision[]>([])
  const [recoveryLogs, setRecoveryLogs] = useState<RecoveryLogEntry[]>([])
  const [traces, setTraces] = useState<AgentTrace[]>([])
  const [metrics, setMetrics] = useState<AgentMetrics | null>(null)
  const [dialogues, setDialogues] = useState<IncidentDialogue[]>([])
  const [llmStatus, setLlmStatus] = useState<LlmAgentStatus | null>(null)
  const [incidents, setIncidents] = useState<MemoryIncident[]>([])
  const [runs, setRuns] = useState<MemoryRun[]>([])
  const [currentRunId, setCurrentRunId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [lastChaos, setLastChaos] = useState<ChaosEventResult | null>(null)
  const mounted = useRef(true)
  const connectionRef = useRef<ApiConnectionState>('checking')
  const hasExampleRef = useRef(false)

  const applyExample = useCallback(async () => {
    const snap = await loadExampleSnapshot()
    if (!mounted.current) return
    setState(snap.state)
    setEvents([...snap.events].reverse())
    setDecisions(snap.decisions)
    setRecoveryLogs([...snap.recoveryLogs].reverse())
    setTraces([...snap.traces].reverse())
    setMetrics(snap.metrics)
    setDialogues([...snap.dialogues].reverse())
    setLlmStatus(snap.llmStatus)
    setAgopenweb(snap.agopenweb)
    setIncidents(snap.incidents)
    setRuns(snap.runs)
    setCurrentRunId(snap.currentRunId)
    setConnection('example')
    connectionRef.current = 'example'
    hasExampleRef.current = true
    setError(EXAMPLE_NOTE)
  }, [])

  const refresh = useCallback(async () => {
    try {
      const [
        nextState,
        eventPayload,
        decisionPayload,
        recovery,
        tracePayload,
        metricPayload,
        incidentPayload,
        runPayload,
        aow,
        llmPayload,
      ] = await Promise.all([
        api.getState(),
        api.getEvents(),
        api.getDecisions(),
        api.getRecoveryLogs(),
        api.getAgentTraces(),
        api.getAgentMetrics(),
        api.getMemoryIncidents(),
        api.getMemoryRuns(),
        api.getAgOpenWebStatus(),
        api.getLlmDialogues(),
      ])
      if (!mounted.current) return
      setState(nextState)
      setAgopenweb(aow)
      setEvents(eventPayload.events.slice(-80).reverse())
      setDecisions(decisionPayload.decisions)
      setRecoveryLogs(recovery.logs.slice().reverse())
      setTraces(tracePayload.traces.slice(-120).reverse())
      setMetrics(metricPayload)
      setDialogues(llmPayload.dialogues.slice().reverse())
      setLlmStatus(llmPayload.status)
      setIncidents(incidentPayload.incidents)
      setRuns(runPayload.runs)
      setCurrentRunId(runPayload.current_run_id)
      setConnection('connected')
      connectionRef.current = 'connected'
      hasExampleRef.current = false
      setError(null)
    } catch {
      if (!mounted.current) return
      if (hasExampleRef.current) return
      try {
        await applyExample()
      } catch {
        if (!mounted.current) return
        setConnection('disconnected')
        connectionRef.current = 'disconnected'
        setError('API unavailable and example snapshot failed to load.')
      }
    }
  }, [applyExample])

  useEffect(() => {
    mounted.current = true
    void refresh()
    const id = window.setInterval(() => {
      if (connectionRef.current === 'example') {
        void api
          .getHealth()
          .then(() => refresh())
          .catch(() => undefined)
        return
      }
      void refresh()
    }, pollMs)
    return () => {
      mounted.current = false
      window.clearInterval(id)
    }
  }, [pollMs, refresh])

  const exampleBlocked = useCallback(async () => {
    setError(EXAMPLE_NOTE)
  }, [])

  const runAction = useCallback(
    async (action: () => Promise<unknown>) => {
      if (connectionRef.current === 'example') {
        await exampleBlocked()
        return
      }
      setBusy(true)
      try {
        await action()
        await refresh()
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Action failed')
      } finally {
        setBusy(false)
      }
    },
    [exampleBlocked, refresh],
  )

  const runChaos = useCallback(
    async (action: () => Promise<ChaosEventResult>) => {
      if (connectionRef.current === 'example') {
        await exampleBlocked()
        return null
      }
      setBusy(true)
      try {
        const result = await action()
        setLastChaos(result)
        await refresh()
        return result
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Chaos action failed')
        return null
      } finally {
        setBusy(false)
      }
    },
    [exampleBlocked, refresh],
  )

  return {
    connection,
    agopenweb,
    state,
    events,
    decisions,
    recoveryLogs,
    traces,
    metrics,
    dialogues,
    llmStatus,
    incidents,
    runs,
    currentRunId,
    error,
    busy,
    lastChaos,
    refresh,
    play: () => runAction(() => api.play()),
    pause: () => runAction(() => api.pause()),
    step: () => runAction(() => api.step()),
    reset: () => runAction(() => api.reset()),
    schedule: () => runAction(() => api.schedule()),
    replan: () => runAction(() => api.replan()),
    breakdown: (tractorId: string) => runAction(() => api.breakdown(tractorId)),
    repair: (tractorId: string) => runAction(() => api.repair(tractorId)),
    blockRoute: (x, y) => runChaos(() => api.blockRoute(x, y)),
    unblockRoute: (x, y) => runChaos(() => api.unblockRoute(x, y)),
    priorityChange: (jobId, priority) => runChaos(() => api.priorityChange(jobId, priority)),
    fuelChange: (tractorId, fuelLevel) => runChaos(() => api.fuelChange(tractorId, fuelLevel)),
    chaosRandom: (seed) => runChaos(() => api.chaosRandom(seed)),
  }
}
