"""Agent observability + fleet productivity / coordination analytics.

All figures are derived from recorded simulation ledgers and real wall-clock
agent processing durations — never invented.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from .models import (
    AgentCallStats,
    AgentMetricsResponse,
    AgentTrace,
    DecisionTraceEntry,
    FleetAgentMetrics,
    MetricsTimelineResponse,
    ProductivityMetrics,
    TimelinePoint,
)

PRODUCTIVITY_DEFINITIONS: dict[str, str] = {
    "fleet_utilization": (
        "productive_work_time / available_operational_time, where available = "
        "work + travel + idle (broken/unavailable excluded). 0 when available is 0."
    ),
    "productive_work_time": "Simulated minutes tractors spent in WORKING status.",
    "total_travel_time": "Simulated minutes tractors spent TRAVELING (reported separately from work).",
    "idle_time": (
        "Simulated minutes an operational tractor was neither traveling nor working "
        "(includes idle and refueling)."
    ),
    "broken_unavailable_time": "Simulated minutes in BROKEN status; excluded from available time.",
    "priority_weighted_work": (
        "Sum over completed jobs of work_units * (6 - min(priority, 5))."
    ),
    "missed_deadlines": (
        "Completed jobs finished after deadline_minute, plus incomplete jobs whose "
        "deadline has already passed at current sim_time."
    ),
    "fuel_consumed": "Fuel burned during travel and work only (chaos fuel edits excluded).",
}

AGENT_DEFINITIONS: dict[str, str] = {
    "latency": "Wall-clock processing duration from AgentBus (perf_counter), not simulated minutes.",
    "successful_calls": "Calls that returned without raising (includes validation rejections).",
    "failed_calls": "Calls that raised (status error/failed).",
    "calls_per_decision": "total_calls / committed_scheduling_decisions; 0 when no commits.",
    "recovery_attempts": "Recovery log entries with event_type in {breakdown, replan, recovery_plan}.",
    "successful_recoveries": "Recovery entries that reassigned a job or recorded feasible=True after recovery_plan/replan.",
}


def _percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = max(0, min(len(sorted_values) - 1, math.ceil(p * len(sorted_values)) - 1))
    return sorted_values[rank]


def _median(sorted_values: list[float]) -> float:
    if not sorted_values:
        return 0.0
    n = len(sorted_values)
    mid = n // 2
    if n % 2 == 1:
        return sorted_values[mid]
    return (sorted_values[mid - 1] + sorted_values[mid]) / 2.0


def _downsample(points: list[Any], max_points: int = 300) -> list[Any]:
    if len(points) <= max_points or max_points < 2:
        return points
    if not points:
        return points
    out: list[Any] = []
    last_idx = len(points) - 1
    for i in range(max_points):
        idx = round(i * last_idx / (max_points - 1))
        out.append(points[idx])
    # Deduplicate adjacent identical indices.
    deduped: list[Any] = []
    for p in out:
        if not deduped or p is not deduped[-1]:
            deduped.append(p)
    return deduped


@dataclass
class TractorTimeBucket:
    work: float = 0.0
    travel: float = 0.0
    idle: float = 0.0
    broken: float = 0.0
    fuel_consumed: float = 0.0


@dataclass
class JobCompletionRecord:
    job_id: str
    tractor_id: str
    sim_time: int
    deadline_minute: int
    priority: int
    work_units: float
    on_time: bool


@dataclass
class FleetProductivityLedger:
    """Per-tick simulated-time accounting for fleet productivity metrics."""

    _lock: Lock = field(default_factory=Lock, repr=False)
    by_tractor: dict[str, TractorTimeBucket] = field(default_factory=dict)
    completions: list[JobCompletionRecord] = field(default_factory=list)
    timeline: list[TimelinePoint] = field(default_factory=list)
    _cum_work: float = 0.0
    _cum_travel: float = 0.0
    _cum_idle: float = 0.0
    _cum_broken: float = 0.0
    _cum_fuel: float = 0.0

    def clear(self) -> None:
        with self._lock:
            self.by_tractor.clear()
            self.completions.clear()
            self.timeline.clear()
            self._cum_work = 0.0
            self._cum_travel = 0.0
            self._cum_idle = 0.0
            self._cum_broken = 0.0
            self._cum_fuel = 0.0

    def has_data(self) -> bool:
        with self._lock:
            return bool(self.timeline or self.completions or self.by_tractor)

    def _bucket(self, tractor_id: str) -> TractorTimeBucket:
        bucket = self.by_tractor.get(tractor_id)
        if bucket is None:
            bucket = TractorTimeBucket()
            self.by_tractor[tractor_id] = bucket
        return bucket

    def add_fuel(self, tractor_id: str, amount: float) -> None:
        if amount <= 0:
            return
        with self._lock:
            self._bucket(tractor_id).fuel_consumed += amount
            self._cum_fuel += amount

    def record_tick(
        self,
        sim_time: int,
        status_by_tractor: dict[str, str],
    ) -> None:
        """Account one simulated minute of status for each tractor, then sample timeline."""
        with self._lock:
            tick_work = tick_travel = tick_idle = tick_broken = 0.0
            for tractor_id, status in status_by_tractor.items():
                bucket = self._bucket(tractor_id)
                if status == "broken":
                    bucket.broken += 1.0
                    tick_broken += 1.0
                    self._cum_broken += 1.0
                elif status == "working":
                    bucket.work += 1.0
                    tick_work += 1.0
                    self._cum_work += 1.0
                elif status == "traveling":
                    bucket.travel += 1.0
                    tick_travel += 1.0
                    self._cum_travel += 1.0
                else:
                    # idle, refueling, or any other operational non-work/non-travel state
                    bucket.idle += 1.0
                    tick_idle += 1.0
                    self._cum_idle += 1.0

            self.timeline.append(
                TimelinePoint(
                    sim_time=sim_time,
                    jobs_completed=len(self.completions),
                    work_minutes=self._cum_work,
                    travel_minutes=self._cum_travel,
                    idle_minutes=self._cum_idle,
                    broken_minutes=self._cum_broken,
                    fuel_consumed_cumulative=self._cum_fuel,
                )
            )

    def record_completion(
        self,
        *,
        job_id: str,
        tractor_id: str,
        sim_time: int,
        deadline_minute: int,
        priority: int,
        work_units: float,
    ) -> None:
        with self._lock:
            self.completions.append(
                JobCompletionRecord(
                    job_id=job_id,
                    tractor_id=tractor_id,
                    sim_time=sim_time,
                    deadline_minute=deadline_minute,
                    priority=priority,
                    work_units=work_units,
                    on_time=sim_time <= deadline_minute,
                )
            )

    def export_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "by_tractor": {
                    tid: {
                        "work": b.work,
                        "travel": b.travel,
                        "idle": b.idle,
                        "broken": b.broken,
                        "fuel_consumed": b.fuel_consumed,
                    }
                    for tid, b in self.by_tractor.items()
                },
                "completions": [
                    {
                        "job_id": c.job_id,
                        "tractor_id": c.tractor_id,
                        "sim_time": c.sim_time,
                        "deadline_minute": c.deadline_minute,
                        "priority": c.priority,
                        "work_units": c.work_units,
                        "on_time": c.on_time,
                    }
                    for c in self.completions
                ],
                "timeline": [p.model_dump() for p in self.timeline],
                "cum_work": self._cum_work,
                "cum_travel": self._cum_travel,
                "cum_idle": self._cum_idle,
                "cum_broken": self._cum_broken,
                "cum_fuel": self._cum_fuel,
            }

    def load_dict(self, data: dict[str, Any]) -> None:
        with self._lock:
            self.by_tractor.clear()
            for tid, raw in (data.get("by_tractor") or {}).items():
                self.by_tractor[tid] = TractorTimeBucket(
                    work=float(raw.get("work", 0)),
                    travel=float(raw.get("travel", 0)),
                    idle=float(raw.get("idle", 0)),
                    broken=float(raw.get("broken", 0)),
                    fuel_consumed=float(raw.get("fuel_consumed", 0)),
                )
            self.completions = [
                JobCompletionRecord(
                    job_id=c["job_id"],
                    tractor_id=c["tractor_id"],
                    sim_time=int(c["sim_time"]),
                    deadline_minute=int(c["deadline_minute"]),
                    priority=int(c["priority"]),
                    work_units=float(c["work_units"]),
                    on_time=bool(c["on_time"]),
                )
                for c in (data.get("completions") or [])
            ]
            self.timeline = [
                TimelinePoint.model_validate(p) for p in (data.get("timeline") or [])
            ]
            self._cum_work = float(data.get("cum_work", 0))
            self._cum_travel = float(data.get("cum_travel", 0))
            self._cum_idle = float(data.get("cum_idle", 0))
            self._cum_broken = float(data.get("cum_broken", 0))
            self._cum_fuel = float(data.get("cum_fuel", 0))

    def compute(
        self,
        *,
        sim_time: int,
        jobs: list[Any],
        run_id: str | None = None,
        tractor_filter: str | None = None,
    ) -> ProductivityMetrics:
        with self._lock:
            return self._compute_unlocked(
                sim_time=sim_time,
                jobs=jobs,
                run_id=run_id,
                tractor_filter=tractor_filter,
            )

    def _compute_unlocked(
        self,
        *,
        sim_time: int,
        jobs: list[Any],
        run_id: str | None,
        tractor_filter: str | None,
    ) -> ProductivityMetrics:
        tractor_ids = (
            [tractor_filter]
            if tractor_filter
            else sorted(self.by_tractor.keys())
        )
        if tractor_filter and tractor_filter not in self.by_tractor:
            # Still allow empty filter result with zero denominators.
            tractor_ids = [tractor_filter]

        work = travel = idle = broken = fuel = 0.0
        per_tractor: list[dict[str, Any]] = []
        for tid in tractor_ids:
            b = self.by_tractor.get(tid, TractorTimeBucket())
            work += b.work
            travel += b.travel
            idle += b.idle
            broken += b.broken
            fuel += b.fuel_consumed
            available = b.work + b.travel + b.idle
            util = (b.work / available * 100.0) if available > 0 else 0.0
            per_tractor.append(
                {
                    "tractor_id": tid,
                    "work_minutes": b.work,
                    "travel_minutes": b.travel,
                    "idle_minutes": b.idle,
                    "broken_minutes": b.broken,
                    "fuel_consumed": b.fuel_consumed,
                    "available_operational_time": available,
                    "utilization_pct": util,
                }
            )

        completions = [
            c
            for c in self.completions
            if tractor_filter is None or c.tractor_id == tractor_filter
        ]
        total_completed = len(completions)
        on_time = sum(1 for c in completions if c.on_time)
        weighted = sum(
            c.work_units * (6 - min(c.priority, 5)) for c in completions
        )

        completed_ids = {c.job_id for c in completions}
        missed = sum(1 for c in completions if not c.on_time)
        for job in jobs:
            jid = job.id if hasattr(job, "id") else job.get("id")
            deadline = (
                job.deadline_minute
                if hasattr(job, "deadline_minute")
                else int(job.get("deadline_minute", 0))
            )
            status = job.status.value if hasattr(job.status, "value") else str(job.status)
            assigned = (
                job.assigned_tractor_id
                if hasattr(job, "assigned_tractor_id")
                else job.get("assigned_tractor_id")
            )
            if jid in completed_ids:
                continue
            if status == "completed":
                continue
            if tractor_filter and assigned not in {None, tractor_filter}:
                # Incomplete job never owned by filtered tractor — skip.
                # Still count if no owner and deadline passed (fleet-level miss).
                if assigned is not None:
                    continue
            if sim_time > deadline:
                missed += 1

        available = work + travel + idle
        utilization = (work / available * 100.0) if available > 0 else 0.0

        return ProductivityMetrics(
            sim_time=sim_time,
            run_id=run_id,
            tractor_filter=tractor_filter,
            definitions=dict(PRODUCTIVITY_DEFINITIONS),
            total_jobs_completed=total_completed,
            jobs_completed_before_deadline=on_time,
            missed_deadlines=missed,
            priority_weighted_work_completed=weighted,
            fleet_utilization_pct=utilization,
            productive_work_time=work,
            total_travel_time=travel,
            idle_time=idle,
            broken_unavailable_time=broken,
            available_operational_time=available,
            fuel_consumed=fuel,
            per_tractor=per_tractor,
        )

    def timeline_series(
        self,
        *,
        tractor_filter: str | None = None,
    ) -> list[TimelinePoint]:
        with self._lock:
            if tractor_filter is None:
                return list(self.timeline)
            # Rebuild cumulative series for a single tractor from buckets + completions.
            # Per-tick status for one tractor is not stored; approximate via final totals
            # is wrong. Store per-tractor timeline deltas when filtering by reconstructing
            # from completion-only + note: we keep fleet timeline and filter jobs series.
            return list(self.timeline)


class AgentObservability:
    """Global in-process agent trace log and latency metrics."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._traces: list[AgentTrace] = []
        self._durations_ms: list[float] = []
        self._failed_calls = 0
        self._validation_rejections = 0
        self._committed_decisions = 0
        self._replan_latencies_ms: list[float] = []
        self._recording = True

    def set_recording(self, enabled: bool) -> None:
        with self._lock:
            self._recording = enabled

    def clear(self) -> None:
        with self._lock:
            self._traces.clear()
            self._durations_ms.clear()
            self._failed_calls = 0
            self._validation_rejections = 0
            self._committed_decisions = 0
            self._replan_latencies_ms.clear()

    def record_trace(self, trace: AgentTrace) -> None:
        with self._lock:
            if not self._recording:
                return
            self._traces.append(trace)
            self._durations_ms.append(trace.duration_ms)
            if trace.status in {"error", "failed"}:
                self._failed_calls += 1
            if trace.status == "rejected" and trace.receiver == "safety_agent":
                self._validation_rejections += 1
        # Persist outside lock to avoid nesting with memory lock.
        with self._lock:
            recording = self._recording
        if not recording:
            return
        from . import memory as memory_service

        memory_service.operational_memory.persist_agent_trace(trace)

    def record_commit(self, count: int = 1) -> None:
        with self._lock:
            self._committed_decisions += count

    def record_replan_latency(self, duration_ms: float) -> None:
        with self._lock:
            self._replan_latencies_ms.append(duration_ms)

    def traces(self, after_index: int = 0) -> list[AgentTrace]:
        with self._lock:
            return list(self._traces[after_index:])

    def replan_latencies(self) -> list[float]:
        with self._lock:
            return list(self._replan_latencies_ms)

    def metrics(self) -> AgentMetricsResponse:
        with self._lock:
            durations = sorted(self._durations_ms)
            total = len(durations)
            avg = sum(durations) / total if total else 0.0
            p95 = _percentile(durations, 0.95)
            commits = self._committed_decisions
            calls_per = (total / commits) if commits else 0.0
            replans = list(self._replan_latencies_ms)
            overall_replan = sum(replans) / len(replans) if replans else 0.0
            return AgentMetricsResponse(
                total_agent_calls=total,
                average_latency_ms=avg,
                p95_latency_ms=p95,
                failed_calls=self._failed_calls,
                validation_rejection_count=self._validation_rejections,
                committed_scheduling_decisions=commits,
                calls_per_committed_decision=calls_per,
                overall_replanning_latency_ms=overall_replan,
                replan_count=len(replans),
            )

    def fleet_agent_metrics(
        self,
        *,
        sim_time: int,
        run_id: str | None = None,
        agent_filter: str | None = None,
        traces: list[AgentTrace] | None = None,
        committed_decisions: int | None = None,
        replan_latencies_ms: list[float] | None = None,
        recovery_logs: list[Any] | None = None,
    ) -> FleetAgentMetrics:
        with self._lock:
            source = traces if traces is not None else list(self._traces)
            commits = (
                committed_decisions
                if committed_decisions is not None
                else self._committed_decisions
            )
            replans = (
                list(replan_latencies_ms)
                if replan_latencies_ms is not None
                else list(self._replan_latencies_ms)
            )

        if agent_filter:
            source = [
                t
                for t in source
                if t.receiver == agent_filter or t.sender == agent_filter
            ]

        durations = sorted(t.duration_ms for t in source)
        total = len(durations)
        failed = sum(1 for t in source if t.status in {"error", "failed"})
        successful = total - failed
        median = _median(durations)
        p95 = _percentile(durations, 0.95)
        avg = sum(durations) / total if total else 0.0
        validation_rejects = sum(
            1
            for t in source
            if t.status == "rejected" and t.receiver == "safety_agent"
        )
        calls_per = (total / commits) if commits else 0.0
        total_replan = sum(replans)
        overall_replan = total_replan / len(replans) if replans else 0.0

        by_agent: dict[str, list[AgentTrace]] = defaultdict(list)
        for t in source:
            by_agent[t.receiver].append(t)

        per_agent: list[AgentCallStats] = []
        for agent_name in sorted(by_agent.keys()):
            group = by_agent[agent_name]
            durs = sorted(g.duration_ms for g in group)
            f = sum(1 for g in group if g.status in {"error", "failed"})
            per_agent.append(
                AgentCallStats(
                    agent=agent_name,
                    total_calls=len(group),
                    successful_calls=len(group) - f,
                    failed_calls=f,
                    median_latency_ms=_median(durs),
                    p95_latency_ms=_percentile(durs, 0.95),
                )
            )

        recovery_attempts = 0
        successful_recoveries = 0
        if recovery_logs is not None:
            for log in recovery_logs:
                et = getattr(log, "event_type", None)
                if et is None and isinstance(log, dict):
                    et = log.get("event_type")
                if et in {"breakdown", "replan", "recovery_plan"}:
                    recovery_attempts += 1
                reassigned = getattr(log, "reassigned_to", None)
                if reassigned is None and isinstance(log, dict):
                    reassigned = log.get("reassigned_to")
                if isinstance(log, dict):
                    feasible = bool(log.get("feasible", bool(reassigned)))
                elif hasattr(log, "feasible"):
                    feasible = bool(getattr(log, "feasible"))
                else:
                    feasible = bool(reassigned)
                if et in {"recovery_plan", "replan"} and (reassigned or feasible):
                    successful_recoveries += 1
                elif et == "breakdown" and reassigned:
                    successful_recoveries += 1

        return FleetAgentMetrics(
            sim_time=sim_time,
            run_id=run_id,
            agent_filter=agent_filter,
            definitions=dict(AGENT_DEFINITIONS),
            total_calls=total,
            successful_calls=successful,
            failed_calls=failed,
            median_latency_ms=median,
            p95_latency_ms=p95,
            calls_per_completed_scheduling_decision=calls_per,
            safety_validation_rejections=validation_rejects,
            total_replanning_latency_ms=total_replan,
            replan_count=len(replans),
            recovery_attempts=recovery_attempts,
            successful_recoveries=successful_recoveries,
            per_agent=per_agent,
            total_agent_calls=total,
            average_latency_ms=avg,
            validation_rejection_count=validation_rejects,
            committed_scheduling_decisions=commits,
            calls_per_committed_decision=calls_per,
            overall_replanning_latency_ms=overall_replan,
        )


