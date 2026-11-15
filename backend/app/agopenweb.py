"""Optional AgOpenWeb integration — read-only field.geojson adapter.

Investigation summary (AgOpenGPS-Official/AgOpenWeb, develop Docs):

- AgOpenWeb is a cab GPS guidance host (UI on :5174 via its own WebSocket).
- It does **not** document a public REST API for fleet command or live tractor telemetry
  for third-party coordinators.
- Documented external interface for other tools: **field.geojson** (WGS84 FeatureCollection)
  per Docs/FIELD_FILE_FORMATS.md — boundaries, tracks, flags, origin.
- Live position/steer data uses NMEA/UDP PGN on the machine network (hardware modules),
  not a Fleet REST surface. Claiming tractor control would be false.

This adapter therefore supports **read-only import** of a documented field.geojson file.
Status meanings:
- unsupported — no field path configured (default; sim-only mode)
- disconnected — path set but file missing/invalid
- connected — file parsed successfully (field metadata only; sim remains authoritative)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from threading import Lock
from typing import Any, Literal

from pydantic import BaseModel, Field

AgOpenWebStatus = Literal["connected", "disconnected", "unsupported"]

DEFAULT_SAMPLE = (
    Path(__file__).resolve().parent.parent / "data" / "agopenweb" / "sample_field.geojson"
)


class AgOpenWebFieldSummary(BaseModel):
    name: str | None = None
    origin_latitude: float | None = None
    origin_longitude: float | None = None
    format_version: int | None = None
    outer_boundary_points: int = 0
    inner_boundary_count: int = 0
    track_count: int = 0
    flag_count: int = 0
    source_path: str | None = None


class AgOpenWebIntegrationStatus(BaseModel):
    status: AgOpenWebStatus
    mode: str = "read_only_field_geojson"
    message: str
    integrated: list[str] = Field(default_factory=list)
    remains_simulated: list[str] = Field(default_factory=list)
    field: AgOpenWebFieldSummary | None = None
    documentation: dict[str, str] = Field(default_factory=dict)


def _default_remains_simulated() -> list[str]:
    return [
        "tractor positions and motion (FarmShield grid simulator)",
        "job scheduling, fuel, deadlines, recovery",
        "A* routes on the demo grid",
        "live GPS / NMEA / autosteer (not connected)",
        "fleet command or section control (not claimed)",
    ]


def _default_docs() -> dict[str, str]:
    return {
        "repo": "https://github.com/AgOpenGPS-Official/AgOpenWeb",
        "field_formats": (
            "https://github.com/AgOpenGPS-Official/AgOpenWeb/blob/develop/Docs/FIELD_FILE_FORMATS.md"
        ),
        "web_client": (
            "https://github.com/AgOpenGPS-Official/AgOpenWeb/blob/develop/Docs/WEB_CLIENT.md"
        ),
        "add_on_cards": (
            "https://github.com/AgOpenGPS-Official/AgOpenWeb/blob/develop/Docs/ADD_ON_CARDS.md"
        ),
    }


class AgOpenWebAdapter:
    """Read-only adapter for AgOpenWeb field.geojson files."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._path: Path | None = None
        self._field: AgOpenWebFieldSummary | None = None
        self._last_error: str | None = None
        env = os.environ.get("AGOPENWEB_FIELD_GEOJSON", "").strip()
        if env:
            self.configure_path(env)

    def configure_path(self, path: str | Path | None) -> AgOpenWebIntegrationStatus:
        with self._lock:
            if not path:
                self._path = None
                self._field = None
                self._last_error = None
            else:
                self._path = Path(path).expanduser()
                self._reload_unlocked()
            return self.status_unlocked()

    def reload(self) -> AgOpenWebIntegrationStatus:
        with self._lock:
            self._reload_unlocked()
            return self.status_unlocked()

    def status(self) -> AgOpenWebIntegrationStatus:
        with self._lock:
            return self.status_unlocked()

    def _reload_unlocked(self) -> None:
        self._field = None
        self._last_error = None
        if self._path is None:
            return
        try:
            self._field = parse_field_geojson(self._path)
        except Exception as exc:  # noqa: BLE001 — surface as disconnected
            self._last_error = str(exc)
            self._field = None

    def status_unlocked(self) -> AgOpenWebIntegrationStatus:
        docs = _default_docs()
        remains = _default_remains_simulated()
        if self._path is None:
            return AgOpenWebIntegrationStatus(
                status="unsupported",
                message=(
                    "No AgOpenWeb field.geojson configured. FarmShield runs fully on its "
                    "custom simulator. Set AGOPENWEB_FIELD_GEOJSON or POST /api/agopenweb/configure "
                    "to import a documented field file (read-only)."
                ),
                integrated=[],
                remains_simulated=remains,
                field=None,
                documentation=docs,
            )
        if self._field is None:
            return AgOpenWebIntegrationStatus(
                status="disconnected",
                message=(
                    f"Configured path unreadable or invalid: {self._path}. "
                    f"Error: {self._last_error or 'unknown'}"
                ),
                integrated=[],
                remains_simulated=remains,
                field=AgOpenWebFieldSummary(source_path=str(self._path)),
                documentation=docs,
            )
        return AgOpenWebIntegrationStatus(
            status="connected",
            message=(
                "Read-only field.geojson loaded (AgOpenWeb Docs/FIELD_FILE_FORMATS.md). "
                "No live tractor control or fabricated GPS telemetry."
            ),
            integrated=[
                "field name and WGS84 origin",
                "outer/inner boundary point counts from GeoJSON",
                "track and flag counts (metadata only)",
            ],
            remains_simulated=remains,
            field=self._field,
            documentation=docs,
        )


