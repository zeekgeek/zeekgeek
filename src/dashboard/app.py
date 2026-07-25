"""Launch the Etsy AI swarm Streamlit dashboard.

Usage:
    python -m dashboard.app
    python -m dashboard.app --port 8501 --refresh 3
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def _streamlit_target() -> Path:
    import etsy_ai_space.dashboard.app as swarm_app

    return Path(swarm_app.__file__).resolve()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Etsy AI swarm status dashboard")
    parser.add_argument("--port", type=int, default=8501)
    parser.add_argument("--refresh", type=int, default=3, help="Auto-refresh interval in seconds")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    app_path = _streamlit_target()
    env = os.environ.copy()
    env["ETSY_DASHBOARD_REFRESH"] = str(args.refresh)
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(app_path),
        "--server.port",
        str(args.port),
        "--server.headless",
        "true",
    ]
    return subprocess.call(cmd, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
