import os
import socket
import unittest
from unittest.mock import patch

from bt_thrust.__main__ import default_dashboard_host, pick_available_port


class MainTests(unittest.TestCase):
    def test_default_dashboard_host_uses_all_interfaces_in_cursor(self) -> None:
        with patch.dict(os.environ, {"CURSOR_AGENT": "1"}, clear=False):
            self.assertEqual(default_dashboard_host(), "0.0.0.0")

    def test_default_dashboard_host_uses_localhost_outside_cursor(self) -> None:
        env = os.environ.copy()
        env.pop("CURSOR_AGENT", None)
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(default_dashboard_host(), "127.0.0.1")

    def test_pick_available_port_returns_preferred_when_free(self) -> None:
        chosen = pick_available_port("127.0.0.1", 39877, max_tries=2)
        self.assertEqual(chosen, 39877)

    def test_pick_available_port_skips_busy_port(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            occupied_port = sock.getsockname()[1]
            chosen = pick_available_port("127.0.0.1", occupied_port, max_tries=4)
        self.assertNotEqual(chosen, occupied_port)
        self.assertGreaterEqual(chosen, occupied_port + 1)


if __name__ == "__main__":
    unittest.main()
