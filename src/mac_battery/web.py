"""Live web dashboard for MacBook battery diagnostics."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse

if TYPE_CHECKING:
    from .state import BatteryState

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>MacBook Battery Diagnostic</title>
<style>
  :root {
    --ink: #f1f1fb;
    --muted: #a8abd6;
    --line: rgba(255, 255, 255, 0.12);
    --panel: rgba(20, 18, 56, 0.55);
    --pill: rgba(255, 255, 255, 0.09);
    --pill-line: rgba(255, 255, 255, 0.18);
    --accent: #3ecf8e;
    --accent-dim: #1f7a56;
    --warn: #e6b84d;
    --danger: #e36d5a;
    --volt: #6ec8ff;
    --amp: #f0a36b;
    --watt: #c9a0ff;
    --font-display: "IBM Plex Sans", "Avenir Next", "Segoe UI", sans-serif;
    --font-mono: "IBM Plex Mono", "SF Mono", ui-monospace, monospace;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    min-height: 100vh;
    color: var(--ink);
    font-family: var(--font-display);
    background:
      radial-gradient(1100px 620px at 8% -12%, #4b3aa8 0%, transparent 55%),
      radial-gradient(900px 560px at 100% 0%, #2c3f9e 0%, transparent 52%),
      radial-gradient(900px 700px at 30% 120%, #1f2a78 0%, transparent 60%),
      linear-gradient(165deg, #1b1750, #100d33);
  }
  header {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    padding: 1.5rem 1.75rem 0.9rem;
    border-bottom: 1px solid var(--line);
  }
  header h1 {
    margin: 0;
    font-size: 1.4rem;
    font-weight: 650;
    letter-spacing: 0.01em;
  }
  .pills { display: flex; flex-wrap: wrap; gap: 0.5rem; }
  .pill {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    padding: 0.35rem 0.85rem;
    border-radius: 999px;
    background: var(--pill);
    border: 1px solid var(--pill-line);
    font-size: 0.82rem;
    font-weight: 600;
    color: var(--muted);
  }
  .pill.on { color: var(--accent); border-color: var(--accent-dim); }
  .pill.limit { color: var(--ink); }
  main {
    display: grid;
    gap: 1rem;
    padding: 1.25rem 1.75rem 2rem;
    grid-template-columns: repeat(12, 1fr);
  }
  .panel {
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 16px;
    padding: 1.1rem 1.2rem 1.25rem;
    backdrop-filter: blur(10px);
  }
  .span-4 { grid-column: span 4; }
  .span-6 { grid-column: span 6; }
  .span-8 { grid-column: span 8; }
  .span-12 { grid-column: span 12; }
  @media (max-width: 980px) {
    .span-4, .span-6, .span-8 { grid-column: span 12; }
  }
  h2 {
    margin: 0 0 0.85rem;
    font-size: 0.78rem;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    color: var(--muted);
    font-weight: 600;
  }
  .icon { width: 1.05em; height: 1.05em; stroke: currentColor; fill: none; stroke-width: 1.8; vertical-align: -0.18em; }
  .metrics {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 0.75rem;
  }
  @media (max-width: 640px) {
    .metrics { grid-template-columns: 1fr; }
  }
  .metric .label { color: var(--muted); font-size: 0.78rem; }
  .metric .value {
    font-family: var(--font-mono);
    font-size: 1.5rem;
    font-weight: 600;
    margin-top: 0.15rem;
  }
  .metric.volt .value { color: var(--volt); }
  .metric.amp .value { color: var(--amp); }
  .metric.watt .value { color: var(--watt); }
  .sub { color: var(--muted); font-size: 0.8rem; margin-top: 0.2rem; }

  /* Level bar (AlDente-style pill with plug icon + percent inside the fill) */
  .level-bar {
    height: 46px;
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid var(--line);
    overflow: hidden;
    position: relative;
  }
  .level-fill {
    position: absolute;
    inset: 0;
    width: 0%;
    display: flex;
    align-items: center;
    gap: 0.4rem;
    padding-left: 1rem;
    background: linear-gradient(90deg, var(--accent-dim), var(--accent));
    color: #062017;
    font-weight: 700;
    font-family: var(--font-mono);
    font-size: 1rem;
    transition: width 0.5s ease;
    white-space: nowrap;
  }
  .level-target {
    position: absolute;
    top: 4px;
    bottom: 4px;
    width: 0;
    border-left: 2px dashed rgba(255, 255, 255, 0.55);
  }

  .going-on {
    display: flex;
    align-items: flex-start;
    gap: 0.7rem;
    color: var(--muted);
    font-size: 0.95rem;
    line-height: 1.4;
  }
  .going-on .icons { display: flex; gap: 0.4rem; color: var(--accent); flex-shrink: 0; margin-top: 0.1rem; }
  .going-on p { margin: 0; color: var(--ink); }

  .bar {
    height: 12px;
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.08);
    overflow: hidden;
    margin-top: 0.55rem;
  }
  .bar > span {
    display: block;
    height: 100%;
    width: 0%;
    background: linear-gradient(90deg, var(--accent-dim), var(--accent));
    transition: width 0.4s ease;
  }
  .bar.health > span { background: linear-gradient(90deg, #b8860b, var(--accent)); }

  .eta-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0.85rem; }
  .eta { padding: 0.85rem 0.9rem; border-radius: 12px; background: rgba(255, 255, 255, 0.05); border: 1px solid var(--line); }
  .eta .big { font-family: var(--font-mono); font-size: 1.3rem; margin-top: 0.25rem; color: var(--accent); }

  .stat-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    padding: 0.55rem 0;
    border-bottom: 1px solid var(--line);
    font-size: 0.92rem;
  }
  .stat-row:last-child { border-bottom: none; }
  .stat-row .stat-label { display: flex; align-items: center; gap: 0.55rem; color: var(--muted); }
  .stat-row .stat-values { display: flex; gap: 0.9rem; font-family: var(--font-mono); }
  .stat-row .stat-values .pct { color: var(--muted); min-width: 3.2em; text-align: right; }

  .flow {
    display: grid;
    grid-template-columns: auto 1fr auto;
    align-items: center;
    gap: 0.7rem;
    margin-top: 0.35rem;
  }
  .flow .node {
    width: 34px; height: 34px;
    border-radius: 10px;
    display: flex; align-items: center; justify-content: center;
    background: rgba(255, 255, 255, 0.07);
    border: 1px solid var(--line);
  }
  .flow-track {
    height: 30px;
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.06);
    position: relative;
    overflow: hidden;
  }
  .flow-fill {
    position: absolute; inset: 0; width: 0%;
    display: flex; align-items: center; justify-content: center;
    font-family: var(--font-mono); font-weight: 600; font-size: 0.85rem;
    transition: width 0.5s ease;
  }
  .flow-fill.charge { background: linear-gradient(90deg, var(--accent-dim), var(--accent)); color: #062017; }
  .flow-fill.discharge { background: linear-gradient(90deg, #274b8f, var(--volt)); color: #071427; }
  .flow-label { color: var(--muted); font-size: 0.8rem; margin-top: 0.35rem; }

  canvas { width: 100%; height: 180px; display: block; }
  #events { list-style: none; margin: 0; padding: 0; max-height: 180px; overflow: auto; }
  #events li { padding: 0.45rem 0; border-bottom: 1px solid var(--line); font-size: 0.88rem; color: var(--muted); }
  #events li strong { color: var(--ink); font-weight: 600; }
</style>
</head>
<body>
  <header>
    <h1>MacBook Battery Diagnostic</h1>
    <div class="pills">
      <span class="pill limit" id="limit-pill">Limit —%</span>
      <span class="pill" id="source">—</span>
      <span class="pill" id="charge-state">—</span>
    </div>
  </header>
  <main>
    <section class="panel span-12">
      <h2>Live electricals</h2>
      <div class="metrics">
        <div class="metric volt">
          <div class="label">Charging voltage</div>
          <div class="value" id="voltage">—</div>
          <div class="sub" id="voltage-sub">mV</div>
        </div>
        <div class="metric amp">
          <div class="label">Amperage</div>
          <div class="value" id="amperage">—</div>
          <div class="sub" id="amperage-sub">mA</div>
        </div>
        <div class="metric watt">
          <div class="label">Power</div>
          <div class="value" id="watts">—</div>
          <div class="sub">V × I at battery</div>
        </div>
      </div>
    </section>

    <section class="panel span-12">
      <h2>Battery level</h2>
      <div class="level-bar" id="level-bar">
        <div class="level-target" id="level-target"></div>
        <div class="level-fill" id="level-fill">
          <svg class="icon" viewBox="0 0 24 24"><path d="M9 2h6v3h2a1 1 0 0 1 1 1v3H6V6a1 1 0 0 1 1-1h2V2Z"/><path d="M6 9h12v11a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V9Z"/></svg>
          <span id="level-text">—%</span>
        </div>
      </div>
    </section>

    <section class="panel span-12">
      <h2>What's going on?</h2>
      <div class="going-on">
        <span class="icons">
          <svg class="icon" viewBox="0 0 24 24"><path d="M9 2h6v3h2a1 1 0 0 1 1 1v3H6V6a1 1 0 0 1 1-1h2V2Z"/><path d="M6 9h12v11a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V9Z"/></svg>
          <svg class="icon" viewBox="0 0 24 24"><path d="M13 2 4 14h6l-1 8 9-12h-6l1-8Z"/></svg>
        </span>
        <p id="going-on-text">Waiting for the first reading…</p>
      </div>
    </section>

    <section class="panel span-8">
      <h2>Battery level history</h2>
      <canvas id="levelChart" width="900" height="180"></canvas>
    </section>

    <section class="panel span-4">
      <h2>Time to target</h2>
      <div class="eta-grid">
        <div class="eta">
          <div class="label" id="eta-target-label">To target</div>
          <div class="big" id="eta80">—</div>
        </div>
        <div class="eta">
          <div class="label">To full</div>
          <div class="big" id="etaFull">—</div>
        </div>
      </div>
      <div class="sub" id="apple-eta" style="margin-top:0.7rem">Apple ETA —</div>
    </section>

    <section class="panel span-6">
      <h2>Battery stats</h2>
      <div class="stat-row">
        <span class="stat-label">
          <svg class="icon" viewBox="0 0 24 24"><rect x="2" y="7" width="18" height="10" rx="2"/><path d="M22 10v4"/></svg>
          Design capacity
        </span>
        <span class="stat-values"><span id="design">— mAh</span><span class="pct">100%</span></span>
      </div>
      <div class="stat-row">
        <span class="stat-label">
          <svg class="icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 8v4l3 2"/></svg>
          macOS capacity
        </span>
        <span class="stat-values"><span id="maxcap">— mAh</span><span class="pct" id="health-pct">—</span></span>
      </div>
      <div class="stat-row">
        <span class="stat-label">
          <svg class="icon" viewBox="0 0 24 24"><path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 4v5h5"/></svg>
          Cycle count
        </span>
        <span class="stat-values"><span id="cycles">—</span><span class="pct" id="cycle-used">—</span></span>
      </div>
      <div class="stat-row">
        <span class="stat-label">
          <svg class="icon" viewBox="0 0 24 24"><path d="M10 14.5V4a2 2 0 1 1 4 0v10.5a4 4 0 1 1-4 0Z"/></svg>
          Battery temperature
        </span>
        <span class="stat-values"><span id="temp">— °C</span></span>
      </div>
      <div class="stat-row">
        <span class="stat-label">
          <svg class="icon" viewBox="0 0 24 24"><path d="M13 2 4 14h6l-1 8 9-12h-6l1-8Z"/></svg>
          Power
        </span>
        <span class="stat-values"><span id="watts2">— W</span></span>
      </div>
    </section>

    <section class="panel span-6">
      <h2>Power flow</h2>
      <div class="flow">
        <div class="node">
          <svg class="icon" viewBox="0 0 24 24"><path d="M9 2v4M15 2v4M6 8h12l-1 5a5 5 0 0 1-10 0L6 8Z"/><path d="M10 18v2M14 18v2"/></svg>
        </div>
        <div class="flow-track"><div class="flow-fill" id="flow-fill">—</div></div>
        <div class="node">
          <svg class="icon" viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="12" rx="1.5"/><path d="M2 20h20"/></svg>
        </div>
      </div>
      <div class="flow-label" id="flow-label">Battery power —</div>
    </section>

    <section class="panel span-8">
      <h2>Realtime history (voltage / watts)</h2>
      <canvas id="chart" width="900" height="180"></canvas>
    </section>

    <section class="panel span-4">
      <h2>Events</h2>
      <ul id="events"></ul>
    </section>
  </main>
<script>
const history = [];
const maxPoints = 120;
let lastPushedTs = null;
let currentTarget = 80;

function $(id) { return document.getElementById(id); }

function goingOnText(report) {
  const c = report.charging || {};
  const target = c.optimized_target_percent ?? 80;
  if (c.fully_charged) return "Battery is fully charged.";
  if (c.is_charging) {
    const pct = c.charge_percent;
    if (pct != null && pct < target) {
      return `Battery is charging to ${target}%. Currently at ${pct.toFixed(0)}%, ${c.eta_to_80_label} to go.`;
    }
    return `Battery is charging to 100%. ${c.eta_to_full_label} to go.`;
  }
  if (c.adapter_connected) return "Connected to power. Charging is paused above your limit.";
  const pct = c.charge_percent;
  return `Running on battery power${pct != null ? " · " + pct.toFixed(0) + "% remaining" : ""}.`;
}

function apply(report) {
  if (!report) return;
  const e = report.electrical || {};
  const c = report.charging || {};
  const h = report.health || {};
  currentTarget = c.optimized_target_percent ?? 80;

  $("voltage").textContent = (e.voltage_v ?? "—") + " V";
  $("voltage-sub").textContent = (e.voltage_mv ?? "—") + " mV";
  $("amperage").textContent = (e.amperage_a ?? "—") + " A";
  $("amperage-sub").textContent = (e.amperage_ma ?? "—") + " mA · " +
    (e.amperage_ma > 50 ? "charging" : e.amperage_ma < -50 ? "discharging" : "idle");
  $("watts").textContent = (e.watts ?? "—") + " W";
  $("watts2").textContent = (e.watts ?? "—") + " W";
  $("temp").textContent = (e.temperature_c ?? "—") + " °C";

  const soc = c.charge_percent;
  $("level-text").textContent = soc == null ? "—%" : soc.toFixed(0) + "%";
  $("level-fill").style.width = (soc ?? 0) + "%";
  $("level-target").style.left = currentTarget + "%";

  $("limit-pill").textContent = "Limit: " + currentTarget + "%";
  $("eta-target-label").textContent = "To " + currentTarget + "%";
  $("eta80").textContent = c.eta_to_80_label || "—";
  $("etaFull").textContent = c.eta_to_full_label || "—";
  $("apple-eta").textContent = c.apple_time_remaining_min == null
    ? "Apple ETA —"
    : "Apple ETA " + c.apple_time_remaining_min + " min";

  const health = h.health_percent;
  $("design").textContent = (h.design_capacity_mah ?? "—") + " mAh";
  $("maxcap").textContent = (h.max_capacity_mah ?? "—") + " mAh";
  $("health-pct").textContent = health == null ? "—" : health.toFixed(0) + "%";
  $("cycles").textContent = h.cycle_count ?? "—";
  $("cycle-used").textContent = h.cycle_life_used_percent == null ? "—" : h.cycle_life_used_percent + "%";

  const amp = e.amperage_ma ?? 0;
  const watts = Math.abs(e.watts ?? 0);
  const flowFill = $("flow-fill");
  const flowMax = Math.max(watts, 30);
  if (amp > 50) {
    flowFill.className = "flow-fill charge";
    flowFill.style.width = Math.min(100, (watts / flowMax) * 100) + "%";
    flowFill.textContent = watts.toFixed(1) + " W";
    $("flow-label").textContent = "Charging the battery at " + watts.toFixed(1) + " W";
  } else if (amp < -50) {
    flowFill.className = "flow-fill discharge";
    flowFill.style.width = Math.min(100, (watts / flowMax) * 100) + "%";
    flowFill.textContent = watts.toFixed(1) + " W";
    $("flow-label").textContent = "Powering the Mac from battery at " + watts.toFixed(1) + " W";
  } else {
    flowFill.className = "flow-fill";
    flowFill.style.width = "4%";
    flowFill.style.background = "rgba(255,255,255,0.15)";
    flowFill.textContent = "";
    $("flow-label").textContent = "Idle / trickle";
  }

  $("going-on-text").textContent = goingOnText(report);

  const src = $("source");
  src.textContent = report.source || "—";
  const st = $("charge-state");
  st.textContent = c.is_charging ? "charging" : (c.fully_charged ? "full" : "not charging");
  st.className = "pill" + (c.is_charging ? " on" : "");
}

function drawLevelChart() {
  const canvas = $("levelChart");
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const cssW = canvas.clientWidth;
  const cssH = 180;
  canvas.width = Math.floor(cssW * dpr);
  canvas.height = Math.floor(cssH * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);

  const pad = 10;
  function x(i, n) { return pad + (i / Math.max(1, n - 1)) * (cssW - pad * 2); }
  function y(pct) { return cssH - pad - (Math.max(0, Math.min(100, pct)) / 100) * (cssH - pad * 2); }

  ctx.setLineDash([5, 4]);
  ctx.strokeStyle = "rgba(255,255,255,0.35)";
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(pad, y(currentTarget));
  ctx.lineTo(cssW - pad, y(currentTarget));
  ctx.stroke();
  ctx.setLineDash([]);

  const pts = history.filter(p => p.charge_percent != null);
  if (pts.length < 2) return;
  ctx.lineWidth = 2;
  ctx.strokeStyle = "#3ecf8e";
  ctx.beginPath();
  pts.forEach((p, i) => i ? ctx.lineTo(x(i, pts.length), y(p.charge_percent)) : ctx.moveTo(x(i, pts.length), y(p.charge_percent)));
  ctx.stroke();
}

function draw() {
  const canvas = $("chart");
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const cssW = canvas.clientWidth;
  const cssH = 180;
  canvas.width = Math.floor(cssW * dpr);
  canvas.height = Math.floor(cssH * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);
  if (history.length < 2) return;

  const pad = 10;
  const volts = history.map(p => p.voltage_v);
  const watts = history.map(p => Math.abs(p.watts));
  const minV = Math.min(...volts) - 0.05;
  const maxV = Math.max(...volts) + 0.05;
  const maxW = Math.max(...watts, 1) * 1.15;

  function x(i) { return pad + (i / (history.length - 1)) * (cssW - pad * 2); }
  function yV(v) { return cssH - pad - ((v - minV) / (maxV - minV || 1)) * (cssH - pad * 2); }
  function yW(w) { return cssH - pad - (w / maxW) * (cssH - pad * 2); }

  ctx.lineWidth = 2;
  ctx.strokeStyle = "#6ec8ff";
  ctx.beginPath();
  volts.forEach((v, i) => i ? ctx.lineTo(x(i), yV(v)) : ctx.moveTo(x(i), yV(v)));
  ctx.stroke();

  ctx.strokeStyle = "#c9a0ff";
  ctx.beginPath();
  watts.forEach((w, i) => i ? ctx.lineTo(x(i), yW(w)) : ctx.moveTo(x(i), yW(w)));
  ctx.stroke();

  drawLevelChart();
}

function pushHistory(report) {
  const ts = report.timestamp;
  if (ts != null && ts === lastPushedTs) return;
  lastPushedTs = ts;
  const e = report.electrical || {};
  const c = report.charging || {};
  history.push({ voltage_v: e.voltage_v || 0, watts: e.watts || 0, charge_percent: c.charge_percent ?? null });
  while (history.length > maxPoints) history.shift();
  draw();
}

function addEvent(ev) {
  const li = document.createElement("li");
  li.innerHTML = "<strong>" + (ev.type || "event") + "</strong> — " + (ev.message || "");
  $("events").prepend(li);
}

async function boot() {
  const snap = await fetch("/api/snapshot").then(r => r.json());
  if (snap.latest) {
    apply(snap.latest);
    (snap.history || []).forEach(p => {
      history.push({ voltage_v: p.voltage_v || 0, watts: p.watts || 0, charge_percent: p.charge_percent ?? null });
    });
    lastPushedTs = snap.latest.timestamp ?? null;
    draw();
  }
  (snap.events || []).slice().reverse().forEach(addEvent);

  const es = new EventSource("/api/events");
  es.onmessage = (msg) => {
    const payload = JSON.parse(msg.data);
    if (payload.type === "snapshot") {
      apply(payload.data);
      pushHistory(payload.data);
    } else if (payload.type === "event") {
      addEvent(payload.data);
    }
  };
  window.addEventListener("resize", draw);
}
boot();
</script>
</body>
</html>
"""


