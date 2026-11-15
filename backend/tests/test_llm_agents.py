"""LLM incident agents — fallback dialogue without API key."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.llm_agents import llm_agent_bus, run_incident_dialogue
from app.llm_config import reload_llm_settings
from app.main import app
from app.orchestration import breakdown_and_recover, schedule_and_apply
from app.scheduler import fleet_agent
from app.simulation import SimulationService


@pytest.fixture
def sim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimulationService:
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("LLM_AGENTS_ENABLED", "true")
    reload_llm_settings()
    llm_agent_bus.clear()

    from app import memory as memory_service

    db = tmp_path / "llm_test.db"
    mem = memory_service.OperationalMemory(db_path=db)
    monkeypatch.setattr(memory_service, "operational_memory", mem)
    monkeypatch.setattr(memory_service, "recovery_memory", mem)

    service = SimulationService()
    service.auto_recover = False
    service.reset()
    fleet_agent.clear()
    schedule_and_apply(service, fleet_agent)
    return service


def test_fallback_dialogue_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "")
    reload_llm_settings()
    llm_agent_bus.clear()
    d = run_incident_dialogue(
        sim_time=12,
        tractor_id="tractor_01",
        job_id="job_01",
        reason="test",
        preserved_work_units=3.5,
        percent_complete=35.0,
        reassigned_to="tractor_02",
        blocking_reason=None,
    )
    assert d.llm_used is False
    assert len(d.messages) >= 3
    assert d.messages[0].sender == "fleet_llm"
    assert d.messages[0].source == "fallback"


def test_breakdown_records_dialogue(sim: SimulationService) -> None:
    victim = next(t for t in sim.tractors.values() if t.assigned_job_id)
    result = breakdown_and_recover(sim, victim.id, reason="llm_test")
    assert result.ok
    dialogues = llm_agent_bus.list_dialogues()
    assert len(dialogues) >= 1
    assert dialogues[-1].tractor_id == victim.id
    assert len(dialogues[-1].messages) >= 3


def test_llm_api_endpoints(sim: SimulationService) -> None:
    client = TestClient(app)
    status = client.get("/api/agents/llm/status")
    assert status.status_code == 200
    body = status.json()
    assert "configured" in body
    assert body["api_key_present"] is False

    victim = next(t for t in sim.tractors.values() if t.assigned_job_id)
    breakdown_and_recover(sim, victim.id)
    dialogues = client.get("/api/agents/llm/dialogues")
    assert dialogues.status_code == 200
    payload = dialogues.json()
    assert payload["count"] >= 1
    assert payload["dialogues"][0]["messages"]
