"""Live BLE GATT connection manager for AdoRime/Galaku toys."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .protocol import (
    ProtocolProfile,
    classify_protocol,
    encode_command,
    profile_for_protocol,
)

LOGGER = logging.getLogger(__name__)


@dataclass
class ConnectedDevice:
    address: str
    name: str | None
    protocol: str
    profile: ProtocolProfile
    client: Any
    dual_motor: bool = False
    services: list[str] = field(default_factory=list)


class DeviceConnectionManager:
    """Owns Bleak GATT clients for selected toys (mirrors AdoRime iOS flow)."""

    def __init__(self) -> None:
        self._connected: dict[str, ConnectedDevice] = {}

    @property
    def connected_addresses(self) -> list[str]:
        return list(self._connected.keys())

    def is_connected(self, address: str) -> bool:
        entry = self._connected.get(address)
        if entry is None:
            return False
        try:
            return bool(entry.client.is_connected)
        except Exception:
            return False

    def connection_snapshot(self, address: str | None) -> dict[str, Any]:
        if not address:
            return {"connected": False, "protocol": None, "services": []}
        entry = self._connected.get(address)
        connected = self.is_connected(address)
        if entry is None:
            return {"connected": False, "protocol": None, "services": []}
        return {
            "connected": connected,
            "protocol": entry.protocol,
            "services": list(entry.services),
            "dual_motor": entry.dual_motor,
            "tx_characteristic": entry.profile.tx_characteristic_uuid,
        }

    async def connect(
        self,
        *,
        address: str,
        name: str | None,
        service_uuids: list[str] | None = None,
        timeout: float = 20.0,
    ) -> dict[str, Any]:
        if self.is_connected(address):
            return self.connection_snapshot(address)

        try:
            from bleak import BleakClient
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Install the 'bleak' package for live Bluetooth connections.") from exc

        protocol = classify_protocol(service_uuids, name) or "galaku"
        profile = profile_for_protocol(protocol)
        if profile is None:
            raise ValueError(f"No GATT profile available for protocol '{protocol}'")

        # AdoRime iOS does not use OS pairing/PIN — plain GATT connect.
        client = BleakClient(address, timeout=timeout, pair=False)
        await client.connect()
        try:
            discovered_services = [service.uuid.lower() for service in client.services]
            if profile.service_uuid.lower() not in discovered_services:
                # Fall back: if Galaku service missing, try Magic Motion profile.
                alt = profile_for_protocol("magic-motion")
                if alt and alt.service_uuid.lower() in discovered_services:
                    protocol = "magic-motion"
                    profile = alt
                else:
                    raise RuntimeError(
                        f"Connected to {address} but expected service {profile.service_uuid} "
                        f"was not found. Discovered: {', '.join(discovered_services) or 'none'}"
                    )

            tx = client.services.get_characteristic(profile.tx_characteristic_uuid)
            if tx is None:
                raise RuntimeError(
                    f"TX characteristic {profile.tx_characteristic_uuid} not found on {address}"
                )

            dual_motor = sum(1 for char in client.services.characteristics.values() if "write" in char.properties) > 1
            entry = ConnectedDevice(
                address=address,
                name=name,
                protocol=protocol,
                profile=profile,
                client=client,
                dual_motor=dual_motor,
                services=discovered_services,
            )
            self._connected[address] = entry
            LOGGER.info("Connected to %s (%s) via %s", name or address, address, protocol)
            return self.connection_snapshot(address)
        except Exception:
            with _suppress():
                await client.disconnect()
            raise

    async def disconnect(self, address: str) -> dict[str, Any]:
        entry = self._connected.pop(address, None)
        if entry is None:
            return {"connected": False, "protocol": None, "services": []}
        with _suppress():
            await entry.client.disconnect()
        LOGGER.info("Disconnected from %s", address)
        return {"connected": False, "protocol": entry.protocol, "services": []}

    async def disconnect_all(self) -> None:
        for address in list(self._connected):
            await self.disconnect(address)

    async def send_thrust(self, address: str, thrust_percent: int, pattern: str = "steady") -> dict[str, Any]:
        entry = self._connected.get(address)
        if entry is None or not self.is_connected(address):
            raise RuntimeError(f"Device {address} is not connected over GATT")

        payload = encode_command(entry.protocol, thrust_percent, dual=entry.dual_motor and pattern != "idle")
        if payload is None:
            raise RuntimeError(f"Unable to encode command for protocol {entry.protocol}")

        # Write without response when supported — matches common toy TX behaviour.
        await entry.client.write_gatt_char(entry.profile.tx_characteristic_uuid, payload, response=False)
        return {
            "address": address,
            "protocol": entry.protocol,
            "thrust": int(thrust_percent),
            "pattern": pattern,
            "bytes_hex": payload.hex(),
            "tx_characteristic": entry.profile.tx_characteristic_uuid,
        }


class _suppress:
    def __enter__(self) -> "_suppress":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:  # type: ignore[no-untyped-def]
        return True
