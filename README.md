# zeekgeek Bluetooth Proximity Radar

A local Bluetooth Low Energy proximity radar with:

- live BLE scanning through [Bleak](https://bleak.readthedocs.io/)
- a browser dashboard with detected clients, RSSI movement graph, details, and event log
- browser notifications when devices are discovered, leave range, or return
- classification of public/common versus randomized/private-style addresses
- conservative anomaly findings for repeated reappearance, volatile signal movement, missing names/manufacturer data, and watchlist-like advertised names
- a demo mode that works without Bluetooth hardware

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
python3 -m bt_radar --demo
```

Open <http://127.0.0.1:8765> and click **Enable browser notifications**.

For live Bluetooth scanning:

```bash
python3 -m bt_radar
```

If live scanning is unavailable (for example no `bluetoothd` / BlueZ service),
the app now auto-switches to demo mode and posts a system event in the UI.

Linux hosts usually need:

- a Bluetooth adapter that is powered on
- `bluetoothd` running
- permission to perform BLE scans from the current user/session

## Dashboard behavior

The dashboard separates each observed Bluetooth address into:

- **public/common**: an address that looks like a normal public Bluetooth address
- **rotating/randomized**: an address whose scanner metadata or bit pattern looks like BLE random/private addressing
- **unknown**: malformed or incomplete address data

The movement graph plots RSSI over time. Stronger RSSI usually means the device is nearer, but reflections, body blocking, antenna orientation, transmit power, and walls can all distort distance estimates. Treat movement labels as hints, not measurements.

## Anomaly and sensitive-device notes

This tool does **not** claim that a device belongs to the U.S. government, law enforcement, or any other organization unless your own local evidence supports that conclusion. Bluetooth names, OUIs, and randomized MAC addresses are often incomplete, spoofed, or privacy-protected.

Instead, the radar reports observable conditions:

- randomized/private address patterns
- no friendly name
- repeated disappearance and reappearance
- volatile RSSI suggesting movement or relay/obstruction effects
- missing manufacturer data after repeated sightings
- generic watchlist keywords in the advertised name, such as `beacon`, `sensor`, `camera`, `bodycam`, or `tracker`

Use these findings as prompts for lawful, local investigation only. If you have a legitimate public OUI list or an organization-specific watchlist, add that data as local rules before making attribution decisions.

## Command options

```text
python3 -m bt_radar --host 127.0.0.1 --port 8765 --stale-after 20
```

- `--demo`: simulate devices instead of scanning hardware
- `--host`: dashboard bind address
- `--port`: dashboard port
- `--stale-after`: seconds without sightings before a device is marked as left
- `--no-auto-demo-fallback`: exit instead of auto-switching from live scanner to demo mode
- `--log-level`: `debug`, `info`, `warning`, or `error`

The app also auto-selects the next free port if the requested `--port` is busy.
For example, if `8765` is taken it will try `8766`, `8767`, etc.

## API

- `GET /api/devices`: current snapshot of devices and findings
- `GET /api/events`: Server-Sent Events stream for live UI updates

## Tests

```bash
python3 -m unittest discover -s tests
```

## Troubleshooting startup

- If you see `address already in use`, keep the same command running and check
  the printed dashboard URL because the app may have moved to a new free port.
- If you want deterministic behavior, pass an explicit free port:
  `python3 -m bt_radar --demo --port 9876`
- If live BLE scanning fails on Linux, verify:
  - `bluetoothd` is installed and running
  - your adapter is present and enabled
  - your session has BLE scan permission
