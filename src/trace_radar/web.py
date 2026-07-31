"""FastAPI dashboard for the visual 3D traceroute radar."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from .speedtest import run_speed_test
from .state import RadarState


class TraceRequest(BaseModel):
    target: str = Field(min_length=1, max_length=253)


def create_app(state: RadarState) -> FastAPI:
    app = FastAPI(title="Visual Trace Radar")

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return DASHBOARD_HTML

    @app.get("/api/state")
    async def api_state() -> dict:
        return await state.snapshot()

    @app.post("/api/trace")
    async def api_trace(request: TraceRequest) -> JSONResponse:
        target = request.target.strip()
        if not target:
            return JSONResponse({"ok": False, "error": "Empty target"}, status_code=400)
        created = await state.request_trace(target)
        return JSONResponse({"ok": True, "created": created, "target": target})

    @app.post("/api/speedtest")
    async def api_speedtest() -> JSONResponse:
        if await state.speedtest_running():
            return JSONResponse({"ok": False, "error": "Speed test already running"}, status_code=409)
        asyncio.create_task(run_speed_test(state), name="speedtest")
        return JSONResponse({"ok": True, "status": "started"})

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
  <title>Trace Radar — 3D Route Map</title>
  <style>
    :root {
      --bg0: #071018;
      --bg1: #0b1a28;
      --panel: rgba(10, 24, 38, 0.92);
      --line: #1d334a;
      --text: #e7f0f8;
      --muted: #8aa0b5;
      --cyan: #3ec7ff;
      --teal: #2dd4bf;
      --amber: #f5b942;
      --red: #f07178;
      --green: #4ade80;
      --violet: #a78bfa;
      --font-display: "Segoe UI", "Helvetica Neue", sans-serif;
      --font-mono: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      color: var(--text);
      font-family: var(--font-display);
      background:
        radial-gradient(1200px 700px at 15% -10%, rgba(62,199,255,.16), transparent 55%),
        radial-gradient(900px 600px at 90% 10%, rgba(45,212,191,.10), transparent 50%),
        linear-gradient(165deg, var(--bg0), #050d14 45%, var(--bg1));
    }
    header {
      display: flex; justify-content: space-between; gap: 16px; align-items: center; flex-wrap: wrap;
      padding: 16px 22px; border-bottom: 1px solid var(--line);
      background: rgba(5,12,20,.55); backdrop-filter: blur(8px);
    }
    h1 { margin: 0; font-size: 22px; letter-spacing: .02em; }
    h1 span { color: var(--cyan); font-weight: 800; }
    h2 { margin: 0 0 10px; font-size: 15px; letter-spacing: .04em; text-transform: uppercase; color: var(--muted); }
    .stats { display: flex; gap: 14px; flex-wrap: wrap; color: var(--muted); font-size: 13px; margin-top: 6px; }
    .stats b { color: var(--text); }
    .controls { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
    input[type=text] {
      background: #0a1622; border: 1px solid var(--line); color: var(--text);
      border-radius: 10px; padding: 9px 12px; min-width: 180px; font: inherit;
    }
    button {
      background: linear-gradient(180deg, #49d0ff, #1aa7d8);
      color: #041018; border: 0; border-radius: 10px; padding: 9px 13px;
      font-weight: 700; cursor: pointer;
    }
    button.secondary { background: #152738; color: var(--text); border: 1px solid var(--line); }
    button:disabled { opacity: .5; cursor: wait; }
    main {
      display: grid;
      grid-template-columns: minmax(340px, 420px) 1fr;
      gap: 14px; padding: 14px; align-items: start;
    }
    .panel {
      background: var(--panel); border: 1px solid var(--line); border-radius: 14px;
      padding: 13px; box-shadow: 0 18px 40px rgba(0,0,0,.28);
    }
    .stack { display: grid; gap: 14px; }
    #globe {
      width: 100%; height: min(62vh, 560px); display: block;
      border-radius: 12px; border: 1px solid var(--line); background: #02080f; cursor: grab;
      touch-action: none;
    }
    #globe:active { cursor: grabbing; }
    .legend { display: flex; gap: 14px; flex-wrap: wrap; font-size: 12px; color: var(--muted); margin-top: 8px; }
    .legend i { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 5px; }
    .route-tabs { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 10px; }
    .route-tabs button {
      background: #102033; color: var(--muted); border: 1px solid var(--line);
      border-radius: 999px; padding: 6px 10px; font-size: 12px; font-weight: 600;
    }
    .route-tabs button.active { color: #041018; background: var(--cyan); border-color: transparent; }
    .hop-table { width: 100%; border-collapse: collapse; font-size: 12px; }
    .hop-table th {
      text-align: left; color: var(--muted); font-weight: 600; padding: 6px 4px;
      border-bottom: 1px solid var(--line); position: sticky; top: 0; background: #0b1826;
    }
    .hop-table td { padding: 7px 4px; border-bottom: 1px solid rgba(29,51,74,.65); vertical-align: top; }
    .hop-table tr:hover { background: rgba(62,199,255,.06); }
    .hop-table tr.selected { background: rgba(62,199,255,.12); }
    .hop-table tr.lossy td.loss { color: var(--amber); font-weight: 700; }
    .hop-table tr.badloss td.loss { color: var(--red); font-weight: 800; }
    .mono { font-family: var(--font-mono); }
    .muted { color: var(--muted); }
    .place { color: var(--teal); }
    .whois-line { color: var(--violet); font-size: 11px; margin-top: 2px; }
    .detail {
      margin-top: 10px; padding: 10px; border-radius: 10px; border: 1px solid var(--line);
      background: #0a1622; font-size: 12px; line-height: 1.45;
    }
    .detail b { color: var(--text); }
    .kv { display: grid; grid-template-columns: 110px 1fr; gap: 4px 8px; }
    .kv span { color: var(--muted); }
    .gauges { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
    .gauge {
      border: 1px solid var(--line); border-radius: 12px; padding: 10px; background: #0a1622; text-align: center;
    }
    .gauge .label { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .05em; }
    .gauge .value { font-size: 22px; font-weight: 800; margin: 6px 0 2px; color: var(--cyan); }
    .gauge .unit { color: var(--muted); font-size: 11px; }
    .bar {
      height: 6px; border-radius: 999px; background: #132333; overflow: hidden; margin-top: 8px;
    }
    .bar > i { display: block; height: 100%; width: 0; background: linear-gradient(90deg, var(--teal), var(--cyan)); }
    .events { max-height: 180px; overflow: auto; font-size: 12px; color: var(--muted); }
    .events div { padding: 4px 0; border-bottom: 1px solid rgba(29,51,74,.5); }
    .events .whois { color: var(--violet); }
    .events .loss { color: var(--amber); }
    .hint { font-size: 11px; color: var(--muted); margin-top: 6px; }
    .hop-scroll { max-height: min(58vh, 520px); overflow: auto; }
    @media (max-width: 980px) {
      main { grid-template-columns: 1fr; }
      .gauges { grid-template-columns: repeat(2, 1fr); }
      #globe { height: 420px; }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1><span>Trace Radar</span> — 3D Internet Routes</h1>
      <div class="stats">
        <span id="counts">Waiting for traceroute…</span>
        <span id="updated"></span>
      </div>
    </div>
    <div class="controls">
      <input id="target-input" type="text" placeholder="host or IP to trace" value="cloudflare.com">
      <button id="trace-btn">Trace route</button>
      <button id="speed-btn" class="secondary">Run speed test</button>
    </div>
  </header>

  <main>
    <section class="stack">
      <section class="panel">
        <h2>Connection quality</h2>
        <div class="gauges">
          <div class="gauge"><div class="label">Latency</div><div class="value" id="g-lat">—</div><div class="unit">ms</div></div>
          <div class="gauge"><div class="label">Jitter</div><div class="value" id="g-jit">—</div><div class="unit">ms</div></div>
          <div class="gauge"><div class="label">Download</div><div class="value" id="g-down">—</div><div class="unit">Mbps</div></div>
          <div class="gauge"><div class="label">Upload</div><div class="value" id="g-up">—</div><div class="unit">Mbps</div></div>
        </div>
        <div class="bar" title="Speed test progress"><i id="speed-bar"></i></div>
        <p class="hint" id="speed-msg">Idle — click Run speed test for live probes + Cloudflare throughput.</p>
      </section>

      <section class="panel">
        <h2>Detailed hops · packet loss · WHOIS</h2>
        <div id="route-tabs" class="route-tabs"></div>
        <div class="hop-scroll">
          <table class="hop-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Host / IP</th>
                <th>RTT</th>
                <th>Loss %</th>
                <th>Place</th>
              </tr>
            </thead>
            <tbody id="hops"></tbody>
          </table>
        </div>
        <div id="hop-detail" class="detail muted">Select a hop for WHOIS ownership, ASN, CIDR, and probe stats.</div>
      </section>

      <section class="panel">
        <h2>Events</h2>
        <div id="events" class="events"></div>
      </section>
    </section>

    <section class="stack">
      <section class="panel">
        <h2>3D route globe</h2>
        <canvas id="globe" width="980" height="560"></canvas>
        <div class="legend">
          <span><i style="background:var(--green)"></i>Origin</span>
          <span><i style="background:var(--cyan)"></i>Hop</span>
          <span><i style="background:var(--amber)"></i>Lossy hop</span>
          <span><i style="background:var(--red)"></i>High loss</span>
          <span><i style="background:var(--violet)"></i>Destination</span>
        </div>
        <p class="hint">Drag to rotate · scroll to zoom · arcs follow geolocated hops; color tracks RTT / loss.</p>
      </section>
    </section>
  </main>

  <script>
    const CONTINENTS = [[[107.0,77.0],[114.1,75.8],[110.6,74.0],[115.6,73.8],[125.4,73.6],[129.7,71.2],[137.5,71.3],[149.5,72.2],[159.8,70.5],[165.9,69.5],[170.5,70.1],[180.0,65.0],[178.9,63.3],[174.6,61.8],[168.9,60.6],[163.2,59.2],[162.1,56.1],[158.5,53.0],[155.4,55.4],[160.2,59.3],[162.7,61.6],[155.0,59.1],[148.5,59.2],[136.7,54.6],[141.3,53.1],[138.6,47.0],[133.5,42.8],[130.4,42.3],[129.0,40.5],[127.4,39.2],[129.5,35.6],[126.4,34.9],[125.7,37.9],[124.7,38.1],[125.3,39.6],[121.1,38.9],[120.8,40.6],[118.1,38.1],[121.7,37.5],[119.7,35.6],[121.9,31.7],[121.9,29.0],[118.7,24.5],[113.8,22.5],[109.9,20.3],[106.7,20.7],[108.3,16.1],[107.2,10.4],[104.3,10.5],[100.8,12.6],[99.2,10.0],[101.0,6.9],[103.4,4.9],[103.9,2.5],[101.4,2.8],[100.3,6.0],[98.5,8.4],[98.5,10.7],[97.8,14.8],[94.8,15.8],[93.7,19.7],[91.8,22.2],[89.8,22.0],[88.2,21.7],[83.9,18.3],[80.8,16.0],[79.9,12.1],[78.3,8.9],[75.7,11.3],[73.5,16.0],[71.2,20.8],[68.2,23.7],[62.9,25.2],[57.0,27.0],[52.5,27.6],[48.9,30.3],[48.4,28.6],[50.2,26.3],[50.8,24.8],[51.6,25.2],[52.6,24.2],[56.1,26.1],[56.4,24.9],[59.2,23.0],[59.3,21.4],[57.7,19.7],[56.5,18.1],[54.8,17.0],[52.2,15.9],[48.2,13.9],[45.6,13.3],[44.2,12.6],[42.9,14.8],[42.8,16.3],[41.2,18.7],[39.0,22.0],[37.2,24.9],[35.6,27.4],[35.0,29.4],[33.9,27.6],[32.7,28.7],[35.7,23.9],[37.2,21.0],[38.4,18.0],[41.7,13.9],[43.3,12.0],[44.1,10.4],[48.0,11.2],[50.3,11.7],[51.0,10.6],[48.6,5.3],[43.1,0.3],[40.6,-2.5],[39.2,-4.7],[39.2,-7.7],[40.3,-10.3],[40.8,-14.7],[37.4,-17.6],[34.7,-20.5],[35.5,-23.1],[34.2,-24.8],[32.8,-26.7],[31.3,-29.4],[28.2,-32.8],[25.2,-33.8],[21.5,-34.3],[18.9,-34.4],[17.9,-32.6],[17.1,-29.9],[14.7,-25.4],[13.4,-20.9],[11.6,-16.7],[12.7,-13.1],[13.4,-10.4],[12.9,-7.6],[11.9,-5.0],[8.8,-0.8],[9.6,2.3],[8.5,4.5],[5.9,4.3],[2.7,6.3],[-2.0,4.7],[-5.8,5.0],[-9.0,4.8],[-12.4,7.3],[-14.1,9.9],[-15.1,11.0],[-16.6,12.2],[-17.6,14.7],[-16.3,17.2],[-16.5,20.6],[-16.3,22.7],[-14.8,25.1],[-12.6,28.0],[-9.8,31.2],[-6.9,34.1],[-3.6,35.4],[0.5,36.3],[6.3,37.1],[10.2,37.2],[10.6,35.9],[10.9,33.8],[13.9,32.7],[19.1,30.3],[20.9,32.7],[23.9,32.0],[28.5,31.0],[31.7,31.4],[34.3,31.2],[35.1,33.1],[35.9,35.4],[34.7,36.8],[30.4,36.3],[26.3,38.2],[29.2,41.2],[36.9,41.3],[41.7,42.0],[38.7,44.3],[37.7,46.6],[36.8,46.7],[36.5,45.5],[33.5,45.0],[31.7,46.3],[29.6,45.0],[27.7,42.6],[27.6,41.0],[25.4,40.9],[23.3,40.0],[23.0,39.0],[23.4,37.4],[21.3,37.6],[20.0,39.7],[19.5,41.7],[17.5,42.9],[14.9,44.7],[13.7,45.5],[12.4,44.9],[15.1,42.0],[17.5,40.9],[16.9,40.4],[16.1,38.0],[15.7,39.5],[13.6,41.2],[10.2,43.9],[7.4,43.7],[3.0,41.9],[-0.3,39.3],[-2.1,36.7],[-5.9,36.0],[-8.4,37.0],[-9.5,38.7],[-8.8,41.2],[-8.0,43.7],[-1.9,43.4],[-4.5,48.0],[-1.0,49.3],[3.8,51.6],[7.9,53.7],[8.1,55.5],[9.8,57.4],[10.9,56.5],[9.9,54.6],[13.6,54.1],[18.6,54.7],[21.1,56.0],[24.1,57.0],[23.3,59.2],[29.1,60.0],[22.3,60.4],[22.4,63.8],[22.2,65.7],[17.1,61.3],[16.4,57.0],[12.6,56.3],[7.0,58.1],[8.6,63.5],[19.2,69.8],[28.2,71.2],[33.8,69.3],[40.0,66.3],[34.9,64.4],[37.2,65.1],[43.0,66.4],[43.5,68.6],[46.3,66.7],[54.5,68.8],[58.8,68.9],[63.5,69.5],[68.1,69.4],[68.5,71.9],[71.8,71.4],[73.2,67.7],[74.2,67.3],[73.6,69.6],[75.2,72.9],[77.6,72.3],[82.3,73.9],[88.3,75.1],[96.7,75.9],[104.4,77.7],[107.0,77.0]],[[-58.6,-64.2],[-62.0,-64.8],[-62.8,-66.4],[-65.7,-68.0],[-62.8,-69.6],[-61.4,-72.0],[-61.4,-74.1],[-65.9,-75.6],[-72.2,-76.7],[-75.4,-77.3],[-77.9,-78.4],[-75.4,-80.3],[-65.7,-81.5],[-58.2,-83.2],[-49.8,-81.7],[-40.8,-81.4],[-30.1,-80.6],[-31.6,-79.3],[-35.3,-78.1],[-28.9,-76.7],[-22.5,-76.1],[-16.6,-74.8],[-15.4,-73.1],[-11.0,-71.5],[-7.4,-71.3],[-3.0,-71.3],[1.9,-71.1],[7.1,-70.2],[10.8,-70.8],[15.1,-70.4],[20.4,-70.0],[24.8,-70.5],[30.0,-69.9],[33.9,-68.5],[37.9,-69.5],[42.0,-68.6],[46.5,-67.6],[50.8,-66.9],[54.5,-65.8],[58.1,-67.0],[62.4,-68.0],[66.9,-67.9],[69.6,-69.7],[68.9,-71.1],[71.0,-72.1],[73.3,-70.4],[77.6,-69.5],[80.9,-67.9],[84.7,-67.2],[88.4,-66.5],[92.6,-67.2],[96.7,-67.2],[100.9,-66.6],[104.9,-66.3],[110.2,-66.7],[114.4,-66.1],[118.6,-67.2],[123.2,-66.5],[127.9,-66.7],[132.9,-66.4],[135.7,-65.6],[138.6,-66.9],[144.4,-66.8],[147.7,-68.1],[153.6,-68.9],[158.0,-69.5],[162.7,-70.7],[168.4,-71.0],[170.6,-72.4],[167.4,-74.2],[163.8,-75.9],[164.3,-77.8],[163.7,-79.1],[159.8,-80.9],[165.1,-82.7],[172.5,-84.1],[180.0,-90.0],[-177.3,-84.5],[-176.1,-84.1],[-172.9,-84.1],[-164.2,-84.8],[-148.5,-85.6],[-150.1,-84.3],[-152.7,-82.5],[-154.4,-81.2],[-146.4,-80.3],[-153.4,-79.2],[-158.4,-76.9],[-152.9,-77.5],[-146.1,-76.5],[-144.3,-75.5],[-137.5,-74.7],[-132.3,-74.3],[-125.4,-74.5],[-118.7,-74.2],[-113.3,-74.0],[-108.7,-74.9],[-102.0,-75.1],[-102.5,-74.1],[-101.6,-72.8],[-96.3,-73.6],[-90.1,-73.3],[-85.2,-73.5],[-80.3,-73.1],[-74.9,-73.9],[-68.9,-73.0],[-67.6,-71.2],[-68.4,-69.3],[-67.7,-67.3],[-64.6,-65.6],[-61.4,-64.3],[-57.8,-63.3],[-58.6,-64.2]],[[-90.5,69.5],[-87.4,67.2],[-82.6,69.7],[-81.4,67.1],[-87.0,65.2],[-90.8,63.0],[-94.7,58.9],[-89.0,56.9],[-83.4,55.2],[-79.9,51.2],[-78.2,55.1],[-78.5,58.8],[-75.7,62.3],[-71.4,61.1],[-67.6,58.2],[-62.5,58.2],[-58.0,54.9],[-55.7,52.1],[-61.7,50.1],[-68.5,49.1],[-66.6,49.1],[-64.5,46.2],[-59.8,45.9],[-66.1,43.6],[-67.0,44.8],[-70.8,42.9],[-69.9,41.9],[-72.3,41.3],[-73.3,40.6],[-74.2,39.7],[-75.3,39.0],[-76.0,37.3],[-76.3,38.1],[-75.9,36.6],[-78.6,33.9],[-81.3,31.4],[-80.5,28.0],[-80.7,25.1],[-82.7,27.5],[-84.1,30.1],[-87.5,30.3],[-89.4,29.5],[-90.9,29.1],[-94.7,29.5],[-97.4,26.7],[-97.5,25.0],[-97.4,21.4],[-94.8,18.6],[-91.4,18.9],[-89.6,21.3],[-86.8,20.8],[-87.8,18.3],[-88.1,18.1],[-88.4,16.5],[-88.5,15.9],[-87.5,15.8],[-86.0,16.0],[-84.5,15.9],[-83.1,15.0],[-83.5,13.6],[-83.7,11.9],[-83.4,10.4],[-81.8,9.0],[-79.9,9.3],[-78.1,9.2],[-75.7,9.4],[-74.2,11.3],[-71.4,12.4],[-71.6,11.0],[-71.0,9.9],[-69.9,12.2],[-67.3,10.5],[-64.3,10.6],[-61.6,9.9],[-59.1,8.0],[-57.1,6.0],[-53.6,5.6],[-51.1,3.7],[-50.4,-0.1],[-44.9,-1.6],[-40.0,-2.9],[-35.2,-5.5],[-37.0,-11.0],[-38.9,-15.7],[-40.8,-20.9],[-44.6,-23.4],[-48.6,-26.6],[-50.7,-31.0],[-53.8,-34.4],[-57.8,-34.5],[-56.7,-36.4],[-62.3,-38.8],[-63.8,-41.2],[-63.8,-42.0],[-65.6,-45.0],[-65.6,-47.2],[-69.1,-50.7],[-69.9,-52.5],[-73.7,-52.8],[-75.6,-48.7],[-74.4,-44.1],[-74.3,-43.2],[-73.6,-37.2],[-71.7,-30.9],[-70.4,-23.6],[-71.5,-17.4],[-76.3,-13.5],[-79.8,-7.2],[-81.1,-4.0],[-81.0,-2.2],[-80.0,0.4],[-78.6,1.8],[-77.1,3.8],[-77.5,6.7],[-78.4,8.4],[-80.2,8.3],[-80.4,7.3],[-81.7,8.1],[-83.0,8.2],[-83.9,9.3],[-84.9,9.8],[-85.8,10.4],[-86.5,11.8],[-87.4,12.9],[-88.5,13.2],[-90.6,13.9],[-93.9,15.9],[-97.3,15.9],[-101.7,17.6],[-105.0,19.3],[-105.3,21.1],[-106.9,23.8],[-109.3,26.4],[-111.8,28.5],[-113.1,31.2],[-114.8,30.9],[-113.3,28.8],[-112.2,27.2],[-110.7,24.3],[-109.9,22.8],[-112.2,24.7],[-113.6,26.6],[-114.6,27.7],[-115.9,30.2],[-117.9,33.6],[-120.4,34.4],[-122.5,37.8],[-124.2,41.1],[-124.1,46.9],[-122.6,47.1],[-124.9,50.0],[-129.1,52.8],[-132.0,55.5],[-136.6,58.2],[-144.0,60.0],[-148.6,59.9],[-151.4,60.7],[-154.0,59.4],[-156.6,57.0],[-161.2,55.4],[-163.8,55.0],[-158.7,57.0],[-158.2,58.6],[-160.4,59.1],[-162.5,60.0],[-166.1,61.5],[-163.1,63.1],[-161.5,64.4],[-163.5,64.6],[-166.7,66.1],[-162.5,66.7],[-166.2,68.9],[-160.9,70.4],[-154.3,70.7],[-149.7,70.5],[-142.1,69.9],[-135.6,69.3],[-129.1,69.8],[-124.4,70.2],[-119.9,69.4],[-115.3,67.9],[-107.8,67.9],[-105.3,68.6],[-98.4,67.8],[-95.5,68.1],[-96.4,71.2],[-92.4,69.7],[-90.5,69.5]],[[143.6,-13.8],[145.3,-15.4],[146.1,-18.3],[148.7,-20.6],[150.7,-22.4],[153.1,-26.1],[153.3,-29.5],[151.7,-33.0],[150.1,-36.4],[147.4,-38.2],[145.0,-37.9],[141.6,-38.3],[139.1,-35.7],[136.8,-35.3],[137.0,-33.8],[134.6,-33.2],[131.3,-31.5],[125.1,-32.7],[122.2,-34.0],[119.0,-34.5],[115.6,-34.4],[115.7,-32.9],[115.0,-29.5],[113.5,-26.5],[114.2,-26.3],[113.5,-23.8],[114.2,-22.5],[117.2,-20.6],[119.3,-20.0],[122.2,-18.2],[123.9,-17.1],[124.9,-15.1],[126.1,-14.1],[129.0,-14.9],[130.2,-13.1],[132.6,-11.6],[134.4,-12.0],[136.5,-11.9],[136.1,-13.7],[137.1,-15.9],[139.3,-17.4],[141.4,-15.8],[141.7,-12.9],[142.1,-11.0],[143.2,-12.3],[143.6,-13.8]],[[-27.1,83.5],[-31.4,82.0],[-23.2,81.2],[-16.3,80.6],[-19.7,78.8],[-19.8,76.1],[-20.4,73.8],[-22.3,72.2],[-21.8,70.7],[-26.4,70.2],[-30.7,68.1],[-37.0,65.9],[-41.2,63.5],[-44.8,60.0],[-51.6,63.6],[-54.0,67.2],[-52.0,69.6],[-54.4,70.8],[-55.0,71.4],[-57.3,74.7],[-66.1,76.1],[-66.8,77.4],[-65.7,79.4],[-62.2,81.3],[-53.0,81.9],[-46.9,82.2],[-35.1,83.6],[-27.1,83.5]],[[-86.6,73.2],[-80.7,72.1],[-74.1,71.3],[-67.0,69.2],[-61.9,66.9],[-68.0,66.3],[-64.7,63.4],[-66.3,62.3],[-71.9,63.7],[-78.6,64.6],[-73.9,66.3],[-76.9,68.9],[-79.5,69.9],[-89.5,70.8],[-88.4,73.5],[-86.6,73.2]],[[-68.5,83.1],[-64.3,81.9],[-69.5,80.6],[-75.5,79.2],[-78.4,77.5],[-80.6,76.2],[-89.6,77.0],[-86.3,78.2],[-86.5,79.7],[-84.1,80.6],[-91.6,81.9],[-84.3,82.6],[-76.2,83.2],[-68.5,83.1]],[[134.1,-1.2],[138.3,-1.7],[144.6,-3.9],[147.9,-6.6],[149.3,-9.1],[150.7,-10.6],[147.1,-9.5],[143.3,-8.2],[140.1,-8.3],[138.7,-7.3],[133.7,-3.5],[132.0,-2.8],[131.8,-1.6],[134.0,-0.8],[134.1,-1.2]],[[-114.2,73.1],[-109.0,72.6],[-106.5,73.1],[-101.0,70.0],[-104.2,68.9],[-113.3,68.5],[-116.7,70.1],[-116.5,70.5],[-119.4,71.6],[-114.2,73.1]],[[117.9,1.8],[116.6,-1.5],[114.5,-3.5],[111.0,-3.0],[109.0,0.4],[111.4,2.7],[114.6,4.9],[117.6,6.4],[118.4,5.0],[117.9,1.8]],[[50.1,-13.6],[49.9,-15.4],[49.4,-18.0],[47.1,-24.9],[43.8,-24.5],[43.9,-21.2],[44.0,-18.3],[45.5,-16.0],[48.0,-14.1],[49.2,-12.0],[50.1,-13.6]],[[105.8,-5.9],[101.4,-2.8],[98.6,1.8],[95.3,5.5],[99.7,3.2],[103.8,0.1],[104.9,-2.3],[105.8,-5.9]],[[141.0,37.1],[137.2,34.6],[132.2,33.9],[130.2,31.4],[130.9,34.2],[136.7,37.3],[139.9,40.6],[141.0,38.2],[141.0,37.1]],[[-3.0,58.6],[-3.1,56.0],[0.5,52.9],[0.6,50.8],[-4.5,50.3],[-5.0,51.6],[-3.1,53.4],[-4.7,55.5],[-5.8,57.8],[-3.0,58.6]],[[57.5,70.7],[51.5,72.0],[55.9,74.6],[66.2,76.8],[61.6,75.3],[57.5,70.7]],[[-94.7,77.1],[-89.8,75.8],[-82.8,75.8],[-81.9,74.4],[-92.4,74.8],[-97.1,76.8],[-94.7,77.1]],[[-175.0,66.6],[-170.9,65.5],[-174.7,64.6],[-178.9,65.7],[-180.0,69.0],[-175.0,66.6]],[[-45.2,-78.0],[-44.9,-80.3],[-54.2,-80.6],[-49.9,-78.8],[-46.7,-77.8],[-45.2,-78.0]],[[-87.0,79.7],[-92.9,78.3],[-96.1,79.7],[-94.7,81.2],[-87.0,79.7]],[[18.3,79.7],[17.1,76.8],[11.2,78.9],[15.5,80.0],[18.3,79.7]],[[173.0,-40.9],[173.9,-42.2],[171.5,-44.2],[168.4,-46.6],[168.3,-44.1],[171.6,-41.8],[173.0,-40.9]],[[125.2,1.4],[120.2,0.2],[123.3,-1.1],[122.3,-3.5],[122.7,-4.5],[121.0,-2.6],[119.4,-5.4],[119.2,-2.1],[121.7,1.0],[125.2,1.4]],[[-56.1,50.7],[-54.9,49.3],[-53.0,48.2],[-54.0,47.6],[-56.3,47.6],[-59.2,48.5],[-55.4,51.6],[-56.1,50.7]],[[-14.5,66.5],[-18.7,63.5],[-22.2,65.1],[-20.6,65.7],[-14.5,66.5]],[[174.6,-36.2],[176.8,-37.9],[178.0,-39.2],[176.5,-40.6],[175.2,-40.5],[174.7,-38.0],[173.1,-35.2],[174.6,-36.2]],[[121.3,18.5],[122.5,17.1],[122.3,14.2],[124.1,12.5],[121.1,13.6],[120.6,14.4],[120.4,17.6],[121.3,18.5]],[[-79.7,22.8],[-76.5,21.2],[-74.2,20.3],[-77.8,19.9],[-78.7,21.6],[-82.2,22.4],[-84.1,21.9],[-83.8,22.8],[-80.6,23.1],[-79.7,22.8]],[[-68.5,-71.0],[-71.1,-72.5],[-75.0,-72.1],[-72.1,-71.2],[-70.3,-68.9],[-68.5,-71.0]],[[-67.8,-53.9],[-67.0,-54.9],[-71.0,-55.1],[-72.4,-53.7],[-68.6,-52.6],[-67.8,-53.9]],[[-120.5,71.4],[-124.8,73.0],[-117.6,74.2],[-120.5,71.8],[-120.5,71.4]],[[143.6,50.7],[143.5,46.1],[141.9,48.9],[142.6,53.8],[143.2,51.8],[143.6,50.7]],[[-85.2,65.7],[-81.6,64.5],[-82.5,63.7],[-87.2,63.5],[-85.2,65.7]],[[-108.2,76.2],[-106.3,75.0],[-111.8,75.2],[-112.6,76.1],[-108.5,76.7],[-108.2,76.2]],[[108.6,-6.8],[114.5,-7.8],[111.5,-8.3],[106.5,-7.4],[108.1,-6.3],[108.6,-6.8]],[[-72.6,19.9],[-70.0,19.6],[-68.3,18.6],[-70.1,18.2],[-71.7,17.8],[-73.9,18.0],[-72.3,18.7],[-72.6,19.9]],[[145.4,-40.8],[148.4,-42.1],[146.7,-43.6],[144.7,-40.7],[145.4,-40.8]],[[126.4,8.4],[125.4,6.8],[124.2,7.4],[121.9,7.2],[124.6,8.5],[126.3,8.8],[126.4,8.4]]];

    let snapshot = null;
    let selectedTarget = null;
    let selectedTtl = null;
    let anim = 0;

    // Globe camera
    let rotY = -0.85;   // yaw
    let rotX = 0.35;    // pitch
    let distance = 2.35;
    let dragging = false;
    let lastX = 0, lastY = 0;
    let autoSpin = true;

    const canvas = document.getElementById("globe");
    const ctx = canvas.getContext("2d");

    const targetInput = document.getElementById("target-input");
    const traceBtn = document.getElementById("trace-btn");
    let tracingTarget = null;

    async function startTraceFromInput() {
      const target = targetInput.value.trim();
      if (!target) {
        targetInput.focus();
        targetInput.placeholder = "Enter a host or IP to trace";
        return;
      }
      if (traceBtn.disabled) return;

      const previousLabel = traceBtn.textContent;
      traceBtn.disabled = true;
      traceBtn.textContent = "Tracing…";
      tracingTarget = target;
      selectedTarget = target;
      selectedTtl = null;

      try {
        const res = await fetch("/api/trace", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ target }),
        });
        const body = await res.json();
        if (!res.ok || !body.ok) {
          throw new Error(body.error || `Trace failed (${res.status})`);
        }
        // Hop feed + globe update via SSE once the tracer emits a route.
        renderPanels();
      } catch (err) {
        tracingTarget = null;
        alert(err.message || "Could not start traceroute");
      } finally {
        // Keep "Tracing…" until hops arrive (or after a short grace period).
        const started = Date.now();
        const unlock = () => {
          const route = (snapshot && snapshot.routes || []).find((r) => r.target === target);
          const ready = route && route.hop_count > 0;
          if (ready || Date.now() - started > 8000) {
            traceBtn.disabled = false;
            traceBtn.textContent = previousLabel;
            tracingTarget = null;
            return;
          }
          setTimeout(unlock, 250);
        };
        setTimeout(unlock, 250);
      }
    }

    traceBtn.onclick = () => { void startTraceFromInput(); };
    targetInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        void startTraceFromInput();
      }
    });

    document.getElementById("speed-btn").onclick = async (event) => {
      const btn = event.currentTarget;
      const previous = btn.textContent;
      btn.disabled = true;
      btn.textContent = "Running…";
      try {
        const res = await fetch("/api/speedtest", { method: "POST" });
        const body = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(body.error || `Speed test failed (${res.status})`);
        }
        // Stay disabled until the SSE snapshot reports complete/failed.
        const started = Date.now();
        const unlock = () => {
          const st = (snapshot && snapshot.speedtest) || {};
          if (st.status === "complete" || st.status === "failed" || Date.now() - started > 45000) {
            btn.disabled = false;
            btn.textContent = previous;
            return;
          }
          setTimeout(unlock, 300);
        };
        setTimeout(unlock, 300);
      } catch (err) {
        btn.disabled = false;
        btn.textContent = previous;
        alert(err.message || "Could not start speed test");
      }
    };

    canvas.addEventListener("pointerdown", (e) => {
      dragging = true; autoSpin = false;
      lastX = e.clientX; lastY = e.clientY;
      canvas.setPointerCapture(e.pointerId);
    });
    canvas.addEventListener("pointerup", () => { dragging = false; });
    canvas.addEventListener("pointercancel", () => { dragging = false; });
    canvas.addEventListener("pointermove", (e) => {
      if (!dragging) return;
      const dx = e.clientX - lastX;
      const dy = e.clientY - lastY;
      lastX = e.clientX; lastY = e.clientY;
      rotY += dx * 0.005;
      rotX = Math.max(-1.2, Math.min(1.2, rotX + dy * 0.005));
    });
    canvas.addEventListener("wheel", (e) => {
      e.preventDefault();
      distance = Math.max(1.55, Math.min(3.6, distance + e.deltaY * 0.0015));
    }, { passive: false });

    const source = new EventSource("/api/events");
    source.onmessage = (message) => {
      snapshot = JSON.parse(message.data);
      if (!selectedTarget && snapshot.routes.length) selectedTarget = snapshot.routes[0].target;
      if (selectedTarget && !snapshot.routes.find((r) => r.target === selectedTarget) && snapshot.routes.length) {
        selectedTarget = snapshot.routes[0].target;
      }
      renderPanels();
    };

    function currentRoute() {
      if (!snapshot) return null;
      return snapshot.routes.find((r) => r.target === selectedTarget) || snapshot.routes[0] || null;
    }

    function renderPanels() {
      if (!snapshot) return;
      const st = snapshot.speedtest || {};
      document.getElementById("counts").innerHTML =
        `<b>${snapshot.target_count}</b> targets · <b>${snapshot.hop_count}</b> hops · ` +
        `<b>${snapshot.located_count}</b> geolocated` +
        (snapshot.demo_mode ? ' · <b style="color:var(--amber)">DEMO</b>' : "");
      document.getElementById("updated").textContent = `Updated ${snapshot.generated_at}`;

      const live = st.current_mbps != null ? st.current_mbps : null;
      setGauge("g-lat", st.latency_ms);
      setGauge("g-jit", st.jitter_ms);
      setGauge("g-down", st.download_mbps != null ? st.download_mbps : (st.phase === "download" ? live : null));
      setGauge("g-up", st.upload_mbps != null ? st.upload_mbps : (st.phase === "upload" ? live : null));
      document.getElementById("speed-bar").style.width = `${st.progress || 0}%`;
      let msg = "Idle — click Run speed test.";
      if (st.status === "running") {
        msg = st.message || `Running ${st.phase || ""}…`;
      } else if (st.status === "complete") {
        msg = `Done · ↓ ${fmt(st.download_mbps)} / ↑ ${fmt(st.upload_mbps)} Mbps · `
          + `${fmt(st.latency_ms)} ms · loss ${fmt(st.packet_loss_pct)}%`
          + (st.server ? ` · ${st.server}` : "");
      } else if (st.status === "failed") {
        msg = st.message || "Speed test failed.";
      }
      document.getElementById("speed-msg").textContent = msg;

      const tabs = document.getElementById("route-tabs");
      tabs.innerHTML = "";
      for (const route of snapshot.routes) {
        const btn = document.createElement("button");
        btn.textContent = `${route.target} (${route.packet_loss_pct ?? 0}% loss)`;
        if (route.target === selectedTarget) btn.classList.add("active");
        btn.onclick = () => { selectedTarget = route.target; selectedTtl = null; renderPanels(); };
        tabs.appendChild(btn);
      }

      const route = currentRoute();
      const tbody = document.getElementById("hops");
      tbody.innerHTML = "";
      if (!route) {
        tbody.innerHTML = `<tr><td colspan="5" class="muted">No routes yet.</td></tr>`;
      } else {
        for (const hop of route.hops) {
          const tr = document.createElement("tr");
          if (hop.loss_pct >= 20) tr.classList.add("badloss");
          else if (hop.loss_pct > 0) tr.classList.add("lossy");
          if (hop.ttl === selectedTtl) tr.classList.add("selected");
          const host = hop.responded
            ? `<div class="mono">${esc(hop.hostname || hop.ip || "*")}</div>` +
              (hop.hostname && hop.ip ? `<div class="muted mono">${esc(hop.ip)}</div>` : "") +
              (hop.whois && hop.whois.found ? `<div class="whois-line">${esc(hop.whois.summary || hop.whois.org || hop.whois.name || "")}</div>` : "")
            : `<span class="muted">* * * no reply</span>`;
          const place = hop.geo ? (hop.geo.place || "—") : "—";
          tr.innerHTML = `
            <td>${hop.ttl}</td>
            <td>${host}</td>
            <td class="mono">${hop.rtt_avg_ms != null ? hop.rtt_avg_ms.toFixed(1) + " ms" : "—"}</td>
            <td class="loss mono">${hop.responded || hop.probes_sent ? hop.loss_pct.toFixed(1) + "%" : "100%"}</td>
            <td class="place">${esc(place)}</td>`;
          tr.onclick = () => { selectedTtl = hop.ttl; renderPanels(); };
          tbody.appendChild(tr);
        }
      }
      renderHopDetail(route);
      renderEvents();
    }

    function renderHopDetail(route) {
      const el = document.getElementById("hop-detail");
      if (!route) { el.innerHTML = "No route selected."; return; }
      const hop = route.hops.find((h) => h.ttl === selectedTtl) || route.hops.find((h) => h.responded) || route.hops[0];
      if (!hop) { el.innerHTML = "No hops yet."; return; }
      selectedTtl = hop.ttl;
      const w = hop.whois || {};
      const g = hop.geo || {};
      el.innerHTML = `
        <div style="margin-bottom:8px"><b>Hop ${hop.ttl}</b> · ${esc(hop.hostname || hop.ip || "unresponsive")}
        · probes ${hop.probes_answered}/${hop.probes_sent}
        · last cycle loss <b style="color:${hop.last_loss_pct>=20?'var(--red)':hop.last_loss_pct>0?'var(--amber)':'var(--green)'}">${fmt(hop.last_loss_pct)}%</b>
        · cumulative <b>${fmt(hop.loss_pct)}%</b></div>
        <div class="kv">
          <span>RTT</span><b class="mono">${fmt(hop.rtt_min_ms)} / ${fmt(hop.rtt_avg_ms)} / ${fmt(hop.rtt_max_ms)} ms (min/avg/max)</b>
          <span>Network</span><b>${esc(g.isp || w.org || "—")} ${g.asn ? "("+esc(g.asn)+")" : (w.asn ? "("+esc(w.asn)+")" : "")}</b>
          <span>WHOIS name</span><b>${esc(w.name || "—")}</b>
          <span>WHOIS org</span><b>${esc(w.org || w.registrant || "—")}</b>
          <span>CIDR / net</span><b class="mono">${esc(w.cidr || w.handle || "—")}</b>
          <span>Abuse</span><b>${esc(w.abuse_email || "—")}${w.abuse_phone ? " · " + esc(w.abuse_phone) : ""}</b>
          <span>Country</span><b>${esc(w.country || g.country || "—")}</b>
          <span>Place</span><b>${esc(g.place || "—")}</b>
        </div>`;
    }

    function renderEvents() {
      const el = document.getElementById("events");
      const events = (snapshot.events || []).slice(-40).reverse();
      el.innerHTML = events.map((e) => {
        const cls = e.type.includes("whois") ? "whois" : (e.type.includes("loss") || e.type.includes("route-changed") ? "loss" : "");
        return `<div class="${cls}"><span class="mono">${esc(e.at)}</span> · ${esc(e.message)}</div>`;
      }).join("") || `<div class="muted">No events yet.</div>`;
    }

    function setGauge(id, value) {
      document.getElementById(id).textContent = value == null ? "—" : (Number(value) >= 100 ? Math.round(value) : Number(value).toFixed(1));
    }
    function fmt(v) { return v == null || Number.isNaN(Number(v)) ? "—" : Number(v).toFixed(1); }
    function esc(s) {
      return String(s ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
    }

    // ---------- 3D globe ----------
    function project(lat, lon) {
      const phi = lat * Math.PI / 180;
      const lam = lon * Math.PI / 180;
      let x = Math.cos(phi) * Math.cos(lam);
      let y = Math.sin(phi);
      let z = Math.cos(phi) * Math.sin(lam);
      // rotate yaw then pitch
      const cy = Math.cos(rotY), sy = Math.sin(rotY);
      let x1 = x * cy - z * sy;
      let z1 = x * sy + z * cy;
      const cx = Math.cos(rotX), sx = Math.sin(rotX);
      let y2 = y * cx - z1 * sx;
      let z2 = y * sx + z1 * cx;
      const depth = z2;
      const scale = (Math.min(canvas.width, canvas.height) * 0.42) / distance;
      const px = canvas.width / 2 + x1 * scale;
      const py = canvas.height / 2 - y2 * scale;
      return { x: px, y: py, depth, visible: depth > -0.05 };
    }

    function greatCircle(a, b, n=48) {
      // a,b = {lat,lon}
      const toV = (p) => {
        const phi = p.lat * Math.PI/180, lam = p.lon * Math.PI/180;
        return [Math.cos(phi)*Math.cos(lam), Math.sin(phi), Math.cos(phi)*Math.sin(lam)];
      };
      const A = toV(a), B = toV(b);
      let dot = A[0]*B[0]+A[1]*B[1]+A[2]*B[2];
      dot = Math.max(-1, Math.min(1, dot));
      const omega = Math.acos(dot);
      const pts = [];
      if (omega < 1e-6) return [a, b];
      for (let i=0;i<=n;i++) {
        const t = i/n;
        const s1 = Math.sin((1-t)*omega)/Math.sin(omega);
        const s2 = Math.sin(t*omega)/Math.sin(omega);
        const x = s1*A[0]+s2*B[0], y = s1*A[1]+s2*B[1], z = s1*A[2]+s2*B[2];
        const lat = Math.asin(Math.max(-1, Math.min(1, y))) * 180/Math.PI;
        const lon = Math.atan2(z, x) * 180/Math.PI;
        pts.push({lat, lon});
      }
      return pts;
    }

    function drawGlobe() {
      const dpr = window.devicePixelRatio || 1;
      const rect = canvas.getBoundingClientRect();
      if (canvas.width !== Math.floor(rect.width * dpr) || canvas.height !== Math.floor(rect.height * dpr)) {
        canvas.width = Math.floor(rect.width * dpr);
        canvas.height = Math.floor(rect.height * dpr);
      }
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      // atmosphere
      const cx = canvas.width/2, cy = canvas.height/2;
      const R = Math.min(canvas.width, canvas.height) * 0.42 / distance;
      const grad = ctx.createRadialGradient(cx - R*0.3, cy - R*0.35, R*0.2, cx, cy, R*1.15);
      grad.addColorStop(0, "#12314a");
      grad.addColorStop(0.55, "#0a1a2b");
      grad.addColorStop(0.92, "#061018");
      grad.addColorStop(1, "rgba(3,10,18,0)");
      ctx.fillStyle = grad;
      ctx.beginPath(); ctx.arc(cx, cy, R*1.12, 0, Math.PI*2); ctx.fill();

      // ocean sphere
      const ocean = ctx.createRadialGradient(cx - R*0.25, cy - R*0.3, R*0.1, cx, cy, R);
      ocean.addColorStop(0, "#1a4a6e");
      ocean.addColorStop(1, "#071828");
      ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI*2); ctx.fillStyle = ocean; ctx.fill();

      // graticule
      ctx.lineWidth = Math.max(1, dpr * 0.7);
      ctx.strokeStyle = "rgba(90,140,180,0.18)";
      for (let lat = -60; lat <= 60; lat += 30) {
        ctx.beginPath();
        let started = false;
        for (let lon = -180; lon <= 180; lon += 6) {
          const p = project(lat, lon);
          if (!p.visible) { started = false; continue; }
          if (!started) { ctx.moveTo(p.x, p.y); started = true; } else ctx.lineTo(p.x, p.y);
        }
        ctx.stroke();
      }
      for (let lon = -180; lon < 180; lon += 30) {
        ctx.beginPath();
        let started = false;
        for (let lat = -90; lat <= 90; lat += 6) {
          const p = project(lat, lon);
          if (!p.visible) { started = false; continue; }
          if (!started) { ctx.moveTo(p.x, p.y); started = true; } else ctx.lineTo(p.x, p.y);
        }
        ctx.stroke();
      }

      // continents
      ctx.fillStyle = "rgba(56, 120, 92, 0.55)";
      ctx.strokeStyle = "rgba(140, 210, 170, 0.35)";
      ctx.lineWidth = Math.max(1, dpr * 0.8);
      for (const ring of CONTINENTS) {
        let path = [];
        for (const [lon, lat] of ring) {
          const p = project(lat, lon);
          if (p.visible) path.push(p);
          else {
            if (path.length > 2) fillPath(path);
            path = [];
          }
        }
        if (path.length > 2) fillPath(path);
      }

      // routes
      const route = currentRoute();
      const points = [];
      if (snapshot && snapshot.origin && snapshot.origin.lat != null) {
        points.push({ lat: snapshot.origin.lat, lon: snapshot.origin.lon, kind: "origin", label: "You", loss: 0, rtt: 0 });
      }
      if (route) {
        for (const hop of route.hops) {
          if (!hop.located || !hop.geo) continue;
          points.push({
            lat: hop.geo.lat, lon: hop.geo.lon,
            kind: hop.ttl === route.hops[route.hops.length-1]?.ttl ? "dest" : "hop",
            label: hop.hostname || hop.ip, loss: hop.loss_pct || 0, rtt: hop.rtt_avg_ms || 0, ttl: hop.ttl,
          });
        }
      }

      // arcs
      for (let i = 0; i < points.length - 1; i++) {
        const a = points[i], b = points[i+1];
        const gc = greatCircle(a, b, 56);
        const pulse = (Math.sin(anim * 0.06 + i) + 1) / 2;
        const loss = b.loss || 0;
        const color = loss >= 20 ? `rgba(240,113,120,${0.55+pulse*0.35})`
          : loss > 0 ? `rgba(245,185,66,${0.5+pulse*0.35})`
          : `rgba(62,199,255,${0.45+pulse*0.4})`;
        ctx.strokeStyle = color;
        ctx.lineWidth = Math.max(1.5, dpr * (2 + pulse));
        ctx.beginPath();
        let started = false;
        for (const pt of gc) {
          const p = project(pt.lat, pt.lon);
          // lift arc slightly toward camera for visibility
          if (!p.visible) { started = false; continue; }
          if (!started) { ctx.moveTo(p.x, p.y); started = true; } else ctx.lineTo(p.x, p.y);
        }
        ctx.stroke();

        // traveling packet
        const t = ((anim * 0.01) + i * 0.15) % 1;
        const idx = Math.floor(t * (gc.length - 1));
        const pkt = project(gc[idx].lat, gc[idx].lon);
        if (pkt.visible) {
          ctx.beginPath();
          ctx.fillStyle = "#fff";
          ctx.arc(pkt.x, pkt.y, 2.8 * dpr, 0, Math.PI*2);
          ctx.fill();
        }
      }

      // markers
      for (const pt of points) {
        const p = project(pt.lat, pt.lon);
        if (!p.visible) continue;
        let color = "var(--cyan)";
        if (pt.kind === "origin") color = "#4ade80";
        else if (pt.kind === "dest") color = "#a78bfa";
        else if (pt.loss >= 20) color = "#f07178";
        else if (pt.loss > 0) color = "#f5b942";
        else color = "#3ec7ff";
        const selected = pt.ttl === selectedTtl;
        const r = (selected ? 6 : 4) * dpr;
        ctx.beginPath();
        ctx.fillStyle = color;
        ctx.shadowColor = color;
        ctx.shadowBlur = 12 * dpr;
        ctx.arc(p.x, p.y, r, 0, Math.PI*2);
        ctx.fill();
        ctx.shadowBlur = 0;
        if (selected || pt.kind === "origin" || pt.kind === "dest") {
          ctx.fillStyle = "rgba(231,240,248,0.9)";
          ctx.font = `${11*dpr}px sans-serif`;
          ctx.fillText(String(pt.label || "").slice(0, 28), p.x + 8*dpr, p.y - 6*dpr);
        }
      }

      // limb outline
      ctx.beginPath();
      ctx.arc(cx, cy, R, 0, Math.PI*2);
      ctx.strokeStyle = "rgba(120,190,230,0.35)";
      ctx.lineWidth = Math.max(1, dpr);
      ctx.stroke();
    }

    function fillPath(path) {
      ctx.beginPath();
      ctx.moveTo(path[0].x, path[0].y);
      for (let i=1;i<path.length;i++) ctx.lineTo(path[i].x, path[i].y);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
    }

    function frame() {
      if (autoSpin && !dragging) rotY += 0.0022;
      anim += 1;
      drawGlobe();
      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  </script>
</body>
</html>
"""
