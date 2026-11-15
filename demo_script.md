# FarmShield AI: 90-Second Demo Script

Live demo for judges. Values come from the running FastAPI simulator.

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

**Say:** FarmShield assigns field jobs only after Safety checks equipment, fuel reserve, and one job per tractor.

**Do:**
1. Reset → Schedule.
2. Point at the farm grid: three tractors should own compatible jobs (spray with spray, mow with mow).
3. Point at **Agents talking** / farm handshake: Fleet asked Nav, then Safety, then commit.

**Expect:** Compatible assignments only. No double-booking.

---

## 15–30s: Live movement and progress

**Say:** The clock is simulated minutes. Tractors travel with A*, then burn real work units and fuel.

**Do:**
1. Click **Play** (about 0.4s wall-clock per sim minute) or **Step**.
2. Watch paths and job progress increase.
3. Glance at the event feed: travel, arrival, job start, progress.

**Expect:** Positions change. Fuel drops. Progress is fractional and honest.

---

## 30–45s: Tractor failure

**Say:** Break a tractor mid-job. We keep completed work. We do not invent progress.

**Do:**
1. Pause if the grid is hard to read.
2. On Command Center or **Chaos Lab**, pick a tractor that is **working**.
3. Click **Breakdown**.

**Expect:** Tractor is `broken`. Job goes `pending`. Preserved `completed_work_units` stay on the job.

---

## 45–60s: Safe recovery

**Say:** Recovery asks for a replan. Fleet, Nav, and Safety run the same handshake before any reassign.

**Do:**
1. Show the recovery explanation if it already ran.
2. Otherwise click **Schedule** / **Replan**.
3. Same job id: progress is at least the preserved value. A free compatible tractor may take it. The broken one is not selected.

**Expect:** No progress loss. No unsafe assign.

---

## 60–75s: Agent communication and memory

**Say:** Orchestration is turn-taking. Fleet proposes, Nav routes, Safety approves or rejects. Each hop is logged with real latency.

**Do:**
1. Open **Agent Network**: traces show `fleet_agent → navigation_agent` and `→ safety_agent`.
2. Show incident dialogue if Claude (or fallback) ran after the breakdown.
3. Open **Incident Memory**: breakdown row with preserved work.
4. Optional: Chaos Lab → **Block route** → obstacle appears, routes change.

---

## 75–90s: Measured baseline

**Say:** Benchmark Lab compares FCFS vs FarmShield on independent sims. These numbers are measured.

**Do:**
1. Open **Benchmark Lab**.
2. If empty, click **Run benchmark** (or show `benchmark_results.json`).
3. Point at averages:
   - Jobs completed / on-time / priority-weighted work up
   - Missed deadlines down
   - Travel / fuel may be higher (say that honestly)
4. Offer CSV/JSON if asked.

**Measured averages (horizon 300, 1 main + 20 variants):**

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

## Backup if the UI misbehaves

```bash
curl -s -X POST http://127.0.0.1:8000/api/simulation/reset
curl -s -X POST http://127.0.0.1:8000/api/schedule
curl -s -X POST http://127.0.0.1:8000/api/simulation/play
# after ~10s
curl -s -X POST http://127.0.0.1:8000/api/events/breakdown \
  -H 'Content-Type: application/json' \
  -d '{"tractor_id":"tractor_01","reason":"demo"}'
curl -s http://127.0.0.1:8000/api/events | python -m json.tool | head
```

Captured run: repo-root `demo_event_log.json` from `backend/scripts/generate_demo_and_verify.py`.
