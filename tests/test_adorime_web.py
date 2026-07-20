import asyncio
import unittest
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from adorime_control.state import Observation, RadarState
from adorime_control.web import create_app


class AdorimeWebTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = RadarState(stale_after=3.0)
        asyncio.run(
            self.state.observe(
                Observation(
                    address="A1:42:19:77:33:10",
                    name="AdoRime Thrust Pod",
                    address_type="random",
                    rssi=-61,
                    observed_at=datetime.now(UTC),
                )
            )
        )
        app = create_app(self.state)
        self.client = TestClient(app)

    def test_status_endpoint_returns_control_block(self) -> None:
        response = self.client.get("/api/status")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("control", payload)
        self.assertIn("devices", payload)

    def test_manual_control_route(self) -> None:
        target = self.client.post("/api/control/target", json={"address": "A1:42:19:77:33:10"})
        self.assertEqual(target.status_code, 200)

        response = self.client.post("/api/control/manual", json={"thrust": 68, "pattern": "pulse"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["event"]["type"], "control-command")
        self.assertEqual(payload["event"]["control"]["thrust"], 68)
        self.assertEqual(payload["event"]["control"]["pattern"], "pulse")

    def test_ai_route_requires_target(self) -> None:
        response = self.client.post(
            "/api/control/ai",
            json={"enabled": True, "aggressiveness": 0.75, "min_thrust": 25, "max_thrust": 90},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("No control target selected", response.text)


if __name__ == "__main__":
    unittest.main()
