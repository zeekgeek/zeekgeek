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


class WebRouteTests(unittest.TestCase):
    def test_routes_exist(self) -> None:
        app = create_app(RadarState())
        paths = {route.path: route.methods for route in app.routes if hasattr(route, "methods")}
        self.assertIn("/", paths)
        self.assertIn("/api/state", paths)
        self.assertIn("/api/events", paths)
        self.assertIn("/api/trace", paths)
        self.assertIn("/api/speedtest", paths)
        self.assertIn("GET", paths["/api/state"])
        self.assertIn("POST", paths["/api/trace"])


if __name__ == "__main__":
    unittest.main()
