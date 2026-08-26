"""Unit tests for the visual 3D traceroute radar."""

from __future__ import annotations

import asyncio
import unittest

from trace_radar.geoip import GeoInfo, is_private_ip
from trace_radar.speedtest import compute_jitter, summarize_rtts, throughput_mbps
from trace_radar.state import HopObservation, RadarState, loss_percent
from trace_radar.tracer import DemoTracerBackend, parse_traceroute_output, parse_tracepath_output
from trace_radar.web import create_app
from trace_radar.whois import WhoisInfo, WhoisResolver, parse_rdap


SAMPLE_TRACEROUTE = """
traceroute to one.one.one.one (1.1.1.1), 30 hops max, 60 byte packets
 1  192.168.1.1  1.234 ms  1.100 ms  1.050 ms  1.080 ms  1.090 ms
 2  24.7.128.1  8.500 ms  8.400 ms  *  8.600 ms  *
 3  * * * * *
 4  edge.example.net (4.69.140.94)  40.1 ms  39.8 ms  40.0 ms  40.2 ms  39.9 ms
 5  1.1.1.1  15.0 ms  14.8 ms  15.1 ms  14.9 ms  15.2 ms
"""

SAMPLE_TRACEPATH = """
 1?: [LOCALHOST]                      pmtu 1500
 1:  192.168.1.1                                           1.234ms
 2:  no reply
 3:  1.1.1.1                                              15.000ms
"""


class GeoIpTests(unittest.TestCase):
    def test_private_detection(self) -> None:
        self.assertTrue(is_private_ip("192.168.1.1"))
        self.assertTrue(is_private_ip("10.0.0.1"))
        self.assertTrue(is_private_ip("127.0.0.1"))
        self.assertFalse(is_private_ip("1.1.1.1"))
        self.assertFalse(is_private_ip("not-an-ip"))


class SpeedMathTests(unittest.TestCase):
    def test_jitter(self) -> None:
        self.assertEqual(compute_jitter([10.0, 12.0, 11.0]), 1.5)
        self.assertEqual(compute_jitter([5.0]), 0.0)

    def test_summarize_rtts(self) -> None:
        summary = summarize_rtts([10.0, None, 12.0, 11.0])
        self.assertEqual(summary["loss_pct"], 25.0)
        self.assertEqual(summary["min_ms"], 10.0)
        self.assertEqual(summary["max_ms"], 12.0)
        self.assertAlmostEqual(summary["avg_ms"], 11.0)

    def test_throughput(self) -> None:
        self.assertEqual(throughput_mbps(1_000_000, 1.0), 8.0)


class LossPercentTests(unittest.TestCase):
    def test_loss_percent(self) -> None:
        self.assertEqual(loss_percent(5, 5), 0.0)
        self.assertEqual(loss_percent(5, 3), 40.0)
        self.assertEqual(loss_percent(0, 0), 0.0)


class TracerouteParserTests(unittest.TestCase):
    def test_parse_traceroute_with_partial_loss(self) -> None:
        hops = parse_traceroute_output(SAMPLE_TRACEROUTE, probes=5)
        self.assertEqual(len(hops), 5)
        self.assertEqual(hops[0].ip, "192.168.1.1")
        self.assertEqual(len(hops[0].rtts_ms), 5)
        self.assertEqual(hops[0].probes, 5)

        # Hop 2: 3 answers + 2 stars → 40% loss this cycle
        self.assertEqual(hops[1].ip, "24.7.128.1")
        self.assertEqual(len(hops[1].rtts_ms), 3)
        self.assertEqual(hops[1].probes, 5)
        self.assertEqual(loss_percent(hops[1].probes, len(hops[1].rtts_ms)), 40.0)

        # Fully silent hop
        self.assertIsNone(hops[2].ip)
        self.assertEqual(hops[2].rtts_ms, [])
        self.assertEqual(loss_percent(hops[2].probes, 0), 100.0)

        self.assertEqual(hops[3].hostname, "edge.example.net")
        self.assertEqual(hops[3].ip, "4.69.140.94")
        self.assertEqual(hops[4].ip, "1.1.1.1")

    def test_parse_tracepath(self) -> None:
        hops = parse_tracepath_output(SAMPLE_TRACEPATH)
        self.assertEqual(len(hops), 3)
        self.assertEqual(hops[0].ip, "192.168.1.1")
        self.assertIsNone(hops[1].ip)
        self.assertEqual(hops[2].ip, "1.1.1.1")


