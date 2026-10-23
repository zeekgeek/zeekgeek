"""FastAPI dashboard for SkyVeil."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import asdict

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from .reference import TEST_RANGES
from .state import SkyState


def create_app(state: SkyState) -> FastAPI:
    app = FastAPI(title="SkyVeil Flight Anomaly Radar")

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return DASHBOARD_HTML

    @app.get("/api/flights")
    async def flights() -> dict:
        return await state.snapshot()

    @app.get("/api/reference")
    async def reference() -> JSONResponse:
        return JSONResponse({"test_ranges": [asdict(r) for r in TEST_RANGES]})

    @app.get("/api/events")
    async def events() -> StreamingResponse:
        return StreamingResponse(_event_stream(state), media_type="text/event-stream")

    return app


async def _event_stream(state: SkyState) -> AsyncIterator[str]:
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
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#05070c">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="SkyVeil">
<title>SkyVeil — Flight Anomaly Radar</title>
<link href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css" rel="stylesheet">
<script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
<style>
  :root {
    color-scheme: dark;
    --bg: #05070c;
    --panel: rgba(11, 16, 26, 0.88);
    --panel-2: rgba(20, 27, 43, 0.9);
    --line: #1d2740;
    --text: #e7ecf9;
    --muted: #8a97b3;
    --cyan: #22d3ee;
    --red: #ef4444;
    --violet: #a78bfa;
    --pink: #f472b6;
    --amber: #f59e0b;
    --green: #34d399;
    --mil: #a3e635;
  }
  * { box-sizing: border-box; }
  [hidden] { display: none !important; }
  html, body { margin: 0; height: 100%; background: var(--bg); color: var(--text); font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif; overflow: hidden; }
  #map { position: absolute; inset: 0; }
  #map .maplibregl-ctrl-logo { display: none; }

  header {
    position: absolute; top: 0; left: 0; right: 0; z-index: 5;
    display: flex; justify-content: space-between; align-items: center; gap: 16px;
    padding: 12px 18px; background: linear-gradient(180deg, rgba(5,7,12,.92), rgba(5,7,12,0));
    pointer-events: none;
  }
  header * { pointer-events: auto; }
  .brand { display: flex; align-items: baseline; gap: 10px; }
  .brand .dot { width: 10px; height: 10px; border-radius: 50%; background: var(--cyan); box-shadow: 0 0 10px var(--cyan); animation: blink 2.2s infinite; }
  @keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: .35; } }
  h1 { font-size: 17px; margin: 0; letter-spacing: .02em; }
  .sub { font-size: 12px; color: var(--muted); }
  .stat-strip { display: flex; gap: 8px; flex-wrap: wrap; }
  .stat {
    background: var(--panel-2); border: 1px solid var(--line); border-radius: 10px;
    padding: 6px 11px; font-size: 12px; color: var(--muted); white-space: nowrap;
  }
  .stat b { color: var(--text); font-size: 13px; }
  .stat.emergency b { color: var(--red); }
  .stat.experimental b { color: var(--violet); }
  .stat.cloaked b { color: var(--pink); }
  .stat.erratic b { color: var(--amber); }
  .stat.military b { color: var(--mil); }
  .stat.emergency.live { border-color: var(--red); background: rgba(239,68,68,.16); animation: pulse 1.4s infinite; }

  #alarm-banner {
    display: none; position: absolute; top: 58px; left: 50%; transform: translateX(-50%); z-index: 6;
    background: rgba(239,68,68,.16); border: 1px solid var(--red); color: #fecaca;
    padding: 8px 18px; border-radius: 999px; font-weight: 700; font-size: 13px;
    box-shadow: 0 8px 30px rgba(239,68,68,.25); animation: pulse 1.4s infinite;
    cursor: pointer; max-width: calc(100% - 820px); min-width: 220px; text-align: center;
  }
  #alarm-banner:hover { background: rgba(239,68,68,.28); }

  .filter-bar {
    position: absolute; left: 110px; top: 68px; z-index: 5; display: flex; gap: 4px;
    background: var(--panel-2); border: 1px solid var(--line); border-radius: 9px; padding: 3px;
  }
  .filter-bar button {
    background: none; border: 0; color: var(--muted); font: inherit; font-size: 12px;
    padding: 4px 10px; border-radius: 6px; cursor: pointer;
  }
  .filter-bar button[aria-pressed="true"] { background: rgba(255,255,255,.1); color: var(--text); }
  .filter-bar button:focus-visible, #reset-view:focus-visible, #alarm-banner:focus-visible { outline: 2px solid var(--cyan); outline-offset: 2px; }
  .filter-bar .f-mil[aria-pressed="true"] { color: var(--mil); }
  .filter-bar .f-emg[aria-pressed="true"] { color: #fca5a5; }

  .emergency-panel { border-color: rgba(239,68,68,.6); box-shadow: 0 0 0 1px rgba(239,68,68,.25), 0 20px 50px rgba(0,0,0,.45); }
  .emergency-panel .panel-head h2 { color: #fca5a5; }
  .emergency-panel .list { padding: 0 10px 10px; display: flex; flex-direction: column; gap: 8px; }
  .emg-card {
    border: 1px solid rgba(239,68,68,.55); border-radius: 10px; padding: 9px 11px; cursor: pointer;
    background: linear-gradient(90deg, rgba(239,68,68,.22), rgba(239,68,68,.06));
  }
  .emg-card:hover { background: rgba(239,68,68,.28); }
  .emg-card .code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-weight: 800; color: #fecaca; }
  .emg-card .what { font-size: 12px; color: #fecaca; margin-top: 4px; }

  #military-panel { max-height: 30%; min-height: 0; }
  #military-list { overflow: auto; padding: 0 10px 10px; }
  .mil-row {
    display: grid; grid-template-columns: 1fr auto auto; gap: 10px; align-items: baseline;
    padding: 6px 4px; border-top: 1px dashed var(--line); font-size: 12px; cursor: pointer;
  }
  .mil-row:hover { background: rgba(163,230,53,.06); }
  .mil-row .id { color: var(--mil); font-weight: 700; }
  .mil-row .t, .mil-row .alt { color: var(--muted); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; }
  .chip.mil { color: var(--mil); background: rgba(163,230,53,.12); }
  @keyframes pulse { 0%, 100% { box-shadow: 0 0 0 0 rgba(239,68,68,.35); } 50% { box-shadow: 0 0 0 9px rgba(239,68,68,0); } }

  aside {
    position: absolute; top: 0; right: 0; bottom: 0; width: 380px; z-index: 5;
    padding: 68px 12px 12px 0; display: flex; flex-direction: column; gap: 10px;
  }
  .panel {
    background: var(--panel); border: 1px solid var(--line); border-radius: 14px;
    backdrop-filter: blur(10px); box-shadow: 0 20px 50px rgba(0,0,0,.45);
    overflow: hidden; display: flex; flex-direction: column;
  }
  .panel-head { padding: 12px 14px 8px; display: flex; justify-content: space-between; align-items: center; }
  .panel-head h2 { margin: 0; font-size: 14px; }
  .panel-head .count { font-size: 12px; color: var(--muted); }
  #detections { flex: 1; overflow: auto; padding: 0 10px 10px; }
  .empty { color: var(--muted); font-size: 13px; text-align: center; padding: 30px 10px; }

  .card {
    border: 1px solid var(--line); border-left: 3px solid var(--cyan); border-radius: 10px;
    padding: 9px 11px; margin-bottom: 8px; background: var(--panel-2); cursor: pointer; transition: transform .12s ease;
  }
  .card:hover { transform: translateX(-2px); }
  .card.active { outline: 1px solid var(--text); }
  .card.cat-emergency { border-left-color: var(--red); }
  .card.cat-experimental { border-left-color: var(--violet); }
  .card.cat-cloaked { border-left-color: var(--pink); }
  .card.cat-erratic { border-left-color: var(--amber); }
  .card-top { display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; }
  .card-name { font-weight: 700; font-size: 13px; }
  .card-sub { font-size: 11px; color: var(--muted); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
  .score { border-radius: 999px; padding: 2px 9px; font-size: 12px; font-weight: 800; white-space: nowrap; }
  .score.cat-emergency { background: rgba(239,68,68,.18); color: #fca5a5; }
  .score.cat-experimental { background: rgba(167,139,250,.18); color: var(--violet); }
  .score.cat-cloaked { background: rgba(244,114,182,.18); color: var(--pink); }
  .score.cat-erratic { background: rgba(245,158,11,.18); color: var(--amber); }
  .card-msg { font-size: 12px; color: #cbd5f5; margin-top: 5px; line-height: 1.4; }
  .card-meta { display: flex; gap: 10px; flex-wrap: wrap; font-size: 11px; color: var(--muted); margin-top: 6px; }
  .chip { border-radius: 6px; padding: 1px 6px; font-size: 10px; background: rgba(255,255,255,.06); }

  #activity-toggle { font-size: 11px; color: var(--muted); background: none; border: 0; cursor: pointer; text-decoration: underline; padding: 0; }
  #activity { max-height: 140px; overflow: auto; font-size: 11px; color: var(--muted); padding: 0 14px 12px; display: none; }
  #activity .line { padding: 2px 0; border-top: 1px dashed var(--line); }

  .legend {
    position: absolute; left: 14px; bottom: 14px; z-index: 5;
    background: var(--panel); border: 1px solid var(--line); border-radius: 12px;
    padding: 10px 14px; font-size: 11px; color: var(--muted); backdrop-filter: blur(10px);
    display: flex; gap: 14px; flex-wrap: wrap; max-width: 460px;
  }
  .legend span::before { content: ""; display: inline-block; width: 9px; height: 9px; border-radius: 3px; margin-right: 6px; vertical-align: middle; }
  .legend .l-routine::before { background: var(--cyan); }
  .legend .l-emergency::before { background: var(--red); }
  .legend .l-experimental::before { background: var(--violet); }
  .legend .l-cloaked::before { background: var(--pink); }
  .legend .l-erratic::before { background: var(--amber); }
  .legend .l-military::before { background: transparent; border: 2px solid var(--mil); border-radius: 50%; width: 7px; height: 7px; }
  .legend .note { flex-basis: 100%; color: #5b6788; }

  .radar-hud {
    position: absolute; right: 396px; bottom: 14px; z-index: 5; width: 74px; height: 74px;
    border-radius: 50%; border: 1px solid var(--line); background: radial-gradient(circle, rgba(34,211,238,.08), transparent 70%);
    overflow: hidden; pointer-events: none;
  }
  .radar-hud::before {
    content: ""; position: absolute; inset: 0; border-radius: 50%;
    background: conic-gradient(from 0deg, rgba(34,211,238,.55), transparent 28%, transparent 100%);
    animation: spin 2.6s linear infinite;
  }
  .radar-hud::after { content: ""; position: absolute; inset: 30%; border-radius: 50%; border: 1px solid rgba(34,211,238,.35); }
  @keyframes spin { to { transform: rotate(360deg); } }

  #reset-view {
    position: absolute; left: 14px; top: 68px; z-index: 5; background: var(--panel-2);
    border: 1px solid var(--line); color: var(--text); border-radius: 9px; padding: 7px 11px;
    font-size: 12px; cursor: pointer;
  }

  #sheet-handle { display: none; }

  @media (max-width: 1300px) {
    #alarm-banner { top: 104px; max-width: calc(100% - 420px); }
  }

  /* Tablet and narrow desktop windows: panel stacks under the map. */
  @media (max-width: 900px) and (min-width: 601px) {
    #alarm-banner { max-width: calc(100% - 32px); }
    aside { position: static; width: auto; height: 46vh; padding: 8px; }
    body { overflow: auto; }
    #map { position: fixed; inset: 0 0 46vh 0; }
    .radar-hud { display: none; }
  }

  /* Phones (iPhone 13 Pro Max is 428x926 CSS px): full-screen map, scrolling
     stat chips, and the detections list as a draggable-style bottom sheet. */
  @media (max-width: 600px) {
    html, body { overscroll-behavior: none; -webkit-text-size-adjust: 100%; touch-action: manipulation; }
    header {
      flex-direction: column; align-items: stretch; gap: 8px;
      padding: calc(env(safe-area-inset-top) + 8px) 12px 6px;
    }
    h1 { font-size: 16px; }
    .stat-strip {
      flex-wrap: nowrap; overflow-x: auto; -webkit-overflow-scrolling: touch;
      scrollbar-width: none; margin: 0 -12px; padding: 0 12px;
    }
    .stat-strip::-webkit-scrollbar { display: none; }
    .stat { flex: 0 0 auto; padding: 7px 12px; font-size: 12px; }
    #alarm-banner { top: calc(env(safe-area-inset-top) + 84px); max-width: calc(100vw - 24px); text-align: center; font-size: 12px; }
    #reset-view {
      left: 12px; top: calc(env(safe-area-inset-top) + 92px); min-height: 40px; padding: 8px 14px; font-size: 13px;
    }
    .filter-bar { left: 112px; top: calc(env(safe-area-inset-top) + 92px); }
    .filter-bar button { min-height: 32px; padding: 4px 9px; }
    #alarm-banner { top: calc(env(safe-area-inset-top) + 140px); }
    .emergency-panel { border-radius: 14px; margin: 0 8px; max-height: 40%; overflow: auto; }
    #military-panel { display: none; }
    aside.expanded #military-panel { display: flex; }
    .maplibregl-ctrl-top-right { top: calc(env(safe-area-inset-top) + 84px); }
    .maplibregl-ctrl-top-right .maplibregl-ctrl-group button { width: 38px; height: 38px; }
    .radar-hud, .legend { display: none; }
    aside {
      top: auto; left: 0; right: 0; bottom: 0; width: auto; height: 40vh; padding: 0;
      transition: height .25s ease;
    }
    aside.expanded { height: 82vh; }
    aside .panel {
      border-radius: 18px 18px 0 0; border-bottom: 0;
      padding-bottom: env(safe-area-inset-bottom);
    }
    #sheet-handle {
      display: block; width: 100%; height: 26px; border: 0; background: none; cursor: pointer; flex: none;
    }
    #sheet-handle::before {
      content: ""; display: block; width: 40px; height: 5px; margin: 10px auto 0;
      border-radius: 3px; background: #3a4766;
    }
    .panel-head { padding: 2px 14px 8px; }
    .panel-head h2 { font-size: 15px; }
    .card { padding: 11px 12px; }
    .card:hover { transform: none; }
    .card-name { font-size: 14px; }
    .card-msg { font-size: 13px; }
    #activity-toggle { min-height: 40px; font-size: 12px; }
  }
</style>
</head>
<body>
  <div id="map"></div>
  <button id="reset-view">Recenter</button>
  <div class="filter-bar" role="group" aria-label="Show on map">
    <button id="filter-all" data-filter="all" aria-pressed="true">All traffic</button>
    <button id="filter-mil" class="f-mil" data-filter="military" aria-pressed="false">Military</button>
    <button id="filter-emg" class="f-emg" data-filter="emergency" aria-pressed="false">Emergencies</button>
  </div>
  <div class="radar-hud"></div>

  <header>
    <div class="brand">
      <span class="dot"></span>
      <div>
        <h1>SkyVeil</h1>
        <div class="sub" id="mode-note">Connecting…</div>
      </div>
    </div>
    <div class="stat-strip" id="stats"></div>
  </header>

  <div id="alarm-banner" role="button" tabindex="0" title="Show emergencies on the map"></div>

  <aside>
    <section class="panel emergency-panel" id="emergency-panel" hidden>
      <div class="panel-head">
        <h2>Active emergencies</h2>
        <span class="count" id="emergency-count">0</span>
      </div>
      <div class="list" id="emergency-list"></div>
    </section>
    <section class="panel" style="flex: 1; min-height: 0;">
      <button id="sheet-handle" aria-label="Expand or collapse detections"></button>
      <div class="panel-head">
        <h2>Strange detections</h2>
        <span class="count" id="detection-count">0</span>
      </div>
      <div id="detections"></div>
      <button id="activity-toggle">show activity log</button>
      <div id="activity"></div>
    </section>
    <section class="panel" id="military-panel">
      <div class="panel-head">
        <h2>Military aircraft</h2>
        <span class="count" id="military-count">0</span>
      </div>
      <div id="military-list"></div>
    </section>
  </aside>

  <div class="legend">
    <span class="l-routine">Routine</span>
    <span class="l-emergency">Emergency</span>
    <span class="l-experimental">Experimental / test</span>
    <span class="l-cloaked">Cloaked / mislabeled</span>
    <span class="l-erratic">Erratic movement</span>
    <span class="l-military">Military (ringed)</span>
    <span class="note">Pillar height ≈ altitude. Public ADS-B only — a lead, never proof.</span>
  </div>

<script>
const CATEGORY_COLOR = {
  emergency: "#ef4444",
  experimental: "#a78bfa",
  cloaked: "#f472b6",
  erratic: "#f59e0b",
  routine: "#22d3ee",
};
const MILITARY_COLOR = "#a3e635";
const EMERGENCY_CODES = { "7500": "7500 · hijack", "7600": "7600 · radio failure", "7700": "7700 · emergency" };
let viewFilter = "all";

function isEmergency(f) { return (f.triggers || []).some((t) => t.category === "emergency"); }
function emergencyFlights() {
  return (snapshot ? snapshot.flights : []).filter((f) => f.present && isEmergency(f));
}
function militaryFlights() {
  return (snapshot ? snapshot.flights : []).filter((f) => f.present && f.is_mil);
}
function passesFilter(f) {
  if (viewFilter === "military") return f.is_mil;
  if (viewFilter === "emergency") return isEmergency(f);
  return true;
}
function focusFlight(hex) {
  selectedHex = hex;
  userMovedMap = true;
  const flight = snapshot && snapshot.flights.find((f) => f.hex === hex);
  if (flight && flight.lat != null && flight.lon != null) {
    map.flyTo({ center: [flight.lon, flight.lat], zoom: Math.max(map.getZoom(), 7), duration: 900 });
  }
  render();
}
function fitTo(flights) {
  const pts = flights.filter((f) => f.lat != null && f.lon != null);
  if (!pts.length) return;
  userMovedMap = true;
  if (pts.length === 1) { focusFlight(pts[0].hex); return; }
  const bounds = new maplibregl.LngLatBounds();
  pts.forEach((f) => bounds.extend([f.lon, f.lat]));
  map.fitBounds(bounds, { padding: 110, maxZoom: 7, duration: 900 });
}
const CATEGORY_LABEL = {
  emergency: "Emergency",
  experimental: "Experimental / test",
  cloaked: "Cloaked / mislabeled",
  erratic: "Erratic movement",
};

let snapshot = null;
let referenceData = null;
let selectedHex = null;
let mapReady = false;
let userMovedMap = false;
const notifiedEvents = new Set();

const map = new maplibregl.Map({
  container: "map",
  style: "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
  center: [-98.58, 39.83],
  zoom: 3.6,
  pitch: 58,
  bearing: -12,
  antialias: true,
});
map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-right");
map.on("dragstart", () => { userMovedMap = true; });
map.on("zoomstart", (e) => { if (e.originalEvent) userMovedMap = true; });

document.getElementById("reset-view").onclick = () => {
  userMovedMap = false;
  fitToFlights(true);
};

function planeIcon(size) {
  const canvas = document.createElement("canvas");
  canvas.width = size; canvas.height = size;
  const ctx = canvas.getContext("2d");
  ctx.translate(size / 2, size / 2);
  ctx.fillStyle = "#fff";
  ctx.beginPath();
  ctx.moveTo(0, -size * 0.44);
  ctx.lineTo(size * 0.30, size * 0.30);
  ctx.lineTo(size * 0.09, size * 0.18);
  ctx.lineTo(size * 0.09, size * 0.44);
  ctx.lineTo(-size * 0.09, size * 0.44);
  ctx.lineTo(-size * 0.09, size * 0.18);
  ctx.lineTo(-size * 0.30, size * 0.30);
  ctx.closePath();
  ctx.fill();
  return ctx.getImageData(0, 0, size, size);
}

map.on("load", () => {
  map.addImage("plane", planeIcon(64), { sdf: true });

  // Real elevation under the flat basemap so altitude pillars read against
  // actual ground. Free AWS Terrarium tiles; if they fail to load the map
  // simply stays flat.
  map.addSource("terrain-dem", {
    type: "raster-dem",
    encoding: "terrarium",
    tileSize: 256,
    maxzoom: 12,
    tiles: ["https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"],
    attribution: "Terrain: Mapzen / AWS Open Data",
  });
  map.setTerrain({ source: "terrain-dem", exaggeration: 1.6 });
  map.addLayer({
    id: "terrain-hillshade", type: "hillshade", source: "terrain-dem",
    paint: {
      "hillshade-shadow-color": "#000000",
      "hillshade-highlight-color": "#2a3a5a",
      "hillshade-accent-color": "#0b1020",
      "hillshade-exaggeration": 0.45,
    },
  });

  map.addSource("test-ranges", { type: "geojson", data: emptyFC() });
  map.addLayer({
    id: "test-ranges-fill", type: "fill", source: "test-ranges",
    paint: { "fill-color": "#a78bfa", "fill-opacity": 0.05 },
  });
  map.addLayer({
    id: "test-ranges-line", type: "line", source: "test-ranges",
    paint: { "line-color": "#a78bfa", "line-opacity": 0.35, "line-width": 1, "line-dasharray": [2, 2] },
  });

  map.addSource("trails", { type: "geojson", data: emptyFC() });
  map.addLayer({
    id: "trails-glow", type: "line", source: "trails",
    layout: { "line-cap": "round", "line-join": "round" },
    paint: {
      "line-color": ["get", "color"],
      "line-width": 5,
      "line-blur": 4,
      "line-opacity": 0.35,
    },
  });
  map.addLayer({
    id: "trails-core", type: "line", source: "trails",
    layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-color": ["get", "color"], "line-width": 1.4, "line-opacity": 0.85 },
  });

  map.addSource("pillars", { type: "geojson", data: emptyFC() });
  map.addLayer({
    id: "pillars-3d", type: "fill-extrusion", source: "pillars",
    paint: {
      // fill-extrusion-opacity is not a data-driven property in MapLibre, so
      // per-flight opacity is baked into the feature's own rgba color string.
      "fill-extrusion-color": ["get", "color"],
      "fill-extrusion-height": ["get", "height"],
      "fill-extrusion-base": 0,
      "fill-extrusion-opacity": 0.9,
    },
  });

  // Altitude profile walls under each trail, and a solid cap marking where
  // each aircraft actually is at altitude (symbols can only sit at ground level).
  map.addSource("curtains", { type: "geojson", data: emptyFC() });
  map.addLayer({
    id: "trail-curtains", type: "fill-extrusion", source: "curtains",
    paint: {
      "fill-extrusion-color": ["get", "color"],
      "fill-extrusion-height": ["get", "height"],
      "fill-extrusion-base": 0,
      "fill-extrusion-opacity": 0.55,
    },
  }, "pillars-3d");
  map.addSource("caps", { type: "geojson", data: emptyFC() });
  map.addLayer({
    id: "plane-caps", type: "fill-extrusion", source: "caps",
    paint: {
      "fill-extrusion-color": ["get", "color"],
      "fill-extrusion-height": ["get", "top"],
      "fill-extrusion-base": ["get", "base"],
      "fill-extrusion-opacity": 1,
    },
  });

  map.addSource("flights", { type: "geojson", data: emptyFC() });
  map.addLayer({
    id: "flights-halo", type: "circle", source: "flights",
    filter: ["==", ["get", "flagged"], true],
    paint: {
      "circle-radius": 14,
      "circle-color": ["get", "color"],
      "circle-opacity": 0.18,
      "circle-blur": 0.6,
    },
  });
  map.addLayer({
    id: "military-ring", type: "circle", source: "flights",
    filter: ["==", ["get", "mil"], true],
    paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 3, 9, 8, 15],
      "circle-color": "rgba(0,0,0,0)",
      "circle-stroke-color": MILITARY_COLOR,
      "circle-stroke-width": 1.6,
      "circle-stroke-opacity": 0.9,
      "circle-pitch-alignment": "map",
    },
  });
  map.addLayer({
    id: "emergency-pulse", type: "circle", source: "flights",
    filter: ["==", ["get", "emergency"], true],
    paint: {
      "circle-radius": 18,
      "circle-color": "#ef4444",
      "circle-opacity": 0.25,
      "circle-stroke-color": "#ef4444",
      "circle-stroke-width": 2,
      "circle-stroke-opacity": 0.9,
    },
  });
  map.addLayer({
    id: "flights-icons", type: "symbol", source: "flights",
    layout: {
      "icon-image": "plane",
      // "zoom" must be the top-level input, so the emergency enlargement
      // lives inside each stop's output rather than wrapping the interpolate.
      "icon-size": ["interpolate", ["linear"], ["zoom"],
        3, ["case", ["==", ["get", "emergency"], true], 0.6, 0.35],
        8, ["case", ["==", ["get", "emergency"], true], 1.2, 0.75]],
      "icon-rotate": ["get", "track"],
      "icon-rotation-alignment": "map",
      "icon-pitch-alignment": "viewport",
      "icon-allow-overlap": true,
      // Higher-severity flights draw and place last, so they win overlap
      // and label collisions against nearby routine traffic.
      "symbol-sort-key": ["get", "score"],
      "text-field": ["get", "label"],
      "text-font": ["Open Sans Regular"],
      "text-size": 11,
      "text-offset": [0, 1.1],
      "text-anchor": "top",
      "text-optional": true,
      "text-allow-overlap": false,
    },
    paint: {
      "icon-color": ["get", "color"],
      "text-color": "#dbe3f7",
      "text-halo-color": "#05070c",
      "text-halo-width": 1.2,
    },
  });

  map.on("click", "flights-icons", (e) => {
    const hex = e.features[0].properties.hex;
    selectedHex = hex;
    userMovedMap = true;
    render();
  });
  map.on("mouseenter", "flights-icons", () => { map.getCanvas().style.cursor = "pointer"; });
  map.on("mouseleave", "flights-icons", () => { map.getCanvas().style.cursor = ""; });

  // Pulse the emergency rings so they read as live alarms, not static dots.
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!reduceMotion) {
    const pulseStart = performance.now();
    const pulse = () => {
      // Repainting every frame costs GPU and battery, so idle when nothing is in distress.
      if (!emergencyFlights().length || document.hidden) { setTimeout(pulse, 1000); return; }
      const t = ((performance.now() - pulseStart) % 1600) / 1600;
      map.setPaintProperty("emergency-pulse", "circle-radius", 14 + t * 26);
      map.setPaintProperty("emergency-pulse", "circle-opacity", 0.35 * (1 - t));
      map.setPaintProperty("emergency-pulse", "circle-stroke-opacity", 0.95 * (1 - t));
      requestAnimationFrame(pulse);
    };
    requestAnimationFrame(pulse);
  }

  let zoomFrame = 0;
  map.on("zoom", () => {
    if (zoomFrame) return;
    zoomFrame = requestAnimationFrame(() => { zoomFrame = 0; if (snapshot) renderMapLayers(); });
  });

  mapReady = true;
  if (referenceData) drawTestRanges();
  if (snapshot) render();
});

function emptyFC() { return { type: "FeatureCollection", features: [] }; }

function drawTestRanges() {
  const features = referenceData.test_ranges.map((r) => ({
    type: "Feature",
    properties: { name: r.name },
    geometry: { type: "Polygon", coordinates: [circlePolygon(r.lat, r.lon, r.radius_nm)] },
  }));
  map.getSource("test-ranges").setData({ type: "FeatureCollection", features });
}

function circlePolygon(lat, lon, radiusNm, steps = 48) {
  const radiusM = radiusNm * 1852;
  const coords = [];
  for (let i = 0; i <= steps; i++) {
    const angle = (i / steps) * 2 * Math.PI;
    const dLat = (radiusM * Math.cos(angle)) / 110574;
    const dLon = (radiusM * Math.sin(angle)) / (111320 * Math.cos((lat * Math.PI) / 180) || 1);
    coords.push([lon + dLon, lat + dLat]);
  }
  return coords;
}

// True-scale altitude is invisible at regional zoom (a 36,000 ft jet is an
// 11 km column; at zoom 4 one pixel is ~30 km). Scale heights and footprints
// to screen pixels so the 3D view reads at every zoom, falling back to true
// scale once zoomed in far enough for it to be visible on its own.
const MAX_ALT_M = 16000;        // ~52,000 ft, top of the extrusion range
const MAX_COLUMN_PX = 160;      // tallest column, in screen pixels
function metersPerPixel() {
  const lat = map.getCenter().lat;
  return (78271.517 * Math.cos((lat * Math.PI) / 180)) / Math.pow(2, map.getZoom());
}
function verticalScale(mpp) { return Math.max(1, (MAX_COLUMN_PX * mpp) / MAX_ALT_M); }
function altitudeMeters(ft) { return ft != null ? Math.max(ft * 0.3048, 60) : 60; }

function ribbonPolygon(a, b, halfWidthM) {
  const midLat = ((a.lat + b.lat) / 2) * Math.PI / 180;
  const mx = 111320 * Math.cos(midLat) || 1, my = 110574;
  const dx = (b.lon - a.lon) * mx, dy = (b.lat - a.lat) * my;
  const len = Math.hypot(dx, dy);
  if (!len) return null;
  const ox = (-dy / len) * halfWidthM / mx, oy = (dx / len) * halfWidthM / my;
  return [
    [a.lon + ox, a.lat + oy], [b.lon + ox, b.lat + oy],
    [b.lon - ox, b.lat - oy], [a.lon - ox, a.lat - oy], [a.lon + ox, a.lat + oy],
  ];
}

function squarePolygon(lat, lon, halfWidthM) {
  const dLat = halfWidthM / 110574;
  const dLon = halfWidthM / (111320 * Math.cos((lat * Math.PI) / 180) || 1);
  return [
    [lon - dLon, lat - dLat],
    [lon + dLon, lat - dLat],
    [lon + dLon, lat + dLat],
    [lon - dLon, lat + dLat],
    [lon - dLon, lat - dLat],
  ];
}

function withAlpha(hexColor, alpha) {
  const hex = hexColor.replace("#", "");
  const r = parseInt(hex.substring(0, 2), 16);
  const g = parseInt(hex.substring(2, 4), 16);
  const b = parseInt(hex.substring(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function colorFor(flight) {
  if (flight.score >= (snapshot ? snapshot.detection_threshold : 30) && flight.dominant_category) {
    return CATEGORY_COLOR[flight.dominant_category] || CATEGORY_COLOR.routine;
  }
  if (isEmergency(flight)) return CATEGORY_COLOR.emergency;
  if (flight.is_mil) return MILITARY_COLOR;
  return CATEGORY_COLOR.routine;
}

async function fetchReference() {
  const res = await fetch("/api/reference");
  referenceData = await res.json();
  if (mapReady) drawTestRanges();
}

function fitToFlights(force) {
  if (!snapshot || !snapshot.flights.length || (userMovedMap && !force)) return;
  const positioned = snapshot.flights.filter((f) => f.present && f.lat != null && f.lon != null);
  if (!positioned.length) return;
  // The global PIA/LADD/military/emergency feeds drop far-off aircraft into
  // the pool; fitting to all of them zooms out to the whole planet. Fit to
  // the 85% of flights closest to the median instead.
  const median = (values) => values.slice().sort((a, b) => a - b)[Math.floor(values.length / 2)];
  const midLat = median(positioned.map((f) => f.lat));
  const midLon = median(positioned.map((f) => f.lon));
  const core = positioned
    .map((f) => ({ f, d: (f.lat - midLat) ** 2 + ((f.lon - midLon) * Math.cos((midLat * Math.PI) / 180)) ** 2 }))
    .sort((a, b) => a.d - b.d)
    .slice(0, Math.max(1, Math.ceil(positioned.length * 0.85)))
    .map((x) => x.f);
  const bounds = new maplibregl.LngLatBounds();
  core.forEach((f) => bounds.extend([f.lon, f.lat]));
  const phone = window.matchMedia("(max-width: 600px)").matches;
  const padding = phone
    ? { top: 130, bottom: Math.round(window.innerHeight * 0.4) + 20, left: 24, right: 24 }
    : 90;
  map.fitBounds(bounds, { padding, maxZoom: 7, duration: force ? 900 : 0 });
}

const source = new EventSource("/api/events");
source.onmessage = (message) => {
  const wasFirst = snapshot === null;
  snapshot = JSON.parse(message.data);
  render();
  handleEvents(snapshot.events || []);
  if (wasFirst) { fetchReference(); fitToFlights(true); }
};
source.onerror = () => {
  document.getElementById("mode-note").textContent = "Reconnecting…";
};

function render() {
  if (!snapshot) return;
  renderStats();
  renderMapLayers();
  renderEmergencies();
  renderDetections();
  renderMilitary();
  renderActivity();
}

function renderStats() {
  document.getElementById("mode-note").textContent =
    `Live · updated ${snapshot.generated_at.replace("T", " ")}`;
  const c = snapshot.category_counts || {};
  const emergencies = emergencyFlights();
  const militaryCount = snapshot.military_count != null ? snapshot.military_count : militaryFlights().length;
  const stats = [
    `<span class="stat"><b>${snapshot.tracked_count}</b> tracked</span>`,
    `<span class="stat"><b>${snapshot.airborne_count}</b> airborne</span>`,
    `<span class="stat military"><b>${militaryCount}</b> military</span>`,
    `<span class="stat emergency ${emergencies.length ? "live" : ""}"><b>${emergencies.length}</b> emergency</span>`,
    `<span class="stat experimental"><b>${c.experimental || 0}</b> experimental</span>`,
    `<span class="stat cloaked"><b>${c.cloaked || 0}</b> cloaked</span>`,
    `<span class="stat erratic"><b>${c.erratic || 0}</b> erratic</span>`,
  ];
  document.getElementById("stats").innerHTML = stats.join("");
  document.getElementById("detection-count").textContent = snapshot.detection_count;

  const banner = document.getElementById("alarm-banner");
  if (emergencies.length) {
    banner.style.display = "block";
    banner.textContent = `⚠ ${emergencies.length} EMERGENCY · ` + emergencies
      .map((f) => `${f.identity}${f.squawk && EMERGENCY_CODES[f.squawk] ? " (" + f.squawk + ")" : ""}`)
      .join(", ") + "  ›  show";
  } else {
    banner.style.display = "none";
  }
}

function renderEmergencies() {
  const panel = document.getElementById("emergency-panel");
  const rows = emergencyFlights();
  panel.hidden = !rows.length;
  document.getElementById("emergency-count").textContent = rows.length;
  const list = document.getElementById("emergency-list");
  list.innerHTML = rows.map((f) => {
    const what = (f.triggers || []).filter((t) => t.category === "emergency")
      .sort((a, b) => b.weight - a.weight)[0];
    const code = EMERGENCY_CODES[f.squawk] || (f.emergency_field ? f.emergency_field.toUpperCase() : "EMERGENCY");
    return `
      <div class="emg-card" role="button" tabindex="0" data-hex="${escapeHtml(f.hex)}">
        <div class="card-top">
          <div>
            <div class="card-name">${escapeHtml(f.identity)} ${f.is_mil ? '<span class="chip mil">MIL</span>' : ""}</div>
            <div class="card-sub">${escapeHtml(f.hex)}${f.type ? " · " + escapeHtml(f.type) : ""}</div>
          </div>
          <span class="code">${escapeHtml(code)}</span>
        </div>
        <div class="what">${escapeHtml(what ? what.message : "")}</div>
        <div class="card-meta">
          <span>${f.altitude_ft != null ? "FL" + String(Math.round(f.altitude_ft / 100)).padStart(3, "0") : (f.on_ground ? "on ground" : "alt ?")}</span>
          <span>${f.ground_speed_kt != null ? Math.round(f.ground_speed_kt) + " kt" : ""}</span>
          <span>${f.baro_rate_fpm != null ? Math.round(f.baro_rate_fpm) + " fpm" : ""}</span>
        </div>
      </div>`;
  }).join("");
  bindFocus(list, ".emg-card");
}

function renderMilitary() {
  const rows = militaryFlights().slice().sort((a, b) =>
    (isEmergency(b) - isEmergency(a)) || String(a.identity).localeCompare(String(b.identity)));
  document.getElementById("military-count").textContent = rows.length;
  const list = document.getElementById("military-list");
  if (!rows.length) {
    list.innerHTML = '<div class="empty">No military transponders in view right now.</div>';
    return;
  }
  list.innerHTML = rows.map((f) => `
    <div class="mil-row" role="button" tabindex="0" data-hex="${escapeHtml(f.hex)}">
      <span class="id">${isEmergency(f) ? "⚠ " : ""}${escapeHtml(f.identity)}</span>
      <span class="t">${escapeHtml(f.type || "?")}</span>
      <span class="alt">${f.altitude_ft != null ? "FL" + String(Math.round(f.altitude_ft / 100)).padStart(3, "0") : (f.on_ground ? "GND" : "—")}</span>
    </div>`).join("");
  bindFocus(list, ".mil-row");
}

function bindFocus(root, selector) {
  root.querySelectorAll(selector).forEach((node) => {
    node.onclick = () => focusFlight(node.dataset.hex);
    node.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); focusFlight(node.dataset.hex); } };
  });
}

document.querySelectorAll(".filter-bar button").forEach((btn) => {
  btn.onclick = () => {
    viewFilter = btn.dataset.filter;
    document.querySelectorAll(".filter-bar button").forEach((b) =>
      b.setAttribute("aria-pressed", String(b === btn)));
    render();
    if (viewFilter === "military") fitTo(militaryFlights());
    if (viewFilter === "emergency") fitTo(emergencyFlights());
  };
});

const alarmBanner = document.getElementById("alarm-banner");
const showEmergencies = () => document.getElementById("filter-emg").click();
alarmBanner.onclick = showEmergencies;
alarmBanner.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); showEmergencies(); } };

function renderMapLayers() {
  if (!mapReady) return;
  // Ascending score so flagged/high-severity aircraft paint last (on top) —
  // the flights array itself is sorted score-descending for the list panel.
  const positioned = snapshot.flights
    .filter((f) => f.present && f.lat != null && f.lon != null && passesFilter(f))
    .slice()
    .sort((a, b) => (isEmergency(a) - isEmergency(b)) || (a.score - b.score));

  const flightFeatures = positioned.map((f) => {
    const color = colorFor(f);
    const flagged = f.score >= snapshot.detection_threshold;
    return {
      type: "Feature",
      properties: {
        hex: f.hex, color, flagged, track: f.track_deg || 0,
        score: f.score + (isEmergency(f) ? 1000 : 0),
        mil: !!f.is_mil, emergency: isEmergency(f),
        label: (isEmergency(f) ? `⚠ ${f.identity}  ·  ${f.squawk || "EMERG"}`
          : f.identity + (flagged ? `  ·  ${Math.round(f.score)}` : "")),
      },
      geometry: { type: "Point", coordinates: [f.lon, f.lat] },
    };
  });
  map.getSource("flights").setData({ type: "FeatureCollection", features: flightFeatures });

  const mpp = metersPerPixel();
  const vScale = verticalScale(mpp);

  const pillarFeatures = [];
  const capFeatures = [];
  positioned.forEach((f) => {
    const color = colorFor(f);
    const flagged = f.score >= snapshot.detection_threshold;
    const height = altitudeMeters(f.altitude_ft) * vScale;
    const pillarHalf = Math.max(flagged ? 2600 : 1500, (flagged ? 2.6 : 1.6) * mpp);
    const capHalf = Math.max(flagged ? 5200 : 3000, (flagged ? 6 : 4) * mpp);
    pillarFeatures.push({
      type: "Feature",
      properties: { color: withAlpha(color, flagged ? 0.85 : 0.4), height },
      geometry: { type: "Polygon", coordinates: [squarePolygon(f.lat, f.lon, pillarHalf)] },
    });
    capFeatures.push({
      type: "Feature",
      properties: { color, base: height, top: height + Math.max(250, 4 * mpp) },
      geometry: { type: "Polygon", coordinates: [squarePolygon(f.lat, f.lon, capHalf)] },
    });
  });
  map.getSource("pillars").setData({ type: "FeatureCollection", features: pillarFeatures });
  map.getSource("caps").setData({ type: "FeatureCollection", features: capFeatures });

  const curtainFeatures = [];
  const curtainHalf = Math.max(400, 0.8 * mpp);
  positioned.forEach((f) => {
    const pts = (f.trail || []).filter((p) => p.lat != null && p.lon != null);
    const color = withAlpha(colorFor(f), 0.5);
    for (let i = 1; i < pts.length; i++) {
      const ring = ribbonPolygon(pts[i - 1], pts[i], curtainHalf);
      if (!ring) continue;
      const altFt = pts[i].alt != null ? pts[i].alt : f.altitude_ft;
      curtainFeatures.push({
        type: "Feature",
        properties: { color, height: altitudeMeters(altFt) * vScale },
        geometry: { type: "Polygon", coordinates: [ring] },
      });
    }
  });
  map.getSource("curtains").setData({ type: "FeatureCollection", features: curtainFeatures });

  const trailFeatures = positioned
    .filter((f) => f.trail && f.trail.length > 1)
    .map((f) => ({
      type: "Feature",
      properties: { color: colorFor(f) },
      geometry: { type: "LineString", coordinates: f.trail.map((p) => [p.lon, p.lat]) },
    }));
  map.getSource("trails").setData({ type: "FeatureCollection", features: trailFeatures });
}

function renderDetections() {
  const root = document.getElementById("detections");
  const scrollTop = root.scrollTop;
  const rows = snapshot.detections || [];
  if (!rows.length) {
    root.innerHTML = '<div class="empty">No anomalies detected. Tracking normally.</div>';
    return;
  }
  root.innerHTML = rows.map((f) => {
    const cat = f.dominant_category || "erratic";
    const top = (f.triggers || []).slice().sort((a, b) => b.weight - a.weight)[0];
    const otherCats = [...new Set((f.triggers || []).map((t) => t.category))].filter((c) => c !== cat);
    return `
      <div class="card cat-${cat} ${f.hex === selectedHex ? "active" : ""}" data-hex="${escapeHtml(f.hex)}">
        <div class="card-top">
          <div>
            <div class="card-name">${escapeHtml(f.identity)}</div>
            <div class="card-sub">${escapeHtml(f.hex)}${f.type ? " · " + escapeHtml(f.type) : ""}</div>
          </div>
          <span class="score cat-${cat}">${Math.round(f.score)}</span>
        </div>
        <div class="card-msg">${escapeHtml(top ? top.message : "")}</div>
        <div class="card-meta">
          <span>${f.altitude_ft != null ? "FL" + String(Math.round(f.altitude_ft / 100)).padStart(3, "0") : (f.on_ground ? "on ground" : "alt ?")}</span>
          <span>${f.ground_speed_kt != null ? Math.round(f.ground_speed_kt) + " kt" : ""}</span>
          <span>squawk ${escapeHtml(f.squawk || "?")}</span>
          ${f.is_mil ? '<span class="chip mil">Military</span>' : ""}
          ${otherCats.map((c) => `<span class="chip">${CATEGORY_LABEL[c] || c}</span>`).join("")}
        </div>
      </div>`;
  }).join("");
  root.scrollTop = scrollTop;
  root.querySelectorAll(".card").forEach((node) => {
    node.onclick = () => {
      selectedHex = node.dataset.hex;
      userMovedMap = true;
      const flight = snapshot.flights.find((f) => f.hex === selectedHex);
      const phone = window.matchMedia("(max-width: 600px)").matches;
      if (phone) sheet.classList.remove("expanded");
      if (flight && flight.lat != null && flight.lon != null) {
        map.flyTo({
          center: [flight.lon, flight.lat], zoom: Math.max(map.getZoom(), 7), duration: 900,
          // On a phone the bottom sheet covers the lower ~40% of the map.
          padding: phone ? { top: 120, bottom: Math.round(window.innerHeight * 0.4), left: 0, right: 0 } : undefined,
        });
      }
      render();
    };
  });
}

const sheet = document.querySelector("aside");
document.getElementById("sheet-handle").onclick = () => sheet.classList.toggle("expanded");

const activityToggle = document.getElementById("activity-toggle");
let activityOpen = false;
activityToggle.onclick = () => {
  activityOpen = !activityOpen;
  document.getElementById("activity").style.display = activityOpen ? "block" : "none";
  activityToggle.textContent = activityOpen ? "hide activity log" : "show activity log";
};

function renderActivity() {
  const root = document.getElementById("activity");
  const rows = (snapshot.events || []).slice(-40).reverse();
  root.innerHTML = rows.map((e) =>
    `<div class="line">${escapeHtml(e.at.split("T")[1] || e.at)} · ${escapeHtml(e.identity)} · ${escapeHtml(e.message)}</div>`
  ).join("");
}

function handleEvents(events) {
  if (!("Notification" in window)) return;
  for (const event of events.slice(-24)) {
    const key = `${event.at}:${event.type}:${event.hex}`;
    if (notifiedEvents.has(key)) continue;
    notifiedEvents.add(key);
    if (event.type && event.type.startsWith("detection-opened:emergency") && Notification.permission === "granted") {
      new Notification("SkyVeil: emergency detected", { body: event.message });
    }
  }
}

if ("Notification" in window && Notification.permission === "default") {
  window.addEventListener("click", () => Notification.requestPermission(), { once: true });
}

function escapeHtml(value) {
  return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
}
</script>
</body>
</html>
"""
