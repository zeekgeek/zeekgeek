"""Live browser dashboard for BluetoothRadar."""

from __future__ import annotations

import asyncio
import contextlib
import json
import socket
import time
import webbrowser
from contextlib import asynccontextmanager
from threading import Timer
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse

from analysis import analyze_graph
from graph import build_relationship_graph
from scanner import (
    BluetoothRadarScanner,
    DiscoveredDevice,
    demo_scan,
    probe_bluetooth,
)


class DashboardState:
    def __init__(self, source: str, status: str = "starting") -> None:
        self.source = source
        self.status = status
        self.devices: dict[str, DiscoveredDevice] = {}
        self.sequence = 0
        self.error: str | None = None
        self.message: str | None = None
        self.started_at = time.time()
        self.hardware_ok: bool | None = None
        self.packets = 0
        self.last_packet_at: float | None = None

    def update(self, device: DiscoveredDevice) -> None:
        self.devices[device.address] = device
        self.sequence += 1
        self.packets += 1
        self.last_packet_at = device.last_seen
        if self.status != "fallback":
            self.status = "streaming"
        # Keep the hardware failure reason visible while demo fallback streams.
        if self.source.startswith("LIVE"):
            self.error = None
            self.message = None

    def snapshot(self) -> dict[str, Any]:
        devices = sorted(
            self.devices.values(), key=lambda item: item.rssi, reverse=True
        )
        graph = build_relationship_graph(devices)
        report = analyze_graph(graph)
        return {
            "source": self.source,
            "status": self.status,
            "message": self.message,
            "sequence": self.sequence,
            "packets": self.packets,
            "last_packet_at": self.last_packet_at,
            "hardware_ok": self.hardware_ok,
            "error": self.error,
            "uptime_seconds": round(time.time() - self.started_at, 1),
            "server_time": time.time(),
            "devices": [device.as_dict() for device in devices],
            "graph": {
                "nodes": [
                    {
                        "id": node,
                        "label": attrs["label"],
                        "hidden": attrs["hidden"],
                        "rssi": attrs["rssi"],
                    }
                    for node, attrs in graph.nodes(data=True)
                ],
                "edges": [
                    {
                        "source": left,
                        "target": right,
                        "weight": attrs["weight"],
                        "evidence": attrs["evidence"],
                    }
                    for left, right, attrs in graph.edges(data=True)
                ],
            },
            "analysis": {
                "hubs": [
                    {"id": node, "score": round(score, 3)}
                    for node, score in report.hubs
                ],
                "clusters": [sorted(cluster) for cluster in report.clusters],
                "multi_cluster_devices": report.multi_cluster_devices,
                "suggestions": report.suggestions,
            },
        }


async def _seed_demo_devices(state: DashboardState) -> list[DiscoveredDevice]:
    devices = await demo_scan(0.05)
    for device in devices:
        state.update(device)
    return devices


async def _demo_stream(state: DashboardState) -> None:
    devices = await _seed_demo_devices(state)
    base_rssi = {device.address: device.rssi for device in devices}
    offsets = (0, 2, -1, 3, -2, 1)
    tick = 0
    while True:
        now = time.time()
        for index, device in enumerate(devices):
            device.rssi = base_rssi[device.address] + offsets[
                (tick + index) % len(offsets)
            ]
            device.last_seen = now
            device.sightings += 1
            state.update(device)
        tick += 1
        await asyncio.sleep(0.8)


async def _live_stream(
    state: DashboardState, active: bool, adapter: str | None
) -> None:
    loop = asyncio.get_running_loop()
    while True:
        state.source = "LIVE BLE"
        state.status = "scanning"
        state.error = None
        state.message = (
            "Live BLE scan active. Nearby advertisements will appear as they "
            "are observed."
        )
        scanner = BluetoothRadarScanner(
            active=active,
            adapter=adapter,
            on_update=state.update,
            loop=loop,
        )
        try:
            await scanner.run_continuous()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            state.hardware_ok = False
            state.status = "error"
            state.error = str(error)
            state.message = f"Live scanner error: {error}. Retrying in 3s…"
            await asyncio.sleep(3.0)


