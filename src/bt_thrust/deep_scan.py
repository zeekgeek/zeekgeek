"""GATT service and characteristic discovery for BLE devices."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

LOGGER = logging.getLogger(__name__)


async def discover_gatt(
    address: str,
    *,
    ble_device: Any = None,
    timeout: float = 15.0,
) -> dict[str, Any]:
    from bleak import BleakClient

    result: dict[str, Any] = {
        "address": address,
        "connected": False,
        "services": [],
        "error": None,
    }
    client = BleakClient(ble_device if ble_device is not None else address, timeout=timeout)
    try:
        await client.connect()
        if not client.is_connected:
            result["error"] = "connection failed"
            return result
        result["connected"] = True
        services_payload: list[dict[str, Any]] = []
        for service in client.services:
            characteristics: list[dict[str, Any]] = []
            for char in service.characteristics:
                characteristics.append(
                    {
                        "uuid": char.uuid,
                        "properties": list(char.properties),
                        "descriptors": [descriptor.uuid for descriptor in char.descriptors],
                    }
                )
            services_payload.append(
                {
                    "uuid": service.uuid,
                    "description": service.description,
                    "characteristics": characteristics,
                }
            )
        result["services"] = services_payload
    except Exception as exc:
        LOGGER.warning("GATT deep scan failed for %s: %s", address, exc)
        result["error"] = str(exc)
    finally:
        if client.is_connected:
            await client.disconnect()
    return result


async def run_deep_scan_worker(state: Any) -> None:
    """Background worker for GATT and classic discovery during deep scan."""
    from .classic_scanner import scan_classic_devices

    scanned_gatt: set[str] = set()
    while True:
        try:
            snapshot = await state.snapshot()
            scanner = snapshot.get("scanner", {})
            if scanner.get("deep_scan_active"):
                for device in await scan_classic_devices(duration_seconds=4.0):
                    await state.observe_classic_device(
                        address=device.address,
                        name=device.name,
                        device_class=device.device_class,
                        rssi=device.rssi,
                    )
                for toy in snapshot.get("toys", []):
                    address = toy.get("address")
                    if not address or not toy.get("present"):
                        continue
                    if not toy.get("controllable") and not toy.get("galaku_service"):
                        continue
                    if address in scanned_gatt and toy.get("gatt_services"):
                        continue
                    ble_device = await state.get_ble_device(address)
                    result = await discover_gatt(address, ble_device=ble_device)
                    await state.store_gatt_result(address, result)
                    scanned_gatt.add(address)
            else:
                scanned_gatt.clear()
            await asyncio.sleep(6.0)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOGGER.warning("Deep scan worker error: %s", exc)
            await asyncio.sleep(6.0)
