"""FastAPI dashboard for the visual traceroute path radar."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from .speedtest import run_speed_test
from .state import RadarState
from .tools import COMMON_PORTS, lookup_dns, ping_host, scan_ports
from .whois import WhoisResolver

_HOST_RE = re.compile(r"^[A-Za-z0-9._:-]{1,253}$")


class TraceRequest(BaseModel):
    target: str = Field(min_length=1, max_length=253)


class ToolRequest(BaseModel):
    target: str = Field(min_length=1, max_length=253)
    ports: list[int] | None = None
    count: int | None = Field(default=None, ge=1, le=20)


def create_app(state: RadarState) -> FastAPI:
    app = FastAPI(title="Trace Radar — PingPlotter + Scanny tools")
    whois_resolver = WhoisResolver(demo=state.demo_mode)

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return DASHBOARD_HTML

    @app.get("/api/state")
    async def api_state() -> dict:
        return await state.snapshot()

    @app.post("/api/trace")
    async def api_trace(request: TraceRequest) -> JSONResponse:
        target = request.target.strip()
        if not target or not _HOST_RE.match(target):
            return JSONResponse({"ok": False, "error": "Invalid target"}, status_code=400)
        created = await state.request_trace(target)
        return JSONResponse({"ok": True, "created": created, "target": target})

    @app.post("/api/speedtest")
    async def api_speedtest() -> JSONResponse:
        if await state.speedtest_running():
            return JSONResponse({"ok": False, "error": "Speed test already running"}, status_code=409)
        asyncio.create_task(run_speed_test(state), name="speedtest")
        return JSONResponse({"ok": True, "status": "started"})

    @app.post("/api/whois")
    async def api_whois(request: ToolRequest) -> JSONResponse:
        target = request.target.strip()
        if not target or not _HOST_RE.match(target):
            return JSONResponse({"ok": False, "error": "Invalid target"}, status_code=400)
        ip = target
        if not _looks_like_ipv4(target):
            dns = await lookup_dns(target, demo=state.demo_mode)
            addrs = (dns.records or {}).get("A") or []
            if not addrs:
                return JSONResponse({"ok": False, "error": dns.error or "No A record"}, status_code=400)
            ip = addrs[0]
        whois_resolver.demo = state.demo_mode
        info = await whois_resolver.lookup(ip)
        payload = info.to_dict()
        await state.record_tool_result("whois", target, payload)
        return JSONResponse({"ok": True, "result": payload})

    @app.post("/api/dns")
    async def api_dns(request: ToolRequest) -> JSONResponse:
        target = request.target.strip()
        if not target or not _HOST_RE.match(target):
            return JSONResponse({"ok": False, "error": "Invalid target"}, status_code=400)
        result = await lookup_dns(target, demo=state.demo_mode)
        payload = result.to_dict()
        await state.record_tool_result("dns", target, payload)
        return JSONResponse({"ok": True, "result": payload})

    @app.post("/api/ports")
    async def api_ports(request: ToolRequest) -> JSONResponse:
        target = request.target.strip()
        if not target or not _HOST_RE.match(target):
            return JSONResponse({"ok": False, "error": "Invalid target"}, status_code=400)
        ports = request.ports or list(COMMON_PORTS)
        ports = [int(p) for p in ports if 1 <= int(p) <= 65535][:64]
        result = await scan_ports(target, ports=ports, demo=state.demo_mode)
        payload = result.to_dict()
        await state.record_tool_result("ports", target, payload)
        return JSONResponse({"ok": True, "result": payload})

    @app.post("/api/ping")
    async def api_ping(request: ToolRequest) -> JSONResponse:
        target = request.target.strip()
        if not target or not _HOST_RE.match(target):
            return JSONResponse({"ok": False, "error": "Invalid target"}, status_code=400)
        count = request.count or 4
        result = await ping_host(target, count=count, demo=state.demo_mode)
        payload = result.to_dict()
        await state.record_tool_result("ping", target, payload)
        return JSONResponse({"ok": True, "result": payload})

    @app.get("/api/events")
    async def events() -> StreamingResponse:
        return StreamingResponse(_event_stream(state), media_type="text/event-stream")

    return app


def _looks_like_ipv4(value: str) -> bool:
    parts = value.split(".")
    if len(parts) != 4:
        return False
    try:
        return all(0 <= int(part) <= 255 for part in parts)
    except ValueError:
        return False


async def _event_stream(state: RadarState) -> AsyncIterator[str]:
    last_payload = ""
    while True:
        snapshot = await state.snapshot()
        payload = json.dumps(snapshot)
        if payload != last_payload:
            yield f"data: {payload}\n\n"
            last_payload = payload
        await asyncio.sleep(1)


DASHBOARD_HTML = r"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Path Radar — hop health</title>
  <style>
    :root {
      --bg: #05070c;
      --glass: rgba(8,14,24,.78);
      --line: rgba(148,176,210,.16);
      --text: #eef4ff;
      --muted: #8b9bb4;
      --cyan: #5ce1e6;
      --mint: #7dffc3;
      --amber: #ffb020;
      --coral: #ff6b7a;
      --violet: #9b8cff;
      --blue: #6ea8ff;
      --font: "IBM Plex Sans", "Segoe UI", "Helvetica Neue", sans-serif;
      --mono: "IBM Plex Mono", "SFMono-Regular", ui-monospace, Menlo, monospace;
    }
    * { box-sizing: border-box; }
    html, body { margin: 0; height: 100%; overflow: hidden; color: var(--text); font-family: var(--font); background: var(--bg); }
    #net { position: fixed; inset: 0; width: 100%; height: 100%; display: block; }
    .hud { position: fixed; z-index: 2; pointer-events: none; }
    .hud > * , .glass, .hud button, .hud input, .hud table, .hud canvas, .hud a { pointer-events: auto; }
    .glass {
      background: var(--glass); border: 1px solid var(--line); border-radius: 16px;
      backdrop-filter: blur(14px); box-shadow: 0 18px 50px rgba(0,0,0,.35);
    }
    .top {
      top: 12px; left: 12px; right: 12px; display: flex; gap: 12px; align-items: center;
      justify-content: space-between; flex-wrap: wrap; padding: 10px 14px;
    }
    h1 { margin: 0; font-size: 18px; letter-spacing: .04em; }
    h1 b { color: var(--cyan); font-weight: 800; }
    .stats { color: var(--muted); font-size: 12px; margin-top: 3px; }
    .stats b { color: var(--text); }
    .controls { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
    input[type=text] {
      background: #0a1420; border: 1px solid var(--line); color: var(--text);
      border-radius: 10px; padding: 8px 11px; font: inherit; min-width: 150px;
    }
    button {
      background: linear-gradient(180deg, #6ae7ec, #2bb7c4); color: #041016;
      border: 0; border-radius: 10px; padding: 8px 12px; font-weight: 700; cursor: pointer;
    }
    button.secondary { background: #152333; color: var(--text); border: 1px solid var(--line); }
    button:disabled { opacity: .5; cursor: wait; }
    .chip { font-size: 11px; color: var(--muted); border: 1px solid var(--line); border-radius: 999px; padding: 4px 8px; }
    .chip b { color: var(--text); }
    .left, .right {
      width: min(400px, 34vw); max-height: calc(100vh - 92px); overflow: auto;
      padding: 12px; display: grid; gap: 12px;
    }
    .left { top: 76px; left: 12px; }
    .right { top: 76px; right: 12px; }
    h2 { margin: 0 0 8px; font-size: 11px; letter-spacing: .12em; text-transform: uppercase; color: var(--muted); }
    #hop3d { width: 100%; height: 236px; display: block; border-radius: 12px; background: #070d16; border: 1px solid var(--line); }
    #timeline { width: 100%; height: 168px; display: block; border-radius: 12px; background: #070d16; border: 1px solid var(--line); }
    .hop-table { width: 100%; border-collapse: collapse; font-size: 12px; }
    .hop-table th { text-align: left; color: var(--muted); font-size: 10px; letter-spacing: .06em; text-transform: uppercase; padding: 4px; }
    .hop-table td { padding: 6px 4px; border-bottom: 1px solid rgba(148,176,210,.1); vertical-align: top; }
    .hop-table tr { cursor: pointer; }
    .hop-table tr:hover { background: rgba(92,225,230,.06); }
    .hop-table tr.selected { background: rgba(92,225,230,.12); }
    .hop-table tr.slow td { color: var(--amber); }
    .hop-table .mono { font-family: var(--mono); font-size: 11px; color: var(--muted); }
    .health { border-radius: 999px; padding: 2px 7px; font-size: 10px; font-weight: 700; text-transform: uppercase; }
    .health.good { background: rgba(125,255,195,.14); color: var(--mint); }
    .health.degraded, .health.slow { background: rgba(255,176,32,.14); color: var(--amber); }
    .health.poor, .health.down { background: rgba(255,107,122,.16); color: var(--coral); }
    .health.unknown { background: rgba(139,155,180,.14); color: var(--muted); }
    .problem {
      border: 1px solid rgba(255,176,32,.35); background: rgba(255,176,32,.08);
      border-radius: 12px; padding: 10px; font-size: 12px;
    }
    .problem.poor { border-color: rgba(255,107,122,.4); background: rgba(255,107,122,.08); }
    .problem h3 { margin: 0 0 4px; font-size: 13px; }
    .problem .meta { color: var(--muted); font-size: 11px; font-family: var(--mono); }
    .inspector { font-size: 13px; }
    .kv { display: grid; grid-template-columns: 92px 1fr; gap: 4px 8px; font-size: 12px; }
    .kv span { color: var(--muted); }
    .route-tabs { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; }
    .route-tabs button { padding: 5px 9px; font-size: 11px; }
    .events { max-height: 120px; overflow: auto; font-size: 11px; color: var(--muted); }
    .events div { padding: 3px 0; border-bottom: 1px solid rgba(148,176,210,.1); }
    #tool-out { min-height: 56px; max-height: 140px; overflow: auto; font-family: var(--mono); font-size: 11px; color: var(--muted); white-space: pre-wrap; }
    .legend { display: flex; gap: 10px; flex-wrap: wrap; font-size: 11px; color: var(--muted); margin-top: 6px; }
    .legend i { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 4px; }
    .hint { font-size: 11px; color: var(--muted); margin: 6px 0 0; }
    .bar { height: 5px; border-radius: 999px; background: #132333; overflow: hidden; margin-top: 8px; }
    .bar > i { display: block; height: 100%; width: 0; background: linear-gradient(90deg, var(--mint), var(--cyan)); }
    @media (max-width: 980px) {
      .left, .right { position: relative; top: auto; left: auto; right: auto; width: auto; max-height: none; margin: 8px; }
      body { overflow: auto; }
      #net { position: relative; height: 52vh; }
      .top { position: relative; }
      .hud { position: relative; }
    }
  </style>
</head>
<body>
  <canvas id="net"></canvas>
  <header class="hud top glass">
    <div>
      <h1><b>Path Radar</b> · hops · graph · 3D</h1>
      <div class="stats" id="counts">Waiting for traceroute…</div>
    </div>
    <div class="controls">
      <input id="search" type="text" placeholder="Search nodes, IP, ASN, provider" autocomplete="off">
      <input id="target-input" type="text" placeholder="host or IP" value="cloudflare.com">
      <button id="trace-btn">Trace</button>
      <button id="reheat" class="secondary">Reheat</button>
      <button id="freeze" class="secondary">Freeze</button>
      <button id="speed-btn" class="secondary">Speed test</button>
    </div>
  </header>
  <aside class="hud left glass">
    <section>
      <h2>Hop path · 3D</h2>
      <div class="route-tabs" id="route-tabs"></div>
      <canvas id="hop3d" width="760" height="210"></canvas>
      <p class="hint">Drag to orbit · click a hop for provider detail. Height is current RTT; slow hops glow.</p>
    </section>
    <section>
      <h2>Live hops</h2>
      <table class="hop-table">
        <thead><tr><th>#</th><th>Host</th><th>+ms</th><th>RTT</th><th>Loss</th><th></th></tr></thead>
        <tbody id="hops"></tbody>
      </table>
    </section>
    <section id="problem-box"></section>
  </aside>
  <aside class="hud right glass">
    <section class="inspector">
      <h2>Inspect</h2>
      <div id="inspect">Click a hop, LAN device, or graph node.</div>
    </section>
    <section>
      <h2>PingPlotter timeline</h2>
      <canvas id="timeline" width="760" height="168"></canvas>
      <div class="legend">
        <span><i style="background:var(--mint)"></i>good</span>
        <span><i style="background:var(--amber)"></i>slow / loss</span>
        <span><i style="background:var(--coral)"></i>timeout</span>
      </div>
    </section>
    <section>
      <h2>Scanny tools</h2>
      <div class="controls">
        <input id="tool-input" type="text" placeholder="host or IP" value="1.1.1.1">
      </div>
      <div class="controls" style="margin-top:8px">
        <button id="tool-whois" class="secondary">WHOIS</button>
        <button id="tool-dns" class="secondary">DNS</button>
        <button id="tool-ports" class="secondary">Ports</button>
        <button id="tool-ping" class="secondary">Ping</button>
      </div>
      <div id="tool-out">WHOIS · DNS · ports · ping</div>
      <div class="bar"><i id="speed-bar"></i></div>
      <p class="hint" id="speed-msg">Speed test idle.</p>
    </section>
    <section>
      <h2>Events</h2>
      <div id="events" class="events"></div>
    </section>
  </aside>
  <script>
    const net = document.getElementById("net");
    const nctx = net.getContext("2d");
    const hopCanvas = document.getElementById("hop3d");
    const hctx = hopCanvas.getContext("2d");
    const timeCanvas = document.getElementById("timeline");
    const tctx = timeCanvas.getContext("2d");

    let snapshot = null;
    let selectedTarget = null;
    let selectedTtl = null;
    let selectedNode = null;
    let searchQ = "";
    let lastPanelKey = "";

    const sim = {
      nodes: [],
      links: [],
      byId: new Map(),
      alpha: 1,
      frozen: false,
      scale: 1,
      panX: null,
      panY: null,
      dragging: null,
      panning: false,
      lastX: 0,
      lastY: 0,
    };

    const cam3 = { yaw: 0.55, pitch: 0.42, dragging: false, lastX: 0, lastY: 0, auto: true };

    const KIND_COLOR = {
      host: "#5ce1e6", phone: "#6ea8ff", nas: "#9b8cff", ap: "#7dffc3",
      media: "#c4b5fd", gateway: "#7dffc3", router: "#6ea8ff", hop: "#8b9bb4", dest: "#9b8cff",
    };

    function $(id) { return document.getElementById(id); }
    function esc(s) {
      return String(s ?? "").replace(/[&<>"']/g, (c) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
      }[c]));
    }
    function fmt(v, d=1) {
      return v == null || Number.isNaN(Number(v)) ? "—" : Number(v).toFixed(d);
    }
    function healthColor(h) {
      if (h === "good") return "#7dffc3";
      if (h === "degraded") return "#ffb020";
      if (h === "poor" || h === "down") return "#ff6b7a";
      return "#8b9bb4";
    }

    function currentRoute() {
      if (!snapshot || !snapshot.routes || !snapshot.routes.length) return null;
      return snapshot.routes.find((r) => r.target === selectedTarget) || snapshot.routes[0];
    }

    function syncGraph(graph) {
      if (!graph) return;
      const keep = new Set();
      const W = net.clientWidth || 800, H = net.clientHeight || 600;
      const maxLayer = Math.max(1, ...graph.nodes.map((n) => n.layer || 0));
      for (const spec of graph.nodes) {
        keep.add(spec.id);
        let node = sim.byId.get(spec.id);
        if (!node) {
          const jitter = () => (Math.random() - 0.5) * 40;
          node = {
            id: spec.id, x: ((spec.layer || 0) / maxLayer - 0.4) * Math.min(W, 900) + jitter(),
            y: jitter(), vx: 0, vy: 0, fx: null, fy: null,
          };
          sim.nodes.push(node);
          sim.byId.set(spec.id, node);
        }
        Object.assign(node, spec);
      }
      sim.nodes = sim.nodes.filter((n) => {
        if (keep.has(n.id)) return true;
        sim.byId.delete(n.id);
        return false;
      });
      sim.links = graph.edges.map((e) => ({
        ...e,
        s: sim.byId.get(e.source),
        t: sim.byId.get(e.target),
        dist: e.kind === "lan" ? 54 : 86,
      })).filter((e) => e.s && e.t);
      if (sim.alpha < 0.08 && !sim.frozen) sim.alpha = 0.12;
    }

    function tickForce() {
      if (sim.frozen || sim.alpha < 0.004) return false;
      const a = sim.alpha;
      const nodes = sim.nodes;
      const n = nodes.length;
      for (const l of sim.links) {
        const dx = l.t.x - l.s.x, dy = l.t.y - l.s.y;
        const dist = Math.hypot(dx, dy) || 0.01;
        const k = ((dist - l.dist) / dist) * 0.35 * a;
        const sx = dx * k, sy = dy * k;
        if (l.s.fx == null) { l.s.vx += sx; l.s.vy += sy; }
        if (l.t.fx == null) { l.t.vx -= sx; l.t.vy -= sy; }
      }
      for (let i = 0; i < n; i++) {
        const A = nodes[i];
        for (let j = i + 1; j < n; j++) {
          const B = nodes[j];
          let dx = B.x - A.x, dy = B.y - A.y;
          let dist2 = dx * dx + dy * dy || 0.01;
          const min = 28;
          if (dist2 < min * min) dist2 = min * min;
          const f = -420 * a / dist2;
          const fx = dx * f, fy = dy * f;
          if (A.fx == null) { A.vx += fx; A.vy += fy; }
          if (B.fx == null) { B.vx -= fx; B.vy -= fy; }
        }
        const layerX = ((A.layer || 0) / 8 - 0.35) * 640;
        if (A.fx == null) A.vx += (layerX - A.x) * 0.012 * a;
      }
      const decay = 0.72;
      for (const node of nodes) {
        if (node.fx != null) { node.x = node.fx; node.y = node.fy; node.vx = 0; node.vy = 0; continue; }
        node.vx *= decay; node.vy *= decay;
        node.x += node.vx; node.y += node.vy;
      }
      sim.alpha *= 0.978;
      return true;
    }

    function resizeCanvas(canvas, ctx) {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const rect = canvas.getBoundingClientRect();
      const w = Math.max(1, Math.floor(rect.width * dpr));
      const h = Math.max(1, Math.floor(rect.height * dpr));
      if (canvas.width !== w || canvas.height !== h) {
        canvas.width = w; canvas.height = h;
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      return { w: rect.width, h: rect.height, dpr };
    }

    function nodeMatches(node) {
      if (!searchQ) return true;
      return (node.search || "").includes(searchQ) || (node.id || "").toLowerCase().includes(searchQ);
    }

    function drawGraph() {
      const { w, h } = resizeCanvas(net, nctx);
      nctx.setTransform(1, 0, 0, 1, 0, 0);
      nctx.clearRect(0, 0, net.width, net.height);
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      nctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      nctx.fillStyle = "#05070c";
      nctx.fillRect(0, 0, w, h);
      nctx.save();
      nctx.translate(sim.panX ?? w / 2, sim.panY ?? h / 2);
      nctx.scale(sim.scale, sim.scale);
      const showLabels = sim.scale > 0.72 && sim.nodes.length < 70;
      for (const l of sim.links) {
        const dim = searchQ && !(nodeMatches(l.s) || nodeMatches(l.t));
        nctx.globalAlpha = dim ? 0.12 : (l.kind === "lan" ? 0.28 : 0.55);
        nctx.strokeStyle = l.slow ? "#ffb020" : (l.kind === "lan" ? "#3a5168" : "#5ce1e6");
        nctx.lineWidth = l.slow ? 2.2 : 1.1;
        nctx.beginPath();
        nctx.moveTo(l.s.x, l.s.y);
        nctx.lineTo(l.t.x, l.t.y);
        nctx.stroke();
        if (showLabels && l.label && !dim) {
          nctx.globalAlpha = 0.85;
          nctx.fillStyle = l.slow ? "#ffb020" : "#8b9bb4";
          nctx.font = "10px ui-sans-serif, sans-serif";
          nctx.fillText(l.label, (l.s.x + l.t.x) / 2 + 4, (l.s.y + l.t.y) / 2 - 4);
        }
      }
      nctx.globalAlpha = 1;
      for (const node of sim.nodes) {
        const hit = nodeMatches(node);
        const selected = selectedNode === node.id || (selectedTtl && node.ttl === selectedTtl && (node.targets || []).includes(selectedTarget));
        nctx.globalAlpha = searchQ && !hit ? 0.14 : 1;
        const r = node.kind === "host" || node.kind === "dest" ? 11 : (node.slow ? 10 : 8);
        if (node.slow) {
          nctx.beginPath();
          nctx.arc(node.x, node.y, r + 7, 0, Math.PI * 2);
          nctx.fillStyle = "rgba(255,176,32,.16)";
          nctx.fill();
        }
        nctx.beginPath();
        nctx.arc(node.x, node.y, r, 0, Math.PI * 2);
        nctx.fillStyle = node.slow ? "#ffb020" : (KIND_COLOR[node.kind] || healthColor(node.health));
        nctx.fill();
        if (selected) {
          nctx.strokeStyle = "#eef4ff";
          nctx.lineWidth = 2;
          nctx.stroke();
        }
        if (showLabels && hit) {
          nctx.fillStyle = "#eef4ff";
          nctx.font = selected ? "bold 11px ui-sans-serif" : "10px ui-sans-serif";
          nctx.fillText(node.label || node.ip || node.id, node.x + r + 4, node.y + 3);
        }
      }
      nctx.restore();
    }

    function worldFromEvent(ev) {
      const rect = net.getBoundingClientRect();
      const px = ev.clientX - rect.left;
      const py = ev.clientY - rect.top;
      const cx = sim.panX ?? rect.width / 2;
      const cy = sim.panY ?? rect.height / 2;
      return { x: (px - cx) / sim.scale, y: (py - cy) / sim.scale };
    }

    function hitNode(ev) {
      const p = worldFromEvent(ev);
      let best = null, bestD = 16;
      for (const node of sim.nodes) {
        const d = Math.hypot(node.x - p.x, node.y - p.y);
        if (d < bestD) { best = node; bestD = d; }
      }
      return best;
    }

    net.addEventListener("pointerdown", (e) => {
      const node = hitNode(e);
      if (node) {
        sim.dragging = node;
        node.fx = node.x; node.fy = node.y;
        selectNode(node);
        net.setPointerCapture(e.pointerId);
      } else {
        sim.panning = true;
        sim.lastX = e.clientX; sim.lastY = e.clientY;
        net.setPointerCapture(e.pointerId);
      }
    });
    net.addEventListener("pointermove", (e) => {
      if (sim.dragging) {
        const p = worldFromEvent(e);
        sim.dragging.fx = p.x; sim.dragging.fy = p.y;
        sim.dragging.x = p.x; sim.dragging.y = p.y;
        if (!sim.frozen) sim.alpha = Math.max(sim.alpha, 0.12);
      } else if (sim.panning) {
        sim.panX = (sim.panX ?? net.clientWidth / 2) + (e.clientX - sim.lastX);
        sim.panY = (sim.panY ?? net.clientHeight / 2) + (e.clientY - sim.lastY);
        sim.lastX = e.clientX; sim.lastY = e.clientY;
      }
    });
    net.addEventListener("pointerup", () => { sim.dragging = null; sim.panning = false; });
    net.addEventListener("pointercancel", () => { sim.dragging = null; sim.panning = false; });
    net.addEventListener("wheel", (e) => {
      e.preventDefault();
      const factor = e.deltaY < 0 ? 1.08 : 0.92;
      const rect = net.getBoundingClientRect();
      const mx = e.clientX - rect.left, my = e.clientY - rect.top;
      const cx = sim.panX ?? rect.width / 2, cy = sim.panY ?? rect.height / 2;
      sim.scale = Math.min(3.2, Math.max(0.28, sim.scale * factor));
      sim.panX = mx - (mx - cx) * factor;
      sim.panY = my - (my - cy) * factor;
    }, { passive: false });

    function selectNode(node) {
      selectedNode = node.id;
      if (node.ttl) selectedTtl = node.ttl;
      if (node.targets && node.targets.length) selectedTarget = node.targets[0];
      lastPanelKey = "";
      renderPanels(true);
    }

    function project3(x, y, z, W, H) {
      const cy = Math.cos(cam3.yaw), sy = Math.sin(cam3.yaw);
      const cp = Math.cos(cam3.pitch), sp = Math.sin(cam3.pitch);
      const x1 = x * cy - z * sy;
      const z1 = x * sy + z * cy;
      const y1 = y * cp - z1 * sp;
      const z2 = y * sp + z1 * cp + 260;
      const s = 240 / Math.max(48, z2);
      return { x: W * 0.5 + x1 * s, y: H * 0.78 - y1 * s, s, z: z2 };
    }

    function drawBox(ctx, corners, fill, stroke) {
      ctx.beginPath();
      ctx.moveTo(corners[0].x, corners[0].y);
      for (let i = 1; i < corners.length; i++) ctx.lineTo(corners[i].x, corners[i].y);
      ctx.closePath();
      ctx.fillStyle = fill;
      ctx.fill();
      ctx.strokeStyle = stroke || "rgba(255,255,255,.18)";
      ctx.lineWidth = 1;
      ctx.stroke();
    }

    function hopWorld(i, n) {
      const t = n <= 1 ? 0 : i / (n - 1);
      return { x: (t - 0.5) * 200, y: 0, z: 24 + t * 140 };
    }

    function hopHeight(hop) {
      return hop.rtt_avg_ms != null ? Math.min(86, 18 + hop.rtt_avg_ms * 0.55) : 14;
    }

    function face(ax, ay, az, bx, by, bz, cx, cy, cz, dx, dy, dz, w, h) {
      return [
        project3(ax, ay, az, w, h),
        project3(bx, by, bz, w, h),
        project3(cx, cy, cz, w, h),
        project3(dx, dy, dz, w, h),
      ];
    }

    function drawHop3d(route) {
      const { w, h } = resizeCanvas(hopCanvas, hctx);
      hctx.setTransform(1, 0, 0, 1, 0, 0);
      hctx.clearRect(0, 0, hopCanvas.width, hopCanvas.height);
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      hctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      hctx.fillStyle = "#070d16";
      hctx.fillRect(0, 0, w, h);
      if (cam3.auto && !cam3.dragging && !sim.frozen) cam3.yaw += 0.0016;
      const hops = (route && route.hops) || [];
      const n = hops.length;
      if (!n) {
        hctx.fillStyle = "#8b9bb4";
        hctx.font = "12px ui-sans-serif";
        hctx.fillText("Waiting for hops…", 16, h / 2);
        return;
      }
      hctx.strokeStyle = "rgba(148,176,210,.2)";
      hctx.lineWidth = 1;
      for (let g = -4; g <= 4; g++) {
        const a = project3(-130, 0, 8 + g * 24, w, h);
        const b = project3(130, 0, 8 + g * 24, w, h);
        hctx.beginPath(); hctx.moveTo(a.x, a.y); hctx.lineTo(b.x, b.y); hctx.stroke();
      }
      for (let g = -4; g <= 4; g++) {
        const a = project3(g * 28, 0, 8, w, h);
        const b = project3(g * 28, 0, 180, w, h);
        hctx.beginPath(); hctx.moveTo(a.x, a.y); hctx.lineTo(b.x, b.y); hctx.stroke();
      }
      const pts = hops.map((hop, i) => {
        const p = hopWorld(i, n);
        const height = hopHeight(hop);
        return { hop, i, p, height, pr: project3(p.x, height + 8, p.z, w, h) };
      });
      const ordered = pts.slice().sort((a, b) => b.pr.z - a.pr.z);
      for (let i = 0; i < n - 1; i++) {
        const a = pts[i].pr, b = pts[i + 1].pr;
        hctx.strokeStyle = hops[i + 1].slow ? "rgba(255,176,32,.85)" : "rgba(92,225,230,.55)";
        hctx.lineWidth = hops[i + 1].slow ? 2.6 : 1.6;
        hctx.beginPath(); hctx.moveTo(a.x, a.y); hctx.lineTo(b.x, b.y); hctx.stroke();
      }
      const t = (performance.now() / 1800) % 1;
      if (n > 1) {
        const seg = Math.min(n - 2, Math.floor(t * (n - 1)));
        const lt = (t * (n - 1)) - seg;
        const a = pts[seg].pr, b = pts[seg + 1].pr;
        hctx.beginPath();
        hctx.arc(a.x + (b.x - a.x) * lt, a.y + (b.y - a.y) * lt, 3.4, 0, Math.PI * 2);
        hctx.fillStyle = "#eef4ff";
        hctx.fill();
      }
      for (const item of ordered) {
        const hop = item.hop;
        const hw = 8, hd = 8, cap = 7;
        const y0 = 0, y1 = item.height, y2 = item.height + cap;
        const px = item.p.x, pz = item.p.z;
        const col = hop.slow ? "#ffb020" : healthColor(hop.health);
        const selected = selectedTtl === hop.ttl;
        const side = hop.slow ? "rgba(180,110,20,.85)" : "rgba(40,70,95,.9)";
        const frontC = hop.slow ? "rgba(255,176,32,.55)" : "rgba(70,110,140,.85)";
        drawBox(hctx, face(px + hw, y0, pz - hd, px + hw, y1, pz - hd, px + hw, y1, pz + hd, px + hw, y0, pz + hd, w, h), side);
        drawBox(hctx, face(px - hw, y0, pz + hd, px + hw, y0, pz + hd, px + hw, y1, pz + hd, px - hw, y1, pz + hd, w, h), frontC);
        drawBox(hctx, face(px - hw, y1, pz - hd, px + hw, y1, pz - hd, px + hw, y1, pz + hd, px - hw, y1, pz + hd, w, h), col);
        const rw = 6, rd = 6;
        drawBox(hctx, face(px + rw, y1, pz - rd, px + rw, y2, pz - rd, px + rw, y2, pz + rd, px + rw, y1, pz + rd, w, h), "rgba(20,30,42,.95)");
        drawBox(hctx, face(px - rw, y1, pz + rd, px + rw, y1, pz + rd, px + rw, y2, pz + rd, px - rw, y2, pz + rd, w, h), "rgba(36,52,70,.95)");
        drawBox(hctx, face(px - rw, y2, pz - rd, px + rw, y2, pz - rd, px + rw, y2, pz + rd, px - rw, y2, pz + rd, w, h), selected ? "#eef4ff" : col, selected ? "#ffffff" : "rgba(255,255,255,.35)");
        const label = "#" + hop.ttl + "  " + fmt(hop.rtt_avg_ms, 0) + " ms";
        const lx = (item.i % 2 === 0) ? item.pr.x + 12 : item.pr.x - 124;
        hctx.fillStyle = selected || hop.slow ? "#eef4ff" : "#c5d0e0";
        hctx.font = (selected || hop.slow ? "bold " : "") + "11px ui-sans-serif";
        hctx.fillText(label, lx, item.pr.y - 2);
        if (hop.slow || selected) {
          const host = hop.hostname || hop.ip || "no reply";
          const who = (hop.whois && (hop.whois.org || hop.whois.asn)) || (hop.geo && hop.geo.isp) || "";
          hctx.font = "10px ui-monospace, monospace";
          hctx.fillStyle = "#9aabc2";
          hctx.fillText(String(host).slice(0, 26), lx, item.pr.y + 12);
          if (who) hctx.fillText(String(who).slice(0, 26), lx, item.pr.y + 24);
          if (hop.added_ms != null && hop.slow) {
            hctx.fillStyle = "#ffb020";
            hctx.fillText("+" + fmt(hop.added_ms, 0) + " ms introduced", lx, item.pr.y + 36);
          }
        }
      }
    }

    hopCanvas.addEventListener("pointerdown", (e) => {
      cam3.dragging = true; cam3.auto = false;
      cam3.lastX = e.clientX; cam3.lastY = e.clientY;
      hopCanvas.setPointerCapture(e.pointerId);
      const route = currentRoute();
      if (!route) return;
      const rect = hopCanvas.getBoundingClientRect();
      const { w, h } = { w: rect.width, h: rect.height };
      const mx = e.clientX - rect.left, my = e.clientY - rect.top;
      let best = null, bestD = 28;
      route.hops.forEach((hop, i) => {
        const p = hopWorld(i, route.hops.length);
        const height = hopHeight(hop);
        const pr = project3(p.x, height, p.z, w, h);
        const d = Math.hypot(pr.x - mx, pr.y - my);
        if (d < bestD) { best = hop; bestD = d; }
      });
      if (best) {
        selectedTtl = best.ttl;
        selectedNode = best.ip ? ("ip:" + best.ip) : ("star:" + route.target + ":" + best.ttl);
        lastPanelKey = "";
        renderPanels(true);
      }
    });
    hopCanvas.addEventListener("pointermove", (e) => {
      if (!cam3.dragging) return;
      cam3.yaw += (e.clientX - cam3.lastX) * 0.01;
      cam3.pitch = Math.max(0.18, Math.min(1.05, cam3.pitch + (e.clientY - cam3.lastY) * 0.008));
      cam3.lastX = e.clientX; cam3.lastY = e.clientY;
    });
    hopCanvas.addEventListener("pointerup", () => { cam3.dragging = false; });
    hopCanvas.addEventListener("pointercancel", () => { cam3.dragging = false; });

    function drawTimeline(route) {
      const { w, h } = resizeCanvas(timeCanvas, tctx);
      tctx.setTransform(1, 0, 0, 1, 0, 0);
      tctx.clearRect(0, 0, timeCanvas.width, timeCanvas.height);
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      tctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      tctx.fillStyle = "#070d16";
      tctx.fillRect(0, 0, w, h);
      if (!route || !route.hops.length) return;
      const hops = route.hops;
      const left = 28, top = 8, right = w - 8, bottom = h - 8;
      const rowH = (bottom - top) / hops.length;
      hops.forEach((hop, i) => {
        const y = top + i * rowH;
        const samples = hop.timeline || [];
        const maxN = Math.max(24, samples.length);
        const cellW = (right - left) / maxN;
        samples.forEach((s, k) => {
          const x = left + k * cellW;
          let col = "#163042";
          if (s.rtt_avg_ms == null) col = "#ff6b7a";
          else if (s.loss_pct >= 20 || (hop.slow && s.rtt_avg_ms > 80)) col = "#ffb020";
          else col = "#1f6f58";
          tctx.fillStyle = col;
          const hh = s.rtt_avg_ms == null ? rowH - 2 : Math.max(3, Math.min(rowH - 2, (s.rtt_avg_ms / 180) * (rowH - 2)));
          tctx.fillRect(x, y + rowH - 2 - hh, Math.max(2, cellW - 1), hh);
        });
        if (selectedTtl === hop.ttl) {
          tctx.strokeStyle = "#5ce1e6";
          tctx.strokeRect(left, y, right - left, rowH);
        }
        tctx.fillStyle = hop.slow ? "#ffb020" : "#8b9bb4";
        tctx.font = "9px ui-sans-serif";
        tctx.fillText(String(hop.ttl), 6, y + rowH * 0.65);
      });
    }

    function renderPanels(force) {
      const route = currentRoute();
      const key = JSON.stringify({
        t: selectedTarget, ttl: selectedTtl, node: selectedNode, q: searchQ,
        g: snapshot && snapshot.generated_at, f: sim.frozen,
      });
      if (!force && key === lastPanelKey) return;
      lastPanelKey = key;
      const counts = $("counts");
      if (snapshot) {
        counts.innerHTML = (snapshot.demo_mode ? "Demo · " : "Live · ") +
          "<b>" + snapshot.target_count + "</b> targets · <b>" + snapshot.hop_count + "</b> hops · <b>" +
          (snapshot.slow_hop_count || 0) + "</b> slow · " + (snapshot.generated_at || "");
      }
      const tabs = $("route-tabs");
      tabs.innerHTML = (snapshot && snapshot.routes || []).map((r) =>
        "<button class='" + (r.target === (route && route.target) ? "" : "secondary") + "' data-t='" + esc(r.target) + "'>" +
        esc(r.target) + "</button>"
      ).join("");
      tabs.querySelectorAll("button").forEach((btn) => btn.onclick = () => {
        selectedTarget = btn.dataset.t; selectedTtl = null; lastPanelKey = ""; renderPanels(true);
      });
      const body = $("hops");
      if (!route) {
        body.innerHTML = "<tr><td colspan='6' class='mono'>No hops yet.</td></tr>";
      } else {
        body.innerHTML = route.hops.map((hop) => {
          const sel = hop.ttl === selectedTtl ? "selected" : "";
          const slow = hop.slow ? "slow" : "";
          const host = hop.hostname || hop.ip || "no reply";
          const added = hop.icmp_filtered ? "filt" : (hop.added_ms == null ? "—" : "+" + fmt(hop.added_ms, 0));
          const badge = hop.slow ? "slow" : hop.health;
          return "<tr class='" + sel + " " + slow + "' data-ttl='" + hop.ttl + "'>" +
            "<td>" + hop.ttl + "</td>" +
            "<td>" + esc(host) + "<div class='mono'>" + esc(hop.ip || "") + "</div></td>" +
            "<td>" + added + "</td>" +
            "<td>" + fmt(hop.rtt_last_ms || hop.rtt_avg_ms, 1) + "</td>" +
            "<td>" + fmt(hop.last_loss_pct, 0) + "%</td>" +
            "<td><span class='health " + esc(badge) + "'>" + esc(badge) + "</span></td></tr>";
        }).join("");
        body.querySelectorAll("tr").forEach((tr) => tr.onclick = () => {
          selectedTtl = Number(tr.dataset.ttl);
          const hop = route.hops.find((h) => h.ttl === selectedTtl);
          selectedNode = hop && hop.ip ? ("ip:" + hop.ip) : ("star:" + route.target + ":" + selectedTtl);
          lastPanelKey = ""; renderPanels(true);
        });
      }
      const problems = (route && route.problems) || [];
      const box = $("problem-box");
      if (!problems.length) {
        box.innerHTML = "";
      } else {
        box.innerHTML = problems.map((p) => {
          const bad = p.reason === "high-loss" || p.reason === "timeout";
          return "<div class='problem " + (bad ? "poor" : "") + "' data-ttl='" + p.ttl + "'>" +
            "<h3>Slow hop " + p.ttl + " · " + esc(p.provider || "Unknown operator") + "</h3>" +
            "<div class='meta'>" + esc(p.ip || "") + " · " + esc(p.asn || "") + " · " + esc(p.cidr || "") + "</div>" +
            "<p>" + esc(p.detail) + "</p></div>";
        }).join("");
        box.querySelectorAll(".problem").forEach((el) => el.onclick = () => {
          selectedTtl = Number(el.dataset.ttl); lastPanelKey = ""; renderPanels(true);
        });
      }
      $("inspect").innerHTML = inspectorHtml(route);
      $("events").innerHTML = (snapshot && snapshot.events || []).slice(-12).reverse().map((e) =>
        "<div>" + esc(e.at || "") + " · " + esc(e.message) + "</div>"
      ).join("");
      const st = snapshot && snapshot.speedtest;
      if (st) {
        $("speed-bar").style.width = (st.progress || 0) + "%";
        $("speed-msg").textContent = st.message || (st.status + (st.latency_ms != null ? " · " + st.latency_ms + " ms" : ""));
      }
      drawTimeline(route);
    }

    function inspectorHtml(route) {
      const hop = route && route.hops.find((h) => h.ttl === selectedTtl);
      const node = sim.byId.get(selectedNode);
      const src = hop || node;
      if (!src) return "<div class='hint'>Click a hop in the table, 3D path, or graph.</div>";
      const who = (hop && hop.whois) || {};
      const geo = (hop && hop.geo) || {};
      const rows = [
        ["Name", src.label || src.hostname || src.ip || "—"],
        ["IP", src.ip || "—"],
        ["TTL", src.ttl != null ? src.ttl : "—"],
        ["RTT", fmt(src.rtt_last_ms || src.rtt_avg_ms || src.rtt_ms) + " ms"],
        ["Added", src.added_ms != null ? ("+" + fmt(src.added_ms, 1) + " ms") : "—"],
        ["Loss", fmt(src.last_loss_pct || src.loss_pct, 0) + "%"],
        ["Health", src.health || "—"],
        ["Provider", who.org || src.provider || geo.isp || "—"],
        ["ASN", who.asn || src.asn || geo.asn || "—"],
        ["Prefix", who.cidr || "—"],
        ["Place", geo.place || src.place || [src.city, src.country].filter(Boolean).join(", ") || "—"],
        ["Abuse", who.abuse_email || "—"],
      ];
      let html = "<div class='kv'>" + rows.map((r) => "<span>" + esc(r[0]) + "</span><div>" + esc(r[1]) + "</div>").join("") + "</div>";
      if (hop && hop.icmp_filtered) html += "<p class='hint'>Silent hop with later replies — likely ICMP rate-limiting, not a down router.</p>";
      if (hop && hop.slow && hop.problem_reason) html += "<p class='hint'>Flagged as " + esc(hop.problem_reason) + ".</p>";
      return html;
    }

    async function startTrace() {
      const target = $("target-input").value.trim();
      if (!target) return;
      $("trace-btn").disabled = true;
      try {
        await fetch("/api/trace", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ target }) });
        selectedTarget = target;
      } finally { $("trace-btn").disabled = false; }
    }

    async function runTool(path, label) {
      const target = $("tool-input").value.trim();
      if (!target) return;
      $("tool-out").textContent = label + " " + target + "…";
      const res = await fetch("/api/" + path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ target }) });
      const data = await res.json();
      $("tool-out").textContent = JSON.stringify(data.result || data, null, 2);
    }

    $("trace-btn").onclick = startTrace;
    $("target-input").addEventListener("keydown", (e) => { if (e.key === "Enter") startTrace(); });
    $("search").addEventListener("input", (e) => { searchQ = e.target.value.trim().toLowerCase(); lastPanelKey = ""; });
    $("reheat").onclick = () => {
      sim.frozen = false; sim.alpha = 1; cam3.auto = true;
      for (const n of sim.nodes) { n.fx = null; n.fy = null; }
      $("freeze").textContent = "Freeze";
    };
    $("freeze").onclick = () => {
      sim.frozen = !sim.frozen;
      $("freeze").textContent = sim.frozen ? "Frozen" : "Freeze";
      cam3.auto = !sim.frozen;
    };
    $("speed-btn").onclick = () => fetch("/api/speedtest", { method: "POST" });
    $("tool-whois").onclick = () => runTool("whois", "WHOIS");
    $("tool-dns").onclick = () => runTool("dns", "DNS");
    $("tool-ports").onclick = () => runTool("ports", "Ports");
    $("tool-ping").onclick = () => runTool("ping", "Ping");

    function applySnapshot(data) {
      snapshot = data;
      if (!selectedTarget && data.routes && data.routes.length) selectedTarget = data.routes[0].target;
      syncGraph(data.graph);
      renderPanels(false);
    }

    function connect() {
      const es = new EventSource("/api/events");
      es.onmessage = (ev) => {
        try { applySnapshot(JSON.parse(ev.data)); } catch (err) { console.warn(err); }
      };
      es.onerror = () => { setTimeout(connect, 1500); es.close(); };
    }

    fetch("/api/state").then((r) => r.json()).then(applySnapshot).catch(() => {});
    connect();

    function frame() {
      tickForce();
      drawGraph();
      drawHop3d(currentRoute());
      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
    window.addEventListener("resize", () => { lastPanelKey = ""; });
  </script>
</body>
</html>
"""
