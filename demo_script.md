# FarmShield AI: 90-Second Demo Script

Live demonstration for judges. UI values come from the running FastAPI simulator.

## Before you start (once)

```bash
cd "/path/to/FarmShield AI"
source .venv/bin/activate
cd backend && uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

```bash
cd frontend && npm run dev -- --host 127.0.0.1 --port 5173
```

Open **http://127.0.0.1:5173** → Command Center. Click **Reset**, then **Schedule**.

---

## 0–15s: Tractors receive jobs

**Say:** FarmShield assigns jobs only after Safety checks equipment, fuel reserve, and single ownership.

**Do:**
1. Reset → Schedule.
2. Show the farm grid: three tractors own compatible jobs.
3. Show the assignment handshake / Agent Network traces (Fleet → Nav → Safety).

**Expect:** Compatible assignments only. No double-booking.

---

## 15–30s: Live movement and progress

**Say:** Simulated minutes. A* travel, then work units and fuel decrease.

**Do:**
1. Play (about 0.4s per sim minute) or Step.
2. Watch paths and job progress.
3. Check the event feed.

**Expect:** Positions and fuel change. Progress is fractional.

---

## 30–45s: Tractor failure

**Say:** Break a tractor mid-job. Completed work is preserved.

**Do:**
1. Pause if needed.
2. Select a working tractor.
3. Breakdown.

**Expect:** Tractor `broken`. Job `pending` with preserved `completed_work_units`.

---

## 45–60s: Recovery

**Say:** Recovery requests a replan. Fleet, Navigation, and Safety validate before reassign.

**Do:**
1. Show recovery explanation if already present.
2. Otherwise Schedule / Replan.
3. Same job id: progress is at least the preserved value. Broken tractor is not selected.

---

## 60–75s: Traces and memory

**Say:** Each agent hop is logged with wall-clock latency.

**Do:**
1. Agent Network: `fleet_agent → navigation_agent` and `→ safety_agent`.
2. Incident dialogue after breakdown (Claude or fallback).
3. Incident Memory: breakdown row.
4. Optional: block a route in Chaos Lab.

---

## 75–90s: Benchmark

**Say:** Benchmark Lab compares FCFS and FarmShield on independent sims. Numbers are measured.

**Do:**
1. Open Benchmark Lab.
2. Run benchmark if needed (or show `benchmark_results.json`).
3. Note completion / on-time gains and any travel or fuel increase.

| Metric | FCFS | FarmShield | Δ% |
| --- | ---: | ---: | ---: |
| Jobs completed | 9.86 | 10.00 | +1.45% |
| On-time completions | 9.86 | 10.00 | +1.45% |
| Priority-weighted work | 236.1 | 239.1 | +1.29% |
| Idle time | 741.0 | 735.1 | −0.80% |
| Missed deadlines | 0.14 | 0.00 | −100% |
| Travel time | 67.1 | 72.3 | +7.66% (worse) |
| Fuel consumed | 70.5 | 74.8 | +6.15% (worse) |

---

## API backup

```bash
curl -s -X POST http://127.0.0.1:8000/api/simulation/reset
curl -s -X POST http://127.0.0.1:8000/api/schedule
curl -s -X POST http://127.0.0.1:8000/api/simulation/play
curl -s -X POST http://127.0.0.1:8000/api/events/breakdown \
  -H 'Content-Type: application/json' \
  -d '{"tractor_id":"tractor_01","reason":"demo"}'
```

Event capture: `demo_event_log.json` via `backend/scripts/generate_demo_and_verify.py`.
