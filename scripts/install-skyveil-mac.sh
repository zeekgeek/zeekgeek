#!/usr/bin/env bash
# Install SkyVeil on macOS (Intel or Apple silicon) into ~/.skyveil and add a
# `skyveil` launcher. Only needs Python 3.11+ (brew install python@3.12).
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This installer is for macOS." >&2
  exit 1
fi

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
install_dir="${SKYVEIL_HOME:-$HOME/.skyveil}"

pick_python() {
  for candidate in python3.13 python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1 &&
       "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
      command -v "$candidate"
      return 0
    fi
  done
  return 1
}

python_bin="$(pick_python)" || {
  echo "Python 3.11+ not found. Install it with: brew install python@3.12" >&2
  exit 1
}

echo "Using $python_bin ($("$python_bin" --version))"
"$python_bin" -m venv "$install_dir/venv"
"$install_dir/venv/bin/python" -m pip install --quiet --upgrade pip
"$install_dir/venv/bin/python" -m pip install --quiet "$repo_dir"

mkdir -p "$install_dir/bin"
cat > "$install_dir/bin/skyveil" <<LAUNCH
#!/usr/bin/env bash
exec "$install_dir/venv/bin/python" -m skyveil "\$@"
LAUNCH
chmod +x "$install_dir/bin/skyveil"

echo
echo "Installed. Run it with:"
echo "  $install_dir/bin/skyveil --open          # Mac only, opens your browser"
echo "  $install_dir/bin/skyveil --lan           # also reachable from your iPhone on the same Wi-Fi"
echo
echo "Optional: add it to your PATH:"
echo "  echo 'export PATH=\"$install_dir/bin:\$PATH\"' >> ~/.zshrc"
