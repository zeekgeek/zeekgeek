#!/bin/bash
# Local BrowserClaw → Printify → Etsy staging workflow
# Run this on your Mac after cloning the repo and starting BrowserClaw with CDP.
#
# Usage:
#   ./scripts/local-browserclaw-printify.sh
#   ./scripts/local-browserclaw-printify.sh . listing-04-brought-back-by-each-other
#   PACKAGE=listing-04-brought-back-by-each-other ./scripts/local-browserclaw-printify.sh

set -euo pipefail

REPO_DIR="${1:-$(pwd)}"
PACKAGE_NAME="${2:-${PACKAGE:-}}"
CDP_URL="${BROWSERCLAW_CDP_URL:-9222}"

cd "$REPO_DIR"

if [ ! -f "pyproject.toml" ]; then
  echo "Error: pyproject.toml not found. Run from the repo root."
  exit 1
fi

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
pip install -q -e ".[etsy]"

echo "Checking BrowserClaw CDP on $CDP_URL..."
if ! curl -sS "http://127.0.0.1:9222/json/version" >/dev/null 2>&1; then
  echo "Error: BrowserClaw/CDP not found on 127.0.0.1:9222"
  echo "Start it with:"
  echo '  /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222 --user-data-dir="$HOME/chrome-cdp-profile"'
  exit 1
fi

PACKAGE_ARGS=()
if [ -n "$PACKAGE_NAME" ]; then
  PACKAGE_DIR="etsy_ai_space/exports/${PACKAGE_NAME}"
  if [ ! -d "$PACKAGE_DIR" ]; then
    # Allow full path or bare folder already under exports/
    if [ -d "$PACKAGE_NAME" ]; then
      PACKAGE_DIR="$PACKAGE_NAME"
    elif [ -d "etsy_ai_space/exports/listing-${PACKAGE_NAME}" ]; then
      PACKAGE_DIR="etsy_ai_space/exports/listing-${PACKAGE_NAME}"
    else
      echo "Error: listing package not found: $PACKAGE_NAME"
      echo "Expected e.g. etsy_ai_space/exports/listing-04-brought-back-by-each-other"
      exit 1
    fi
  fi
  if [ ! -f "$PACKAGE_DIR/listing.json" ]; then
    echo "Error: no listing.json in $PACKAGE_DIR"
    exit 1
  fi
  PACKAGE_ARGS=(--package "$PACKAGE_DIR")
  echo "Target package: $PACKAGE_DIR"
else
  PACKAGE_ARGS=(--all-listings)
  echo "Target: all listing packages under etsy_ai_space/exports/"
fi

echo "Previewing..."
python3 -m etsy_ai_space browserclaw-printify "${PACKAGE_ARGS[@]}" --dry-run

echo "Staging Printify draft(s) via BrowserClaw (you will publish to Etsy manually)..."
python3 -m etsy_ai_space browserclaw-printify \
  "${PACKAGE_ARGS[@]}" \
  --cdp-url "$CDP_URL" \
  --reuse-tab \
  --wait

echo "After you publish each product in Printify, run:"
echo "  python3 -m etsy_ai_space printify mark-submitted --all"