async def _run_dashboard_stream(
    state: DashboardState,
    *,
    demo: bool,
    active: bool,
    adapter: str | None,
    demo_fallback: bool,
) -> None:
    if demo:
        state.source = "SIMULATED LIVE"
        state.status = "demo"
        state.hardware_ok = False
        await _demo_stream(state)
        return

    ready, detail = await probe_bluetooth(adapter=adapter, timeout=0.8)
    state.hardware_ok = ready
    if not ready:
        if demo_fallback:
            state.source = "SIMULATED LIVE (fallback)"
            state.status = "fallback"
            state.error = detail
            state.message = (
                "No usable Bluetooth adapter detected. Streaming simulated "
                "devices so the dashboard stays usable. On a Mac with Bluetooth "
                "enabled, restart without --demo and grant Terminal Bluetooth "
                "permission."
            )
            await _demo_stream(state)
            return
        state.source = "LIVE BLE"
        state.status = "error"
        state.error = detail
        state.message = (
            "Live scanning unavailable. Enable Bluetooth / BlueZ, grant scan "
            "permission, or restart with --demo-fallback."
        )
        while True:
            await asyncio.sleep(3600)
        return

    state.message = detail
    try:
        await _live_stream(state, active, adapter)
    except asyncio.CancelledError:
        raise
    except Exception as error:
        if not demo_fallback:
            state.status = "error"
            state.error = str(error)
            state.message = (
                "Live scanning failed. Restart with --demo-fallback to use "
                "simulated devices when hardware is unavailable."
            )
            while True:
                await asyncio.sleep(3600)
            return

        state.source = "SIMULATED LIVE (fallback)"
        state.status = "fallback"
        state.error = str(error)
        state.message = (
            "Live scanning unavailable on this host. Showing simulated devices."
        )
        await _demo_stream(state)


def _render_dashboard_html(initial_snapshot: dict[str, Any]) -> str:
    payload = json.dumps(initial_snapshot).replace("<", "\\u003c")
    return DASHBOARD_HTML.replace("__INITIAL_SNAPSHOT__", payload)


def create_app(
    *,
    demo: bool = False,
    active: bool = True,
    adapter: str | None = None,
    demo_fallback: bool = False,
) -> FastAPI:
    initial_source = "SIMULATED LIVE" if demo else "LIVE BLE"
    state = DashboardState(
        initial_source,
        status="demo" if demo else "scanning",
    )
    if not demo:
        state.message = (
            "Starting live BLE scan. Enable Bluetooth and grant scan permission "
            "to your terminal app."
        )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if demo:
            await _seed_demo_devices(state)
        task = asyncio.create_task(
            _run_dashboard_stream(
                state,
                demo=demo,
                active=active,
                adapter=adapter,
                demo_fallback=demo_fallback,
            )
        )
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title="BluetoothRadar", lifespan=lifespan)
    app.state.radar = state

    @app.get("/", response_class=HTMLResponse)
    async def dashboard() -> HTMLResponse:
        return HTMLResponse(_render_dashboard_html(state.snapshot()))

    @app.get("/api/snapshot")
    async def snapshot() -> dict[str, Any]:
        return state.snapshot()

    @app.get("/api/events")
    async def events() -> StreamingResponse:
        async def stream() -> Any:
            last_sequence = -1
            while True:
                payload = state.snapshot()
                if payload["sequence"] != last_sequence:
                    last_sequence = payload["sequence"]
                yield f"data: {json.dumps(payload)}\n\n"
                await asyncio.sleep(0.35)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return app


