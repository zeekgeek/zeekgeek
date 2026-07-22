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

    @app.post("/api/control/connect")
    async def connect_target() -> JSONResponse:
        try:
            event = await state.connect_target()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse({"event": event, "control": await state.control_snapshot()})

    @app.post("/api/control/disconnect")
    async def disconnect_target() -> JSONResponse:
        try:
            event = await state.disconnect_target()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse({"event": event, "control": await state.control_snapshot()})

    @app.post("/api/control/manual")
    async def manual_command(request: ManualCommandRequest) -> JSONResponse:
        try:
            event = await state.send_manual_thrust(request.thrust, pattern=request.pattern)
        except Exception as exc:
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
        except Exception as exc:
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
    .device.candidate { border-color: #3b82f6; }
    .device.probable { border-color: #f59e0b; }
    .device strong { display: block; }
    .device small { color: var(--muted); display: block; margin-top: 3px; }
    .device .actions { display: flex; gap: 8px; margin-top: 8px; flex-wrap: wrap; }
    .device button { padding: 6px 10px; font-size: 12px; }
    .banner {
      margin: 12px 16px 0;
      padding: 12px 14px;
      border-radius: 12px;
      border: 1px solid #7c2d12;
      background: rgba(249, 115, 22, 0.12);
      color: #fed7aa;
      display: none;
    }
    .banner.visible { display: block; }
    .banner strong { display: block; margin-bottom: 4px; }
    .tier { display: inline-block; border-radius: 999px; padding: 2px 8px; font-size: 11px; font-weight: 700; margin-left: 6px; }
    .tier-known { background: rgba(34,197,94,.18); color: var(--green); }
    .tier-probable { background: rgba(245,158,11,.18); color: #fbbf24; }
    .tier-none { background: rgba(148,163,184,.15); color: var(--muted); }
    .filters { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 10px; color: var(--muted); font-size: 13px; }
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
    .method { border: 1px solid #2d3b57; border-radius: 10px; padding: 8px; margin-top: 8px; background: #0d1629; }
    .method strong { display: block; }
    .confidence-low { color: #94a3b8; }
    .confidence-medium { color: #f59e0b; }
    .confidence-high { color: #f97316; }
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
        <span id="scan-mode" class="pill warn">scan: starting</span>
        <span id="counts">Waiting for Bluetooth scan...</span>
        <span id="updated"></span>
      </div>
    </div>
    <button id="notify">Enable browser notifications</button>
  </header>

  <div id="scan-help" class="banner">
    <strong>Bluetooth scan is not running</strong>
    <span id="scan-help-detail"></span>
  </div>

  <main class="shell">
    <section class="panel">
      <h2>Nearby Bluetooth devices</h2>
      <div class="filters">
        <label><input id="filter-candidates" type="checkbox" checked> highlight toys first</label>
        <label><input id="filter-toys-only" type="checkbox"> toys only</label>
        <span id="nearby-summary" class="code"></span>
      </div>
      <p class="code" style="margin:0 0 8px 0;">
        AdoRime toys advertise short codes (BGSF, QD48, SN80…), not “Adorime”. Tap <em>Select &amp; connect</em> on a likely match.
      </p>
      <div id="devices" class="devices empty">Waiting for nearby Bluetooth advertisements…</div>
    </section>

    <section class="stack">
      <section class="panel">
        <h2>Control panel</h2>
        <div class="row">
          <label for="target">Target device</label>
          <select id="target"></select>
          <button id="set-target" class="secondary">Set target</button>
          <button id="clear-target" class="secondary">Clear</button>
          <button id="connect-target">Connect GATT</button>
          <button id="disconnect-target" class="secondary">Disconnect</button>
        </div>
        <div class="row">
          <span id="target-state" class="pill warn">No target selected</span>
          <span id="mode-state" class="pill warn">manual</span>
          <span id="gatt-state" class="pill warn">GATT: disconnected</span>
        </div>
        <p class="code" style="margin-top:8px;">
          Matches AdoRime iOS flow: scan BLE ads → select toy → GATT connect (no OS pairing PIN) → write Galaku encrypted thrust frames.
          Toys usually advertise short codes (BGSF, QD48, SN80…), not the word “Adorime”.
        </p>
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
        <h2>Likely hiding methods</h2>
        <div id="hiding-report" class="empty">Waiting for enough observations to assess hiding behavior.</div>
        <h3 style="margin-top:14px;">Target-level indicators</h3>
        <div id="target-hiding-methods" class="empty">Select a target device to inspect method indicators.</div>
      </section>

      <section class="panel">
        <h2>Event stream</h2>
        <div id="events" class="events"></div>
      </section>
    </section>
  </main>

  <script>
    let snapshot = null;
    let aiControlsDirty = false;
    const notifiedEvents = new Set();

    const notifyBtn = document.getElementById("notify");
    const devicesRoot = document.getElementById("devices");
    const targetSelect = document.getElementById("target");
    const targetState = document.getElementById("target-state");
    const modeState = document.getElementById("mode-state");
    const gattState = document.getElementById("gatt-state");
    const scanMode = document.getElementById("scan-mode");
    const manualThrust = document.getElementById("manual-thrust");
    const manualThrustValue = document.getElementById("manual-thrust-value");
    const manualPattern = document.getElementById("manual-pattern");
    const aiEnabled = document.getElementById("ai-enabled");
    const aiAggressiveness = document.getElementById("ai-aggressiveness");
    const aiAggrValue = document.getElementById("ai-aggr-value");
    const aiMin = document.getElementById("ai-min");
    const aiMax = document.getElementById("ai-max");
    const aiControlInputIds = new Set(["ai-enabled", "ai-aggressiveness", "ai-min", "ai-max"]);

    const scanHelp = document.getElementById("scan-help");
    const scanHelpDetail = document.getElementById("scan-help-detail");
    const filterCandidates = document.getElementById("filter-candidates");
    const filterToysOnly = document.getElementById("filter-toys-only");
    const nearbySummary = document.getElementById("nearby-summary");

    filterCandidates.onchange = () => render();
    filterToysOnly.onchange = () => render();

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
      aiControlsDirty = true;
      aiAggrValue.textContent = Number(aiAggressiveness.value).toFixed(2);
    };
    aiEnabled.onchange = () => { aiControlsDirty = true; };
    aiMin.oninput = () => { aiControlsDirty = true; };
    aiMax.oninput = () => { aiControlsDirty = true; };

    document.getElementById("set-target").onclick = async () => {
      const address = targetSelect.value || null;
      await postJson("/api/control/target", { address });
    };

    document.getElementById("clear-target").onclick = async () => {
      await postJson("/api/control/target", { address: null });
    };

    document.getElementById("connect-target").onclick = async () => {
      await postJson("/api/control/connect", {});
    };

    document.getElementById("disconnect-target").onclick = async () => {
      await postJson("/api/control/disconnect", {});
    };

    document.getElementById("send-manual").onclick = async () => {
      await postJson("/api/control/manual", {
        thrust: Number(manualThrust.value),
        pattern: manualPattern.value,
      });
    };

    document.getElementById("save-ai").onclick = async () => {
      const payload = await postJson("/api/control/ai", {
        enabled: aiEnabled.checked,
        aggressiveness: Number(aiAggressiveness.value),
        min_thrust: Number(aiMin.value),
        max_thrust: Number(aiMax.value),
      });
      if (payload) {
        aiControlsDirty = false;
      }
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
        return null;
      }
      return payload;
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
      const nearby = control.nearby_devices || snapshot.devices || [];
      const supported = control.supported_devices || nearby.filter((d) => d.controllable || d.adorime_candidate);
      const mode = snapshot.scan_mode || "unknown";
      scanMode.textContent = mode === "demo" ? "scan: demo (simulated)" : `scan: ${mode}`;
      scanMode.className = `pill ${mode === "live" || mode === "demo" ? "ok" : "warn"}`;
      const candidates = snapshot.candidate_count ?? supported.length;
      document.getElementById("counts").textContent =
        `${snapshot.present_count} in range · ${candidates} likely toys · ${snapshot.device_count} total`;
      document.getElementById("updated").textContent = `Updated ${snapshot.generated_at}`;
      renderScanHelp(mode, snapshot.scanner_error);
      renderDevices(nearby, control.target_address);
      renderTargetSelect(supported, control.target_address);
      renderControlState(control);
      renderLastCommand(control.last_command);
      renderHistory(control.history || []);
      renderHidingAssessment(control.hiding_assessment || null, supported, control.target_address || null);
      renderEvents(snapshot.events || []);
    }

    function renderScanHelp(mode, error) {
      if (mode === "demo") {
        scanHelp.className = "banner visible";
        scanHelp.querySelector("strong").textContent = "Demo mode (not live Bluetooth)";
        scanHelpDetail.textContent =
          "Simulated devices only. Restart without --demo for live scan.";
        return;
      }
      const bt = snapshot.bluetooth || {};
      const platform = snapshot.host_platform || bt.platform || "";
      if (mode !== "live-error") {
        scanHelp.className = "banner";
        return;
      }
      scanHelp.className = "banner visible";
      const blocked = bt.capable === false;
      const title = blocked
        ? "This server cannot scan Bluetooth"
        : "Bluetooth scan is not running";
      scanHelp.querySelector("strong").textContent = title;
      if (blocked && bt.fix) {
        scanHelpDetail.textContent = `${bt.reason || error || ""} ${bt.fix}`;
        return;
      }
      const platformHint = platform === "Darwin"
        ? "On macOS: System Settings → Privacy & Security → Bluetooth → allow Terminal or your IDE."
        : "On Linux with an adapter: sudo systemctl start bluetooth and ensure rfkill is unblocked.";
      scanHelpDetail.textContent = error
        ? `${error} ${platformHint} Keep the toy powered on (flashing light) nearby.`
        : `${platformHint} Keep the toy powered on nearby. The scanner retries automatically.`;
    }

    function renderDevices(devices, targetAddress) {
      const toysOnly = filterToysOnly.checked;
      const highlightFirst = filterCandidates.checked;
      let list = devices.slice();
      if (toysOnly) {
        list = list.filter((d) => d.controllable || d.adorime_candidate || d.match_tier === "known" || d.match_tier === "probable");
      }
      if (highlightFirst) {
        list = list.slice().sort((a, b) => {
          const rank = { known: 3, probable: 2, none: 0 };
          const ta = rank[a.match_tier] || 0;
          const tb = rank[b.match_tier] || 0;
          if (tb !== ta) return tb - ta;
          return (b.rssi ?? -999) - (a.rssi ?? -999);
        });
      }
      const likely = devices.filter((d) => d.controllable || d.adorime_candidate).length;
      nearbySummary.textContent = `${list.length} shown · ${likely} likely toys nearby`;

      if (!list.length) {
        devicesRoot.className = "devices empty";
        devicesRoot.textContent = toysOnly
          ? "No likely toys yet. Uncheck “toys only” to see every nearby BLE advertisement, or power the toy on."
          : "No nearby Bluetooth advertisements yet. Power the toy on and keep it close to the adapter.";
        return;
      }
      devicesRoot.className = "devices";
      devicesRoot.innerHTML = list.map((device) => {
        const selected = device.address === targetAddress ? "selected" : "";
        const tier = device.match_tier || "none";
        const tierClass = tier === "known" ? "candidate" : (tier === "probable" ? "probable" : "");
        const state = device.present ? "in range" : "left";
        const connected = device.gatt && device.gatt.connected ? "GATT connected" : "GATT idle";
        const title = escapeHtml(device.display_name || device.name || "Unnamed BLE device");
        const code = escapeHtml(device.name || "no-local-name");
        const controllable = device.controllable || device.adorime_candidate;
        const action = controllable
          ? `<button data-action="select-connect" data-address="${escapeHtml(device.address)}">Select &amp; connect</button>`
          : `<button class="secondary" data-action="select-only" data-address="${escapeHtml(device.address)}" disabled title="Not a likely AdoRime/Galaku name">Not a toy match</button>`;
        return `
          <div class="device ${selected} ${tierClass}">
            <strong>${title}<span class="tier tier-${escapeHtml(tier)}">${escapeHtml(tier)}</span></strong>
            <small class="code">${escapeHtml(device.address)} · BLE name ${code} · ${escapeHtml(device.match_reason || "none")}</small>
            <small>RSSI ${device.rssi ?? "?"} dBm · ${state} · ${connected}</small>
            <small>protocol: ${escapeHtml(device.protocol || "—")}</small>
            <div class="actions">${action}</div>
          </div>
        `;
      }).join("");

      devicesRoot.querySelectorAll("button[data-action]").forEach((button) => {
        button.onclick = async () => {
          const address = button.getAttribute("data-address");
          const action = button.getAttribute("data-action");
          if (!address) return;
          button.disabled = true;
          try {
            const targetPayload = await postJson("/api/control/target", { address });
            if (!targetPayload) return;
            if (action === "select-connect") {
              await postJson("/api/control/connect", {});
            }
          } finally {
            button.disabled = false;
          }
        };
      });
    }

    function renderTargetSelect(devices, targetAddress) {
      const previous = targetSelect.value;
      targetSelect.innerHTML = devices.map((device) => {
        const label = device.display_name || device.name || device.address;
        const tier = device.match_tier ? ` [${device.match_tier}]` : "";
        return `<option value="${escapeHtml(device.address)}">${escapeHtml(label)}${escapeHtml(tier)} (${device.present ? "in range" : "left"})</option>`;
      }).join("");
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
      const gatt = control.gatt || {};
      gattState.textContent = gatt.connected
        ? `GATT: connected (${gatt.protocol || "unknown"})`
        : "GATT: disconnected";
      gattState.className = `pill ${gatt.connected ? "ok" : "warn"}`;

      if (!aiControlsDirty && !isAiControlFocused()) {
        aiEnabled.checked = Boolean(control.ai_enabled);
        aiAggressiveness.value = Number(control.ai_aggressiveness ?? 0.65);
        aiAggrValue.textContent = Number(control.ai_aggressiveness ?? 0.65).toFixed(2);
        aiMin.value = Number(control.min_thrust ?? 20);
        aiMax.value = Number(control.max_thrust ?? 90);
      }
    }

    function isAiControlFocused() {
      const active = document.activeElement;
      return !!active && aiControlInputIds.has(active.id);
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

    function renderHidingAssessment(assessment, supportedDevices, targetAddress) {
      const root = document.getElementById("hiding-report");
      if (!assessment || !supportedDevices.length) {
        root.className = "empty";
        root.textContent = "Waiting for enough observations to assess hiding behavior.";
      } else {
        root.className = "";
        const methods = (assessment.primary_methods || []).length
          ? assessment.primary_methods.map((method) => `<li>${escapeHtml(method)}</li>`).join("")
          : "<li>No strong method pattern detected yet.</li>";
        root.innerHTML = `
          <div class="method">
            <strong class="confidence-${escapeHtml(assessment.confidence || "low")}">Fleet confidence: ${escapeHtml(assessment.confidence || "low")}</strong>
            <div class="code">evaluated devices: ${assessment.evaluated_devices ?? 0}</div>
            <ul>${methods}</ul>
            <div class="code">${escapeHtml(assessment.note || "")}</div>
          </div>
        `;
      }

      const targetRoot = document.getElementById("target-hiding-methods");
      const target = supportedDevices.find((item) => item.address === targetAddress);
      const targetMethods = target?.hiding_methods || [];
      if (!target || !targetMethods.length) {
        targetRoot.className = "empty";
        targetRoot.textContent = target ? "No strong hiding method indicators yet." : "Select a target device to inspect method indicators.";
        return;
      }
      targetRoot.className = "";
      targetRoot.innerHTML = targetMethods.map((method) => `
        <div class="method">
          <strong>${escapeHtml(method.method || "unknown-method")}</strong>
          <div class="confidence-${escapeHtml(method.confidence || "low")}">confidence: ${escapeHtml(method.confidence || "low")}</div>
          <div>${escapeHtml(method.summary || "")}</div>
          <div class="code">${escapeHtml(method.evidence || "")}</div>
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