class WhoisTests(unittest.TestCase):
    def test_parse_rdap(self) -> None:
        payload = {
            "handle": "CLOUDFLARENET",
            "name": "CLOUDFLARENET",
            "startAddress": "104.16.0.0",
            "endAddress": "104.31.255.255",
            "country": "US",
            "type": "ALLOCATED PA",
            "status": ["active"],
            "cidr0_cidrs": [{"v4prefix": "104.16.0.0", "length": 12}],
            "entities": [
                {
                    "roles": ["registrant"],
                    "vcardArray": [
                        "vcard",
                        [
                            ["version", {}, "text", "4.0"],
                            ["fn", {}, "text", "Cloudflare, Inc."],
                        ],
                    ],
                },
                {
                    "roles": ["abuse"],
                    "vcardArray": [
                        "vcard",
                        [
                            ["fn", {}, "text", "Abuse"],
                            ["email", {}, "text", "abuse@cloudflare.com"],
                            ["tel", {}, "text", "+1-555-0100"],
                        ],
                    ],
                },
            ],
        }
        info = parse_rdap("104.16.248.249", payload)
        self.assertTrue(info.found)
        self.assertEqual(info.name, "CLOUDFLARENET")
        self.assertEqual(info.cidr, "104.16.0.0/12")
        self.assertEqual(info.registrant, "Cloudflare, Inc.")
        self.assertEqual(info.abuse_email, "abuse@cloudflare.com")
        self.assertIn("Cloudflare", info.summary())

    def test_demo_whois_resolver(self) -> None:
        resolver = WhoisResolver(demo=True)

        async def _run() -> dict[str, WhoisInfo]:
            return await resolver.lookup_many(["1.1.1.1", "192.168.1.1", "9.9.9.9"])

        results = asyncio.run(_run())
        self.assertTrue(results["1.1.1.1"].found)
        self.assertTrue(results["192.168.1.1"].is_private)
        self.assertFalse(results["9.9.9.9"].found)


class RequestTraceTests(unittest.TestCase):
    def test_retrace_queues_existing_target(self) -> None:
        async def _run() -> tuple[bool, bool, str | None]:
            state = RadarState(demo_mode=True)
            first = await state.request_trace("example.com")
            second = await state.request_trace("example.com")
            queued = await state.next_new_target(timeout=0.1)
            # Drain the first queued item from the initial create, then the re-trace.
            # After create+retrace the queue has two entries; pull until empty.
            seen = [queued]
            while True:
                item = await state.next_new_target(timeout=0.05)
                if item is None:
                    break
                seen.append(item)
            return first, second, seen

        first, second, seen = asyncio.run(_run())
        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(seen.count("example.com"), 2)


