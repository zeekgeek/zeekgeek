"""FastAPI dashboard for the crypto market radar."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse

from .state import MarketState


def create_app(state: MarketState) -> FastAPI:
    app = FastAPI(title="Crypto Market Radar")

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
  <title>Crypto Market Radar</title>
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
      --btc: #f7931a;
    }
    body { margin: 0; font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif; background: var(--bg); color: var(--text); }
    header { padding: 16px 26px; border-bottom: 1px solid #1f2c45; display: flex; justify-content: space-between; gap: 18px; align-items: center; flex-wrap: wrap; }
    h1 { font-size: 21px; margin: 0; }
    h2 { margin: 0 0 10px 0; font-size: 16px; }
    .hero { display: flex; gap: 22px; align-items: baseline; flex-wrap: wrap; }
    .btc-price { font-size: 34px; font-weight: 800; color: var(--btc); font-variant-numeric: tabular-nums; }
    .btc-change { font-size: 17px; font-weight: 700; }
    .stats { display: flex; gap: 16px; color: var(--muted); font-size: 13px; flex-wrap: wrap; margin-top: 4px; }
    .stats b { color: var(--text); }
    .chip { border-radius: 999px; padding: 4px 12px; font-size: 13px; font-weight: 700; }
    .chip.live { background: rgba(34,197,94,.15); color: var(--green); }
    .chip.demo { background: rgba(234,179,8,.16); color: var(--gold); }
    #alarm-banner { display: none; background: #7f1d1d; color: #fecaca; padding: 10px 26px; font-weight: 800; letter-spacing: .03em; }
    #alarm-banner.active { display: block; animation: pulse 1.2s ease-in-out infinite; }
    @keyframes pulse { 50% { opacity: .55; } }
    main { display: grid; grid-template-columns: minmax(320px, 390px) 1fr; gap: 16px; padding: 16px; align-items: start; }
    .panel { background: var(--panel); border: 1px solid #1f2c45; border-radius: 14px; padding: 14px; box-shadow: 0 16px 40px rgba(0,0,0,.3); }
    .stack { display: grid; gap: 16px; }
    .health-score { font-size: 42px; font-weight: 800; font-variant-numeric: tabular-nums; }
    .health-label { font-size: 15px; font-weight: 700; text-transform: uppercase; letter-spacing: .06em; }
    .health-head { display: flex; align-items: baseline; gap: 14px; margin-bottom: 8px; }
    .bar-row { display: grid; grid-template-columns: 92px 1fr 38px; gap: 8px; align-items: center; font-size: 13px; color: var(--muted); margin: 7px 0; }
    .bar { height: 9px; background: #0a1220; border-radius: 999px; overflow: hidden; border: 1px solid #1f2c45; }
    .bar i { display: block; height: 100%; border-radius: 999px; transition: width .6s ease, background .6s ease; }
    .kv { display: grid; grid-template-columns: 1fr auto; gap: 6px 12px; font-size: 14px; }
    .kv span { color: var(--muted); }
    .kv b { font-variant-numeric: tabular-nums; text-align: right; }
    .movers div { display: flex; justify-content: space-between; gap: 10px; padding: 5px 0; font-size: 14px; border-bottom: 1px dashed #1c2942; }
    .movers div:last-child { border-bottom: 0; }
    .events { max-height: 230px; overflow: auto; color: var(--muted); font-size: 13px; }
    .events p { margin: 5px 0; }
    .events .alarm-line { color: #fecaca; font-weight: 700; }
    .events .up-line { color: #bbf7d0; }
    .events .down-line { color: #fecaca; }
    canvas { width: 100%; display: block; }
    #btc-chart { height: 230px; background: #050c18; border: 1px solid #1f2c45; border-radius: 12px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(215px, 1fr)); gap: 10px; }
    .card { background: var(--panel-2); border: 1px solid #24314c; border-radius: 12px; padding: 10px 12px; }
    .card.up { border-color: rgba(34,197,94,.45); }
    .card.down { border-color: rgba(239,68,68,.45); }
    .card-head { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }
    .sym { font-weight: 800; }
    .coin-name { color: var(--muted); font-size: 12px; }
    .price { font-size: 19px; font-weight: 800; margin-top: 4px; font-variant-numeric: tabular-nums; }
    .pct { font-weight: 700; font-size: 13px; }
    .pos { color: var(--green); }
    .neg { color: var(--red); }
    .flat { color: var(--muted); }
    .mcap { color: var(--muted); font-size: 12px; margin-top: 3px; }
    .spark { height: 42px; margin-top: 6px; }
    table { width: 100%; border-collapse: collapse; font-size: 14px; }
    th, td { text-align: right; padding: 7px 8px; border-bottom: 1px solid #1c2942; font-variant-numeric: tabular-nums; }
    th:first-child, td:first-child { text-align: left; }
    th { color: var(--muted); font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: .05em; }
    tr:last-child td { border-bottom: 0; }
    .tag { border-radius: 999px; padding: 2px 8px; font-size: 11px; font-weight: 700; background: rgba(56,189,248,.14); color: var(--blue); }
    .tag.stock { background: rgba(167,139,250,.16); color: var(--violet); }
    @media (max-width: 980px) { main { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Crypto Market Radar</h1>
      <div class="hero">
        <span class="btc-price" id="btc-price">—</span>
        <span class="btc-change" id="btc-change"></span>
        <span class="chip" id="mode-chip">connecting…</span>
      </div>
      <div class="stats">
        <span>Total crypto mcap <b id="total-mcap">—</b></span>
        <span>BTC dominance <b id="btc-dom">—</b></span>
        <span>Fear &amp; Greed <b id="fear-greed">—</b></span>
        <span>Updated <b id="updated-at">—</b></span>
      </div>
    </div>
    <div class="health-head panel" style="margin:0;">
      <span class="health-score" id="health-score">—</span>
      <div>
        <div class="health-label" id="health-label">market health</div>
        <div class="stats" style="margin-top:2px;"><span>composite 0–100</span></div>
      </div>
    </div>
  </header>
  <div id="alarm-banner">RISK-OFF ALARM — market health has collapsed</div>
  <main>
    <div class="stack">
      <section class="panel">
        <h2>Market health components</h2>
        <div id="health-bars"></div>
      </section>
      <section class="panel">
        <h2>Global</h2>
        <div class="kv" id="global-kv"></div>
      </section>
      <section class="panel">
        <h2>Top movers</h2>
        <div class="movers" id="movers"></div>
      </section>
      <section class="panel">
        <h2>Events</h2>
        <div class="events" id="events"></div>
      </section>
    </div>
    <div class="stack">
      <section class="panel">
        <h2>Bitcoin — session price &amp; market health</h2>
        <canvas id="btc-chart"></canvas>
      </section>
      <section class="panel">
        <h2>Cryptos across the board</h2>
        <div class="grid" id="crypto-grid"></div>
      </section>
      <section class="panel">
        <h2>Stocks &amp; index bellwethers <span class="coin-name">(change vs session open)</span></h2>
        <table>
          <thead><tr><th>Asset</th><th>Kind</th><th>Price</th><th>Change</th><th>Session range</th></tr></thead>
          <tbody id="stock-rows"></tbody>
        </table>
      </section>
    </div>
  </main>
  <script>
    const $ = (id) => document.getElementById(id);

    function fmtPrice(v) {
      if (v == null) return '—';
      if (v >= 1000) return '$' + v.toLocaleString('en-US', { maximumFractionDigits: 0 });
      if (v >= 1) return '$' + v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
      return '$' + v.toLocaleString('en-US', { minimumFractionDigits: 4, maximumFractionDigits: 4 });
    }
    function fmtBig(v) {
      if (v == null) return '—';
      if (v >= 1e12) return '$' + (v / 1e12).toFixed(2) + 'T';
      if (v >= 1e9) return '$' + (v / 1e9).toFixed(1) + 'B';
      if (v >= 1e6) return '$' + (v / 1e6).toFixed(1) + 'M';
      return '$' + Math.round(v).toLocaleString('en-US');
    }
    function pctClass(v) { return v == null ? 'flat' : v > 0.05 ? 'pos' : v < -0.05 ? 'neg' : 'flat'; }
    function fmtPct(v) { return v == null ? '—' : (v > 0 ? '+' : '') + v.toFixed(2) + '%'; }
    function healthColor(score) {
      if (score == null) return 'var(--muted)';
      if (score < 25) return 'var(--red)';
      if (score < 40) return 'var(--amber)';
      if (score < 60) return 'var(--gold)';
      if (score < 80) return 'var(--green)';
      return 'var(--violet)';
    }

    function drawSpark(canvas, series, color) {
      const dpr = window.devicePixelRatio || 1;
      const w = canvas.clientWidth, h = canvas.clientHeight;
      if (!w || !h) return;
      canvas.width = w * dpr; canvas.height = h * dpr;
      const ctx = canvas.getContext('2d');
      ctx.scale(dpr, dpr);
      ctx.clearRect(0, 0, w, h);
      if (!series || series.length < 2) return;
      const min = Math.min(...series), max = Math.max(...series);
      const span = (max - min) || 1;
      ctx.beginPath();
      series.forEach((v, i) => {
        const x = (i / (series.length - 1)) * (w - 4) + 2;
        const y = h - 4 - ((v - min) / span) * (h - 8);
        i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
      });
      ctx.strokeStyle = color; ctx.lineWidth = 1.6; ctx.stroke();
    }

    function drawBtcChart(history, cryptos) {
      const canvas = $('btc-chart');
      const dpr = window.devicePixelRatio || 1;
      const w = canvas.clientWidth, h = canvas.clientHeight;
      if (!w || !h) return;
      canvas.width = w * dpr; canvas.height = h * dpr;
      const ctx = canvas.getContext('2d');
      ctx.scale(dpr, dpr);
      ctx.clearRect(0, 0, w, h);
      const prices = history.map((p) => p.btc_price).filter((v) => v != null);
      if (prices.length < 2) {
        ctx.fillStyle = '#93a1ba'; ctx.font = '13px sans-serif';
        ctx.fillText('Collecting price history…', 14, 24);
        return;
      }
      const pad = 12;
      const min = Math.min(...prices), max = Math.max(...prices);
      const span = (max - min) || 1;
      // health backdrop (0-100 scaled to chart)
      ctx.beginPath();
      let started = false;
      history.forEach((p, i) => {
        if (p.health == null) return;
        const x = pad + (i / (history.length - 1)) * (w - pad * 2);
        const y = h - pad - (p.health / 100) * (h - pad * 2);
        started ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
        started = true;
      });
      ctx.strokeStyle = 'rgba(167,139,250,.55)'; ctx.lineWidth = 1.4;
      ctx.setLineDash([5, 4]); ctx.stroke(); ctx.setLineDash([]);
      // BTC price line
      ctx.beginPath();
      let j = 0;
      history.forEach((p, i) => {
        if (p.btc_price == null) return;
        const x = pad + (i / (history.length - 1)) * (w - pad * 2);
        const y = h - pad - ((p.btc_price - min) / span) * (h - pad * 2);
        j++ ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
      });
      ctx.strokeStyle = '#f7931a'; ctx.lineWidth = 2.2; ctx.stroke();
      ctx.fillStyle = '#93a1ba'; ctx.font = '12px sans-serif';
      ctx.fillText(fmtPrice(max), pad, 16);
      ctx.fillText(fmtPrice(min), pad, h - 16);
      ctx.fillStyle = 'rgba(167,139,250,.9)';
      ctx.fillText('dashed: health 0–100', w - 148, 16);
    }

    const BAR_META = [
      ['breadth', 'Breadth'],
      ['crypto', 'Crypto 24h'],
      ['stocks', 'Stocks'],
      ['sentiment', 'Sentiment'],
    ];

    function render(snapshot) {
      const btc = (snapshot.cryptos || []).find((c) => c.symbol === 'BTC');
      $('btc-price').textContent = btc ? fmtPrice(btc.price) : '—';
      const change = btc ? btc.change_24h_pct : null;
      const changeEl = $('btc-change');
      changeEl.textContent = fmtPct(change) + (change == null ? '' : ' 24h');
      changeEl.className = 'btc-change ' + pctClass(change);

      const chip = $('mode-chip');
      chip.textContent = snapshot.data_source === 'demo' ? 'DEMO' : 'LIVE';
      chip.className = 'chip ' + (snapshot.data_source === 'demo' ? 'demo' : 'live');

      $('total-mcap').textContent = fmtBig(snapshot.global.total_market_cap_usd);
      $('btc-dom').textContent = snapshot.global.btc_dominance_pct == null
        ? '—' : snapshot.global.btc_dominance_pct.toFixed(1) + '%';
      $('fear-greed').textContent = snapshot.global.fear_greed_value == null
        ? '—' : snapshot.global.fear_greed_value + ' · ' + (snapshot.global.fear_greed_label || '');
      $('updated-at').textContent = (snapshot.generated_at || '').replace('T', ' ').slice(11, 19) + ' UTC';

      const score = snapshot.health.score;
      const scoreEl = $('health-score');
      scoreEl.textContent = score == null ? '—' : Math.round(score);
      scoreEl.style.color = healthColor(score);
      $('health-label').textContent = snapshot.health.label || 'market health';
      $('health-label').style.color = healthColor(score);
      $('alarm-banner').className = snapshot.alarm_active ? 'active' : '';

      $('health-bars').innerHTML = BAR_META.map(([key, label]) => {
        const v = snapshot.health.components[key];
        const width = v == null ? 0 : Math.max(2, Math.min(100, v));
        return `<div class="bar-row"><span>${label}</span>
          <div class="bar"><i style="width:${width}%;background:${healthColor(v)}"></i></div>
          <b>${v == null ? '—' : Math.round(v)}</b></div>`;
      }).join('');

      $('global-kv').innerHTML = `
        <span>Total crypto market cap</span><b>${fmtBig(snapshot.global.total_market_cap_usd)}</b>
        <span>BTC dominance</span><b>${snapshot.global.btc_dominance_pct == null ? '—' : snapshot.global.btc_dominance_pct.toFixed(1) + '%'}</b>
        <span>Fear &amp; Greed index</span><b>${snapshot.global.fear_greed_value ?? '—'} ${snapshot.global.fear_greed_label ? '(' + snapshot.global.fear_greed_label + ')' : ''}</b>
        <span>Assets tracked</span><b>${(snapshot.cryptos || []).length + (snapshot.stocks || []).length}</b>
        <span>Poll cycles</span><b>${snapshot.cycles}</b>`;

      $('movers').innerHTML = (snapshot.top_movers || []).map((m) =>
        `<div><span>${m.name} <span class="coin-name">${m.symbol}</span></span>
         <b class="${pctClass(m.change_24h_pct)}">${fmtPct(m.change_24h_pct)}</b></div>`
      ).join('') || '<div><span class="coin-name">No data yet</span></div>';

      const events = (snapshot.events || []).slice(-40).reverse();
      $('events').innerHTML = events.map((e) => {
        const cls = e.alarm ? 'alarm-line' : e.type === 'mover-up' ? 'up-line' : e.type === 'mover-down' ? 'down-line' : '';
        return `<p class="${cls}">[${(e.at || '').slice(11, 19)}] ${e.message}</p>`;
      }).join('') || '<p>No events yet.</p>';

      $('crypto-grid').innerHTML = (snapshot.cryptos || []).map((c) => {
        const cls = pctClass(c.change_24h_pct);
        const cardCls = cls === 'pos' ? 'up' : cls === 'neg' ? 'down' : '';
        return `<div class="card ${cardCls}">
          <div class="card-head"><span class="sym">${c.symbol}</span><span class="pct ${cls}">${fmtPct(c.change_24h_pct)}</span></div>
          <div class="coin-name">${c.name}</div>
          <div class="price">${fmtPrice(c.price)}</div>
          <div class="mcap">mcap ${fmtBig(c.market_cap)}</div>
          <canvas class="spark" data-sym="${c.symbol}"></canvas>
        </div>`;
      }).join('');
      (snapshot.cryptos || []).forEach((c) => {
        const canvas = document.querySelector(`canvas[data-sym="${c.symbol}"]`);
        if (canvas) {
          const cls = pctClass(c.change_24h_pct);
          drawSpark(canvas, c.price_history, cls === 'neg' ? '#ef4444' : cls === 'pos' ? '#22c55e' : '#93a1ba');
        }
      });

      $('stock-rows').innerHTML = (snapshot.stocks || []).map((s) => `
        <tr>
          <td><b>${s.symbol}</b> <span class="coin-name">${s.name}</span></td>
          <td><span class="tag ${s.kind === 'index' ? '' : 'stock'}">${s.kind}</span></td>
          <td>${fmtPrice(s.price)}</td>
          <td class="${pctClass(s.change_24h_pct)}">${fmtPct(s.change_24h_pct)}</td>
          <td class="coin-name">${fmtPrice(s.session_low)} – ${fmtPrice(s.session_high)}</td>
        </tr>`).join('') || '<tr><td colspan="5" class="coin-name">Stock feed unavailable</td></tr>';

      drawBtcChart(snapshot.history || [], snapshot.cryptos || []);
    }

    let lastSnapshot = null;
    const source = new EventSource('/api/events');
    source.onmessage = (msg) => {
      lastSnapshot = JSON.parse(msg.data);
      render(lastSnapshot);
    };
    window.addEventListener('resize', () => { if (lastSnapshot) render(lastSnapshot); });
  </script>
</body>
</html>
"""
