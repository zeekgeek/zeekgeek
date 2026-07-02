"""FastAPI dashboard for the WiFi motion radar."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from .state import RadarState


class AlarmRangeRequest(BaseModel):
    range_m: float = Field(gt=0, le=120)


def create_app(state: RadarState) -> FastAPI:
    app = FastAPI(title="WiFi Motion Radar")

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return DASHBOARD_HTML

    @app.get("/api/devices")
    async def devices() -> dict:
        return await state.snapshot()

    @app.post("/api/alarm")
    async def set_alarm(request: AlarmRangeRequest) -> JSONResponse:
        event = await state.set_alarm_range(request.range_m)
        return JSONResponse({"alarm_range_m": state.alarm_range_m, "event": event})

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
  <title>WiFi Motion Radar</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #050b16;
      --panel: #0e1728;
      --panel-2: #142138;
      --text: #e8eefc;
      --muted: #94a3b8;
      --green: #22c55e;
      --amber: #f59e0b;
      --red: #ef4444;
      --blue: #38bdf8;
    }
    body { margin: 0; font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif; background: var(--bg); color: var(--text); }
    header { padding: 18px 26px; border-bottom: 1px solid #22304a; display: flex; justify-content: space-between; gap: 16px; align-items: center; flex-wrap: wrap; }
    h1 { font-size: 21px; margin: 0; }
    h2 { margin: 0 0 10px 0; font-size: 17px; }
    h3 { margin: 14px 0 8px 0; font-size: 15px; }
    button { background: var(--blue); color: #06111f; border: 0; border-radius: 10px; padding: 9px 13px; font-weight: 700; cursor: pointer; }
    .stats { display: flex; gap: 14px; color: var(--muted); font-size: 14px; flex-wrap: wrap; margin-top: 6px; }
    .stats b { color: var(--text); }
    .controls { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
    .controls label { font-size: 13px; color: var(--muted); }
    input[type=range] { accent-color: var(--blue); vertical-align: middle; }
    main { display: grid; grid-template-columns: minmax(320px, 400px) 1fr; gap: 16px; padding: 16px; align-items: start; }
    .panel { background: var(--panel); border: 1px solid #22304a; border-radius: 14px; padding: 14px; box-shadow: 0 16px 40px rgba(0,0,0,.3); }
    .stack { display: grid; gap: 16px; }
    .device-list { max-height: 78vh; overflow: auto; }
    .device { border: 1px solid #26324b; border-radius: 12px; padding: 10px; margin: 8px 0; background: var(--panel-2); cursor: pointer; }
    .device.active { outline: 2px solid var(--blue); }
    .device.alarm { border-color: var(--red); box-shadow: 0 0 0 1px var(--red) inset; }
    .device-title { display: flex; justify-content: space-between; align-items: start; gap: 10px; }
    .name { font-weight: 800; }
    .addr { color: var(--muted); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
    .badge { border-radius: 999px; padding: 3px 8px; font-size: 12px; font-weight: 700; white-space: nowrap; }
    .badge.stationary { background: rgba(34,197,94,.15); color: var(--green); }
    .badge.moving { background: rgba(245,158,11,.16); color: var(--amber); }
    .badge.collecting { background: rgba(148,163,184,.15); color: var(--muted); }
    .badge.gone { background: rgba(148,163,184,.12); color: var(--muted); }
    .signal-row { display: flex; justify-content: space-between; gap: 8px; font-size: 13px; color: var(--muted); margin: 6px 0 4px 0; }
    .bar { width: 100%; height: 8px; border-radius: 6px; background: #091427; overflow: hidden; border: 1px solid #22324a; }
    .bar > div { height: 100%; background: linear-gradient(90deg, #1e3a8a, #38bdf8, #22c55e); }
    canvas { width: 100%; background: #060e1c; border-radius: 12px; border: 1px solid #22304a; display: block; }
    #radar-map { height: 420px; }
    #signal-graph { height: 230px; margin-top: 10px; }
    dl { display: grid; grid-template-columns: 160px 1fr; gap: 8px 12px; margin: 8px 0 0 0; }
    dt { color: var(--muted); }
    dd { margin: 0; overflow-wrap: anywhere; }
    .events { max-height: 220px; overflow: auto; color: var(--muted); font-size: 13px; }
    .events .alarm-line { color: #fecaca; font-weight: 600; }
    .legend { display: flex; gap: 16px; flex-wrap: wrap; font-size: 12px; color: var(--muted); margin-top: 8px; }
    .legend span::before { content: ""; display: inline-block; width: 10px; height: 10px; margin-right: 6px; vertical-align: middle; }
    .legend .s-dot::before { background: var(--green); border-radius: 2px; }
    .legend .m-dot::before { background: var(--amber); border-radius: 50%; }
    .legend .a-dot::before { background: var(--red); border-radius: 50%; }
    .empty { color: var(--muted); text-align: center; padding: 34px 0; }
    .tiny-note { font-size: 12px; color: var(--muted); margin-top: 6px; }
    #alarm-banner { display: none; background: rgba(239,68,68,.16); border: 1px solid var(--red); color: #fecaca; padding: 10px 14px; border-radius: 10px; margin: 0 16px; font-weight: 700; }
    @media (max-width: 980px) { main { grid-template-columns: 1fr; } .device-list { max-height: none; } }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>WiFi Motion Radar</h1>
      <div class="stats">
        <span id="counts">Waiting for scan data...</span>
        <span id="updated"></span>
      </div>
    </div>
    <div class="controls">
      <label>Alarm range: <b id="range-label">5.0</b> m</label>
      <input id="range-slider" type="range" min="1" max="40" step="0.5" value="5">
      <button id="notify">Enable notifications</button>
      <button id="sound-toggle">Sound: off</button>
    </div>
  </header>

  <div id="alarm-banner"></div>

  <main>
    <section class="panel">
      <h2>Detected devices</h2>
      <div id="devices" class="device-list empty">No WiFi devices observed yet.</div>
    </section>

    <section class="stack">
      <section class="panel">
        <h2>Proximity map</h2>
        <canvas id="radar-map" width="960" height="420"></canvas>
        <div class="legend">
          <span class="s-dot">Stationary</span>
          <span class="m-dot">Moving</span>
          <span class="a-dot">In alarm zone</span>
        </div>
        <p class="tiny-note">
          Red ring = alarm range. Distance is estimated from smoothed RSSI and varies with walls, reflections, and antenna orientation.
        </p>
      </section>

      <section class="panel">
        <h2>Selected device signal history</h2>
        <canvas id="signal-graph" width="960" height="230"></canvas>
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
    let selectedBssid = null;
    let soundOn = false;
    let audioCtx = null;
    const notifiedEvents = new Set();

    const rangeSlider = document.getElementById("range-slider");
    const rangeLabel = document.getElementById("range-label");

    document.getElementById("notify").onclick = async () => {
      if (!("Notification" in window)) { alert("This browser does not support notifications."); return; }
      await Notification.requestPermission();
    };

    document.getElementById("sound-toggle").onclick = (event) => {
      soundOn = !soundOn;
      event.target.textContent = `Sound: ${soundOn ? "on" : "off"}`;
      if (soundOn && !audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    };

    rangeSlider.oninput = () => { rangeLabel.textContent = Number(rangeSlider.value).toFixed(1); };
    rangeSlider.onchange = async () => {
      await fetch("/api/alarm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ range_m: Number(rangeSlider.value) }),
      });
    };

    const source = new EventSource("/api/events");
    source.onmessage = (message) => {
      snapshot = JSON.parse(message.data);
      if (document.activeElement !== rangeSlider) {
        rangeSlider.value = snapshot.alarm_range_m;
        rangeLabel.textContent = Number(snapshot.alarm_range_m).toFixed(1);
      }
      if (snapshot.devices.length && !snapshot.devices.find((d) => d.bssid === selectedBssid)) {
        selectedBssid = snapshot.devices[0].bssid;
      }
      render();
      handleEvents(snapshot.events || []);
    };

    function handleEvents(events) {
      const banner = document.getElementById("alarm-banner");
      let latestAlarm = null;
      for (const event of events.slice(-16)) {
        const key = `${event.at}:${event.type}:${event.bssid}`;
        if (notifiedEvents.has(key)) continue;
        notifiedEvents.add(key);
        if (event.type === "alarm") {
          latestAlarm = event;
          if ("Notification" in window && Notification.permission === "granted") {
            new Notification(`WiFi proximity alarm: ${event.ssid || event.bssid}`, { body: event.message });
          }
          beep();
        }
      }
      if (latestAlarm) {
        banner.style.display = "block";
        banner.textContent = `ALARM  ·  ${latestAlarm.ssid || latestAlarm.bssid}  ·  ${latestAlarm.message}`;
        clearTimeout(banner._timer);
        banner._timer = setTimeout(() => { banner.style.display = "none"; }, 6000);
      }
    }

    function beep() {
      if (!soundOn || !audioCtx) return;
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();
      osc.type = "square";
      osc.frequency.value = 880;
      gain.gain.value = 0.08;
      osc.connect(gain).connect(audioCtx.destination);
      osc.start();
      osc.stop(audioCtx.currentTime + 0.18);
    }

    function render() {
      if (!snapshot) return;
      document.getElementById("counts").innerHTML =
        `<b>${snapshot.present_count}</b> in range · <b>${snapshot.stationary_count}</b> stationary · ` +
        `<b>${snapshot.moving_count}</b> moving · <b>${snapshot.alarm_count}</b> in alarm zone`;
      document.getElementById("updated").textContent = `Updated ${snapshot.generated_at}`;
      renderDevices();
      drawRadarMap(snapshot.devices, snapshot.alarm_range_m);
      renderDetails();
      renderEvents();
    }

    function renderDevices() {
      const root = document.getElementById("devices");
      if (!snapshot.devices.length) {
        root.className = "device-list empty";
        root.textContent = "No WiFi devices observed yet.";
        return;
      }
      root.className = "device-list";
      root.innerHTML = snapshot.devices.map((device) => {
        const signalPercent = toPercent(device.rssi_smoothed ?? device.rssi);
        const badge = device.present ? device.motion : "gone";
        const badgeText = device.present ? `${device.motion}${device.direction && device.direction !== "steady" ? " · " + device.direction : ""}` : "left";
        return `
          <div class="device ${device.bssid === selectedBssid ? "active" : ""} ${device.in_alarm_zone ? "alarm" : ""}" data-bssid="${escapeHtml(device.bssid)}">
            <div class="device-title">
              <div>
                <div class="name">${escapeHtml(device.ssid || "(hidden / no SSID)")}</div>
                <div class="addr">${escapeHtml(device.bssid)}</div>
              </div>
              <span class="badge ${badge}">${escapeHtml(badgeText)}</span>
            </div>
            <div class="signal-row">
              <span>RSSI ${device.rssi ?? "?"} dBm</span>
              <span>${formatDistance(device.estimated_distance_m)}</span>
            </div>
            <div class="bar"><div style="width:${signalPercent}%"></div></div>
            <div class="signal-row">
              <span>${escapeHtml(device.distance_label)}${device.channel ? " · ch " + device.channel : ""}</span>
              <span>seen ${device.seen_count}x</span>
            </div>
          </div>`;
      }).join("");
      root.querySelectorAll(".device").forEach((node) => {
        node.onclick = () => { selectedBssid = node.dataset.bssid; render(); };
      });
    }

    function drawRadarMap(devices, alarmRange) {
      const canvas = document.getElementById("radar-map");
      const ctx = canvas.getContext("2d");
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      const centerX = canvas.width / 2;
      const centerY = canvas.height / 2;
      const maxRadius = Math.min(canvas.width, canvas.height) * 0.44;
      const ringDistances = [2, 5, 15, 40];

      ctx.strokeStyle = "#22304a";
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

      const alarmRadius = mapDistanceToRadius(alarmRange, maxRadius);
      ctx.beginPath();
      ctx.arc(centerX, centerY, alarmRadius, 0, Math.PI * 2);
      ctx.fillStyle = "rgba(239,68,68,0.10)";
      ctx.fill();
      ctx.strokeStyle = "rgba(239,68,68,0.9)";
      ctx.setLineDash([6, 4]);
      ctx.lineWidth = 2;
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = "#fca5a5";
      ctx.fillText(`alarm ${Number(alarmRange).toFixed(1)}m`, centerX - 34, centerY - alarmRadius - 8);

      ctx.beginPath();
      ctx.arc(centerX, centerY, 6, 0, Math.PI * 2);
      ctx.fillStyle = "#e8eefc";
      ctx.fill();
      ctx.fillStyle = "#94a3b8";
      ctx.fillText("sensor", centerX + 10, centerY + 20);

      const plotted = devices.filter((d) => d.present);
      for (const device of plotted) {
        const distance = typeof device.estimated_distance_m === "number" ? device.estimated_distance_m : 40;
        const angle = hashToAngle(device.bssid);
        const radius = mapDistanceToRadius(distance, maxRadius);
        const x = centerX + Math.cos(angle) * radius;
        const y = centerY + Math.sin(angle) * radius;
        const moving = device.motion === "moving";
        let color = moving ? "#f59e0b" : "#22c55e";
        if (device.in_alarm_zone) color = "#ef4444";
        if (device.bssid === selectedBssid) color = "#38bdf8";

        ctx.strokeStyle = hexToRgba(color, 0.3);
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(centerX, centerY);
        ctx.lineTo(x, y);
        ctx.stroke();

        ctx.fillStyle = color;
        if (moving) {
          drawDiamond(ctx, x, y, 7);
          drawDirectionArrow(ctx, centerX, centerY, x, y, device.direction, color);
        } else {
          ctx.fillRect(x - 6, y - 6, 12, 12);
        }
        if (device.in_alarm_zone) {
          ctx.strokeStyle = "#ef4444";
          ctx.lineWidth = 2;
          ctx.beginPath();
          ctx.arc(x, y, 13, 0, Math.PI * 2);
          ctx.stroke();
        }
        ctx.fillStyle = "#e8eefc";
        ctx.font = "12px sans-serif";
        ctx.fillText(shortLabel(device), x + 10, y - 8);
      }
    }

    function drawDiamond(ctx, x, y, size) {
      ctx.beginPath();
      ctx.moveTo(x, y - size);
      ctx.lineTo(x + size, y);
      ctx.lineTo(x, y + size);
      ctx.lineTo(x - size, y);
      ctx.closePath();
      ctx.fill();
    }

    function drawDirectionArrow(ctx, cx, cy, x, y, direction, color) {
      if (direction !== "approaching" && direction !== "departing") return;
      const angle = Math.atan2(y - cy, x - cx);
      const sign = direction === "approaching" ? -1 : 1;
      const tipAngle = angle + (sign < 0 ? Math.PI : 0);
      const tx = x + Math.cos(tipAngle) * 16;
      const ty = y + Math.sin(tipAngle) * 16;
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(x, y);
      ctx.lineTo(tx, ty);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(tx, ty);
      ctx.lineTo(tx - Math.cos(tipAngle - 0.5) * 6, ty - Math.sin(tipAngle - 0.5) * 6);
      ctx.moveTo(tx, ty);
      ctx.lineTo(tx - Math.cos(tipAngle + 0.5) * 6, ty - Math.sin(tipAngle + 0.5) * 6);
      ctx.stroke();
    }

    function renderDetails() {
      const root = document.getElementById("details");
      const device = snapshot.devices.find((item) => item.bssid === selectedBssid);
      drawSignalGraph(device);
      if (!device) {
        root.className = "empty";
        root.textContent = "Select a device to see details.";
        return;
      }
      root.className = "";
      root.innerHTML = `
        <h3>${escapeHtml(device.ssid || "(hidden / no SSID)")}</h3>
        <dl>
          <dt>BSSID</dt><dd>${escapeHtml(device.bssid)}</dd>
          <dt>Vendor</dt><dd>${escapeHtml(device.vendor || "unknown")}</dd>
          <dt>Channel</dt><dd>${device.channel ?? "?"}${device.frequency_mhz ? " (" + device.frequency_mhz + " MHz)" : ""}</dd>
          <dt>Raw RSSI</dt><dd>${device.rssi ?? "unknown"} dBm</dd>
          <dt>Smoothed RSSI</dt><dd>${device.rssi_smoothed ?? "unknown"} dBm</dd>
          <dt>Estimated distance</dt><dd>${formatDistance(device.estimated_distance_m)} (${escapeHtml(device.distance_label)})</dd>
          <dt>Motion</dt><dd>${escapeHtml(device.motion)} · ${escapeHtml(device.direction)}</dd>
          <dt>In alarm zone</dt><dd>${device.in_alarm_zone ? "YES" : "no"}</dd>
          <dt>First seen</dt><dd>${escapeHtml(device.first_seen)}</dd>
          <dt>Last seen</dt><dd>${escapeHtml(device.last_seen)} (${device.stale_seconds}s ago)</dd>
        </dl>`;
    }

    function drawSignalGraph(device) {
      const canvas = document.getElementById("signal-graph");
      const ctx = canvas.getContext("2d");
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.strokeStyle = "#22304a";
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
        ctx.fillText("Select a device to plot history", 44, canvas.height / 2);
        return;
      }
      const raw = device.rssi_history;
      drawLine(ctx, raw, "#64748b", 2, canvas);
      drawLine(ctx, smoothSeries(raw), "#38bdf8", 3, canvas);
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
      root.innerHTML = events.map((event) => {
        const cls = event.type === "alarm" ? "alarm-line" : "";
        return `<div class="${cls}">${escapeHtml(event.at)} · ${escapeHtml(event.type)} · ${escapeHtml(event.ssid || event.bssid)} · ${escapeHtml(event.message)}</div>`;
      }).join("");
    }

    function smoothSeries(values, window = 6) {
      return values.map((_, end) => {
        const start = Math.max(0, end - window + 1);
        const chunk = values.slice(start, end + 1);
        let weighted = 0, sum = 0;
        chunk.forEach((value, index) => { const w = index + 1; weighted += value * w; sum += w; });
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
    function mapDistanceToRadius(distanceMeters, maxRadius) {
      const distance = Math.max(0.2, Math.min(distanceMeters || 40, 60));
      const normalized = Math.log10(distance + 1) / Math.log10(61);
      return 22 + normalized * (maxRadius - 22);
    }
    function hashToAngle(text) {
      let hash = 0;
      for (let i = 0; i < text.length; i++) { hash = ((hash << 5) - hash) + text.charCodeAt(i); hash |= 0; }
      return ((hash >>> 0) % 360) * (Math.PI / 180);
    }
    function shortLabel(device) {
      const name = (device.ssid || "").trim();
      if (name) return name.length > 18 ? `${name.slice(0, 17)}…` : name;
      return device.bssid.slice(-8);
    }
    function formatDistance(distanceMeters) {
      if (typeof distanceMeters !== "number") return "distance unknown";
      if (distanceMeters < 1) return `${Math.round(distanceMeters * 100)} cm est.`;
      return `${distanceMeters.toFixed(2)} m est.`;
    }
    function hexToRgba(hex, alpha) {
      const clean = hex.replace("#", "");
      const bigint = parseInt(clean, 16);
      return `rgba(${(bigint >> 16) & 255},${(bigint >> 8) & 255},${bigint & 255},${alpha})`;
    }
    function escapeHtml(value) {
      return String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
    }
  </script>
</body>
</html>
"""
