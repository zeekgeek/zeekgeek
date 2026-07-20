"""Live web dashboard for MacBook battery diagnostics."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse

from .reader import RemoteIngestBuffer, sample_from_payload

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
    --bg0: #0c1210;
    --bg1: #14201b;
    --ink: #e7f2ec;
    --muted: #8aa396;
    --line: #24362e;
    --accent: #3ecf8e;
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
      radial-gradient(1200px 600px at 10% -10%, #1a3a2c 0%, transparent 55%),
      radial-gradient(900px 500px at 100% 0%, #1a2a38 0%, transparent 50%),
      linear-gradient(165deg, var(--bg0), var(--bg1));
  }
  header {
    padding: 1.5rem 1.75rem 0.75rem;
    border-bottom: 1px solid var(--line);
  }
  header h1 {
    margin: 0;
    font-size: 1.45rem;
    font-weight: 650;
    letter-spacing: 0.02em;
  }
  header p {
    margin: 0.35rem 0 0;
    color: var(--muted);
    font-size: 0.92rem;
  }
  #waiting {
    display: none;
    margin: 1rem 1.75rem 0;
    padding: 0.9rem 1rem;
    border: 1px solid #5a4a20;
    background: rgba(80, 60, 10, 0.35);
    border-radius: 10px;
    color: var(--warn);
    font-size: 0.92rem;
  }
  #waiting code {
    font-family: var(--font-mono);
    color: var(--ink);
  }
  main {
    display: grid;
    gap: 1rem;
    padding: 1.25rem 1.75rem 2rem;
    grid-template-columns: repeat(12, 1fr);
  }
  .panel {
    background: rgba(8, 14, 12, 0.45);
    border: 1px solid var(--line);
    border-radius: 14px;
    padding: 1rem 1.1rem 1.15rem;
    backdrop-filter: blur(8px);
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
    font-size: 1.65rem;
    font-weight: 600;
    margin-top: 0.15rem;
  }
  .metric.volt .value { color: var(--volt); }
  .metric.amp .value { color: var(--amp); }
  .metric.watt .value { color: var(--watt); }
  .sub { color: var(--muted); font-size: 0.8rem; margin-top: 0.2rem; }
  .bar {
    height: 12px;
    border-radius: 999px;
    background: #1b2a24;
    overflow: hidden;
    margin-top: 0.55rem;
  }
  .bar > span {
    display: block;
    height: 100%;
    width: 0%;
    background: linear-gradient(90deg, #2a9b68, var(--accent));
    transition: width 0.4s ease;
  }
  .bar.health > span { background: linear-gradient(90deg, #b8860b, #3ecf8e); }
  .eta-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.85rem;
  }
  .eta {
    padding: 0.85rem 0.9rem;
    border-radius: 10px;
    background: #101a16;
    border: 1px solid var(--line);
  }
  .eta .big {
    font-family: var(--font-mono);
    font-size: 1.35rem;
    margin-top: 0.25rem;
    color: var(--accent);
  }
  .kv { display: grid; gap: 0.4rem; font-size: 0.92rem; }
  .kv div { display: flex; justify-content: space-between; gap: 1rem; }
  .kv span:last-child { font-family: var(--font-mono); color: var(--ink); }
  .kv span:first-child { color: var(--muted); }
  canvas {
    width: 100%;
    height: 180px;
    display: block;
  }
  #events {
    list-style: none;
    margin: 0;
    padding: 0;
    max-height: 180px;
    overflow: auto;
  }
  #events li {
    padding: 0.45rem 0;
    border-bottom: 1px solid var(--line);
    font-size: 0.88rem;
    color: var(--muted);
  }
  #events li strong { color: var(--ink); font-weight: 600; }
  .pill {
    display: inline-block;
    padding: 0.15rem 0.55rem;
    border-radius: 999px;
    border: 1px solid var(--line);
    font-size: 0.75rem;
    color: var(--muted);
  }
  .pill.on { color: var(--accent); border-color: #2f6b4f; }
</style>
</head>
<body>
  <header>
    <h1>MacBook Battery Diagnostic</h1>
    <p>
      Realtime voltage, current, watts · health &amp; cycles · ETA to 80% and full
      <span id="source" class="pill">—</span>
      <span id="charge-state" class="pill">—</span>
    </p>
  </header>
  <div id="waiting">
    Waiting for live sensor data.
    On your MacBook run:
    <code>python3 -m mac_battery.collect --url http://&lt;this-host&gt;:8780</code>
    or start the dashboard with
    <code>--ssh user@macbook</code> /
    <code>--source sysfs</code>.
  </div>
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

    <section class="panel span-6">
      <h2>Charge level</h2>
      <div class="value" style="font-family:var(--font-mono);font-size:1.8rem" id="soc">—</div>
      <div class="bar"><span id="soc-bar"></span></div>
      <div class="sub" id="temp" style="margin-top:0.65rem">Temp —</div>
    </section>

    <section class="panel span-6">
      <h2>Time to target</h2>
      <div class="eta-grid">
        <div class="eta">
          <div class="label">To 80%</div>
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
      <h2>Battery health</h2>
      <div class="value" style="font-family:var(--font-mono);font-size:1.8rem" id="health">—</div>
      <div class="bar health"><span id="health-bar"></span></div>
      <div class="kv" style="margin-top:0.9rem">
        <div><span>Design capacity</span><span id="design">—</span></div>
        <div><span>Max capacity now</span><span id="maxcap">—</span></div>
        <div><span>Current capacity</span><span id="curcap">—</span></div>
        <div><span>Condition</span><span id="health-band">—</span></div>
      </div>
    </section>

    <section class="panel span-6">
      <h2>Cycle wear</h2>
      <div class="kv">
        <div><span>Cycle count</span><span id="cycles">—</span></div>
        <div><span>Rated life</span><span id="cycle-limit">—</span></div>
        <div><span>Life used</span><span id="cycle-used">—</span></div>
        <div><span>Wear band</span><span id="cycle-band">—</span></div>
        <div><span>Pack</span><span id="pack">—</span></div>
      </div>
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

function $(id) { return document.getElementById(id); }

function apply(report) {
  if (!report) return;
  const e = report.electrical || {};
  const c = report.charging || {};
  const h = report.health || {};

  $("voltage").textContent = (e.voltage_v ?? "—") + " V";
  $("voltage-sub").textContent = (e.voltage_mv ?? "—") + " mV";
  $("amperage").textContent = (e.amperage_a ?? "—") + " A";
  $("amperage-sub").textContent = (e.amperage_ma ?? "—") + " mA · " +
    (e.amperage_ma > 50 ? "charging" : e.amperage_ma < -50 ? "discharging" : "idle");
  $("watts").textContent = (e.watts ?? "—") + " W";
  $("temp").textContent = "Temp " + (e.temperature_c ?? "—") + " °C";

  const soc = c.charge_percent;
  $("soc").textContent = soc == null ? "—" : soc.toFixed(1) + "%";
  $("soc-bar").style.width = (soc ?? 0) + "%";

  $("eta80").textContent = c.eta_to_80_label || "—";
  $("etaFull").textContent = c.eta_to_full_label || "—";
  $("apple-eta").textContent = c.apple_time_remaining_min == null
    ? "Apple ETA —"
    : "Apple ETA " + c.apple_time_remaining_min + " min";

  const health = h.health_percent;
  $("health").textContent = health == null ? "—" : health.toFixed(1) + "%";
  $("health-bar").style.width = (health ?? 0) + "%";
  $("design").textContent = (h.design_capacity_mah ?? "—") + " mAh";
  $("maxcap").textContent = (h.max_capacity_mah ?? "—") + " mAh";
  $("curcap").textContent = (h.current_capacity_mah ?? "—") + " mAh";
  $("health-band").textContent = h.health_band || "—";

  $("cycles").textContent = h.cycle_count ?? "—";
  $("cycle-limit").textContent = h.design_cycle_count ?? "—";
  $("cycle-used").textContent = h.cycle_life_used_percent == null ? "—" : h.cycle_life_used_percent + "%";
  $("cycle-band").textContent = h.cycle_band || "—";
  $("pack").textContent = [h.manufacturer, h.device_name].filter(Boolean).join(" ") || "—";

  const src = $("source");
  src.textContent = report.source || "—";
  const st = $("charge-state");
  st.textContent = c.is_charging ? "charging" : (c.fully_charged ? "full" : "not charging");
  st.className = "pill" + (c.is_charging ? " on" : "");
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
}

function pushHistory(report) {
  const e = report.electrical || {};
  history.push({ voltage_v: e.voltage_v || 0, watts: e.watts || 0 });
  while (history.length > maxPoints) history.shift();
  draw();
}

function addEvent(ev) {
  const li = document.createElement("li");
  li.innerHTML = "<strong>" + (ev.type || "event") + "</strong> — " + (ev.message || "");
  $("events").prepend(li);
}

function setWaiting(on) {
  $("waiting").style.display = on ? "block" : "none";
}

async function boot() {
  const snap = await fetch("/api/snapshot").then(r => r.json());
  setWaiting(!snap.latest);
  if (snap.latest) {
    apply(snap.latest);
    (snap.history || []).forEach(p => {
      history.push({ voltage_v: p.voltage_v || 0, watts: p.watts || 0 });
    });
    draw();
  }
  (snap.events || []).slice().reverse().forEach(addEvent);

  const es = new EventSource("/api/events");
  es.onmessage = (msg) => {
    const payload = JSON.parse(msg.data);
    if (payload.type === "snapshot") {
      setWaiting(false);
      apply(payload.data);
      pushHistory(payload.data);
    } else if (payload.type === "event") {
      addEvent(payload.data);
    } else if (payload.type === "waiting") {
      setWaiting(true);
    }
  };
  window.addEventListener("resize", draw);
}
boot();
</script>
</body>
</html>
"""


