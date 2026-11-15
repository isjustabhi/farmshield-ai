# FarmShield AI

Autonomous tractor fleet coordinator for the **American Tractor Company: Run the Fleet** hackathon.

FarmShield schedules field jobs on a deterministic simulator, validates assignments through Fleet, Navigation, and Safety agents, recovers from failures without losing completed work, records operational memory, and benchmarks against FCFS. The UI uses the FastAPI backend. Optional Anthropic Claude (via `.env`) generates incident dialogue only; it does not commit jobs.

Static UI preview: [https://isjustabhi.github.io/farmshield-ai/](https://isjustabhi.github.io/farmshield-ai/)

---

## APIs

| API | Role |
| --- | --- |
| FastAPI `/api/*` | Simulation, schedule, chaos, metrics |
| Claude (optional) | Incident dialogue after breakdowns |
| AgOpenWeb field file (optional) | Read-only `field.geojson` metadata |

---

## Scenario

`backend/data/scenario.json` (`hackathon_demo_v1`, seed 42)

| Piece | Details |
| --- | --- |
| Map | 20×20 grid, depot at (0,0) |
| Fields | 8 fields (North Orchard, East Meadow, River Bend, Center Plot, and others) |
| Tractors | Shield-Alpha and Charlie (spraying), Shield-Bravo (mowing) |
| Jobs | 10 jobs with priority, deadlines, and dependencies |
| Fuel | Travel, work, and safety reserve |

One tick equals one simulated minute. Schedule runs orchestration. Play advances the clock. Chaos Lab injects breakdowns and route blocks.

---

## AI orchestration

Agents run in sequence through `orchestration.py`. Each step consumes the previous response. Assignments are committed only after Safety approval.

| Agent | Role |
| --- | --- |
| Fleet | Match free tractors to schedulable jobs |
| Navigation | A* route, travel time, fuel estimate |
| Safety | Approve or reject before commit |
| Recovery | Propose replan after faults; preserve completed work |
| Incident LLM (optional) | Dialogue about the incident |

### Assign path

```
Fleet plan
  → Navigation (RouteRequest / RouteResponse)
  → Safety (SafetyValidationRequest / SafetyValidationResponse)
  → simulation.assign_job (only if approved)
```

Rejected pairs are skipped. Traces appear on Command Center and Agent Network (`fleet_agent → navigation_agent → safety_agent`).

### Failure path

```
Breakdown: preserve completed_work_units, release job
  → Recovery proposal
  → Fleet → Navigation → Safety (same gates)
  → optional incident LLM dialogue
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for AgentBus details and API routes.

---

## Differentiating factors

1. Safety validation is required before every commit.
2. Agent hops are logged (sender, receiver, latency, status) and shown in the UI.
3. Breakdowns preserve completed work; recovery reuses the same Safety path.
4. Productivity metrics and FCFS benchmarks use measured simulator data.
5. SQLite stores runs, incidents, and traces.
6. AgOpenWeb support is read-only field metadata; no claimed GPS or vehicle control.

---

## Problem statement

Multi-tractor fleets must assign the right implement to the right field job, respect fuel and deadlines, avoid conflicting ownership, and recover when machines fail mid-work. First-free-tractor policies waste priority and miss deadlines. Schedulers that ignore fuel or equipment produce unsafe plans. This project is a working demo of coordination, safety, memory, and measured comparison against a baseline.

## Solution overview

FarmShield runs a **single authoritative simulator** plus a **Fleet Agent** that exhaustively matches free tractors to schedulable jobs, then commits only after **Navigation (A\*)** and **Safety** approve. Failures release jobs with **preserved work units**; Recovery requests a replan through the same gates. Optional Claude dialogue narrates incidents. SQLite **operational memory** stores runs, incidents, decisions, and traces. A **Benchmark Lab** compares FCFS vs FarmShield on independent state copies under identical seeds and incidents.

## Architecture

Full agent/orchestration write-up: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

```
┌─────────────────────────────────────────────────────────────┐
│  React Command Center (Vite)                                │
│  Fleet · Missions · Chaos · Intelligence · Agents · Bench   │
└───────────────────────────┬─────────────────────────────────┘
                            │ HTTP /api/*
┌───────────────────────────▼─────────────────────────────────┐
│  FastAPI                                                    │
│  simulation · orchestration (AgentBus) · chaos · metrics    │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────────┐   │
│  │ Fleet    │→│ Nav A*   │→│ Safety   │→│ Recovery      │   │
│  │ matching │ │ routes   │ │ validate │ │ replan advise │   │
│  └──────────┘ └──────────┘ └──────────┘ └───────────────┘   │
│  SQLite operational memory · productivity ledger · FCFS     │
└─────────────────────────────────────────────────────────────┘
```

| Module | Role |
| --- | --- |
| `simulation.py` | Deterministic 1-minute ticks, fuel, travel, work, events |
| `scheduler.py` | Exhaustive scored matching (FarmShield) |
| `baseline.py` | FCFS planner (same feasibility + Safety commit path) |
| `navigation.py` | A* routes |
| `safety.py` | Hard constraints + lateness warnings |
| `orchestration.py` | AgentBus, schedule_and_apply, breakdown/repair/replan |
| `memory.py` | SQLite append-only history |
| `metrics.py` | Wall-clock agent latency + productivity ledger |
| `benchmark.py` | Fair FCFS vs FarmShield harness |
| `chaos.py` | Seeded disruptions |

## Stack

| Layer | Technology |
| --- | --- |
| Frontend | React 19, TypeScript, Vite, Tailwind CSS 4, Recharts, Lucide |
| Backend | Python 3.12, FastAPI, Pydantic, Uvicorn |
| Database | SQLite (`backend/data/farmshield.db`) |
| Simulation | Custom deterministic 2D grid |

## Setup

```bash
# Python
python3.12 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Frontend
cd frontend && npm install && cd ..

# Optional: LLM incident agents (paste keys — .env is gitignored)
cp .env.example .env
# Anthropic Claude: LLM_PROVIDER=anthropic, LLM_API_KEY=sk-ant-...
# OpenAI:          LLM_PROVIDER=openai, LLM_API_KEY=sk-...
```

Without a key, agents still talk via a deterministic fallback after breakdowns. With a Claude/OpenAI key, Fleet / Recovery / Safety LLM personas exchange messages. They **never** bypass Safety or invent telemetry.

## How to run

**Terminal 1 — API**

```bash
source .venv/bin/activate
cd backend
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

**Terminal 2 — UI**

```bash
cd frontend
npm run dev -- --host 127.0.0.1 --port 5173
```

Open **http://127.0.0.1:5173**. Health: `curl http://127.0.0.1:8000/api/health`.

Production frontend build:

```bash
cd frontend && npm run build
```

### Static site (GitHub Pages)

UI preview (example snapshot when the API is not running):  
**https://isjustabhi.github.io/farmshield-ai/**

For the full live demo, run FastAPI locally as above.

## How to trigger incidents

| Action | UI | API |
| --- | --- | --- |
| Breakdown | Command Center / Chaos Lab | `POST /api/events/breakdown` `{"tractor_id":"tractor_01"}` |
| Repair | same | `POST /api/events/repair` |
| Block route | Chaos Lab | `POST /api/events/block-route` `{"x":7,"y":7}` |
| Fuel change | Chaos Lab | `POST /api/events/fuel-change` |
| Priority change | Chaos Lab | `POST /api/events/priority-change` |
| Random chaos | Chaos Lab | `POST /api/chaos/random` `{"seed":42}` |
| Replan | API / recovery flows | `POST /api/replan` |

## Scheduling algorithm (FarmShield)

1. Collect **free idle** tractors and **schedulable** pending jobs (dependencies met).
2. Score every feasible pair (`evaluate_pair`: equipment, reachability, fuel + safety reserve).
3. Weights: priority reward, deadline urgency, lateness penalty, travel / unproductive time.
4. Exhaustive matching: maximize assignment count, then total score, then deterministic lex tie-break.
5. For each planned assignment: Nav route → Safety validate → `assign_job` (or skip).

**FCFS baseline:** jobs in scenario submission order; first feasible free tractor (scenario tractor order); **same** Nav + Safety commit path. Not handicapped.

## Agent communication design (technical)

`AgentBus` wraps in-process calls with `time.perf_counter()` latency. Each hop records an `AgentTrace` (sender, receiver, request/response types, status, `correlation_id`, optional `decision_id`, simulation timestamp). Transport is `in_process`. Traces persist to SQLite and show on Agent Network. LLM incident dialogues are separate (`/api/agents/llm/dialogues`) and never commit assigns.

## Operational memory design

SQLite tables: `simulation_runs`, `tractor_events`, `job_events`, `assignments`, `incidents`, `agent_traces`, `scheduling_decisions`, `performance_summaries`. Append-only. Reset starts a new `run_id` and clears ephemeral recovery logs; historical rows remain. Tractor profiles surface recurrence warnings from stored incident counts only — no invented predictions.

## Safety constraints

Hard reject (assignment not committed):

- Missing tractor/job; broken tractor; tractor not idle/unassigned
- Job already owned / not pending; reservation conflicts in-cycle
- Incompatible implement vs job type
- Work regression / progress mismatch on recovery proposals
- Unreachable field; insufficient fuel for travel + remaining work + **safety reserve**

Warnings (allowed): predicted finish past deadline (`unavoidable_lateness`).

## Metrics definitions

| Metric | Definition |
| --- | --- |
| Fleet utilization | `work / (work + travel + idle)`; broken time excluded; 0 if available=0 |
| Productive work | Minutes in `WORKING` |
| Travel / idle | Travel separate from work; idle = operational neither travel nor work |
| Priority-weighted work | `Σ work_units × (6 − min(priority, 5))` |
| Missed deadlines | Late completions + incomplete jobs past deadline |
| Fuel consumed | Travel + work burn only (chaos fuel edits excluded) |
| Agent latency | Wall-clock AgentBus duration (not simulated minutes) |
| Safety violations (benchmark) | Hard Safety rejections during commit |

## Real benchmark results

Generated by `app.benchmark.run_benchmark(horizon=300, variant_count=20)` on independent sim copies. Files: `benchmark_results.json`, `benchmark_results.csv` (repo root + `backend/data/`).

**Averages across 21 scenarios (1 main + 20 seeded variants):**

| Metric | FCFS | FarmShield | Δ% |
| --- | ---: | ---: | ---: |
| Jobs completed | 9.86 | 10.00 | **+1.45%** |
| On-time completions | 9.86 | 10.00 | **+1.45%** |
| Priority-weighted work | 236.1 | 239.1 | **+1.29%** |
| Idle time | 741.0 | 735.1 | **−0.80%** |
| Missed deadlines | 0.14 | 0.00 | **−100%** |
| Travel time | 67.1 | 72.3 | +7.66% (FarmShield worse) |
| Fuel consumed | 70.5 | 74.8 | +6.15% (FarmShield worse) |
| Safety violations | 0 | 0 | tie |

FarmShield finishes more (and more on-time) priority-weighted work with fewer misses, at higher travel and fuel on this scenario family. Equal-weight scenario scoring can favor FCFS when travel and fuel are counted the same as completions.

Re-run:

```bash
source .venv/bin/activate
cd backend
python -c "from app.benchmark import run_benchmark; run_benchmark()"
```

## AgOpenWeb integration

Investigated against [AgOpenGPS-Official/AgOpenWeb](https://github.com/AgOpenGPS-Official/AgOpenWeb).

**Finding:** AgOpenWeb does **not** expose a public REST API for fleet command or live tractor telemetry. It is a cab guidance host (UI ~`:5174`). Documented third-party surface is primarily **`field.geojson`** (`Docs/FIELD_FILE_FORMATS.md`). Live fixes use NMEA/UDP PGN for hardware modules — not claimed here.

**What we ship:** optional **read-only** `AgOpenWebAdapter` + top-nav status (`Unsupported` / `Disconnected` / `Connected`). See [`docs/AGOPENWEB.md`](docs/AGOPENWEB.md).

| When Connected | Still simulated |
| --- | --- |
| Field name, WGS84 origin, boundary/track/flag metadata from GeoJSON | Tractor motion, jobs, fuel, scheduling, recovery, grid routes |

We do **not** claim real tractor control or fabricated GPS streams. Default status is **Unsupported** (custom simulator fully functional).

## Known limitations

- Small fleet exhaustive matching; not scaled to hundreds of tractors.
- Travel is grid A* with shared obstacles; no continuous kinematics or collision cones between tractors.
- Refueling model is minimal; depot fill is one-tick.
- Benchmark “scenario wins” count every metric equally (travel/fuel can outweigh completion gains).
- Live Command Center and headless benchmark use separate sim instances; running a long benchmark while demoing may contend for CPU only (isolated sims do not mutate the live API state).
- GitHub Pages hosts a **static example** UI only; live control needs FastAPI.

## Submission artifacts

| File | Description |
| --- | --- |
| `README.md` | This document |
| `backend/data/scenario.json` | Seeded demo farm |
| `demo_event_log.json` | Real simulator event export from demo timeline |
| `benchmark_results.json` / `.csv` | Measured FCFS vs FarmShield |
| `requirements.txt` | Python deps |
| `package.json` | Root npm scripts → `frontend/` |
| `frontend/package.json` | UI dependencies |
| `.gitignore` | venv, node_modules, db, dist |
| `demo_script.md` | 90-second judge walkthrough (full product) |
| `demo_script_agents.md` | 90-second walkthrough focused on agent orchestration |
| `docs/ARCHITECTURE.md` | Agents, AgentBus, APIs |

Regenerate demo log + checklist:

```bash
source .venv/bin/activate
cd backend && python scripts/generate_demo_and_verify.py
```

## Key API routes

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Liveness |
| GET | `/api/state` | Authoritative sim state |
| POST | `/api/simulation/{reset,step,play,pause}` | Control |
| POST | `/api/schedule` | Plan + apply |
| GET | `/api/agents/traces` | AgentBus traces |
| GET | `/api/agents/llm/status` | LLM key configured? (no secrets) |
| GET | `/api/agents/llm/dialogues` | Incident agent-to-agent chat |
| GET | `/api/metrics/productivity` | Fleet productivity |
| GET | `/api/metrics/agents` | Coordination metrics |
| GET | `/api/metrics/timeline` | Series + decision traces |
| POST | `/api/benchmark/run` | Fair benchmark |
| GET | `/api/benchmark/export` | JSON/CSV payload |
| GET | `/api/memory/*` | Incidents, runs, tractor profile |

## Tests

```bash
source .venv/bin/activate
cd backend && python -m pytest -q
```

---

Built for ATC Run the Fleet — working demo over complexity.
