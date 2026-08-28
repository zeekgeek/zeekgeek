# AGENTS.md

## Cursor Cloud specific instructions

This repo contains self-contained Python apps under `src/`:

- `bt_radar` — BLE scanner + FastAPI dashboard
- `wifi_radar` — WiFi motion radar + FastAPI dashboard
- `mac_battery` — MacBook battery/charging diagnostic + FastAPI dashboard
- `jet_radar` — private-jet ADS-B movement radar + strange-event alarm dashboard
- `path_radar` — force-directed network map + continuous traceroute (Scanny + PingPlotter)
- `market_radar` — crypto board + stock bellwethers + market-health score dashboard
- `etsy_ai_space` — phased Etsy POD research swarm (scrape → brief → export; manual upload)

There is no database and no frontend build step (dashboard HTML/JS is embedded
in each package’s `web.py`).

Environment: a Python virtualenv lives at `.venv` (created by the update script, which
also runs `pip install -e .`). Activate it before running anything: `source .venv/bin/activate`.

Running the apps:
- Cloud VMs have no Bluetooth adapter / `bluetoothd`, so live BLE scanning will not work.
 Always run bt_radar in demo mode: `python3 -m bt_radar --demo`. (Without `--demo` the app tries
 live scanning and auto-falls back to demo mode, printing a system event.)
- WiFi radar: `python3 -m wifi_radar --demo` (live needs `iw` / wireless hardware).
- Mac battery: `python3 -m mac_battery --demo` on non-macOS hosts (live needs macOS `ioreg` /
 AppleSmartBattery). Default dashboard port is `8780`.
- Jet radar: `python3 -m jet_radar --demo` (live polls adsb.lol; needs network egress).
 Default dashboard port is `8790`.
- Path radar: `python3 -m path_radar` (live ICMP TTL traceroute + Team Cymru ASN +
 RIPE geo + ARP LAN). Optional `--demo` for the simulated Comcast/Cogent/Google
 topology. Default dashboard port is `8800`.
- Market radar: `python3 -m market_radar --demo` (live polls CoinGecko + Stooq + the
 alternative.me Fear & Greed index; needs network egress, no API keys). Default dashboard
 port is `8810`. Demo simulates a risk-off shock and relief rally.
- Etsy AI Space: `python3 -m etsy_ai_space scrape "retro cat shirt" --demo` (Phase 1 demo scraper +
 SQLite logging). Live Etsy scraping needs `pip install -e ".[etsy]"` and `playwright install chromium`.
 Phase 4 exports JSON/CSV for **manual** listing upload — no Etsy API publish in this flow.
 Dashboard: `python3 -m etsy_ai_space dashboard` (Streamlit; reads `etsy_ai_space/pipeline/state.json`).
 Autopilot: `python3 -m etsy_ai_space autopilot --once --demo` (loop with `autopilot.yaml`; manual upload gate).
 Image generation: `python3 -m etsy_ai_space cursor-generate --list` to list pending prompts,
 then ask the Cursor agent to generate images and attach them with `cursor-generate --attach <draft-id> <file>`.
 Images are copied to `etsy_ai_space/exports/images/` and referenced in the export bundle.
 BrowserClaw upload: `python3 -m etsy_ai_space browserclaw-upload --dry-run` then
 `browserclaw-upload --package etsy_ai_space/exports/listing-02-we-do-recover --reuse-tab`
 (saves as Etsy draft by default; needs BrowserClaw CDP + seller login).
 `--publish` is blocked while `require_manual_upload: true` unless `--force-publish`.
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
