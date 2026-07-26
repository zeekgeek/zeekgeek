# AGENTS.md

## Cursor Cloud specific instructions

This repo contains self-contained Python apps under `src/`:

- `bt_radar` — BLE scanner + FastAPI dashboard
- `bt_thrust` — Pump and dump Bluetooth Controller (BLE scanner + device dashboard + CLI)
- `wifi_radar` — WiFi motion radar + FastAPI dashboard
- `mac_battery` — MacBook battery/charging diagnostic + FastAPI dashboard
- `jet_radar` — private-jet ADS-B movement radar + strange-event alarm dashboard

There is no database and no frontend build step (dashboard HTML/JS is embedded
in each package’s `web.py`).

Environment: a Python virtualenv lives at `.venv` (created by the update script, which
also runs `pip install -e .`). Activate it before running anything: `source .venv/bin/activate`.

Running the apps:
- Cloud VMs have no Bluetooth adapter / `bluetoothd`, so live BLE scanning will not work.
 Always run bt_radar in demo mode: `python3 -m bt_radar --demo`. (Without `--demo` the app tries
 live scanning and auto-falls back to demo mode, printing a system event.)
- BT thrust controller (`bt_thrust`): Pump and dump Bluetooth Controller — `python3 -m bt_thrust` (port `8800`);
  terminal scanner: `python3 -m bt_thrust scan --interval 2`. Needs Bluetooth adapter.
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

## User-requested removal (minimal public footprint)

When the user asks to delete a feature, app, or thread of work, optimize for **few
lasting public artifacts in the repo**, not for erasing platform logs (Cursor/GitHub
still retain account activity — agents cannot scrub those).

**Do immediately**

1. Stop related processes (servers, tmux sessions, background scanners).
2. Delete source, tests, CLI entry in `pyproject.toml`, README/AGENTS sections — one
   focused commit or a **single revert** of the merge commit that introduced the feature
   on `main` (prefer revert on `main` over a long-lived feature branch).
3. Close obsolete open PRs; delete remote feature branches after the revert/ removal PR
   is open or merged.
4. Use **neutral commit/PR titles** (e.g. “Remove unused module”, “Revert #N”) — avoid
   sensitive product names in titles if the user asked for discretion.
5. Do not add new docs, demos, recordings, or long PR narratives about the removed work.

**Prefer for `main`**

- One PR that **reverts the original merge commit** (clean undo) rather than many
  follow-up commits on a named feature branch.

**Optional (user must explicitly ask)**

- Rewrite git history (`git filter-repo` / BFG) to purge paths from all commits —
  requires force-push, breaks forks/clones, needs coordinated consent.

**Tell the user they control outside the repo**

- Archive/delete cloud agent runs in Cursor if the UI allows.
- Merge the removal PR, then `git pull` and reinstall locally; remove local clones if desired.
- GitHub will still show closed PRs and old commits unless history was rewritten.

**Do not claim**

- That chat transcripts, IP/account audit logs, or all Git history are gone — only that
  the **current tree and default branch** no longer contain the code after merge.
