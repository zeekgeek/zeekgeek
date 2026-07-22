import socket
import unittest

from adorime_control.__main__ import build_parser, pick_available_port, resolve_scan_mode_flags


class AdorimeMainTests(unittest.TestCase):
    def test_parser_defaults_to_live_only(self) -> None:
        args = build_parser().parse_args([])
        force_demo, allow_demo_fallback = resolve_scan_mode_flags(args)
        self.assertFalse(args.demo)
        self.assertFalse(args.allow_demo_fallback)
        self.assertFalse(force_demo)
        self.assertFalse(allow_demo_fallback)

    def test_parser_accepts_demo_fallback_flag(self) -> None:
        args = build_parser().parse_args(["--allow-demo-fallback"])
        _, allow_demo_fallback = resolve_scan_mode_flags(args)
        self.assertTrue(allow_demo_fallback)

    def test_pick_available_port_returns_preferred_when_free(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            free_port = sock.getsockname()[1]
        chosen = pick_available_port("127.0.0.1", free_port, max_tries=2)
        self.assertEqual(chosen, free_port)

    def test_pick_available_port_skips_busy_port(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            occupied_port = sock.getsockname()[1]
            chosen = pick_available_port("127.0.0.1", occupied_port, max_tries=3)
        self.assertNotEqual(chosen, occupied_port)
        self.assertGreaterEqual(chosen, occupied_port + 1)


if __name__ == "__main__":
    unittest.main()
