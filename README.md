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

---

# Etsy AI Space

Phased agent swarm for **safe** print-on-demand store research. It follows a
manual-upload rollout: scrape trends → creative brief → listing copy → JSON/CSV
export. Nothing publishes to Etsy automatically.

## Architecture

```text
src/etsy_ai_space/
├── database/
│   └── schema.sql         # SQLite schema (listings, concepts, drafts)
├── scraper/
│   └── etsy_scraper.py    # Playwright niche scraper → DB
├── agents/
│   └── workers.py         # Copywriter, design (Midjourney), SEO workers
├── pipeline/
│   ├── orchestrator.py    # Manager agent → 5 concepts → export
│   └── state.json         # Live agent status (gitignored; see state.schema.json)
├── dashboard/
│   └── app.py             # Streamlit live status UI
├── tools/                 # Humanized delays + QC rules
└── obsidian_vault/        # Brief memory (Markdown)
```

## Quick start (demo — no Etsy network)

```bash
source .venv/bin/activate
pip install -e .

# Phase 1 only — scrape + SQLite
python3 -m etsy_ai_space scrape "retro cat shirt" --demo

# Full swarm — scrape, 5 concepts, worker drafts, export
python3 -m etsy_ai_space orchestrate "retro cat shirt" --demo

# Legacy single-brief pipeline
python3 -m etsy_ai_space pipeline "retro cat shirt" --demo
```

Inspect stored trends:

```bash
python3 -m etsy_ai_space stats
python3 -m etsy_ai_space top --limit 5
```

## Live scraping (Phase 1)

Requires Playwright and a local Chromium install. Requests are **rate-limited by default**
(3–6s between Etsy requests, max ~12/min, exponential backoff on 429/503). Tune constants
in `src/etsy_ai_space/scraper/rate_limit.py`.

```bash
pip install -e ".[etsy]"
playwright install chromium
python3 -m etsy_ai_space scrape "cottagecore mushroom shirt"
```

The scraper uses randomized delays between actions. Start with low volume and
 `--max-results 24` while you validate selectors.

## Claude orchestration (Phase 2–3)

Set `ANTHROPIC_API_KEY` and run the pipeline without `--demo` when ready:

```bash
export ANTHROPIC_API_KEY=sk-...
python3 -m etsy_ai_space pipeline "retro cat shirt"
```

Without the key, Ultron falls back to deterministic templates so you can test
the full export flow offline.

## Safe scaling checklist

1. Run demo pipeline locally and review `etsy_ai_space/exports/listing-bundle-*.json`.
2. Generate artwork from `image_prompt` in your tool of choice; save paths into the bundle.
3. Upload listings **manually** in Etsy Seller Manager (3–5/day for new shops).
4. Only after the shop is established, consider Etsy Open API or browser assist tools.
5. Never auto-delete listings — warroom outputs recommendations only.

## Command reference

```text
python3 -m etsy_ai_space scrape <query> [--demo] [--max-results 48] [--min-score 35]
python3 -m etsy_ai_space orchestrate <niche> [--demo] [--concepts 5] [--skip-scrape]
python3 -m etsy_ai_space pipeline <query> [--demo] [--niche "..."] [--export-dir PATH]
python3 -m etsy_ai_space export [--export-dir PATH]
python3 -m etsy_ai_space cursor-generate --list
python3 -m etsy_ai_space cursor-generate --attach <draft-id> <image-file>
python3 -m etsy_ai_space browserclaw-upload --dry-run
python3 -m etsy_ai_space browserclaw-upload --package etsy_ai_space/exports/listing-02-we-do-recover --reuse-tab
python3 -m etsy_ai_space stats
python3 -m etsy_ai_space top [--limit 10]

# Live Streamlit dashboard (auto-refreshes from pipeline/state.json)
pip install -e ".[etsy]"
python -m dashboard.app --port 8501
# or: python3 -m etsy_ai_space dashboard --port 8501

# Standalone module entry points
python3 -m etsy_ai_space.scraper.etsy_scraper "retro cat shirt" --demo
python3 -m etsy_ai_space.pipeline.orchestrator "retro cat shirt" --demo
```

