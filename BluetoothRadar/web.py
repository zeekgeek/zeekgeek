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
    def __init__(self, source: str) -> None:
        self.source = source
        self.devices: dict[str, DiscoveredDevice] = {}
        self.sequence = 0
        self.error: str | None = None
        self.started_at = time.time()

    def update(self, device: DiscoveredDevice) -> None:
        self.devices[device.address] = device
        self.sequence += 1
        self.error = None

    def snapshot(self) -> dict[str, Any]:
        devices = sorted(
            self.devices.values(), key=lambda item: item.rssi, reverse=True
        )
        graph = build_relationship_graph(devices)
        report = analyze_graph(graph)
        return {
            "source": self.source,
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


async def _demo_stream(state: DashboardState) -> None:
    devices = await demo_scan(0.2)
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
    while True:
        try:
            scanner = BluetoothRadarScanner(
                active=active, adapter=adapter, on_update=state.update
            )
            await scanner.scan(8.0)
        except asyncio.CancelledError:
            raise
        except Exception as error:  # hardware/backend errors belong in the UI
            state.error = str(error)
            await asyncio.sleep(2.0)


def create_app(
    *, demo: bool = False, active: bool = True, adapter: str | None = None
) -> FastAPI:
    source = "SIMULATED LIVE" if demo else "LIVE BLE"
    state = DashboardState(source)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        stream = _demo_stream(state) if demo else _live_stream(state, active, adapter)
        task = asyncio.create_task(stream)
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
    if args.open_browser:
        Timer(0.8, lambda: webbrowser.open(url)).start()
    uvicorn.run(
        create_app(
            demo=args.demo,
            active=args.scan_mode == "active",
            adapter=args.adapter,
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
--red:#ff496a;--muted:#8ea0b8;--green:#38e29b}*{box-sizing:border-box}
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
#graph{display:block;width:100%;height:355px;background:linear-gradient(#0e1622aa 1px,transparent 1px),linear-gradient(90deg,#0e1622aa 1px,transparent 1px);background-size:26px 26px}
.edge{stroke:#536984}.node{cursor:pointer;stroke:#d9f5ff;stroke-width:1.5}.node.hidden-node{fill:var(--red)}.node.visible-node{fill:var(--cyan)}
.node-label{fill:#eaf6ff;font-size:10px;pointer-events:none}.edge-label{fill:#8ea0b8;font-size:9px}.detail{min-height:120px;padding:14px 16px;color:var(--muted);line-height:1.55}
.detail strong{color:#fff}.intel{padding:13px 16px;min-height:115px}.intel div{margin:5px 0;color:var(--muted)}.error{color:var(--red)}
@media(max-width:950px){.stats{grid-template-columns:repeat(2,1fr)}.grid{grid-template-columns:1fr}}
</style></head>
<body><header><div><h1><span class="mark">◉</span> BLUETOOTH/RADAR</h1><div class="sub">Advertisement telemetry · relationship hypotheses</div></div>
<div class="status"><span class="pulse"></span><span id="source" class="badge">CONNECTING</span></div></header>
<main><section class="stats"><div class="card">DEVICES<div id="count" class="value">0</div></div>
<div class="card">IDENTITY-LIMITED<div id="hidden" class="value">0</div></div>
<div class="card">UPDATES<div id="seq" class="value">0</div></div>
<div class="card">LAST FRAME<div id="age" class="value">—</div></div></section>
<section class="grid"><div class="panel"><h2>LIVE ADVERTISEMENT TABLE · CLICK HEADERS TO SORT</h2><div class="table-wrap">
<table><thead><tr><th data-sort="name">DEVICE</th><th data-sort="address">IDENTIFIER</th><th data-sort="rssi">RSSI</th><th>MANUFACTURER</th><th>SERVICES</th></tr></thead><tbody id="rows"></tbody></table></div></div>
<div><div class="panel"><h2>INFERRED RELATIONSHIP GRAPH</h2><svg id="graph" viewBox="0 0 600 355"></svg>
<div id="detail" class="detail">Select a node for observed details. Edges are heuristics, not confirmed connections.</div></div>
<div class="panel" style="margin-top:14px"><h2>GRAPH INTELLIGENCE</h2><div id="intel" class="intel"></div></div></div></section></main>
<script>
let snapshot=null, sortKey="rssi", selected=null;
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
document.querySelectorAll("th[data-sort]").forEach(th=>th.onclick=()=>{sortKey=th.dataset.sort;render()});
function render(){
 if(!snapshot)return; const ds=[...snapshot.devices].sort((a,b)=>sortKey==="rssi"?b.rssi-a.rssi:String(a[sortKey]||"").localeCompare(String(b[sortKey]||"")));
 source.textContent=snapshot.source; count.textContent=ds.length; hidden.textContent=ds.filter(d=>d.identity_limited).length; seq.textContent=snapshot.sequence;
 age.textContent=snapshot.devices.length?Math.max(0,Date.now()/1000-Math.max(...snapshot.devices.map(d=>d.last_seen))).toFixed(1)+"s":"—";
 rows.innerHTML=ds.map(d=>`<tr><td class="${d.identity_limited?"hidden":""}">${d.identity_limited?"🕵️ HIDDEN":esc(d.name||"Unnamed")}</td><td>${esc(d.address)}</td><td class="rssi">${d.rssi} dBm</td><td>${esc(d.manufacturer_data.map(m=>m.company).join(", ")||"—")}</td><td class="service">${esc(d.service_uuids.join(", ")||"—")}</td></tr>`).join("");
 drawGraph(); const hubs=snapshot.analysis.hubs.map(h=>snapshot.graph.nodes.find(n=>n.id===h.id)?.label||h.id);
 intel.innerHTML=`<div><strong>Hub candidates:</strong> ${esc(hubs.join(", ")||"none")}</div><div><strong>Clusters:</strong> ${snapshot.analysis.clusters.length}</div><div><strong>Overlapping:</strong> ${esc(snapshot.analysis.multi_cluster_devices.join(", ")||"none")}</div>${snapshot.error?`<div class="error">${esc(snapshot.error)}</div>`:""}`;
}
function drawGraph(){const svg=document.getElementById("graph"),ns="http://www.w3.org/2000/svg",nodes=snapshot.graph.nodes,n=nodes.length;
 const pos={};nodes.forEach((d,i)=>{const a=-Math.PI/2+i*2*Math.PI/Math.max(n,1);pos[d.id]={x:300+190*Math.cos(a),y:175+125*Math.sin(a)}});
 svg.innerHTML="";snapshot.graph.edges.forEach(e=>{let a=pos[e.source],b=pos[e.target],l=document.createElementNS(ns,"line");l.setAttribute("x1",a.x);l.setAttribute("y1",a.y);l.setAttribute("x2",b.x);l.setAttribute("y2",b.y);l.setAttribute("class","edge");l.setAttribute("stroke-width",1+e.weight*5);svg.appendChild(l);
 let t=document.createElementNS(ns,"text");t.setAttribute("x",(a.x+b.x)/2);t.setAttribute("y",(a.y+b.y)/2);t.setAttribute("class","edge-label");t.textContent=e.weight.toFixed(2);svg.appendChild(t)});
 nodes.forEach(d=>{let p=pos[d.id],c=document.createElementNS(ns,"circle");c.setAttribute("cx",p.x);c.setAttribute("cy",p.y);c.setAttribute("r",selected===d.id?20:15);c.setAttribute("class",`node ${d.hidden?"hidden-node":"visible-node"}`);c.onclick=()=>selectNode(d.id);svg.appendChild(c);
 let t=document.createElementNS(ns,"text");t.setAttribute("x",p.x);t.setAttribute("y",p.y+31);t.setAttribute("text-anchor","middle");t.setAttribute("class","node-label");t.textContent=d.label;svg.appendChild(t)});
}
function selectNode(id){selected=id;let d=snapshot.devices.find(x=>x.address===id),edges=snapshot.graph.edges.filter(e=>e.source===id||e.target===id);
 detail.innerHTML=`<strong>${esc(d.name||"🕵️ Hidden")}</strong><br>${esc(d.address)} · ${d.rssi} dBm · ${d.sightings} sightings<br>${esc(d.manufacturer_data.map(m=>m.company+" "+(m.frame_type||"")).join(", ")||"No manufacturer data")}<br>${edges.length} inferred edge(s)`;drawGraph()}
async function load(){try{let r=await fetch("/api/snapshot",{cache:"no-store"});snapshot=await r.json();render()}catch(e){source.textContent="DISCONNECTED"}}
load();setInterval(load,700);setInterval(()=>{if(snapshot)render()},200);
</script></body></html>"""

