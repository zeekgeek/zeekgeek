"""Live browser dashboard for BluetoothRadar."""

from __future__ import annotations

import asyncio
import contextlib
import socket
import time
import webbrowser
from contextlib import asynccontextmanager
from threading import Timer
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from analysis import analyze_graph
from graph import build_relationship_graph
from scanner import BluetoothRadarScanner, DiscoveredDevice, demo_scan


class DashboardState:
    def __init__(self, source: str, status: str = "starting") -> None:
        self.source = source
        self.status = status
        self.devices: dict[str, DiscoveredDevice] = {}
        self.sequence = 0
        self.error: str | None = None
        self.message: str | None = None
        self.started_at = time.time()

    def update(self, device: DiscoveredDevice) -> None:
        self.devices[device.address] = device
        self.sequence += 1
        self.status = "streaming"
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
    state.status = "scanning"
    state.message = (
        "Scanning for nearby BLE advertisements. Results appear here as they "
        "are observed."
    )
    scanner = BluetoothRadarScanner(
        active=active, adapter=adapter, on_update=state.update
    )
    await scanner.run_continuous(empty_timeout=15.0)


async def _run_dashboard_stream(
    state: DashboardState,
    *,
    demo: bool,
    active: bool,
    adapter: str | None,
    auto_demo_fallback: bool,
) -> None:
    if demo:
        state.source = "SIMULATED LIVE"
        state.status = "demo"
        await _demo_stream(state)
        return

    state.source = "LIVE BLE"
    try:
        await _live_stream(state, active, adapter)
    except asyncio.CancelledError:
        raise
    except Exception as error:
        if not auto_demo_fallback:
            state.status = "error"
            state.error = str(error)
            state.message = (
                "Live scanning failed and auto-demo fallback is disabled."
            )
            while True:
                await asyncio.sleep(3600)
            return

        state.source = "SIMULATED LIVE (fallback)"
        state.status = "fallback"
        state.error = str(error)
        state.message = (
            "Live scanning did not produce results. Showing simulated devices "
            "so the dashboard remains usable."
        )
        await _demo_stream(state)


def create_app(
    *,
    demo: bool = False,
    active: bool = True,
    adapter: str | None = None,
    auto_demo_fallback: bool = True,
) -> FastAPI:
    initial_source = "SIMULATED LIVE" if demo else "LIVE BLE"
    state = DashboardState(initial_source)

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
                auto_demo_fallback=auto_demo_fallback,
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
        return HTMLResponse(DASHBOARD_HTML)

    @app.get("/api/snapshot")
    async def snapshot() -> dict[str, Any]:
        return state.snapshot()

    return app


def _available_port(host: str, preferred: int) -> int:
    for port in range(preferred, preferred + 50):
        with socket.socket() as candidate:
            try:
                candidate.bind((host, port))
            except OSError:
                continue
            return port
    raise OSError("no available dashboard port found")


