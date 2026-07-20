"""FastAPI dashboard and control API for AdoRime devices."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from .state import RadarState


class TargetRequest(BaseModel):
    address: str | None = None


class ManualCommandRequest(BaseModel):
    thrust: int = Field(ge=0, le=100)
    pattern: str = Field(default="steady", min_length=1, max_length=24)


class AiControlRequest(BaseModel):
    enabled: bool = True
    aggressiveness: float = Field(default=0.65, ge=0.0, le=1.0)
    min_thrust: int = Field(default=20, ge=0, le=100)
    max_thrust: int = Field(default=90, ge=0, le=100)


def create_app(state: RadarState) -> FastAPI:
    app = FastAPI(title="AdoRime Bluetooth Control")

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return DASHBOARD_HTML

    @app.get("/api/status")
    async def status() -> dict:
        return await state.snapshot()

    @app.post("/api/control/target")
    async def set_target(request: TargetRequest) -> JSONResponse:
        try:
            event = await state.set_control_target(request.address)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse({"event": event, "control": await state.control_snapshot()})

    @app.post("/api/control/manual")
    async def manual_command(request: ManualCommandRequest) -> JSONResponse:
        try:
            event = await state.send_manual_thrust(request.thrust, pattern=request.pattern)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse({"event": event, "control": await state.control_snapshot()})

    @app.post("/api/control/ai")
    async def set_ai(request: AiControlRequest) -> JSONResponse:
        try:
            event = await state.configure_ai_thrust(
                enabled=request.enabled,
                aggressiveness=request.aggressiveness,
                min_thrust=request.min_thrust,
                max_thrust=request.max_thrust,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse({"event": event, "control": await state.control_snapshot()})

    @app.post("/api/control/ai/step")
    async def run_ai_step() -> JSONResponse:
        try:
            event = await state.run_ai_thrust_step()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse({"event": event, "control": await state.control_snapshot()})

    @app.get("/api/events")
    async def events() -> StreamingResponse:
        return StreamingResponse(_event_stream(state), media_type="text/event-stream")

    return app


async def _event_stream(state: RadarState) -> AsyncIterator[str]:
    last_payload = ""
    while True:
        snapshot = await state.snapshot()
        payload = json.dumps(snapshot)
        if payload != last_payload:
            yield f"data: {payload}\n\n"
            last_payload = payload
        await asyncio.sleep(1)


DASHBOARD_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AdoRime Bluetooth Control</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #0b1020;
      --panel: #121a2e;
      --panel-2: #17213a;
      --text: #e8eefc;
      --muted: #94a3b8;
      --green: #22c55e;
      --orange: #f97316;
      --blue: #38bdf8;
    }
    body { margin: 0; font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif; background: var(--bg); color: var(--text); }
    header { padding: 20px 28px; border-bottom: 1px solid #243047; display: flex; justify-content: space-between; align-items: center; gap: 14px; flex-wrap: wrap; }
    h1 { margin: 0; font-size: 22px; }
    h2 { margin: 0 0 10px 0; font-size: 17px; }
    .stats { color: var(--muted); font-size: 14px; display: flex; gap: 12px; flex-wrap: wrap; margin-top: 6px; }
    .shell { display: grid; grid-template-columns: minmax(320px, 420px) 1fr; gap: 16px; padding: 16px; align-items: start; }
    .panel { background: var(--panel); border: 1px solid #243047; border-radius: 14px; padding: 14px; box-shadow: 0 16px 40px rgba(0,0,0,.25); }
    .stack { display: grid; gap: 16px; }
    .devices { max-height: 70vh; overflow: auto; display: grid; gap: 8px; }
    .device { border: 1px solid #26324b; border-radius: 12px; padding: 10px; background: var(--panel-2); }
    .device.selected { outline: 2px solid var(--blue); }
    .device strong { display: block; }
    .device small { color: var(--muted); display: block; margin-top: 3px; }
    .row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-top: 8px; }
    input, select { background: #0d1629; color: var(--text); border: 1px solid #30405f; border-radius: 9px; padding: 7px 9px; }
    input[type=range] { accent-color: var(--blue); padding: 0; }
    button { background: var(--blue); color: #041120; border: 0; border-radius: 9px; padding: 9px 12px; font-weight: 700; cursor: pointer; }
    button.secondary { background: #22304a; color: var(--text); }
    .pill { display: inline-block; border-radius: 999px; padding: 4px 8px; font-size: 12px; font-weight: 700; }
    .ok { background: rgba(34,197,94,.15); color: var(--green); }
    .warn { background: rgba(249,115,22,.15); color: var(--orange); }
    .code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; color: var(--muted); }
    .command { border: 1px solid #2d3b57; border-radius: 10px; padding: 8px; margin-top: 8px; background: #0d1629; }
    .events { max-height: 250px; overflow: auto; font-size: 13px; color: var(--muted); }
    .empty { color: var(--muted); text-align: center; padding: 30px 0; }
    @media (max-width: 980px) { .shell { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>AdoRime Bluetooth Control</h1>
      <div class="stats">
        <span id="counts">Waiting for Bluetooth scan...</span>
        <span id="updated"></span>
      </div>
    </div>
    <button id="notify">Enable browser notifications</button>
  </header>

  <main class="shell">
    <section class="panel">
      <h2>Detected AdoRime devices</h2>
      <div id="devices" class="devices empty">No AdoRime-compatible devices detected yet.</div>
    </section>

    <section class="stack">
      <section class="panel">
        <h2>Control panel</h2>
        <div class="row">
          <label for="target">Target device</label>
          <select id="target"></select>
          <button id="set-target" class="secondary">Set target</button>
          <button id="clear-target" class="secondary">Clear</button>
        </div>
        <div class="row">
          <span id="target-state" class="pill warn">No target selected</span>
          <span id="mode-state" class="pill warn">manual</span>
        </div>
        <hr style="border-color:#243047; margin:14px 0;">

        <h3 style="margin:0 0 8px 0;">Manual thrust control</h3>
        <div class="row">
          <label for="manual-thrust">Thrust %</label>
          <input id="manual-thrust" type="range" min="0" max="100" step="1" value="45">
          <span id="manual-thrust-value">45</span>
          <select id="manual-pattern">
            <option value="steady">steady</option>
            <option value="ramp">ramp</option>
            <option value="pulse">pulse</option>
            <option value="burst">burst</option>
          </select>
          <button id="send-manual">Send manual command</button>
        </div>

        <hr style="border-color:#243047; margin:14px 0;">
        <h3 style="margin:0 0 8px 0;">AI thrust control</h3>
        <div class="row">
          <label><input id="ai-enabled" type="checkbox"> enable AI thrust</label>
          <label>aggressiveness <input id="ai-aggressiveness" type="range" min="0" max="1" step="0.05" value="0.65"></label>
          <span id="ai-aggr-value">0.65</span>
        </div>
        <div class="row">
          <label>min <input id="ai-min" type="number" min="0" max="100" step="1" value="20"></label>
          <label>max <input id="ai-max" type="number" min="0" max="100" step="1" value="90"></label>
          <button id="save-ai">Apply AI settings</button>
          <button id="run-ai-step" class="secondary">Run AI step now</button>
        </div>
      </section>

      <section class="panel">
        <h2>Last command</h2>
        <div id="last-command" class="empty">No thrust command has been sent yet.</div>
        <h2 style="margin-top:16px;">Recent command history</h2>
        <div id="command-history"></div>
      </section>

      <section class="panel">
        <h2>Event stream</h2>
        <div id="events" class="events"></div>
      </section>
    </section>
  </main>

  <script>
    let snapshot = null;
    const notifiedEvents = new Set();

    const notifyBtn = document.getElementById("notify");
    const devicesRoot = document.getElementById("devices");
    const targetSelect = document.getElementById("target");
    const targetState = document.getElementById("target-state");
    const modeState = document.getElementById("mode-state");
    const manualThrust = document.getElementById("manual-thrust");
    const manualThrustValue = document.getElementById("manual-thrust-value");
    const manualPattern = document.getElementById("manual-pattern");
    const aiEnabled = document.getElementById("ai-enabled");
    const aiAggressiveness = document.getElementById("ai-aggressiveness");
    const aiAggrValue = document.getElementById("ai-aggr-value");
    const aiMin = document.getElementById("ai-min");
    const aiMax = document.getElementById("ai-max");

    notifyBtn.onclick = async () => {
      if (!("Notification" in window)) {
        alert("Browser notifications are not supported here.");
        return;
      }
      await Notification.requestPermission();
    };

    manualThrust.oninput = () => {
      manualThrustValue.textContent = String(manualThrust.value);
    };
    aiAggressiveness.oninput = () => {
      aiAggrValue.textContent = Number(aiAggressiveness.value).toFixed(2);
    };

    document.getElementById("set-target").onclick = async () => {
      const address = targetSelect.value || null;
      await postJson("/api/control/target", { address });
    };

    document.getElementById("clear-target").onclick = async () => {
      await postJson("/api/control/target", { address: null });
    };

    document.getElementById("send-manual").onclick = async () => {
      await postJson("/api/control/manual", {
        thrust: Number(manualThrust.value),
        pattern: manualPattern.value,
      });
    };

    document.getElementById("save-ai").onclick = async () => {
      await postJson("/api/control/ai", {
        enabled: aiEnabled.checked,
        aggressiveness: Number(aiAggressiveness.value),
        min_thrust: Number(aiMin.value),
        max_thrust: Number(aiMax.value),
      });
    };

    document.getElementById("run-ai-step").onclick = async () => {
      await postJson("/api/control/ai/step", {});
    };

    const source = new EventSource("/api/events");
    source.onmessage = (message) => {
      snapshot = JSON.parse(message.data);
      render();
      maybeNotify(snapshot.events || []);
    };

    async function postJson(url, body) {
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        alert(payload.detail || "Command failed.");
        return;
      }
    }

    function maybeNotify(events) {
      if (!("Notification" in window) || Notification.permission !== "granted") return;
      for (const event of events.slice(-12)) {
        const key = `${event.at}:${event.type}:${event.address}`;
        if (notifiedEvents.has(key)) continue;
        notifiedEvents.add(key);
        if (event.type === "control-command") {
          new Notification(`AdoRime control: ${event.name || event.address}`, { body: event.message });
        }
      }
    }

    function render() {
      if (!snapshot) return;
      const control = snapshot.control || {};
      const supported = control.supported_devices || [];
      document.getElementById("counts").textContent = `${snapshot.present_count} in range / ${snapshot.device_count} total Bluetooth devices`;
      document.getElementById("updated").textContent = `Updated ${snapshot.generated_at}`;

      renderDevices(supported, control.target_address);
      renderTargetSelect(supported, control.target_address);
      renderControlState(control);
      renderLastCommand(control.last_command);
      renderHistory(control.history || []);
      renderEvents(snapshot.events || []);
    }

    function renderDevices(devices, targetAddress) {
      if (!devices.length) {
        devicesRoot.className = "devices empty";
        devicesRoot.textContent = "No AdoRime-compatible devices detected yet.";
        return;
      }
      devicesRoot.className = "devices";
      devicesRoot.innerHTML = devices.map((device) => {
        const selected = device.address === targetAddress ? "selected" : "";
        const state = device.present ? "in range" : "left";
        return `
          <div class="device ${selected}">
            <strong>${escapeHtml(device.name || "Unnamed AdoRime")}</strong>
            <small class="code">${escapeHtml(device.address)}</small>
            <small>RSSI ${device.rssi ?? "?"} dBm · ${state}</small>
          </div>
        `;
      }).join("");
    }

    function renderTargetSelect(devices, targetAddress) {
      const previous = targetSelect.value;
      targetSelect.innerHTML = devices.map((device) =>
        `<option value="${escapeHtml(device.address)}">${escapeHtml(device.name || device.address)} (${device.present ? "in range" : "left"})</option>`
      ).join("");
      if (targetAddress && devices.find((item) => item.address === targetAddress)) {
        targetSelect.value = targetAddress;
      } else if (previous && devices.find((item) => item.address === previous)) {
        targetSelect.value = previous;
      }
    }

    function renderControlState(control) {
      const targetName = control.target_name || "No target selected";
      const targetPresent = control.target_present ? "in range" : "not present";
      targetState.textContent = `${targetName} · ${targetPresent}`;
      targetState.className = `pill ${control.target_present ? "ok" : "warn"}`;
      modeState.textContent = `${control.mode} ${control.ai_enabled ? "(AI on)" : "(AI off)"}`;
      modeState.className = `pill ${control.ai_enabled ? "ok" : "warn"}`;

      aiEnabled.checked = Boolean(control.ai_enabled);
      aiAggressiveness.value = Number(control.ai_aggressiveness ?? 0.65);
      aiAggrValue.textContent = Number(control.ai_aggressiveness ?? 0.65).toFixed(2);
      aiMin.value = Number(control.min_thrust ?? 20);
      aiMax.value = Number(control.max_thrust ?? 90);
    }

    function renderLastCommand(command) {
      const root = document.getElementById("last-command");
      if (!command) {
        root.className = "empty";
        root.textContent = "No thrust command has been sent yet.";
        return;
      }
      root.className = "command";
      root.innerHTML = `
        <div><strong>${escapeHtml(command.source)}</strong> sent to ${escapeHtml(command.name || command.address)}</div>
        <div>thrust <strong>${command.thrust}%</strong> · pattern <strong>${escapeHtml(command.pattern)}</strong></div>
        <div class="code">${escapeHtml(command.reason)}</div>
        <div class="code">${escapeHtml(command.at)}</div>
      `;
    }

    function renderHistory(history) {
      const root = document.getElementById("command-history");
      if (!history.length) {
        root.innerHTML = "<div class='empty'>No command history yet.</div>";
        return;
      }
      root.innerHTML = history.slice(-12).reverse().map((entry) => `
        <div class="command">
          <strong>${escapeHtml(entry.source)}</strong> · ${escapeHtml(entry.name || entry.address)} · ${entry.thrust}% (${escapeHtml(entry.pattern)})
          <div class="code">${escapeHtml(entry.at)} · ${escapeHtml(entry.reason)}</div>
        </div>
      `).join("");
    }

    function renderEvents(events) {
      const root = document.getElementById("events");
      root.innerHTML = events.slice(-35).reverse().map((event) =>
        `<div>${escapeHtml(event.at)} · ${escapeHtml(event.type)} · ${escapeHtml(event.name || event.address)} · ${escapeHtml(event.message)}</div>`
      ).join("");
    }

    function escapeHtml(value) {
      return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
    }
  </script>
</body>
</html>
"""
