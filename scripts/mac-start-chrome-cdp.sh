#!/bin/bash
# Start Google Chrome with CDP enabled for Playwright / BrowserClaw attach.
# Run this in a separate Terminal window and LEAVE IT OPEN.

set -euo pipefail

PORT="${1:-9222}"
PROFILE="${HOME}/browserclaw-profile"

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
if [[ ! -x "$CHROME" ]]; then
  echo "Google Chrome not found at: $CHROME" >&2
  exit 1
fi

echo "Starting Chrome with CDP on http://127.0.0.1:${PORT}"
echo "Profile: ${PROFILE}"
echo "Leave this window open while scraping."

exec "$CHROME" \
  --remote-debugging-port="${PORT}" \
  --remote-debugging-address=127.0.0.1 \
  --user-data-dir="${PROFILE}"