POPOVER_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Battery</title>
<style>
  :root {
    --ink: #f1f1fb;
    --muted: #a8abd6;
    --line: rgba(255, 255, 255, 0.12);
    --accent: #3ecf8e;
    --accent-dim: #1f7a56;
    --font-display: "IBM Plex Sans", "Avenir Next", "Segoe UI", sans-serif;
    --font-mono: "IBM Plex Mono", "SF Mono", ui-monospace, monospace;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; overflow: hidden; }
  body {
    width: 320px;
    color: var(--ink);
    font-family: var(--font-display);
    background:
      radial-gradient(480px 280px at 0% -20%, #4b3aa8 0%, transparent 60%),
      radial-gradient(480px 280px at 100% 0%, #2c3f9e 0%, transparent 55%),
      linear-gradient(165deg, #1b1750, #100d33);
    padding: 14px;
  }
  header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; gap: 0.4rem; }
  header h1 { font-size: 0.95rem; margin: 0; font-weight: 650; white-space: nowrap; }
  .pills { display: flex; gap: 0.3rem; flex-wrap: wrap; justify-content: flex-end; }
  .pill {
    display: inline-flex; align-items: center; gap: 0.3rem;
    padding: 0.18rem 0.55rem; border-radius: 999px;
    background: rgba(255, 255, 255, 0.09); border: 1px solid rgba(255, 255, 255, 0.18);
    font-size: 0.68rem; font-weight: 600; color: var(--muted); white-space: nowrap;
  }
  .pill.on { color: var(--accent); border-color: var(--accent-dim); }
  .level-bar {
    height: 32px; border-radius: 999px; background: rgba(255, 255, 255, 0.06);
    border: 1px solid var(--line); position: relative; overflow: hidden; margin-bottom: 10px;
  }
  .level-fill {
    position: absolute; inset: 0; width: 0%; display: flex; align-items: center; gap: 0.35rem;
    padding-left: 0.7rem; background: linear-gradient(90deg, var(--accent-dim), var(--accent));
    color: #062017; font-weight: 700; font-family: var(--font-mono); font-size: 0.82rem;
    white-space: nowrap; transition: width 0.5s ease;
  }
  .level-target { position: absolute; top: 3px; bottom: 3px; width: 0; border-left: 2px dashed rgba(255, 255, 255, 0.55); }
  .icon { width: 0.9em; height: 0.9em; stroke: currentColor; fill: none; stroke-width: 1.8; }
  .going-on { font-size: 0.8rem; color: var(--muted); line-height: 1.35; margin-bottom: 10px; min-height: 2.3em; }
  .stats { display: grid; grid-template-columns: 1fr 1fr; gap: 0 0.8rem; font-size: 0.78rem; margin-bottom: 10px; }
  .stats div { display: flex; justify-content: space-between; gap: 0.4rem; padding: 0.16rem 0; border-bottom: 1px solid var(--line); }
  .stats span:first-child { color: var(--muted); }
  .stats span:last-child { font-family: var(--font-mono); }
  footer { font-size: 0.68rem; color: var(--muted); text-align: center; border-top: 1px solid var(--line); padding-top: 8px; }
</style>
</head>
<body>
  <header>
    <h1>Battery</h1>
    <span class="pills">
      <span class="pill" id="source">—</span>
      <span class="pill" id="charge-state">—</span>
    </span>
  </header>
  <div class="level-bar" id="level-bar">
    <div class="level-target" id="level-target"></div>
    <div class="level-fill" id="level-fill">
      <svg class="icon" viewBox="0 0 24 24"><path d="M9 2h6v3h2a1 1 0 0 1 1 1v3H6V6a1 1 0 0 1 1-1h2V2Z"/><path d="M6 9h12v11a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V9Z"/></svg>
      <span id="level-text">—%</span>
    </div>
  </div>
  <div class="going-on" id="going-on-text">Waiting for the first reading…</div>
  <div class="stats">
    <div><span>Power</span><span id="watts">—</span></div>
    <div><span>To target</span><span id="eta80">—</span></div>
    <div><span>Voltage</span><span id="voltage">—</span></div>
    <div><span>To full</span><span id="etaFull">—</span></div>
    <div><span>Health</span><span id="health">—</span></div>
    <div><span>Cycles</span><span id="cycles">—</span></div>
    <div><span>Temp</span><span id="temp">—</span></div>
    <div><span>Amperage</span><span id="amperage">—</span></div>
  </div>
  <footer>Right-click the menu-bar icon for the full dashboard &amp; Quit</footer>
<script>
function $(id) { return document.getElementById(id); }
let currentTarget = 80;

function goingOnText(report) {
  const c = report.charging || {};
  const target = c.optimized_target_percent ?? 80;
  if (c.fully_charged) return "Fully charged.";
  if (c.is_charging) {
    const pct = c.charge_percent;
    if (pct != null && pct < target) return `Charging to ${target}% — ${c.eta_to_80_label} to go.`;
    return `Charging to 100% — ${c.eta_to_full_label} to go.`;
  }
  if (c.adapter_connected) return "On power, paused above your limit.";
  const pct = c.charge_percent;
  return `On battery${pct != null ? " · " + pct.toFixed(0) + "% left" : ""}.`;
}

function apply(report) {
  if (!report) return;
  const e = report.electrical || {};
  const c = report.charging || {};
  const h = report.health || {};
  currentTarget = c.optimized_target_percent ?? 80;

  const soc = c.charge_percent;
  $("level-text").textContent = soc == null ? "—%" : soc.toFixed(0) + "%";
  $("level-fill").style.width = (soc ?? 0) + "%";
  $("level-target").style.left = currentTarget + "%";

  $("watts").textContent = (e.watts ?? "—") + " W";
  $("voltage").textContent = (e.voltage_v ?? "—") + " V";
  $("amperage").textContent = (e.amperage_a ?? "—") + " A";
  $("temp").textContent = (e.temperature_c ?? "—") + " °C";
  $("health").textContent = h.health_percent == null ? "—" : h.health_percent.toFixed(0) + "%";
  $("cycles").textContent = h.cycle_count ?? "—";
  $("eta80").textContent = c.eta_to_80_label || "—";
  $("etaFull").textContent = c.eta_to_full_label || "—";

  $("going-on-text").textContent = goingOnText(report);

  $("source").textContent = report.source || "—";
  const st = $("charge-state");
  st.textContent = c.is_charging ? "charging" : (c.fully_charged ? "full" : "not charging");
  st.className = "pill" + (c.is_charging ? " on" : "");
}

async function boot() {
  const snap = await fetch("/api/snapshot").then(r => r.json());
  if (snap.latest) apply(snap.latest);
  const es = new EventSource("/api/events");
  es.onmessage = (msg) => {
    const payload = JSON.parse(msg.data);
    if (payload.type === "snapshot") apply(payload.data);
  };
}
boot();
</script>
</body>
</html>
"""


def create_app(state: "BatteryState") -> FastAPI:
    app = FastAPI(title="MacBook Battery Diagnostic")

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return DASHBOARD_HTML

    @app.get("/popover", response_class=HTMLResponse)
    async def popover() -> str:
        return POPOVER_HTML

    @app.get("/api/snapshot")
    async def snapshot() -> dict:
        return state.snapshot()

    @app.get("/api/events")
    async def events() -> StreamingResponse:
        queue = state.subscribe()

        async def generate():
            try:
                if state.latest:
                    yield _sse({"type": "snapshot", "data": state.latest})
                while True:
                    item = await queue.get()
                    yield _sse(item)
            except asyncio.CancelledError:
                pass
            finally:
                state.unsubscribe(queue)

        return StreamingResponse(generate(), media_type="text/event-stream")

    return app


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"
