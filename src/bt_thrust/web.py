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
    app = FastAPI(title="Bluetooth Thrust Controller")

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
  <title>Bluetooth Thrust Controller</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #0a0d16;
      --panel: #121827;
      --panel-2: #182033;
      --text: #edf2ff;
      --muted: #93a1ba;
      --accent: #38bdf8;
      --accent-soft: rgba(56, 189, 248, 0.16);
      --green: #22c55e;
      --rose: #ec4899;
      --violet: #a855f7;
    }
    body.theme-adorime {
      --bg: #160812;
      --panel: #24101c;
      --panel-2: #311528;
      --accent: #f472b6;
      --accent-soft: rgba(244, 114, 182, 0.18);
    }
    body.theme-galaku {
      --bg: #0d0818;
      --panel: #17102a;
      --panel-2: #22153b;
      --accent: #c084fc;
      --accent-soft: rgba(192, 132, 252, 0.18);
    }
    body.theme-classic {
      --bg: #0a0d16;
      --panel: #121827;
      --panel-2: #182033;
      --accent: #38bdf8;
      --accent-soft: rgba(56, 189, 248, 0.16);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif;
      background: radial-gradient(circle at top, color-mix(in srgb, var(--accent) 18%, transparent), transparent 42%), var(--bg);
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
    main {
      display: grid;
      grid-template-columns: minmax(320px, 390px) 1fr;
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
    .toy-list { max-height: 74vh; overflow: auto; }
    .toy {
      border: 1px solid #26324b;
      border-radius: 14px;
      padding: 12px;
      margin: 8px 0;
      background: var(--panel-2);
      cursor: pointer;
      transition: transform .12s ease, border-color .12s ease;
    }
    .toy:hover { transform: translateY(-1px); }
    .toy.active { outline: 2px solid var(--accent); border-color: color-mix(in srgb, var(--accent) 55%, #26324b); }
    .toy.connected { box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--green) 45%, transparent); }
    .toy-title { display: flex; justify-content: space-between; gap: 10px; align-items: start; }
    .name { font-weight: 800; }
    .addr { color: var(--muted); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
    .badge {
      border-radius: 999px;
      padding: 4px 8px;
      font-size: 11px;
      font-weight: 700;
      white-space: nowrap;
      text-transform: uppercase;
      letter-spacing: .04em;
    }
    .brand-adorime { background: rgba(236, 72, 153, .18); color: #f9a8d4; }
    .brand-galaku { background: rgba(168, 85, 247, .18); color: #d8b4fe; }
    .brand-unknown { background: rgba(148, 163, 184, .15); color: var(--muted); }
    .brand-generic { background: rgba(56, 189, 248, .15); color: #7dd3fc; }
    .present { background: rgba(34,197,94,.15); color: var(--green); }
    .gone { background: rgba(148,163,184,.15); color: var(--muted); }
    .connected { background: rgba(56,189,248,.15); color: #7dd3fc; }
    .signal-row { display: flex; justify-content: space-between; gap: 8px; font-size: 13px; color: var(--muted); margin: 8px 0 4px 0; }
    .bar { width: 100%; height: 8px; border-radius: 999px; background: #091427; overflow: hidden; border: 1px solid #22324a; }
    .bar > div { height: 100%; background: linear-gradient(90deg, #312e81, var(--accent), #22c55e); }
    .control-head {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      flex-wrap: wrap;
      margin-bottom: 14px;
    }
    .control-title { font-size: 24px; font-weight: 800; }
    .control-sub { color: var(--muted); font-size: 13px; margin-top: 4px; }
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
    button.secondary {
      background: transparent;
      color: var(--text);
      border: 1px solid color-mix(in srgb, var(--accent) 35%, #334155);
    }
    button.danger { background: #ef4444; color: white; }
    .slider-block { margin: 16px 0; }
    .slider-label { display: flex; justify-content: space-between; margin-bottom: 8px; font-size: 14px; }
    .slider-label span:last-child { color: var(--accent); font-weight: 800; }
    input[type=range] { width: 100%; accent-color: var(--accent); }
    .patterns {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
      gap: 10px;
      margin-top: 12px;
    }
    .pattern {
      background: var(--panel-2);
      border: 1px solid #26324b;
      border-radius: 12px;
      padding: 12px;
      text-align: center;
      cursor: pointer;
      transition: border-color .12s ease, background .12s ease;
    }
    .pattern:hover, .pattern.active {
      border-color: var(--accent);
      background: var(--accent-soft);
    }
    .pattern-icon { font-size: 22px; margin-bottom: 6px; }
    .pattern-label { font-size: 13px; font-weight: 700; }
    .meter-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 12px;
      margin-top: 12px;
    }
    .meter {
      background: var(--panel-2);
      border-radius: 14px;
      padding: 12px;
      border: 1px solid #26324b;
    }
    .meter-value { font-size: 28px; font-weight: 800; color: var(--accent); }
    .meter-label { color: var(--muted); font-size: 12px; margin-top: 4px; }
    .events { max-height: 220px; overflow: auto; color: var(--muted); font-size: 13px; }
    .event { padding: 6px 0; border-bottom: 1px solid #1f2937; }
    .empty { color: var(--muted); text-align: center; padding: 34px 0; }
    .hero-card {
      background: linear-gradient(135deg, color-mix(in srgb, var(--accent) 22%, var(--panel-2)), var(--panel-2));
      border-radius: 16px;
      padding: 16px;
      border: 1px solid color-mix(in srgb, var(--accent) 28%, #26324b);
      margin-bottom: 16px;
    }
    @media (max-width: 980px) {
      main { grid-template-columns: 1fr; }
      .toy-list { max-height: none; }
    }
  </style>
</head>
<body class="theme-classic">
  <header>
    <div>
      <h1>Bluetooth Thrust Controller</h1>
      <div class="stats">
        <span id="counts">Waiting for scan data...</span>
        <span id="updated"></span>
      </div>
    </div>
  </header>

  <main>
    <section class="panel">
      <h2>Scanned toys</h2>
      <div id="toys" class="toy-list empty">Scanning for Adorime, Galaku, and compatible BLE toys...</div>
    </section>

    <section class="stack">
      <section class="panel">
        <div id="control-panel" class="empty">Select a recognized toy to open thrust controls.</div>
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

    const themes = {
      adorime: "theme-adorime",
      galaku: "theme-galaku",
      classic: "theme-classic",
      unknown: "theme-classic",
      generic: "theme-classic",
    };

    function brandBadge(brand) {
      const labels = { adorime: "Adorime", galaku: "Galaku", generic: "Generic", unknown: "Unknown" };
      return `<span class="badge brand-${brand}">${labels[brand] || brand}</span>`;
    }

    function statusBadge(toy) {
      if (toy.connected) return `<span class="badge connected">Connected</span>`;
      return `<span class="badge ${toy.present ? "present" : "gone"}">${toy.present ? "In range" : "Left"}</span>`;
    }

    function rssiBar(rssi) {
      const pct = Math.max(4, Math.min(100, ((rssi + 100) / 55) * 100));
      return `<div class="bar"><div style="width:${pct}%"></div></div>`;
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
      await api("/api/select", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ address }),
      });
      render();
    }

    async function connectToy(address) {
      await api(`/api/toys/${encodeURIComponent(address)}/connect`, { method: "POST" });
    }

    async function disconnectToy(address) {
      await api(`/api/toys/${encodeURIComponent(address)}/disconnect`, { method: "POST" });
    }

    async function sendLevels(address) {
      await api(`/api/toys/${encodeURIComponent(address)}/control`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ levels: localLevels[address] || {} }),
      });
    }

    async function runPattern(address, pattern) {
      await api(`/api/toys/${encodeURIComponent(address)}/pattern`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pattern }),
      });
    }

    function selectedToy() {
      if (!snapshot) return null;
      return snapshot.toys.find((toy) => toy.address === selectedAddress) || snapshot.toys[0] || null;
    }

    function applyTheme(theme) {
      document.body.className = themes[theme] || "theme-classic";
    }

    function renderToyList() {
      const root = document.getElementById("toys");
      if (!snapshot || snapshot.toys.length === 0) {
        root.className = "toy-list empty";
        root.textContent = "No compatible toys observed yet.";
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
              ${brandBadge(toy.brand)}
              ${statusBadge(toy)}
            </div>
          </div>
          <div class="signal-row"><span>Signal</span><span>${toy.rssi ?? "—"} dBm</span></div>
          ${rssiBar(toy.rssi ?? -100)}
        </article>
      `).join("");
      root.querySelectorAll(".toy").forEach((node) => {
        node.addEventListener("click", () => selectToy(node.dataset.address));
      });
    }

    function renderControlPanel() {
      const root = document.getElementById("control-panel");
      const toy = selectedToy();
      if (!toy) {
        root.className = "empty";
        root.textContent = "Select a recognized toy to open thrust controls.";
        applyTheme("classic");
        return;
      }
      applyTheme(toy.theme || "classic");
      if (!localLevels[toy.address]) {
        localLevels[toy.address] = { ...toy.levels };
      } else {
        Object.assign(localLevels[toy.address], toy.levels);
      }

      const motors = toy.motors.length ? toy.motors : [{ id: "vibrate", label: "Output", type: "vibrate" }];
      const sliders = motors.map((motor) => `
        <div class="slider-block">
          <div class="slider-label"><span>${motor.label}</span><span id="value-${motor.id}">${localLevels[toy.address][motor.id] ?? 0}%</span></div>
          <input type="range" min="0" max="100" value="${localLevels[toy.address][motor.id] ?? 0}" data-motor="${motor.id}" ${toy.connected ? "" : "disabled"}>
        </div>
      `).join("");

      const patterns = (snapshot.patterns || []).map((pattern) => `
        <div class="pattern ${toy.active_pattern === pattern.id ? "active" : ""}" data-pattern="${pattern.id}">
          <div class="pattern-icon">${pattern.icon}</div>
          <div class="pattern-label">${pattern.label}</div>
        </div>
      `).join("");

      root.className = "";
      root.innerHTML = `
        <div class="hero-card">
          <div class="control-head">
            <div>
              <div class="control-title">${toy.display_name}</div>
              <div class="control-sub">${toy.protocol ? toy.protocol.toUpperCase() + " protocol" : "Unknown protocol"} · ${toy.address}</div>
            </div>
            <div class="actions">
              ${toy.connected
                ? `<button class="secondary" id="disconnect-btn">Disconnect</button>`
                : `<button id="connect-btn" ${toy.brand === "unknown" ? "disabled title='Profile not recognized'" : ""}>Connect</button>`}
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

        <h2>Manual controls</h2>
        ${sliders}
        <div class="actions" style="margin-top:12px;">
          <button id="apply-btn" ${toy.connected ? "" : "disabled"}>Apply levels</button>
        </div>

        <h2 style="margin-top:22px;">Pattern presets</h2>
        <div class="patterns">${patterns}</div>
      `;

      const connectBtn = document.getElementById("connect-btn");
      if (connectBtn) connectBtn.addEventListener("click", () => connectToy(toy.address));
      document.getElementById("disconnect-btn")?.addEventListener("click", () => disconnectToy(toy.address));
      document.getElementById("stop-btn")?.addEventListener("click", () => runPattern(toy.address, "stop"));
      document.getElementById("apply-btn")?.addEventListener("click", () => sendLevels(toy.address));

      root.querySelectorAll("input[type=range]").forEach((input) => {
        input.addEventListener("input", () => {
          const motor = input.dataset.motor;
          localLevels[toy.address][motor] = Number(input.value);
          document.getElementById(`value-${motor}`).textContent = `${input.value}%`;
          document.getElementById(`meter-${motor}`).textContent = input.value;
        });
      });

      root.querySelectorAll(".pattern").forEach((node) => {
        node.addEventListener("click", () => {
          if (!toy.connected) return;
          runPattern(toy.address, node.dataset.pattern);
        });
      });
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
        `<b>${snapshot.present_count}</b> in range · <b>${snapshot.connected_count}</b> connected · <b>${snapshot.toy_count}</b> total`;
      document.getElementById("updated").textContent = `Updated ${snapshot.generated_at}`;
      renderToyList();
      renderControlPanel();
      renderEvents();
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
