"""Galaku BLE protocol used by AdoRime (and sister brands).

AdoRime iOS app (v1.0.31, seller Hong Kong BSheng / ShenZhen WS Electronic)
connects toys the same way as Galaku/Kisstoy apps from the same OEM family:

1. Scan BLE advertisements (no OS-level pairing / PIN).
2. Match short local names (``QD48``, ``BGSF``, ``SN80``, …) or the Galaku
   service UUID ``00001000-0000-1000-8000-00805f9b34fb``.
3. Connect as a GATT client and write encrypted command frames to TX
   characteristic ``00001001-0000-1000-8000-00805f9b34fb``.

Command framing and encryption match the reverse-engineered Galaku
implementation published in the Buttplug/Intiface project
(``galaku.rs`` / ``galaku.yml``), which already maps many AdoRime SKUs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Galaku toys almost always advertise opaque short codes (3-5 alnum chars),
# never the storefront brand "Adorime". Treat those as probable scan hits.
_GALAKU_CODE_RE = re.compile(r"^[A-Z0-9]{3,5}$")
_COMMON_NON_TOY_NAMES = frozenset(
    {
        "IPHONE",
        "IPAD",
        "MACBOOK",
        "AIRPODS",
        "GALAXY",
        "PIXEL",
        "WATCH",
        "KEYBOARD",
        "MOUSE",
        "TV",
        "SPEAKER",
        "HEADPHONES",
        "HEADSET",
        "BEACON",
        "LAPTOP",
        "DESKTOP",
        "WINDOWS",
        "LINUX",
        "UBUNTU",
        "SAMSUNG",
        "HUAWEI",
        "XIAOMI",
        "HONOR",
        "ONEPLUS",
        "GOOGLE",
        "NEST",
        "ECHO",
        "ALEXA",
        "BOSE",
        "SONY",
        "JBL",
        "FITBIT",
        "GARMIN",
        "TILE",
        "AIRTAG",
        "UNKNOWN",
    }
)

GALAKU_SERVICE_UUID = "00001000-0000-1000-8000-00805f9b34fb"
GALAKU_TX_CHARACTERISTIC_UUID = "00001001-0000-1000-8000-00805f9b34fb"
GALAKU_BATTERY_CHARACTERISTIC_UUID = "00001002-0000-1000-8000-00805f9b34fb"

# Magic Motion platform (some AdoRime storefront SKUs rebrand Magic Motion toys).
MAGIC_MOTION_SERVICE_UUID = "78667579-7b48-43db-b8c5-7928a6b0a335"
MAGIC_MOTION_TX_CHARACTERISTIC_UUID = "78667579-a914-49a4-8333-aa3c0cd8fedc"

KEY_TAB: tuple[tuple[int, ...], ...] = (
    (0, 24, 152, 247, 165, 61, 13, 41, 37, 80, 68, 70),
    (0, 69, 110, 106, 111, 120, 32, 83, 45, 49, 46, 55),
    (0, 101, 120, 32, 84, 111, 121, 115, 10, 142, 157, 163),
    (0, 197, 214, 231, 248, 10, 50, 32, 111, 98, 13, 10),
)

# BLE advertised local-name → friendly AdoRime product name.
# Source: buttplug device-config-v5 galaku protocol configurations.
ADORIME_BLE_NAME_MAP: dict[str, str] = {
    "QD48": "Adorime Wearable Egg Vibrator",
    "BGSF": "Adorime Male Masturbator",
    "BGQS": "Adorime Penis Vibrator",
    "AX05": "Adorime Anal Vibrator",
    "DT01": "Adorime Chastity Cage",
    "BGZY": "Adorime Penis Helmet Vibrator",
    "A531": "Adorime Pink Touch",
    "SN80": "Adorime G-spot Rabbit Dildo Vibrator",
    "BGCD": "Adorime Backy",
    "YXSJ": "Adorime Cock Ring",
}

# Full Galaku BLE name set from device-config (sister-brand toys share the stack).
GALAKU_BLE_NAMES: frozenset[str] = frozenset(
    {
        "GX85",
        "GX07",
        "GX17",
        "GX21",
        "GX22",
        "GX16",
        "GX29",
        "GX23",
        "GX25",
        "GX26",
        "GK03",
        "GX39",
        "G321",
        "G304",
        "G336",
        "G331",
        "G326",
        "G335",
        "G341",
        "G355",
        "G349",
        "G407",
        "G204",
        "G171",
        "G12D",
        "G123",
        "G23A",
        "A073",
        "GLMT",
        "G901",
        "G912",
        "G20B",
        "K112",
        "G202",
        "K118",
        "K107",
        "G203",
        "TXHL",
        "TXMM",
        "TXKL",
        "K108",
        "K109",
        "KWL2",
        "TFHL",
        "TFMM",
        "TFKL",
        "K120",
        "K12A",
        "K12C",
        "LL18",
        "CYX2",
        "RC31",
        "MD19",
        "QD48",
        "BGSF",
        "BGQS",
        "AX05",
        "DT01",
        "BGZY",
        "A531",
        "YXSJ",
        "G317",
        "G312",
        "G302",
        "G320",
        "G314",
        "G228",
        "G315",
        "G307",
        "K311",
        "G339",
        "G354",
        "G12B",
        "G29C",
        "G29D",
        "GKML",
        "G348",
        "G913",
        "G213",
        "TFF1",
        "G310",
        "K113",
        "D358",
        "G322",
        "D402",
        "G40A",
        "G403",
        "G43A",
        "K12B",
        "QCVW",
        "QCSW",
        "QCPW",
        "SN80",
        "BGCD",
        "AK71",
        "TFG1",
        "GK27",
        "GX27",
        "GK25",
        "AC695X_1(BLE)",
        "GX33",
        "WSXK",
    }
)

KNOWN_SERVICE_PROTOCOLS: dict[str, str] = {
    GALAKU_SERVICE_UUID.lower(): "galaku",
    MAGIC_MOTION_SERVICE_UUID.lower(): "magic-motion",
}


@dataclass(frozen=True)
class ProtocolProfile:
    protocol: str
    service_uuid: str
    tx_characteristic_uuid: str
    battery_characteristic_uuid: str | None = None


PROTOCOL_PROFILES: dict[str, ProtocolProfile] = {
    "galaku": ProtocolProfile(
        protocol="galaku",
        service_uuid=GALAKU_SERVICE_UUID,
        tx_characteristic_uuid=GALAKU_TX_CHARACTERISTIC_UUID,
        battery_characteristic_uuid=GALAKU_BATTERY_CHARACTERISTIC_UUID,
    ),
    "magic-motion": ProtocolProfile(
        protocol="magic-motion",
        service_uuid=MAGIC_MOTION_SERVICE_UUID,
        tx_characteristic_uuid=MAGIC_MOTION_TX_CHARACTERISTIC_UUID,
    ),
}


def clamp_percent(value: int) -> int:
    return max(0, min(int(value), 100))


def normalize_ble_name(name: str | None) -> str:
    return (name or "").strip()


def _name_key(name: str | None) -> str:
    return normalize_ble_name(name).upper()


def looks_like_galaku_code(name: str | None) -> bool:
    """Heuristic: short opaque alphanumeric BLE names used by Galaku OEM toys."""
    code = _name_key(name)
    if not code or code in _COMMON_NON_TOY_NAMES:
        return False
    if not _GALAKU_CODE_RE.fullmatch(code):
        return False
    has_letter = any(ch.isalpha() for ch in code)
    has_digit = any(ch.isdigit() for ch in code)
    # Prefer letter+digit mixes (QD48); also allow 4-letter opaque codes (BGSF).
    return has_letter and (has_digit or len(code) == 4)


def match_tier(name: str | None, service_uuids: list[str] | None = None) -> str:
    """Classify advertisement confidence: known | probable | none."""
    for uuid in service_uuids or []:
        if KNOWN_SERVICE_PROTOCOLS.get(str(uuid).strip().lower()):
            return "known"
    code = _name_key(name)
    if not code:
        return "none"
    if code in {item.upper() for item in ADORIME_BLE_NAME_MAP}:
        return "known"
    if code in {item.upper() for item in GALAKU_BLE_NAMES}:
        return "known"
    if any(token in code for token in ("ADORIME", "ADO RIME", "GALAKU", "KISSTOY")):
        return "known"
    if looks_like_galaku_code(code):
        return "probable"
    return "none"


def match_reason(name: str | None, service_uuids: list[str] | None = None) -> str:
    for uuid in service_uuids or []:
        protocol = KNOWN_SERVICE_PROTOCOLS.get(str(uuid).strip().lower())
        if protocol:
            return f"{protocol}-service"
    code = _name_key(name)
    if not code:
        return "none"
    if code in {item.upper() for item in ADORIME_BLE_NAME_MAP}:
        return "adorime-code"
    if code in {item.upper() for item in GALAKU_BLE_NAMES}:
        return "galaku-code"
    if any(token in code for token in ("ADORIME", "ADO RIME", "GALAKU", "KISSTOY")):
        return "brand-name"
    if looks_like_galaku_code(code):
        return "galaku-heuristic"
    return "none"


def friendly_device_name(local_name: str | None) -> str | None:
    raw = normalize_ble_name(local_name)
    if not raw:
        return None
    mapped = ADORIME_BLE_NAME_MAP.get(raw) or ADORIME_BLE_NAME_MAP.get(raw.upper())
    if mapped:
        return mapped
    lower = raw.lower()
    if "adorime" in lower or "ado rime" in lower:
        return raw
    if looks_like_galaku_code(raw):
        return f"Likely Galaku toy ({raw.upper()})"
    return None


def is_adorime_candidate(name: str | None, service_uuids: list[str] | None = None) -> bool:
    """True for known or high-confidence probable AdoRime/Galaku advertisements."""
    return match_tier(name, service_uuids) in {"known", "probable"}


def classify_protocol(service_uuids: list[str] | None, name: str | None = None) -> str | None:
    for uuid in service_uuids or []:
        protocol = KNOWN_SERVICE_PROTOCOLS.get(str(uuid).strip().lower())
        if protocol:
            return protocol
    raw = normalize_ble_name(name)
    if not raw:
        return None
    code = raw.upper()
    if code in {item.upper() for item in GALAKU_BLE_NAMES}:
        return "galaku"
    if code in {item.upper() for item in ADORIME_BLE_NAME_MAP}:
        return "galaku"
    lower = raw.lower()
    if "adorime" in lower or "ado rime" in lower or "galaku" in lower or "kisstoy" in lower:
        return "galaku"
    if looks_like_galaku_code(raw):
        return "galaku"
    return None


def _get_tab_key(previous: int, index: int) -> int:
    return KEY_TAB[previous & 3][index]


def _encrypt(data: list[int]) -> list[int]:
    encrypted = [data[0]]
    for index in range(1, len(data)):
        key = _get_tab_key(encrypted[index - 1], index)
        encrypted.append((key ^ data[0] ^ data[index]) + key)
    return encrypted


def send_bytes(payload: list[int]) -> bytes:
    """Wrap + checksum + encrypt a Galaku command payload into wire bytes."""
    framed = [35, *payload]
    framed.append(sum(framed) & 0xFF)
    return bytes(value & 0xFF for value in _encrypt(framed))


def encode_galaku_single(speed_percent: int) -> bytes:
    speed = clamp_percent(speed_percent)
    return send_bytes([90, 0, 0, 1, 49, speed, 0, 0, 0, 0])


def encode_galaku_dual(speed1_percent: int, speed2_percent: int) -> bytes:
    speed1 = clamp_percent(speed1_percent)
    speed2 = clamp_percent(speed2_percent)
    return send_bytes([90, 0, 0, 1, 64, 3, speed1, speed2, 0, 0])


def encode_magic_motion_single(vibrate_percent: int) -> bytes:
    v1 = clamp_percent(vibrate_percent)
    return bytes([0x04, 0x08, v1, 0x64, 0x00])


def encode_command(protocol: str, thrust_percent: int, *, dual: bool = False) -> bytes | None:
    level = clamp_percent(thrust_percent)
    if protocol == "galaku":
        if dual:
            return encode_galaku_dual(level, level)
        return encode_galaku_single(level)
    if protocol == "magic-motion":
        return encode_magic_motion_single(level)
    return None


def profile_for_protocol(protocol: str | None) -> ProtocolProfile | None:
    if not protocol:
        return None
    return PROTOCOL_PROFILES.get(protocol)
