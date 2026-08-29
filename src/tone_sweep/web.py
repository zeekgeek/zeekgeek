"""FastAPI app and embedded Web Audio dashboard."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from .sweep import SweepConfig


def create_app(config: SweepConfig | None = None) -> FastAPI:
    sweep = config or SweepConfig()
    app = FastAPI(title="47–65 Hz Tone Sweep")

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return DASHBOARD_HTML

    @app.get("/api/config")
    async def get_config() -> dict[str, float]:
        return sweep.as_dict()

    return app


DASHBOARD_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#090b10">
  <title>Slow Current · 47–65 Hz</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #090b10;
      --panel: rgba(19, 22, 30, .72);
      --line: rgba(255, 255, 255, .10);
      --text: #f5f0e8;
      --muted: #aaa7a1;
      --coral: #f29a74;
      --gold: #f2c879;
      --mint: #9cd8c1;
      --danger: #ff927f;
    }
    * { box-sizing: border-box; }
    html, body { margin: 0; min-height: 100%; background: var(--bg); color: var(--text); }
    body {
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
      overflow-x: hidden;
      background:
        radial-gradient(circle at 50% 42%, rgba(242, 154, 116, .09), transparent 28rem),
        radial-gradient(circle at 15% 5%, rgba(156, 216, 193, .07), transparent 24rem),
        var(--bg);
    }
    .grain {
      position: fixed; inset: 0; pointer-events: none; opacity: .13; z-index: 4;
      background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 180 180' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='.18'/%3E%3C/svg%3E");
    }
    main { width: min(1180px, calc(100% - 32px)); margin: 0 auto; padding: 30px 0 42px; }
    header { display: flex; align-items: center; justify-content: space-between; gap: 18px; }
    .brand { display: flex; align-items: center; gap: 12px; }
    .mark {
      width: 34px; height: 34px; display: grid; place-items: center; border-radius: 50%;
      border: 1px solid var(--line); color: var(--coral); font-size: 18px;
      box-shadow: inset 0 0 18px rgba(242,154,116,.13);
    }
    .eyebrow { color: var(--muted); text-transform: uppercase; letter-spacing: .18em; font-size: 10px; }
    .brand-name { font-family: Georgia, serif; font-size: 18px; letter-spacing: .02em; }
    .status {
      display: flex; align-items: center; gap: 8px; color: var(--muted); font-size: 12px;
      border: 1px solid var(--line); border-radius: 999px; padding: 8px 12px;
    }
    .dot { width: 7px; height: 7px; border-radius: 50%; background: #686a70; }
    .status.live .dot { background: var(--mint); box-shadow: 0 0 12px var(--mint); }
    .hero { text-align: center; padding: 42px 0 24px; }
    h1 { margin: 0; font-family: Georgia, "Times New Roman", serif; font-size: clamp(38px, 7vw, 82px); font-weight: 400; letter-spacing: -.045em; }
    h1 em { color: var(--coral); font-weight: 400; }
    .subtitle { max-width: 540px; margin: 14px auto 0; color: var(--muted); line-height: 1.65; font-size: 14px; }
    .stage { position: relative; min-height: 420px; display: grid; place-items: center; }
    canvas { position: absolute; inset: 0; width: 100%; height: 100%; }
    .readout { position: relative; z-index: 2; text-align: center; pointer-events: none; }
    .hz { font: 300 clamp(76px, 14vw, 156px)/.9 Georgia, serif; letter-spacing: -.07em; font-variant-numeric: tabular-nums; }
    .unit { margin-left: 8px; color: var(--coral); font: 16px ui-monospace, monospace; letter-spacing: .12em; }
    .direction { margin-top: 18px; color: var(--muted); text-transform: uppercase; letter-spacing: .2em; font-size: 10px; }
    .progress-track { width: min(350px, 70vw); height: 2px; margin: 18px auto 0; background: rgba(255,255,255,.08); }
    .progress { width: 0; height: 100%; background: linear-gradient(90deg, var(--mint), var(--coral)); transition: width .08s linear; }
    .controls {
      position: relative; z-index: 3; display: grid; grid-template-columns: 1fr auto 1fr;
      gap: 22px; align-items: center; background: var(--panel); border: 1px solid var(--line);
      border-radius: 22px; padding: 18px 24px; backdrop-filter: blur(18px);
      box-shadow: 0 24px 70px rgba(0,0,0,.3);
    }
    .control { min-width: 0; }
    .control:last-child { text-align: right; }
    label { display: block; margin-bottom: 9px; color: var(--muted); font-size: 10px; text-transform: uppercase; letter-spacing: .14em; }
    input[type=range] { width: 100%; accent-color: var(--coral); }
    .value { color: var(--text); font: 12px ui-monospace, monospace; }
    button {
      width: 92px; height: 92px; border-radius: 50%; cursor: pointer; border: 1px solid rgba(242,154,116,.55);
      background: radial-gradient(circle at 42% 35%, #fac39d, var(--coral) 58%, #b85f4b);
      color: #25100b; font-weight: 800; letter-spacing: .09em; text-transform: uppercase;
      box-shadow: 0 0 0 8px rgba(242,154,116,.05), 0 12px 36px rgba(242,154,116,.22);
    }
    button:hover { transform: translateY(-1px); }
    button:focus-visible { outline: 3px solid var(--gold); outline-offset: 4px; }
    button.running { background: rgba(255,255,255,.05); color: var(--text); border-color: var(--line); box-shadow: none; }
    .safety {
      margin-top: 18px; display: grid; grid-template-columns: auto 1fr; gap: 12px;
      padding: 16px 18px; border: 1px solid rgba(242,200,121,.20); border-radius: 16px;
      background: rgba(242,200,121,.045); color: var(--muted); font-size: 12px; line-height: 1.55;
    }
    .safety b { color: var(--gold); }
    .speaker-note { margin: 22px auto 0; text-align: center; color: var(--muted); font-size: 11px; }
    .speaker-note strong { color: var(--text); font-weight: 600; }
    @media (max-width: 700px) {
      main { width: min(100% - 20px, 1180px); padding-top: 18px; }
      .hero { padding-top: 36px; }
      .stage { min-height: 330px; }
      .controls { grid-template-columns: 1fr 92px; padding: 16px; }
      .control:last-child { grid-column: 1 / -1; text-align: left; }
      .safety { grid-template-columns: 1fr; }
    }
    @media (prefers-reduced-motion: reduce) { .progress { transition: none; } }
  </style>
</head>
<body>
  <div class="grain"></div>
  <main>
    <header>
      <div class="brand"><div class="mark">∿</div><div><div class="eyebrow">Low frequency study</div><div class="brand-name">Slow Current</div></div></div>
      <div class="status" id="status"><span class="dot"></span><span id="status-text">Muted · ready</span></div>
    </header>
    <section class="hero">
      <h1>A gentler <em>frequency.</em></h1>
      <p class="subtitle">A continuous sine wave that drifts slowly from 47 to 65 Hz and back. Created for attentive listening, not medical use.</p>
    </section>
    <section class="stage">
      <canvas id="field" aria-hidden="true"></canvas>
      <div class="readout">
        <div><span class="hz" id="hz">47.0</span><span class="unit">Hz</span></div>
        <div class="direction" id="direction">Waiting to begin</div>
        <div class="progress-track"><div class="progress" id="progress"></div></div>
      </div>
    </section>
    <section class="controls" aria-label="Tone controls">
      <div class="control">
        <label for="volume">In-app level · starts silent</label>
        <input id="volume" type="range" min="0" max="100" value="0">
        <span class="value" id="volume-value">0%</span>
      </div>
      <button id="toggle" type="button">Start</button>
      <div class="control">
        <label for="duration">Time from 47 to 65 Hz</label>
        <input id="duration" type="range" min="30" max="180" step="15" value="90">
        <span class="value" id="duration-value">90 seconds</span>
      </div>
    </section>
    <div class="safety">
      <b>Listen safely</b>
      <span>Set the JBL Flip 5 as your system audio output before starting. Keep its hardware volume low and keep the speaker off your skin. Low frequencies can feel quieter than they are—do not compensate by turning them up. Stop immediately for pain, numbness, dizziness, nausea, or hearing discomfort.</span>
    </div>
    <p class="speaker-note"><strong>JBL Flip 5 note:</strong> its published response begins around 65 Hz, so lower tones may be faint or distorted.</p>
  </main>
  <script>
    const ui = {
      canvas: document.querySelector("#field"), hz: document.querySelector("#hz"),
      direction: document.querySelector("#direction"), progress: document.querySelector("#progress"),
      toggle: document.querySelector("#toggle"), volume: document.querySelector("#volume"),
      volumeValue: document.querySelector("#volume-value"), duration: document.querySelector("#duration"),
      durationValue: document.querySelector("#duration-value"), status: document.querySelector("#status"),
      statusText: document.querySelector("#status-text")
    };
    let config = {low_hz: 47, high_hz: 65, sweep_seconds: 90, max_gain: .12};
    let audio = null, oscillator = null, gain = null, startedAt = 0, running = false, animation = 0;

    fetch("/api/config").then(r => r.json()).then(data => {
      config = data;
      ui.duration.value = String(data.sweep_seconds);
      ui.durationValue.textContent = `${data.sweep_seconds} seconds`;
      ui.hz.textContent = data.low_hz.toFixed(1);
    }).catch(() => {});

    function frequencyAt(elapsed) {
      const oneWay = Number(ui.duration.value);
      const raw = elapsed / oneWay;
      const folded = raw % 2 > 1 ? 2 - raw % 2 : raw % 2;
      return config.low_hz + (config.high_hz - config.low_hz) * folded;
    }
    function setGain() {
      if (!gain || !audio) return;
      const target = running ? config.max_gain * Number(ui.volume.value) / 100 : 0;
      gain.gain.cancelScheduledValues(audio.currentTime);
      gain.gain.setTargetAtTime(target, audio.currentTime, .08);
    }
    async function start() {
      audio = audio || new (window.AudioContext || window.webkitAudioContext)();
      await audio.resume();
      oscillator = audio.createOscillator();
      gain = audio.createGain();
      oscillator.type = "sine";
      oscillator.frequency.value = config.low_hz;
      gain.gain.value = 0;
      oscillator.connect(gain).connect(audio.destination);
      oscillator.start();
      startedAt = performance.now() / 1000;
      running = true;
      setGain();
      ui.toggle.textContent = "Stop";
      ui.toggle.classList.add("running");
      ui.status.classList.add("live");
      ui.statusText.textContent = ui.volume.value === "0" ? "Running · silent" : "Tone active";
      frame();
    }
    function stop() {
      running = false;
      if (gain && audio) {
        gain.gain.cancelScheduledValues(audio.currentTime);
        gain.gain.setTargetAtTime(0, audio.currentTime, .035);
      }
      const oldOscillator = oscillator;
      setTimeout(() => { try { oldOscillator && oldOscillator.stop(); } catch (_) {} }, 250);
      oscillator = null;
      cancelAnimationFrame(animation);
      ui.toggle.textContent = "Start";
      ui.toggle.classList.remove("running");
      ui.status.classList.remove("live");
      ui.statusText.textContent = "Muted · ready";
      ui.direction.textContent = "Waiting to begin";
    }
    function frame() {
      if (!running) return;
      const elapsed = performance.now() / 1000 - startedAt;
      const oneWay = Number(ui.duration.value);
      const phase = (elapsed / oneWay) % 2;
      const ascending = phase <= 1;
      const hz = frequencyAt(elapsed);
      if (oscillator && audio) oscillator.frequency.setTargetAtTime(hz, audio.currentTime, .04);
      ui.hz.textContent = hz.toFixed(1);
      ui.direction.textContent = ascending ? "Rising slowly" : "Falling slowly";
      ui.progress.style.width = `${(ascending ? phase : 2 - phase) * 100}%`;
      draw(hz, elapsed);
      animation = requestAnimationFrame(frame);
    }
    ui.toggle.addEventListener("click", () => running ? stop() : start());
    ui.volume.addEventListener("input", () => {
      ui.volumeValue.textContent = `${ui.volume.value}%`;
      ui.statusText.textContent = running ? (ui.volume.value === "0" ? "Running · silent" : "Tone active") : "Muted · ready";
      setGain();
    });
    ui.duration.addEventListener("input", () => ui.durationValue.textContent = `${ui.duration.value} seconds`);
    window.addEventListener("pagehide", stop);

    const ctx = ui.canvas.getContext("2d");
    function draw(hz = config.low_hz, time = 0) {
      const rect = ui.canvas.getBoundingClientRect();
      const dpr = Math.min(devicePixelRatio || 1, 2);
      if (ui.canvas.width !== rect.width * dpr || ui.canvas.height !== rect.height * dpr) {
        ui.canvas.width = rect.width * dpr; ui.canvas.height = rect.height * dpr;
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, rect.width, rect.height);
      const cx = rect.width / 2, cy = rect.height / 2;
      const energy = Number(ui.volume.value) / 100;
      for (let i = 5; i >= 0; i--) {
        const drift = running ? (time * 18 + i * 42) % 250 : i * 42;
        const radius = 70 + drift;
        const alpha = Math.max(0, .14 - drift / 2100) * (.45 + energy);
        ctx.beginPath();
        ctx.arc(cx, cy, radius, 0, Math.PI * 2);
        ctx.strokeStyle = `rgba(242, 154, 116, ${alpha})`;
        ctx.lineWidth = 1;
        ctx.stroke();
      }
      ctx.beginPath();
      for (let x = 0; x <= rect.width; x += 3) {
        const envelope = Math.sin(Math.PI * x / rect.width);
        const y = cy + Math.sin(x / rect.width * Math.PI * 8 + time * hz / 8) * (12 + energy * 20) * envelope;
        x === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
      }
      ctx.strokeStyle = "rgba(156, 216, 193, .32)";
      ctx.lineWidth = 1.2;
      ctx.stroke();
    }
    draw();
    window.addEventListener("resize", () => !running && draw());
  </script>
</body>
</html>
"""