class StateTests(unittest.TestCase):
    def test_ingest_accumulates_packet_loss_and_whois(self) -> None:
        async def _run() -> dict:
            state = RadarState(demo_mode=True)
            whois = WhoisInfo(
                ip="24.7.128.1",
                name="COMCAST",
                org="Comcast Cable Communications, LLC",
                cidr="24.7.128.0/17",
                found=True,
            )
            hops = [
                HopObservation(
                    ttl=1,
                    ip="192.168.1.1",
                    rtts_ms=[1.0, 1.1, 1.2, 1.0, 1.1],
                    probes=5,
                    hostname="gw",
                    geo=GeoInfo(ip="192.168.1.1", is_private=True),
                ),
                HopObservation(
                    ttl=2,
                    ip="24.7.128.1",
                    rtts_ms=[8.0, 8.1, 8.2],
                    probes=5,
                    hostname="isp",
                    geo=GeoInfo(
                        ip="24.7.128.1",
                        lat=37.3,
                        lon=-121.9,
                        city="San Jose",
                        country="United States",
                        isp="Comcast",
                        asn="AS7922",
                    ),
                    whois=whois,
                ),
            ]
            await state.ingest_trace(
                "example.com",
                resolved_ip="24.7.128.1",
                hops=hops,
                destination_reached=True,
            )
            # Second cycle: more loss on hop 2
            hops2 = [
                HopObservation(ttl=1, ip="192.168.1.1", rtts_ms=[1.0, 1.0, 1.0, 1.0, 1.0], probes=5),
                HopObservation(
                    ttl=2,
                    ip="24.7.128.1",
                    rtts_ms=[8.0, 8.5],
                    probes=5,
                    whois=whois,
                ),
            ]
            await state.ingest_trace(
                "example.com",
                resolved_ip="24.7.128.1",
                hops=hops2,
                destination_reached=True,
            )
            return await state.snapshot()

        snap = asyncio.run(_run())
        route = snap["routes"][0]
        hop2 = route["hops"][1]
        self.assertEqual(hop2["probes_sent"], 10)
        self.assertEqual(hop2["probes_answered"], 5)
        self.assertEqual(hop2["loss_pct"], 50.0)
        self.assertEqual(hop2["last_loss_pct"], 60.0)
        self.assertTrue(hop2["whois"]["found"])
        self.assertEqual(hop2["whois"]["org"], "Comcast Cable Communications, LLC")
        self.assertEqual(route["packet_loss_pct"], 25.0)  # 5 lost of 20 total probes


class DemoBackendTests(unittest.TestCase):
    def test_demo_emits_geolocated_routes_with_whois(self) -> None:
        async def _run() -> dict:
            state = RadarState(demo_mode=True)
            backend = DemoTracerBackend(state, targets=["one.one.one.one"], interval=60.0, probes=5)
            task = asyncio.create_task(backend.run())
            for _ in range(40):
                snap = await state.snapshot()
                if snap["routes"] and snap["routes"][0]["hop_count"] > 0:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                    return snap
                await asyncio.sleep(0.05)
            task.cancel()
            raise AssertionError("demo backend produced no hops")

        snap = asyncio.run(_run())
        route = snap["routes"][0]
        self.assertGreaterEqual(route["hop_count"], 4)
        self.assertGreaterEqual(route["located_count"], 2)
        self.assertGreaterEqual(route["whois_count"], 1)
        # At least one hop should report loss or an unresponsive hop exists
        self.assertTrue(
            route["lossy_hop_count"] > 0
            or any(not hop["responded"] for hop in route["hops"])
        )
        self.assertIsNotNone(snap["origin"])
        self.assertTrue(snap["origin"]["lat"] is not None)