def _available_port(host: str, preferred: int) -> int:
    for port in range(preferred, preferred + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind((host, port))
                probe.listen(1)
            except OSError:
                continue
            return port
    raise OSError("no available dashboard port found")


def run_dashboard(args: Any) -> int:
    use_demo = bool(args.demo)
    # Default: fall back to simulated data only when no Bluetooth hardware is
    # available. Pass --no-demo-fallback to keep an empty LIVE error state.
    demo_fallback = not bool(getattr(args, "no_demo_fallback", False))
    if getattr(args, "demo_fallback", False):
        demo_fallback = True
    port = _available_port(args.host, args.port)
    url = f"http://{args.host}:{port}"
    print(f"BluetoothRadar dashboard: {url}", flush=True)
    if use_demo:
        print("Running browser dashboard in demo mode with simulated devices.", flush=True)
    else:
        print("Running live BLE scan. Nearby advertisements will stream to the dashboard.", flush=True)
        if demo_fallback:
            print(
                "If no Bluetooth adapter is available, the dashboard will fall back to simulated devices.",
                flush=True,
            )
        else:
            print("Demo fallback disabled with --no-demo-fallback.", flush=True)
    if args.open_browser:
        Timer(0.8, lambda: webbrowser.open(url)).start()
    uvicorn.run(
        create_app(
            demo=use_demo,
            active=args.scan_mode == "active",
            adapter=args.adapter,
            demo_fallback=demo_fallback,
        ),
        host=args.host,
        port=port,
        log_level="info",
    )
    return 0


DASHBOARD_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>BluetoothRadar — Live BLE Intelligence</title>
<style>
:root{color-scheme:dark;--bg:#070b12;--panel:#101722;--line:#253247;--cyan:#39d8ff;
--red:#ff496a;--muted:#8ea0b8;--green:#38e29b;--amber:#fbbf24}*{box-sizing:border-box}
body{margin:0;background:radial-gradient(circle at 75% -10%,#18324d 0,transparent 38%),var(--bg);
color:#ecf5ff;font:14px ui-monospace,SFMono-Regular,Menlo,monospace}
header{display:flex;align-items:center;justify-content:space-between;padding:22px 30px;border-bottom:1px solid var(--line)}
h1{font-size:22px;letter-spacing:.08em;margin:0}.mark{color:var(--cyan)}.sub{color:var(--muted);margin-top:5px}
.status{display:flex;gap:10px;align-items:center}.badge{padding:7px 11px;border:1px solid var(--cyan);color:var(--cyan);border-radius:20px}
.pulse{width:9px;height:9px;border-radius:50%;background:var(--green);box-shadow:0 0 0 0 #38e29b88;animation:p 1.4s infinite}
@keyframes p{70%{box-shadow:0 0 0 9px transparent}}main{padding:22px 30px}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}
.card,.panel{background:#101722dd;border:1px solid var(--line);border-radius:10px}.card{padding:16px}.value{font-size:25px;color:var(--cyan);margin-top:8px}
.grid{display:grid;grid-template-columns:minmax(520px,1.25fr) minmax(380px,.75fr);gap:14px;margin-top:14px}
.radar-grid{display:grid;grid-template-columns:minmax(360px,1.1fr) minmax(360px,.9fr);gap:14px;margin-top:14px}
.panel{overflow:hidden}
.panel h2{font-size:13px;letter-spacing:.1em;margin:0;padding:14px 16px;border-bottom:1px solid var(--line);color:#bcd0e7}
.radar-panel{display:flex;flex-direction:column;min-height:480px}
.radar-wrap{position:relative;flex:1;min-height:440px;height:440px;background:radial-gradient(circle at 50% 58%,#14324d 0%,#0a1420 52%,#070b12 100%);border-top:1px solid #1a2738}
#radar3d{display:block;width:100%;height:440px;min-height:440px;cursor:pointer}
.radar-hud{position:absolute;left:16px;bottom:14px;z-index:2;padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:#0b121dcc;color:var(--muted);font-size:11px;line-height:1.5;pointer-events:none}
.radar-hud strong{color:var(--cyan)}.list-panel .table-wrap{max-height:440px}
.table-wrap{max-height:480px;overflow:auto}table{width:100%;border-collapse:collapse}th,td{padding:11px 12px;border-bottom:1px solid #1e2938;text-align:left}
th{position:sticky;top:0;background:#121b28;color:var(--muted);cursor:pointer;font-size:11px}.rssi{font-weight:700;color:var(--cyan)}
.hidden{color:var(--red);font-weight:700}.service{max-width:170px;color:var(--muted);font-size:11px;overflow-wrap:anywhere}
.row-active{background:#152033}.row-click{cursor:pointer}
.empty{padding:28px 16px;color:var(--muted);line-height:1.6}.banner{margin:0 0 14px;padding:12px 16px;border:1px solid var(--line);border-radius:10px;background:#121b28cc;color:var(--muted)}
.banner.warn{border-color:#7c5d12;color:var(--amber)}.banner.error{border-color:#7f1d1d;color:var(--red)}
#graph{display:block;width:100%;height:355px;background:linear-gradient(#0e1622aa 1px,transparent 1px),linear-gradient(90deg,#0e1622aa 1px,transparent 1px);background-size:26px 26px}
.edge{stroke:#536984}.node{cursor:pointer;stroke:#d9f5ff;stroke-width:1.5}.node.hidden-node{fill:var(--red)}.node.visible-node{fill:var(--cyan)}
.node-label{fill:#eaf6ff;font-size:10px;pointer-events:none}.edge-label{fill:#8ea0b8;font-size:9px}.detail{min-height:120px;padding:14px 16px;color:var(--muted);line-height:1.55}
.detail strong{color:#fff}.intel{padding:13px 16px;min-height:115px}.intel div{margin:5px 0;color:var(--muted)}
@media(max-width:950px){.stats{grid-template-columns:repeat(2,1fr)}.grid,.radar-grid{grid-template-columns:1fr}}
</style></head>
<body><header><div><h1><span class="mark">◉</span> BLUETOOTH/RADAR</h1><div class="sub">Advertisement telemetry · relationship hypotheses</div></div>
<div class="status"><span class="pulse"></span><span id="sourceBadge" class="badge">CONNECTING</span></div></header>
<main><div id="banner" class="banner">Connecting to scanner stream…</div><section class="stats"><div class="card">DEVICES<div id="countValue" class="value">0</div></div>
<div class="card">IDENTITY-LIMITED<div id="hiddenValue" class="value">0</div></div>
<div class="card">PACKETS<div id="seqValue" class="value">0</div></div>
<div class="card">LAST FRAME<div id="ageValue" class="value">—</div></div></section>
<section class="radar-grid"><div class="panel radar-panel"><h2>3D PROXIMITY RADAR · LIVE SCAN SWEEP</h2><div class="radar-wrap">
<svg id="radar3d" viewBox="0 0 640 440" role="img" aria-label="Bluetooth proximity radar">
  <defs>
    <radialGradient id="radarGlow" cx="50%" cy="58%" r="55%"><stop offset="0%" stop-color="#1a4d6e"/><stop offset="70%" stop-color="#0b1624"/><stop offset="100%" stop-color="#070b12"/></radialGradient>
    <linearGradient id="sweepGrad" x1="0%" y1="0%" x2="100%" y2="0%"><stop offset="0%" stop-color="#38e29b" stop-opacity="0"/><stop offset="100%" stop-color="#38e29b" stop-opacity="0.35"/></linearGradient>
  </defs>
  <rect width="640" height="440" fill="url(#radarGlow)"/>
  <g id="radarFloor" transform="translate(320 255) scale(1 0.55)"></g>
  <g id="radarSweep" transform="translate(320 255) scale(1 0.55)"><path id="sweepWedge" d="" fill="url(#sweepGrad)"/><line id="sweepArm" x1="0" y1="0" x2="0" y2="-180" stroke="#38e29b" stroke-width="2" stroke-opacity="0.95"/></g>
  <circle cx="320" cy="255" r="6" fill="#38e29b"/>
  <g id="radarBlips"></g>
  <text id="radarEmpty" x="24" y="36" fill="#8ea0b8" font-size="14" font-family="ui-monospace,monospace">Starting radar…</text>
</svg>
<div id="radarHud" class="radar-hud"><strong>Observer</strong> at center · distance from RSSI · azimuth from identifier hash<br>Click a blip or list row to inspect a device</div></div></div>
<div class="panel list-panel"><h2>LIVE DEVICE LIST · CLICK ROW TO SELECT</h2><div class="table-wrap">
<table><thead><tr><th data-sort="name">DEVICE</th><th data-sort="address">IDENTIFIER</th><th data-sort="rssi">RSSI</th><th>MANUFACTURER</th><th>SERVICES</th></tr></thead><tbody id="deviceRows"></tbody></table>
<div id="emptyState" class="empty">Waiting for the first BLE advertisement…</div></div></div></section>
<section class="grid"><div class="panel"><h2>INFERRED RELATIONSHIP GRAPH</h2><svg id="graph" viewBox="0 0 600 355"></svg>
<div id="detail" class="detail">Select a node for observed details. Edges are heuristics, not confirmed connections.</div></div>
<div><div class="panel" style="margin-top:0"><h2>GRAPH INTELLIGENCE</h2><div id="intel" class="intel"></div></div></div></section></main>
<script>
const INITIAL_SNAPSHOT=__INITIAL_SNAPSHOT__;
class RadarDisplay{
  constructor(svg,hud){
    this.svg=svg;this.hud=hud;
    this.floor=document.getElementById("radarFloor");
    this.sweep=document.getElementById("radarSweep");
    this.wedge=document.getElementById("sweepWedge");
    this.arm=document.getElementById("sweepArm");
    this.blips=document.getElementById("radarBlips");
    this.empty=document.getElementById("radarEmpty");
    this.devices=[];this.selected=null;this.scanning=true;this.angle=0;
    this._buildFloor();
    this.svg.addEventListener("click",(event)=>{
      const target=event.target.closest("[data-address]");
      if(target){window.dispatchEvent(new CustomEvent("radar-select",{detail:{address:target.dataset.address}}));}
    });
    const tick=()=>{this.angle=(this.angle+0.045)%(Math.PI*2);this._drawSweep();requestAnimationFrame(tick);};
    requestAnimationFrame(tick);
  }
  _buildFloor(){
    this.floor.innerHTML="";
    for(const radius of [45,90,135,180]){
      const ring=document.createElementNS("http://www.w3.org/2000/svg","circle");
      ring.setAttribute("cx","0");ring.setAttribute("cy","0");ring.setAttribute("r",String(radius));
      ring.setAttribute("fill","none");ring.setAttribute("stroke","#39d8ff");ring.setAttribute("stroke-opacity","0.22");ring.setAttribute("stroke-width","1.5");
      this.floor.appendChild(ring);
    }
    for(const [x1,y1,x2,y2] of [[-190,0,190,0],[0,-190,0,190]]){
      const line=document.createElementNS("http://www.w3.org/2000/svg","line");
      line.setAttribute("x1",x1);line.setAttribute("y1",y1);line.setAttribute("x2",x2);line.setAttribute("y2",y2);
      line.setAttribute("stroke","#1f3550");line.setAttribute("stroke-width","1");
      this.floor.appendChild(line);
    }
  }
  _drawSweep(){
    const start=this.angle-0.35,end=this.angle+0.35,r=180;
    const x1=Math.sin(start)*r,y1=-Math.cos(start)*r,x2=Math.sin(end)*r,y2=-Math.cos(end)*r;
    this.wedge.setAttribute("d",`M0 0 L${x1} ${y1} A${r} ${r} 0 0 1 ${x2} ${y2} Z`);
    this.arm.setAttribute("x2",String(Math.sin(this.angle)*r));
    this.arm.setAttribute("y2",String(-Math.cos(this.angle)*r));
  }
  rssiRadius(rssi){const clamped=Math.max(-95,Math.min(-35,Number(rssi)||-95));return 35+((-clamped-35)/60)*145;}
  stableAngle(address){let hash=0;const text=String(address||"");for(let i=0;i<text.length;i+=1){hash=(hash*31+text.charCodeAt(i))>>>0;}return (hash%360)*Math.PI/180;}
  update(devices,selected,scanning){
    this.devices=devices||[];this.selected=selected;this.scanning=!!scanning;
    const count=this.devices.length;
    this.hud.innerHTML=`<strong>${this.scanning?"Scanning":"Tracking"}</strong> · ${count} device${count===1?"":"s"} · 3D proximity radar<br>Closer blips = stronger RSSI · red = identity-limited · click to select`;
    this.empty.style.display=count?"none":"block";
    this.empty.textContent=this.scanning?"Scanning for BLE advertisements…":"No devices in range yet";
    this.blips.innerHTML="";
    this.devices.forEach((device)=>{
      const angle=this.stableAngle(device.address);
      const radius=this.rssiRadius(device.rssi);
      const x=320+Math.sin(angle)*radius;
      const y=255-Math.cos(angle)*radius*0.55;
      const hidden=!!device.identity_limited;
      const active=this.selected===device.address;
      const color=hidden?"#ff496a":"#39d8ff";
      const group=document.createElementNS("http://www.w3.org/2000/svg","g");
      group.setAttribute("data-address",device.address);
      group.style.cursor="pointer";
      const halo=document.createElementNS("http://www.w3.org/2000/svg","circle");
      halo.setAttribute("cx",x);halo.setAttribute("cy",y);halo.setAttribute("r",active?"16":"11");
      halo.setAttribute("fill",color);halo.setAttribute("fill-opacity","0.18");
      const core=document.createElementNS("http://www.w3.org/2000/svg","circle");
      core.setAttribute("cx",x);core.setAttribute("cy",y);core.setAttribute("r",active?"8":"6");
      core.setAttribute("fill",color);core.setAttribute("stroke",active?"#fff":"rgba(255,255,255,0.35)");core.setAttribute("stroke-width",active?"2":"1");
      const label=document.createElementNS("http://www.w3.org/2000/svg","text");
      label.setAttribute("x",x+12);label.setAttribute("y",y-10);
      label.setAttribute("fill","#eaf6ff");label.setAttribute("font-size","12");label.setAttribute("font-family","ui-monospace,monospace");
      label.textContent=hidden?"Hidden":(device.name||String(device.address).slice(-8));
      group.appendChild(halo);group.appendChild(core);group.appendChild(label);
      this.blips.appendChild(group);
    });
  }
}
const ui={
  source:document.getElementById("sourceBadge"),
  banner:document.getElementById("banner"),
  count:document.getElementById("countValue"),
  hidden:document.getElementById("hiddenValue"),
  seq:document.getElementById("seqValue"),
  age:document.getElementById("ageValue"),
  rows:document.getElementById("deviceRows"),
  empty:document.getElementById("emptyState"),
  intel:document.getElementById("intel"),
  detail:document.getElementById("detail"),
  graph:document.getElementById("graph")
};
const radar3d=new RadarDisplay(document.getElementById("radar3d"),document.getElementById("radarHud"));
let snapshot=INITIAL_SNAPSHOT||null,sortKey="rssi",selected=null;
const esc=(value)=>String(value??"").replace(/[&<>"']/g,(char)=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
document.querySelectorAll("th[data-sort]").forEach((header)=>{header.addEventListener("click",()=>{sortKey=header.dataset.sort;render();});});
function renderBanner(){
  if(!snapshot){ui.banner.textContent="Connecting to scanner stream…";ui.banner.className="banner";return;}
  if(snapshot.message){ui.banner.textContent=snapshot.message;ui.banner.className=snapshot.error?"banner warn":"banner";}
  else if(snapshot.error && !snapshot.devices.length){ui.banner.textContent=snapshot.error;ui.banner.className="banner error";}
  else if(snapshot.error){ui.banner.textContent=snapshot.error;ui.banner.className="banner warn";}
  else if(snapshot.devices.length===0 && snapshot.status==="scanning"){ui.banner.textContent="Live scan running — waiting for nearby BLE advertisements…";ui.banner.className="banner";}
  else{ui.banner.textContent="";ui.banner.className="banner";}
}
function renderTable(devices){
  ui.rows.innerHTML=devices.map((device)=>`<tr class="row-click ${selected===device.address?"row-active":""}" data-address="${esc(device.address)}"><td class="${device.identity_limited?"hidden":""}">${device.identity_limited?"🕵️ HIDDEN":esc(device.name||"Unnamed")}</td><td>${esc(device.address)}</td><td class="rssi">${device.rssi} dBm</td><td>${esc((device.manufacturer_data||[]).map((item)=>item.company).join(", ")||"—")}</td><td class="service">${esc((device.service_uuids||[]).join(", ")||"—")}</td></tr>`).join("");
  ui.rows.querySelectorAll("tr[data-address]").forEach((row)=>{row.addEventListener("click",()=>selectDevice(row.dataset.address));});
  ui.empty.style.display=devices.length?"none":"block";
  ui.empty.textContent=snapshot && snapshot.status==="scanning" ? "Scanning for nearby BLE advertisements…" : "No devices observed yet.";
}
function renderGraph(){
  const nodes=snapshot.graph.nodes,positions={};
  nodes.forEach((node,index)=>{const angle=-Math.PI/2+index*2*Math.PI/Math.max(nodes.length,1);positions[node.id]={x:300+190*Math.cos(angle),y:175+125*Math.sin(angle)};});
  ui.graph.innerHTML="";
  snapshot.graph.edges.forEach((edge)=>{const start=positions[edge.source],end=positions[edge.target];const line=document.createElementNS("http://www.w3.org/2000/svg","line");line.setAttribute("x1",start.x);line.setAttribute("y1",start.y);line.setAttribute("x2",end.x);line.setAttribute("y2",end.y);line.setAttribute("class","edge");line.setAttribute("stroke-width",1+edge.weight*5);ui.graph.appendChild(line);const label=document.createElementNS("http://www.w3.org/2000/svg","text");label.setAttribute("x",(start.x+end.x)/2);label.setAttribute("y",(start.y+end.y)/2);label.setAttribute("class","edge-label");label.textContent=edge.weight.toFixed(2);ui.graph.appendChild(label);});
  nodes.forEach((node)=>{const point=positions[node.id];const circle=document.createElementNS("http://www.w3.org/2000/svg","circle");circle.setAttribute("cx",point.x);circle.setAttribute("cy",point.y);circle.setAttribute("r",selected===node.id?20:15);circle.setAttribute("class",`node ${node.hidden?"hidden-node":"visible-node"}`);circle.addEventListener("click",()=>selectNode(node.id));ui.graph.appendChild(circle);const label=document.createElementNS("http://www.w3.org/2000/svg","text");label.setAttribute("x",point.x);label.setAttribute("y",point.y+31);label.setAttribute("text-anchor","middle");label.setAttribute("class","node-label");label.textContent=node.label;ui.graph.appendChild(label);});
}
function render(){
  if(!snapshot)return;
  const devices=[...snapshot.devices].sort((left,right)=>sortKey==="rssi"?right.rssi-left.rssi:String(left[sortKey]||"").localeCompare(String(right[sortKey]||"")));
  ui.source.textContent=snapshot.source;
  ui.count.textContent=devices.length;
  ui.hidden.textContent=devices.filter((device)=>device.identity_limited).length;
  ui.seq.textContent=snapshot.packets ?? snapshot.sequence;
  ui.age.textContent=devices.length?`${Math.max(0,Date.now()/1000-Math.max(...devices.map((device)=>device.last_seen))).toFixed(1)}s`:"—";
  if(snapshot.source && String(snapshot.source).startsWith("LIVE")){ui.source.style.borderColor="#38e29b";ui.source.style.color="#38e29b";}
  else{ui.source.style.borderColor="#39d8ff";ui.source.style.color="#39d8ff";}
  renderBanner();renderTable(devices);
  try{renderGraph();}catch(error){console.error("graph render failed",error);}
  try{radar3d.update(devices,selected,snapshot.status==="scanning"||snapshot.status==="streaming"||snapshot.status==="demo"||snapshot.status==="fallback");}catch(error){console.error("radar render failed",error);}
  const hubs=(snapshot.analysis&&snapshot.analysis.hubs||[]).map((hub)=>(snapshot.graph.nodes.find((node)=>node.id===hub.id)||{}).label||hub.id);
  ui.intel.innerHTML=`<div><strong>Hub candidates:</strong> ${esc(hubs.join(", ")||"none")}</div><div><strong>Clusters:</strong> ${(snapshot.analysis.clusters||[]).length}</div><div><strong>Overlapping:</strong> ${esc((snapshot.analysis.multi_cluster_devices||[]).join(", ")||"none")}</div>`;
}
function selectDevice(id){
  selected=id;
  const device=snapshot.devices.find((item)=>item.address===id);
  if(!device)return;
  const edges=snapshot.graph.edges.filter((edge)=>edge.source===id||edge.target===id);
  ui.detail.innerHTML=`<strong>${esc(device.name||"🕵️ Hidden")}</strong><br>${esc(device.address)} · ${device.rssi} dBm · ${device.sightings} sightings<br>${esc((device.manufacturer_data||[]).map((item)=>`${item.company} ${item.frame_type||""}`.trim()).join(", ")||"No manufacturer data")}<br>${edges.length} inferred edge(s)`;
  render();
}
function selectNode(id){selectDevice(id);renderGraph();}
window.addEventListener("radar-select",(event)=>{if(event.detail&&event.detail.address){selectDevice(event.detail.address);}});
async function load(){
  try{
    const response=await fetch("/api/snapshot",{cache:"no-store"});
    if(!response.ok)throw new Error(`HTTP ${response.status}`);
    snapshot=await response.json();
    render();
  }catch(error){
    ui.source.textContent="DISCONNECTED";
    ui.banner.textContent=`Could not reach /api/snapshot (${error.message}). Start the server with: python main.py --browser --open-browser`;
    ui.banner.className="banner error";
    radar3d.update([],null,true);
  }
}
function connectLiveStream(){
  if(typeof EventSource==="undefined"){load();setInterval(load,700);return;}
  const stream=new EventSource("/api/events");
  stream.onmessage=(event)=>{snapshot=JSON.parse(event.data);render();};
  stream.onerror=()=>{ui.source.textContent="RECONNECTING";load();};
}
render();
connectLiveStream();
setInterval(()=>{if(snapshot)render();},200);
</script></body></html>"""
