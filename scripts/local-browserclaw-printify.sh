#!/bin/bash
# Local BrowserClaw → Printify → Etsy staging workflow
# Run this on your Mac after cloning the repo and starting BrowserClaw with CDP.

set -euo pipefail

REPO_DIR="${1:-$(pwd)}"
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

echo "Previewing packages..."
python3 -m etsy_ai_space browserclaw-printify --all-listings --dry-run

echo "Staging Printify drafts (you will publish to Etsy manually)..."
python3 -m etsy_ai_space browserclaw-printify \
  --all-listings \
  --cdp-url "$CDP_URL" \
  --reuse-tab \
  --wait

echo "After you publish each product in Printify, run:"
echo "  python3 -m etsy_ai_space printify mark-submitted --all"
