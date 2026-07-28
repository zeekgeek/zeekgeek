from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1] / "BluetoothRadar"
sys.path.insert(0, str(PROJECT))

from analysis import analyze_graph  # noqa: E402
from graph import build_relationship_graph  # noqa: E402
from parser import parse_manufacturer_record  # noqa: E402
from scanner import DiscoveredDevice  # noqa: E402


class ParserTests(unittest.TestCase):
    def test_known_company_and_frame_are_described(self) -> None:
        record = parse_manufacturer_record(0x004C, b"\x02" + bytes(22))
        self.assertEqual(record.company, "Apple")
        self.assertEqual(record.frame_type, "iBeacon")
        self.assertIn("iBeacon-length payload observed", record.observations)

    def test_unknown_company_is_preserved(self) -> None:
        record = parse_manufacturer_record(0xBEEF, "0102")
        self.assertEqual(record.company_id, 0xBEEF)
        self.assertEqual(record.payload_hex, "0102")


class GraphTests(unittest.TestCase):
    def test_shared_service_creates_evidenced_edge(self) -> None:
        service = "0000180f-0000-1000-8000-00805f9b34fb"
        devices = [
            DiscoveredDevice("one", "Phone", -50, None, {service}),
            DiscoveredDevice(
                "two",
                None,
                -60,
                None,
                {service},
                identity_limited=True,
            ),
        ]
        graph = build_relationship_graph(devices)
        self.assertTrue(graph.nodes["two"]["hidden"])
        self.assertTrue(graph.has_edge("one", "two"))
        self.assertIn(
            "1 shared service(s)", graph.edges["one", "two"]["evidence"]
        )

    def test_graph_analysis_finds_hub(self) -> None:
        devices = [
            DiscoveredDevice("hub", "Hub", -40, None),
            DiscoveredDevice("left", "Left", -50, None),
            DiscoveredDevice("right", "Right", -55, None),
        ]
        graph = build_relationship_graph(devices)
        graph.remove_edge("left", "right")
        report = analyze_graph(graph)
        self.assertEqual(report.hubs[0][0], "hub")
        self.assertTrue(report.suggestions)


if __name__ == "__main__":
    unittest.main()

