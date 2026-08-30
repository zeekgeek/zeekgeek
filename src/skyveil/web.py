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
<meta name="viewport" content="width=device-width, initial-scale=1">
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
  }
  * { box-sizing: border-box; }
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

  #alarm-banner {
    display: none; position: absolute; top: 58px; left: 50%; transform: translateX(-50%); z-index: 6;
    background: rgba(239,68,68,.16); border: 1px solid var(--red); color: #fecaca;
    padding: 8px 18px; border-radius: 999px; font-weight: 700; font-size: 13px;
    box-shadow: 0 8px 30px rgba(239,68,68,.25); animation: pulse 1.4s infinite;
  }
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

  @media (max-width: 900px) {
    aside { position: static; width: auto; height: 46vh; padding: 8px; }
    body { overflow: auto; }
    #map { position: fixed; inset: 0 0 46vh 0; }
    .radar-hud { display: none; }
  }
</style>
</head>
<body>
  <div id="map"></div>
  <button id="reset-view">Recenter</button>
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

  <div id="alarm-banner"></div>

  <aside>
    <section class="panel" style="flex: 1;">
      <div class="panel-head">
        <h2>Strange detections</h2>
        <span class="count" id="detection-count">0</span>
      </div>
      <div id="detections"></div>
      <button id="activity-toggle">show activity log</button>
      <div id="activity"></div>
    </section>
  </aside>

  <div class="legend">
    <span class="l-routine">Routine</span>
    <span class="l-emergency">Emergency</span>
    <span class="l-experimental">Experimental / test</span>
    <span class="l-cloaked">Cloaked / mislabeled</span>
    <span class="l-erratic">Erratic movement</span>
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
    id: "flights-icons", type: "symbol", source: "flights",
    layout: {
      "icon-image": "plane",
      "icon-size": ["interpolate", ["linear"], ["zoom"], 3, 0.35, 8, 0.75],
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
  const bounds = new maplibregl.LngLatBounds();
  positioned.forEach((f) => bounds.extend([f.lon, f.lat]));
  map.fitBounds(bounds, { padding: 90, maxZoom: 7, duration: force ? 900 : 0 });
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
  renderDetections();
  renderActivity();
}

function renderStats() {
  document.getElementById("mode-note").textContent =
    `Live · updated ${snapshot.generated_at.replace("T", " ")}`;
  const c = snapshot.category_counts || {};
  const stats = [
    `<span class="stat"><b>${snapshot.tracked_count}</b> tracked</span>`,
    `<span class="stat"><b>${snapshot.airborne_count}</b> airborne</span>`,
    `<span class="stat emergency"><b>${c.emergency || 0}</b> emergency</span>`,
    `<span class="stat experimental"><b>${c.experimental || 0}</b> experimental</span>`,
    `<span class="stat cloaked"><b>${c.cloaked || 0}</b> cloaked</span>`,
    `<span class="stat erratic"><b>${c.erratic || 0}</b> erratic</span>`,
  ];
  document.getElementById("stats").innerHTML = stats.join("");
  document.getElementById("detection-count").textContent = snapshot.detection_count;

  const banner = document.getElementById("alarm-banner");
  const emergencyDetections = (snapshot.detections || []).filter((d) => d.dominant_category === "emergency");
  if (emergencyDetections.length) {
    banner.style.display = "block";
    banner.textContent = `EMERGENCY: ${emergencyDetections.map((d) => d.identity).join(", ")}`;
  } else {
    banner.style.display = "none";
  }
}

function renderMapLayers() {
  if (!mapReady) return;
  // Ascending score so flagged/high-severity aircraft paint last (on top) —
  // the flights array itself is sorted score-descending for the list panel.
  const positioned = snapshot.flights
    .filter((f) => f.present && f.lat != null && f.lon != null)
    .slice()
    .sort((a, b) => a.score - b.score);

  const flightFeatures = positioned.map((f) => {
    const color = colorFor(f);
    const flagged = f.score >= snapshot.detection_threshold;
    return {
      type: "Feature",
      properties: {
        hex: f.hex, color, flagged, track: f.track_deg || 0, score: f.score,
        label: f.identity + (flagged ? `  ·  ${Math.round(f.score)}` : ""),
      },
      geometry: { type: "Point", coordinates: [f.lon, f.lat] },
    };
  });
  map.getSource("flights").setData({ type: "FeatureCollection", features: flightFeatures });

  const pillarFeatures = positioned.map((f) => {
    const color = colorFor(f);
    const flagged = f.score >= snapshot.detection_threshold;
    const altM = f.altitude_ft != null ? Math.max(f.altitude_ft * 0.3048, 60) : 60;
    return {
      type: "Feature",
      properties: { color: withAlpha(color, flagged ? 0.85 : 0.4), height: altM },
      geometry: { type: "Polygon", coordinates: [squarePolygon(f.lat, f.lon, flagged ? 2600 : 1500)] },
    };
  });
  map.getSource("pillars").setData({ type: "FeatureCollection", features: pillarFeatures });

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
          ${otherCats.map((c) => `<span class="chip">${CATEGORY_LABEL[c] || c}</span>`).join("")}
        </div>
      </div>`;
  }).join("");
  root.querySelectorAll(".card").forEach((node) => {
    node.onclick = () => {
      selectedHex = node.dataset.hex;
      userMovedMap = true;
      const flight = snapshot.flights.find((f) => f.hex === selectedHex);
      if (flight && flight.lat != null && flight.lon != null) {
        map.flyTo({ center: [flight.lon, flight.lat], zoom: Math.max(map.getZoom(), 7), duration: 900 });
      }
      render();
    };
  });
}

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