class AnalysisTests(unittest.TestCase):
    def test_introduced_latency_marks_slow_hop(self) -> None:
        from trace_radar.analysis import annotate_hops, problem_cards

        hops = annotate_hops(
            [
                {"ttl": 1, "responded": True, "rtt_avg_ms": 1.0, "last_loss_pct": 0, "health": "good", "ip": "192.168.1.1", "is_private": True},
                {"ttl": 2, "responded": True, "rtt_avg_ms": 12.0, "last_loss_pct": 0, "health": "good", "ip": "24.7.128.1"},
                {
                    "ttl": 3,
                    "responded": True,
                    "rtt_avg_ms": 88.0,
                    "last_loss_pct": 0,
                    "health": "degraded",
                    "ip": "4.69.140.94",
                    "whois": {"org": "Level 3 Parent, LLC", "asn": "AS3356", "cidr": "4.0.0.0/9", "abuse_email": "abuse@level3.com", "summary": "Level 3"},
                    "geo": {"city": "Ashburn", "country": "United States", "place": "Ashburn, United States", "isp": "Level 3"},
                },
                {"ttl": 4, "responded": True, "rtt_avg_ms": 90.0, "last_loss_pct": 0, "health": "good", "ip": "1.1.1.1"},
            ]
        )
        self.assertEqual(hops[0]["added_ms"], 1.0)
        self.assertEqual(hops[1]["added_ms"], 11.0)
        self.assertGreaterEqual(hops[2]["added_ms"], 25.0)
        self.assertTrue(hops[2]["slow"])
        self.assertEqual(hops[2]["problem_reason"], "latency-introduced")
        self.assertEqual(hops[2]["health"], "degraded")
        self.assertFalse(hops[3]["slow"])  # inherited RTT, little added
        cards = problem_cards(hops)
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["provider"], "Level 3 Parent, LLC")
        self.assertIn("Ashburn", cards[0]["detail"])
        self.assertIn("abuse@level3.com", cards[0]["detail"])

    def test_icmp_filtered_not_problem(self) -> None:
        from trace_radar.analysis import annotate_hops, problem_cards

        hops = annotate_hops(
            [
                {"ttl": 1, "responded": True, "rtt_avg_ms": 2.0, "last_loss_pct": 0, "ip": "192.168.1.1"},
                {"ttl": 2, "responded": False, "rtt_avg_ms": None, "last_loss_pct": 100.0, "ip": None},
                {"ttl": 3, "responded": True, "rtt_avg_ms": 20.0, "last_loss_pct": 0, "ip": "1.1.1.1"},
            ]
        )
        self.assertTrue(hops[1]["icmp_filtered"])
        self.assertFalse(hops[1]["slow"])
        self.assertEqual(problem_cards(hops), [])


class GraphTests(unittest.TestCase):
    def test_sample_graph_and_shared_hops(self) -> None:
        from trace_radar.graph import SAMPLE_LAN, build_topology

        routes = [
            {
                "target": "one.one.one.one",
                "hops": [
                    {"ttl": 1, "ip": "192.168.1.1", "hostname": "gw", "is_private": True, "responded": True, "rtt_avg_ms": 1.2, "health": "good"},
                    {"ttl": 2, "ip": "1.1.1.1", "hostname": "one.one.one.one", "responded": True, "rtt_avg_ms": 15.0, "health": "good", "slow": False},
                ],
            },
            {
                "target": "google.com",
                "hops": [
                    {"ttl": 1, "ip": "192.168.1.1", "hostname": "gw", "is_private": True, "responded": True, "rtt_avg_ms": 1.1, "health": "good"},
                    {"ttl": 2, "ip": "8.8.8.8", "hostname": "dns.google", "responded": True, "rtt_avg_ms": 18.0, "health": "good"},
                ],
            },
        ]
        graph = build_topology(routes, lan=SAMPLE_LAN)
        ids = {node["id"] for node in graph["nodes"]}
        self.assertIn("lan:you", ids)
        self.assertIn("lan:phone", ids)
        self.assertIn("ip:192.168.1.1", ids)
        self.assertIn("ip:1.1.1.1", ids)
        self.assertIn("ip:8.8.8.8", ids)
        gw_nodes = [n for n in graph["nodes"] if n["id"] == "ip:192.168.1.1"]
        self.assertEqual(len(gw_nodes), 1)
        self.assertEqual(set(gw_nodes[0]["targets"]), {"one.one.one.one", "google.com"})
        self.assertGreaterEqual(len(graph["edges"]), 6)
        self.assertTrue(any(e["kind"] == "lan" for e in graph["edges"]))


