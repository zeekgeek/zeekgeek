"""Unit tests for Path Radar analysis, traceroute parsing, and demo state."""

from __future__ import annotations

import socket
import unittest

from path_radar.analysis import (
    HopReading,
    classify_hops,
    end_to_end_ms,
    find_problems,
    grade_path,
    introduced_ms,
    summarize,
)
from path_radar.lan import default_gateway, local_ipv4
from path_radar.pinger import parse_ping_output, traceroute_from_probes
from path_radar.providers import ip_kind, parse_cymru_asn, parse_cymru_origin, provider_for_ip, reversed_ipv4
from path_radar.state import PathState, _label
from path_radar.topology import DEFAULT_TARGET, node_id_for, sample_graph
from path_radar.tracer import demo_probe, parse_traceroute
from path_radar.__main__ import pick_available_port
from path_radar.web import create_app


class LatencyStatsTests(unittest.TestCase):
    def test_summarize_min_avg_max_jitter_loss(self) -> None:
        stats = summarize([10.0, 12.0, None, 11.0])
        self.assertEqual(stats.count, 4)
        self.assertEqual(stats.timeouts, 1)
        self.assertAlmostEqual(stats.loss_pct, 25.0)
        self.assertEqual(stats.min_ms, 10.0)
        self.assertEqual(stats.max_ms, 12.0)
        self.assertAlmostEqual(stats.avg_ms or 0, 11.0)
        self.assertAlmostEqual(stats.jitter_ms or 0, 1.5)
        self.assertEqual(stats.current_ms, 11.0)

    def test_empty_history_is_all_loss(self) -> None:
        stats = summarize([None, None])
        self.assertIsNone(stats.avg_ms)
        self.assertEqual(stats.loss_pct, 100.0)

    def test_introduced_latency_clamps_negative(self) -> None:
        self.assertEqual(introduced_ms(20, 25), 0.0)
        self.assertAlmostEqual(introduced_ms(90, 12), 78.0)
        self.assertIsNone(introduced_ms(None, 12))


class ClassifyHopTests(unittest.TestCase):
    def test_slow_hop_is_where_delay_enters(self) -> None:
        readings = [
            HopReading(1, "192.168.1.1", "gw", 1.0),
            HopReading(2, "68.86.90.5", "comcast", 11.0),
            HopReading(3, "154.54.30.17", "cogent", 92.0, loss_pct=8.0),
            HopReading(4, "1.1.1.1", "one.one.one.one", 96.0),
        ]
        classified = classify_hops(readings)
        self.assertEqual(classified[0].health, "ok")
        self.assertEqual(classified[1].health, "ok")
        self.assertEqual(classified[2].health, "slow")
        self.assertGreaterEqual(classified[2].added_ms or 0, 70)
        self.assertEqual(classified[3].health, "ok")
        problems = find_problems(classified)
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0].ip, "154.54.30.17")
        self.assertEqual(grade_path(classified, problems), "fair")
        self.assertAlmostEqual(end_to_end_ms(classified) or 0, 96.0)

    def test_icmp_filter_is_not_a_problem(self) -> None:
        readings = [
            HopReading(1, "192.168.1.1", "gw", 1.0),
            HopReading(2, "10.4.0.1", "ont", None, timed_out=True),
            HopReading(3, "8.8.8.8", "dns.google", 16.0),
        ]
        classified = classify_hops(readings)
        self.assertEqual(classified[1].health, "filtered")
        self.assertTrue(classified[1].filtered)
        self.assertEqual(find_problems(classified), [])

    def test_filtered_gap_blames_silent_router(self) -> None:
        readings = [
            HopReading(1, "192.168.1.1", "gw", 1.0),
            HopReading(2, "154.54.30.17", "cogent", None, timed_out=True),
            HopReading(3, "1.1.1.1", "dest", 90.0),
        ]
        classified = classify_hops(readings)
        self.assertEqual(classified[1].health, "slow")
        self.assertEqual(classified[2].health, "ok")
        problems = find_problems(classified)
        self.assertEqual(problems[0].ip, "154.54.30.17")

    def test_hard_timeout_at_end_is_critical(self) -> None:
        readings = [
            HopReading(1, "192.168.1.1", "gw", 1.0),
            HopReading(2, "9.9.9.9", "dead", None, timed_out=True),
        ]
        classified = classify_hops(readings)
        self.assertEqual(classified[1].health, "timeout")
        problems = find_problems(classified)
        self.assertEqual(problems[0].kind, "timeout")
        self.assertEqual(grade_path(classified, problems), "critical")

    def test_lossy_hop(self) -> None:
        readings = [HopReading(1, "1.2.3.4", "rtr", 20.0, loss_pct=22.0)]
        classified = classify_hops(readings)
        self.assertEqual(classified[0].health, "loss")
        self.assertEqual(find_problems(classified)[0].kind, "loss")


