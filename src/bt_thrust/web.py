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
    .pattern {
      background: var(--panel-2);
      border: 1px solid #26324b;
      border-radius: 12px;
      padding: 14px 10px;
      text-align: center;
      cursor: pointer;
    }
    .pattern:hover, .pattern.active {
      border-color: var(--accent);
      background: var(--accent-soft);
    }
    .pattern:disabled { opacity: .45; cursor: not-allowed; }
    .pattern-icon { font-size: 24px; margin-bottom: 6px; }
    .pattern-label { font-size: 13px; font-weight: 700; }
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
        <span id="counts">Waiting for live Adorime scan...</span>
        <span id="updated"></span>
      </div>
    </div>
    <div style="display:flex; gap:10px; align-items:center; flex-wrap:wrap;">
      <span class="live-badge">Live Adorime</span>
      <button id="notify">Enable notifications</button>
    </div>
  </header>

  <div id="error-banner" class="error-banner"></div>

  <main>
    <section class="panel">
      <h2>Live Adorime toys</h2>
      <div id="toys" class="toy-list empty">Scanning for live Adorime products...</div>
    </section>

    <section class="stack">
      <section class="panel">
        <div id="control-panel" class="empty">Select an Adorime toy to open thrust controls.</div>
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

    function brandBadge() {
      return `<span class="badge brand-adorime">Adorime</span>`;
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
      return snapshot.toys.find((toy) => toy.address === selectedAddress) || snapshot.toys[0] || null;
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

    function updateControlReadouts(toy) {
      if (!toy || !toy.controllable) return;
      const linked = document.getElementById("status-linked");
      const pattern = document.getElementById("status-pattern");
      if (linked) linked.textContent = toy.connected ? "Linked" : "Not connected";
      if (pattern) {
        pattern.textContent = toy.active_pattern ? `Pattern: ${toy.active_pattern}` : "Manual control";
        pattern.style.display = "inline-block";
      }
      for (const motor of toy.motors || []) {
        const value = sliderDragging ? (localLevels[toy.address]?.[motor.id] ?? 0) : (toy.levels[motor.id] ?? 0);
        if (!sliderDragging) {
          localLevels[toy.address][motor.id] = value;
        }
        const slider = document.querySelector(`#control-panel input[data-motor="${motor.id}"]`);
        const valueEl = document.getElementById(`value-${motor.id}`);
        const meterEl = document.getElementById(`meter-${motor.id}`);
        if (slider && !sliderDragging) slider.value = value;
        if (valueEl) valueEl.textContent = `${value}%`;
        if (meterEl) meterEl.textContent = value;
      }
      document.querySelectorAll("#control-panel .pattern").forEach((node) => {
        node.classList.toggle("active", toy.active_pattern === node.dataset.pattern);
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
      if (!snapshot || snapshot.toys.length === 0) {
        root.className = "toy-list empty";
        root.textContent = "No Adorime toys in range. Power on your device and keep Bluetooth advertising active.";
        return;
      }
      root.className = "toy-list";
      root.innerHTML = snapshot.toys.map((toy) => `
        <article class="toy ${toy.address === selectedAddress ? "active" : ""} ${toy.connected ? "connected" : ""}" data-address="${toy.address}">
          <div class="toy-title">
            <div>
              <div class="name">${toy.display_name}</div>
              <div class="addr">${toy.address}${toy.name ? " · " + toy.name : ""}</div>
            </div>
            <div style="display:flex; gap:6px; flex-wrap:wrap; justify-content:end;">
              ${brandBadge()}
              ${statusBadge(toy)}
            </div>
          </div>
          <div class="signal-row">
            <span>RSSI ${toy.rssi ?? "?"} dBm · ${toy.movement || "collecting"}</span>
            <span>${formatDistance(toy.estimated_distance_m)}</span>
          </div>
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
          const motor = input.dataset.motor;
          localLevels[toy.address][motor] = Number(input.value);
          document.getElementById(`value-${motor}`).textContent = `${input.value}%`;
          document.getElementById(`meter-${motor}`).textContent = input.value;
          if (toy.connected) queueLiveControl(toy.address);
        });
      });

      document.querySelectorAll("#control-panel .pattern").forEach((node) => {
        node.addEventListener("click", () => {
          if (!toy.connected || node.disabled) return;
          runPattern(toy.address, node.dataset.pattern);
        });
      });
    }

    function renderControlPanel() {
      const root = document.getElementById("control-panel");
      const toy = selectedToy();
      if (!toy) {
        panelSignature = null;
        root.className = "empty";
        root.textContent = "Select an Adorime toy to open thrust controls.";
        applyTheme("adorime");
        return;
      }

      applyTheme("adorime");
      ensureLocalLevels(toy);

      const signature = panelKey(toy);
      const needsRebuild = signature !== panelSignature || !document.getElementById("control-sliders");

      if (needsRebuild) {
        panelSignature = signature;
        syncLevelsFromServer(toy);

        const motors = toy.motors.length ? toy.motors : [{ id: "vibrate", label: "Vibration", type: "vibrate" }];
        const sliders = motors.map((motor) => `
          <div class="slider-block">
            <div class="slider-label"><span>${motor.label}</span><span id="value-${motor.id}">${localLevels[toy.address][motor.id] ?? 0}%</span></div>
            <input type="range" min="0" max="100" step="1" value="${localLevels[toy.address][motor.id] ?? 0}" data-motor="${motor.id}" ${toy.connected ? "" : "disabled"}>
          </div>
        `).join("");

        const patterns = (snapshot.patterns || []).map((pattern) => `
          <button type="button" class="pattern ${toy.active_pattern === pattern.id ? "active" : ""}" data-pattern="${pattern.id}" ${toy.connected ? "" : "disabled"}>
            <div class="pattern-icon">${pattern.icon}</div>
            <div class="pattern-label">${pattern.label}</div>
          </button>
        `).join("");

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
                  <span class="status-pill" id="status-pattern">${toy.active_pattern ? `Pattern: ${toy.active_pattern}` : "Manual control"}</span>
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

          <h2>Thrust controls</h2>
          <p class="hint">Sliders send live commands while connected. Release a slider to confirm the final level.</p>
          <div id="control-sliders">${sliders}</div>

          <h2 style="margin-top:22px;">Pattern presets</h2>
          <div class="patterns">${patterns}</div>
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
        `<b>${snapshot.present_count}</b> in range · <b>${snapshot.connected_count}</b> connected · <b>${snapshot.toy_count}</b> Adorime`;
      document.getElementById("updated").textContent = `Updated ${snapshot.generated_at}`;
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