## Image generation with the Cursor agent

Each listing draft now carries a `cursor_image_prompt` optimized for the Cursor image generator. The Python pipeline does not generate images itself; it prepares the prompts and attaches the assets once the Cursor agent creates them.

Typical flow:

1. Run the pipeline to create drafts with prompts:

   ```bash
   python3 -m etsy_ai_space orchestrate "retro cat shirt" --demo
   ```

2. Ask the Cursor agent to generate the images. The agent can list pending jobs:

   ```bash
   python3 -m etsy_ai_space cursor-generate --list
   ```

   Then, for each draft, the agent calls `GenerateImage` with the `cursor_prompt` and saves the resulting image to a file.

3. Attach the generated image to the draft:

   ```bash
   python3 -m etsy_ai_space cursor-generate --attach <draft-id> ./generated-image.png
   ```

   The image is copied into `etsy_ai_space/exports/images/` and the draft's `image_path` is updated.

4. Re-export the bundle so the CSV/JSON includes the image path:

   ```bash
   python3 -m etsy_ai_space export
   ```

This keeps the manual-upload safety gate: the pipeline never publishes to Etsy automatically, and image generation is agent-driven rather than fully autonomous.

## BrowserClaw → Printify → Etsy (stage drafts, you publish)

Requires BrowserClaw Chromium with CDP and an active Printify login (Etsy shop connected).

```bash
# Preview
python3 -m etsy_ai_space browserclaw-printify --all-listings --dry-run

# Open Printify in BrowserClaw and stage drafts (does not publish)
python3 -m etsy_ai_space browserclaw-printify \
  --all-listings \
  --cdp-url 9222 \
  --reuse-tab \
  --wait
```

Then in Printify: review each product → **Publish to Etsy**. When finished:

```bash
python3 -m etsy_ai_space printify mark-submitted --all
```

## Printify draft push (then wait for you to submit)

Push listing packages into Printify as **drafts only**. The workflow never auto-publishes;
it waits for you to submit/publish in the Printify UI.

```bash
# 1) Set token + fill shop/provider IDs
export PRINTIFY_API_TOKEN=your_token
# edit etsy_ai_space/printify.yaml → shop_id + print_provider_id
python3 -m etsy_ai_space printify discover --shops
python3 -m etsy_ai_space printify discover --providers

# 2) Preview push for Listing #3
python3 -m etsy_ai_space printify push \
  --package etsy_ai_space/exports/listing-03-recover-loudly-phoenix \
  --dry-run

# 3) Create Printify drafts (no publish)
python3 -m etsy_ai_space printify push --all-listings

# 4) Wait for you to submit in Printify, then mark done
python3 -m etsy_ai_space printify pending
python3 -m etsy_ai_space printify wait
# After you publish/submit each draft in Printify:
python3 -m etsy_ai_space printify mark-submitted --all
```

## BrowserClaw listing upload (assisted posting)

BrowserClaw can fill the Etsy Seller Manager create-listing form for you. By default it
**saves as Draft** so you review before publish. Requires BrowserClaw Chromium running
with CDP enabled and an active Etsy seller login.

```bash
# Preview what would upload (no browser actions)
python3 -m etsy_ai_space browserclaw-upload --dry-run

# List uploadable drafts
python3 -m etsy_ai_space browserclaw-upload --list

# Upload Listing #2 package as an Etsy draft
python3 -m etsy_ai_space browserclaw-upload \
  --package etsy_ai_space/exports/listing-02-we-do-recover \
  --cdp-url 9222 \
  --reuse-tab

# Upload a specific draft id from SQLite
python3 -m etsy_ai_space browserclaw-upload --draft-id 1 --reuse-tab

# Publish instead of draft (blocked while require_manual_upload=true unless --force-publish)
python3 -m etsy_ai_space browserclaw-upload --draft-id 1 --publish --force-publish
```

Safety:
- `require_manual_upload: true` in `etsy_ai_space/autopilot.yaml` blocks `--publish` unless you pass `--force-publish`
- `daily_upload_cap` limits how many assisted uploads can run per day
- Prefer draft-first for new shops (3–5/day)
