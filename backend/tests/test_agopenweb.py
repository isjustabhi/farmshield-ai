"""AgOpenWeb adapter — read-only field.geojson only."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.agopenweb import AgOpenWebAdapter, parse_field_geojson
from app.main import app

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "agopenweb" / "sample_field.geojson"
client = TestClient(app)


def test_parse_sample_field_geojson() -> None:
    summary = parse_field_geojson(SAMPLE)
    assert summary.name == "FarmShieldSampleField"
    assert summary.origin_latitude == 32.59058587
    assert summary.outer_boundary_points == 5
    assert summary.track_count == 1
    assert summary.flag_count == 1


def test_adapter_status_unsupported_by_default() -> None:
    adapter = AgOpenWebAdapter()
    # Clear any env-configured path from process.
    status = adapter.configure_path(None)
    assert status.status == "unsupported"
    assert status.integrated == []
    assert "simulator" in status.message.lower() or "No AgOpenWeb" in status.message


def test_adapter_connected_and_disconnected(tmp_path: Path) -> None:
    adapter = AgOpenWebAdapter()
    missing = tmp_path / "missing.geojson"
    status = adapter.configure_path(missing)
    assert status.status == "disconnected"

    status = adapter.configure_path(SAMPLE)
    assert status.status == "connected"
    assert status.field is not None
    assert status.field.name == "FarmShieldSampleField"
    assert "field name" in " ".join(status.integrated).lower()
    assert any("GPS" in s or "tractor" in s.lower() for s in status.remains_simulated)


def test_api_status_and_configure() -> None:
    r = client.get("/api/agopenweb/status")
    assert r.status_code == 200
    assert r.json()["status"] in {"connected", "disconnected", "unsupported"}

    ok = client.post(
        "/api/agopenweb/configure",
        json={"path": str(SAMPLE)},
    )
    assert ok.status_code == 200
    assert ok.json()["status"] == "connected"

    cleared = client.post("/api/agopenweb/configure", json={"path": None})
    assert cleared.status_code == 200
    assert cleared.json()["status"] == "unsupported"
