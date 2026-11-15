"""LLM incident agents — talk when something goes wrong.

These agents do NOT assign jobs or bypass Safety. Deterministic Fleet/Nav/Safety/
Recovery still own commits. LLM agents exchange short messages after incidents
so operators (and judges) can hear the coordination story.
"""

from __future__ import annotations

import json
import time
import uuid
from threading import Lock
from typing import Any

import httpx
from pydantic import BaseModel, Field

from .llm_config import LLMSettings, get_llm_settings, reload_llm_settings


class AgentMessage(BaseModel):
    id: str
    correlation_id: str
    sim_time: int
    sender: str
    receiver: str
    content: str
    wall_time: float
    source: str = "llm"  # llm | fallback


class IncidentDialogue(BaseModel):
    correlation_id: str
    sim_time: int
    incident_type: str
    tractor_id: str
    job_id: str | None = None
    preserved_work_units: float = 0.0
    messages: list[AgentMessage] = Field(default_factory=list)
    llm_used: bool = False
    note: str = ""


class LLMAgentBus:
    """In-memory log of LLM agent-to-agent incident dialogues."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._dialogues: list[IncidentDialogue] = []

    def clear(self) -> None:
        with self._lock:
            self._dialogues.clear()

    def list_dialogues(self, limit: int = 40) -> list[IncidentDialogue]:
        with self._lock:
            return list(self._dialogues[-limit:])

    def record(self, dialogue: IncidentDialogue) -> IncidentDialogue:
        with self._lock:
            self._dialogues.append(dialogue)
            return dialogue


llm_agent_bus = LLMAgentBus()

_ROLES = {
    "fleet_llm": (
        "You are FarmShield Fleet Agent. Coordinate tractors and jobs. "
        "Be concise (1-2 sentences). Never invent fuel or progress numbers — use only facts given."
    ),
    "safety_llm": (
        "You are FarmShield Safety Agent. Enforce equipment match, fuel reserve, "
        "and no double-booking. Be concise (1-2 sentences). Reject unsafe ideas."
    ),
    "recovery_llm": (
        "You are FarmShield Recovery Agent. After breakdowns, preserve completed work "
        "and recommend replan. Be concise (1-2 sentences). Use only facts given."
    ),
}


def _chat(system: str, user: str) -> str:
    settings = get_llm_settings()
    if not settings.configured:
        raise RuntimeError("LLM not configured")
    if settings.provider == "anthropic":
        return _chat_anthropic(system, user, settings)
    return _chat_openai(system, user, settings)


def _chat_anthropic(system: str, user: str, settings: LLMSettings) -> str:
    url = f"{settings.base_url}/v1/messages"
    headers = {
        "x-api-key": settings.api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.model,
        "max_tokens": 220,
        "temperature": 0.2,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    with httpx.Client(timeout=settings.timeout_sec) as client:
        resp = client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
    parts = data.get("content") or []
    texts = [str(p.get("text", "")) for p in parts if p.get("type") == "text" or "text" in p]
    text = "".join(texts).strip()
    if not text:
        raise RuntimeError(f"Empty Anthropic response: {data}")
    return text


def _chat_openai(system: str, user: str, settings: LLMSettings) -> str:
    url = f"{settings.base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    with httpx.Client(timeout=settings.timeout_sec) as client:
        resp = client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
    return str(data["choices"][0]["message"]["content"]).strip()


def _fallback_messages(
    *,
    correlation_id: str,
    sim_time: int,
    tractor_id: str,
    job_id: str | None,
    reason: str,
    preserved: float,
    reassigned_to: str | None,
    blocking: str | None,
) -> list[AgentMessage]:
    """Deterministic dialogue if no API key — still shows agent communication."""
    now = time.time()
    msgs: list[AgentMessage] = []

    def add(sender: str, receiver: str, content: str) -> None:
        msgs.append(
            AgentMessage(
                id=str(uuid.uuid4()),
                correlation_id=correlation_id,
                sim_time=sim_time,
                sender=sender,
                receiver=receiver,
                content=content,
                wall_time=now,
                source="fallback",
            )
        )

    add(
        "fleet_llm",
        "recovery_llm",
        f"Incident on {tractor_id} ({reason}). Job {job_id or 'none'} released with "
        f"{preserved:.2f} work units preserved. Need recovery plan.",
    )
    add(
        "recovery_llm",
        "safety_llm",
        f"Propose replan for {job_id or 'idle fleet'} while keeping preserved progress "
        f"{preserved:.2f}. Do not regress completed work.",
    )
    if reassigned_to:
        add(
            "safety_llm",
            "fleet_llm",
            f"Approved path: reassign {job_id} to {reassigned_to} only if equipment and "
            f"fuel+reserve checks pass. Progress must stay ≥ {preserved:.2f}.",
        )
        add(
            "fleet_llm",
            "recovery_llm",
            f"Commit noted: {job_id} → {reassigned_to}. Monitoring for further faults.",
        )
    else:
        add(
            "safety_llm",
            "fleet_llm",
            f"No safe replacement yet"
            + (f" ({blocking})." if blocking else ".")
            + f" Keep {job_id or 'work'} pending with preserved {preserved:.2f}; do not invent progress.",
        )
        add(
            "fleet_llm",
            "recovery_llm",
            "Holding unsafe assigns. Will retry when a compatible idle tractor is free.",
        )
    return msgs


def run_incident_dialogue(
    *,
    sim_time: int,
    tractor_id: str,
    job_id: str | None,
    reason: str,
    preserved_work_units: float,
    percent_complete: float | None,
    reassigned_to: str | None,
    blocking_reason: str | None,
    correlation_id: str | None = None,
    incident_type: str = "breakdown",
) -> IncidentDialogue:
    """Fleet ↔ Recovery ↔ Safety LLM (or fallback) conversation after a bad event."""
    corr = correlation_id or str(uuid.uuid4())
    facts = {
        "sim_time": sim_time,
        "incident_type": incident_type,
        "tractor_id": tractor_id,
        "job_id": job_id,
        "reason": reason,
        "preserved_work_units": preserved_work_units,
        "percent_complete": percent_complete,
        "reassigned_to": reassigned_to,
        "blocking_reason": blocking_reason,
    }
    facts_json = json.dumps(facts, indent=2)
    settings = get_llm_settings()
    messages: list[AgentMessage] = []
    llm_used = False
    note = ""

    if settings.configured:
        try:
            # Round 1: Fleet alerts Recovery
            m1 = _chat(
                _ROLES["fleet_llm"],
                f"FACTS (JSON):\n{facts_json}\n\n"
                "Message Recovery Agent: what happened and what you need.",
            )
            messages.append(
                AgentMessage(
                    id=str(uuid.uuid4()),
                    correlation_id=corr,
                    sim_time=sim_time,
                    sender="fleet_llm",
                    receiver="recovery_llm",
                    content=m1,
                    wall_time=time.time(),
                )
            )
            # Round 2: Recovery asks Safety
            m2 = _chat(
                _ROLES["recovery_llm"],
                f"FACTS:\n{facts_json}\n\nFleet said:\n{m1}\n\n"
                "Message Safety Agent with your recovery recommendation.",
            )
            messages.append(
                AgentMessage(
                    id=str(uuid.uuid4()),
                    correlation_id=corr,
                    sim_time=sim_time,
                    sender="recovery_llm",
                    receiver="safety_llm",
                    content=m2,
                    wall_time=time.time(),
                )
            )
            # Round 3: Safety replies to Fleet
            m3 = _chat(
                _ROLES["safety_llm"],
                f"FACTS:\n{facts_json}\n\nRecovery said:\n{m2}\n\n"
                "Message Fleet: approve constraints or block unsafe reassignment.",
            )
            messages.append(
                AgentMessage(
                    id=str(uuid.uuid4()),
                    correlation_id=corr,
                    sim_time=sim_time,
                    sender="safety_llm",
                    receiver="fleet_llm",
                    content=m3,
                    wall_time=time.time(),
                )
            )
            llm_used = True
            note = "LLM agents exchanged messages; deterministic recovery already applied the plan."
        except Exception as exc:  # noqa: BLE001
            messages = _fallback_messages(
                correlation_id=corr,
                sim_time=sim_time,
                tractor_id=tractor_id,
                job_id=job_id,
                reason=reason,
                preserved=preserved_work_units,
                reassigned_to=reassigned_to,
                blocking=blocking_reason,
            )
            note = f"LLM call failed ({exc}); used deterministic agent dialogue fallback."
    else:
        messages = _fallback_messages(
            correlation_id=corr,
            sim_time=sim_time,
            tractor_id=tractor_id,
            job_id=job_id,
            reason=reason,
            preserved=preserved_work_units,
            reassigned_to=reassigned_to,
            blocking=blocking_reason,
        )
        note = (
            "No LLM_API_KEY in .env — deterministic agent dialogue only. "
            "Paste a key to enable live LLM talk."
        )

    dialogue = IncidentDialogue(
        correlation_id=corr,
        sim_time=sim_time,
        incident_type=incident_type,
        tractor_id=tractor_id,
        job_id=job_id,
        preserved_work_units=preserved_work_units,
        messages=messages,
        llm_used=llm_used,
        note=note,
    )
    return llm_agent_bus.record(dialogue)


def llm_status() -> dict[str, Any]:
    settings = reload_llm_settings()
    return {
        "enabled": settings.enabled,
        "configured": settings.configured,
        "provider": settings.provider,
        "model": settings.model,
        "base_url": settings.base_url,
        "api_key_present": bool(settings.api_key),
        "dialogue_count": len(llm_agent_bus.list_dialogues(limit=10_000)),
        "note": (
            "LLM agents explain incidents only; they do not bypass Safety or invent telemetry."
            if settings.configured
            else "Add LLM_API_KEY to .env and restart the API."
        ),
    }
