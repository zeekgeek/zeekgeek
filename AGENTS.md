# AGENTS.md

## Cursor Cloud specific instructions

This repo contains self-contained Python apps under `src/`:

- `bt_radar` — BLE scanner + FastAPI dashboard
- `wifi_radar` — WiFi motion radar + FastAPI dashboard
- `mac_battery` — MacBook battery/charging diagnostic + FastAPI dashboard
- `jet_radar` — private-jet ADS-B movement radar + strange-event alarm dashboard
- `adorime_control` — AdoRime/Galaku BLE toy control + dashboard (default port `8785`)

There is no database and no frontend build step (dashboard HTML/JS is embedded
in each package’s `web.py`).

Environment: a Python virtualenv lives at `.venv` (created by the update script, which
also runs `pip install -e .`). Activate it before running anything: `source .venv/bin/activate`.

Running the apps:
- Cloud VMs have no Bluetooth adapter / `bluetoothd`, so live BLE scanning will not work.
  Always run bt_radar in demo mode: `python3 -m bt_radar --demo`. (Without `--demo` the app tries
  live scanning and auto-falls back to demo mode, printing a system event.)
- `adorime_control` defaults to **live-only** scan (no simulated fallback). On cloud VMs use
  `python3 -m adorime_control --demo` for UI testing only. Real toys: run on a Mac with Bluetooth
  at `http://127.0.0.1:8785` (default port `8785`).
- WiFi radar: `python3 -m wifi_radar --demo` (live needs `iw` / wireless hardware).
- Mac battery: `python3 -m mac_battery --demo` on non-macOS hosts (live needs macOS `ioreg` /
 AppleSmartBattery). Default dashboard port is `8780`.
- Jet radar: `python3 -m jet_radar --demo` (live polls adsb.lol; needs network egress).
  Default dashboard port is `8790`.
- Dashboards bind to `http://127.0.0.1:<port>` by default. If the port is busy the app
 auto-increments to the next free port and prints the chosen URL, so read the startup log
 rather than assuming the default. Pass `--port <n>` for deterministic binding.

Tests: `python3 -m unittest discover -s tests` (stdlib `unittest`; the package must be
installed editable first, which the update script handles).

Lint/build: no linter/formatter is configured, and there is no separate build step
(editable install is the build). See `README.md` for full command options.
