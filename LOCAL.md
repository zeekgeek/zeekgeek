# Local BrowserClaw + Printify workflow

Run this workflow on your own machine instead of the cloud agent.

## One-time setup

```bash
git clone https://github.com/zeekgeek/zeekgeek.git
cd zeekgeek
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[etsy]"
```

## Copy the generated shirt images

The generated images are in `etsy_ai_space/exports/` (gitignored). From the cloud VM:

1. Copy the whole `etsy_ai_space/exports/` folder to your local machine, OR
2. Regenerate images locally with the `cursor-generate` / `GenerateImage` workflow.

## Start BrowserClaw with CDP

```bash
mkdir -p ~/chrome-cdp-profile
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/chrome-cdp-profile" \
  --no-first-run
```

Verify:

```bash
curl http://127.0.0.1:9222/json/version
```

## Run the staging script

```bash
./scripts/local-browserclaw-printify.sh
```

Or manually:

```bash
source .venv/bin/activate
python3 -m etsy_ai_space browserclaw-printify \
  --all-listings \
  --cdp-url 9222 \
  --reuse-tab \
  --wait
```

## After you publish in Printify

```bash
python3 -m etsy_ai_space printify mark-submitted --all
```

## Why local?

The cloud agent cannot reach `127.0.0.1:9222` or `127.0.0.1:9010` on your Mac. BrowserClaw must be driven from the same machine it is running on.
