import socket
import unittest

from bt_radar.__main__ import pick_available_port


class MainTests(unittest.TestCase):
    def test_pick_available_port_returns_preferred_when_free(self) -> None:
        chosen = pick_available_port("127.0.0.1", 39876, max_tries=2)
        self.assertEqual(chosen, 39876)

    def test_pick_available_port_skips_busy_port(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            occupied_port = sock.getsockname()[1]
            chosen = pick_available_port("127.0.0.1", occupied_port, max_tries=4)
        self.assertNotEqual(chosen, occupied_port)
        self.assertGreaterEqual(chosen, occupied_port + 1)


if __name__ == "__main__":
    unittest.main()