def create_app(
    state: "BatteryState",
    *,
    ingest: RemoteIngestBuffer | None = None,
) -> FastAPI:
    app = FastAPI(title="MacBook Battery Diagnostic")

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return DASHBOARD_HTML

    @app.get("/api/snapshot")
    async def snapshot() -> dict:
        return state.snapshot()

    @app.get("/api/status")
    async def status() -> dict:
        return {
            "has_sample": state.latest is not None,
            "ingest_enabled": ingest is not None,
            "ingest_age_s": None if ingest is None else ingest.age_s(),
            "source": None if state.latest is None else state.latest.get("source"),
        }

    @app.post("/api/ingest")
    async def ingest_sample(payload: dict[str, Any]) -> dict:
        if ingest is None:
            raise HTTPException(
                status_code=400,
                detail="This dashboard is not in remote ingest mode. Start with --source remote.",
            )
        try:
            sample = sample_from_payload(payload)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        ingest.push(sample)
        return {"status": "accepted", "source": sample.source}

    @app.get("/api/events")
    async def events() -> StreamingResponse:
        queue = state.subscribe()

        async def generate():
            try:
                if state.latest:
                    yield _sse({"type": "snapshot", "data": state.latest})
                else:
                    yield _sse({"type": "waiting", "message": "waiting for sensor data"})
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
