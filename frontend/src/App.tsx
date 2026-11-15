import { useState } from 'react'
import { Sidebar } from './components/layout/Sidebar'
import { TopNav } from './components/layout/TopNav'
import { useFleetData } from './hooks/useFleetData'
import { AgentNetworkPage } from './pages/AgentNetworkPage'
import { BenchmarkLabPage } from './pages/BenchmarkLabPage'
import { ChaosLabPage } from './pages/ChaosLabPage'
import { CommandCenterPage } from './pages/CommandCenterPage'
import { FleetMonitorPage } from './pages/FleetMonitorPage'
import { IncidentMemoryPage } from './pages/IncidentMemoryPage'
import { IntelligencePage } from './pages/IntelligencePage'
import { MissionQueuePage } from './pages/MissionQueuePage'
import type { AppView } from './types/api'

export default function App() {
  const [view, setView] = useState<AppView>('command')
  const fleet = useFleetData(700)

  return (
    <div className="flex min-h-screen text-slate-100">
      <Sidebar view={view} onChange={setView} />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopNav
          connection={fleet.connection}
          agopenweb={fleet.agopenweb}
          state={fleet.state}
          busy={fleet.busy}
          onPlay={() => void fleet.play()}
          onPause={() => void fleet.pause()}
          onStep={() => void fleet.step()}
          onReset={() => void fleet.reset()}
          onSchedule={() => void fleet.schedule()}
        />

        <main className="flex-1 space-y-4 overflow-auto p-4 md:p-5">
          {fleet.error && (
            <div className="rounded-lg border border-[var(--fs-red)]/40 bg-[var(--fs-red-dim)] px-4 py-3 text-sm text-red-100">
              {fleet.error}
            </div>
          )}

          {!fleet.state ? (
            <div className="fs-glass rounded-xl px-6 py-16 text-center text-sm text-slate-400">
              {fleet.connection === 'checking'
                ? 'Connecting to FarmShield API…'
                : 'Backend offline. Start FastAPI on port 8000.'}
            </div>
          ) : (
            <>
              {view === 'command' && (
                <CommandCenterPage
                  state={fleet.state}
                  decisions={fleet.decisions}
                  events={fleet.events}
                  recoveryLogs={fleet.recoveryLogs}
                  traces={fleet.traces}
                  dialogues={fleet.dialogues}
                  llmStatus={fleet.llmStatus}
                  busy={fleet.busy}
                  onBreakdown={(id) => void fleet.breakdown(id)}
                  onRepair={(id) => void fleet.repair(id)}
                />
              )}
              {view === 'fleet' && <FleetMonitorPage state={fleet.state} />}
              {view === 'missions' && <MissionQueuePage state={fleet.state} />}
              {view === 'chaos' && (
                <ChaosLabPage
                  state={fleet.state}
                  busy={fleet.busy}
                  events={fleet.events}
                  recoveryLogs={fleet.recoveryLogs}
                  traces={fleet.traces}
                  dialogues={fleet.dialogues}
                  llmStatus={fleet.llmStatus}
                  lastChaos={fleet.lastChaos}
                  onBreakdown={(id) => void fleet.breakdown(id)}
                  onRepair={(id) => void fleet.repair(id)}
                  onReset={() => void fleet.reset()}
                  onBlock={(x, y) => void fleet.blockRoute(x, y)}
                  onUnblock={(x, y) => void fleet.unblockRoute(x, y)}
                  onPriority={(jobId, priority) => void fleet.priorityChange(jobId, priority)}
                  onFuel={(tractorId, fuel) => void fleet.fuelChange(tractorId, fuel)}
                  onRandom={(seed) => void fleet.chaosRandom(seed)}
                />
              )}
              {view === 'intelligence' && (
                <IntelligencePage
                  state={fleet.state}
                  runs={fleet.runs}
                  currentRunId={fleet.currentRunId}
                />
              )}
              {view === 'agents' && (
                <AgentNetworkPage
                  traces={fleet.traces}
                  metrics={fleet.metrics}
                  dialogues={fleet.dialogues}
                  llmStatus={fleet.llmStatus}
                />
              )}
              {view === 'memory' && (
                <IncidentMemoryPage incidents={fleet.incidents} runs={fleet.runs} />
              )}
              {view === 'benchmark' && (
                <BenchmarkLabPage state={fleet.state} decisions={fleet.decisions} />
              )}
            </>
          )}
        </main>
      </div>
    </div>
  )
}
