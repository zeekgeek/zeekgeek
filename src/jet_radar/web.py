"""FastAPI dashboard for the private-jet movement radar."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from .state import RadarState


class SensitivityRequest(BaseModel):
    sigma: float | None = Field(default=None, ge=1.0, le=8.0)
    trigger_threshold: int | None = Field(default=None, ge=1, le=20)


def create_app(state: RadarState) -> FastAPI:
    app = FastAPI(title="Private Jet Movement Radar")

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return DASHBOARD_HTML

    @app.get("/api/jets")
    async def jets() -> dict:
        return await state.snapshot(stream=False)

    @app.post("/api/sensitivity")
    async def set_sensitivity(request: SensitivityRequest) -> JSONResponse:
        event = await state.set_sensitivity(
            sigma=request.sigma, trigger_threshold=request.trigger_threshold
        )
        return JSONResponse({"sigma": state.sigma, "event": event})

    @app.get("/api/events")
    async def events() -> StreamingResponse:
        return StreamingResponse(
            _event_stream(state),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return app


async def _event_stream(state: RadarState) -> AsyncIterator[str]:
    last_payload = ""
    while True:
        snapshot = await state.snapshot(stream=True)
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
  <title>Private Jet Movement Radar</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #060910;
      --panel: #0d1522;
      --panel-2: #131f33;
      --text: #e9eefb;
      --muted: #93a1ba;
      --green: #22c55e;
      --amber: #f59e0b;
      --red: #ef4444;
      --gold: #eab308;
      --blue: #38bdf8;
      --violet: #a78bfa;
    }
    body { margin: 0; font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif; background: var(--bg); color: var(--text); }
    header { padding: 18px 26px; border-bottom: 1px solid #1f2c45; display: flex; justify-content: space-between; gap: 16px; align-items: center; flex-wrap: wrap; }
    h1 { font-size: 21px; margin: 0; }
    h2 { margin: 0 0 10px 0; font-size: 17px; }
    button { background: var(--blue); color: #06111f; border: 0; border-radius: 10px; padding: 9px 13px; font-weight: 700; cursor: pointer; }
    .stats { display: flex; gap: 14px; color: var(--muted); font-size: 14px; flex-wrap: wrap; margin-top: 6px; }
    .stats b { color: var(--text); }
    .controls { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
    .controls label { font-size: 13px; color: var(--muted); }
    input[type=range] { accent-color: var(--blue); vertical-align: middle; }
    main { display: grid; grid-template-columns: minmax(330px, 410px) 1fr; gap: 16px; padding: 16px; align-items: start; }
    .panel { background: var(--panel); border: 1px solid #1f2c45; border-radius: 14px; padding: 14px; box-shadow: 0 16px 40px rgba(0,0,0,.3); }
    .stack { display: grid; gap: 16px; }
    .jet-list { max-height: 70vh; overflow: auto; }
    .jet { border: 1px solid #24314c; border-radius: 12px; padding: 10px; margin: 8px 0; background: var(--panel-2); cursor: pointer; }
    .jet.active { outline: 2px solid var(--blue); }
    .jet.emergency { border-color: var(--red); box-shadow: 0 0 0 1px var(--red) inset; }
    .jet.watched { border-color: #5b4a1e; }
    .jet-title { display: flex; justify-content: space-between; align-items: start; gap: 10px; }
    .name { font-weight: 800; }
    .addr { color: var(--muted); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
    .badge { border-radius: 999px; padding: 3px 8px; font-size: 12px; font-weight: 700; white-space: nowrap; }
    .badge.airborne { background: rgba(34,197,94,.15); color: var(--green); }
    .badge.new { background: rgba(56,189,248,.16); color: var(--blue); }
    .badge.dark { background: rgba(234,179,8,.16); color: var(--gold); }
    .badge.emergency { background: rgba(239,68,68,.2); color: #fca5a5; }
    .badge.watched { background: rgba(167,139,250,.18); color: var(--violet); }
    .badge.tanker { background: rgba(245,158,11,.18); color: var(--amber); }
    .badge.gone { background: rgba(148,163,184,.12); color: var(--muted); }
    .badge.still { background: rgba(148,163,184,.15); color: var(--muted); }
    .badge.move { background: rgba(34,197,94,.15); color: var(--green); }
    .meta-row { display: flex; justify-content: space-between; gap: 8px; font-size: 13px; color: var(--muted); margin-top: 6px; flex-wrap: wrap; }
    canvas { width: 100%; background: #050c18; border-radius: 12px; border: 1px solid #1f2c45; display: block; }
    #jet-map { height: 380px; }
    #volume-graph { height: 220px; }
    .events { max-height: 220px; overflow: auto; color: var(--muted); font-size: 13px; }
    .events .alarm-line { color: #fecaca; font-weight: 700; }
    .events .trigger-line { color: #fde68a; }
    .legend { display: flex; gap: 16px; flex-wrap: wrap; font-size: 12px; color: var(--muted); margin-top: 8px; }
    .legend span::before { content: ""; display: inline-block; width: 10px; height: 10px; margin-right: 6px; vertical-align: middle; border-radius: 50%; }
    .legend .n-dot::before { background: var(--green); }
    .legend .d-dot::before { background: var(--gold); }
    .legend .e-dot::before { background: var(--red); }
    .legend .s-dot::before { background: var(--blue); }
    .legend .w-dot::before { background: var(--violet); }
    .legend .t-dot::before { background: var(--amber); }
    .empty { color: var(--muted); text-align: center; padding: 34px 0; }
    .tiny-note { font-size: 12px; color: var(--muted); margin-top: 6px; }
    #status-banner { display: none; background: rgba(56,189,248,.14); border: 1px solid var(--blue); color: #bae6fd; padding: 10px 14px; border-radius: 10px; margin: 12px 16px 0 16px; font-size: 14px; }
    #status-banner.error { background: rgba(239,68,68,.14); border-color: var(--red); color: #fecaca; }
    #alarm-banner { display: none; background: rgba(239,68,68,.18); border: 1px solid var(--red); color: #fecaca; padding: 12px 16px; border-radius: 10px; margin: 12px 16px 0 16px; font-weight: 800; font-size: 15px; animation: pulse 1.2s infinite; }
    @keyframes pulse { 0%, 100% { box-shadow: 0 0 0 0 rgba(239,68,68,.4); } 50% { box-shadow: 0 0 0 8px rgba(239,68,68,0); } }
    .baseline-chip { border: 1px solid #24314c; border-radius: 10px; padding: 6px 10px; font-size: 12px; color: var(--muted); background: var(--panel-2); }
    .baseline-chip b { color: var(--text); }
    .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
    .hideout, .move-row { border: 1px solid #24314c; border-radius: 10px; padding: 8px 10px; margin: 6px 0; background: var(--panel-2); font-size: 13px; }
    .hideout b, .move-row b { color: var(--text); }
    .muted { color: var(--muted); }
    @media (max-width: 980px) { main { grid-template-columns: 1fr; } .jet-list { max-height: none; } .grid-2 { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Private Jet Movement Radar</h1>
      <div class="stats">
        <span id="counts">Waiting for ADS-B data...</span>
        <span id="updated"></span>
      </div>
    </div>
    <div class="controls">
      <span class="baseline-chip" id="baseline-chip">Baseline: learning…</span>
      <label>Surge sigma: <b id="sigma-label">3.0</b>&sigma;</label>
      <input id="sigma-slider" type="range" min="1" max="8" step="0.5" value="3">
      <label>Alarm at: <b id="threshold-label">3</b> triggers</label>
      <input id="threshold-slider" type="range" min="1" max="12" step="1" value="3">
      <button id="notify">Enable notifications</button>
      <button id="sound-toggle">Sound: off</button>
    </div>
  </header>

  <div id="status-banner"></div>
  <div id="alarm-banner"></div>

  <main>
    <section class="panel">
      <h2>Tracked jets</h2>
      <div id="jets" class="jet-list empty">No business jets observed yet.</div>
    </section>

    <section class="stack">
      <section class="panel">
        <h2>Jet positions</h2>
        <canvas id="jet-map" width="980" height="380"></canvas>
        <div class="legend">
          <span class="n-dot">Cruising</span>
          <span class="w-dot">Watchlist</span>
          <span class="t-dot">Tanker</span>
          <span class="d-dot">Dark</span>
          <span class="e-dot">Emergency</span>
          <span class="s-dot">Selected</span>
        </div>
      </section>

      <section class="panel">
        <h2>Movement volume vs historical baseline</h2>
        <canvas id="volume-graph" width="980" height="220"></canvas>
        <p class="tiny-note">Cyan: airborne jets. Dashed: baseline mean. Red shading: strange-event alarm. Amber ticks: triggers.</p>
      </section>

      <section class="grid-2">
        <section class="panel">
          <h2>Watchlist: move vs sit still</h2>
          <div id="posture" class="muted">No watched aircraft yet.</div>
          <div id="watch-moves" style="margin-top:10px;"></div>
          <p class="tiny-note">Reactive styles (publicly linked to Musk/Gates travel) are scored for scramble departures. Privacy-heavy styles are scored for quiet landings near known destinations.</p>
        </section>
        <section class="panel">
          <h2>Privacy / hideout candidates</h2>
          <div id="hideouts" class="muted">No privacy landings scored yet.</div>
          <p class="tiny-note">Built from public ADS-B quiet-zones near publicly reported HNW property corridors — not claims about underground facilities.</p>
        </section>
      </section>

      <section class="panel">
        <h2>Movement triggers &amp; events</h2>
        <div id="events" class="events"></div>
      </section>
    </section>
  </main>

  <script>
    let snapshot = null;
    let selectedHex = null;
    let soundOn = false;
    let audioCtx = null;
    let sirenTimer = null;
    const notifiedEvents = new Set();

    const sigmaSlider = document.getElementById("sigma-slider");
    const sigmaLabel = document.getElementById("sigma-label");
    const thresholdSlider = document.getElementById("threshold-slider");
    const thresholdLabel = document.getElementById("threshold-label");

    document.getElementById("notify").onclick = async () => {
      if (!("Notification" in window)) { alert("This browser does not support notifications."); return; }
      await Notification.requestPermission();
    };

    document.getElementById("sound-toggle").onclick = (event) => {
      soundOn = !soundOn;
      event.target.textContent = `Sound: ${soundOn ? "on" : "off"}`;
      if (soundOn && !audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      if (!soundOn) stopSiren();
    };

    sigmaSlider.oninput = () => { sigmaLabel.textContent = Number(sigmaSlider.value).toFixed(1); };
    sigmaSlider.onchange = () => postSensitivity({ sigma: Number(sigmaSlider.value) });
    thresholdSlider.oninput = () => { thresholdLabel.textContent = thresholdSlider.value; };
    thresholdSlider.onchange = () => postSensitivity({ trigger_threshold: Number(thresholdSlider.value) });

    async function postSensitivity(body) {
      await fetch("/api/sensitivity", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    }

    let source = null;

    function connectEvents() {
      if (source) source.close();
      source = new EventSource("/api/events");
      source.onmessage = (message) => {
        document.getElementById("status-banner").style.display = "none";
        snapshot = JSON.parse(message.data);
        if (document.activeElement !== sigmaSlider) {
          sigmaSlider.value = snapshot.sigma;
          sigmaLabel.textContent = Number(snapshot.sigma).toFixed(1);
        }
        if (document.activeElement !== thresholdSlider) {
          thresholdSlider.value = snapshot.trigger_threshold;
          thresholdLabel.textContent = snapshot.trigger_threshold;
        }
        if (snapshot.jets.length && !snapshot.jets.find((j) => j.hex === selectedHex)) {
          selectedHex = snapshot.jets[0].hex;
        }
        render();
        handleEvents(snapshot.events || []);
        if (snapshot.alarm_active) startSiren(); else stopSiren();
      };
      source.onerror = () => {
        const banner = document.getElementById("status-banner");
        banner.className = "error";
        banner.style.display = "block";
        banner.textContent = "Lost connection to the radar feed — reconnecting…";
        source.close();
        setTimeout(connectEvents, 2000);
      };
    }

    connectEvents();

    function handleEvents(events) {
      const banner = document.getElementById("alarm-banner");
      let latestAlarm = null;
      for (const event of events.slice(-24)) {
        const key = `${event.at}:${event.type}:${event.hex}`;
        if (notifiedEvents.has(key)) continue;
        notifiedEvents.add(key);
        if (event.type === "strange-event-alarm") {
          latestAlarm = event;
          if ("Notification" in window && Notification.permission === "granted") {
            new Notification("STRANGE EVENT: unusual private-jet movement", { body: event.message });
          }
        }
      }
      if (snapshot.alarm_active) {
        banner.style.display = "block";
        const last = [...(snapshot.events || [])].reverse().find((e) => e.type === "strange-event-alarm");
        banner.textContent = `STRANGE EVENT IN PROGRESS  ·  ${(last || latestAlarm || {}).message || "Unusual jet movement detected"}`;
      } else {
        banner.style.display = "none";
      }
    }

    function startSiren() {
      if (!soundOn || !audioCtx || sirenTimer) return;
      const blast = () => {
        const osc = audioCtx.createOscillator();
        const gain = audioCtx.createGain();
        osc.type = "sawtooth";
        osc.frequency.setValueAtTime(620, audioCtx.currentTime);
        osc.frequency.linearRampToValueAtTime(980, audioCtx.currentTime + 0.4);
        gain.gain.value = 0.06;
        osc.connect(gain).connect(audioCtx.destination);
        osc.start();
        osc.stop(audioCtx.currentTime + 0.45);
      };
      blast();
      sirenTimer = setInterval(blast, 1200);
    }

    function stopSiren() {
      if (sirenTimer) { clearInterval(sirenTimer); sirenTimer = null; }
    }

    function render() {
      if (!snapshot) return;
      const statusBanner = document.getElementById("status-banner");
      if (snapshot.awaiting_first_poll) {
        statusBanner.className = "";
        statusBanner.style.display = "block";
        statusBanner.textContent = snapshot.scan_mode === "demo"
          ? "Starting demo radar…"
          : "Polling live ADS-B from adsb.lol — first update can take up to 60 seconds.";
      } else if (statusBanner.className !== "error") {
        statusBanner.style.display = "none";
      }
      document.getElementById("counts").innerHTML =
        `<b>${snapshot.airborne_count}</b> jets · <b>${snapshot.watched_count || 0}</b> watched · ` +
        `<b>${snapshot.tanker_count || 0}</b> tankers · <b>${snapshot.dark_count}</b> dark · ` +
        `<b>${snapshot.recent_triggers}</b> triggers` +
        (snapshot.alarm_active ? ' · <b style="color:#f87171">ALARM</b>' : "");
      document.getElementById("updated").textContent = `Updated ${snapshot.generated_at}`;
      const baseline = snapshot.baseline || {};
      document.getElementById("baseline-chip").innerHTML = baseline.ready
        ? `Baseline: <b>${baseline.airborne_mean}</b> jets ± ${baseline.airborne_std} (${baseline.samples} samples)`
        : `Baseline: learning… ${baseline.samples || 0} samples`;
      renderJets();
      drawMap(snapshot.jets);
      drawVolumeGraph(snapshot.history || [], baseline);
      renderPosture();
      renderHideouts();
      renderEvents();
    }

    function renderJets() {
      const root = document.getElementById("jets");
      if (!snapshot.jets.length) {
        root.className = "jet-list empty";
        root.textContent = "No business jets observed yet.";
        return;
      }
      root.className = "jet-list";
      root.innerHTML = snapshot.jets.slice(0, 140).map((jet) => {
        const badges = [];
        if (!jet.present) badges.push('<span class="badge gone">left coverage</span>');
        else {
          if (jet.watched_label) badges.push('<span class="badge watched">watchlist</span>');
          if (jet.is_tanker) badges.push('<span class="badge tanker">tanker</span>');
          if (jet.emergency_squawk) badges.push(`<span class="badge emergency">SQUAWK ${escapeHtml(jet.squawk)}</span>`);
          if (jet.dark) badges.push('<span class="badge dark">dark</span>');
          if (jet.posture === "sitting-still") badges.push('<span class="badge still">sit still</span>');
          if (jet.posture === "on-the-move") badges.push('<span class="badge move">on the move</span>');
          if (jet.seen_count <= 3 && !jet.is_tanker) badges.push('<span class="badge new">new</span>');
          if (jet.airborne && !jet.emergency_squawk && !jet.dark && !jet.watched_label && jet.seen_count > 3)
            badges.push('<span class="badge airborne">airborne</span>');
        }
        return `
          <div class="jet ${jet.hex === selectedHex ? "active" : ""} ${jet.emergency_squawk && jet.present ? "emergency" : ""} ${jet.watched_label ? "watched" : ""}" data-hex="${escapeHtml(jet.hex)}">
            <div class="jet-title">
              <div>
                <div class="name">${escapeHtml(jet.identity)}</div>
                <div class="addr">${escapeHtml(jet.hex)}${jet.type ? " · " + escapeHtml(jet.type) : ""}${jet.registration && jet.registration !== jet.callsign ? " · " + escapeHtml(jet.registration) : ""}</div>
              </div>
              <div>${badges.join(" ")}</div>
            </div>
            <div class="meta-row">
              <span>${jet.altitude_ft != null ? "FL" + String(Math.round(jet.altitude_ft / 100)).padStart(3, "0") : (jet.on_ground ? "on ground" : "alt ?")}</span>
              <span>${jet.ground_speed_kt != null ? Math.round(jet.ground_speed_kt) + " kt" : ""}</span>
              <span>squawk ${escapeHtml(jet.squawk || "?")}</span>
              <span>${escapeHtml(jet.posture || "")}</span>
            </div>
          </div>`;
      }).join("");
      root.querySelectorAll(".jet").forEach((node) => {
        node.onclick = () => { selectedHex = node.dataset.hex; render(); };
      });
    }

    function renderPosture() {
      const root = document.getElementById("posture");
      const summary = snapshot.posture_summary || {};
      const keys = Object.keys(summary);
      if (!keys.length) {
        root.className = "muted";
        root.textContent = "No watched aircraft yet.";
      } else {
        root.className = "";
        root.innerHTML = keys.map((key) =>
          `<div class="move-row"><b>${escapeHtml(key)}</b>: ${summary[key].map(escapeHtml).join("; ")}</div>`
        ).join("");
      }
      const moves = document.getElementById("watch-moves");
      const rows = (snapshot.watchlist_moves || []).slice(-8).reverse();
      moves.innerHTML = rows.map((m) =>
        `<div class="move-row">${escapeHtml(m.at)} · <b>${escapeHtml(m.identity)}</b> · ${escapeHtml(m.action)}</div>`
      ).join("");
    }

    function renderHideouts() {
      const root = document.getElementById("hideouts");
      const rows = snapshot.hideout_candidates || [];
      if (!rows.length) {
        root.className = "muted";
        root.textContent = "No privacy landings scored yet.";
        return;
      }
      root.className = "";
      root.innerHTML = rows.map((h) =>
        `<div class="hideout"><b>${escapeHtml(h.name)}</b> · ${h.hits} quiet event${h.hits === 1 ? "" : "s"}<div class="muted">${escapeHtml(h.notes || "")}</div></div>`
      ).join("");
    }

    function drawMap(jets) {
      const canvas = document.getElementById("jet-map");
      const ctx = canvas.getContext("2d");
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      const plotted = jets.filter((j) => j.present && j.lat != null && j.lon != null);
      const bounds = mapBounds(plotted);

      ctx.strokeStyle = "#1c2942";
      ctx.lineWidth = 1;
      for (let i = 1; i < 6; i++) {
        const x = (canvas.width / 6) * i;
        const y = (canvas.height / 6) * i;
        ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, canvas.height); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(canvas.width, y); ctx.stroke();
      }
      ctx.fillStyle = "#93a1ba";
      ctx.font = "11px sans-serif";
      ctx.fillText(`lon ${bounds.minLon.toFixed(0)}° … ${bounds.maxLon.toFixed(0)}°`, 8, canvas.height - 8);
      ctx.fillText(`lat ${bounds.minLat.toFixed(0)}° … ${bounds.maxLat.toFixed(0)}°`, 8, 16);

      if (!plotted.length) {
        ctx.fillText("No positioned jets yet", canvas.width / 2 - 60, canvas.height / 2);
        return;
      }

      for (const jet of plotted) {
        const x = 24 + ((jet.lon - bounds.minLon) / (bounds.maxLon - bounds.minLon)) * (canvas.width - 48);
        const y = 24 + ((bounds.maxLat - jet.lat) / (bounds.maxLat - bounds.minLat)) * (canvas.height - 48);
        let color = "#22c55e";
        if (jet.dark) color = "#eab308";
        if (jet.is_tanker) color = "#f59e0b";
        if (jet.watched_label) color = "#a78bfa";
        if (jet.emergency_squawk) color = "#ef4444";
        if (jet.hex === selectedHex) color = "#38bdf8";
        drawPlane(ctx, x, y, ((jet.track_deg || 0) - 90) * Math.PI / 180, color);
        if (jet.emergency_squawk || jet.is_tanker) {
          ctx.strokeStyle = color;
          ctx.lineWidth = 2;
          ctx.beginPath();
          ctx.arc(x, y, 13, 0, Math.PI * 2);
          ctx.stroke();
        }
        ctx.fillStyle = "#e9eefb";
        ctx.font = "11px sans-serif";
        ctx.fillText(jet.identity.length > 28 ? jet.identity.slice(0, 27) + "…" : jet.identity, x + 10, y - 8);
      }
    }

    function drawPlane(ctx, x, y, angle, color) {
      ctx.save();
      ctx.translate(x, y);
      ctx.rotate(angle);
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.moveTo(8, 0);
      ctx.lineTo(-6, -5);
      ctx.lineTo(-3, 0);
      ctx.lineTo(-6, 5);
      ctx.closePath();
      ctx.fill();
      ctx.restore();
    }

    function mapBounds(jets) {
      if (!jets.length) return { minLat: 15, maxLat: 55, minLon: -160, maxLon: -60 };
      let minLat = Math.min(...jets.map((j) => j.lat));
      let maxLat = Math.max(...jets.map((j) => j.lat));
      let minLon = Math.min(...jets.map((j) => j.lon));
      let maxLon = Math.max(...jets.map((j) => j.lon));
      const padLat = Math.max((maxLat - minLat) * 0.15, 2);
      const padLon = Math.max((maxLon - minLon) * 0.15, 2);
      return { minLat: minLat - padLat, maxLat: maxLat + padLat, minLon: minLon - padLon, maxLon: maxLon + padLon };
    }

    function drawVolumeGraph(history, baseline) {
      const canvas = document.getElementById("volume-graph");
      const ctx = canvas.getContext("2d");
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      const left = 44, right = canvas.width - 12, top = 16, bottom = canvas.height - 26;
      if (!history.length) {
        ctx.fillStyle = "#93a1ba";
        ctx.font = "12px sans-serif";
        ctx.fillText("Collecting movement history…", left, canvas.height / 2);
        return;
      }
      const maxVal = Math.max(...history.map((h) => h.airborne), baseline.airborne_mean || 0, 4) * 1.15;
      const xStep = (right - left) / Math.max(history.length - 1, 1);
      const yFor = (value) => bottom - (value / maxVal) * (bottom - top);

      ctx.strokeStyle = "#1c2942";
      ctx.fillStyle = "#93a1ba";
      ctx.font = "11px sans-serif";
      for (let i = 0; i <= 4; i++) {
        const value = (maxVal / 4) * i;
        const y = yFor(value);
        ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(right, y); ctx.stroke();
        ctx.fillText(String(Math.round(value)), 10, y + 4);
      }

      ctx.fillStyle = "rgba(239,68,68,0.12)";
      history.forEach((h, i) => {
        if (h.alarm) ctx.fillRect(left + i * xStep - xStep / 2, top, xStep, bottom - top);
      });

      if (baseline.ready && baseline.airborne_mean != null) {
        ctx.strokeStyle = "#93a1ba";
        ctx.setLineDash([6, 5]);
        ctx.lineWidth = 1.5;
        const y = yFor(baseline.airborne_mean);
        ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(right, y); ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = "#93a1ba";
        ctx.fillText(`baseline ${baseline.airborne_mean}`, right - 96, y - 6);
      }

      ctx.strokeStyle = "#38bdf8";
      ctx.lineWidth = 2.5;
      ctx.beginPath();
      history.forEach((h, i) => {
        const x = left + i * xStep;
        const y = yFor(h.airborne);
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      ctx.stroke();

      ctx.fillStyle = "#f59e0b";
      history.forEach((h, i) => {
        if (h.triggers > 0) {
          const x = left + i * xStep;
          ctx.beginPath();
          ctx.arc(x, yFor(h.airborne) - 8, 3.5, 0, Math.PI * 2);
          ctx.fill();
        }
      });
    }

    function renderEvents() {
      const root = document.getElementById("events");
      const events = (snapshot.events || []).slice(-50).reverse();
      root.innerHTML = events.map((event) => {
        let cls = "";
        if (event.type === "strange-event-alarm") cls = "alarm-line";
        else if (String(event.type).startsWith("trigger:") || event.type === "took-off") cls = "trigger-line";
        return `<div class="${cls}">${escapeHtml(event.at)} · ${escapeHtml(event.type)} · ${escapeHtml(event.identity)} · ${escapeHtml(event.message)}</div>`;
      }).join("");
    }

    function escapeHtml(value) {
      return String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
    }
  </script>
</body>
</html>
"""
