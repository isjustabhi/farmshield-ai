# AgOpenWeb integration status (honest)

Official source: [AgOpenGPS-Official/AgOpenWeb](https://github.com/AgOpenGPS-Official/AgOpenWeb)

## Investigation (time-boxed)

| Question | Finding |
| --- | --- |
| Public REST fleet API? | **No.** Host serves its own web UI (~`:5174`) over a private WebSocket wire format for the guidance client (`Docs/WEB_CLIENT.md`). |
| Field / map formats? | **Yes — documented.** One field folder with `field.geojson` (WGS84 FeatureCollection, `role` properties). Spec: `Docs/FIELD_FILE_FORMATS.md` on `develop`. Also imports ISO-XML, KML/KMZ; AgShare cloud sync is separate. |
| Position / route for third parties? | Live fix via **NMEA / UDP PGN** to hardware modules (`Docs/PGN.md` / architecture), not a documented fleet REST telemetry API. Add-ons **must not** command AgOpenWeb (`Docs/ADD_ON_CARDS.md`). |
| Safe read-only integration? | **Yes, file-level only:** parse `field.geojson` for name, origin, boundary/track/flag counts. |

## What FarmShield implements

- `AgOpenWebAdapter` (`backend/app/agopenweb.py`) — read-only GeoJSON importer.
- `GET /api/agopenweb/status` — `connected` | `disconnected` | `unsupported`.
- `POST /api/agopenweb/configure` — set/clear path to a `field.geojson`.
- Env: `AGOPENWEB_FIELD_GEOJSON=/path/to/field.geojson`
- UI badge in the top nav (AgOpenWeb status).

### Status meanings

| Status | Meaning |
| --- | --- |
| **Unsupported** | Default. No field file configured. Custom simulator only. |
| **Disconnected** | Path configured but missing/invalid. |
| **Connected** | Documented `field.geojson` parsed successfully. |

### Integrated when Connected

- Field name, WGS84 origin, boundary/track/flag **metadata** from GeoJSON.

### Remains simulated (always)

- Tractor motion, jobs, fuel, scheduling, recovery, grid A*, benchmarks.
- **No** real GPS stream, **no** autosteer, **no** tractor command.

## What we do **not** claim

- Real tractor control  
- Fabricated live GPS telemetry  
- Undocumented reverse-engineered WebSocket command APIs  

## Quick try

```bash
# optional: load the bundled format sample (not live AgOpenWeb)
curl -s -X POST http://127.0.0.1:8000/api/agopenweb/configure \
  -H 'Content-Type: application/json' \
  -d '{"path":"backend/data/agopenweb/sample_field.geojson"}'
curl -s http://127.0.0.1:8000/api/agopenweb/status | python -m json.tool
```
