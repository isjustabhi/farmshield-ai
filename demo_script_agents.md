# FarmShield AI: 90-Second Demo Script (agents)

Alternate walkthrough focused on orchestration. Same setup as `demo_script.md`.

## Before you start

API on `:8000`, UI on `:5173`, then **Reset** → **Schedule**.

---

## 0–20s: Assignment handshake

**Say:** Fleet proposes, Navigation routes, Safety approves or rejects, then the job is committed.

**Do:**
1. Reset → Schedule.
2. On Command Center, show the assignment handshake panel.
3. Open **Agent Network** and show traces: `fleet_agent → navigation_agent`, then `→ safety_agent`.

**Expect:** Compatible jobs only. Traces match the handshake.

---

## 20–40s: Live simulation

**Say:** Play advances the simulator. New assignments still use the same agent path.

**Do:**
1. Play briefly, then Pause.
2. Point at tractor progress and fuel.
3. Optional: Schedule again and show new traces.

---

## 40–65s: Breakdown and recovery

**Say:** Completed work is preserved. Recovery requests a replan. Fleet, Navigation, and Safety validate again. Optional Claude dialogue describes the incident; it does not bypass Safety.

**Do:**
1. Breakdown on a working tractor.
2. Show preserved work on the released job.
3. Agent Network: recovery traces and incident dialogue.
4. Confirm the broken tractor is not reassigned.

---

## 65–90s: Memory and benchmarks

**Do:**
1. Incident Memory: breakdown entry.
2. Benchmark Lab: FCFS vs FarmShield averages (or `benchmark_results.json`).

Reference: `docs/ARCHITECTURE.md`.
