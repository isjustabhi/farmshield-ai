"""Structured event log for every simulation state change."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .models import SimEvent


class EventLog:
    """Append-only event store keyed by monotonic IDs."""

    def __init__(self, on_emit: Callable[[SimEvent], None] | None = None) -> None:
        self._events: list[SimEvent] = []
        self._next_id = 1
        self._on_emit = on_emit

    def set_on_emit(self, on_emit: Callable[[SimEvent], None] | None) -> None:
        self._on_emit = on_emit

    def clear(self) -> None:
        self._events.clear()
        self._next_id = 1

    def emit(
        self,
        *,
        sim_time: int,
        event_type: str,
        message: str,
        tractor_id: str | None = None,
        job_id: str | None = None,
        field_id: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> SimEvent:
        event = SimEvent(
            id=self._next_id,
            sim_time=sim_time,
            event_type=event_type,
            message=message,
            tractor_id=tractor_id,
            job_id=job_id,
            field_id=field_id,
            data=data or {},
        )
        self._next_id += 1
        self._events.append(event)
        if self._on_emit is not None:
            self._on_emit(event)
        return event

    @property
    def events(self) -> list[SimEvent]:
        return list(self._events)

    def since(self, after_id: int) -> list[SimEvent]:
        return [event for event in self._events if event.id > after_id]