class PingParseTests(unittest.TestCase):
    def test_ttl_exceeded(self) -> None:
        text = """
PING 1.1.1.1 (1.1.1.1) 56(84) bytes of data.
From 10.1.3.17 icmp_seq=1 Time to live exceeded
"""
        parsed = parse_ping_output(text)
        self.assertEqual(parsed["ip"], "10.1.3.17")
        self.assertTrue(parsed["ttl_exceeded"])
        self.assertFalse(parsed["reached"])

    def test_echo_reply(self) -> None:
        text = "64 bytes from 1.1.1.1: icmp_seq=1 ttl=55 time=2.20 ms"
        parsed = parse_ping_output(text)
        self.assertEqual(parsed["ip"], "1.1.1.1")
        self.assertTrue(parsed["reached"])
        self.assertAlmostEqual(parsed["rtt_ms"], 2.20)

    def test_timeout(self) -> None:
        parsed = parse_ping_output("PING 1.1.1.1 (1.1.1.1) 56(84) bytes of data.\n")
        self.assertTrue(parsed["timed_out"])
        self.assertIsNone(parsed["ip"])

    def test_stop_at_destination(self) -> None:
        probes = {
            1: {"ip": None, "timed_out": True},
            2: {"ip": "10.1.3.17", "ttl_exceeded": True, "rtt_ms": 2.0, "timed_out": False},
            3: {"ip": "1.1.1.1", "reached": True, "rtt_ms": 2.2, "timed_out": False},
            4: {"ip": "1.1.1.1", "reached": True, "rtt_ms": 2.1, "timed_out": False},
        }
        hops = traceroute_from_probes(probes, {"1.1.1.1"}, 20)
        self.assertEqual(len(hops), 3)
        self.assertEqual(hops[-1]["ip"], "1.1.1.1")
        self.assertTrue(hops[-1]["reached"])


class LiveLookupTests(unittest.TestCase):
    def test_ip_kind(self) -> None:
        self.assertEqual(ip_kind("10.1.3.17"), "private")
        self.assertEqual(ip_kind("192.168.1.1"), "private")
        self.assertEqual(ip_kind("240.0.232.98"), "reserved")
        self.assertEqual(ip_kind("1.1.1.1"), "public")
        self.assertEqual(ip_kind("100.64.0.1"), "cgnat")

    def test_cymru_origin_parse(self) -> None:
        parsed = parse_cymru_origin('"16509 | 52.32.0.0/11 | US | arin | 1991-12-19"')
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["asn"], "16509")
        self.assertEqual(parsed["prefix"], "52.32.0.0/11")
        self.assertEqual(reversed_ipv4("52.46.166.113"), "113.166.46.52")

    def test_cymru_asn_parse(self) -> None:
        parsed = parse_cymru_asn('"16509 | US | arin | 2000-05-04 | AMAZON-02 - Amazon.com, Inc., US"')
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertIn("Amazon", parsed["name"])


class LiveStateTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_mode_does_not_seed_demo_topology(self) -> None:
        state = PathState(mode="live")
        snap = await state.snapshot()
        self.assertEqual(snap["source"], "live")
        self.assertEqual(snap["hops"], [])
        ids = {node["id"] for node in snap["graph"]["nodes"]}
        self.assertNotIn("net:154.54.30.17", ids)
        self.assertNotIn("lan:phone", ids)

    async def test_live_ingest_keeps_provider_lookup(self) -> None:
        state = PathState(mode="live")
        hops = [
            {
                "hop": 1,
                "ip": "10.1.3.17",
                "hostname": None,
                "rtts": [1.4],
                "timed_out": False,
                "lookup": {"asn": "PRIVATE", "provider": "Home network", "provider_detail": {"asn": "PRIVATE", "name": "LAN"}},
            },
            {
                "hop": 2,
                "ip": "1.1.1.1",
                "hostname": "one.one.one.one",
                "rtts": [2.2],
                "timed_out": False,
                "lookup": {
                    "asn": "AS13335",
                    "provider": "Cloudflare",
                    "as_name": "Cloudflare, Inc.",
                    "city": "Anycast",
                    "provider_detail": {"asn": "AS13335", "name": "Cloudflare, Inc.", "aka": "Cloudflare"},
                },
            },
        ]
        await state.ingest_live(hops, target="1.1.1.1", source="live")
        snap = await state.snapshot()
        self.assertEqual(snap["target"], "1.1.1.1")
        dest = snap["hops"][-1]
        self.assertEqual(dest["ip"], "1.1.1.1")
        self.assertEqual(dest["asn"], "AS13335")
        self.assertEqual(dest["provider"], "Cloudflare")
        self.assertEqual(dest["label"], "one.one.one.one")
        self.assertNotIn("154.54.30.17", [hop["ip"] for hop in snap["hops"]])

    async def test_companion_trace_stays_on_graph_not_hud(self) -> None:
        state = PathState(mode="live")
        await state.set_target("1.1.1.1")
        await state.ingest_live(
            [
                {
                    "hop": 1,
                    "ip": "10.1.3.17",
                    "hostname": None,
                    "rtts": [1.0],
                    "timed_out": False,
                    "lookup": {"asn": "PRIVATE", "provider": "Home network"},
                },
                {
                    "hop": 2,
                    "ip": "1.1.1.1",
                    "hostname": "one.one.one.one",
                    "rtts": [2.0],
                    "timed_out": False,
                    "lookup": {
                        "asn": "AS13335",
                        "provider": "Cloudflare",
                        "city": "Anycast",
                        "notes": "Anycast DNS / edge.",
                    },
                },
            ],
            target="1.1.1.1",
        )
        await state.ingest_live(
            [
                {
                    "hop": 1,
                    "ip": "10.1.3.17",
                    "hostname": None,
                    "rtts": [1.1],
                    "timed_out": False,
                },
                {
                    "hop": 2,
                    "ip": "8.8.8.8",
                    "hostname": "dns.google",
                    "rtts": [2.4],
                    "timed_out": False,
                    "lookup": {"asn": "AS15169", "provider": "Google", "city": "Anycast"},
                },
            ],
            target="8.8.8.8",
        )
        snap = await state.snapshot()
        self.assertEqual(snap["target"], "1.1.1.1")
        self.assertEqual([hop["ip"] for hop in snap["hops"]], ["10.1.3.17", "1.1.1.1"])
        self.assertEqual(snap["probe_count"], 1)
        ips = {node.get("ip") for node in snap["graph"]["nodes"]}
        self.assertIn("1.1.1.1", ips)
        self.assertIn("8.8.8.8", ips)
        google = next(node for node in snap["graph"]["nodes"] if node.get("ip") == "8.8.8.8")
        self.assertEqual(google["label"], "dns.google")
        self.assertIn("as15169", google["search"])
        cloudflare = next(node for node in snap["graph"]["nodes"] if node.get("ip") == "1.1.1.1")
        self.assertIn("anycast", cloudflare["search"])

    def test_lan_discovery_returns_this_host(self) -> None:
        ip = local_ipv4()
        self.assertTrue(ip)
        gw = default_gateway()
        # Gateway may be absent in some netns; host address should exist.
        self.assertNotEqual(ip, "127.0.0.1")


class TracerouteParseTests(unittest.TestCase):
    def test_parse_named_and_numeric_and_stars(self) -> None:
        text = """
traceroute to 1.1.1.1 (1.1.1.1), 30 hops max, 60 byte packets
 1  u6-gateway.lan (192.168.1.1)  0.412 ms  0.389 ms
 2  10.4.0.1  1.8 ms
 3  * * *
 4  be2993.ccr42.sea02.atlas.cogentco.com (154.54.30.17)  88.1 ms
        """
        hops = parse_traceroute(text)
        self.assertEqual(len(hops), 4)
        self.assertEqual(hops[0]["ip"], "192.168.1.1")
        self.assertEqual(hops[0]["hostname"], "u6-gateway.lan")
        self.assertAlmostEqual(hops[0]["rtts"][0], 0.412)
        self.assertEqual(hops[1]["ip"], "10.4.0.1")
        self.assertTrue(hops[2]["timed_out"])
        self.assertEqual(hops[3]["ip"], "154.54.30.17")


