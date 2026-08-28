"""FastAPI dashboard for crypto and equity market health."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse

from .state import MarketState


def create_app(state: MarketState) -> FastAPI:
    app = FastAPI(title="Market Radar")

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return DASHBOARD_HTML

    @app.get("/api/market")
    async def market() -> dict:
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
  <title>Market Radar — Bitcoin &amp; Market Health</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #07090f;
      --panel: #0e1420;
      --panel-2: #131c2c;
      --line: #1f2d45;
      --text: #edf2ff;
      --muted: #8fa0be;
      --btc: #f7931a;
      --green: #22c55e;
      --red: #ef4444;
      --blue: #38bdf8;
      --violet: #a78bfa;
      --amber: #f59e0b;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif;
      background: radial-gradient(1200px 500px at 0% -10%, rgba(247,147,26,.12), transparent 55%),
                  radial-gradient(900px 400px at 100% 0%, rgba(56,189,248,.08), transparent 50%),
                  var(--bg);
      color: var(--text);
    }
    header {
      padding: 20px 24px 14px;
      border-bottom: 1px solid var(--line);
      display: flex;
      justify-content: space-between;
      gap: 16px;
      flex-wrap: wrap;
      align-items: flex-start;
    }
    h1 { margin: 0; font-size: 22px; letter-spacing: -0.02em; }
    .sub { color: var(--muted); font-size: 14px; margin-top: 4px; }
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      border-radius: 999px;
      padding: 4px 10px;
      font-size: 12px;
      font-weight: 700;
      border: 1px solid var(--line);
      background: var(--panel);
      color: var(--muted);
    }
    .badge.live { color: #86efac; border-color: rgba(34,197,94,.35); }
    .badge.demo { color: #fde68a; border-color: rgba(245,158,11,.35); }
    main { padding: 16px 24px 28px; display: grid; gap: 16px; }
    .hero {
      display: grid;
      grid-template-columns: 1.4fr 1fr;
      gap: 16px;
    }
    .panel {
      background: rgba(14,20,32,.85);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 16px 18px;
      box-shadow: 0 18px 50px rgba(0,0,0,.28);
    }
    .btc-hero {
      display: grid;
      gap: 10px;
      background: linear-gradient(135deg, rgba(247,147,26,.14), rgba(14,20,32,.9) 45%);
      border-color: rgba(247,147,26,.28);
    }
    .btc-label { color: var(--btc); font-size: 13px; font-weight: 700; text-transform: uppercase; letter-spacing: .08em; }
    .btc-price { font-size: clamp(2rem, 5vw, 3.2rem); font-weight: 800; line-height: 1.05; font-variant-numeric: tabular-nums; }
    .btc-change { font-size: 18px; font-weight: 700; }
    .btc-change.up { color: var(--green); }
    .btc-change.down { color: var(--red); }
    .btc-meta { display: flex; gap: 18px; flex-wrap: wrap; color: var(--muted); font-size: 14px; }
    .btc-meta b { color: var(--text); }
    .health-score {
      display: grid;
      gap: 12px;
      align-content: start;
    }
    .score-ring {
      width: 120px; height: 120px;
      border-radius: 50%;
      display: grid; place-items: center;
      margin: 0 auto;
      background: conic-gradient(var(--blue) calc(var(--score) * 1%), #1a2740 0);
      position: relative;
    }
    .score-ring::after {
      content: "";
      position: absolute;
      inset: 10px;
      border-radius: 50%;
      background: var(--panel);
    }
    .score-value {
      position: relative;
      z-index: 1;
      font-size: 28px;
      font-weight: 800;
      font-variant-numeric: tabular-nums;
    }
    .posture {
      text-align: center;
      font-size: 15px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: .06em;
    }
    .posture.risk-on { color: var(--green); }
    .posture.mixed { color: var(--amber); }
    .posture.risk-off { color: var(--red); }
    .chips { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; }
    .chip {
      font-size: 12px;
      color: var(--muted);
      border: 1px solid var(--line);
      background: var(--panel-2);
      border-radius: 999px;
      padding: 4px 10px;
    }
    .chip b { color: var(--text); }
    .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
    h2 { margin: 0 0 12px; font-size: 15px; color: var(--muted); text-transform: uppercase; letter-spacing: .08em; }
    table { width: 100%; border-collapse: collapse; font-size: 14px; }
    th, td { padding: 8px 6px; border-bottom: 1px solid rgba(31,45,69,.65); text-align: left; }
    th { color: var(--muted); font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: .05em; }
    td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
    tr:hover td { background: rgba(56,189,248,.04); }
    .sym { font-weight: 700; }
    .name { color: var(--muted); font-size: 12px; }
    .chg.up { color: var(--green); font-weight: 700; }
    .chg.down { color: var(--red); font-weight: 700; }
    .chg.flat { color: var(--muted); }
    canvas.spark { width: 88px; height: 28px; display: block; margin-left: auto; }
    .global-row {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 12px;
    }
    .stat-card {
      background: var(--panel-2);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 12px 14px;
    }
    .stat-card .label { color: var(--muted); font-size: 12px; margin-bottom: 4px; }
    .stat-card .value { font-size: 20px; font-weight: 800; font-variant-numeric: tabular-nums; }
    .events {
      max-height: 140px;
      overflow: auto;
      font-size: 13px;
      color: var(--muted);
    }
    .events div { padding: 4px 0; border-bottom: 1px dashed rgba(31,45,69,.5); }
    .empty { color: var(--muted); text-align: center; padding: 28px 0; }
    .cat { font-size: 11px; color: var(--violet); text-transform: uppercase; letter-spacing: .05em; }
    @media (max-width: 980px) {
      .hero, .grid-2, .global-row { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Market Radar</h1>
      <div class="sub">Bitcoin, top crypto, and equities health at a glance</div>
    </div>
    <div>
      <span class="badge" id="source-badge">connecting…</span>
      <div class="sub" id="updated-at" style="margin-top:8px;text-align:right"></div>
    </div>
  </header>

  <main>
    <section class="hero">
      <div class="panel btc-hero" id="btc-hero">
        <div class="btc-label">Bitcoin</div>
        <div class="btc-price" id="btc-price">—</div>
        <div class="btc-change flat" id="btc-change">—</div>
        <div class="btc-meta" id="btc-meta"></div>
      </div>
      <div class="panel health-score" id="health-panel">
        <h2>Market Health</h2>
        <div class="score-ring" id="score-ring" style="--score:50">
          <div class="score-value" id="health-score">—</div>
        </div>
        <div class="posture mixed" id="health-posture">—</div>
        <div class="chips" id="health-chips"></div>
      </div>
    </section>

    <section class="panel">
      <h2>Global Crypto</h2>
      <div class="global-row" id="global-stats">
        <div class="stat-card"><div class="label">Total Market Cap</div><div class="value">—</div></div>
        <div class="stat-card"><div class="label">24h Volume</div><div class="value">—</div></div>
        <div class="stat-card"><div class="label">BTC Dominance</div><div class="value">—</div></div>
        <div class="stat-card"><div class="label">Mkt Cap Δ 24h</div><div class="value">—</div></div>
      </div>
    </section>

    <section class="grid-2">
      <div class="panel">
        <h2>Top Cryptocurrencies</h2>
        <div style="overflow:auto;max-height:62vh">
          <table id="crypto-table">
            <thead>
              <tr>
                <th>#</th><th>Asset</th><th class="num">Price</th><th class="num">24h</th><th class="num">Trend</th>
              </tr>
            </thead>
            <tbody><tr><td colspan="5" class="empty">Waiting for quotes…</td></tr></tbody>
          </table>
        </div>
      </div>
      <div class="panel">
        <h2>Equities &amp; Macro</h2>
        <div style="overflow:auto;max-height:62vh">
          <table id="stock-table">
            <thead>
              <tr>
                <th>Symbol</th><th>Name</th><th class="num">Price</th><th class="num">24h</th><th class="num">Trend</th>
              </tr>
            </thead>
            <tbody><tr><td colspan="5" class="empty">Waiting for quotes…</td></tr></tbody>
          </table>
        </div>
      </div>
    </section>

    <section class="panel">
      <h2>System Events</h2>
      <div class="events" id="events"><div class="empty">No events yet.</div></div>
    </section>
  </main>

  <script>
    const fmtUsd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 });
    const fmtUsdCompact = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', notation: 'compact', maximumFractionDigits: 2 });
    const fmtPct = new Intl.NumberFormat('en-US', { signDisplay: 'always', minimumFractionDigits: 2, maximumFractionDigits: 2 });

    function chgClass(v) {
      if (v == null || Number.isNaN(v)) return 'flat';
      if (v > 0.05) return 'up';
      if (v < -0.05) return 'down';
      return 'flat';
    }

    function fmtPrice(v, assetClass) {
      if (v == null) return '—';
      if (assetClass === 'crypto' && v < 1) return fmtUsd.format(v);
      if (v >= 1000) return fmtUsd.format(v);
      return fmtUsd.format(v);
    }

    function drawSpark(canvas, series, positive) {
      if (!canvas || !series || series.length < 2) return;
      const ctx = canvas.getContext('2d');
      const w = canvas.width = 88;
      const h = canvas.height = 28;
      ctx.clearRect(0, 0, w, h);
      const min = Math.min(...series);
      const max = Math.max(...series);
      const span = max - min || 1;
      ctx.strokeStyle = positive ? '#22c55e' : '#ef4444';
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      series.forEach((v, i) => {
        const x = (i / (series.length - 1)) * (w - 4) + 2;
        const y = h - 2 - ((v - min) / span) * (h - 4);
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      ctx.stroke();
    }

    function renderGlobal(global) {
      const root = document.getElementById('global-stats');
      if (!global) {
        root.innerHTML = '<div class="empty">Global stats unavailable.</div>';
        return;
      }
      const cards = [
        ['Total Market Cap', global.total_market_cap_usd != null ? fmtUsdCompact.format(global.total_market_cap_usd) : '—'],
        ['24h Volume', global.total_volume_24h_usd != null ? fmtUsdCompact.format(global.total_volume_24h_usd) : '—'],
        ['BTC Dominance', global.btc_dominance != null ? global.btc_dominance.toFixed(1) + '%' : '—'],
        ['Mkt Cap Δ 24h', global.market_cap_change_24h_pct != null ? fmtPct.format(global.market_cap_change_24h_pct) + '%' : '—'],
      ];
      root.innerHTML = cards.map(([label, value]) =>
        `<div class="stat-card"><div class="label">${label}</div><div class="value">${value}</div></div>`
      ).join('');
    }

    function renderTable(tbody, rows, history, mode) {
      if (!rows.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="empty">No data.</td></tr>';
        return;
      }
      tbody.innerHTML = rows.map(row => {
        const cls = chgClass(row.change_pct_24h);
        const hist = (history[row.symbol] || []);
        const id = `spark-${mode}-${row.symbol.replace(/[^a-z0-9]/gi, '')}`;
        const left = mode === 'crypto'
          ? `<td>${row.rank ?? ''}</td><td><div class="sym">${row.name}</div><div class="name">${row.symbol}</div></td>`
          : `<td class="sym">${row.symbol}</td><td><div>${row.name}</div><div class="cat">${row.category || ''}</div></td>`;
        return `<tr>
          ${left}
          <td class="num">${fmtPrice(row.price, row.asset_class)}</td>
          <td class="num chg ${cls}">${row.change_pct_24h != null ? fmtPct.format(row.change_pct_24h) + '%' : '—'}</td>
          <td class="num"><canvas class="spark" id="${id}"></canvas></td>
        </tr>`;
      }).join('');
      rows.forEach(row => {
        const id = `spark-${mode}-${row.symbol.replace(/[^a-z0-9]/gi, '')}`;
        const canvas = document.getElementById(id);
        const hist = history[row.symbol] || [];
        drawSpark(canvas, hist, (row.change_pct_24h || 0) >= 0);
      });
    }

    function render(snapshot) {
      const badge = document.getElementById('source-badge');
      badge.textContent = snapshot.source === 'live' ? '● Live feeds' : '● Demo mode';
      badge.className = 'badge ' + (snapshot.source === 'live' ? 'live' : 'demo');
      document.getElementById('updated-at').textContent = snapshot.updated_at ? 'Updated ' + snapshot.updated_at : '';

      const btc = snapshot.bitcoin;
      if (btc) {
        document.getElementById('btc-price').textContent = fmtUsd.format(btc.price);
        const chg = document.getElementById('btc-change');
        const cls = chgClass(btc.change_pct_24h);
        chg.className = 'btc-change ' + cls;
        chg.textContent = btc.change_pct_24h != null ? fmtPct.format(btc.change_pct_24h) + '% (24h)' : '—';
        document.getElementById('btc-meta').innerHTML = `
          <span>Rank <b>#${btc.rank ?? 1}</b></span>
          <span>Mkt cap <b>${btc.market_cap_usd ? fmtUsdCompact.format(btc.market_cap_usd) : '—'}</b></span>
          <span>Vol 24h <b>${btc.volume_24h_usd ? fmtUsdCompact.format(btc.volume_24h_usd) : '—'}</b></span>`;
      }

      const health = snapshot.health || {};
      document.getElementById('health-score').textContent = health.score != null ? Math.round(health.score) : '—';
      document.getElementById('score-ring').style.setProperty('--score', health.score ?? 50);
      const posture = document.getElementById('health-posture');
      posture.textContent = health.posture ? health.posture.replace('-', ' ') : '—';
      posture.className = 'posture ' + (health.posture || 'mixed');
      const chips = [
        health.crypto_breadth_pct != null ? `Crypto <b>${health.crypto_breadth_pct}%</b> green` : null,
        health.stock_breadth_pct != null ? `Stocks <b>${health.stock_breadth_pct}%</b> green` : null,
        health.vix != null ? `VIX <b>${health.vix.toFixed(2)}</b> (${health.vix_regime})` : null,
        health.btc_dominance_pct != null ? `BTC dom <b>${health.btc_dominance_pct.toFixed(1)}%</b>` : null,
      ].filter(Boolean);
      document.getElementById('health-chips').innerHTML = chips.map(c => `<span class="chip">${c}</span>`).join('');

      renderGlobal(snapshot.global);
      renderTable(
        document.querySelector('#crypto-table tbody'),
        snapshot.cryptos || [],
        (snapshot.history && snapshot.history.crypto) || {},
        'crypto'
      );
      renderTable(
        document.querySelector('#stock-table tbody'),
        snapshot.stocks || [],
        (snapshot.history && snapshot.history.stocks) || {},
        'stock'
      );

      const events = snapshot.events || [];
      const eventsEl = document.getElementById('events');
      if (!events.length) {
        eventsEl.innerHTML = '<div class="empty">No events yet.</div>';
      } else {
        eventsEl.innerHTML = events.slice(0, 12).map(e =>
          `<div><b>${e.type}</b> — ${e.message} <span style="opacity:.7">(${e.at})</span></div>`
        ).join('');
      }
    }

    async function bootstrap() {
      try {
        const res = await fetch('/api/market');
        render(await res.json());
      } catch (err) {
        console.error(err);
      }
      const source = new EventSource('/api/events');
      source.onmessage = (evt) => {
        try { render(JSON.parse(evt.data)); } catch (e) { console.error(e); }
      };
    }
    bootstrap();
  </script>
</body>
</html>
"""
