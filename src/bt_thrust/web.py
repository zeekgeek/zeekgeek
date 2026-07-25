"""FastAPI dashboard for the Bluetooth thrust controller."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from bt_radar.calibration import calibration_profile_payload

from .controller import ToyController
from .deep_scan import discover_gatt
from .export import export_connection_logs_csv, export_devices_csv, export_snapshot_json
from .state import ControllerState


class ControlRequest(BaseModel):
    levels: dict[str, int] = Field(default_factory=dict)


class PatternRequest(BaseModel):
    pattern: str


class SelectRequest(BaseModel):
    address: str | None = None


class ScannerSettingsRequest(BaseModel):
    stale_after: float | None = None


class ScannerPausedRequest(BaseModel):
    paused: bool = True


class DeepScanRequest(BaseModel):
    duration_seconds: float = 20.0


class ScannerFilterRequest(BaseModel):
    min_rssi: int | None = None
    device_type: str | None = None


class ThrusterRequest(BaseModel):
    throttle: int = Field(ge=0, le=100)
    direction: str = "forward"
    pulse_mode: bool = False


class AutoTuneRequest(BaseModel):
    enabled: bool = True


def create_app(state: ControllerState, controller: ToyController) -> FastAPI:
    app = FastAPI(title="Adorime Thrust Controller")
    calibration_json = json.dumps(calibration_profile_payload())

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return DASHBOARD_HTML.replace("__RSSI_CALIBRATION_JSON__", calibration_json)

    @app.get("/api/toys")
    async def toys() -> dict:
        return await state.snapshot()

    @app.post("/api/select")
    async def select_toy(request: SelectRequest) -> JSONResponse:
        await state.select(request.address)
        return JSONResponse({"selected_address": request.address})

    @app.post("/api/toys/{address}/connect")
    async def connect_toy(address: str) -> JSONResponse:
        try:
            result = await controller.connect(address)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(result)

    @app.post("/api/toys/{address}/disconnect")
    async def disconnect_toy(address: str) -> JSONResponse:
        result = await controller.disconnect(address)
        return JSONResponse(result)

    @app.post("/api/toys/{address}/control")
    async def control_toy(address: str, request: ControlRequest) -> JSONResponse:
        try:
            result = await controller.set_levels(address, request.levels)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(result)

    @app.post("/api/toys/{address}/pattern")
    async def pattern_toy(address: str, request: PatternRequest) -> JSONResponse:
        try:
            result = await controller.run_pattern(address, request.pattern)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(result)

    @app.post("/api/scanner/pause")
    async def pause_scanner(request: ScannerPausedRequest) -> JSONResponse:
        event = await state.set_scanner_paused(request.paused)
        return JSONResponse({"paused": request.paused, "event": event})

    @app.post("/api/scanner/clear-stale")
    async def clear_stale_devices() -> JSONResponse:
        removed = await state.clear_stale_devices()
        return JSONResponse({"removed": removed})

    @app.post("/api/scanner/settings")
    async def update_scanner_settings(request: ScannerSettingsRequest) -> JSONResponse:
        if request.stale_after is not None:
            await state.set_stale_after(request.stale_after)
        snapshot = await state.snapshot()
        return JSONResponse(snapshot["scanner"])

    @app.post("/api/scanner/deep-scan")
    async def deep_scan(request: DeepScanRequest) -> JSONResponse:
        event = await state.trigger_deep_scan(request.duration_seconds)
        snapshot = await state.snapshot()
        return JSONResponse({"event": event, "scanner": snapshot["scanner"]})

    @app.post("/api/scanner/filters")
    async def scanner_filters(request: ScannerFilterRequest) -> JSONResponse:
        await state.set_scanner_filters(min_rssi=request.min_rssi, device_type=request.device_type)
        snapshot = await state.snapshot()
        return JSONResponse(snapshot["scanner"])

    @app.post("/api/toys/{address}/gatt-scan")
    async def gatt_scan(address: str) -> JSONResponse:
        ble_device = await state.get_ble_device(address)
        result = await discover_gatt(address, ble_device=ble_device)
        event = await state.store_gatt_result(address, result)
        return JSONResponse({"result": result, "event": event})

    @app.post("/api/toys/{address}/thruster")
    async def thruster_control(address: str, request: ThrusterRequest) -> JSONResponse:
        try:
            result = await controller.set_thruster(
                address,
                throttle=request.throttle,
                direction=request.direction,
                pulse_mode=request.pulse_mode,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(result)

    @app.get("/api/toys/{address}/ai-suggest")
    async def ai_suggest(address: str) -> JSONResponse:
        track = await state.get_track(address)
        if track is None:
            raise HTTPException(status_code=404, detail="Device not found")
        suggestion = controller.advisor.suggest(
            address=address,
            current_levels=track.levels,
            rssi=track.rssi,
            connected=track.connected,
        )
        return JSONResponse(suggestion)

    @app.post("/api/toys/{address}/ai-apply")
    async def ai_apply(address: str) -> JSONResponse:
        try:
            result = await controller.apply_ai_suggestion(address)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(result)

    @app.post("/api/ai/auto-tune")
    async def ai_auto_tune(request: AutoTuneRequest) -> JSONResponse:
        controller.advisor.set_auto_tune(request.enabled)
        return JSONResponse({"auto_tune_enabled": request.enabled})

    @app.get("/api/export/json")
    async def export_json() -> PlainTextResponse:
        snapshot = await state.snapshot()
        snapshot["connection_logs"] = controller.connection_logs()
        snapshot["ai"] = controller.advisor.snapshot()
        return PlainTextResponse(export_snapshot_json(snapshot), media_type="application/json")

    @app.get("/api/export/csv")
    async def export_csv() -> PlainTextResponse:
        snapshot = await state.snapshot()
        return PlainTextResponse(export_devices_csv(snapshot), media_type="text/csv")

    @app.get("/api/export/logs.csv")
    async def export_logs_csv() -> PlainTextResponse:
        snapshot = await state.snapshot()
        logs = snapshot.get("events", []) + controller.connection_logs()
        return PlainTextResponse(export_connection_logs_csv(logs), media_type="text/csv")

    @app.get("/api/events")
    async def events() -> StreamingResponse:
        return StreamingResponse(_event_stream(state), media_type="text/event-stream")

    return app


async def _event_stream(state: ControllerState) -> AsyncIterator[str]:
    last_payload = ""
    while True:
        snapshot = await state.snapshot()
        payload = json.dumps(snapshot)
        if payload != last_payload:
            yield f"data: {payload}\n\n"
            last_payload = payload
        await asyncio.sleep(0.5)


DASHBOARD_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Adorime Thrust Controller</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #160812;
      --panel: #24101c;
      --panel-2: #311528;
      --text: #edf2ff;
      --muted: #93a1ba;
      --accent: #f472b6;
      --accent-soft: rgba(244, 114, 182, 0.18);
      --green: #22c55e;
      --yellow: #eab308;
      --red: #ef4444;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif;
      background: radial-gradient(circle at top, color-mix(in srgb, var(--accent) 16%, transparent), transparent 40%), var(--bg);
      color: var(--text);
      min-height: 100vh;
    }
    header {
      padding: 18px 24px;
      border-bottom: 1px solid color-mix(in srgb, var(--accent) 24%, #243047);
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: center;
      flex-wrap: wrap;
    }
    h1 { font-size: 22px; margin: 0; }
    h2 { margin: 0 0 12px 0; font-size: 17px; }
    .stats { display: flex; gap: 14px; color: var(--muted); font-size: 14px; flex-wrap: wrap; margin-top: 6px; }
    .stats b { color: var(--text); }
    .live-badge {
      background: rgba(34,197,94,.15);
      color: var(--green);
      border-radius: 999px;
      padding: 6px 12px;
      font-size: 12px;
      font-weight: 800;
      letter-spacing: .04em;
      text-transform: uppercase;
    }
    main {
      display: grid;
      gap: 16px;
      padding: 16px;
      max-width: 980px;
      margin: 0 auto;
      align-items: start;
    }
    .panel {
      background: var(--panel);
      border: 1px solid color-mix(in srgb, var(--accent) 18%, #243047);
      border-radius: 16px;
      padding: 14px;
      box-shadow: 0 18px 44px rgba(0,0,0,.28);
    }
    .stack { display: grid; gap: 16px; }
    .toy-list { max-height: 78vh; overflow: auto; }
    .found-devices-panel { margin-bottom: 0; }
    .found-devices-head {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      flex-wrap: wrap;
      margin-bottom: 12px;
    }
    .found-devices-summary {
      color: var(--muted);
      font-size: 13px;
    }
    .found-devices-summary b { color: var(--text); }
    .device-table-wrap {
      overflow: auto;
      border: 1px solid #26324b;
      border-radius: 12px;
      background: rgba(0,0,0,.12);
    }
    .device-table {
      width: 100%;
      border-collapse: collapse;
      min-width: 640px;
    }
    .device-table thead th {
      position: sticky;
      top: 0;
      background: var(--panel-2);
      color: var(--muted);
      font-size: 11px;
      font-weight: 800;
      letter-spacing: .05em;
      text-transform: uppercase;
      text-align: left;
      padding: 10px 12px;
      border-bottom: 1px solid #26324b;
    }
    .device-table tbody tr {
      cursor: pointer;
      border-bottom: 1px solid #1f2937;
    }
    .device-table tbody tr:hover { background: rgba(244,114,182,.06); }
    .device-table tbody tr.active { background: var(--accent-soft); }
    .device-table tbody tr.connected { box-shadow: inset 3px 0 0 var(--green); }
    .device-table td {
      padding: 12px;
      font-size: 13px;
      vertical-align: top;
    }
    .device-table .col-name { font-weight: 800; min-width: 140px; }
    .device-table .col-addr {
      font-family: ui-monospace, Menlo, monospace;
      font-size: 12px;
      color: var(--muted);
    }
    .device-table .col-rssi { white-space: nowrap; font-weight: 700; }
    .device-table .col-meta { color: var(--muted); font-size: 12px; }
    .device-table .badge-cell { display: flex; gap: 6px; flex-wrap: wrap; }
    .scanner-visual-grid {
      display: grid;
      grid-template-columns: minmax(280px, 1fr) minmax(280px, 1fr);
      gap: 16px;
      align-items: start;
    }
    .radar-wrap {
      background: rgba(0,0,0,.18);
      border: 1px solid #26324b;
      border-radius: 14px;
      padding: 10px;
    }
    canvas#radar-map {
      width: 100%;
      height: 320px;
      background: radial-gradient(circle at center, rgba(244,114,182,.08), rgba(0,0,0,.25));
      border-radius: 12px;
      border: 1px solid #26324b;
      display: block;
    }
    .device-cards {
      display: grid;
      gap: 10px;
      max-height: 360px;
      overflow: auto;
      padding-right: 4px;
    }
    .device-card {
      background: var(--panel-2);
      border: 1px solid #26324b;
      border-radius: 12px;
      padding: 12px;
      cursor: pointer;
    }
    .device-card:hover { border-color: color-mix(in srgb, var(--accent) 35%, #26324b); }
    .device-card.active { outline: 2px solid var(--accent); background: var(--accent-soft); }
    .device-card.connected { box-shadow: inset 3px 0 0 var(--green); }
    .device-card-head {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: start;
      margin-bottom: 8px;
    }
    .device-card-name { font-weight: 800; font-size: 14px; }
    .device-card-addr {
      color: var(--muted);
      font-family: ui-monospace, Menlo, monospace;
      font-size: 11px;
      margin-top: 4px;
    }
    .device-card-meta {
      display: flex;
      justify-content: space-between;
      gap: 8px;
      font-size: 12px;
      color: var(--muted);
      margin-top: 8px;
    }
    .toy {
      border: 1px solid #26324b;
      border-radius: 14px;
      padding: 12px;
      margin: 8px 0;
      background: var(--panel-2);
      cursor: pointer;
    }
    .toy.active { outline: 2px solid var(--accent); }
    .toy.connected { box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--green) 45%, transparent); }
    .toy.unrecognized { opacity: .72; }
    .toy-title { display: flex; justify-content: space-between; gap: 10px; align-items: start; }
    .name { font-weight: 800; }
    .addr { color: var(--muted); font-family: ui-monospace, Menlo, monospace; font-size: 12px; }
    .badge {
      border-radius: 999px;
      padding: 4px 8px;
      font-size: 11px;
      font-weight: 700;
      white-space: nowrap;
      text-transform: uppercase;
    }
    .brand-adorime { background: rgba(236, 72, 153, .18); color: #f9a8d4; }
    .brand-bluetooth { background: rgba(56,189,248,.15); color: #7dd3fc; }
    .brand-galaku { background: rgba(167, 139, 250, .18); color: #c4b5fd; }
    .scanner-toolbar {
      display: grid;
      gap: 10px;
      margin-bottom: 12px;
      padding-bottom: 12px;
      border-bottom: 1px solid #26324b;
    }
    .scanner-row {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      align-items: center;
    }
    .scanner-status {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: .04em;
      color: var(--muted);
    }
    .scanner-dot {
      width: 9px;
      height: 9px;
      border-radius: 999px;
      background: var(--muted);
    }
    .scanner-dot.running { background: var(--green); box-shadow: 0 0 0 4px rgba(34,197,94,.15); }
    .scanner-dot.paused { background: var(--yellow); }
    .scanner-dot.error { background: var(--red); }
    .scanner-controls label {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      color: var(--muted);
      font-size: 12px;
    }
    .scanner-controls select, .scanner-controls input[type=number] {
      background: var(--panel-2);
      color: var(--text);
      border: 1px solid #26324b;
      border-radius: 10px;
      padding: 8px 10px;
      font: inherit;
    }
    .toy.controllable { border-color: color-mix(in srgb, var(--accent) 35%, #26324b); }
    .toy.other { opacity: .92; }
    .present { background: rgba(34,197,94,.15); color: var(--green); }
    .gone { background: rgba(148,163,184,.15); color: var(--muted); }
    .connected { background: rgba(56,189,248,.15); color: #7dd3fc; }
    .signal-row { display: flex; justify-content: space-between; gap: 8px; font-size: 12px; color: var(--muted); margin: 8px 0 4px 0; }
    .bar { width: 100%; height: 8px; border-radius: 999px; background: #091427; overflow: hidden; border: 1px solid #22324a; }
    .bar > div { height: 100%; background: linear-gradient(90deg, #312e81, var(--accent), #22c55e); }
    .control-head {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      flex-wrap: wrap;
      margin-bottom: 16px;
    }
    .control-title { font-size: 26px; font-weight: 800; line-height: 1.15; }
    .control-sub { color: var(--muted); font-size: 13px; margin-top: 6px; }
    .actions { display: flex; gap: 10px; flex-wrap: wrap; }
    button {
      background: var(--accent);
      color: #08111f;
      border: 0;
      border-radius: 12px;
      padding: 10px 14px;
      font-weight: 700;
      cursor: pointer;
    }
    button:disabled { opacity: .45; cursor: not-allowed; }
    button.secondary {
      background: transparent;
      color: var(--text);
      border: 1px solid color-mix(in srgb, var(--accent) 35%, #334155);
    }
    button.danger { background: var(--red); color: white; }
    .hero-card {
      background: linear-gradient(135deg, color-mix(in srgb, var(--accent) 20%, var(--panel-2)), var(--panel-2));
      border-radius: 16px;
      padding: 18px;
      border: 1px solid color-mix(in srgb, var(--accent) 28%, #26324b);
      margin-bottom: 18px;
    }
    .meter-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
      gap: 12px;
    }
    .meter {
      background: rgba(0,0,0,.18);
      border-radius: 14px;
      padding: 14px;
      border: 1px solid #26324b;
      text-align: center;
    }
    .meter-value { font-size: 34px; font-weight: 800; color: var(--accent); line-height: 1; }
    .meter-label { color: var(--muted); font-size: 12px; margin-top: 6px; font-weight: 700; text-transform: uppercase; letter-spacing: .04em; }
    .slider-block {
      background: var(--panel-2);
      border: 1px solid #26324b;
      border-radius: 14px;
      padding: 16px;
      margin: 12px 0;
    }
    .slider-label { display: flex; justify-content: space-between; margin-bottom: 10px; font-size: 15px; font-weight: 700; }
    .slider-label span:last-child { color: var(--accent); font-size: 18px; }
    input[type=range] { width: 100%; accent-color: var(--accent); height: 8px; }
    .patterns {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
      gap: 10px;
    }
    .mode-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(92px, 1fr));
      gap: 10px;
    }
    .pattern, .mode-btn, .quick-btn {
      background: var(--panel-2);
      border: 1px solid #26324b;
      border-radius: 12px;
      padding: 14px 10px;
      text-align: center;
      cursor: pointer;
      color: var(--text);
      font: inherit;
    }
    .quick-btn {
      padding: 10px 8px;
      min-width: 54px;
      font-weight: 800;
    }
    .pattern:hover, .pattern.active, .mode-btn:hover, .mode-btn.active, .quick-btn:hover {
      border-color: var(--accent);
      background: var(--accent-soft);
    }
    .pattern:disabled, .mode-btn:disabled, .quick-btn:disabled {
      opacity: .45;
      cursor: not-allowed;
    }
    .pattern-icon, .mode-icon { font-size: 24px; margin-bottom: 6px; font-weight: 800; }
    .pattern-label, .mode-label { font-size: 12px; font-weight: 700; line-height: 1.25; }
    .control-section { margin: 18px 0; }
    .control-section h2 { margin-bottom: 10px; }
    .master-block {
      background: linear-gradient(135deg, rgba(244,114,182,.12), rgba(0,0,0,.18));
      border: 1px solid color-mix(in srgb, var(--accent) 30%, #26324b);
      border-radius: 16px;
      padding: 18px;
    }
    .master-head {
      display: flex;
      justify-content: space-between;
      align-items: end;
      gap: 12px;
      margin-bottom: 12px;
    }
    .master-value {
      font-size: 48px;
      font-weight: 900;
      color: var(--accent);
      line-height: 1;
    }
    .master-caption { color: var(--muted); font-size: 13px; font-weight: 700; text-transform: uppercase; letter-spacing: .05em; }
    .quick-levels { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
    .focus-row {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      align-items: center;
      margin: 14px 0;
    }
    .focus-row button.secondary.active {
      background: var(--accent-soft);
      border-color: var(--accent);
      color: var(--text);
    }
    .link-toggle {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      color: var(--muted);
      font-size: 13px;
      margin-left: auto;
    }
    .link-toggle input { accent-color: var(--accent); }
    .disabled-overlay {
      opacity: .55;
      pointer-events: none;
    }
    .status-line {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 10px;
      font-size: 12px;
      color: var(--muted);
    }
    .status-pill {
      background: rgba(0,0,0,.18);
      border: 1px solid #26324b;
      border-radius: 999px;
      padding: 4px 10px;
    }
    .events { max-height: 180px; overflow: auto; color: var(--muted); font-size: 13px; }
    .event { padding: 6px 0; border-bottom: 1px solid #1f2937; }
    .empty { color: var(--muted); text-align: center; padding: 34px 0; }
    .hint { font-size: 12px; color: var(--muted); margin-top: 8px; }
    .scan-power {
      font-size: 14px;
      font-weight: 800;
      letter-spacing: .03em;
      text-transform: uppercase;
      min-width: 118px;
    }
    .scan-power.on { background: var(--green); color: #052e16; }
    .scan-power.off {
      background: transparent;
      color: #fecaca;
      border: 2px solid var(--red);
    }
    .scan-power.deep {
      background: linear-gradient(135deg, var(--accent), #c084fc);
      color: #1f1024;
    }
    dl.device-info {
      display: grid;
      grid-template-columns: 170px 1fr;
      gap: 8px 12px;
      margin: 12px 0 0 0;
      font-size: 13px;
    }
    dl.device-info dt { color: var(--muted); margin: 0; }
    dl.device-info dd { margin: 0; overflow-wrap: anywhere; font-family: ui-monospace, Menlo, monospace; font-size: 12px; }
    .uuid-list { display: grid; gap: 6px; margin-top: 4px; }
    .uuid-item {
      background: rgba(0,0,0,.18);
      border: 1px solid #26324b;
      border-radius: 8px;
      padding: 8px 10px;
      font-family: ui-monospace, Menlo, monospace;
      font-size: 11px;
      overflow-wrap: anywhere;
    }
    .uuid-item.galaku { border-color: color-mix(in srgb, var(--accent) 45%, #26324b); }
    .finding {
      padding: 9px;
      border-radius: 10px;
      background: rgba(0,0,0,.18);
      border: 1px solid #26324b;
      margin: 8px 0;
      font-size: 13px;
    }
    .severity-info { color: #7dd3fc; }
    .severity-low { color: var(--yellow); }
    .severity-medium, .severity-high { color: var(--red); }
    canvas#signal-graph {
      width: 100%;
      height: 180px;
      background: rgba(0,0,0,.18);
      border-radius: 12px;
      border: 1px solid #26324b;
      display: block;
      margin-top: 10px;
    }
    .section-head {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      flex-wrap: wrap;
      margin-bottom: 8px;
    }
    .section-head h2 { margin: 0; }
    .error-banner {
      display: none;
      margin: 0 16px 0 16px;
      padding: 12px 14px;
      border-radius: 12px;
      background: rgba(239, 68, 68, .12);
      border: 1px solid rgba(239, 68, 68, .35);
      color: #fecaca;
      font-size: 14px;
    }
    .error-banner.visible { display: block; }
    @media (max-width: 980px) {
      .toy-list { max-height: none; }
      dl.device-info { grid-template-columns: 1fr; }
      .scanner-visual-grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Adorime Thrust Controller</h1>
      <div class="stats">
        <span id="counts">Waiting for live Bluetooth scan...</span>
        <span id="updated"></span>
      </div>
    </div>
    <div style="display:flex; gap:10px; align-items:center; flex-wrap:wrap;">
      <span class="live-badge" id="scanner-badge">Live BLE</span>
      <button id="notify">Enable notifications</button>
    </div>
  </header>

  <div id="error-banner" class="error-banner"></div>

  <main>
    <section class="panel">
      <div class="section-head">
        <h2>Bluetooth scanner</h2>
        <div style="display:flex; gap:8px; flex-wrap:wrap;">
          <button type="button" class="scan-power on" id="scan-toggle">Scan ON</button>
          <button type="button" class="secondary" id="deep-scan">Deep Scan</button>
        </div>
      </div>
      <div class="scanner-toolbar">
        <div class="scanner-row">
          <span class="scanner-status"><span class="scanner-dot" id="scanner-dot"></span><span id="scanner-status-text">Scanner starting</span></span>
          <button type="button" class="secondary" id="scanner-clear">Clear left</button>
        </div>
        <div class="scanner-row scanner-controls">
          <label>Filter
            <select id="device-filter">
              <option value="all">All devices</option>
              <option value="adorime">Adorime / Galaku</option>
              <option value="controllable">Controllable only</option>
            </select>
          </label>
          <label>Sort
            <select id="device-sort">
              <option value="signal">Strongest signal</option>
              <option value="name">Name</option>
              <option value="recent">Most recent</option>
            </select>
          </label>
          <label><input type="checkbox" id="show-left" checked> Show left devices</label>
          <label>Stale after
            <input type="number" id="stale-after" min="3" max="120" step="1" value="20"> s
          </label>
          <label>Min RSSI
            <input type="number" id="min-rssi" min="-127" max="-30" step="1" value="-127"> dBm
          </label>
        </div>
        <div class="scanner-row">
          <button type="button" class="secondary" id="export-json">Export JSON</button>
          <button type="button" class="secondary" id="export-csv">Export CSV</button>
          <button type="button" class="secondary" id="export-logs">Export logs</button>
        </div>
      </div>
    </section>

    <section class="panel">
      <h2>Nearby Bluetooth radar</h2>
      <p class="hint" style="margin-top:0;">Live graphical view of every discovered device. Dot size follows signal strength; distance rings are 1m, 3m, 8m, and 20m.</p>
      <div class="scanner-visual-grid">
        <div class="radar-wrap">
          <canvas id="radar-map" width="920" height="320"></canvas>
        </div>
        <div id="device-cards" class="device-cards empty">Scanning for nearby devices...</div>
      </div>
    </section>

    <section class="panel">
      <h2>Device details</h2>
      <canvas id="signal-graph" width="920" height="180"></canvas>
      <div id="device-details" class="empty">Select a scanned device to inspect UUIDs and advertisement data.</div>
    </section>

    <section class="panel found-devices-panel">
      <div class="found-devices-head">
        <h2 style="margin:0;">Found Bluetooth devices</h2>
        <div class="found-devices-summary" id="found-devices-summary">Waiting for scan results...</div>
      </div>
      <div class="device-table-wrap">
        <div id="found-devices" class="empty" style="padding:24px;">Turn scan ON to populate the device list.</div>
      </div>
    </section>

    <section class="panel">
      <h2>Thruster controls</h2>
      <div id="control-panel" class="empty">Select an Adorime/Galaku device from the list above to connect and control thrust.</div>
    </section>

    <section class="panel">
      <h2>Recent events</h2>
      <div id="events" class="events"></div>
    </section>
  </main>

  <script>
    let snapshot = null;
    let selectedAddress = null;
    let localLevels = {};
    let controlTimer = null;
    let sliderDragging = false;
    let panelSignature = null;
    let linkVibrate = false;
    let controlFocus = "both";
    let deviceFilter = "all";
    let deviceSort = "signal";
    let showLeftDevices = true;
    const notifiedEvents = new Set();
    const RSSI_DISTANCE_CALIBRATION = __RSSI_CALIBRATION_JSON__;

    const themes = { adorime: "theme-adorime" };

    function showError(message) {
      const banner = document.getElementById("error-banner");
      if (!message) {
        banner.textContent = "";
        banner.classList.remove("visible");
        return;
      }
      banner.textContent = message;
      banner.classList.add("visible");
    }

    document.getElementById("notify").onclick = async () => {
      if (!("Notification" in window)) {
        showError("This browser does not support notifications.");
        return;
      }
      await Notification.requestPermission();
    };

    function hasMotor(toy, motorId) {
      return (toy.motors || []).some((motor) => motor.id === motorId);
    }

    function thrustMotor(toy) {
      return (toy.motors || []).find((motor) => motor.id === "thrust" || motor.type === "oscillate") || null;
    }

    function vibrateMotor(toy) {
      return (toy.motors || []).find((motor) => motor.id === "vibrate" || motor.type === "vibrate") || null;
    }

    function primaryMotor(toy) {
      return thrustMotor(toy) || vibrateMotor(toy) || (toy.motors || [])[0] || null;
    }

    function clampLevel(value) {
      return Math.max(0, Math.min(100, Number(value) || 0));
    }

    function escapeHtml(value) {
      return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;");
    }

    function brandBadge(toy) {
      if (toy.controllable) return `<span class="badge brand-adorime">Adorime</span>`;
      if (toy.galaku_service) return `<span class="badge brand-galaku">Galaku svc</span>`;
      return `<span class="badge brand-bluetooth">BLE</span>`;
    }

    function deviceTitle(toy) {
      if (toy.controllable) return toy.display_name;
      return toy.name || toy.details?.local_name || "Unnamed device";
    }

    function filteredDevices() {
      if (!snapshot) return [];
      let devices = snapshot.toys.slice();
      const minRssi = snapshot.scanner?.min_rssi_filter;
      if (typeof minRssi === "number" && minRssi > -127) {
        devices = devices.filter((toy) => toy.rssi == null || toy.rssi >= minRssi);
      }
      const typeFilter = snapshot.scanner?.device_type_filter;
      if (typeFilter && typeFilter !== "all") {
        devices = devices.filter((toy) => toy.device_type === typeFilter);
      }
      if (deviceFilter === "adorime") {
        devices = devices.filter((toy) => toy.adorime_match || toy.galaku_service);
      } else if (deviceFilter === "controllable") {
        devices = devices.filter((toy) => toy.controllable);
      }
      if (!showLeftDevices) {
        devices = devices.filter((toy) => toy.present);
      }
      devices.sort((a, b) => {
        if (deviceSort === "name") {
          return deviceTitle(a).localeCompare(deviceTitle(b));
        }
        if (deviceSort === "recent") {
          return (b.last_seen || "").localeCompare(a.last_seen || "");
        }
        const rank = Number(b.present) - Number(a.present);
        if (rank !== 0) return rank;
        return (b.rssi ?? -999) - (a.rssi ?? -999);
      });
      return devices;
    }

    function bindScannerControls() {
      const filterEl = document.getElementById("device-filter");
      const sortEl = document.getElementById("device-sort");
      const showLeftEl = document.getElementById("show-left");
      const staleEl = document.getElementById("stale-after");
      const scanToggle = document.getElementById("scan-toggle");
      const clearEl = document.getElementById("scanner-clear");
      const deepScanEl = document.getElementById("deep-scan");

      if (filterEl && filterEl.dataset.bound !== "1") {
        filterEl.dataset.bound = "1";
        filterEl.addEventListener("change", () => {
          deviceFilter = filterEl.value;
          renderToyList();
        });
      }
      if (sortEl && sortEl.dataset.bound !== "1") {
        sortEl.dataset.bound = "1";
        sortEl.addEventListener("change", () => {
          deviceSort = sortEl.value;
          renderToyList();
        });
      }
      if (showLeftEl && showLeftEl.dataset.bound !== "1") {
        showLeftEl.dataset.bound = "1";
        showLeftEl.addEventListener("change", () => {
          showLeftDevices = showLeftEl.checked;
          renderToyList();
        });
      }
      if (staleEl && staleEl.dataset.bound !== "1") {
        staleEl.dataset.bound = "1";
        staleEl.addEventListener("change", async () => {
          try {
            await api("/api/scanner/settings", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ stale_after: Number(staleEl.value) }),
            });
            showError("");
          } catch (err) {
            showError(err.message || "Failed to update scanner settings");
          }
        });
      }
      if (scanToggle && scanToggle.dataset.bound !== "1") {
        scanToggle.dataset.bound = "1";
        scanToggle.addEventListener("click", async () => {
          const paused = !(snapshot?.scanner?.paused);
          try {
            await api("/api/scanner/pause", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ paused }),
            });
            showError("");
          } catch (err) {
            showError(err.message || "Failed to update scanner state");
          }
        });
      }
      if (deepScanEl && deepScanEl.dataset.bound !== "1") {
        deepScanEl.dataset.bound = "1";
        deepScanEl.addEventListener("click", async () => {
          try {
            await api("/api/scanner/deep-scan", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ duration_seconds: 20 }),
            });
            showError("");
          } catch (err) {
            showError(err.message || "Failed to start deep scan");
          }
        });
      }
      if (clearEl && clearEl.dataset.bound !== "1") {
        clearEl.dataset.bound = "1";
        clearEl.addEventListener("click", async () => {
          try {
            await api("/api/scanner/clear-stale", { method: "POST" });
            showError("");
          } catch (err) {
            showError(err.message || "Failed to clear stale devices");
          }
        });
      }
      const minRssiEl = document.getElementById("min-rssi");
      if (minRssiEl && minRssiEl.dataset.bound !== "1") {
        minRssiEl.dataset.bound = "1";
        minRssiEl.addEventListener("change", async () => {
          const parsed = Number(minRssiEl.value);
          const minRssi = Number.isFinite(parsed) && parsed <= -30 ? parsed : -127;
          try {
            await api("/api/scanner/filters", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ min_rssi: minRssi }),
            });
            showError("");
          } catch (err) {
            showError(err.message || "Failed to update RSSI filter");
          }
        });
      }
      ["export-json", "export-csv", "export-logs"].forEach((id) => {
        const node = document.getElementById(id);
        if (!node || node.dataset.bound === "1") return;
        node.dataset.bound = "1";
        const paths = {
          "export-json": "/api/export/json",
          "export-csv": "/api/export/csv",
          "export-logs": "/api/export/logs.csv",
        };
        node.addEventListener("click", () => {
          window.open(paths[id], "_blank");
        });
      });
    }

    function renderScannerStatus() {
      const scanner = snapshot?.scanner || {};
      const dot = document.getElementById("scanner-dot");
      const text = document.getElementById("scanner-status-text");
      const badge = document.getElementById("scanner-badge");
      const scanToggle = document.getElementById("scan-toggle");
      const staleEl = document.getElementById("stale-after");
      const deepScanEl = document.getElementById("deep-scan");
      if (!dot || !text || !scanToggle || !deepScanEl) return;

      dot.className = "scanner-dot";
      if (scanner.error) {
        dot.classList.add("error");
        text.textContent = "Scanner retrying — check Bluetooth is on";
        if (badge) badge.textContent = "Scanner error";
        showError(`${scanner.error}. On machines without an adapter, run with --demo.`);
      } else if (scanner.deep_scan_active) {
        dot.classList.add("running");
        text.textContent = "Deep scan active";
        if (badge) badge.textContent = "Deep Scan";
      } else if (scanner.paused) {
        dot.classList.add("paused");
        text.textContent = "Scan OFF";
        if (badge) badge.textContent = "Scan OFF";
      } else if (scanner.active) {
        dot.classList.add("running");
        text.textContent = "Scan ON · listening";
        if (badge) badge.textContent = "Scan ON";
      } else {
        text.textContent = "Scanner starting";
      }

      const scanning = !scanner.paused && !scanner.error;
      scanToggle.textContent = scanning ? "Scan OFF" : "Scan ON";
      scanToggle.classList.toggle("on", scanning);
      scanToggle.classList.toggle("off", !scanning);
      scanToggle.classList.toggle("deep", Boolean(scanner.deep_scan_active));
      deepScanEl.classList.toggle("active", Boolean(scanner.deep_scan_active));
      deepScanEl.textContent = scanner.deep_scan_active ? "Deep Scan Active" : "Deep Scan";

      if (staleEl && document.activeElement !== staleEl) {
        staleEl.value = scanner.stale_after ?? 20;
      }
      bindScannerControls();
    }

    function renderUuidList(uuids, toy) {
      if (!uuids || !uuids.length) {
        return `<div class="hint">No service UUIDs advertised.</div>`;
      }
      return `<div class="uuid-list">${uuids.map((uuid) => {
        const galaku = toy.galaku_service && uuid.toLowerCase().includes("00001000");
        return `<div class="uuid-item ${galaku ? "galaku" : ""}">${escapeHtml(uuid)}${galaku ? " · Galaku control" : ""}</div>`;
      }).join("")}</div>`;
    }

    function renderManufacturerData(entries) {
      if (!entries || !entries.length) {
        return "none advertised";
      }
      return entries.map((entry) =>
        `${escapeHtml(entry.company_hex)} [${entry.data_length} B]: ${escapeHtml(entry.data_hex)}`
      ).join("<br>");
    }

    function renderServiceData(serviceData) {
      if (!serviceData || !Object.keys(serviceData).length) {
        return "none advertised";
      }
      return Object.entries(serviceData).map(([uuid, hex]) =>
        `${escapeHtml(uuid)} → ${escapeHtml(hex)}`
      ).join("<br>");
    }

    function renderGattServices(toy) {
      if (toy.gatt_error) {
        return `<span class="hint">GATT scan error: ${escapeHtml(toy.gatt_error)}</span>`;
      }
      const services = toy.gatt_services || [];
      if (!services.length) {
        return `<span class="hint">Run Deep Scan to enumerate services and characteristics.</span>`;
      }
      return services.map((service) => {
        const chars = (service.characteristics || []).map((char) =>
          `<div class="uuid-item">${escapeHtml(char.uuid)} · ${escapeHtml((char.properties || []).join(", "))}</div>`
        ).join("");
        return `<div style="margin-bottom:8px;"><strong>${escapeHtml(service.uuid)}</strong>${chars}</div>`;
      }).join("");
    }

    function drawSignalGraph(device) {
      const canvas = document.getElementById("signal-graph");
      if (!canvas) return;
      const ctx = canvas.getContext("2d");
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      ctx.strokeStyle = "#26324b";
      ctx.lineWidth = 1;
      for (let i = 0; i <= 4; i++) {
        const y = 16 + i * ((canvas.height - 32) / 4);
        ctx.beginPath();
        ctx.moveTo(36, y);
        ctx.lineTo(canvas.width - 12, y);
        ctx.stroke();
      }
      ctx.fillStyle = varMuted();
      ctx.font = "11px sans-serif";
      ctx.fillText("-30 dBm", 40, 24);
      ctx.fillText("-100 dBm", 40, canvas.height - 8);

      if (!device || !device.rssi_history || !device.rssi_history.length) {
        ctx.fillStyle = varMuted();
        ctx.fillText("Select a device to plot RSSI history", 44, canvas.height / 2);
        return;
      }

      const values = device.rssi_history;
      const step = (canvas.width - 52) / Math.max(values.length - 1, 1);
      ctx.strokeStyle = "#f472b6";
      ctx.lineWidth = 2;
      ctx.beginPath();
      values.forEach((rssi, index) => {
        const x = 36 + index * step;
        const y = mapRssiToY(rssi, canvas.height);
        if (index === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.stroke();
    }

    function varMuted() {
      return getComputedStyle(document.documentElement).getPropertyValue("--muted").trim() || "#93a1ba";
    }

    function mapRssiToY(rssi, height) {
      const clamped = Math.max(-100, Math.min(-30, Number(rssi) || -100));
      const pct = (clamped + 100) / 70;
      return height - 16 - pct * (height - 32);
    }

    function renderDeviceDetails() {
      const root = document.getElementById("device-details");
      const toy = selectedToy();
      drawSignalGraph(toy);
      if (!toy) {
        root.className = "empty";
        root.textContent = "Select a scanned device to inspect UUIDs and advertisement data.";
        return;
      }

      const findings = (toy.findings || []).length
        ? toy.findings.map((finding) =>
            `<div class="finding"><strong class="severity-${escapeHtml(finding.severity)}">${escapeHtml(finding.title)}</strong><br>${escapeHtml(finding.detail)}</div>`
          ).join("")
        : `<div class="hint">No anomalies flagged from current observations.</div>`;

      const controlLines = toy.control_uuids && toy.control_uuids.service_uuid
        ? `<dt>Control service UUID</dt><dd>${escapeHtml(toy.control_uuids.service_uuid)}</dd>
           <dt>Control TX UUID</dt><dd>${escapeHtml(toy.control_uuids.tx_uuid)}</dd>`
        : "";

      root.className = "";
      root.innerHTML = `
        <h3 style="margin:0 0 8px 0;">${escapeHtml(deviceTitle(toy))}</h3>
        <dl class="device-info">
          <dt>MAC address</dt><dd>${escapeHtml(toy.address)}</dd>
          <dt>Advertised name</dt><dd>${escapeHtml(toy.name || "none")}</dd>
          <dt>Local name</dt><dd>${escapeHtml(toy.local_name || "none")}</dd>
          <dt>Address class</dt><dd>${escapeHtml(toy.address_family || "unknown")}</dd>
          <dt>Address type</dt><dd>${escapeHtml(toy.address_type || "unknown")}</dd>
          <dt>Connectable</dt><dd>${escapeHtml(formatNullable(toy.is_connectable))}</dd>
          <dt>Adorime match</dt><dd>${toy.controllable ? "yes" : "no"}</dd>
          <dt>Galaku service</dt><dd>${toy.galaku_service ? "yes" : "no"}</dd>
          <dt>Protocol</dt><dd>${escapeHtml(toy.protocol || "none")}</dd>
          ${controlLines}
          <dt>Manufacturer</dt><dd>${escapeHtml(toy.manufacturer_hex || "unknown")}</dd>
          <dt>Manufacturer data</dt><dd>${renderManufacturerData(toy.manufacturer_data)}</dd>
          <dt>Service data</dt><dd>${renderServiceData(toy.details?.service_data)}</dd>
          <dt>TX power</dt><dd>${escapeHtml(formatNullable(toy.tx_power, " dBm"))}</dd>
          <dt>Raw RSSI</dt><dd>${escapeHtml(formatNullable(toy.rssi, " dBm"))}</dd>
          <dt>Smoothed RSSI</dt><dd>${escapeHtml(formatNullable(toy.rssi_smoothed, " dBm"))}</dd>
          <dt>Signal quality</dt><dd>${escapeHtml(toy.signal_quality || toy.signal_stats?.quality || "unknown")} · avg ${escapeHtml(formatNullable(toy.signal_stats?.average, " dBm"))} · min ${escapeHtml(formatNullable(toy.signal_stats?.min, " dBm"))} · max ${escapeHtml(formatNullable(toy.signal_stats?.max, " dBm"))}</dd>
          <dt>Device type</dt><dd>${escapeHtml(toy.device_type || "unknown")} (${escapeHtml(toy.transport || "ble")})</dd>
          <dt>Estimated distance</dt><dd>${escapeHtml(formatDistance(toy.estimated_distance_m))} (${escapeHtml(toy.distance_label || "unknown")})</dd>
          <dt>Movement</dt><dd>${escapeHtml(toy.movement || "collecting")}</dd>
          <dt>First seen</dt><dd>${escapeHtml(toy.first_seen)}</dd>
          <dt>Last seen</dt><dd>${escapeHtml(toy.last_seen)} (${escapeHtml(toy.stale_seconds)}s ago)</dd>
          <dt>Seen count</dt><dd>${escapeHtml(toy.seen_count)}</dd>
          <dt>Reappearances</dt><dd>${escapeHtml(toy.reappear_count)}</dd>
          <dt>Service UUIDs</dt><dd>${renderUuidList(toy.service_uuids || [], toy)}</dd>
          <dt>GATT services</dt><dd>${renderGattServices(toy)}</dd>
        </dl>
        <h3 style="margin:18px 0 8px 0;">Findings</h3>
        ${findings}
      `;
    }

    function formatNullable(value, suffix = "") {
      if (value === null || value === undefined || value === "") return "unknown";
      return `${value}${suffix}`;
    }

    function statusBadge(toy) {
      if (toy.connected) return `<span class="badge connected">Connected</span>`;
      return `<span class="badge ${toy.present ? "present" : "gone"}">${toy.present ? "In range" : "Left"}</span>`;
    }

    function rssiBar(rssi) {
      const pct = Math.max(4, Math.min(100, ((rssi + 100) / 55) * 100));
      return `<div class="bar"><div style="width:${pct}%"></div></div>`;
    }

    function formatDistance(meters) {
      if (typeof meters !== "number") return "distance unknown";
      if (meters < 1) return `${Math.round(meters * 100)} cm est.`;
      return `${meters.toFixed(2)} m est.`;
    }

    function toPercent(rssi) {
      if (typeof rssi !== "number") return 0;
      const clamped = Math.max(-100, Math.min(-35, rssi));
      return Math.round(((clamped + 100) / 65) * 100);
    }

    function hexToRgba(hex, alpha) {
      const clean = hex.replace("#", "");
      const bigint = parseInt(clean, 16);
      const r = (bigint >> 16) & 255;
      const g = (bigint >> 8) & 255;
      const b = bigint & 255;
      return `rgba(${r},${g},${b},${alpha})`;
    }

    function hashToAngle(text) {
      let hash = 0;
      for (let i = 0; i < text.length; i++) {
        hash = ((hash << 5) - hash) + text.charCodeAt(i);
        hash |= 0;
      }
      return (hash >>> 0) % 360 * (Math.PI / 180);
    }

    function lookupCalibratedDistance(rssi) {
      const calibration = RSSI_DISTANCE_CALIBRATION;
      const points = calibration.points;
      const strongest = points[0];
      const weakest = points[points.length - 1];
      if (rssi >= strongest.rssi_dbm) return calibration.min_distance_m;
      if (rssi <= weakest.rssi_dbm) return calibration.max_distance_m;
      for (let index = 0; index < points.length - 1; index += 1) {
        const upper = points[index];
        const lower = points[index + 1];
        if (rssi <= upper.rssi_dbm && rssi >= lower.rssi_dbm) {
          if (upper.rssi_dbm === lower.rssi_dbm) return upper.distance_m;
          const ratio = (rssi - upper.rssi_dbm) / (lower.rssi_dbm - upper.rssi_dbm);
          const logUpper = Math.log10(upper.distance_m);
          const logLower = Math.log10(lower.distance_m);
          return Math.max(
            calibration.min_distance_m,
            Math.min(Math.pow(10, logUpper + ratio * (logLower - logUpper)), calibration.max_distance_m),
          );
        }
      }
      return calibration.max_distance_m;
    }

    function estimateDistanceFromRssi(rssi, txPower) {
      if (typeof rssi !== "number") return RSSI_DISTANCE_CALIBRATION.max_distance_m;
      const adjusted = typeof txPower === "number"
        ? rssi + (RSSI_DISTANCE_CALIBRATION.reference_tx_power_dbm - txPower)
        : rssi;
      return lookupCalibratedDistance(adjusted);
    }

    function mapDistanceToRadius(distanceMeters, maxRadius) {
      const maxDistance = RSSI_DISTANCE_CALIBRATION.max_distance_m;
      const distance = Math.max(0.2, Math.min(distanceMeters || maxDistance, maxDistance));
      const normalized = Math.log10(distance + 1) / Math.log10(maxDistance + 1);
      return 22 + normalized * (maxRadius - 22);
    }

    function shortLabel(device) {
      const name = (device.name || device.local_name || "").trim();
      if (name) return name.length > 18 ? `${name.slice(0, 17)}…` : name;
      return device.address.slice(-8);
    }

    function drawRadarMap(devices) {
      const canvas = document.getElementById("radar-map");
      if (!canvas) return;
      const ctx = canvas.getContext("2d");
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      const centerX = canvas.width / 2;
      const centerY = canvas.height / 2;
      const maxRadius = Math.min(canvas.width, canvas.height) * 0.43;
      const ringDistances = [1, 3, 8, 20];

      ctx.strokeStyle = "#3f2a3d";
      ctx.lineWidth = 1;
      for (const dist of ringDistances) {
        const ring = mapDistanceToRadius(dist, maxRadius);
        ctx.beginPath();
        ctx.arc(centerX, centerY, ring, 0, Math.PI * 2);
        ctx.stroke();
        ctx.fillStyle = "#93a1ba";
        ctx.font = "11px sans-serif";
        ctx.fillText(`${dist}m`, centerX + ring + 4, centerY - 2);
      }

      ctx.beginPath();
      ctx.arc(centerX, centerY, 6, 0, Math.PI * 2);
      ctx.fillStyle = "#f472b6";
      ctx.fill();
      ctx.fillStyle = "#93a1ba";
      ctx.font = "11px sans-serif";
      ctx.fillText("you", centerX + 10, centerY + 4);

      if (!devices.length) {
        ctx.fillStyle = "#93a1ba";
        ctx.font = "14px sans-serif";
        ctx.fillText("No devices to plot yet", centerX - 72, centerY);
        return;
      }

      const plotted = devices.filter((d) => d.present).concat(devices.filter((d) => !d.present));
      for (const device of plotted) {
        const estimatedDistance = typeof device.estimated_distance_m === "number"
          ? device.estimated_distance_m
          : estimateDistanceFromRssi(device.rssi_smoothed ?? device.rssi, device.tx_power);
        const angle = hashToAngle(device.address);
        const radius = mapDistanceToRadius(estimatedDistance, maxRadius);
        const x = centerX + Math.cos(angle) * radius;
        const y = centerY + Math.sin(angle) * radius;
        let color = "#64748b";
        if (device.address === selectedAddress) color = "#f472b6";
        else if (device.controllable) color = "#22c55e";
        else if (device.present) color = "#38bdf8";
        const alpha = device.present ? 0.9 : 0.35;
        const size = 4 + Math.round((toPercent(device.rssi_smoothed ?? device.rssi) / 100) * 7);

        ctx.strokeStyle = `rgba(244,114,182,${alpha * 0.25})`;
        ctx.beginPath();
        ctx.moveTo(centerX, centerY);
        ctx.lineTo(x, y);
        ctx.stroke();

        ctx.beginPath();
        ctx.arc(x, y, size, 0, Math.PI * 2);
        ctx.fillStyle = hexToRgba(color, alpha);
        ctx.fill();

        ctx.fillStyle = "#edf2ff";
        ctx.font = "11px sans-serif";
        ctx.fillText(shortLabel(device), x + size + 3, y - 4);
      }
    }

    function renderDeviceCards() {
      const root = document.getElementById("device-cards");
      if (!root) return;
      const devices = filteredDevices();
      drawRadarMap(devices);

      if (!snapshot || !snapshot.toys.length) {
        root.className = "device-cards empty";
        root.textContent = "No nearby Bluetooth devices yet. Turn Scan ON and wait for advertisements.";
        return;
      }
      if (!devices.length) {
        root.className = "device-cards empty";
        root.textContent = "No devices match the current filter.";
        return;
      }

      root.className = "device-cards";
      root.innerHTML = devices.map((toy) => `
        <article class="device-card ${toy.controllable ? "controllable" : ""} ${toy.address === selectedAddress ? "active" : ""} ${toy.connected ? "connected" : ""}" data-address="${escapeHtml(toy.address)}">
          <div class="device-card-head">
            <div>
              <div class="device-card-name">${escapeHtml(deviceTitle(toy))}</div>
              <div class="device-card-addr">${escapeHtml(toy.address)}</div>
            </div>
            <div style="display:flex; gap:4px; flex-wrap:wrap; justify-content:end;">
              ${brandBadge(toy)}
            </div>
          </div>
          ${rssiBar(toy.rssi ?? -100)}
          <div class="device-card-meta">
            <span>RSSI ${toy.rssi ?? "?"} dBm · ${escapeHtml(toy.movement || "collecting")}</span>
            <span>${escapeHtml(formatDistance(toy.estimated_distance_m))}</span>
          </div>
          <div class="device-card-meta">
            <span>${toy.service_uuids?.length || 0} service UUID(s)</span>
            ${statusBadge(toy)}
          </div>
        </article>
      `).join("");
      root.querySelectorAll(".device-card").forEach((node) => {
        node.addEventListener("click", () => selectToy(node.dataset.address));
      });
    }

    async function api(path, options) {
      const response = await fetch(path, options);
      if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        throw new Error(detail.detail || response.statusText);
      }
      return response.json();
    }

    async function selectToy(address) {
      selectedAddress = address;
      panelSignature = null;
      await api("/api/select", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ address }),
      });
      render();
    }

    async function connectToy(address) {
      try {
        await api(`/api/toys/${encodeURIComponent(address)}/connect`, { method: "POST" });
        panelSignature = null;
        showError("");
      } catch (err) {
        showError(err.message || "Connection failed");
      }
    }

    async function disconnectToy(address) {
      try {
        await api(`/api/toys/${encodeURIComponent(address)}/disconnect`, { method: "POST" });
        panelSignature = null;
        showError("");
      } catch (err) {
        showError(err.message || "Disconnect failed");
      }
    }

    async function sendLevels(address) {
      try {
        await api(`/api/toys/${encodeURIComponent(address)}/control`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ levels: localLevels[address] || {} }),
        });
        showError("");
      } catch (err) {
        showError(err.message || "Control command failed");
      }
    }

    function queueLiveControl(address) {
      clearTimeout(controlTimer);
      controlTimer = setTimeout(() => sendLevels(address), 150);
    }

    async function runPattern(address, pattern) {
      try {
        await api(`/api/toys/${encodeURIComponent(address)}/pattern`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ pattern }),
        });
        panelSignature = null;
        showError("");
      } catch (err) {
        showError(err.message || "Pattern command failed");
      }
    }

    function selectedToy() {
      if (!snapshot) return null;
      const selected = snapshot.toys.find((toy) => toy.address === selectedAddress);
      if (selected) return selected;
      const controllable = snapshot.toys.find((toy) => toy.controllable && toy.present);
      return controllable || snapshot.toys.find((toy) => toy.present) || snapshot.toys[0] || null;
    }

    function applyTheme(_theme) {
      document.body.className = "";
    }

    function panelKey(toy) {
      if (!toy) return "none";
      return [
        toy.address,
        toy.connected,
        toy.controllable,
        toy.active_pattern || "",
        (toy.motors || []).map((motor) => motor.id).join(","),
      ].join("|");
    }

    function ensureLocalLevels(toy) {
      if (!localLevels[toy.address]) {
        localLevels[toy.address] = Object.fromEntries((toy.motors || []).map((motor) => [motor.id, toy.levels[motor.id] ?? 0]));
      }
    }

    function syncLevelsFromServer(toy) {
      ensureLocalLevels(toy);
      for (const motor of toy.motors || []) {
        localLevels[toy.address][motor.id] = toy.levels[motor.id] ?? 0;
      }
    }

    function setMotorLevel(toy, motorId, rawValue, options = {}) {
      const value = clampLevel(rawValue);
      ensureLocalLevels(toy);
      localLevels[toy.address][motorId] = value;
      const slider = document.querySelector(`#control-panel input[data-motor="${motorId}"]`);
      const master = document.getElementById("master-thrust");
      const valueEl = document.getElementById(`value-${motorId}`);
      const meterEl = document.getElementById(`meter-${motorId}`);
      const masterValue = document.getElementById("master-thrust-value");
      if (slider) slider.value = value;
      if (valueEl) valueEl.textContent = `${value}%`;
      if (meterEl) meterEl.textContent = value;
      if (motorId === "thrust" && master && !options.skipMaster) master.value = value;
      if (motorId === "thrust" && masterValue) masterValue.textContent = `${value}%`;
      if (linkVibrate && !options.skipLink && hasMotor(toy, "thrust") && hasMotor(toy, "vibrate") && motorId === "thrust") {
        const linked = clampLevel(Math.round(value * 0.75));
        setMotorLevel(toy, "vibrate", linked, { skipMaster: true, skipSend: true, skipLink: true });
      }
      if (!options.skipSend && toy.connected) queueLiveControl(toy.address);
    }

    function applyQuickLevel(toy, motorId, level) {
      setMotorLevel(toy, motorId, level);
      if (toy.connected) sendLevels(toy.address);
    }

    function applyFocusMode(toy, focus) {
      controlFocus = focus;
      document.querySelectorAll("#control-panel [data-focus]").forEach((node) => {
        node.classList.toggle("active", node.dataset.focus === focus);
      });
      if (!toy.connected) return;
      if (focus === "thrust" && hasMotor(toy, "vibrate")) {
        setMotorLevel(toy, "vibrate", 0, { skipSend: true });
      }
      if (focus === "vibrate" && hasMotor(toy, "thrust")) {
        setMotorLevel(toy, "thrust", 0, { skipSend: true });
      }
      sendLevels(toy.address);
    }

    function updateControlReadouts(toy) {
      if (!toy || !toy.controllable) return;
      const linked = document.getElementById("status-linked");
      const pattern = document.getElementById("status-pattern");
      if (linked) linked.textContent = toy.connected ? "Linked" : "Not connected";
      if (pattern) {
        pattern.textContent = toy.active_pattern ? `Active: ${toy.active_pattern}` : "Manual control";
        pattern.style.display = "inline-block";
      }
      for (const motor of toy.motors || []) {
        const value = sliderDragging ? (localLevels[toy.address]?.[motor.id] ?? 0) : (toy.levels[motor.id] ?? 0);
        if (!sliderDragging) {
          localLevels[toy.address][motor.id] = value;
        }
        setMotorLevel(toy, motor.id, value, { skipMaster: sliderDragging, skipSend: true, skipLink: true });
      }
      document.querySelectorAll("#control-panel .pattern, #control-panel .mode-btn").forEach((node) => {
        node.classList.toggle("active", toy.active_pattern === node.dataset.pattern);
        node.disabled = !toy.connected;
      });
      document.querySelectorAll("#control-panel .quick-btn").forEach((node) => {
        node.disabled = !toy.connected;
      });
      const connectBtn = document.getElementById("connect-btn");
      const disconnectBtn = document.getElementById("disconnect-btn");
      const stopBtn = document.getElementById("stop-btn");
      if (connectBtn) connectBtn.disabled = toy.connected;
      if (disconnectBtn) disconnectBtn.disabled = !toy.connected;
      if (stopBtn) stopBtn.disabled = !toy.connected;
      document.querySelectorAll("#control-panel input[type=range]").forEach((input) => {
        input.disabled = !toy.connected;
      });
      const linkToggle = document.getElementById("link-vibrate");
      if (linkToggle) linkToggle.checked = linkVibrate;
      document.querySelectorAll("#control-panel [data-focus]").forEach((node) => {
        node.classList.toggle("active", node.dataset.focus === controlFocus);
      });
      const controlsBody = document.getElementById("controls-body");
      if (controlsBody) controlsBody.classList.toggle("disabled-overlay", !toy.connected);
    }

    function renderModeButtons(modes, toy, activePattern) {
      return (modes || []).map((mode) => `
        <button type="button" class="mode-btn ${activePattern === mode.id ? "active" : ""}" data-pattern="${mode.id}" ${toy.connected ? "" : "disabled"}>
          <div class="mode-icon">${mode.icon}</div>
          <div class="mode-label">${mode.label}</div>
        </button>
      `).join("");
    }

    function renderQuickLevels(toy, motorId) {
      const levels = snapshot?.quick_levels || [0, 25, 50, 75, 100];
      return levels.map((level) => `
        <button type="button" class="quick-btn" data-motor="${motorId}" data-level="${level}" ${toy.connected ? "" : "disabled"}>${level}%</button>
      `).join("");
    }

    function notifyEvents(events) {
      if (!("Notification" in window) || Notification.permission !== "granted") return;
      for (const event of events.slice(-8)) {
        const key = `${event.at}:${event.type}:${event.address}`;
        if (notifiedEvents.has(key)) continue;
        notifiedEvents.add(key);
        if (["new", "entered", "left", "connected", "disconnected"].includes(event.type)) {
          new Notification(`${event.type}: ${event.name || event.address}`, { body: event.message });
        }
      }
    }

    function renderToyList() {
      const root = document.getElementById("found-devices");
      const summary = document.getElementById("found-devices-summary");
      const devices = filteredDevices();
      const total = snapshot?.toys?.length || 0;
      const present = snapshot?.present_count || 0;
      const adorime = snapshot?.adorime_count || 0;

      if (summary) {
        summary.innerHTML = total
          ? `<b>${devices.length}</b> shown · <b>${total}</b> found · <b>${present}</b> in range · <b>${adorime}</b> Adorime`
          : "No devices found yet";
      }

      if (!snapshot || total === 0) {
        root.className = "empty";
        root.style.padding = "24px";
        root.textContent = "No Bluetooth devices observed yet. Click Scan ON or Deep Scan and keep devices advertising nearby.";
        return;
      }
      if (devices.length === 0) {
        root.className = "empty";
        root.style.padding = "24px";
        root.textContent = "No devices match the current filter. Try setting Filter to All devices.";
        return;
      }

      root.className = "";
      root.style.padding = "0";
      root.innerHTML = `
        <table class="device-table">
          <thead>
            <tr>
              <th>Device</th>
              <th>Address</th>
              <th>Signal</th>
              <th>Distance</th>
              <th>Services</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            ${devices.map((toy) => `
              <tr class="${toy.controllable ? "controllable" : "other"} ${toy.address === selectedAddress ? "active" : ""} ${toy.connected ? "connected" : ""}" data-address="${escapeHtml(toy.address)}">
                <td class="col-name">
                  ${escapeHtml(deviceTitle(toy))}
                  <div class="col-meta">${escapeHtml(toy.name && toy.name !== deviceTitle(toy) ? toy.name : (toy.local_name || "Unnamed"))}</div>
                </td>
                <td class="col-addr">${escapeHtml(toy.address)}</td>
                <td class="col-rssi">${toy.rssi ?? "?"} dBm<br><span class="col-meta">${escapeHtml(toy.signal_quality || "unknown")} · ${escapeHtml(toy.movement || "collecting")}</span></td>
                <td class="col-meta">${escapeHtml(formatDistance(toy.estimated_distance_m))}<br>${escapeHtml(toy.distance_label || "")}</td>
                <td class="col-meta">${toy.service_uuids?.length || 0} UUID(s)${toy.galaku_service ? "<br>Galaku svc" : ""}${toy.manufacturer_hex ? `<br>${escapeHtml(toy.manufacturer_hex)}` : ""}</td>
                <td><div class="badge-cell">${brandBadge(toy)} ${statusBadge(toy)}</div></td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      `;
      root.querySelectorAll("tbody tr").forEach((row) => {
        row.addEventListener("click", () => selectToy(row.dataset.address));
      });
    }

    function bindControlPanel(toy) {
      document.getElementById("connect-btn")?.addEventListener("click", () => connectToy(toy.address));
      document.getElementById("disconnect-btn")?.addEventListener("click", () => disconnectToy(toy.address));
      document.getElementById("stop-btn")?.addEventListener("click", () => runPattern(toy.address, "stop"));

      document.querySelectorAll("#control-panel input[type=range]").forEach((input) => {
        input.addEventListener("pointerdown", () => { sliderDragging = true; });
        input.addEventListener("pointerup", () => {
          sliderDragging = false;
          if (toy.connected) sendLevels(toy.address);
        });
        input.addEventListener("input", () => {
          setMotorLevel(toy, input.dataset.motor, Number(input.value), { skipSend: false });
        });
      });

      document.getElementById("master-thrust")?.addEventListener("pointerdown", () => { sliderDragging = true; });
      document.getElementById("master-thrust")?.addEventListener("pointerup", () => {
        sliderDragging = false;
        if (toy.connected) sendLevels(toy.address);
      });
      document.getElementById("master-thrust")?.addEventListener("input", (event) => {
        setMotorLevel(toy, "thrust", Number(event.target.value));
      });

      document.querySelectorAll("#control-panel .quick-btn").forEach((node) => {
        node.addEventListener("click", () => {
          if (!toy.connected || node.disabled) return;
          applyQuickLevel(toy, node.dataset.motor, Number(node.dataset.level));
        });
      });

      document.querySelectorAll("#control-panel [data-focus]").forEach((node) => {
        node.addEventListener("click", () => applyFocusMode(toy, node.dataset.focus));
      });

      document.getElementById("link-vibrate")?.addEventListener("change", (event) => {
        linkVibrate = event.target.checked;
        if (linkVibrate && hasMotor(toy, "thrust")) {
          const thrustLevel = localLevels[toy.address]?.thrust ?? 0;
          setMotorLevel(toy, "vibrate", clampLevel(Math.round(thrustLevel * 0.75)));
        }
      });

      document.querySelectorAll("#control-panel .pattern, #control-panel .mode-btn").forEach((node) => {
        node.addEventListener("click", () => {
          if (!toy.connected || node.disabled) return;
          runPattern(toy.address, node.dataset.pattern);
        });
      });

      document.getElementById("ai-suggest-btn")?.addEventListener("click", async () => {
        try {
          const suggestion = await api(`/api/toys/${encodeURIComponent(toy.address)}/ai-suggest`);
          showError(`AI: thrust ${suggestion.suggested_levels?.thrust ?? "?"}% · ${(suggestion.notes || []).join(" ")}`);
        } catch (err) {
          showError(err.message || "AI suggestion failed");
        }
      });
      document.getElementById("ai-apply-btn")?.addEventListener("click", async () => {
        try {
          await api(`/api/toys/${encodeURIComponent(toy.address)}/ai-apply`, { method: "POST" });
          showError("");
        } catch (err) {
          showError(err.message || "AI apply failed");
        }
      });
      async function sendThruster(direction, pulseMode) {
        const throttle = Number(document.getElementById("master-thrust")?.value || localLevels[toy.address]?.thrust || 0);
        await api(`/api/toys/${encodeURIComponent(toy.address)}/thruster`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ throttle, direction, pulse_mode: pulseMode }),
        });
      }
      document.getElementById("thruster-forward")?.addEventListener("click", () => {
        if (toy.connected) sendThruster("forward", false).catch((err) => showError(err.message));
      });
      document.getElementById("thruster-reverse")?.addEventListener("click", () => {
        if (toy.connected) sendThruster("reverse", false).catch((err) => showError(err.message));
      });
      document.getElementById("thruster-pulse")?.addEventListener("click", () => {
        if (toy.connected) sendThruster("forward", true).catch((err) => showError(err.message));
      });
    }

    function renderControlPanel() {
      const root = document.getElementById("control-panel");
      const toy = selectedToy();
      applyTheme("adorime");

      if (!toy) {
        panelSignature = null;
        root.className = "";
        root.innerHTML = `
          <div class="hero-card">
            <div class="control-title">Adorime thrust controls</div>
            <div class="control-sub">Select a live Adorime toy from the list to connect and drive thrust/vibration.</div>
          </div>
          <div class="control-section disabled-overlay">
            <h2>Master thrust</h2>
            <div class="master-block">
              <div class="master-head">
                <div>
                  <div class="master-value" id="master-thrust-value">0%</div>
                  <div class="master-caption">Waiting for device</div>
                </div>
              </div>
              <input type="range" id="master-thrust" min="0" max="100" step="1" value="0" disabled>
              <div class="quick-levels">${renderQuickLevels({ connected: false }, "thrust")}</div>
            </div>
          </div>
          <p class="hint">Scan the device list for an Adorime or Galaku badge, then connect to unlock thrust control.</p>
        `;
        return;
      }

      if (!toy.controllable) {
        panelSignature = null;
        root.className = "";
        root.innerHTML = `
          <p class="hint">This scanned device is not recognized as an Adorime/Galaku thruster, so thrust controls are unavailable. Inspect UUIDs and advertisement data in <strong>Device details</strong> above.</p>
          ${toy.galaku_service ? `<p class="hint">Galaku control service UUID detected — if this is your thruster, power-cycle it so the advertised name (for example BGSF or SN80) appears, then select it again.</p>` : ""}
        `;
        return;
      }

      ensureLocalLevels(toy);
      const signature = panelKey(toy);
      const needsRebuild = signature !== panelSignature || !document.getElementById("controls-body");
      const thrust = thrustMotor(toy);
      const vibrate = vibrateMotor(toy);
      const motors = toy.motors.length ? toy.motors : [{ id: "vibrate", label: "Vibration", type: "vibrate" }];
      const thrustLevel = localLevels[toy.address][thrust?.id || "thrust"] ?? 0;

      if (needsRebuild) {
        panelSignature = signature;
        syncLevelsFromServer(toy);

        const sliders = motors.map((motor) => `
          <div class="slider-block">
            <div class="slider-label"><span>${motor.label}</span><span id="value-${motor.id}">${localLevels[toy.address][motor.id] ?? 0}%</span></div>
            <input type="range" min="0" max="100" step="1" value="${localLevels[toy.address][motor.id] ?? 0}" data-motor="${motor.id}" ${toy.connected ? "" : "disabled"}>
            <div class="quick-levels">${renderQuickLevels(toy, motor.id)}</div>
          </div>
        `).join("");

        const patterns = (snapshot.patterns || []).map((pattern) => `
          <button type="button" class="pattern ${toy.active_pattern === pattern.id ? "active" : ""}" data-pattern="${pattern.id}" ${toy.connected ? "" : "disabled"}>
            <div class="pattern-icon">${pattern.icon}</div>
            <div class="pattern-label">${pattern.label}</div>
          </button>
        `).join("");

        const thrustModes = thrust
          ? renderModeButtons(snapshot.thrust_modes || [], toy, toy.active_pattern)
          : `<div class="hint">This model has no separate thrust motor.</div>`;

        const vibrateModes = renderModeButtons(snapshot.vibrate_modes || [], toy, toy.active_pattern);

        root.className = "";
        root.innerHTML = `
          <div class="hero-card">
            <div class="control-head">
              <div>
                <div class="control-title">${toy.display_name}</div>
                <div class="control-sub">Adorime BLE · ${toy.address}</div>
                <div class="status-line">
                  <span class="status-pill" id="status-linked">${toy.connected ? "Linked" : "Not connected"}</span>
                  <span class="status-pill">${toy.distance_label || "unknown"} range</span>
                  <span class="status-pill">${toy.movement || "collecting"}</span>
                  <span class="status-pill" id="status-pattern">${toy.active_pattern ? `Active: ${toy.active_pattern}` : "Manual control"}</span>
                </div>
              </div>
              <div class="actions">
                ${toy.connected
                  ? `<button class="secondary" id="disconnect-btn">Disconnect</button>`
                  : `<button id="connect-btn">Connect</button>`}
                <button class="danger" id="stop-btn" ${toy.connected ? "" : "disabled"}>Stop all</button>
                <button class="secondary" id="ai-suggest-btn">AI suggest</button>
                <button class="secondary" id="ai-apply-btn" ${toy.connected ? "" : "disabled"}>Apply AI</button>
              </div>
            </div>
            <div class="meter-grid">
              ${motors.map((motor) => `
                <div class="meter">
                  <div class="meter-value" id="meter-${motor.id}">${localLevels[toy.address][motor.id] ?? 0}</div>
                  <div class="meter-label">${motor.label}</div>
                </div>
              `).join("")}
            </div>
          </div>

          <div id="controls-body" class="${toy.connected ? "" : "disabled-overlay"}">
            ${thrust ? `
              <section class="control-section">
                <h2>Master thrust</h2>
                <div class="master-block">
                  <div class="master-head">
                    <div>
                      <div class="master-value" id="master-thrust-value">${thrustLevel}%</div>
                      <div class="master-caption">Live thrust power</div>
                    </div>
                  </div>
                  <input type="range" id="master-thrust" min="0" max="100" step="1" value="${thrustLevel}" data-motor="thrust" ${toy.connected ? "" : "disabled"}>
                  <div class="quick-levels">${renderQuickLevels(toy, "thrust")}</div>
                  <div class="focus-row" style="margin-top:10px;">
                    <button type="button" class="secondary" id="thruster-forward" ${toy.connected ? "" : "disabled"}>Forward</button>
                    <button type="button" class="secondary" id="thruster-reverse" ${toy.connected ? "" : "disabled"}>Reverse</button>
                    <button type="button" class="secondary" id="thruster-pulse" ${toy.connected ? "" : "disabled"}>Pulse mode</button>
                  </div>
                </div>
              </section>
            ` : ""}

            <div class="focus-row">
              ${thrust ? `<button type="button" class="secondary ${controlFocus === "thrust" ? "active" : ""}" data-focus="thrust" ${toy.connected ? "" : "disabled"}>Thrust only</button>` : ""}
              ${thrust && vibrate ? `<button type="button" class="secondary ${controlFocus === "both" ? "active" : ""}" data-focus="both" ${toy.connected ? "" : "disabled"}>Both motors</button>` : ""}
              ${vibrate ? `<button type="button" class="secondary ${controlFocus === "vibrate" ? "active" : ""}" data-focus="vibrate" ${toy.connected ? "" : "disabled"}>Vibrate only</button>` : ""}
              ${thrust && vibrate ? `
                <label class="link-toggle">
                  <input type="checkbox" id="link-vibrate" ${linkVibrate ? "checked" : ""} ${toy.connected ? "" : "disabled"}>
                  Link vibe to thrust
                </label>
              ` : ""}
            </div>

            <section class="control-section">
              <h2>Motor sliders</h2>
              <p class="hint">Sliders send live BLE commands while connected. Release to confirm the final level.</p>
              <div id="control-sliders">${sliders}</div>
            </section>

            ${thrust ? `
              <section class="control-section">
                <h2>Thrust modes (9)</h2>
                <div class="mode-grid" id="thrust-modes">${thrustModes}</div>
              </section>
            ` : ""}

            <section class="control-section">
              <h2>Vibration modes (10)</h2>
              <div class="mode-grid" id="vibrate-modes">${vibrateModes}</div>
            </section>

            <section class="control-section">
              <h2>Combo patterns</h2>
              <div class="patterns">${patterns}</div>
            </section>
          </div>
        `;
        bindControlPanel(toy);
      } else {
        updateControlReadouts(toy);
      }
    }

    function renderEvents() {
      const root = document.getElementById("events");
      const events = (snapshot?.events || []).slice().reverse().slice(0, 30);
      root.innerHTML = events.map((event) => `
        <div class="event"><strong>${event.at}</strong> · ${event.name || event.address}: ${event.message}</div>
      `).join("") || `<div class="empty">No events yet.</div>`;
    }

    function render() {
      if (!snapshot) return;
      if (!selectedAddress && snapshot.selected_address) {
        selectedAddress = snapshot.selected_address;
      }
      document.getElementById("counts").innerHTML =
        `<b>${snapshot.present_count}</b> in range · <b>${snapshot.device_count ?? snapshot.toy_count}</b> seen · <b>${snapshot.adorime_count ?? snapshot.controllable_count}</b> Adorime · <b>${snapshot.connected_count}</b> connected`;
      document.getElementById("updated").textContent = `Updated ${snapshot.generated_at}`;
      renderScannerStatus();
      renderDeviceCards();
      renderToyList();
      renderDeviceDetails();
      renderControlPanel();
      renderEvents();
      notifyEvents(snapshot.events || []);
    }

    const source = new EventSource("/api/events");
    source.onmessage = (message) => {
      snapshot = JSON.parse(message.data);
      render();
    };
  </script>
</body>
</html>
"""
