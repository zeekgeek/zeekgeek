"""FastAPI dashboard and chat API for Shield Line."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Literal

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .state import ShieldState


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class ModeRequest(BaseModel):
    mode: Literal["passive", "shield"]
    auto_shield: bool | None = None


def create_app(state: ShieldState) -> FastAPI:
    app = FastAPI(title="Shield Line — threat-aware time sink")

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return DASHBOARD_HTML

    @app.get("/api/snapshot")
    async def snapshot() -> dict:
        return await state.snapshot()

    @app.post("/api/chat")
    async def chat(request: ChatRequest) -> JSONResponse:
        result = await state.ingest_inbound(request.message.strip())
        return JSONResponse(result)

    @app.post("/api/mode")
    async def set_mode(request: ModeRequest) -> JSONResponse:
        event = await state.set_mode(request.mode)
        if request.auto_shield is not None:
            await state.set_auto_shield(request.auto_shield)
        snap = await state.snapshot()
        return JSONResponse({"event": event, "mode": snap["mode"], "auto_shield": snap["auto_shield"]})

    @app.post("/api/reset")
    async def reset() -> JSONResponse:
        await state.reset_session()
        return JSONResponse({"ok": True})

    @app.get("/api/events")
    async def events() -> StreamingResponse:
        return StreamingResponse(_event_stream(state), media_type="text/event-stream")

    return app


async def _event_stream(state: ShieldState) -> AsyncIterator[str]:
    last_version = -1
    while True:
        snap = await state.snapshot()
        version = snap.get("version", 0)
        if version != last_version:
            yield f"data: {json.dumps(snap)}\n\n"
            last_version = version
        await asyncio.sleep(0.8)


DASHBOARD_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Shield Line</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #0a0c12;
      --panel: #121826;
      --panel-2: #1a2236;
      --text: #eef2ff;
      --muted: #94a3b8;
      --shield: #a78bfa;
      --danger: #f87171;
      --warn: #fbbf24;
      --ok: #34d399;
      --accent: #38bdf8;
      --line: #243049;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif;
      background: radial-gradient(900px 500px at 0% 0%, #1e1b4b 0%, transparent 50%), var(--bg);
      color: var(--text);
      min-height: 100vh;
    }
    header {
      padding: 18px 22px;
      border-bottom: 1px solid var(--line);
      display: flex;
      flex-wrap: wrap;
      gap: 14px;
      justify-content: space-between;
      align-items: center;
    }
    h1 { margin: 0; font-size: 20px; }
    .sub { color: var(--muted); font-size: 13px; margin-top: 4px; max-width: 520px; }
    .badge {
      display: inline-block;
      padding: 4px 10px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
      border: 1px solid var(--line);
    }
    .badge.shield { background: rgba(167,139,250,.15); color: var(--shield); border-color: #5b4d8a; }
    .badge.passive { background: rgba(148,163,184,.1); color: var(--muted); }
    main {
      display: grid;
      grid-template-columns: 1fr 320px;
      gap: 16px;
      padding: 16px;
      max-width: 1200px;
      margin: 0 auto;
    }
    @media (max-width: 900px) { main { grid-template-columns: 1fr; } }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 14px;
    }
    #chat-log {
      height: 52vh;
      min-height: 280px;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 10px;
      padding: 8px 4px;
    }
    .msg {
      max-width: 88%;
      padding: 10px 12px;
      border-radius: 12px;
      font-size: 14px;
      line-height: 1.45;
    }
    .msg.inbound {
      align-self: flex-end;
      background: #2a1f2e;
      border: 1px solid #4a3050;
    }
    .msg.bot {
      align-self: flex-start;
      background: var(--panel-2);
      border: 1px solid #334155;
    }
    .msg .meta { font-size: 11px; color: var(--muted); margin-top: 6px; }
    .threat-critical { box-shadow: 0 0 0 1px var(--danger); }
    .threat-high { box-shadow: 0 0 0 1px var(--warn); }
    .composer {
      display: flex;
      gap: 8px;
      margin-top: 12px;
    }
    textarea {
      flex: 1;
      resize: vertical;
      min-height: 52px;
      max-height: 120px;
      border-radius: 10px;
      border: 1px solid var(--line);
      background: #0d111c;
      color: var(--text);
      padding: 10px;
      font: inherit;
    }
    button {
      background: var(--accent);
      color: #041018;
      border: 0;
      border-radius: 10px;
      padding: 10px 14px;
      font-weight: 700;
      cursor: pointer;
    }
    button.secondary { background: transparent; color: var(--muted); border: 1px solid var(--line); }
    button.danger { background: rgba(248,113,113,.2); color: #fecaca; border: 1px solid #7f1d1d; }
    .stat-grid { display: grid; gap: 10px; }
    .stat {
      background: var(--panel-2);
      border-radius: 10px;
      padding: 10px;
      border: 1px solid var(--line);
    }
    .stat .label { font-size: 11px; text-transform: uppercase; letter-spacing: .08em; color: var(--muted); }
    .stat .value { font-size: 22px; font-weight: 800; margin-top: 4px; font-variant-numeric: tabular-nums; }
    .events { font-size: 12px; color: var(--muted); max-height: 140px; overflow: auto; }
    .events div { padding: 4px 0; border-bottom: 1px solid var(--line); }
    .safety {
      margin-top: 14px;
      font-size: 12px;
      color: var(--muted);
      line-height: 1.5;
      border-top: 1px solid var(--line);
      padding-top: 12px;
    }
    .safety a { color: var(--accent); }
    .controls { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Shield Line</h1>
      <p class="sub">
        Detects threatening language and auto-replies with a time-wasting bot so you can step away,
        document messages, and reach safety resources — without feeding the escalation.
      </p>
    </div>
    <div>
      <span id="mode-badge" class="badge shield">shield</span>
    </div>
  </header>
  <main>
    <section class="panel">
      <div id="chat-log"></div>
      <div class="composer">
        <textarea id="input" placeholder="Simulate an inbound threatening message…"></textarea>
        <div style="display:flex;flex-direction:column;gap:8px;">
          <button id="send">Send</button>
          <button class="secondary" id="demo" type="button">Demo line</button>
        </div>
      </div>
      <div class="controls">
        <button class="secondary" id="mode-shield" type="button">Force shield</button>
        <button class="secondary" id="mode-passive" type="button">Passive (detect only)</button>
        <button class="danger" id="reset" type="button">New session</button>
      </div>
    </section>
    <aside class="panel">
      <div class="stat-grid">
        <div class="stat">
          <div class="label">Est. time wasted</div>
          <div class="value" id="wasted">0s</div>
        </div>
        <div class="stat">
          <div class="label">Threat turns</div>
          <div class="value" id="threat-turns">0</div>
        </div>
        <div class="stat">
          <div class="label">Last threat level</div>
          <div class="value" id="threat-level">—</div>
        </div>
        <div class="stat">
          <div class="label">Active persona</div>
          <div class="value" id="persona" style="font-size:15px;">—</div>
        </div>
      </div>
      <h3 style="font-size:13px;color:var(--muted);margin:16px 0 8px;">Events</h3>
      <div class="events" id="events"></div>
      <div class="safety">
        <strong>If you are in danger:</strong> contact local emergency services.
        In the U.S., call or text <strong>988</strong> (crisis support) or the National Domestic Violence Hotline
        <a href="https://www.thehotline.org/" target="_blank" rel="noopener">thehotline.org</a> — 1-800-799-7233.
        This tool does not contact authorities automatically; keep your own safety plan.
      </div>
    </aside>
  </main>
  <script>
    const log = document.getElementById('chat-log');
    const input = document.getElementById('input');
    const wastedEl = document.getElementById('wasted');
    const threatTurnsEl = document.getElementById('threat-turns');
    const threatLevelEl = document.getElementById('threat-level');
    const personaEl = document.getElementById('persona');
    const modeBadge = document.getElementById('mode-badge');
    const eventsEl = document.getElementById('events');

    function formatSeconds(s) {
      if (s < 60) return Math.round(s) + 's';
      const m = Math.floor(s / 60);
      const r = Math.round(s % 60);
      return m + 'm ' + r + 's';
    }

    function renderMessages(messages) {
      log.innerHTML = '';
      for (const m of messages) {
        const div = document.createElement('div');
        div.className = 'msg ' + (m.role === 'bot' ? 'bot' : 'inbound');
        if (m.assessment) {
          const lvl = m.assessment.level;
          if (lvl === 'critical' || lvl === 'high') div.classList.add('threat-' + lvl);
        }
        div.textContent = m.text;
        const meta = document.createElement('div');
        meta.className = 'meta';
        if (m.role === 'inbound' && m.assessment) {
          meta.textContent = 'Threat: ' + m.assessment.level + ' (' + m.assessment.score + ')';
        } else if (m.bot) {
          meta.textContent = 'Persona: ' + m.bot.persona + ' · delay ~' + m.bot.suggested_delay_seconds + 's';
        }
        div.appendChild(meta);
        log.appendChild(div);
      }
      log.scrollTop = log.scrollHeight;
    }

    function applySnapshot(snap) {
      renderMessages(snap.messages || []);
      const st = snap.stats || {};
      wastedEl.textContent = formatSeconds(st.estimated_wasted_seconds || 0);
      threatTurnsEl.textContent = st.threat_turns ?? 0;
      personaEl.textContent = st.persona || '—';
      modeBadge.textContent = snap.mode;
      modeBadge.className = 'badge ' + snap.mode;
      const inbound = (snap.messages || []).filter(m => m.role === 'inbound');
      const last = inbound[inbound.length - 1];
      threatLevelEl.textContent = last && last.assessment ? last.assessment.level : '—';
      eventsEl.innerHTML = (snap.events || []).slice(0, 12).map(e =>
        '<div><strong>' + e.kind + '</strong> — ' + e.detail + '</div>'
      ).join('');
    }

    async function postChat(text) {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text })
      });
      return res.json();
    }

    document.getElementById('send').onclick = async () => {
      const text = input.value.trim();
      if (!text) return;
      input.value = '';
      await postChat(text);
    };
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        document.getElementById('send').click();
      }
    });

    document.getElementById('demo').onclick = async () => {
      const samples = [
        "answer me NOW where are you",
        "I know where you live open the door",
        "You're worthless nobody wants you",
        "If you leave me you'll regret it",
        "Last warning bitch"
      ];
      const pick = samples[Math.floor(Math.random() * samples.length)];
      input.value = pick;
      await postChat(pick);
      input.value = '';
    };

    async function setMode(mode) {
      await fetch('/api/mode', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode })
      });
    }
    document.getElementById('mode-shield').onclick = () => setMode('shield');
    document.getElementById('mode-passive').onclick = () => setMode('passive');
    document.getElementById('reset').onclick = () => fetch('/api/reset', { method: 'POST' });

    const es = new EventSource('/api/events');
    es.onmessage = (ev) => {
      try { applySnapshot(JSON.parse(ev.data)); } catch (_) {}
    };
    fetch('/api/snapshot').then(r => r.json()).then(applySnapshot);
  </script>
</body>
</html>
"""
