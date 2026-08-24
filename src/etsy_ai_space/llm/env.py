"""Load local .env files without overriding already-set environment variables."""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_MODEL = "openai/gpt-4o"
ENV_FILENAMES = (".env", ".env.local")


def load_dotenv(*, root: Path | None = None) -> Path | None:
    """Populate os.environ from the first existing .env file. Returns the path used."""
    search_root = root or Path.cwd()
    for name in ENV_FILENAMES:
        path = search_root / name
        if not path.is_file():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if not key or key in os.environ:
                continue
            os.environ[key] = value.strip().strip("'").strip('"')
        return path
    return None


def get_openrouter_key() -> str | None:
    load_dotenv()
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    return key or None


def openrouter_model(configured: str | None = None) -> str:
    """Prefer OPENROUTER_MODEL, then an OpenRouter slug, then gpt-4o."""
    load_dotenv()
    env_model = os.environ.get("OPENROUTER_MODEL", "").strip()
    if env_model:
        return env_model
    if configured and "/" in configured:
        return configured
    return DEFAULT_MODEL
