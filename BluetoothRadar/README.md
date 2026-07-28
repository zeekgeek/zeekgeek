# BluetoothRadar

BluetoothRadar observes nearby BLE advertisements, shows a color-coded live
table, parses common manufacturer identifiers, and builds an interactive graph
of **possible** ecosystem relationships.

## Project tree

```text
BluetoothRadar/
├── main.py
├── scanner.py
├── parser.py
├── graph.py
├── analysis.py
├── web.py
├── requirements.txt
└── README.md
```

## Accuracy and platform boundaries

- Modern macOS BLE scanning is provided by Apple's CoreBluetooth framework.
  This project reaches it through Bleak. PyBluez 0.23 does not provide a
  production-capable CoreBluetooth BLE scanner.
- macOS returns an opaque peripheral UUID rather than a Bluetooth MAC address.
- User-selected passive scanning is available with Linux/BlueZ. CoreBluetooth
  does not expose raw passive-versus-active scan control, so BluetoothRadar
  rejects `--scan-mode passive` on macOS instead of silently misrepresenting it.
- A missing/local generic name is shown as `🕵️ Hidden`. It means
  **identity-limited advertisement**, not proof that a person intentionally hid
  a device.
- Advertisements are unauthenticated and spoofable. A company identifier is a
  payload observation, not proof of device ownership or origin.
- BLE advertisements do not reveal IP addresses, open TCP/UDP sockets, pairing
  state, or actual device-to-device links. BluetoothRadar does not invent those
  fields.

Graph edges are explicitly hypotheses. They score shared advertised services,
shared manufacturer ecosystems, and whether both signals are strong at the
observer. RSSI is noisy and two devices near the observer are not necessarily
near or connected to each other.

## Install

Python 3.11 or newer is recommended.

```bash
cd BluetoothRadar
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
```

On macOS, grant Bluetooth access to Terminal (or the application that launches
Python) in **System Settings → Privacy & Security → Bluetooth**.

On Linux, ensure BlueZ and `bluetoothd` are installed, the adapter is powered,
and the user has permission to scan. PyBluez2, the current-build-compatible
PyBluez fork, is installed on Linux for future classic-Bluetooth extensions;
the current cross-platform BLE scanner uses Bleak.

## Run

Hardware-free demo:

```bash
python3 main.py --demo --duration 2
```

Active scan with a clickable graph:

```bash
python3 main.py --scan-mode active --duration 30
```

Linux passive scan:

```bash
python3 main.py --scan-mode passive --adapter hci0 --duration 30
```

Console-only scan, sorted by name, with exports:

```bash
python3 main.py --no-gui --sort name --json observations.json --csv observations.csv
```

Continuously updating browser dashboard (live BLE by default):

```bash
python3 main.py --browser --open-browser
python3 main.py --browser --demo
python3 main.py --browser --demo-fallback
```

Live advertisements stream to the browser over `/api/events` (Server-Sent
Events). The 3D radar and device list update as each packet is observed. On
macOS, grant Bluetooth access to Terminal in **System Settings → Privacy &
Security → Bluetooth**.

The dashboard defaults to <http://127.0.0.1:8766> and selects the next free
port when needed. Its source badge always says `SIMULATED LIVE` or `LIVE BLE`.
The page includes a live **3D proximity radar** (RSSI distance rings, rotating
scan sweep, clickable blips) plus a sortable **device list** fed by the same
scan stream.

The graph opens after scanning. Red nodes are identity-limited advertisements.
Click a node to display its observations and incident edge scores.

## Manufacturer parsing

`parser.py` recognizes registered company identifiers for Apple, Google,
Samsung, Xiaomi, and Microsoft. A few public Apple continuity frame type bytes
receive descriptive labels. Parsers deliberately avoid decoding undocumented
payload bytes into personal identity or tracking claims.

Add a company identifier to `COMPANIES` and a conservative parser branch in
`parse_manufacturer_record`. Keep malformed payload handling non-fatal because
radio input is untrusted.

## Graph intelligence

`analysis.py` reports:

- maximum degree-centrality hub candidates;
- weighted Louvain communities (or greedy modularity fallback);
- nodes found in multiple overlapping 3-clique communities;
- cautious ecosystem-context suggestions backed by each edge's evidence.

These outputs do not establish pairing, communication, control, or ownership.

## Extending with a sniffer

Keep packet capture separate from `BluetoothRadarScanner`: implement an adapter
that emits `DiscoveredDevice` observations, then reuse parsing, graphing, and
analysis. nRF Sniffer captures require dedicated hardware, firmware, channel
hopping, and lawful capture procedures. Never treat encrypted packet contents
as available merely because advertisements are visible.

## How to run ethically (only on your own devices)

Use BluetoothRadar only on devices and premises you own or where every relevant
party has given informed authorization. Follow local interception, privacy, and
computer-misuse laws. Do not use identifiers or signal strength to stalk,
profile, deanonymize, or make safety-critical accusations about people.

Minimize collection: use short scans, keep exports local, encrypt them when
retained, and delete them when no longer needed. Obtain separate authorization
before using packet-sniffer hardware. BluetoothRadar is an observation and
education tool, not evidence that a device is malicious or connected to
another device.

