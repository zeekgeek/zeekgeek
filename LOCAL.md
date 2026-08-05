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

## One-shot: Listing #4 (Brought Back By Each Other)

Quit Chrome fully (Cmd+Q), then:

```bash
cd ~/zeekgeek
git pull origin cursor/etsy-cursor-image-generation-0214
chmod +x scripts/mac-publish-listing-04.sh
./scripts/mac-publish-listing-04.sh
```

This starts Chrome with CDP on port 9222, waits for you to log into Printify,
then stages the listing (with `--publish`). Confirm Publish to Etsy in Printify if prompted.

## Start BrowserClaw with CDP (manual)

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
# All packages
./scripts/local-browserclaw-printify.sh

# Listing #4 only — Brought Back By Each Other
./scripts/local-browserclaw-printify.sh . listing-04-brought-back-by-each-other
```

Or manually:

```bash
source .venv/bin/activate

# Listing #4 only
python3 -m etsy_ai_space browserclaw-printify \
  --package etsy_ai_space/exports/listing-04-brought-back-by-each-other \
  --cdp-url 9222 \
  --reuse-tab \
  --wait

# Or all packages
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
