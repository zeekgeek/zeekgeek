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
    h2 { margin: 0 0 10px 0; font-size: 18px; }
    h3 { margin: 14px 0 8px 0; font-size: 15px; }
    button { background: var(--blue); color: #06111f; border: 0; border-radius: 10px; padding: 10px 14px; font-weight: 700; cursor: pointer; }
    .stats { display: flex; gap: 12px; color: var(--muted); font-size: 14px; flex-wrap: wrap; }
    main { display: grid; grid-template-columns: minmax(330px, 420px) 1fr; gap: 16px; padding: 16px; align-items: start; }
    .panel { background: var(--panel); border: 1px solid #243047; border-radius: 14px; padding: 14px; box-shadow: 0 16px 40px rgba(0,0,0,.25); }
    .stack { display: grid; gap: 16px; }
    .device-list { max-height: 76vh; overflow: auto; }
    .device { border: 1px solid #26324b; border-radius: 12px; padding: 10px; margin: 8px 0; background: var(--panel-2); cursor: pointer; }
    .device.active { outline: 2px solid var(--blue); }
    .device-title { display: flex; justify-content: space-between; align-items: start; gap: 10px; }
    .name { font-weight: 800; }
    .addr { color: var(--muted); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
    .badge { border-radius: 999px; padding: 4px 8px; font-size: 12px; font-weight: 700; white-space: nowrap; }
    .present { background: rgba(34,197,94,.15); color: var(--green); }
    .gone { background: rgba(148,163,184,.15); color: var(--muted); }
    .signal-row { display: flex; justify-content: space-between; gap: 8px; font-size: 13px; color: var(--muted); margin: 6px 0 4px 0; }
    .bar { width: 100%; height: 8px; border-radius: 6px; background: #091427; overflow: hidden; border: 1px solid #22324a; }
    .bar > div { height: 100%; background: linear-gradient(90deg, #1e3a8a, #38bdf8, #22c55e); }
    canvas { width: 100%; background: #08101f; border-radius: 12px; border: 1px solid #243047; display: block; }
    #radar-map { height: 340px; }
    #signal-graph { height: 250px; margin-top: 10px; }
    dl { display: grid; grid-template-columns: 170px 1fr; gap: 8px 12px; margin: 8px 0 0 0; }
    dt { color: var(--muted); }
    dd { margin: 0; overflow-wrap: anywhere; }
    .finding { padding: 9px; border-radius: 10px; background: #0d1629; margin: 8px 0; }
    .severity-info { color: var(--blue); }
    .severity-low { color: var(--yellow); }
    .severity-medium, .severity-high { color: var(--red); }
    .events { max-height: 220px; overflow: auto; color: var(--muted); font-size: 13px; }
    .empty { color: var(--muted); text-align: center; padding: 34px 0; }
    .tiny-note { font-size: 12px; color: var(--muted); margin-top: 6px; }
    @media (max-width: 980px) {
      main { grid-template-columns: 1fr; }
      .device-list { max-height: none; }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Bluetooth Proximity Radar</h1>
      <div class="stats">
        <span id="counts">Waiting for scan data...</span>
        <span id="updated"></span>
      </div>
    </div>
    <button id="notify">Enable browser notifications</button>
  </header>

  <main>
    <section class="panel">
      <h2>Detected devices</h2>
      <div id="devices" class="device-list empty">No Bluetooth devices observed yet.</div>
    </section>

    <section class="stack">
      <section class="panel">
        <h2>Proximity map (all devices)</h2>
        <canvas id="radar-map" width="960" height="340"></canvas>
        <p class="tiny-note">
          Ring guides: 1m, 3m, 8m, 20m. Distance is estimated from smoothed RSSI and can vary by environment.
        </p>
      </section>

      <section class="panel">
        <h2>Selected device signal history</h2>
        <canvas id="signal-graph" width="960" height="250"></canvas>
        <div id="details" class="empty">Select a device to see details.</div>
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
    const notifiedEvents = new Set();

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
      if (snapshot.devices.length && !snapshot.devices.find((d) => d.address === selectedAddress)) {
        selectedAddress = snapshot.devices[0].address;
      }
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
      document.getElementById("counts").textContent = `${snapshot.present_count} in range / ${snapshot.device_count} total`;
      document.getElementById("updated").textContent = `Updated ${snapshot.generated_at}`;
      renderDevices();
      drawRadarMap(snapshot.devices);
      renderDetails();
      renderEvents();
    }

    function renderDevices() {
      const root = document.getElementById("devices");
      if (!snapshot.devices.length) {
        root.className = "device-list empty";
        root.textContent = "No Bluetooth devices observed yet.";
        return;
      }
      root.className = "device-list";
      root.innerHTML = snapshot.devices.map((device) => {
        const signalPercent = toPercent(device.rssi_smoothed ?? device.rssi);
        const meters = formatDistance(device.estimated_distance_m);
        return `
          <div class="device ${device.address === selectedAddress ? "active" : ""}" data-address="${escapeHtml(device.address)}">
            <div class="device-title">
              <div>
                <div class="name">${escapeHtml(device.name || "Unnamed Bluetooth device")}</div>
                <div class="addr">${escapeHtml(device.address)}</div>
              </div>
              <span class="badge ${device.present ? "present" : "gone"}">${device.present ? "in range" : "left"}</span>
            </div>
            <div class="signal-row">
              <span>RSSI ${device.rssi ?? "?"} dBm (smoothed ${device.rssi_smoothed ?? "?"})</span>
              <span>${meters}</span>
            </div>
            <div class="bar"><div style="width:${signalPercent}%"></div></div>
            <div class="signal-row">
              <span>${escapeHtml(device.distance_label)} · ${escapeHtml(device.movement)}</span>
              <span>seen ${device.seen_count}x</span>
            </div>
          </div>`;
      }).join("");
      root.querySelectorAll(".device").forEach((node) => {
        node.onclick = () => {
          selectedAddress = node.dataset.address;
          render();
        };
      });
    }

    function drawRadarMap(devices) {
      const canvas = document.getElementById("radar-map");
      const ctx = canvas.getContext("2d");
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      const centerX = canvas.width / 2;
      const centerY = canvas.height / 2;
      const maxRadius = Math.min(canvas.width, canvas.height) * 0.43;
      const ringDistances = [1, 3, 8, 20];

      ctx.strokeStyle = "#243047";
      ctx.lineWidth = 1;
      for (const dist of ringDistances) {
        const ring = mapDistanceToRadius(dist, maxRadius);
        ctx.beginPath();
        ctx.arc(centerX, centerY, ring, 0, Math.PI * 2);
        ctx.stroke();
        ctx.fillStyle = "#94a3b8";
        ctx.font = "12px sans-serif";
        ctx.fillText(`${dist}m`, centerX + ring + 6, centerY - 4);
      }

      ctx.beginPath();
      ctx.arc(centerX, centerY, 6, 0, Math.PI * 2);
      ctx.fillStyle = "#e8eefc";
      ctx.fill();
      ctx.fillStyle = "#94a3b8";
      ctx.font = "12px sans-serif";
      ctx.fillText("sensor", centerX + 10, centerY + 20);

      if (!devices.length) {
        ctx.fillStyle = "#94a3b8";
        ctx.font = "15px sans-serif";
        ctx.fillText("No devices to plot yet", centerX - 70, centerY);
        return;
      }

      const plotted = devices.filter((device) => device.present).concat(devices.filter((device) => !device.present));
      for (const device of plotted) {
        const estimatedDistance = typeof device.estimated_distance_m === "number"
          ? device.estimated_distance_m
          : estimateDistanceFromRssi(device.rssi_smoothed ?? device.rssi);
        const angle = hashToAngle(device.address);
        const radius = mapDistanceToRadius(estimatedDistance, maxRadius);
        const x = centerX + Math.cos(angle) * radius;
        const y = centerY + Math.sin(angle) * radius;
        const color = device.address === selectedAddress ? "#38bdf8" : (device.present ? "#22c55e" : "#64748b");
        const alpha = device.present ? 0.85 : 0.35;
        const size = 4 + Math.round((toPercent(device.rssi_smoothed ?? device.rssi) / 100) * 6);

        ctx.strokeStyle = `rgba(56,189,248,${alpha * 0.35})`;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(centerX, centerY);
        ctx.lineTo(x, y);
        ctx.stroke();

        ctx.beginPath();
        ctx.arc(x, y, size, 0, Math.PI * 2);
        ctx.fillStyle = hexToRgba(color, alpha);
        ctx.fill();

        ctx.fillStyle = "#e8eefc";
        ctx.font = "12px sans-serif";
        ctx.fillText(shortLabel(device), x + size + 4, y - 5);
      }
    }

    function renderDetails() {
      const root = document.getElementById("details");
      const device = snapshot.devices.find((item) => item.address === selectedAddress);
      drawSignalGraph(device);
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
          <dt>Raw RSSI</dt><dd>${device.rssi ?? "unknown"} dBm</dd>
          <dt>Smoothed RSSI</dt><dd>${device.rssi_smoothed ?? "unknown"} dBm</dd>
          <dt>Estimated distance</dt><dd>${formatDistance(device.estimated_distance_m)} (${escapeHtml(device.distance_label)})</dd>
          <dt>Movement</dt><dd>${escapeHtml(device.movement)}</dd>
          <dt>First seen</dt><dd>${escapeHtml(device.first_seen)}</dd>
          <dt>Last seen</dt><dd>${escapeHtml(device.last_seen)} (${device.stale_seconds}s ago)</dd>
          <dt>Reappearances</dt><dd>${device.reappear_count}</dd>
          <dt>Services</dt><dd>${escapeHtml((device.service_uuids || []).join(", ") || "none advertised")}</dd>
        </dl>
        <h3>Findings</h3>
        ${findings}`;
    }

    function drawSignalGraph(device) {
      const canvas = document.getElementById("signal-graph");
      const ctx = canvas.getContext("2d");
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      ctx.strokeStyle = "#243047";
      ctx.lineWidth = 1;
      for (let i = 0; i <= 6; i++) {
        const y = 20 + i * ((canvas.height - 40) / 6);
        ctx.beginPath();
        ctx.moveTo(40, y);
        ctx.lineTo(canvas.width - 16, y);
        ctx.stroke();
      }
      ctx.fillStyle = "#94a3b8";
      ctx.font = "12px sans-serif";
      ctx.fillText("-30 dBm (near)", 44, 34);
      ctx.fillText("-100 dBm (far)", 44, canvas.height - 10);

      if (!device || !device.rssi_history || !device.rssi_history.length) {
        ctx.fillStyle = "#94a3b8";
        ctx.fillText("Select a device to plot history", 44, canvas.height / 2);
        return;
      }

      const raw = device.rssi_history;
      const smooth = smoothSeries(raw);
      drawLine(ctx, raw, "#64748b", 2, canvas);
      drawLine(ctx, smooth, "#38bdf8", 3, canvas);

      ctx.fillStyle = "#94a3b8";
      ctx.fillText("Gray: raw RSSI  |  Cyan: smoothed RSSI", 44, canvas.height - 26);
    }

    function drawLine(ctx, values, color, width, canvas) {
      const xStep = (canvas.width - 64) / Math.max(values.length - 1, 1);
      ctx.strokeStyle = color;
      ctx.lineWidth = width;
      ctx.beginPath();
      values.forEach((rssi, index) => {
        const x = 40 + index * xStep;
        const y = mapRssi(rssi, canvas.height);
        if (index === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.stroke();
    }

    function renderEvents() {
      const root = document.getElementById("events");
      const events = (snapshot.events || []).slice(-30).reverse();
      root.innerHTML = events.map((event) => `<div>${escapeHtml(event.at)} · ${escapeHtml(event.type)} · ${escapeHtml(event.name || event.address)} · ${escapeHtml(event.message)}</div>`).join("");
    }

    function smoothSeries(values, window = 6) {
      return values.map((_, end) => {
        const start = Math.max(0, end - window + 1);
        const chunk = values.slice(start, end + 1);
        let weighted = 0;
        let sum = 0;
        chunk.forEach((value, index) => {
          const weight = index + 1;
          weighted += value * weight;
          sum += weight;
        });
        return Math.round(weighted / sum);
      });
    }

    function toPercent(rssi) {
      if (typeof rssi !== "number") return 0;
      const clamped = Math.max(-100, Math.min(-35, rssi));
      return Math.round(((clamped + 100) / 65) * 100);
    }

    function mapRssi(rssi, height) {
      const clamped = Math.max(-100, Math.min(-30, rssi));
      return 20 + ((-30 - clamped) / 70) * (height - 40);
    }

    function estimateDistanceFromRssi(rssi) {
      if (typeof rssi !== "number") return 20;
      const txPower = -59;
      const pathLossExponent = 2.2;
      const distance = Math.pow(10, (txPower - rssi) / (10 * pathLossExponent));
      return Math.max(0.2, Math.min(distance, 20));
    }

    function mapDistanceToRadius(distanceMeters, maxRadius) {
      const distance = Math.max(0.2, Math.min(distanceMeters || 20, 20));
      const normalized = Math.log10(distance + 1) / Math.log10(21);
      return 22 + normalized * (maxRadius - 22);
    }

    function hashToAngle(text) {
      let hash = 0;
      for (let i = 0; i < text.length; i++) {
        hash = ((hash << 5) - hash) + text.charCodeAt(i);
        hash |= 0;
      }
      const positive = hash >>> 0;
      return (positive % 360) * (Math.PI / 180);
    }

    function shortLabel(device) {
      const name = (device.name || "").trim();
      if (name) return name.length > 20 ? `${name.slice(0, 19)}…` : name;
      return device.address.slice(-8);
    }

    function formatDistance(distanceMeters) {
      if (typeof distanceMeters !== "number") return "distance unknown";
      if (distanceMeters < 1) return `${Math.round(distanceMeters * 100)} cm est.`;
      return `${distanceMeters.toFixed(2)} m est.`;
    }

    function hexToRgba(hex, alpha) {
      const clean = hex.replace("#", "");
      const bigint = parseInt(clean, 16);
      const r = (bigint >> 16) & 255;
      const g = (bigint >> 8) & 255;
      const b = bigint & 255;
      return `rgba(${r},${g},${b},${alpha})`;
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
