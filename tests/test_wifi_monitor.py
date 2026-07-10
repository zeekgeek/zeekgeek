import asyncio
import unittest

from wifi_radar.monitor import MonitorModeController, parse_iw_dev_interfaces


class _Runner:
    def __init__(self, responses: dict[tuple[str, ...], str], failures: set[tuple[str, ...]] | None = None) -> None:
        self.responses = responses
        self.failures = failures or set()
        self.calls: list[tuple[str, ...]] = []

    async def __call__(self, command: list[str]) -> str:
        key = tuple(command)
        self.calls.append(key)
        if key in self.failures:
            raise RuntimeError("simulated failure")
        return self.responses.get(key, "")


class MonitorModeTests(unittest.TestCase):
    def test_parse_iw_dev_interfaces(self) -> None:
        parsed = parse_iw_dev_interfaces(
            """
phy#0
    Interface wlan0
        ifindex 3
        type managed
    Interface wlan0mon
        ifindex 4
        type monitor
"""
        )
        self.assertEqual([(item.name, item.if_type) for item in parsed], [("wlan0", "managed"), ("wlan0mon", "monitor")])

    def test_enable_uses_existing_monitor(self) -> None:
        runner = _Runner(
            responses={
                ("iw", "dev"): """
phy#0
    Interface wlan0
        type managed
    Interface mon0
        type monitor
""",
            }
        )
        controller = MonitorModeController(runner)
        activation = asyncio.run(controller.enable("wlan0"))
        self.assertEqual(activation.monitor_interface, "mon0")
        self.assertFalse(activation.created_virtual_interface)

    def test_enable_creates_virtual_monitor_interface(self) -> None:
        runner = _Runner(
            responses={
                ("iw", "dev"): """
phy#0
    Interface wlan0
        type managed
""",
                ("iw", "dev", "wlan0", "interface", "add", "wlan0mon", "type", "monitor"): "",
                ("ip", "link", "set", "wlan0mon", "up"): "",
                ("ip", "link", "set", "wlan0mon", "down"): "",
                ("iw", "dev", "wlan0mon", "del"): "",
            }
        )
        controller = MonitorModeController(runner)
        activation = asyncio.run(controller.enable("wlan0"))
        self.assertTrue(activation.created_virtual_interface)
        self.assertEqual(activation.monitor_interface, "wlan0mon")
        asyncio.run(controller.restore(activation))
        self.assertIn(("iw", "dev", "wlan0mon", "del"), runner.calls)

    def test_enable_falls_back_to_convert_base_interface(self) -> None:
        runner = _Runner(
            responses={
                ("iw", "dev"): """
phy#0
    Interface wlan0
        type managed
""",
                ("ip", "link", "set", "wlan0", "down"): "",
                ("iw", "dev", "wlan0", "set", "type", "monitor"): "",
                ("ip", "link", "set", "wlan0", "up"): "",
                ("iw", "dev", "wlan0", "set", "type", "managed"): "",
            },
            failures={("iw", "dev", "wlan0", "interface", "add", "wlan0mon", "type", "monitor")},
        )
        controller = MonitorModeController(runner)
        activation = asyncio.run(controller.enable("wlan0"))
        self.assertFalse(activation.created_virtual_interface)
        self.assertEqual(activation.monitor_interface, "wlan0")
        asyncio.run(controller.restore(activation))
        self.assertIn(("iw", "dev", "wlan0", "set", "type", "managed"), runner.calls)


if __name__ == "__main__":
    unittest.main()
