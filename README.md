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

## AdoRime Control (separate app)

`adorime_control` is a standalone Bluetooth control app, separate from
`bt_radar`. It includes:

- BLE scan + dashboard in one process
- target selection for AdoRime-named devices
- manual thrust commands (`thrust` + `pattern`)
- AI thrust control mode that auto-generates bounded commands
- control/event API endpoints for remote automation

Quick start:

```bash
source .venv/bin/activate
python3 -m adorime_control --demo
```

Open the printed dashboard URL (default `http://127.0.0.1:8785`).

CLI options:

- `--demo`: run simulated devices (recommended on cloud VMs)
- `--host` / `--port`
- `--stale-after`
- `--no-auto-demo-fallback`
- `--log-level`

API endpoints:

- `GET /api/status`: full device + control snapshot
- `POST /api/control/target`: set/clear target, body `{"address": "..."}`
- `POST /api/control/manual`: send manual command, body `{"thrust": 55, "pattern": "pulse"}`
- `POST /api/control/ai`: configure AI mode, body `{"enabled": true, "aggressiveness": 0.7, "min_thrust": 25, "max_thrust": 92}`
- `POST /api/control/ai/step`: force one immediate AI command
- `GET /api/events`: Server-Sent Events stream

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

---

# WiFi Motion Radar

A separate, self-contained radar for **WiFi** devices. It scans nearby WiFi
access points, tracks each one by BSSID, classifies every target as
**stationary** or **moving** from its signal history, plots them on a
proximity map, and raises an **alarm when a device approaches within a
configurable range**.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
python3 -m wifi_radar --demo
```

Open <http://127.0.0.1:8770>, click **Enable notifications** and **Sound: on**,
then watch the simulated "Espressif" device walk toward the sensor until it
crosses the alarm ring.

For a live scan (Linux, needs the `iw` tool and usually root):

```bash
sudo python3 -m wifi_radar
```

If live scanning is unavailable (no `iw`, no wireless interface, or missing
permission) the app auto-switches to demo mode and posts a system event.

## How motion is classified

Each device is tracked only through its received signal strength (RSSI) over
time:

- **Stationary**: the recent RSSI series is flat (low jitter and no drift).
- **Moving**: the RSSI either trends (getting stronger/weaker) or jitters well
  beyond normal measurement noise.
- **Direction**: `approaching`, `departing`, or `steady`, from the RSSI slope.

RSSI is noisy — walls, reflections, antenna orientation, and transmit-power
changes all distort it — so treat these labels and distances as hints, not
measurements.

## The proximity alarm

- A red dashed ring on the map shows the current alarm range.
- When a device's estimated distance crosses **inside** that range, the radar
  fires an `alarm` event, flashes a banner, sends a browser notification, and
  (if enabled) beeps.
- Hysteresis prevents re-firing: the device must move back out past
  `range × 1.2` before it can alarm again.
- Set the range live with the header slider, or with `--alarm-range` at
  startup. Changing the range is also exposed at `POST /api/alarm`.

## Command options

```text
python3 -m wifi_radar --host 127.0.0.1 --port 8770 --alarm-range 5 --scan-interval 3
```

- `--demo`: simulate WiFi devices instead of scanning hardware
- `--interface`: WiFi interface to scan (auto-detected if omitted)
- `--alarm-range`: alarm when a device is within this many metres
- `--scan-interval`: seconds between live `iw` scans
- `--stale-after`: seconds without sightings before a device is marked left
- `--no-auto-demo-fallback`: exit instead of auto-switching to demo mode
- `--host` / `--port` / `--log-level`

The app also auto-selects the next free port if the requested `--port` is busy.

## API

- `GET /api/devices`: current snapshot of devices, motion labels, and alarm state
- `POST /api/alarm`: set the alarm range, body `{"range_m": 5}`
- `GET /api/events`: Server-Sent Events stream for live UI updates

## Tests

```bash
python3 -m unittest discover -s tests
```
