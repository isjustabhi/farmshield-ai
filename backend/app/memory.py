"""Persistent farm operational memory (SQLite) — not chat/LLM memory."""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from threading import Lock
from typing import Any

from .models import (
    AgentTrace,
    AssignmentDecision,
    MemoryDecisionRecord,
    MemoryIncidentRecord,
    MemoryRunRecord,
    MemoryTractorProfile,
    RecoveryLogEntry,
    ScheduleResponse,
    SimEvent,
    SimilarIncidentOutcome,
)

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "farmshield.db"
BREAKDOWN_WARNING_THRESHOLD = 2


class OperationalMemory:
    """Append-only SQLite history + current-run in-memory recovery log.

    Historical rows never mutate live simulation state. Reset starts a new run_id
    and clears only ephemeral in-memory buffers.
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()
        self._current_run_id: str | None = None
        self._recovery_logs: list[RecoveryLogEntry] = []
        self._next_recovery_id = 1

    # ------------------------------------------------------------------ lifecycle
    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def clear(self) -> None:
        """Clear current-run in-memory recovery log only (does not wipe SQLite)."""
        with self._lock:
            self._recovery_logs.clear()
            self._next_recovery_id = 1

    def wipe_database(self) -> None:
        """Test helper: delete all historical rows."""
        with self._lock:
            for table in (
                "performance_summaries",
                "scheduling_decisions",
                "agent_traces",
                "incidents",
                "assignments",
                "job_events",
                "tractor_events",
                "simulation_runs",
            ):
                self._conn.execute(f"DELETE FROM {table}")
            self._conn.commit()
            self._recovery_logs.clear()
            self._next_recovery_id = 1
            self._current_run_id = None

    @property
    def current_run_id(self) -> str | None:
        return self._current_run_id

    def start_run(self, *, scenario_name: str, seed: int) -> str:
        with self._lock:
            if self._current_run_id is not None:
                self._end_run_unlocked(self._current_run_id)
            run_id = str(uuid.uuid4())
            self._conn.execute(
                """
                INSERT INTO simulation_runs (run_id, scenario_name, seed, status)
                VALUES (?, ?, ?, 'active')
                """,
                (run_id, scenario_name, seed),
            )
            self._conn.commit()
            self._current_run_id = run_id
            self._recovery_logs.clear()
            self._next_recovery_id = 1
            return run_id

    def end_current_run(self) -> None:
        with self._lock:
            if self._current_run_id is not None:
                self._end_run_unlocked(self._current_run_id)
                self._current_run_id = None

    def _end_run_unlocked(self, run_id: str) -> None:
        self._conn.execute(
            """
            UPDATE simulation_runs
            SET status = 'completed', ended_at = CURRENT_TIMESTAMP
            WHERE run_id = ? AND status = 'active'
            """,
            (run_id,),
        )
        self._conn.commit()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS simulation_runs (
                run_id TEXT PRIMARY KEY,
                scenario_name TEXT NOT NULL,
                seed INTEGER NOT NULL,
                started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                ended_at TEXT,
                status TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tractor_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                event_id INTEGER NOT NULL,
                simulation_time INTEGER NOT NULL,
                tractor_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL,
                correlation_id TEXT,
                field_id TEXT,
                payload_json TEXT NOT NULL DEFAULT '{}',
                UNIQUE(run_id, event_id),
                FOREIGN KEY(run_id) REFERENCES simulation_runs(run_id)
            );

            CREATE TABLE IF NOT EXISTS job_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                event_id INTEGER NOT NULL,
                simulation_time INTEGER NOT NULL,
                job_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL,
                correlation_id TEXT,
                tractor_id TEXT,
                field_id TEXT,
                payload_json TEXT NOT NULL DEFAULT '{}',
                UNIQUE(run_id, event_id, job_id),
                FOREIGN KEY(run_id) REFERENCES simulation_runs(run_id)
            );

            CREATE TABLE IF NOT EXISTS assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                decision_id TEXT NOT NULL,
                simulation_time INTEGER NOT NULL,
                correlation_id TEXT,
                tractor_id TEXT NOT NULL,
                job_id TEXT NOT NULL,
                explanation TEXT NOT NULL,
                estimated_travel_time REAL,
                estimated_work_time REAL,
                estimated_fuel_used REAL,
                predicted_finish REAL,
                deadline_margin REAL,
                score_total REAL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                UNIQUE(run_id, decision_id),
                FOREIGN KEY(run_id) REFERENCES simulation_runs(run_id)
            );

            CREATE TABLE IF NOT EXISTS incidents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                incident_key TEXT NOT NULL,
                simulation_time INTEGER NOT NULL,
                correlation_id TEXT,
                tractor_id TEXT NOT NULL,
                job_id TEXT,
                field_id TEXT,
                event_type TEXT NOT NULL,
                preserved_work_units REAL NOT NULL DEFAULT 0,
                percent_complete REAL,
                reassigned_to TEXT,
                blocking_reason TEXT,
                recovery_action TEXT,
                explanation TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                UNIQUE(run_id, incident_key),
                FOREIGN KEY(run_id) REFERENCES simulation_runs(run_id)
            );

            CREATE TABLE IF NOT EXISTS agent_traces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                trace_key TEXT NOT NULL,
                simulation_time INTEGER NOT NULL,
                correlation_id TEXT NOT NULL,
                decision_id TEXT,
                sender TEXT NOT NULL,
                receiver TEXT NOT NULL,
                request_type TEXT NOT NULL,
                response_type TEXT NOT NULL,
                duration_ms REAL NOT NULL,
                status TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                UNIQUE(run_id, trace_key),
                FOREIGN KEY(run_id) REFERENCES simulation_runs(run_id)
            );

            CREATE TABLE IF NOT EXISTS scheduling_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                cycle_key TEXT NOT NULL,
                simulation_time INTEGER NOT NULL,
                correlation_id TEXT,
                trigger TEXT NOT NULL,
                considered_pairs INTEGER NOT NULL,
                matching_score REAL NOT NULL,
                selected_json TEXT NOT NULL,
                rejections_json TEXT NOT NULL,
                explanation TEXT NOT NULL,
                UNIQUE(run_id, cycle_key),
                FOREIGN KEY(run_id) REFERENCES simulation_runs(run_id)
            );

            CREATE TABLE IF NOT EXISTS performance_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                simulation_time INTEGER NOT NULL,
                summary_key TEXT NOT NULL,
                metrics_json TEXT NOT NULL,
                UNIQUE(run_id, summary_key),
                FOREIGN KEY(run_id) REFERENCES simulation_runs(run_id)
            );
            """
        )
        self._conn.commit()

    def _require_run(self) -> str:
        if self._current_run_id is None:
            # Lazy start for early emits during bootstrap.
            run_id = str(uuid.uuid4())
            self._conn.execute(
                """
                INSERT INTO simulation_runs (run_id, scenario_name, seed, status)
                VALUES (?, 'bootstrap', 0, 'active')
                """,
                (run_id,),
            )
            self._conn.commit()
            self._current_run_id = run_id
        return self._current_run_id

    # ------------------------------------------------------------------ writers
    def persist_sim_event(self, event: SimEvent, correlation_id: str | None = None) -> None:
        with self._lock:
            run_id = self._require_run()
            corr = correlation_id or (event.data or {}).get("correlation_id")
            payload = json.dumps(event.data or {})
            if event.tractor_id:
                self._conn.execute(
                    """
                    INSERT OR IGNORE INTO tractor_events (
                        run_id, event_id, simulation_time, tractor_id, event_type,
                        message, correlation_id, field_id, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        event.id,
                        event.sim_time,
                        event.tractor_id,
                        event.event_type,
                        event.message,
                        corr,
                        event.field_id,
                        payload,
                    ),
                )
            if event.job_id:
                self._conn.execute(
                    """
                    INSERT OR IGNORE INTO job_events (
                        run_id, event_id, simulation_time, job_id, event_type,
                        message, correlation_id, tractor_id, field_id, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        event.id,
                        event.sim_time,
                        event.job_id,
                        event.event_type,
                        event.message,
                        corr,
                        event.tractor_id,
                        event.field_id,
                        payload,
                    ),
                )
            self._conn.commit()

    def persist_agent_trace(self, trace: AgentTrace) -> None:
        with self._lock:
            run_id = self._require_run()
            trace_key = (
                f"{trace.correlation_id}:{trace.sender}:{trace.receiver}:"
                f"{trace.request_type}:{trace.start_wall_time:.6f}"
            )
            self._conn.execute(
                """
                INSERT OR IGNORE INTO agent_traces (
                    run_id, trace_key, simulation_time, correlation_id, decision_id,
                    sender, receiver, request_type, response_type, duration_ms,
                    status, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    trace_key,
                    trace.simulation_timestamp,
                    trace.correlation_id,
                    trace.decision_id,
                    trace.sender,
                    trace.receiver,
                    trace.request_type,
                    trace.response_type,
                    trace.duration_ms,
                    trace.status,
                    json.dumps(trace.detail),
                ),
            )
            self._conn.commit()

    def persist_schedule_cycle(
        self,
        *,
        schedule: ScheduleResponse,
        correlation_id: str,
        trigger: str,
        applied: list[AssignmentDecision],
    ) -> None:
        with self._lock:
            run_id = self._require_run()
            cycle_key = f"{correlation_id}:{trigger}:{schedule.sim_time}"
            selected = [
                {
                    "tractor_id": a.tractor_id,
                    "job_id": a.job_id,
                    "decision_id": a.decision_id,
                    "selection_reason": a.selection_reason,
                    "score_total": a.score_components.total,
                }
                for a in applied
            ]
            rejections = [
                {"job_id": r.job_id, "reasons": r.reasons} for r in schedule.infeasible_jobs
            ]
            explanation = (
                f"Scheduling cycle trigger={trigger} selected={len(applied)} "
                f"considered_pairs={schedule.considered_pairs} "
                f"rejections={len(rejections)}"
            )
            self._conn.execute(
                """
                INSERT OR IGNORE INTO scheduling_decisions (
                    run_id, cycle_key, simulation_time, correlation_id, trigger,
                    considered_pairs, matching_score, selected_json, rejections_json,
                    explanation
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    cycle_key,
                    schedule.sim_time,
                    correlation_id,
                    trigger,
                    schedule.considered_pairs,
                    schedule.matching_score,
                    json.dumps(selected),
                    json.dumps(rejections),
                    explanation,
                ),
            )
            for decision in applied:
                self._conn.execute(
                    """
                    INSERT OR IGNORE INTO assignments (
                        run_id, decision_id, simulation_time, correlation_id,
                        tractor_id, job_id, explanation, estimated_travel_time,
                        estimated_work_time, estimated_fuel_used, predicted_finish,
                        deadline_margin, score_total, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        str(decision.decision_id),
                        decision.sim_time,
                        correlation_id,
                        decision.tractor_id,
                        decision.job_id,
                        decision.selection_reason,
                        decision.estimated_travel_time,
                        decision.estimated_work_time,
                        decision.estimated_fuel_used,
                        decision.predicted_finish,
                        decision.deadline_margin,
                        decision.score_components.total,
                        json.dumps(decision.score_components.model_dump()),
                    ),
                )
            self._conn.commit()

    def persist_performance_summary(
        self,
        *,
        simulation_time: int,
        metrics: dict[str, Any],
        summary_key: str = "agent_metrics",
    ) -> None:
        with self._lock:
            run_id = self._require_run()
            self._conn.execute(
                """
                INSERT OR REPLACE INTO performance_summaries (
                    run_id, simulation_time, summary_key, metrics_json
                ) VALUES (?, ?, ?, ?)
                """,
                (run_id, simulation_time, summary_key, json.dumps(metrics)),
            )
            self._conn.commit()

    def get_performance_summary(
        self,
        *,
        run_id: str,
        summary_key: str = "productivity",
    ) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT metrics_json FROM performance_summaries
                WHERE run_id = ? AND summary_key = ?
                ORDER BY simulation_time DESC, id DESC
                LIMIT 1
                """,
                (run_id, summary_key),
            ).fetchone()
            if row is None:
                return None
            return json.loads(row["metrics_json"])

    def query_agent_traces(
        self,
        *,
        run_id: str | None = None,
        agent: str | None = None,
        limit: int = 2000,
    ) -> list[AgentTrace]:
        clauses = ["1=1"]
        params: list[Any] = []
        if run_id:
            clauses.append("run_id = ?")
            params.append(run_id)
        if agent:
            clauses.append("(sender = ? OR receiver = ?)")
            params.extend([agent, agent])
        params.append(limit)
        sql = f"""
            SELECT * FROM agent_traces
            WHERE {' AND '.join(clauses)}
            ORDER BY id ASC
            LIMIT ?
        """
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
            out: list[AgentTrace] = []
            for r in rows:
                payload = json.loads(r["payload_json"] or "{}")
                out.append(
                    AgentTrace(
                        correlation_id=r["correlation_id"],
                        decision_id=r["decision_id"],
                        sender=r["sender"],
                        receiver=r["receiver"],
                        request_type=r["request_type"],
                        response_type=r["response_type"],
                        start_wall_time=0.0,
                        end_wall_time=0.0,
                        duration_ms=float(r["duration_ms"]),
                        status=r["status"],
                        simulation_timestamp=int(r["simulation_time"]),
                        transport="in_process",
                        detail=payload if isinstance(payload, dict) else {},
                    )
                )
            return out

    def append(self, entry: RecoveryLogEntry) -> RecoveryLogEntry:
        """Current-run recovery log + durable incident row."""
        with self._lock:
            stored = entry.model_copy(update={"id": self._next_recovery_id})
            self._next_recovery_id += 1
            self._recovery_logs.append(stored)

            run_id = self._require_run()
            incident_key = f"{stored.correlation_id}:{stored.event_type}:{stored.tractor_id}:{stored.id}"
            payload = stored.model_dump()
            self._conn.execute(
                """
                INSERT OR IGNORE INTO incidents (
                    run_id, incident_key, simulation_time, correlation_id, tractor_id,
                    job_id, field_id, event_type, preserved_work_units, percent_complete,
                    reassigned_to, blocking_reason, recovery_action, explanation, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    incident_key,
                    stored.sim_time,
                    stored.correlation_id,
                    stored.tractor_id,
                    stored.job_id,
                    stored.field_id,
                    stored.event_type,
                    stored.preserved_work_units,
                    stored.percent_complete,
                    stored.reassigned_to,
                    stored.blocking_reason,
                    (
                        f"reassigned_to={stored.reassigned_to}"
                        if stored.reassigned_to
                        else stored.blocking_reason or stored.event_type
                    ),
                    stored.explanation,
                    json.dumps(payload),
                ),
            )
            self._conn.commit()
            return stored

    def logs(self) -> list[RecoveryLogEntry]:
        with self._lock:
            return list(self._recovery_logs)

    # ------------------------------------------------------------------ queries
    def list_runs(self) -> list[MemoryRunRecord]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT run_id, scenario_name, seed, started_at, ended_at, status
                FROM simulation_runs
                ORDER BY started_at DESC
                """
            ).fetchall()
            return [
                MemoryRunRecord(
                    run_id=r["run_id"],
                    scenario_name=r["scenario_name"],
                    seed=r["seed"],
                    started_at=r["started_at"],
                    ended_at=r["ended_at"],
                    status=r["status"],
                )
                for r in rows
            ]

    def query_incidents(
        self,
        *,
        tractor_id: str | None = None,
        field_id: str | None = None,
        event_type: str | None = None,
        run_id: str | None = None,
        limit: int = 100,
    ) -> list[MemoryIncidentRecord]:
        clauses = ["1=1"]
        params: list[Any] = []
        if tractor_id:
            clauses.append("tractor_id = ?")
            params.append(tractor_id)
        if field_id:
            clauses.append("field_id = ?")
            params.append(field_id)
        if event_type:
            clauses.append("event_type = ?")
            params.append(event_type)
        if run_id:
            clauses.append("run_id = ?")
            params.append(run_id)
        params.append(limit)
        sql = f"""
            SELECT * FROM incidents
            WHERE {' AND '.join(clauses)}
            ORDER BY id DESC
            LIMIT ?
        """
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
            return [self._incident_from_row(r) for r in rows]

    def query_decisions(
        self,
        *,
        run_id: str | None = None,
        limit: int = 100,
    ) -> list[MemoryDecisionRecord]:
        clauses = ["1=1"]
        params: list[Any] = []
        if run_id:
            clauses.append("run_id = ?")
            params.append(run_id)
        params.append(limit)
        sql = f"""
            SELECT * FROM scheduling_decisions
            WHERE {' AND '.join(clauses)}
            ORDER BY id DESC
            LIMIT ?
        """
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
            out: list[MemoryDecisionRecord] = []
            for r in rows:
                out.append(
                    MemoryDecisionRecord(
                        run_id=r["run_id"],
                        cycle_key=r["cycle_key"],
                        simulation_time=r["simulation_time"],
                        correlation_id=r["correlation_id"],
                        trigger=r["trigger"],
                        considered_pairs=r["considered_pairs"],
                        matching_score=r["matching_score"],
                        selected=json.loads(r["selected_json"]),
                        rejections=json.loads(r["rejections_json"]),
                        explanation=r["explanation"],
                    )
                )
            return out

    def tractor_profile(self, tractor_id: str) -> MemoryTractorProfile:
        with self._lock:
            breakdowns = self._conn.execute(
                """
                SELECT COUNT(*) AS c FROM incidents
                WHERE tractor_id = ? AND event_type = 'breakdown'
                """,
                (tractor_id,),
            ).fetchone()["c"]
            repairs = self._conn.execute(
                """
                SELECT COUNT(*) AS c FROM incidents
                WHERE tractor_id = ? AND event_type = 'repair'
                """,
                (tractor_id,),
            ).fetchone()["c"]
            runs = self._conn.execute(
                """
                SELECT COUNT(DISTINCT run_id) AS c FROM incidents
                WHERE tractor_id = ? AND event_type = 'breakdown'
                """,
                (tractor_id,),
            ).fetchone()["c"]
            recent = self._conn.execute(
                """
                SELECT * FROM incidents
                WHERE tractor_id = ?
                ORDER BY id DESC
                LIMIT 10
                """,
                (tractor_id,),
            ).fetchall()
            similar = self._conn.execute(
                """
                SELECT * FROM incidents
                WHERE tractor_id = ? AND event_type = 'breakdown'
                ORDER BY id DESC
                LIMIT 5
                """,
                (tractor_id,),
            ).fetchall()

        warnings: list[str] = []
        if breakdowns >= BREAKDOWN_WARNING_THRESHOLD:
            warnings.append(
                f"Previous incident: Tractor {tractor_id} experienced {breakdowns} "
                f"breakdowns across recorded runs. Operator inspection recommended."
            )

        similar_outcomes = [
            SimilarIncidentOutcome(
                run_id=r["run_id"],
                simulation_time=r["simulation_time"],
                event_type=r["event_type"],
                job_id=r["job_id"],
                recovery_action=r["recovery_action"],
                explanation=r["explanation"],
                reassigned_to=r["reassigned_to"],
                blocking_reason=r["blocking_reason"],
            )
            for r in similar
        ]

        return MemoryTractorProfile(
            tractor_id=tractor_id,
            breakdown_count=breakdowns,
            repair_count=repairs,
            runs_with_breakdowns=runs,
            warnings=warnings,
            recent_incidents=[self._incident_from_row(r) for r in recent],
            similar_historical_outcomes=similar_outcomes,
            notes=(
                "Warnings are derived only from stored incident counts. "
                "No unvalidated failure prediction or causal diagnosis is claimed. "
                "Repaired tractors are not auto-excluded without an explicit safety rule."
            ),
        )

    @staticmethod
    def _incident_from_row(row: sqlite3.Row) -> MemoryIncidentRecord:
        return MemoryIncidentRecord(
            id=row["id"],
            run_id=row["run_id"],
            simulation_time=row["simulation_time"],
            correlation_id=row["correlation_id"],
            tractor_id=row["tractor_id"],
            job_id=row["job_id"],
            field_id=row["field_id"],
            event_type=row["event_type"],
            preserved_work_units=row["preserved_work_units"],
            percent_complete=row["percent_complete"],
            reassigned_to=row["reassigned_to"],
            blocking_reason=row["blocking_reason"],
            recovery_action=row["recovery_action"],
            explanation=row["explanation"],
        )


# Process-wide default (live server). Tests may construct isolated instances.
operational_memory = OperationalMemory()
recovery_memory = operational_memory
