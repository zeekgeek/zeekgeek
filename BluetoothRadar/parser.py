"""Conservative BLE advertisement parsing.

Advertisement bytes are unauthenticated and may be malformed or spoofed.  The
labels returned here describe byte patterns; they are not ownership claims.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


COMPANIES: dict[int, str] = {
    0x0006: "Microsoft",
    0x004C: "Apple",
    0x0075: "Samsung",
    0x00E0: "Google",
    0x0157: "Xiaomi",
}

ECOSYSTEMS: dict[int, str] = {
    0x004C: "Apple ecosystem",
    0x0075: "Samsung ecosystem",
    0x00E0: "Google ecosystem",
    0x0157: "Xiaomi ecosystem",
}

APPLE_TYPES: dict[int, str] = {
    0x02: "iBeacon",
    0x05: "AirDrop-like continuity frame",
    0x07: "AirPods-like proximity frame",
    0x09: "AirPlay target frame",
    0x0C: "Handoff-like continuity frame",
    0x10: "Nearby action frame",
    0x12: "Nearby info frame",
}


@dataclass(frozen=True)
class ManufacturerRecord:
    company_id: int
    company: str
    payload_hex: str
    frame_type: str | None = None
    ecosystem: str | None = None
    observations: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "company_id": f"0x{self.company_id:04X}",
            "company": self.company,
            "payload_hex": self.payload_hex,
            "frame_type": self.frame_type,
            "ecosystem": self.ecosystem,
            "observations": list(self.observations),
        }


def _bytes(value: bytes | bytearray | memoryview | str) -> bytes:
    if isinstance(value, str):
        cleaned = value.replace(":", "").replace(" ", "")
        return bytes.fromhex(cleaned)
    return bytes(value)


def parse_manufacturer_record(
    company_id: int, payload: bytes | bytearray | memoryview | str
) -> ManufacturerRecord:
    """Parse one Bleak manufacturer-data entry without over-attributing it."""
    raw = _bytes(payload)
    company = COMPANIES.get(company_id, f"Unknown (0x{company_id:04X})")
    frame_type: str | None = None
    notes: list[str] = []

    if company_id == 0x004C and raw:
        frame_type = APPLE_TYPES.get(raw[0], f"Apple frame 0x{raw[0]:02X}")
        if raw[0] == 0x02 and len(raw) >= 23:
            notes.append("iBeacon-length payload observed")
    elif company_id == 0x0075 and raw:
        frame_type = f"Samsung frame 0x{raw[0]:02X}"
    elif company_id == 0x00E0 and raw:
        frame_type = f"Google frame 0x{raw[0]:02X}"
    elif company_id == 0x0157 and raw:
        frame_type = f"Xiaomi frame 0x{raw[0]:02X}"

    if len(raw) < 2:
        notes.append("short payload")

    return ManufacturerRecord(
        company_id=company_id,
        company=company,
        payload_hex=raw.hex(),
        frame_type=frame_type,
        ecosystem=ECOSYSTEMS.get(company_id),
        observations=tuple(notes),
    )


def parse_manufacturer_data(
    data: Mapping[int, bytes | bytearray | memoryview | str],
) -> list[ManufacturerRecord]:
    return [
        parse_manufacturer_record(company_id, payload)
        for company_id, payload in sorted(data.items())
    ]


def ecosystem_keys(records: list[ManufacturerRecord]) -> set[str]:
    return {record.ecosystem for record in records if record.ecosystem}

