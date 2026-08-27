#!/bin/bash
# One-shot Mac helper: start Chrome CDP (if needed) → stage Listing #4 to Printify.
# Run from the repo root on your Mac:
#   cd ~/zeekgeek && ./scripts/mac-publish-listing-04.sh

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

PACKAGE="etsy_ai_space/exports/listing-04-brought-back-by-each-other"
CDP_URL="http://127.0.0.1:9222"
PROFILE="${HOME}/chrome-cdp-profile"
CHROME="${CHROME_PATH:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"

if [ ! -f "$PACKAGE/listing.json" ]; then
  echo "ERROR: missing $PACKAGE/listing.json"
  echo "Run: git checkout cursor/etsy-cursor-image-generation-0214 && git pull"
  exit 1
fi

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -e ".[etsy]"

cdp_up() {
  curl -sS --max-time 2 "$CDP_URL/json/version" >/dev/null 2>&1
}

if ! cdp_up; then
  if [ ! -x "$CHROME" ]; then
    echo "ERROR: Chrome not found at: $CHROME"
    echo "Set CHROME_PATH to your Chrome/Chromium binary and retry."
    exit 1
  fi
  echo "CDP not up — launching Chrome with --remote-debugging-port=9222 ..."
  mkdir -p "$PROFILE"
  "$CHROME" \
    --remote-debugging-port=9222 \
    --user-data-dir="$PROFILE" \
    --no-first-run \
    "https://printify.com/app/store/products" >/tmp/chrome-cdp.log 2>&1 &
  echo "Waiting for CDP on 9222..."
  for _ in $(seq 1 30); do
    if cdp_up; then
      break
    fi
    sleep 1
  done
fi

if ! cdp_up; then
  echo "ERROR: still cannot reach $CDP_URL"
  echo "Quit all Chrome windows (Cmd+Q), then re-run this script."
  exit 1
fi

echo "CDP OK:"
curl -sS "$CDP_URL/json/version"
echo
echo
echo ">>> Log into Printify in the Chrome window that just opened (if needed)."
echo ">>> Press Enter here when Printify is logged in and ready..."
read -r _

echo "Staging Listing #4 via BrowserClaw → Printify..."
python3 -m etsy_ai_space browserclaw-printify \
  --package "$PACKAGE" \
  --cdp-url 9222 \
  --reuse-tab \
  --publish \
  --wait

echo
echo "Done staging. In Printify, confirm Publish to Etsy if still needed, then:"
echo "  python3 -m etsy_ai_space printify mark-submitted --all"
