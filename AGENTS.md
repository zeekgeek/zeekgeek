# AGENTS.md

## Cursor Cloud specific instructions

This repo is a single self-contained Python app (`bt_radar`): one process runs both the
BLE scanner and the FastAPI/uvicorn web dashboard. There are no separate services, no
database, and no frontend build step (the dashboard HTML/JS is embedded in `src/bt_radar/web.py`).

Environment: a Python virtualenv lives at `.venv` (created by the update script, which
also runs `pip install -e .`). Activate it before running anything: `source .venv/bin/activate`.

Running the app:
- Cloud VMs have no Bluetooth adapter / `bluetoothd`, so live BLE scanning will not work.
  Always run in demo mode: `python3 -m bt_radar --demo`. (Without `--demo` the app tries
  live scanning and auto-falls back to demo mode, printing a system event.)
- The dashboard serves on `http://127.0.0.1:8765` by default. If the port is busy the app
  auto-increments to the next free port and prints the chosen URL, so read the startup log
  rather than assuming `8765`. Pass `--port <n>` for deterministic binding.

Tests: `python3 -m unittest discover -s tests` (stdlib `unittest`; the package must be
installed editable first, which the update script handles).

Lint/build: no linter/formatter is configured, and there is no separate build step
(editable install is the build). See `README.md` for full command options.
