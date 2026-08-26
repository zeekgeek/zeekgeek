"""FastAPI dashboard: full-bleed force graph + traceroute HUD."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from .state import PathState


class TraceRequest(BaseModel):
    target: str = Field(min_length=1, max_length=255)


def create_app(state: PathState) -> FastAPI:
    app = FastAPI(title="Path Radar")

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return DASHBOARD_HTML

    @app.get("/api/snapshot")
    async def snapshot() -> dict:
        return await state.snapshot()

    @app.post("/api/trace")
    async def trace(request: TraceRequest) -> JSONResponse:
        event = await state.set_target(request.target)
        return JSONResponse({"target": state.target, "event": event})

    @app.get("/api/events")
    async def events() -> StreamingResponse:
        return StreamingResponse(_event_stream(state), media_type="text/event-stream")

    return app


async def _event_stream(state: PathState) -> AsyncIterator[str]:
    last_payload = ""
    while True:
        snapshot = await state.snapshot()
        payload = json.dumps(snapshot)
        if payload != last_payload:
            yield f"data: {payload}\n\n"
            last_payload = payload
        await asyncio.sleep(0.7)


DASHBOARD_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Path Radar</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #05070d;
      --ink: #eef3ff;
      --muted: #8b97b3;
      --line: rgba(255,255,255,.08);
      --cyan: #3ee0d4;
      --mint: #9dffce;
      --blue: #5aa8ff;
      --violet: #9b8cff;
      --amber: #ffb020;
      --rose: #ff5d7a;
      --ok: #3ee0d4;
      --warn: #ffb020;
      --slow: #ff5d7a;
      --glass: rgba(8, 12, 22, .72);
      --font: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
      --mono: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
    }
    * { box-sizing: border-box; }
    html, body { margin: 0; height: 100%; overflow: hidden; background: var(--bg); color: var(--ink); font-family: var(--font); }
    #graph { position: fixed; inset: 0; width: 100%; height: 100%; display: block; z-index: 0; cursor: grab; }
    #graph.drag { cursor: grabbing; }
    .vignette {
      position: fixed; inset: 0; z-index: 1; pointer-events: none;
      background:
        radial-gradient(1200px 700px at 10% -10%, rgba(62,224,212,.07), transparent 50%),
        radial-gradient(900px 500px at 110% 10%, rgba(155,140,255,.08), transparent 46%),
        radial-gradient(800px 400px at 80% 110%, rgba(255,93,122,.06), transparent 50%),
        linear-gradient(180deg, rgba(5,7,13,.55) 0%, transparent 14%, transparent 78%, rgba(5,7,13,.7) 100%);
    }
    .hud {
      position: fixed; z-index: 3;
      background: var(--glass);
      border: 1px solid var(--line);
      box-shadow: 0 18px 50px rgba(0,0,0,.35);
      backdrop-filter: blur(18px) saturate(1.35);
      -webkit-backdrop-filter: blur(18px) saturate(1.35);
    }
    header.hud {
      top: 14px; left: 14px; right: 14px;
      display: flex; align-items: center; gap: 14px; flex-wrap: wrap;
      padding: 10px 14px; border-radius: 16px;
    }
    .brand { display: flex; align-items: center; gap: 10px; min-width: 170px; }
    .logo {
      width: 34px; height: 34px; border-radius: 10px;
      background: linear-gradient(135deg, var(--cyan), var(--violet));
      display: grid; place-items: center; font-weight: 800; color: #041016; letter-spacing: -0.08em;
    }
    h1 { margin: 0; font-size: 16px; letter-spacing: .02em; }
    .tag { margin: 0; color: var(--muted); font-size: 11px; }
    form#trace-form { display: flex; gap: 8px; flex: 1; min-width: 220px; }
    input, button {
      font: inherit; color: var(--ink);
    }
    input[type=text], input[type=search] {
      background: rgba(255,255,255,.04);
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 8px 12px;
      outline: none;
      min-width: 0;
      flex: 1;
    }
    input:focus { border-color: rgba(62,224,212,.45); box-shadow: 0 0 0 3px rgba(62,224,212,.12); }
    button {
      background: var(--cyan); color: #041016; border: 0; border-radius: 10px;
      padding: 8px 12px; font-weight: 700; cursor: pointer; white-space: nowrap;
    }
    button.ghost {
      background: rgba(255,255,255,.05); color: var(--ink); border: 1px solid var(--line);
    }
    button.ghost.on { border-color: var(--amber); color: var(--amber); }
    .controls { display: flex; gap: 8px; flex-wrap: wrap; }
    .chip {
      border: 1px solid var(--line); border-radius: 999px; padding: 6px 10px;
      font-size: 12px; color: var(--muted); background: rgba(255,255,255,.03);
    }
    .chip b { color: var(--ink); font-weight: 700; }
    .chip.fair b, .chip.poor b { color: var(--amber); }
    .chip.critical b, .chip.down b, .chip.slow b { color: var(--rose); }
    .chip.excellent b, .chip.good b { color: var(--mint); }
    .chip.live { border-color: rgba(62,224,212,.45); }
    aside.left {
      top: 82px; left: 14px; bottom: 210px; width: min(360px, 38vw);
      border-radius: 16px; padding: 12px; display: flex; flex-direction: column; min-height: 0;
    }
    aside.right {
      top: 82px; right: 14px; bottom: 210px; width: min(340px, 36vw);
      border-radius: 16px; padding: 12px; overflow: auto; min-height: 0;
    }
    footer.hud {
      left: 14px; right: 14px; bottom: 14px; height: 184px;
      border-radius: 16px; padding: 10px 12px 8px;
      display: flex; flex-direction: column;
    }
    h2 { margin: 0 0 8px; font-size: 12px; letter-spacing: .12em; text-transform: uppercase; color: var(--muted); font-weight: 700; }
    .panel-head { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }
    #hops { overflow: auto; display: flex; flex-direction: column; gap: 4px; padding-right: 4px; }
    .hop {
      display: grid; grid-template-columns: 28px 1fr auto; gap: 8px; align-items: center;
      width: 100%; text-align: left; background: rgba(255,255,255,.03);
      border: 1px solid transparent; border-radius: 12px; padding: 7px 8px; color: inherit;
    }
    .hop:hover { border-color: rgba(255,255,255,.12); }
    .hop.sel { border-color: var(--cyan); background: rgba(62,224,212,.08); }
    .hop.slow, .hop.loss, .hop.timeout { border-color: rgba(255,93,122,.45); background: rgba(255,93,122,.08); }
    .hop.warn { border-color: rgba(255,176,32,.35); }
    .hop.filtered { opacity: .7; }
    .hop .n {
      width: 26px; height: 26px; border-radius: 50%; display: grid; place-items: center;
      font-size: 11px; font-weight: 800; background: rgba(255,255,255,.06);
    }
    .hop.slow .n, .hop.loss .n, .hop.timeout .n { background: var(--rose); color: #1a0408; }
    .hop.ok .n { background: rgba(62,224,212,.18); color: var(--cyan); }
    .name { font-weight: 700; font-size: 12.5px; display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .meta { color: var(--muted); font-size: 11px; font-family: var(--mono); display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .rtt { text-align: right; font-variant-numeric: tabular-nums; }
    .rtt b { display: block; font-size: 13px; }
    .rtt small { color: var(--muted); font-size: 10px; }
    .hop.slow .rtt b, .hop.loss .rtt b { color: var(--rose); }
    .spark { width: 72px; height: 22px; display: block; margin-left: auto; }
    .spark path { fill: none; stroke: var(--cyan); stroke-width: 1.4; }
    .hop.slow .spark path { stroke: var(--rose); }
    .card {
      border: 1px solid var(--line); border-radius: 12px; padding: 10px; margin-bottom: 10px;
      background: rgba(255,255,255,.03);
    }
    .card.alert { border-color: rgba(255,93,122,.4); background: rgba(255,93,122,.08); }
    .card h3 { margin: 0 0 6px; font-size: 14px; }
    .kv { display: grid; grid-template-columns: 92px 1fr; gap: 4px 8px; font-size: 12px; }
    .kv span { color: var(--muted); }
    .kv b { font-weight: 650; word-break: break-word; }
    .notes { font-size: 12.5px; line-height: 1.45; color: #d5dcf0; margin: 8px 0 0; }
    .issues { margin: 8px 0 0; padding-left: 16px; color: var(--muted); font-size: 12px; }
    .heat-head { display: flex; justify-content: space-between; align-items: center; gap: 10px; }
    #heat { width: 100%; flex: 1; display: block; }
    .legend { display: flex; gap: 10px; font-size: 11px; color: var(--muted); }
    .legend i { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 4px; vertical-align: middle; }
    .empty { color: var(--muted); font-size: 13px; padding: 20px 8px; text-align: center; }
    .badge { display: inline-block; border-radius: 999px; padding: 2px 7px; font-size: 10px; font-weight: 800; letter-spacing: .04em; }
    .badge.slow { background: rgba(255,93,122,.2); color: var(--rose); }
    .badge.ok { background: rgba(62,224,212,.16); color: var(--cyan); }
    #tip {
      position: fixed; z-index: 4; pointer-events: none; display: none;
      background: rgba(8,12,22,.92); border: 1px solid var(--line); border-radius: 10px;
      padding: 8px 10px; font-size: 12px; max-width: 260px;
      box-shadow: 0 10px 30px rgba(0,0,0,.4);
    }
    @media (max-width: 980px) {
      aside.left, aside.right { bottom: auto; height: 34vh; width: calc(50% - 20px); }
      aside.right { left: auto; }
      footer.hud { height: 150px; }
    }
    @media (max-width: 720px) {
      aside.right { display: none; }
      aside.left { width: calc(100% - 28px); height: 30vh; }
    }
  </style>
</head>
<body>
  <canvas id="graph" aria-label="Network topology graph"></canvas>
  <div class="vignette"></div>
  <header class="hud">
    <div class="brand">
      <div class="logo">PR</div>
      <div>
        <h1>Path Radar</h1>
        <p class="tag">Scanny map · PingPlotter hops</p>
      </div>
    </div>
    <form id="trace-form" autocomplete="off">
      <input id="target" type="text" spellcheck="false" placeholder="Host or IP — 1.1.1.1, 8.8.8.8, github.com">
    </form>
    <button id="trace-btn" type="submit" form="trace-form">Trace</button>
    <input id="search" type="search" placeholder="Search nodes, ASN, city…" aria-label="Search graph">
    <div class="controls">
      <button class="ghost" id="reheat" type="button">Reheat</button>
      <button class="ghost" id="freeze" type="button">Freeze</button>
      <button class="ghost" id="fit" type="button">Fit</button>
    </div>
    <span class="chip" id="status">Waiting for probes…</span>
  </header>
  <aside class="hud left">
    <div class="panel-head">
      <h2>Hop chain</h2>
      <span id="hop-summary" class="tag"></span>
    </div>
    <div id="hops" class="empty">Waiting for traceroute…</div>
  </aside>
  <aside class="hud right">
    <h2>Problem router</h2>
    <div id="problem">No slow hop yet.</div>
    <h2>Inspector</h2>
    <div id="inspect" class="empty">Click a node or hop.</div>
  </aside>
  <footer class="hud">
    <div class="heat-head">
      <h2>Latency over time</h2>
      <div class="legend">
        <span><i style="background:#3ee0d4"></i>fast</span>
        <span><i style="background:#ffb020"></i>slow</span>
        <span><i style="background:#ff5d7a"></i>problem</span>
        <span><i style="background:#1a1520"></i>timeout</span>
      </div>
    </div>
    <canvas id="heat"></canvas>
  </footer>
  <div id="tip"></div>
<script>
(function () {
  const canvas = document.getElementById("graph");
  const ctx = canvas.getContext("2d", { alpha: false, desynchronized: true });
  const heat = document.getElementById("heat");
  const hctx = heat.getContext("2d");
  const hopsEl = document.getElementById("hops");
  const problemEl = document.getElementById("problem");
  const inspectEl = document.getElementById("inspect");
  const statusEl = document.getElementById("status");
  const hopSummary = document.getElementById("hop-summary");
  const targetEl = document.getElementById("target");
  const searchEl = document.getElementById("search");
  const tip = document.getElementById("tip");
  const freezeBtn = document.getElementById("freeze");

  const KIND = {
    host: "#5aa8ff", gateway: "#3ee0d4", device: "#9b8cff", ap: "#7dffc3",
    access: "#6ea8ff", metro: "#8b9cff", peering: "#ffb020", transit: "#ff8a5b",
    ix: "#3ee0d4", anycast: "#9dffce", dns: "#e8f07a"
  };
  const HEALTH = { ok: "#3ee0d4", warn: "#ffb020", slow: "#ff5d7a", loss: "#ff5d7a", timeout: "#6b7280", filtered: "#64748b" };

  let W = 0, H = 0, dpr = 1;
  let nodes = [];
  let links = [];
  let hops = [];
  let snapshot = null;
  let selected = null;
  let hover = null;
  let query = "";
  let frozen = false;
  let alpha = 1;
  let didFit = false;
  const T = { x: 0, y: 0, k: 1 };
  const mouse = { x: 0, y: 0, down: false, pan: false, drag: null, lx: 0, ly: 0 };

  function resize() {
    dpr = Math.min(2, window.devicePixelRatio || 1);
    W = canvas.clientWidth;
    H = canvas.clientHeight;
    const pw = Math.max(1, Math.floor(W * dpr));
    const ph = Math.max(1, Math.floor(H * dpr));
    if (canvas.width !== pw || canvas.height !== ph) {
      canvas.width = pw;
      canvas.height = ph;
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const hw = Math.max(1, Math.floor(heat.clientWidth * dpr));
    const hh = Math.max(1, Math.floor(heat.clientHeight * dpr));
    if (heat.width !== hw || heat.height !== hh) {
      heat.width = hw;
      heat.height = hh;
    }
  }

  function toScreen(x, y) { return [x * T.k + T.x, y * T.k + T.y]; }
  function toWorld(sx, sy) { return [(sx - T.x) / T.k, (sy - T.y) / T.k]; }

  function radius(n) {
    if (n.kind === "host" || n.kind === "anycast" || n.kind === "dns") return 16;
    if (n.kind === "gateway") return 15;
    if (n.kind === "peering" || n.kind === "transit") return 13;
    if (n.kind === "device" || n.kind === "ap") return 10;
    return 12;
  }

  function mergeGraph(graph) {
    const prev = new Map(nodes.map((n) => [n.id, n]));
    const cx = (W || 800) * 0.42;
    const cy = (H || 600) * 0.42;
    nodes = (graph.nodes || []).map((raw, i) => {
      const old = prev.get(raw.id);
      const layer = raw.layer == null ? 3 : raw.layer;
      const tx = 80 + layer * 150;
      const ty = cy + (hash(raw.id) % 80) - 40;
      if (old) {
        Object.assign(old, raw);
        old.r = radius(old);
        old.tx = tx;
        old.ty = ty;
        return old;
      }
      return {
        ...raw,
        x: tx + ((hash(raw.id) % 30) - 15),
        y: ty,
        vx: 0,
        vy: 0,
        fx: null,
        fy: null,
        r: radius(raw),
        tx,
        ty
      };
    });
    const byId = new Map(nodes.map((n) => [n.id, n]));
    links = (graph.links || []).map((l) => ({
      ...l,
      s: byId.get(l.source),
      t: byId.get(l.target)
    })).filter((l) => l.s && l.t);
    if (!didFit && nodes.length) {
      for (let i = 0; i < 40; i++) tick(0.4);
      fit();
      didFit = true;
    }
  }

  function hash(s) {
    let h = 0;
    for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
    return Math.abs(h);
  }

  function tick(a) {
    const n = nodes.length;
    const charge = 520;
    for (let i = 0; i < n; i++) {
      const A = nodes[i];
      for (let j = i + 1; j < n; j++) {
        const B = nodes[j];
        let dx = B.x - A.x, dy = B.y - A.y;
        let d2 = dx * dx + dy * dy || 1;
        const f = (charge * a) / d2;
        const dist = Math.sqrt(d2);
        dx /= dist; dy /= dist;
        if (A.fx == null) { A.vx -= dx * f; A.vy -= dy * f; }
        if (B.fx == null) { B.vx += dx * f; B.vy += dy * f; }
      }
    }
    for (const l of links) {
      const s = l.s, t = l.t;
      let dx = t.x - s.x, dy = t.y - s.y;
      const dist = Math.hypot(dx, dy) || 1;
      const desired = l.kind === "lan" ? 70 : 96;
      const k = ((dist - desired) / dist) * 0.08 * a;
      dx *= k; dy *= k;
      if (s.fx == null) { s.vx += dx; s.vy += dy; }
      if (t.fx == null) { t.vx -= dx; t.vy -= dy; }
    }
    for (const node of nodes) {
      node.vx += (node.tx - node.x) * 0.045 * a;
      node.vy += (node.ty - node.y) * 0.02 * a;
      if (node.fx == null) {
        node.vx *= 0.72;
        node.vy *= 0.72;
        node.x += node.vx;
        node.y += node.vy;
      } else {
        node.x = node.fx;
        node.y = node.fy;
        node.vx = 0;
        node.vy = 0;
      }
    }
  }

  function fit() {
    if (!nodes.length) return;
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const n of nodes) {
      minX = Math.min(minX, n.x); maxX = Math.max(maxX, n.x);
      minY = Math.min(minY, n.y); maxY = Math.max(maxY, n.y);
    }
    const bw = Math.max(80, maxX - minX);
    const bh = Math.max(80, maxY - minY);
    const k = Math.min((W - 420) / bw, (H - 320) / bh, 1.45);
    T.k = Math.max(0.35, k);
    T.x = W * 0.52 - ((minX + maxX) / 2) * T.k;
    T.y = H * 0.42 - ((minY + maxY) / 2) * T.k;
  }

  function hit(sx, sy) {
    const [wx, wy] = toWorld(sx, sy);
    for (let i = nodes.length - 1; i >= 0; i--) {
      const n = nodes[i];
      const dx = wx - n.x, dy = wy - n.y;
      if (dx * dx + dy * dy <= (n.r + 4) * (n.r + 4)) return n;
    }
    return null;
  }

  function draw(now) {
    ctx.fillStyle = "#05070d";
    ctx.fillRect(0, 0, W, H);
    drawGrid();
    const q = query;
    for (const n of nodes) {
      const hay = (n.search || "") + " " + (n.label || "") + " " + (n.ip || "");
      n._match = !q || hay.includes(q);
    }
    ctx.lineCap = "round";
    for (const l of links) {
      const [x1, y1] = toScreen(l.s.x, l.s.y);
      const [x2, y2] = toScreen(l.t.x, l.t.y);
      const dim = q && !(l.s._match && l.t._match);
      const health = l.health || "ok";
      ctx.globalAlpha = dim ? 0.08 : (l.active === false ? 0.28 : 0.85);
      ctx.strokeStyle = HEALTH[health] || "#5aa8ff";
      ctx.lineWidth = (l.problem ? 2.6 : 1.4) * Math.min(T.k, 1.6);
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.lineTo(x2, y2);
      ctx.stroke();
      if (!dim && T.k > 0.7 && l.label) {
        const mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
        ctx.globalAlpha = 0.9;
        ctx.font = "10px ui-monospace, SF Mono, Menlo, monospace";
        ctx.fillStyle = health === "slow" ? "#ffb4c0" : "#9aa6c2";
        ctx.textAlign = "center";
        ctx.fillText(l.label, mx, my - 4);
      }
    }
    ctx.globalAlpha = 1;
    for (const n of nodes) drawNode(n, now);
    ctx.globalAlpha = 1;
  }

  function drawGrid() {
    const step = 48;
    ctx.strokeStyle = "rgba(255,255,255,0.035)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let x = (T.x % step); x < W; x += step) { ctx.moveTo(x, 0); ctx.lineTo(x, H); }
    for (let y = (T.y % step); y < H; y += step) { ctx.moveTo(0, y); ctx.lineTo(W, y); }
    ctx.stroke();
  }

  function drawNode(n, now) {
    const [sx, sy] = toScreen(n.x, n.y);
    if (sx < -50 || sy < -50 || sx > W + 50 || sy > H + 50) return;
    const dim = query && !n._match;
    ctx.globalAlpha = dim ? 0.12 : (n.active ? 1 : 0.7);
    const pulse = n.problem ? 1 + 0.1 * Math.sin(now / 180) : 1;
    const r = n.r * Math.min(T.k, 1.8) * pulse;
    const color = n.problem ? "#ff5d7a" : (KIND[n.kind] || "#5aa8ff");
    if (n.problem || n === selected || (query && n._match)) {
      ctx.beginPath();
      ctx.arc(sx, sy, r + 8, 0, Math.PI * 2);
      ctx.fillStyle = n.problem ? "rgba(255,93,122,.18)" : "rgba(62,224,212,.16)";
      ctx.fill();
    }
    ctx.beginPath();
    ctx.arc(sx, sy, r, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();
    ctx.lineWidth = n === selected ? 2.4 : 1;
    ctx.strokeStyle = n === selected ? "#eef3ff" : "rgba(0,0,0,.35)";
    ctx.stroke();
    ctx.fillStyle = "#041016";
    ctx.font = "700 9px " + getComputedStyle(document.body).fontFamily;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    const mark = n.hop ? String(n.hop) : (n.kind === "host" ? "you" : n.kind.slice(0, 2));
    ctx.fillText(mark, sx, sy);
    if (!dim && T.k > 0.55) {
      ctx.fillStyle = "#eef3ff";
      ctx.font = "11px " + getComputedStyle(document.body).fontFamily;
      ctx.textBaseline = "top";
      ctx.fillText(n.label || n.ip || "", sx, sy + r + 4);
    }
  }

  function loop(now) {
    resize();
    if (!frozen && alpha > 0.002) {
      tick(alpha);
      alpha *= 0.988;
    }
    draw(now);
    requestAnimationFrame(loop);
  }

  canvas.addEventListener("pointerdown", (e) => {
    const n = hit(e.offsetX, e.offsetY);
    mouse.down = true;
    mouse.lx = e.offsetX;
    mouse.ly = e.offsetY;
    if (n) {
      mouse.drag = n;
      n.fx = n.x; n.fy = n.y;
      select(n.id);
      canvas.setPointerCapture(e.pointerId);
    } else {
      mouse.pan = true;
      canvas.classList.add("drag");
      canvas.setPointerCapture(e.pointerId);
    }
  });
  canvas.addEventListener("pointermove", (e) => {
    mouse.x = e.offsetX; mouse.y = e.offsetY;
    const n = hit(e.offsetX, e.offsetY);
    hover = n;
    canvas.style.cursor = n ? "pointer" : (mouse.pan ? "grabbing" : "grab");
    if (n) {
      tip.style.display = "block";
      tip.style.left = (e.clientX + 14) + "px";
      tip.style.top = (e.clientY + 14) + "px";
      tip.innerHTML = "<b>" + esc(n.label) + "</b><br>" + esc(n.ip || "") +
        (n.provider ? "<br>" + esc(n.provider) : "") +
        (n.rtt_ms != null ? "<br>" + n.rtt_ms.toFixed(1) + " ms" : "") +
        (n.added_ms != null ? " · +" + n.added_ms.toFixed(0) + " ms added" : "");
    } else {
      tip.style.display = "none";
    }
    if (mouse.drag) {
      const [wx, wy] = toWorld(e.offsetX, e.offsetY);
      mouse.drag.fx = wx; mouse.drag.fy = wy;
      if (!frozen) alpha = Math.max(alpha, 0.25);
    } else if (mouse.pan) {
      T.x += e.offsetX - mouse.lx;
      T.y += e.offsetY - mouse.ly;
    }
    mouse.lx = e.offsetX; mouse.ly = e.offsetY;
  });
  canvas.addEventListener("pointerup", () => {
    mouse.down = false; mouse.pan = false; mouse.drag = null;
    canvas.classList.remove("drag");
  });
  canvas.addEventListener("dblclick", (e) => {
    const n = hit(e.offsetX, e.offsetY);
    if (n) { n.fx = null; n.fy = null; if (!frozen) alpha = 0.6; }
  });
  canvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.08 : 0.92;
    const k = Math.min(4, Math.max(0.25, T.k * factor));
    const [wx, wy] = toWorld(e.offsetX, e.offsetY);
    T.k = k;
    T.x = e.offsetX - wx * T.k;
    T.y = e.offsetY - wy * T.k;
  }, { passive: false });

  document.getElementById("reheat").onclick = () => { frozen = false; alpha = 1; freezeBtn.classList.remove("on"); freezeBtn.textContent = "Freeze"; };
  freezeBtn.onclick = () => {
    frozen = !frozen;
    if (frozen) { alpha = 0; freezeBtn.classList.add("on"); freezeBtn.textContent = "Frozen"; }
    else { alpha = 0.8; freezeBtn.classList.remove("on"); freezeBtn.textContent = "Freeze"; }
  };
  document.getElementById("fit").onclick = fit;
  searchEl.addEventListener("input", () => { query = searchEl.value.trim().toLowerCase(); });
  document.addEventListener("keydown", (e) => {
    if (e.key === "/" && document.activeElement.tagName !== "INPUT") { e.preventDefault(); searchEl.focus(); }
    if (e.key === "Escape") { searchEl.value = ""; query = ""; selected = null; renderInspect(); }
    if (e.key === "r" && document.activeElement.tagName !== "INPUT") { frozen = false; alpha = 1; }
    if (e.key === "f" && document.activeElement.tagName !== "INPUT") freezeBtn.click();
  });

  document.getElementById("trace-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const target = targetEl.value.trim();
    if (!target) return;
    await fetch("/api/trace", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ target }) });
  });

  hopsEl.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-id]");
    if (btn) select(btn.getAttribute("data-id"));
  });

  function select(id) {
    selected = id;
    const n = nodes.find((x) => x.id === id);
    if (n && !frozen) alpha = Math.max(alpha, 0.15);
    renderHops();
    renderInspect();
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  function fmt(ms) { return ms == null ? "—" : (ms < 10 ? ms.toFixed(1) : ms.toFixed(0)) + " ms"; }

  function spark(hist) {
    if (!hist || !hist.length) return "";
    const w = 74, h = 20;
    const max = Math.max(20, ...hist.filter((v) => v != null));
    const step = w / Math.max(1, hist.length - 1);
    let d = "", drawing = false;
    hist.forEach((v, i) => {
      if (v == null) { drawing = false; return; }
      const x = i * step, y = h - 1 - (v / max) * (h - 2);
      d += (drawing ? "L" : "M") + x.toFixed(1) + "," + y.toFixed(1);
      drawing = true;
    });
    return '<svg class="spark" viewBox="0 0 ' + w + ' ' + h + '"><path d="' + d + '"/></svg>';
  }

  function renderHops() {
    if (!hops.length) { hopsEl.innerHTML = '<div class="empty">Waiting for traceroute…</div>'; return; }
    hopsEl.innerHTML = hops.map((h) => {
      const cls = "hop " + h.health + (h.id === selected ? " sel" : "");
      const added = h.added_ms != null ? (h.added_ms >= 1 ? "+" + h.added_ms.toFixed(0) + " ms" : "on path") : "";
      return '<button class="' + cls + '" data-id="' + esc(h.id) + '" type="button">' +
        '<span class="n">' + h.hop + "</span>" +
        '<span><span class="name">' + esc(h.hostname || h.ip || "timeout") + "</span>" +
        '<span class="meta">' + esc((h.ip || "*") + (h.provider ? " · " + h.provider : "") + (h.city ? " · " + h.city : "")) + "</span></span>" +
        '<span class="rtt"><b>' + fmt(h.rtt_ms) + "</b><small>" + added + "</small>" + spark(h.history) + "</span></button>";
    }).join("");
  }

  function renderProblem(pr) {
    if (!pr) { problemEl.innerHTML = '<div class="empty">Path is clean — no hop is introducing delay.</div>'; return; }
    const p = pr.provider_detail || {};
    problemEl.innerHTML = '<div class="card alert">' +
      '<div class="badge slow">SLOW HOP ' + pr.hop + "</div>" +
      "<h3>" + esc(pr.hostname || pr.label || pr.ip) + "</h3>" +
      '<div class="kv">' +
      "<span>IP</span><b>" + esc(pr.ip || "—") + "</b>" +
      "<span>Provider</span><b>" + esc((p.name || pr.provider || "Unknown") + (p.aka ? " (" + p.aka + ")" : "")) + "</b>" +
      "<span>ASN</span><b>" + esc(p.asn || pr.asn || "—") + "</b>" +
      "<span>Where</span><b>" + esc([pr.city, pr.facility].filter(Boolean).join(" · ") || "—") + "</b>" +
      "<span>Added</span><b>" + fmt(pr.added_ms) + "</b>" +
      "<span>Current</span><b>" + fmt(pr.rtt_ms) + "</b>" +
      "<span>Min / avg / max</span><b>" + [fmt(pr.min_ms), fmt(pr.avg_ms), fmt(pr.max_ms)].join(" · ") + "</b>" +
      "<span>Jitter</span><b>" + fmt(pr.jitter_ms) + "</b>" +
      "<span>Loss</span><b>" + (pr.loss_pct != null ? pr.loss_pct.toFixed(1) + "%" : "—") + "</b>" +
      "<span>NOC</span><b>" + esc(p.noc || "—") + "</b>" +
      "<span>Looking glass</span><b>" + esc(p.looking_glass || "—") + "</b>" +
      "<span>RIR / prefix</span><b>" + esc([p.rir, p.prefix].filter(Boolean).join(" · ") || "—") + "</b>" +
      "</div>" +
      '<p class="notes">' + esc(pr.reason || "") + " " + esc(p.notes || pr.notes || "") + "</p>" +
      (p.typical_issues && p.typical_issues.length
        ? "<ul class='issues'>" + p.typical_issues.map((x) => "<li>" + esc(x) + "</li>").join("") + "</ul>"
        : "") +
      "</div>";
  }

  function renderInspect() {
    const n = nodes.find((x) => x.id === selected) || hops.find((x) => x.id === selected);
    if (!n) { inspectEl.innerHTML = '<div class="empty">Click a node or hop.</div>'; return; }
    inspectEl.innerHTML = '<div class="card">' +
      "<h3>" + esc(n.hostname || n.label || n.ip) + "</h3>" +
      '<div class="kv">' +
      "<span>Kind</span><b>" + esc(n.kind || n.role || "—") + "</b>" +
      "<span>IP</span><b>" + esc(n.ip || "—") + "</b>" +
      "<span>Hop</span><b>" + esc(n.hop || "LAN") + "</b>" +
      "<span>Health</span><b>" + esc(n.health || "ok") + "</b>" +
      "<span>RTT</span><b>" + fmt(n.rtt_ms) + "</b>" +
      "<span>Added</span><b>" + fmt(n.added_ms) + "</b>" +
      "<span>Loss</span><b>" + (n.loss_pct != null ? Number(n.loss_pct).toFixed(1) + "%" : "—") + "</b>" +
      "<span>Jitter</span><b>" + fmt(n.jitter_ms) + "</b>" +
      "<span>Provider</span><b>" + esc(n.provider || n.as_name || "—") + "</b>" +
      "<span>ASN</span><b>" + esc(n.asn || "—") + "</b>" +
      "<span>City</span><b>" + esc(n.city || "—") + "</b>" +
      "<span>Country</span><b>" + esc(n.country || "—") + "</b>" +
      "<span>Facility</span><b>" + esc(n.facility || "—") + "</b>" +
      "</div>" +
      (n.notes || n.reason ? '<p class="notes">' + esc(n.reason || n.notes) + "</p>" : "") +
      "</div>";
  }

  function drawHeat(hm) {
    const w = heat.clientWidth, h = heat.clientHeight;
    hctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    hctx.clearRect(0, 0, w, h);
    if (!hm || !hm.rows || !hm.rows.length) return;
    const labelW = 86;
    const rows = hm.rows;
    const cols = hm.columns || (rows[0].cells || []).length || 1;
    const rowH = Math.min(18, (h - 4) / rows.length);
    const cellW = (w - labelW - 6) / cols;
    rows.forEach((row, ri) => {
      const y = ri * rowH;
      hctx.fillStyle = row.health === "slow" || row.health === "loss" ? "#ff5d7a" : "#8b97b3";
      hctx.font = "10px ui-monospace, SF Mono, Menlo, monospace";
      hctx.textBaseline = "middle";
      hctx.fillText((row.hop + " " + (row.label || "")).slice(0, 14), 0, y + rowH / 2);
      (row.cells || []).forEach((ms, ci) => {
        hctx.fillStyle = heatColor(ms);
        hctx.fillRect(labelW + ci * cellW, y + 1, Math.max(1, cellW - 0.5), rowH - 2);
      });
    });
  }

  function heatColor(ms) {
    if (ms == null) return "#16101a";
    const t = Math.max(0, Math.min(1, ms / 180));
    const hue = 155 - t * 155;
    const lit = 52 - t * 16;
    return "hsl(" + hue + ", 80%, " + lit + "%)";
  }

  function apply(data) {
    snapshot = data;
    hops = data.hops || [];
    targetEl.placeholder = data.target || "1.1.1.1";
    if (document.activeElement !== targetEl && !targetEl.value) targetEl.value = data.target || "";
    const q = data.quality || {};
    const grade = q.grade || "down";
    statusEl.className = "chip " + grade + (data.source === "live" ? " live" : "");
    statusEl.innerHTML = "<b>" + (data.source === "live" ? "LIVE · " : "") + grade.toUpperCase() + "</b> · " + fmt(q.end_to_end_ms) +
      " · " + (q.hop_count || 0) + " hops · " + (q.problem_count || 0) + " slow · " +
      (data.source || "") + " · #" + (data.probe_count || 0);
    hopSummary.textContent = (q.destination || data.target || "") + (q.top_problem ? " · bottleneck hop " + q.top_problem.hop : "");
    if (data.graph) mergeGraph(data.graph);
    renderHops();
    renderProblem(data.problem_router);
    if (!selected && data.problem_router) selected = data.problem_router.node_id;
    renderInspect();
    drawHeat(data.heatmap);
  }

  async function boot() {
    try {
      const res = await fetch("/api/snapshot");
      apply(await res.json());
    } catch (err) {}
    try {
      const es = new EventSource("/api/events");
      es.onmessage = (ev) => { try { apply(JSON.parse(ev.data)); } catch (err) {} };
    } catch (err) {
      setInterval(async () => {
        const res = await fetch("/api/snapshot");
        apply(await res.json());
      }, 1000);
    }
  }

  requestAnimationFrame(loop);
  boot();
})();
</script>
</body>
</html>
"""
