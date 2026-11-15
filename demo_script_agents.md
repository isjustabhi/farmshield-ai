# FarmShield AI: 90-Second Demo Script (agents focus)

Use this when judges ask about AI orchestration or how agents communicate.  
Same setup as `demo_script.md`. Live FastAPI values only.

## Before you start

Same as the main script: API on `:8000`, UI on `:5173`, then **Reset** → **Schedule**.

---

## 0–20s: Show the handshake

**Say:** Assignments are not a single black-box call. Fleet proposes, Navigation routes, Safety approves or rejects, then we commit.

**Do:**
1. Reset → Schedule.
2. Stay on Command Center. Point at **Agents talking** / assignment handshake.
3. Read one live exchange: Fleet → Nav → Safety → commit.
4. Open **Agent Network** and show traces: `fleet_agent → navigation_agent`, then `→ safety_agent`, with durations.

**Expect:** Traces and handshake match. Spray jobs on spray tractors only.

---

## 20–40s: Movement still under the same rules

**Say:** Play only advances the simulator. New assigns still go through the same agent path.

**Do:**
1. Click **Play** briefly, then Pause.
2. Point at a working tractor and its job progress.
3. Optional: click **Schedule** again if idle capacity exists; show new traces appear.

**Expect:** Progress and fuel change. New commits still have Nav + Safety traces.

---

## 40–65s: Failure forces agents to talk again

**Say:** On breakdown we keep completed work. Recovery asks for a replan. Fleet, Nav, and Safety run again. Optional Claude dialogue explains the incident; it does not bypass Safety.

**Do:**
1. Chaos Lab or Command Center: **Breakdown** on a working tractor.
2. Show preserved work on the released job.
3. Agent Network: new recovery-related traces and incident dialogue (Claude or fallback).
4. Confirm the broken tractor is not reassigned.

**Expect:** Job pending with preserved units. Replacement only if Safety approves.

---

## 65–90s: Memory and measured proof

**Say:** Traces and incidents are stored. Benchmarks compare FCFS vs FarmShield with the same Safety path.

**Do:**
1. Incident Memory: breakdown row.
2. Benchmark Lab: point at measured averages (or `benchmark_results.json`).
3. One line close: Safety is the gate; agents are visible; progress is never invented.

**Expect:** Judges can repeat Schedule → Breakdown → Agent Network without relying on slides.

---

## Quick lines if interrupted

| Question | Answer |
| --- | --- |
| Is this just function calling? | Code agents message each other in a fixed order. Safety can reject. The LLM only narrates incidents. |
| Where is the AI? | Orchestration in `orchestration.py` (AgentBus). Optional Claude for incident dialogue. |
| How do I see it? | Schedule, then Agent Network. Break a tractor, then incident dialogue. |

Details: `docs/ARCHITECTURE.md`.
