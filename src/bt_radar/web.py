"""FastAPI dashboard for the Bluetooth radar."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse

from .state import RadarState


def create_app(state: RadarState) -> FastAPI:
    app = FastAPI(title="Bluetooth Proximity Radar")

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return DASHBOARD_HTML

    @app.get("/api/devices")
    async def devices() -> dict:
        return await state.snapshot()

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
  <title>Bluetooth Proximity Radar</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #0b1020;
      --panel: #121a2e;
      --panel-2: #17213a;
      --text: #e8eefc;
      --muted: #94a3b8;
      --green: #22c55e;
      --yellow: #eab308;
      --red: #f97316;
      --blue: #38bdf8;
    }
    body { margin: 0; font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif; background: var(--bg); color: var(--text); }
    header { padding: 20px 28px; border-bottom: 1px solid #243047; display: flex; justify-content: space-between; gap: 16px; align-items: center; }
    h1 { font-size: 22px; margin: 0; }
    button { background: var(--blue); color: #06111f; border: 0; border-radius: 10px; padding: 10px 14px; font-weight: 700; cursor: pointer; }
    main { display: grid; grid-template-columns: minmax(340px, 440px) 1fr; gap: 18px; padding: 18px; }
    .panel { background: var(--panel); border: 1px solid #243047; border-radius: 16px; padding: 16px; box-shadow: 0 16px 40px rgba(0,0,0,.25); }
    .stats { display: flex; gap: 12px; color: var(--muted); font-size: 14px; }
    .device { border: 1px solid #26324b; border-radius: 14px; padding: 12px; margin: 10px 0; background: var(--panel-2); cursor: pointer; }
    .device.active { outline: 2px solid var(--blue); }
    .device-title { display: flex; justify-content: space-between; align-items: start; gap: 12px; }
    .name { font-weight: 800; }
    .addr { color: var(--muted); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
    .badge { border-radius: 999px; padding: 4px 8px; font-size: 12px; font-weight: 700; white-space: nowrap; }
    .present { background: rgba(34,197,94,.15); color: var(--green); }
    .gone { background: rgba(148,163,184,.15); color: var(--muted); }
    .severity-info { color: var(--blue); }
    .severity-low { color: var(--yellow); }
    .severity-medium, .severity-high { color: var(--red); }
    canvas { width: 100%; height: 320px; background: #08101f; border-radius: 14px; border: 1px solid #243047; }
    dl { display: grid; grid-template-columns: 160px 1fr; gap: 8px 12px; }
    dt { color: var(--muted); }
    dd { margin: 0; overflow-wrap: anywhere; }
    .finding { padding: 10px; border-radius: 12px; background: #0d1629; margin: 8px 0; }
    .events { max-height: 220px; overflow: auto; color: var(--muted); font-size: 13px; }
    .empty { color: var(--muted); text-align: center; padding: 40px 0; }
    @media (max-width: 900px) { main { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Bluetooth Proximity Radar</h1>
      <div class="stats"><span id="counts">Waiting for scan data...</span><span id="updated"></span></div>
    </div>
    <button id="notify">Enable browser notifications</button>
  </header>
  <main>
    <section class="panel">
      <h2>Detected clients</h2>
      <div id="devices" class="empty">No Bluetooth devices observed yet.</div>
    </section>
    <section class="panel">
      <h2>Movement graph</h2>
      <canvas id="graph" width="900" height="320"></canvas>
      <div id="details" class="empty">Select a device to see details.</div>
      <h3>Recent events</h3>
      <div id="events" class="events"></div>
    </section>
  </main>
  <script>
    let snapshot = null;
    let selectedAddress = null;
    let notifiedEvents = new Set();

    document.getElementById("notify").onclick = async () => {
      if (!("Notification" in window)) {
        alert("This browser does not support notifications.");
        return;
      }
      await Notification.requestPermission();
    };

    const source = new EventSource("/api/events");
    source.onmessage = (message) => {
      snapshot = JSON.parse(message.data);
      if (!selectedAddress && snapshot.devices.length) selectedAddress = snapshot.devices[0].address;
      render();
      notifyNewEvents(snapshot.events || []);
    };

    function notifyNewEvents(events) {
      if (!("Notification" in window) || Notification.permission !== "granted") return;
      for (const event of events.slice(-12)) {
        const key = `${event.at}:${event.type}:${event.address}`;
        if (notifiedEvents.has(key)) continue;
        notifiedEvents.add(key);
        if (event.type === "new" || event.type === "entered" || event.type === "left") {
          new Notification(`Bluetooth ${event.type}: ${event.name || event.address}`, { body: event.message });
        }
      }
    }

    function render() {
      if (!snapshot) return;
      document.getElementById("counts").textContent = `${snapshot.present_count} present / ${snapshot.device_count} total`;
      document.getElementById("updated").textContent = `Updated ${snapshot.generated_at}`;
      renderDevices();
      renderDetails();
      renderEvents();
    }

    function renderDevices() {
      const root = document.getElementById("devices");
      if (!snapshot.devices.length) {
        root.className = "empty";
        root.textContent = "No Bluetooth devices observed yet.";
        return;
      }
      root.className = "";
      root.innerHTML = snapshot.devices.map((device) => `
        <div class="device ${device.address === selectedAddress ? "active" : ""}" data-address="${escapeHtml(device.address)}">
          <div class="device-title">
            <div>
              <div class="name">${escapeHtml(device.name || "Unnamed Bluetooth device")}</div>
              <div class="addr">${escapeHtml(device.address)}</div>
            </div>
            <span class="badge ${device.present ? "present" : "gone"}">${device.present ? "in range" : "left"}</span>
          </div>
          <p>${device.rssi ?? "?"} dBm · ${escapeHtml(device.distance_label)} · ${escapeHtml(device.movement)}</p>
          <p>${escapeHtml(device.address_family)} · seen ${device.seen_count} times</p>
        </div>`).join("");
      root.querySelectorAll(".device").forEach((node) => {
        node.onclick = () => { selectedAddress = node.dataset.address; render(); };
      });
    }

    function renderDetails() {
      const device = snapshot.devices.find((item) => item.address === selectedAddress);
      drawGraph(device);
      const root = document.getElementById("details");
      if (!device) {
        root.className = "empty";
        root.textContent = "Select a device to see details.";
        return;
      }
      root.className = "";
      const findings = device.findings.length
        ? device.findings.map((finding) => `<div class="finding"><strong class="severity-${finding.severity}">${escapeHtml(finding.title)}</strong><br>${escapeHtml(finding.detail)}</div>`).join("")
        : "<p>No anomalies flagged from current observations.</p>";
      root.innerHTML = `
        <h3>${escapeHtml(device.name || "Unnamed Bluetooth device")}</h3>
        <dl>
          <dt>Address</dt><dd>${escapeHtml(device.address)}</dd>
          <dt>Address class</dt><dd>${escapeHtml(device.address_family)}</dd>
          <dt>Address type</dt><dd>${escapeHtml(device.address_type || "unknown")}</dd>
          <dt>Manufacturer</dt><dd>${escapeHtml(device.manufacturer_hex || "unknown")}</dd>
          <dt>RSSI</dt><dd>${device.rssi ?? "unknown"} dBm (${escapeHtml(device.distance_label)})</dd>
          <dt>Movement</dt><dd>${escapeHtml(device.movement)}</dd>
          <dt>First seen</dt><dd>${escapeHtml(device.first_seen)}</dd>
          <dt>Last seen</dt><dd>${escapeHtml(device.last_seen)} (${device.stale_seconds}s ago)</dd>
          <dt>Reappearances</dt><dd>${device.reappear_count}</dd>
          <dt>Services</dt><dd>${escapeHtml((device.service_uuids || []).join(", ") || "none advertised")}</dd>
        </dl>
        <h3>Findings</h3>
        ${findings}`;
    }

    function renderEvents() {
      const root = document.getElementById("events");
      const events = (snapshot.events || []).slice(-30).reverse();
      root.innerHTML = events.map((event) => `<div>${escapeHtml(event.at)} · ${escapeHtml(event.type)} · ${escapeHtml(event.name || event.address)} · ${escapeHtml(event.message)}</div>`).join("");
    }

    function drawGraph(device) {
      const canvas = document.getElementById("graph");
      const ctx = canvas.getContext("2d");
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.strokeStyle = "#243047";
      ctx.lineWidth = 1;
      for (let i = 0; i <= 5; i++) {
        const y = 20 + i * 54;
        ctx.beginPath(); ctx.moveTo(40, y); ctx.lineTo(canvas.width - 20, y); ctx.stroke();
      }
      ctx.fillStyle = "#94a3b8";
      ctx.font = "13px sans-serif";
      ctx.fillText("-30 dBm near", 44, 34);
      ctx.fillText("-100 dBm far", 44, canvas.height - 18);
      if (!device || !device.rssi_history.length) return;
      const values = device.rssi_history;
      const xStep = (canvas.width - 80) / Math.max(values.length - 1, 1);
      ctx.strokeStyle = "#38bdf8";
      ctx.lineWidth = 3;
      ctx.beginPath();
      values.forEach((rssi, index) => {
        const x = 40 + index * xStep;
        const y = mapRssi(rssi, canvas.height);
        if (index === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      ctx.stroke();
      ctx.fillStyle = "#e8eefc";
      ctx.fillText(`${device.name || device.address} RSSI history`, 44, canvas.height - 42);
    }

    function mapRssi(rssi, height) {
      const clamped = Math.max(-100, Math.min(-30, rssi));
      return 20 + ((-30 - clamped) / 70) * (height - 40);
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