class GraphAndProviderTests(unittest.TestCase):
    def test_sample_graph_has_lan_and_problem_hop(self) -> None:
        graph = sample_graph()
        ids = {node["id"] for node in graph["nodes"]}
        self.assertIn("lan:you", ids)
        self.assertIn("lan:gw", ids)
        self.assertIn("net:154.54.30.17", ids)
        self.assertIn("net:1.1.1.1", ids)
        self.assertIn("net:8.8.8.8", ids)
        problem = next(node for node in graph["nodes"] if node["id"] == "net:154.54.30.17")
        self.assertTrue(problem["problem"])
        self.assertEqual(problem["asn"], "AS174")
        self.assertIn("cogent", problem["search"])

    def test_gateway_node_id_merges_with_lan(self) -> None:
        self.assertEqual(node_id_for("192.168.1.1", 1), "lan:gw")
        self.assertEqual(node_id_for("154.54.30.17", 6), "net:154.54.30.17")

    def test_live_node_ids_skip_demo_lan_map(self) -> None:
        self.assertEqual(node_id_for("192.168.1.1", 1, demo_lan=False), "net:192.168.1.1")
        self.assertEqual(
            node_id_for("192.168.1.1", 1, gateway_ip="192.168.1.1", demo_lan=False),
            "lan:gw",
        )

    def test_cogent_provider_notes(self) -> None:
        provider = provider_for_ip("154.54.30.17")
        self.assertIsNotNone(provider)
        assert provider is not None
        self.assertEqual(provider.asn, "AS174")
        self.assertIn("peering", provider.notes or "")


class HopLabelTests(unittest.TestCase):
    def test_live_hostnames_keep_useful_labels(self) -> None:
        self.assertEqual(_label("one.one.one.one", "1.1.1.1"), "one.one.one.one")
        self.assertEqual(_label("dns.google", "8.8.8.8"), "dns.google")
        self.assertEqual(_label("be2993.ccr42.sea02.atlas.cogentco.com", "154.54.30.17"), "be2993")
        self.assertEqual(_label(None, "10.1.3.17"), "10.1.3.17")
        self.assertEqual(_label(None, None, hop=1), "hop 1")


class DemoStateTests(unittest.IsolatedAsyncioTestCase):
    async def test_snapshot_flags_cogent_as_problem_router(self) -> None:
        state = PathState()
        snap = await state.snapshot()
        self.assertEqual(snap["target"], DEFAULT_TARGET)
        self.assertGreaterEqual(len(snap["hops"]), 6)
        self.assertTrue(snap["problems"])
        router = snap["problem_router"]
        self.assertIsNotNone(router)
        assert router is not None
        self.assertEqual(router["ip"], "154.54.30.17")
        self.assertEqual(router["provider_detail"]["asn"], "AS174")
        self.assertIn("Cogent", router["provider_detail"]["name"])
        self.assertTrue(snap["heatmap"]["rows"])
        ids = {node["id"] for node in snap["graph"]["nodes"]}
        self.assertIn("lan:you", ids)
        self.assertIn("net:154.54.30.17", ids)
        cogent = next(node for node in snap["graph"]["nodes"] if node["ip"] == "154.54.30.17")
        self.assertIn("cogent", cogent["search"])

    async def test_google_path_has_no_cogent_bottleneck(self) -> None:
        state = PathState()
        await state.set_target("8.8.8.8")
        rng_probe = demo_probe(active_target="8.8.8.8", rng=__import__("random").Random(3), now=2.0)
        await state.ingest_demo(rng_probe)
        snap = await state.snapshot()
        self.assertEqual(snap["target"], "8.8.8.8")
        ips = [hop["ip"] for hop in snap["hops"]]
        self.assertIn("8.8.8.8", ips)
        self.assertNotIn("154.54.30.17", ips)
        self.assertLess(snap["quality"]["end_to_end_ms"] or 999, 40)

    async def test_search_blob_includes_asn_and_city(self) -> None:
        state = PathState()
        snap = await state.snapshot()
        cogent = next(node for node in snap["graph"]["nodes"] if node.get("ip") == "154.54.30.17")
        self.assertIn("as174", cogent["search"])
        self.assertIn("seattle", cogent["search"])


class AppTests(unittest.TestCase):
    def test_routes_exist(self) -> None:
        app = create_app(PathState())
        paths = {getattr(route, "path", None) for route in app.routes}
        self.assertIn("/", paths)
        self.assertIn("/api/snapshot", paths)
        self.assertIn("/api/trace", paths)
        self.assertIn("/api/events", paths)

    def test_dashboard_contains_graph_controls(self) -> None:
        from path_radar.web import DASHBOARD_HTML

        for needle in (
            "Reheat",
            "Freeze",
            "Search nodes",
            "Hop chain",
            "Problem router",
            "Latency over time",
            "Country",
            "fittedWan",
        ):
            self.assertIn(needle, DASHBOARD_HTML)

    def test_pick_available_port_skips_busy(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            occupied = sock.getsockname()[1]
            chosen = pick_available_port("127.0.0.1", occupied, max_tries=4)
        self.assertNotEqual(chosen, occupied)
        self.assertGreaterEqual(chosen, occupied + 1)


if __name__ == "__main__":
    unittest.main()