def parse_field_geojson(path: Path) -> AgOpenWebFieldSummary:
    """Parse a documented AgOpenWeb field.geojson (FeatureCollection with role properties)."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("type") != "FeatureCollection":
        raise ValueError("Expected GeoJSON FeatureCollection")
    features = raw.get("features")
    if not isinstance(features, list):
        raise ValueError("FeatureCollection.features must be a list")

    name: str | None = None
    origin_lat: float | None = None
    origin_lon: float | None = None
    format_version: int | None = None
    outer_pts = 0
    inner_count = 0
    tracks = 0
    flags = 0

    for feat in features:
        if not isinstance(feat, dict):
            continue
        props = feat.get("properties") or {}
        if not isinstance(props, dict):
            continue
        role = props.get("role")
        geom = feat.get("geometry") or {}
        if role == "metadata":
            name = props.get("name")
            origin_lat = _as_float(props.get("originLatitude"))
            origin_lon = _as_float(props.get("originLongitude"))
            fv = props.get("formatVersion")
            format_version = int(fv) if fv is not None else 1
        elif role == "outer-boundary":
            outer_pts = _ring_point_count(geom)
        elif role == "inner-boundary":
            inner_count += 1
        elif role == "track":
            tracks += 1
        elif role == "flag":
            flags += 1

    if name is None and origin_lat is None and outer_pts == 0 and tracks == 0 and flags == 0:
        raise ValueError("No AgOpenWeb roles found (metadata/boundary/track/flag)")

    return AgOpenWebFieldSummary(
        name=name,
        origin_latitude=origin_lat,
        origin_longitude=origin_lon,
        format_version=format_version,
        outer_boundary_points=outer_pts,
        inner_boundary_count=inner_count,
        track_count=tracks,
        flag_count=flags,
        source_path=str(path),
    )


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _ring_point_count(geom: dict[str, Any]) -> int:
    if geom.get("type") != "Polygon":
        return 0
    coords = geom.get("coordinates") or []
    if not coords or not isinstance(coords[0], list):
        return 0
    return len(coords[0])


agopenweb_adapter = AgOpenWebAdapter()
