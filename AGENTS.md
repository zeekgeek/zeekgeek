# AGENTS.md

## Cursor Cloud specific instructions

This repo contains two self-contained Python apps installed from one package: `bt_radar`
(BLE proximity radar) and `wifi_radar` (WiFi motion radar). Each is a single process that
runs both its scanner and a FastAPI/uvicorn web dashboard. There are no separate services,
no database, and no frontend build step (the dashboard HTML/JS is embedded in each app's
`web.py`).

Environment: a Python virtualenv lives at `.venv` (created by the update script, which
also runs `pip install -e .`). Activate it before running anything: `source .venv/bin/activate`.
On Ubuntu, creating the venv requires the `python3.12-venv` system package.

Running the apps (Cloud VMs have no Bluetooth/WiFi hardware, so always use `--demo`; without
it each app tries a live scan and auto-falls back to demo mode, printing a system event):
- BLE: `python3 -m bt_radar --demo` — dashboard on `http://127.0.0.1:8765` by default.
- WiFi: `python3 -m wifi_radar --demo` — dashboard on `http://127.0.0.1:8770` by default.
- If the requested port is busy, each app auto-increments to the next free port and prints
 the chosen URL, so read the startup log rather than assuming the default. Pass `--port <n>`
 for deterministic binding.

Tests: `python3 -m unittest discover -s tests` (stdlib `unittest`; covers both apps; the
package must be installed editable first, which the update script handles).

Lint/build: no linter/formatter is configured, and there is no separate build step
(editable install is the build). See `README.md` for full command options.
