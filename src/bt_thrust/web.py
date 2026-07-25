"""FastAPI dashboard for the Bluetooth thrust controller."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from .controller import ToyController
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


def create_app(state: ControllerState, controller: ToyController) -> FastAPI:
    app = FastAPI(title="Adorime Thrust Controller")

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return DASHBOARD_HTML

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
      grid-template-columns: minmax(300px, 360px) 1fr;
      gap: 16px;
      padding: 16px;
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
      main { grid-template-columns: 1fr; }
      .toy-list { max-height: none; }
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
      <h2>Nearby Bluetooth devices</h2>
      <div class="scanner-toolbar">
        <div class="scanner-row">
          <span class="scanner-status"><span class="scanner-dot" id="scanner-dot"></span><span id="scanner-status-text">Scanner starting</span></span>
          <button type="button" class="secondary" id="scanner-toggle">Pause scan</button>
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
        </div>
      </div>
      <div id="toys" class="toy-list empty">Scanning for nearby Bluetooth devices...</div>
    </section>

    <section class="stack">
      <section class="panel">
        <div id="control-panel" class="empty">Loading Adorime thrust controls...</div>
      </section>
      <section class="panel">
        <h2>Recent events</h2>
        <div id="events" class="events"></div>
      </section>
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
      const toggleEl = document.getElementById("scanner-toggle");
      const clearEl = document.getElementById("scanner-clear");

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
      if (toggleEl && toggleEl.dataset.bound !== "1") {
        toggleEl.dataset.bound = "1";
        toggleEl.addEventListener("click", async () => {
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
    }

    function renderScannerStatus() {
      const scanner = snapshot?.scanner || {};
      const dot = document.getElementById("scanner-dot");
      const text = document.getElementById("scanner-status-text");
      const badge = document.getElementById("scanner-badge");
      const toggle = document.getElementById("scanner-toggle");
      const staleEl = document.getElementById("stale-after");
      if (!dot || !text || !toggle) return;

      dot.className = "scanner-dot";
      if (scanner.error) {
        dot.classList.add("error");
        text.textContent = "Scanner retrying";
        if (badge) badge.textContent = "Scanner error";
      } else if (scanner.paused) {
        dot.classList.add("paused");
        text.textContent = "Scanner paused";
        if (badge) badge.textContent = "Scan paused";
      } else if (scanner.active) {
        dot.classList.add("running");
        text.textContent = "Scanner running";
        if (badge) badge.textContent = "Live BLE";
      } else {
        text.textContent = "Scanner starting";
      }
      toggle.textContent = scanner.paused ? "Resume scan" : "Pause scan";
      if (staleEl && document.activeElement !== staleEl) {
        staleEl.value = scanner.stale_after ?? 20;
      }
      bindScannerControls();
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
      const root = document.getElementById("toys");
      const devices = filteredDevices();
      if (!snapshot || snapshot.toys.length === 0) {
        root.className = "toy-list empty";
        root.textContent = "No Bluetooth devices observed yet. Make sure Bluetooth is enabled and devices are advertising nearby.";
        return;
      }
      if (devices.length === 0) {
        root.className = "toy-list empty";
        root.textContent = "No devices match the current scanner filter.";
        return;
      }
      root.className = "toy-list";
      root.innerHTML = devices.map((toy) => `
        <article class="toy ${toy.controllable ? "controllable" : "other"} ${toy.address === selectedAddress ? "active" : ""} ${toy.connected ? "connected" : ""}" data-address="${toy.address}">
          <div class="toy-title">
            <div>
              <div class="name">${deviceTitle(toy)}</div>
              <div class="addr">${toy.address}${toy.name && toy.name !== deviceTitle(toy) ? " · " + toy.name : ""}</div>
            </div>
            <div style="display:flex; gap:6px; flex-wrap:wrap; justify-content:end;">
              ${brandBadge(toy)}
              ${statusBadge(toy)}
            </div>
          </div>
          <div class="signal-row">
            <span>RSSI ${toy.rssi ?? "?"} dBm · ${toy.movement || "collecting"} · ${toy.address_family || "addr ?"}</span>
            <span>${formatDistance(toy.estimated_distance_m)}</span>
          </div>
          ${toy.manufacturer_hex ? `<div class="signal-row"><span>MFG ${toy.manufacturer_hex}</span><span>${toy.service_uuids?.length || 0} service(s)</span></div>` : ""}
          ${toy.galaku_service ? `<div class="signal-row"><span>Galaku control service detected</span><span>${toy.controllable ? "Ready to connect" : "Checking profile"}</span></div>` : ""}
          ${rssiBar(toy.rssi ?? -100)}
        </article>
      `).join("");
      root.querySelectorAll(".toy").forEach((node) => {
        node.addEventListener("click", () => selectToy(node.dataset.address));
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
          <div class="hero-card">
            <div class="control-title">${deviceTitle(toy)}</div>
            <div class="control-sub">${toy.address} · nearby Bluetooth device</div>
            <div class="status-line">
              <span class="status-pill">${toy.present ? "In range" : "Left"}</span>
              <span class="status-pill">${toy.distance_label || "unknown"} range</span>
              <span class="status-pill">${toy.service_uuids?.length || 0} advertised service(s)</span>
            </div>
          </div>
          <p class="hint">This device is visible to the scanner but is not recognized as an Adorime/Galaku thruster. Select a device with an <strong>Adorime</strong> or <strong>Galaku svc</strong> badge to connect and control thrust.</p>
          ${toy.galaku_service ? `<p class="hint">Galaku service UUID detected — if this is your thruster, try power-cycling it so the advertised name (for example BGSF or SN80) appears, then reconnect from the list.</p>` : ""}
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
      renderToyList();
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
