from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from matplotlib import pyplot as plt
from matplotlib.backend_bases import MouseEvent, PickEvent


PROJECT = Path(__file__).resolve().parents[1] / "BluetoothRadar"
sys.path.insert(0, str(PROJECT))

from analysis import analyze_graph  # noqa: E402
from graph import (  # noqa: E402
    _first_pick_index,
    build_relationship_graph,
    show_interactive_graph,
)
from parser import parse_manufacturer_record  # noqa: E402
from scanner import DiscoveredDevice  # noqa: E402
from web import create_app  # noqa: E402
from fastapi.testclient import TestClient


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
    def test_first_node_pick_is_not_treated_as_empty(self) -> None:
        self.assertEqual(_first_pick_index(np.array([0])), 0)
        self.assertIsNone(_first_pick_index(np.array([], dtype=int)))

    def test_clicking_first_node_displays_its_annotation(self) -> None:
        graph = build_relationship_graph(
            [DiscoveredDevice("hub", "Living Room Hub", -40, None)]
        )
        annotation_text: list[str] = []

        def click_first_node() -> None:
            figure = plt.gcf()
            canvas = figure.canvas
            node_artist = figure.axes[0].collections[0]
            mouse_event = MouseEvent("button_press_event", canvas, 0, 0)
            event = PickEvent(
                "pick_event",
                canvas,
                mouse_event,
                node_artist,
                ind=np.array([0]),
            )
            canvas.callbacks.process("pick_event", event)
            annotation = figure.axes[0].texts[-1]
            self.assertTrue(annotation.get_visible())
            annotation_text.append(annotation.get_text())

        with patch("graph.plt.show", side_effect=click_first_node):
            show_interactive_graph(graph)
        plt.close("all")

        self.assertIn("Living Room Hub", annotation_text[0])

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


class BrowserDashboardTests(unittest.TestCase):
    def test_dashboard_streams_fresh_demo_snapshots(self) -> None:
        with TestClient(create_app(demo=True)) as client:
            page = client.get("/")
            self.assertEqual(page.status_code, 200)
            self.assertIn("BLUETOOTH/RADAR", page.text)
            self.assertIn("deviceRows", page.text)
            self.assertIn("radar3d", page.text)
            self.assertIn("3D PROXIMITY RADAR", page.text)
            self.assertIn("Living Room Hub", page.text)
            self.assertNotIn("__INITIAL_SNAPSHOT__", page.text)

            first = client.get("/api/snapshot").json()
            time.sleep(0.9)
            second = client.get("/api/snapshot").json()

        self.assertEqual(first["source"], "SIMULATED LIVE")
        self.assertEqual(len(first["devices"]), 4)
        self.assertGreater(second["sequence"], first["sequence"])
        self.assertNotEqual(
            [item["rssi"] for item in first["devices"]],
            [item["rssi"] for item in second["devices"]],
        )

    def test_live_mode_falls_back_when_scanner_fails(self) -> None:
        with patch(
            "web._live_stream",
            side_effect=RuntimeError("No BLE advertisements observed."),
        ):
            with TestClient(
                create_app(demo=False, auto_demo_fallback=True)
            ) as client:
                time.sleep(0.3)
                snapshot = client.get("/api/snapshot").json()

        self.assertEqual(snapshot["source"], "SIMULATED LIVE (fallback)")
        self.assertGreaterEqual(len(snapshot["devices"]), 4)
        self.assertIn("No BLE advertisements observed.", snapshot["error"])


if __name__ == "__main__":
    unittest.main()