class TimelineTests(unittest.TestCase):
    def test_hop_timeline_and_health(self) -> None:
        async def _run() -> dict:
            state = RadarState(demo_mode=True)
            await state.ingest_trace(
                "example.com",
                resolved_ip="1.1.1.1",
                hops=[
                    HopObservation(ttl=1, ip="192.168.1.1", rtts_ms=[1.0, 1.1], probes=5),
                    HopObservation(ttl=2, ip="1.1.1.1", rtts_ms=[15.0], probes=5),
                ],
                destination_reached=True,
            )
            await state.ingest_trace(
                "example.com",
                resolved_ip="1.1.1.1",
                hops=[
                    HopObservation(ttl=1, ip="192.168.1.1", rtts_ms=[1.0, 1.0, 1.0, 1.0, 1.0], probes=5),
                    HopObservation(ttl=2, ip="1.1.1.1", rtts_ms=[], probes=5),
                ],
                destination_reached=True,
            )
            return await state.snapshot()

        snap = asyncio.run(_run())
        hops = snap["routes"][0]["hops"]
        self.assertEqual(len(hops[0]["timeline"]), 2)
        self.assertEqual(hops[0]["health"], "good")
        self.assertEqual(hops[1]["health"], "poor")  # last cycle 100% loss
        self.assertIsNotNone(hops[0]["timeline"][0]["at"])
        snap_graph = snap["graph"]
        self.assertIn("nodes", snap_graph)
        self.assertGreaterEqual(len(snap_graph["nodes"]), 1)


class ScannyToolTests(unittest.TestCase):
    def test_demo_dns_whois_ports_ping(self) -> None:
        from trace_radar.tools import lookup_dns, ping_host, scan_ports
        from trace_radar.whois import WhoisResolver

        async def _run() -> tuple:
            dns = await lookup_dns("one.one.one.one", demo=True)
            ports = await scan_ports("1.1.1.1", demo=True)
            ping = await ping_host("1.1.1.1", count=4, demo=True)
            whois = await WhoisResolver(demo=True).lookup("1.1.1.1")
            state = RadarState(demo_mode=True)
            await state.record_tool_result("dns", "one.one.one.one", dns.to_dict())
            snap = await state.snapshot()
            return dns, ports, ping, whois, snap

        dns, ports, ping, whois, snap = asyncio.run(_run())
        self.assertIn("A", dns.records)
        self.assertIn(443, ports.open_ports)
        self.assertGreaterEqual(ping.answered, 1)
        self.assertTrue(whois.found)
        self.assertEqual(len(snap["tool_results"]), 1)
        self.assertTrue(any(e["type"] == "tool:dns" for e in snap["events"]))


class WebRouteTests(unittest.TestCase):
    def test_routes_exist(self) -> None:
        app = create_app(RadarState())
        paths = {route.path: route.methods for route in app.routes if hasattr(route, "methods")}
        self.assertIn("/", paths)
        self.assertIn("/api/state", paths)
        self.assertIn("/api/events", paths)
        self.assertIn("/api/trace", paths)
        self.assertIn("/api/speedtest", paths)
        self.assertIn("/api/whois", paths)
        self.assertIn("/api/dns", paths)
        self.assertIn("/api/ports", paths)
        self.assertIn("/api/ping", paths)
        self.assertIn("GET", paths["/api/state"])
        self.assertIn("POST", paths["/api/trace"])
        self.assertIn("POST", paths["/api/whois"])

    def test_dashboard_has_force_graph_and_3d_hops(self) -> None:
        from trace_radar.web import DASHBOARD_HTML

        self.assertIn('id="net"', DASHBOARD_HTML)
        self.assertIn('id="hop3d"', DASHBOARD_HTML)
        self.assertIn('id="search"', DASHBOARD_HTML)
        self.assertIn("Reheat", DASHBOARD_HTML)
        self.assertIn("Freeze", DASHBOARD_HTML)


if __name__ == "__main__":
    unittest.main()
