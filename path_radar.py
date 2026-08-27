#!/usr/bin/env python3
"""Run Path Radar from the repo root.

On macOS Sequoia the easiest launch is to double-click ``path_radar.command``.
You can also run this file directly after Python 3.11+ and FastAPI are available:

    python3 path_radar.py
    python3 path_radar.py --demo
    python3 path_radar.py --open one.one.one.one
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from trace_radar.__main__ import main  # noqa: E402

if __name__ == "__main__":
    main()