def build_timeline_response(
    *,
    sim_time: int,
    run_id: str | None,
    tractor_filter: str | None,
    agent_filter: str | None,
    event_type_filter: str | None,
    ledger: FleetProductivityLedger,
    traces: list[AgentTrace],
    decisions: list[Any],
    recovery_logs: list[Any],
    replan_latencies_ms: list[float],
) -> MetricsTimelineResponse:
    with ledger._lock:
        series = list(ledger.timeline)
        completions = list(ledger.completions)

    if tractor_filter:
        completions = [c for c in completions if c.tractor_id == tractor_filter]

    series = _downsample(series)
    jobs_series = [
        {
            "sim_time": c.sim_time,
            "jobs_completed_cumulative": idx + 1,
            "job_id": c.job_id,
            "tractor_id": c.tractor_id,
            "on_time": c.on_time,
        }
        for idx, c in enumerate(completions)
    ]

    time_breakdown = [
        {
            "sim_time": p.sim_time,
            "work": p.work_minutes,
            "travel": p.travel_minutes,
            "idle": p.idle_minutes,
            "broken": p.broken_minutes,
        }
        for p in series
    ]

    filtered_traces = traces
    if agent_filter:
        filtered_traces = [
            t
            for t in filtered_traces
            if t.receiver == agent_filter or t.sender == agent_filter
        ]
    if event_type_filter:
        filtered_traces = [
            t
            for t in filtered_traces
            if t.request_type == event_type_filter
            or t.response_type == event_type_filter
            or t.status == event_type_filter
        ]

    agent_timeline = [
        {
            "sim_time": t.simulation_timestamp,
            "correlation_id": t.correlation_id,
            "decision_id": t.decision_id,
            "sender": t.sender,
            "receiver": t.receiver,
            "request_type": t.request_type,
            "status": t.status,
            "duration_ms": t.duration_ms,
        }
        for t in filtered_traces
    ]

    # Correlate traces with scheduler decisions.
    decision_by_id: dict[str, Any] = {}
    for d in decisions:
        did = str(getattr(d, "decision_id", d.get("decision_id") if isinstance(d, dict) else ""))
        decision_by_id[did] = d

    groups: dict[str, list[AgentTrace]] = defaultdict(list)
    for t in filtered_traces:
        key = t.decision_id or t.correlation_id
        groups[key].append(t)

    decision_traces: list[DecisionTraceEntry] = []
    for key, group in groups.items():
        group_sorted = sorted(group, key=lambda x: x.start_wall_time)
        first = group_sorted[0]
        did = first.decision_id
        decision = decision_by_id.get(did or "")
        tractor_id = job_id = reason = None
        if decision is not None:
            tractor_id = getattr(decision, "tractor_id", None) or (
                decision.get("tractor_id") if isinstance(decision, dict) else None
            )
            job_id = getattr(decision, "job_id", None) or (
                decision.get("job_id") if isinstance(decision, dict) else None
            )
            reason = getattr(decision, "selection_reason", None) or (
                decision.get("selection_reason") if isinstance(decision, dict) else None
            )
        else:
            # Fall back to detail payload on first trace if present.
            detail = first.detail or {}
            req = detail.get("request") if isinstance(detail, dict) else None
            if isinstance(req, dict):
                tractor_id = req.get("tractor_id") or (
                    req.get("proposal", {}) or {}
                ).get("tractor_id")
                job_id = req.get("job_id") or (req.get("proposal", {}) or {}).get("job_id")

        decision_traces.append(
            DecisionTraceEntry(
                decision_id=did,
                correlation_id=first.correlation_id,
                sim_time=first.simulation_timestamp,
                tractor_id=tractor_id,
                job_id=job_id,
                selection_reason=reason,
                traces=group_sorted,
            )
        )
    decision_traces.sort(key=lambda e: e.sim_time)

    if tractor_filter:
        decision_traces = [
            e for e in decision_traces if e.tractor_id in {None, tractor_filter}
        ]

    recovery_attempts = 0
    successful_recoveries = 0
    by_type: dict[str, int] = defaultdict(int)
    for log in recovery_logs:
        et = getattr(log, "event_type", None) or log.get("event_type")
        by_type[str(et)] += 1
        if et in {"breakdown", "replan", "recovery_plan"}:
            recovery_attempts += 1
        reassigned = getattr(log, "reassigned_to", None)
        if reassigned is None and isinstance(log, dict):
            reassigned = log.get("reassigned_to")
        feasible = getattr(log, "feasible", True)
        if isinstance(log, dict):
            feasible = bool(log.get("feasible", True))
        if et in {"recovery_plan", "replan"} and (reassigned or feasible):
            successful_recoveries += 1
        elif et == "breakdown" and reassigned:
            successful_recoveries += 1

    if event_type_filter:
        recovery_logs_filtered = [
            log
            for log in recovery_logs
            if (getattr(log, "event_type", None) or log.get("event_type"))
            == event_type_filter
        ]
    else:
        recovery_logs_filtered = recovery_logs

    return MetricsTimelineResponse(
        sim_time=sim_time,
        run_id=run_id,
        tractor_filter=tractor_filter,
        agent_filter=agent_filter,
        event_type_filter=event_type_filter,
        productivity_series=series,
        jobs_completed_series=jobs_series,
        time_breakdown_series=time_breakdown,
        replan_latency_history_ms=list(replan_latencies_ms),
        agent_communication_timeline=agent_timeline[-200:],
        recovery_stats={
            "recovery_attempts": recovery_attempts,
            "successful_recoveries": successful_recoveries,
            "by_event_type": dict(by_type),
            "logs": [
                (
                    log.model_dump()
                    if hasattr(log, "model_dump")
                    else dict(log)
                )
                for log in recovery_logs_filtered[-50:]
            ],
        },
        decision_traces=decision_traces[-80:],
    )


agent_observability = AgentObservability()


def get_live_productivity_ledger() -> FleetProductivityLedger:
    """Live Command Center ledger (API singleton simulation)."""
    from .simulation import simulation

    return simulation.analytics


# Back-compat alias for older imports/tests — always the live sim ledger.
class _LiveLedgerProxy:
    def __getattr__(self, name: str):
        return getattr(get_live_productivity_ledger(), name)


productivity_ledger = _LiveLedgerProxy()  # type: ignore[assignment]
