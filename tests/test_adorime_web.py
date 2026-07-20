import asyncio
import json
import unittest
from datetime import UTC, datetime

from fastapi import HTTPException
from fastapi.routing import APIRoute

from adorime_control.state import Observation, RadarState
from adorime_control.web import AiControlRequest, ManualCommandRequest, TargetRequest, create_app


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
        self.app = create_app(self.state)

    def _route(self, path: str, method: str):
        for route in self.app.routes:
            if isinstance(route, APIRoute) and route.path == path and method in (route.methods or set()):
                return route.endpoint
        raise AssertionError(f"Route {method} {path} not found")

    def test_status_endpoint_returns_control_block(self) -> None:
        endpoint = self._route("/api/status", "GET")
        payload = asyncio.run(endpoint())
        self.assertIn("control", payload)
        self.assertIn("devices", payload)

    def test_manual_control_route(self) -> None:
        target_endpoint = self._route("/api/control/target", "POST")
        target_response = asyncio.run(target_endpoint(TargetRequest(address="A1:42:19:77:33:10")))
        self.assertEqual(target_response.status_code, 200)

        manual_endpoint = self._route("/api/control/manual", "POST")
        response = asyncio.run(manual_endpoint(ManualCommandRequest(thrust=68, pattern="pulse")))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["event"]["type"], "control-command")
        self.assertEqual(payload["event"]["control"]["thrust"], 68)
        self.assertEqual(payload["event"]["control"]["pattern"], "pulse")

    def test_ai_route_requires_target(self) -> None:
        endpoint = self._route("/api/control/ai", "POST")
        with self.assertRaises(HTTPException) as context:
            asyncio.run(
                endpoint(
                    AiControlRequest(enabled=True, aggressiveness=0.75, min_thrust=25, max_thrust=90)
                )
            )
        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("No control target selected", str(context.exception.detail))


if __name__ == "__main__":
    unittest.main()
