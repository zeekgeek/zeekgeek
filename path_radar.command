#!/bin/bash
# Path Radar — double-click this file in Finder on macOS Sequoia (15).
#
# First run creates a local virtualenv and installs FastAPI + uvicorn
# (Bluetooth extras are not required). Safari/Chrome opens the dashboard.
# Leave this Terminal window open. Press Ctrl+C to quit.
#
# If macOS blocks it: Right-click → Open, or:
#   xattr -d com.apple.quarantine path_radar.command
#   chmod +x path_radar.command
#
# Needs Python 3.11 or newer (Homebrew: brew install python).
# Sequoia's system /usr/bin/python3 is often 3.9 and is skipped on purpose.
#
# Pass flags after the file name, e.g.  ./path_radar.command --demo

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/local/sbin:/Library/Frameworks/Python.framework/Versions/Current/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

py_ok() {
  "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null
}

find_python() {
  local candidate
  for candidate in \
    python3.13 python3.12 python3.11 \
    /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.11 /opt/homebrew/bin/python3 \
    /usr/local/bin/python3.13 /usr/local/bin/python3.12 /usr/local/bin/python3.11 /usr/local/bin/python3 \
    /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
    /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 \
    /Library/Frameworks/Python.framework/Versions/3.11/bin/python3 \
    python3
  do
    if command -v "$candidate" >/dev/null 2>&1 || [[ -x "$candidate" ]]; then
      if py_ok "$candidate"; then
        command -v "$candidate" 2>/dev/null || echo "$candidate"
        return 0
      fi
    fi
  done
  return 1
}

fail() {
  echo
  echo "Path Radar could not start."
  echo "$1"
  echo
  echo "Install Python 3.11+ with Homebrew:"
  echo "  brew install python"
  echo "or from https://www.python.org/downloads/"
  echo
  read -r -p "Press Return to close this window. " _
  exit 1
}

echo "Path Radar"
echo "=========="
echo

if [[ ! -f "$ROOT/path_radar.py" || ! -d "$ROOT/src/trace_radar" ]]; then
  fail "Keep path_radar.command next to path_radar.py and the src/ folder."
fi

BASE_PY="$(find_python || true)"
if [[ -z "${BASE_PY}" ]]; then
  fail "Python 3.11 or newer was not found (system python3 on Sequoia is often 3.9)."
fi

VENV="$ROOT/.venv"
if [[ ! -x "$VENV/bin/python" ]] || ! py_ok "$VENV/bin/python"; then
  echo "Creating virtualenv with $BASE_PY …"
  "$BASE_PY" -m venv "$VENV"
fi
PY="$VENV/bin/python"

if ! "$PY" -c "import fastapi, uvicorn" 2>/dev/null; then
  echo "Installing FastAPI + uvicorn (one-time) …"
  "$PY" -m pip install -q --upgrade pip
  "$PY" -m pip install -q "fastapi>=0.110" "uvicorn[standard]>=0.27"
fi

export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

echo "Starting dashboard (live traceroute, demo fallback if needed)…"
echo "Leave this window open. Press Ctrl+C to quit."
echo

exec "$PY" "$ROOT/path_radar.py" --open "$@"
