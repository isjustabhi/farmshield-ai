# FarmShield AI: architecture and agents

## System shape

```
React UI (Vite)
    │  HTTP /api/*
FastAPI
    │
    ├── simulation.py      authoritative farm state (ticks, fuel, jobs)
    ├── orchestration.py   AgentBus + schedule / breakdown / recovery
    ├── scheduler.py       Fleet matching
    ├── navigation.py      A* routes
    ├── safety.py          hard validation before commit
    ├── recovery.py        incident proposals, preserved work
    ├── llm_agents.py      optional Claude incident dialogue
    ├── memory.py          SQLite runs, incidents, traces
    ├── metrics.py         productivity + agent latency
    ├── chaos.py           seeded disruptions
    └── benchmark.py       FCFS vs FarmShield (isolated sims)
```

The UI never assigns jobs directly. It calls the API. The API runs agents through orchestration, then mutates simulation state only after Safety approves.

## Agents

| Agent | Code | Responsibility |
| --- | --- | --- |
| Fleet | `scheduler.py` | Score and match free tractors to schedulable jobs |
| Navigation | `navigation.py` | A* path, travel time, reachability |
| Safety | `safety.py` | Approve or reject (equipment, fuel+reserve, ownership, progress) |
| Recovery | `recovery.py` | After breakdown/fuel fail, propose replan; keep preserved work |
| Incident LLM (optional) | `llm_agents.py` | Plain-language dialogue after incidents |

Fleet, Nav, Safety, and Recovery are deterministic. The optional LLM layer narrates incidents. It does not commit assignments.

## Orchestration flow

Entry points in `orchestration.py`:

- `schedule_and_apply`: normal scheduling
- `breakdown_and_recover`: stop tractor, preserve work, replan
- `handle_simulation_incident`: internal fuel/failure path
- `repair_and_log` / `replan_unfinished`: recovery helpers

### Normal assign

1. Fleet builds a plan (exhaustive scored matching).
2. For each planned pair, AgentBus calls Navigation (`RouteRequest` → `RouteResponse`).
3. AgentBus calls Safety (`SafetyValidationRequest` → `SafetyValidationResponse`).
4. If approved, `simulation.assign_job(...)`. If rejected, skip that pair.

### Failure path

1. Simulation marks tractor broken and releases the job with `completed_work_units` unchanged.
2. Recovery proposes reschedule.
3. `schedule_and_apply` runs again (same Nav + Safety gates).
4. Optional: `run_incident_dialogue` (Claude or fallback) records agent-to-agent messages for the UI.

## AgentBus

`AgentBus.call(...)` in `orchestration.py`:

- Records sender, receiver, request/response types
- Measures wall-clock latency (`perf_counter`)
- Sets status (`ok`, `rejected`, `error`, …)
- Attaches `correlation_id` and optional `decision_id`
- Writes an `AgentTrace` via `agent_observability` (and SQLite)

Transport label: `in_process`. This is multi-agent messaging inside one process, not a separate microservice network.

## Where to see it in the UI

| View | What it shows |
| --- | --- |
| Command Center | Live grid + agent handshake panel |
| Agent Network | Traces, metrics, incident dialogue |
| Chaos Lab | Inject breakdown / block / fuel; same agent path |
| Incident Memory | Stored breakdowns and recovery notes |
| Benchmark Lab | FCFS vs FarmShield measured results |

## APIs (agent-related)

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/schedule` | Fleet → Nav → Safety → commit |
| POST | `/api/events/breakdown` | Breakdown + recovery orchestration |
| GET | `/api/agents/traces` | AgentBus traces |
| GET | `/api/agents/metrics` | Call counts and latencies |
| GET | `/api/agents/llm/status` | Whether Claude/OpenAI is configured |
| GET | `/api/agents/llm/dialogues` | Incident agent messages |

## Config (optional LLM)

See `.env.example`:

- `LLM_PROVIDER` (`anthropic` or `openai`)
- `LLM_API_KEY`
- `LLM_MODEL`
- `LLM_AGENTS_ENABLED`

Without a key, incident dialogue still appears via deterministic fallback text.

## What stays out of agent control

- Hard Safety rules (cannot be skipped by Fleet or LLM)
- Progress accounting (no invented work units)
- Benchmark fairness (isolated sims, same seeds/incidents, same Safety path for FCFS)

## Related docs

- [`README.md`](../README.md): setup, scenario, benchmarks
- [`demo_script.md`](../demo_script.md): 90-second judge walkthrough
- [`AGOPENWEB.md`](./AGOPENWEB.md): optional field.geojson adapter
