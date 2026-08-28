"""FastAPI dashboard for the Bitcoin market radar."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse

from .state import MarketState


def create_app(state: MarketState) -> FastAPI:
    app = FastAPI(title="Bitcoin Market Radar")

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return DASHBOARD_HTML

    @app.get("/api/snapshot")
    async def snapshot() -> dict:
        return await state.snapshot()

    @app.get("/api/events")
    async def events() -> StreamingResponse:
        return StreamingResponse(_event_stream(state), media_type="text/event-stream")

    return app


async def _event_stream(state: MarketState) -> AsyncIterator[str]:
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
  <title>Bitcoin Market Radar</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #07080d;
      --panel: #10141c;
      --panel-2: #161c28;
      --line: #243044;
      --text: #eef3ff;
      --muted: #8b9bb8;
      --btc: #f7931a;
      --green: #22c55e;
      --red: #f43f5e;
      --blue: #38bdf8;
      --violet: #a78bfa;
      --gold: #eab308;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif;
      background:
        radial-gradient(1200px 500px at 10% -10%, rgba(247,147,26,.12), transparent 50%),
        radial-gradient(900px 400px at 90% 0%, rgba(56,189,248,.08), transparent 45%),
        var(--bg);
      color: var(--text);
    }
    header {
      padding: 18px 24px 10px;
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: flex-start;
      flex-wrap: wrap;
    }
    h1 { margin: 0; font-size: 22px; letter-spacing: -.02em; }
    h1 span { color: var(--btc); }
    .sub { color: var(--muted); font-size: 13px; margin-top: 4px; }
    .chips { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
    .chip {
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 999px;
      padding: 6px 11px;
      font-size: 12px;
      color: var(--muted);
      font-weight: 700;
    }
    .chip b { color: var(--text); }
    .chip.live { color: var(--green); border-color: rgba(34,197,94,.35); }
    .chip.demo { color: var(--btc); border-color: rgba(247,147,26,.4); }
    .chip.risk-on { color: var(--green); }
    .chip.risk-off { color: var(--red); }
    .chip.mixed, .chip.unknown { color: var(--gold); }
    main { padding: 8px 24px 28px; display: grid; gap: 14px; }
    .hero {
      display: grid;
      grid-template-columns: minmax(280px, 1.2fr) minmax(220px, .9fr) minmax(240px, .9fr);
      gap: 14px;
    }
    .panel {
      background: linear-gradient(180deg, rgba(255,255,255,.02), transparent 40%), var(--panel);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 14px 16px;
      box-shadow: 0 18px 40px rgba(0,0,0,.28);
    }
    .kicker { font-size: 11px; letter-spacing: .14em; text-transform: uppercase; color: var(--muted); font-weight: 800; }
    .btc-price { font-size: 42px; font-weight: 800; letter-spacing: -.03em; margin: 6px 0 2px; }
    .delta { font-weight: 800; font-size: 15px; }
    .up { color: var(--green); }
    .down { color: var(--red); }
    .flat { color: var(--muted); }
    .meta { display: flex; gap: 14px; flex-wrap: wrap; color: var(--muted); font-size: 13px; margin-top: 8px; }
    .meta b { color: var(--text); }
    canvas { width: 100%; height: 88px; display: block; }
    .health-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 8px; }
    .stat {
      background: var(--panel-2);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 10px;
    }
    .stat .v { font-size: 20px; font-weight: 800; }
    .stat .l { font-size: 11px; color: var(--muted); margin-top: 2px; }
    .fng-bar { height: 10px; border-radius: 999px; background: linear-gradient(90deg, #f43f5e, #eab308, #22c55e); position: relative; margin-top: 12px; }
    .fng-bar i {
      position: absolute; top: -4px; width: 4px; height: 18px; background: #fff; border-radius: 2px;
      transform: translateX(-50%);
    }
    .row-3 { display: grid; grid-template-columns: 1.4fr .9fr .8fr; gap: 14px; }
    .tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(132px, 1fr)); gap: 8px; }
    .tile {
      background: var(--panel-2);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 10px;
      min-height: 92px;
    }
    .tile .sym { font-weight: 800; font-size: 13px; }
    .tile .px { font-size: 15px; font-weight: 700; margin-top: 6px; }
    .tile .ch { font-size: 12px; font-weight: 800; margin-top: 4px; }
    .eq-table { width: 100%; border-collapse: collapse; font-size: 13px; }
    .eq-table th { text-align: left; color: var(--muted); font-size: 11px; letter-spacing: .08em; text-transform: uppercase; padding: 6px 4px; }
    .eq-table td { padding: 7px 4px; border-top: 1px solid #1c2738; }
    .eq-table tr:hover td { background: rgba(255,255,255,.02); }
    .right { text-align: right; font-variant-numeric: tabular-nums; }
    .events { max-height: 340px; overflow: auto; display: grid; gap: 8px; }
    .event { background: var(--panel-2); border: 1px solid var(--line); border-radius: 10px; padding: 8px 10px; }
    .event .t { font-weight: 800; font-size: 13px; }
    .event .d { color: var(--muted); font-size: 12px; margin-top: 3px; }
    .event .when { color: #6d7c96; font-size: 11px; margin-top: 4px; }
    .ideas { display: grid; gap: 8px; }
    .idea { background: var(--panel-2); border: 1px solid var(--line); border-radius: 10px; padding: 9px 10px; }
    .idea b { display: block; font-size: 13px; }
    .idea span { display: block; color: var(--muted); font-size: 12px; margin-top: 3px; }
    h2 { margin: 0 0 10px; font-size: 15px; }
    .split { display: flex; justify-content: space-between; gap: 8px; align-items: baseline; }
    .tiny { font-size: 12px; color: var(--muted); }
    .empty { color: var(--muted); text-align: center; padding: 28px 8px; }
    .movers { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    .mover { display: flex; justify-content: space-between; gap: 8px; font-size: 13px; padding: 6px 0; border-bottom: 1px solid #1c2738; }
    @media (max-width: 1100px) {
      .hero, .row-3 { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1><span>Bitcoin</span> Market Radar</h1>
      <div class="sub">Crypto board + equity/macro health. Not investment advice — a local tape of public prices.</div>
    </div>
    <div class="chips">
      <span class="chip" id="mode-chip">starting</span>
      <span class="chip" id="regime-chip">health: —</span>
      <span class="chip" id="updated-chip">waiting for quotes</span>
    </div>
  </header>
  <main>
    <section class="hero">
      <div class="panel">
        <div class="kicker">Bitcoin</div>
        <div class="btc-price" id="btc-price">—</div>
        <div id="btc-delta" class="delta flat">24h — · 7d —</div>
        <canvas id="btc-spark" width="640" height="88"></canvas>
        <div class="meta">
          <span>Cap <b id="btc-cap">—</b></span>
          <span>Vol <b id="btc-vol">—</b></span>
          <span>Dom <b id="btc-dom">—</b></span>
          <span>Halving <b id="halving">—</b></span>
        </div>
      </div>
      <div class="panel">
        <div class="kicker">Market health</div>
        <div class="health-grid">
          <div class="stat"><div class="v" id="health-score">—</div><div class="l">Composite 0–100</div></div>
          <div class="stat"><div class="v" id="health-regime">—</div><div class="l" id="health-div">vs SPY</div></div>
          <div class="stat"><div class="v" id="breadth">—</div><div class="l">Crypto breadth (24h green)</div></div>
          <div class="stat"><div class="v" id="altseason">—</div><div class="l">Alt vs BTC (7d)</div></div>
        </div>
      </div>
      <div class="panel">
        <div class="kicker">Fear &amp; greed</div>
        <div class="btc-price" id="fng-value" style="font-size:36px">—</div>
        <div class="delta" id="fng-label">waiting</div>
        <div class="fng-bar"><i id="fng-needle"></i></div>
        <div class="meta" style="margin-top:14px">
          <span>Total crypto <b id="total-cap">—</b></span>
          <span>24h <b id="total-chg">—</b></span>
          <span>Stables <b id="stables">—</b></span>
        </div>
      </div>
    </section>

    <section class="row-3">
      <div class="panel">
        <div class="split"><h2>Crypto board</h2><span class="tiny">24h heat · tap a tile</span></div>
        <div class="tiles" id="crypto-tiles"></div>
      </div>
      <div class="panel">
        <div class="split"><h2>Equity &amp; macro health</h2><span class="tiny">Yahoo / demo</span></div>
        <table class="eq-table">
          <thead><tr><th>Name</th><th class="right">Last</th><th class="right">24h</th></tr></thead>
          <tbody id="equity-body"></tbody>
        </table>
      </div>
      <div class="panel">
        <h2>Tape</h2>
        <div class="movers" style="margin-bottom:12px">
          <div>
            <div class="kicker">Gainers</div>
            <div id="gainers"></div>
          </div>
          <div>
            <div class="kicker">Losers</div>
            <div id="losers"></div>
          </div>
        </div>
        <div class="kicker">Events</div>
        <div class="events" id="events"><div class="empty">No events yet.</div></div>
      </div>
    </section>

    <section class="panel">
      <div class="split">
        <h2>Good next modules</h2>
        <span class="tiny">Ideas to grow this radar — ask for any of these next</span>
      </div>
      <div class="ideas" id="ideas" style="grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));"></div>
    </section>
  </main>
  <script>
    const $ = (id) => document.getElementById(id);

    function fmtPrice(n) {
      if (n == null || Number.isNaN(n)) return "—";
      const abs = Math.abs(n);
      if (abs >= 1000) return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
      if (abs >= 1) return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
      if (abs >= 0.01) return n.toLocaleString(undefined, { maximumFractionDigits: 4 });
      return n.toLocaleString(undefined, { maximumFractionDigits: 8 });
    }
    function fmtPct(n) {
      if (n == null || Number.isNaN(n)) return "—";
      const sign = n > 0 ? "+" : "";
      return sign + n.toFixed(2) + "%";
    }
    function fmtCap(n) {
      if (n == null || Number.isNaN(n)) return "—";
      const abs = Math.abs(n);
      if (abs >= 1e12) return "$" + (n / 1e12).toFixed(2) + "T";
      if (abs >= 1e9) return "$" + (n / 1e9).toFixed(2) + "B";
      if (abs >= 1e6) return "$" + (n / 1e6).toFixed(1) + "M";
      return "$" + n.toFixed(0);
    }
    function cls(n) {
      if (n == null) return "flat";
      if (n > 0.02) return "up";
      if (n < -0.02) return "down";
      return "flat";
    }
    function heat(n) {
      if (n == null) return "rgba(36,48,68,.6)";
      const mag = Math.min(Math.abs(n) / 8, 1);
      if (n >= 0) return `rgba(34,197,94,${0.12 + mag * 0.45})`;
      return `rgba(244,63,94,${0.12 + mag * 0.45})`;
    }

    function sparkline(canvas, series, color) {
      const ctx = canvas.getContext("2d");
      const w = canvas.width, h = canvas.height;
      ctx.clearRect(0, 0, w, h);
      const vals = (series || []).filter((v) => typeof v === "number");
      if (vals.length < 2) return;
      const min = Math.min(...vals), max = Math.max(...vals);
      const span = max - min || 1;
      ctx.beginPath();
      vals.forEach((v, i) => {
        const x = (i / (vals.length - 1)) * (w - 8) + 4;
        const y = h - 8 - ((v - min) / span) * (h - 16);
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      ctx.strokeStyle = color || "#f7931a";
      ctx.lineWidth = 2;
      ctx.stroke();
    }

    function moverList(items) {
      if (!items || !items.length) return '<div class="tiny">—</div>';
      return items.map((q) =>
        `<div class="mover"><span>${q.symbol}</span><b class="${cls(q.change_24h)}">${fmtPct(q.change_24h)}</b></div>`
      ).join("");
    }

    function render(data) {
      const btc = data.bitcoin || {};
      const health = data.health || {};
      const mode = data.mode || "starting";
      $("mode-chip").textContent = mode === "demo" ? "DEMO" : (data.source === "crypto-only" ? "LIVE crypto" : "LIVE");
      $("mode-chip").className = "chip " + (mode === "demo" ? "demo" : "live");
      const regime = health.regime || "unknown";
      $("regime-chip").textContent = "health: " + regime + (health.score != null ? " " + health.score : "");
      $("regime-chip").className = "chip " + regime;
      $("updated-chip").textContent = data.updated_at ? ("updated " + data.updated_at.replace("T", " ") + "Z") : "waiting";

      $("btc-price").textContent = btc.price != null ? "$" + fmtPrice(btc.price) : "—";
      $("btc-delta").innerHTML =
        `<span class="${cls(btc.change_24h)}">24h ${fmtPct(btc.change_24h)}</span> · ` +
        `<span class="${cls(btc.change_7d)}">7d ${fmtPct(btc.change_7d)}</span>`;
      $("btc-cap").textContent = fmtCap(btc.market_cap);
      $("btc-vol").textContent = fmtCap(btc.volume);
      $("btc-dom").textContent = data.global && data.global.btc_dominance != null
        ? data.global.btc_dominance.toFixed(1) + "%" : "—";
      $("halving").textContent = (data.halving && data.halving.label) || "—";
      const spark = (btc.sparkline && btc.sparkline.length ? btc.sparkline : (data.btc_history || []).map((p) => p.price));
      sparkline($("btc-spark"), spark, btc.change_24h != null && btc.change_24h < 0 ? "#f43f5e" : "#f7931a");

      $("health-score").textContent = health.score != null ? health.score.toFixed(1) : "—";
      $("health-regime").textContent = regime;
      $("health-regime").className = "v " + cls(regime === "risk-on" ? 1 : regime === "risk-off" ? -1 : 0);
      $("health-div").textContent = health.divergence ? ("vs SPY: " + health.divergence) : "vs SPY: in step / quiet";
      const br = health.breadth || {};
      $("breadth").textContent = br.pct_green != null ? (br.green + "/" + br.n + "  " + br.pct_green.toFixed(0) + "%") : "—";
      const alt = health.altseason || {};
      $("altseason").textContent = alt.label || "—";

      const fng = data.fear_greed || {};
      $("fng-value").textContent = fng.value != null ? Math.round(fng.value) : "—";
      $("fng-label").textContent = fng.label || fng.band || "—";
      $("fng-needle").style.left = (fng.value != null ? fng.value : 50) + "%";
      $("total-cap").textContent = fmtCap(data.global && data.global.total_market_cap);
      const ch = data.global && data.global.market_cap_change_24h;
      $("total-chg").textContent = fmtPct(ch);
      $("total-chg").className = cls(ch);
      $("stables").textContent = fmtCap(data.global && data.global.stablecoin_cap);

      const tiles = (data.cryptos || []).filter((q) => q.symbol !== "BTC").map((q) => `
        <div class="tile" style="background:${heat(q.change_24h)}">
          <div class="sym">${q.symbol}</div>
          <div class="tiny">${q.name}</div>
          <div class="px">$${fmtPrice(q.price)}</div>
          <div class="ch ${cls(q.change_24h)}">${fmtPct(q.change_24h)}</div>
        </div>`).join("");
      $("crypto-tiles").innerHTML = tiles || '<div class="empty">No crypto quotes yet.</div>';

      const groups = data.equities || {};
      const rows = []
        .concat(groups.indices || [])
        .concat(groups.mega || [])
        .concat(groups.macro || []);
      $("equity-body").innerHTML = rows.map((q) => `
        <tr>
          <td><b>${q.symbol}</b> <span class="tiny">${q.name}</span></td>
          <td class="right">${fmtPrice(q.price)}</td>
          <td class="right ${cls(q.change_24h)}">${fmtPct(q.change_24h)}</td>
        </tr>`).join("");

      $("gainers").innerHTML = moverList(data.gainers);
      $("losers").innerHTML = moverList(data.losers);
      const events = data.events || [];
      $("events").innerHTML = events.length ? events.map((e) => `
        <div class="event">
          <div class="t">${e.title || e.kind}</div>
          <div class="d">${e.detail || ""}</div>
          <div class="when">${e.ts || ""}</div>
        </div>`).join("") : '<div class="empty">No events yet.</div>';

      $("ideas").innerHTML = (data.roadmap || []).map((idea) => `
        <div class="idea"><b>${idea.title}</b><span>${idea.blurb}</span></div>
      `).join("");
    }

    async function boot() {
      try {
        const res = await fetch("/api/snapshot");
        render(await res.json());
      } catch (err) {
        console.warn(err);
      }
      const src = new EventSource("/api/events");
      src.onmessage = (ev) => {
        try { render(JSON.parse(ev.data)); } catch (err) { console.warn(err); }
      };
    }
    boot();
  </script>
</body>
</html>
"""