def run_dashboard(args: Any) -> int:
    port = _available_port(args.host, args.port)
    url = f"http://{args.host}:{port}"
    print(f"BluetoothRadar dashboard: {url}", flush=True)
    if args.demo:
        print("Running in demo mode with simulated devices.", flush=True)
    elif args.no_auto_demo_fallback:
        print("Running live scan without automatic demo fallback.", flush=True)
    else:
        print(
            "Running live scan with automatic demo fallback if no devices appear.",
            flush=True,
        )
    if args.open_browser:
        Timer(0.8, lambda: webbrowser.open(url)).start()
    uvicorn.run(
        create_app(
            demo=args.demo,
            active=args.scan_mode == "active",
            adapter=args.adapter,
            auto_demo_fallback=not args.no_auto_demo_fallback,
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
.grid{display:grid;grid-template-columns:minmax(520px,1.25fr) minmax(380px,.75fr);gap:14px;margin-top:14px}.panel{overflow:hidden}
.panel h2{font-size:13px;letter-spacing:.1em;margin:0;padding:14px 16px;border-bottom:1px solid var(--line);color:#bcd0e7}
.table-wrap{max-height:480px;overflow:auto}table{width:100%;border-collapse:collapse}th,td{padding:11px 12px;border-bottom:1px solid #1e2938;text-align:left}
th{position:sticky;top:0;background:#121b28;color:var(--muted);cursor:pointer;font-size:11px}.rssi{font-weight:700;color:var(--cyan)}
.hidden{color:var(--red);font-weight:700}.service{max-width:170px;color:var(--muted);font-size:11px;overflow-wrap:anywhere}
.empty{padding:28px 16px;color:var(--muted);line-height:1.6}.banner{margin:0 0 14px;padding:12px 16px;border:1px solid var(--line);border-radius:10px;background:#121b28cc;color:var(--muted)}
.banner.warn{border-color:#7c5d12;color:var(--amber)}.banner.error{border-color:#7f1d1d;color:var(--red)}
#graph{display:block;width:100%;height:355px;background:linear-gradient(#0e1622aa 1px,transparent 1px),linear-gradient(90deg,#0e1622aa 1px,transparent 1px);background-size:26px 26px}
.edge{stroke:#536984}.node{cursor:pointer;stroke:#d9f5ff;stroke-width:1.5}.node.hidden-node{fill:var(--red)}.node.visible-node{fill:var(--cyan)}
.node-label{fill:#eaf6ff;font-size:10px;pointer-events:none}.edge-label{fill:#8ea0b8;font-size:9px}.detail{min-height:120px;padding:14px 16px;color:var(--muted);line-height:1.55}
.detail strong{color:#fff}.intel{padding:13px 16px;min-height:115px}.intel div{margin:5px 0;color:var(--muted)}
@media(max-width:950px){.stats{grid-template-columns:repeat(2,1fr)}.grid{grid-template-columns:1fr}}
</style></head>
<body><header><div><h1><span class="mark">◉</span> BLUETOOTH/RADAR</h1><div class="sub">Advertisement telemetry · relationship hypotheses</div></div>
<div class="status"><span class="pulse"></span><span id="sourceBadge" class="badge">CONNECTING</span></div></header>
<main><div id="banner" class="banner">Connecting to scanner stream…</div><section class="stats"><div class="card">DEVICES<div id="countValue" class="value">0</div></div>
<div class="card">IDENTITY-LIMITED<div id="hiddenValue" class="value">0</div></div>
<div class="card">UPDATES<div id="seqValue" class="value">0</div></div>
<div class="card">LAST FRAME<div id="ageValue" class="value">—</div></div></section>
<section class="grid"><div class="panel"><h2>LIVE ADVERTISEMENT TABLE · CLICK HEADERS TO SORT</h2><div class="table-wrap">
<table><thead><tr><th data-sort="name">DEVICE</th><th data-sort="address">IDENTIFIER</th><th data-sort="rssi">RSSI</th><th>MANUFACTURER</th><th>SERVICES</th></tr></thead><tbody id="deviceRows"></tbody></table>
<div id="emptyState" class="empty">Waiting for the first BLE advertisement…</div></div></div>
<div><div class="panel"><h2>INFERRED RELATIONSHIP GRAPH</h2><svg id="graph" viewBox="0 0 600 355"></svg>
<div id="detail" class="detail">Select a node for observed details. Edges are heuristics, not confirmed connections.</div></div>
<div class="panel" style="margin-top:14px"><h2>GRAPH INTELLIGENCE</h2><div id="intel" class="intel"></div></div></div></section></main>
<script>
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
let snapshot=null,sortKey="rssi",selected=null;
const esc=(value)=>String(value??"").replace(/[&<>"']/g,(char)=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
document.querySelectorAll("th[data-sort]").forEach((header)=>{
  header.addEventListener("click",()=>{sortKey=header.dataset.sort;render();});
});
function renderBanner(){
  if(!snapshot){ui.banner.textContent="Connecting to scanner stream…";ui.banner.className="banner";return;}
  if(snapshot.message){ui.banner.textContent=snapshot.message;ui.banner.className=snapshot.error?"banner warn":"banner";}
  else if(snapshot.error){ui.banner.textContent=snapshot.error;ui.banner.className="banner error";}
  else if(snapshot.devices.length===0 && snapshot.status==="scanning"){
    ui.banner.textContent="Scanning for nearby BLE advertisements…";
    ui.banner.className="banner";
  }else{ui.banner.textContent="";ui.banner.className="banner";}
}
function renderTable(devices){
  ui.rows.innerHTML=devices.map((device)=>`<tr><td class="${device.identity_limited?"hidden":""}">${device.identity_limited?"🕵️ HIDDEN":esc(device.name||"Unnamed")}</td><td>${esc(device.address)}</td><td class="rssi">${device.rssi} dBm</td><td>${esc((device.manufacturer_data||[]).map((item)=>item.company).join(", ")||"—")}</td><td class="service">${esc((device.service_uuids||[]).join(", ")||"—")}</td></tr>`).join("");
  ui.empty.style.display=devices.length?"none":"block";
  ui.empty.textContent=snapshot && snapshot.status==="scanning" ? "Scanning for nearby BLE advertisements…" : "No devices observed yet.";
}
function renderGraph(){
  const nodes=snapshot.graph.nodes,positions={};
  nodes.forEach((node,index)=>{
    const angle=-Math.PI/2+index*2*Math.PI/Math.max(nodes.length,1);
    positions[node.id]={x:300+190*Math.cos(angle),y:175+125*Math.sin(angle)};
  });
  ui.graph.innerHTML="";
  snapshot.graph.edges.forEach((edge)=>{
    const start=positions[edge.source],end=positions[edge.target];
    const line=document.createElementNS("http://www.w3.org/2000/svg","line");
    line.setAttribute("x1",start.x);line.setAttribute("y1",start.y);
    line.setAttribute("x2",end.x);line.setAttribute("y2",end.y);
    line.setAttribute("class","edge");line.setAttribute("stroke-width",1+edge.weight*5);
    ui.graph.appendChild(line);
    const label=document.createElementNS("http://www.w3.org/2000/svg","text");
    label.setAttribute("x",(start.x+end.x)/2);label.setAttribute("y",(start.y+end.y)/2);
    label.setAttribute("class","edge-label");label.textContent=edge.weight.toFixed(2);
    ui.graph.appendChild(label);
  });
  nodes.forEach((node)=>{
    const point=positions[node.id];
    const circle=document.createElementNS("http://www.w3.org/2000/svg","circle");
    circle.setAttribute("cx",point.x);circle.setAttribute("cy",point.y);
    circle.setAttribute("r",selected===node.id?20:15);
    circle.setAttribute("class",`node ${node.hidden?"hidden-node":"visible-node"}`);
    circle.addEventListener("click",()=>selectNode(node.id));
    ui.graph.appendChild(circle);
    const label=document.createElementNS("http://www.w3.org/2000/svg","text");
    label.setAttribute("x",point.x);label.setAttribute("y",point.y+31);
    label.setAttribute("text-anchor","middle");label.setAttribute("class","node-label");
    label.textContent=node.label;ui.graph.appendChild(label);
  });
}
function render(){
  if(!snapshot)return;
  const devices=[...snapshot.devices].sort((left,right)=>{
    if(sortKey==="rssi")return right.rssi-left.rssi;
    return String(left[sortKey]||"").localeCompare(String(right[sortKey]||""));
  });
  ui.source.textContent=snapshot.source;
  ui.count.textContent=devices.length;
  ui.hidden.textContent=devices.filter((device)=>device.identity_limited).length;
  ui.seq.textContent=snapshot.sequence;
  ui.age.textContent=devices.length?`${Math.max(0,Date.now()/1000-Math.max(...devices.map((device)=>device.last_seen))).toFixed(1)}s`:"—";
  renderBanner();renderTable(devices);renderGraph();
  const hubs=snapshot.analysis.hubs.map((hub)=>snapshot.graph.nodes.find((node)=>node.id===hub.id)?.label||hub.id);
  ui.intel.innerHTML=`<div><strong>Hub candidates:</strong> ${esc(hubs.join(", ")||"none")}</div><div><strong>Clusters:</strong> ${snapshot.analysis.clusters.length}</div><div><strong>Overlapping:</strong> ${esc(snapshot.analysis.multi_cluster_devices.join(", ")||"none")}</div>`;
}
function selectNode(id){
  selected=id;
  const device=snapshot.devices.find((item)=>item.address===id);
  if(!device)return;
  const edges=snapshot.graph.edges.filter((edge)=>edge.source===id||edge.target===id);
  ui.detail.innerHTML=`<strong>${esc(device.name||"🕵️ Hidden")}</strong><br>${esc(device.address)} · ${device.rssi} dBm · ${device.sightings} sightings<br>${esc((device.manufacturer_data||[]).map((item)=>`${item.company} ${item.frame_type||""}`.trim()).join(", ")||"No manufacturer data")}<br>${edges.length} inferred edge(s)`;
  renderGraph();
}
async function load(){
  try{
    const response=await fetch("/api/snapshot",{cache:"no-store"});
    if(!response.ok)throw new Error(`HTTP ${response.status}`);
    snapshot=await response.json();
    render();
  }catch(error){
    ui.source.textContent="DISCONNECTED";
    ui.banner.textContent=`Could not reach /api/snapshot (${error.message}). Is the dashboard server running?`;
    ui.banner.className="banner error";
  }
}
load();
setInterval(load,700);
setInterval(()=>{if(snapshot)render();},200);
</script></body></html>"""
