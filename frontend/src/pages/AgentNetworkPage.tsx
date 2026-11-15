import { AgentDashboard } from '../components/agents/AgentDashboard'
import { GlassPanel } from '../components/ui/GlassPanel'
import type { AgentMetrics, AgentTrace, IncidentDialogue, LlmAgentStatus } from '../types/api'

export function AgentNetworkPage({
  traces,
  metrics,
  dialogues,
  llmStatus,
}: {
  traces: AgentTrace[]
  metrics: AgentMetrics | null
  dialogues: IncidentDialogue[]
  llmStatus: LlmAgentStatus | null
}) {
  return (
    <div className="space-y-4">
      <AgentDashboard traces={traces} dialogues={dialogues} llmStatus={llmStatus} />

      <div className="grid gap-4 lg:grid-cols-[0.9fr_1.3fr]">
        <div className="space-y-4">
          <GlassPanel title="Agent metrics">
            {metrics ? (
              <dl className="grid grid-cols-2 gap-3 text-xs">
                <Metric label="Total calls" value={String(metrics.total_agent_calls)} />
                <Metric label="Avg latency" value={`${metrics.average_latency_ms.toFixed(2)} ms`} />
                <Metric label="P95 latency" value={`${metrics.p95_latency_ms.toFixed(2)} ms`} />
                <Metric label="Failed calls" value={String(metrics.failed_calls)} />
                <Metric
                  label="Validation rejects"
                  value={String(metrics.validation_rejection_count)}
                />
                <Metric label="Commits" value={String(metrics.committed_scheduling_decisions)} />
                <Metric
                  label="Calls / commit"
                  value={metrics.calls_per_committed_decision.toFixed(2)}
                />
                <Metric
                  label="Replan latency"
                  value={`${metrics.overall_replanning_latency_ms.toFixed(2)} ms`}
                />
              </dl>
            ) : (
              <p className="text-xs text-slate-500">No metrics yet.</p>
            )}
          </GlassPanel>

          <GlassPanel title="Talking points">
            <ol className="list-decimal space-y-2 pl-4 text-sm leading-relaxed text-slate-300">
              <li>Show the farm radio — dispatcher, navigator, safety clearing the job.</li>
              <li>Schedule again so a new call shows up with another tractor.</li>
              <li>Break a tractor — they talk it through; safety still has the final say.</li>
            </ol>
          </GlassPanel>
        </div>

        <div className="space-y-4">
          <GlassPanel title="Incident agent dialogue">
            <ul className="fs-scroll max-h-[22rem] space-y-3 overflow-y-auto">
              {dialogues.length === 0 && (
                <li className="text-xs text-slate-500">
                  Trigger a breakdown — Fleet, Recovery, and Safety LLM agents will talk here.
                </li>
              )}
              {dialogues.map((d) => (
                <li
                  key={d.correlation_id}
                  className="rounded-lg border border-white/5 bg-black/20 px-3 py-2 text-xs"
                >
                  <p className="font-medium text-slate-200">
                    {d.incident_type} · {d.tractor_id}
                    {d.job_id ? ` · ${d.job_id}` : ''} · t={d.sim_time}
                    {d.llm_used ? ' · LLM' : ' · fallback'}
                  </p>
                  <ul className="mt-2 space-y-1.5 border-l border-emerald-500/30 pl-3">
                    {d.messages.map((m) => (
                      <li key={m.id}>
                        <span className="text-emerald-400/90">
                          {m.sender} → {m.receiver}
                        </span>
                        <p className="text-slate-300">{m.content}</p>
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          </GlassPanel>

          <GlassPanel title="Agent communication traces">
            <ul className="fs-scroll max-h-[16rem] space-y-2 overflow-y-auto">
              {traces.length === 0 && (
                <li className="text-xs text-slate-500">No traces yet. Run Schedule.</li>
              )}
              {traces.map((t, idx) => (
                <li
                  key={`${t.correlation_id}-${idx}`}
                  className="rounded-lg border border-white/5 bg-black/20 px-3 py-2 text-xs"
                >
                  <p className="font-medium text-slate-200">
                    {t.sender} → {t.receiver}
                  </p>
                  <p className="mt-1 text-slate-400">
                    {t.request_type} / {t.response_type} · {t.status} · {t.duration_ms.toFixed(2)}ms
                    · t={t.simulation_timestamp}
                  </p>
                </li>
              ))}
            </ul>
          </GlassPanel>
        </div>
      </div>
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-white/5 bg-black/20 px-3 py-2">
      <dt className="text-[10px] uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className="mt-1 text-sm text-slate-100">{value}</dd>
    </div>
  )
}
