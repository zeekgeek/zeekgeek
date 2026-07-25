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

---

# Adorime Thrust Controller

Live BLE scanner and thrust/vibration controller focused on **Adorime**
products. Identifies devices from their advertised BLE names (for example
`BGSF`, `SN80`, `AX05`) and exposes a rose-themed dashboard with live thrust
controls.

Supported Adorime profiles include masturbators, anal trainers, rabbit dildos,
wearable eggs, cock rings, chastity cage, and related dual-motor models.
Control uses the Adorime/Galaku-family BLE write format documented via
Buttplug/Intiface community research.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
python3 -m bt_thrust
```

Open <http://127.0.0.1:8800>, select a live Adorime toy, click **Connect**,
then use the thrust/vibration sliders or pattern presets.

Requires a powered Bluetooth adapter and an Adorime device in
advertising/pairing mode. Linux hosts usually need `bluetoothd` running and BLE
scan permission for the current user/session.

## Dashboard behavior

- **Live Adorime toys** panel lists only recognized in-range Adorime devices
  with RSSI, estimated distance, and movement hints.
- **Thrust controls** expose separate **Thrust** and **Vibration** sliders on
  dual-motor models, with live command sending while connected.
- **Pattern presets** loop thrust/vibration levels while connected.
- **Stop all** sends a zero command and cancels any active pattern.
- **Browser notifications** for discovered, connected, and disconnected toys.

## Command options

```text
python3 -m bt_thrust --host 127.0.0.1 --port 8800 --stale-after 20
```

- `--host`: dashboard bind address
- `--port`: dashboard port (default `8800`)
- `--stale-after`: seconds without sightings before a toy is marked as left
- `--log-level`: `debug`, `info`, `warning`, or `error`

## API

- `GET /api/toys`: current snapshot of scanned toys and control state
- `POST /api/select`: body `{"address": "..."}` to select a toy in the UI
- `POST /api/toys/{address}/connect` / `disconnect`: manage BLE connection
- `POST /api/toys/{address}/control`: body `{"levels": {"thrust": 50, "vibrate": 30}}`
- `POST /api/toys/{address}/pattern`: body `{"pattern": "pulse"}`
- `GET /api/events`: Server-Sent Events stream for live UI updates

## Tests

```bash
python3 -m unittest discover -s tests
```

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

---

# MacBook Battery Diagnostic

Realtime charging and battery-health monitor aimed at Intel MacBook Pros
(including 2018 models). It reads Apple’s `AppleSmartBattery` data via `ioreg`
and shows:

- live **voltage**, **amperage**, and **watts** (V × I at the pack)
- **charge level** and adapter / charging state
- **ETA to 80%** (optimized charge target) and **ETA to full**
- **battery health %**, design vs worn capacity, **cycle count**, and wear band

On non-macOS hosts (or when `ioreg` is unavailable) it auto-falls back to a
demo session that simulates a worn 2018-class pack charging from ~42%.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
python3 -m mac_battery --demo
```

Open the printed dashboard URL (default <http://127.0.0.1:8780>). The terminal
also redraws a live snapshot every second.

On a MacBook:

```bash
python3 -m mac_battery
```

Single snapshot (no live loop / dashboard):

```bash
python3 -m mac_battery --once
```

## Command options

```text
python3 -m mac_battery --host 127.0.0.1 --port 8780 --interval 1 --target 80
```

- `--demo`: simulate a 2018 MBP charge session
- `--once`: print one snapshot and exit
- `--interval`: seconds between samples (default `1`)
- `--target`: optimized charge percent for ETA (default `80`)
- `--no-web`: terminal-only monitor
- `--no-terminal`: dashboard only
- `--no-auto-demo-fallback`: exit instead of using demo data when live read fails
- `--host` / `--port` / `--log-level`

## API

- `GET /api/snapshot`: latest report plus short history and events
- `GET /api/events`: Server-Sent Events stream for live UI updates

## Notes

- Watts and amps are **battery-side** values from IOKit, not the AC adapter’s
  nameplate wattage.
- ETA uses a smoothed charge current; it is an estimate and will move as the
  pack tapers near full (CC/CV behavior).
- Apple’s own “time remaining” is shown when the firmware reports a valid value.

---

# Private Jet Movement Radar

Watches public ADS-B traffic for business jets, learns a **historical movement
baseline**, and sounds a **strange-event alarm** when volume spikes and
anomaly triggers pile up.

It also scores publicly reported high-net-worth aircraft for **move vs sit
still** posture, flags **military tanker rendezvous** and **high-speed
maneuvers**, and ranks **privacy / hideout candidate** regions when watched
jets go quiet near destinations with publicly reported HNW property corridors
(Hawaii Kauai/Maui/Lanai, Jackson Hole, Aspen, NZ South Island, Montana, …).

Attribution of a tail number to a named person is imperfect (LLC shells,
fractional ownership, registration changes). The radar reports observable
ADS-B patterns and publicly sourced watchlist notes — it does **not** claim
that a named person is on board, or that any underground facility exists.

## Quick start

```bash
source .venv/bin/activate
pip install -e .
python3 -m jet_radar --demo
```

Open the printed dashboard URL (default <http://127.0.0.1:8790>). Enable
notifications and sound, then wait for the demo scramble / Hawaii quiet /
tanker / surge sequence to trip the alarm.

Live ADS-B (polls [adsb.lol](https://api.adsb.lol)):

```bash
python3 -m jet_radar
```

Optional regional watch:

```bash
python3 -m jet_radar --center 38.9,-77.0 --radius-nm 200
```

## What trips a trigger

- `traffic-surge` / `departure-wave` — airborne count or new departures far above history
- `watchlist-scramble` — several reactive watched jets depart together
- `high-speed-maneuver` — extreme ground speed, turn rate, or climb
- `tanker-rendezvous` — bizjet near a KC-135-class tanker at similar altitude
- `emergency-squawk` — 7500 / 7600 / 7700
- `dark-flight-spike` — unusual share of flights with no callsign
- `privacy-landing` — watched jet leaves coverage inside a known privacy region

Enough triggers in a short window fires the **strange-event alarm**.

## Command options

```text
python3 -m jet_radar --host 127.0.0.1 --port 8790 --sigma 3 --trigger-threshold 3
```

- `--demo`: simulated scramble + Hawaii quiet + tanker + surge
- `--poll-interval`: seconds between live ADS-B polls (default `60`)
- `--stale-after`: seconds before a missing jet is marked left coverage
- `--sigma`: z-score above baseline that counts as a surge trigger
- `--trigger-threshold`: triggers in the recent window needed to alarm
- `--baseline-samples`: poll cycles before anomaly scoring starts
- `--center` / `--radius-nm`: optional regional filter
- `--no-auto-demo-fallback` / `--host` / `--port` / `--log-level`

## API

- `GET /api/jets`: snapshot (jets, baseline, hideout candidates, watchlist moves, events)
- `POST /api/sensitivity`: body `{"sigma": 3.0, "trigger_threshold": 3}`
- `GET /api/events`: Server-Sent Events stream
