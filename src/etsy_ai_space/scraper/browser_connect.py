"""Connect Playwright to an existing Chromium instance (BrowserClaw / CDP)."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse

DEFAULT_CDP_URL = "http://127.0.0.1:9222"
CDP_ENV_VARS = ("BROWSERCLAW_CDP_URL", "BROWSER_CDP_URL", "CDP_URL")
COMMON_CDP_PORTS = (9222, 9223, 9224, 9225, 9226, 9229)


def resolve_cdp_url(explicit: str | None = None) -> str:
    """Resolve CDP endpoint from CLI flag, then environment, then default."""
    if explicit:
        return normalize_cdp_url(explicit)
    for key in CDP_ENV_VARS:
        value = os.environ.get(key, "").strip()
        if value:
            return normalize_cdp_url(value)
    return DEFAULT_CDP_URL


def normalize_cdp_url(raw: str) -> str:
    """Accept http(s), ws(s), host:port, or bare port for connect_over_cdp."""
    value = raw.strip()
    if not value:
        raise ValueError("CDP URL cannot be empty")

    if value.isdigit():
        return f"http://127.0.0.1:{value}"

    if re.fullmatch(r"\d{1,5}", value):
        return f"http://127.0.0.1:{value}"

    if "://" not in value:
        # host:port shorthand, e.g. 127.0.0.1:9222
        if re.fullmatch(r"[\w.-]+:\d{1,5}", value):
            return f"http://{value}"
        raise ValueError(f"Unrecognized CDP URL format: {raw!r}")

    parsed = urlparse(value)
    scheme = parsed.scheme.lower()
    if scheme in {"http", "https", "ws", "wss"}:
        return value
    raise ValueError(f"Unsupported CDP URL scheme: {parsed.scheme!r}")


def cdp_http_base(cdp_url: str) -> str:
    """Return http://host:port for CDP JSON endpoints."""
    normalized = normalize_cdp_url(cdp_url)
    parsed = urlparse(normalized)
    if parsed.scheme in {"ws", "wss"}:
        # ws://127.0.0.1:9222/devtools/browser/... -> http://127.0.0.1:9222
        port = parsed.port or 9222
        host = parsed.hostname or "127.0.0.1"
        return f"http://{host}:{port}"
    if parsed.scheme in {"http", "https"}:
        return normalized.rstrip("/")
    raise ValueError(f"Cannot derive HTTP base from {cdp_url!r}")


def probe_cdp_url(cdp_url: str, *, timeout: float = 1.5) -> dict[str, Any] | None:
    """Return Chrome /json/version payload when CDP is reachable."""
    base = cdp_http_base(cdp_url)
    request = urllib.request.Request(f"{base}/json/version")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
        return None


def discover_cdp_url(ports: tuple[int, ...] = COMMON_CDP_PORTS) -> str | None:
    """Scan common BrowserClaw / Chrome debugging ports on localhost."""
    for port in ports:
        url = f"http://127.0.0.1:{port}"
        if probe_cdp_url(url):
            return url
    return None


def cdp_setup_hint() -> str:
    return (
        "No Chrome/BrowserClaw CDP endpoint found on localhost.\n\n"
        "1) Open a NEW Terminal window (keep it open).\n"
        "2) Start Chrome with remote debugging:\n\n"
        '   /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome \\\n'
        "     --remote-debugging-port=9222 \\\n"
        "     --remote-debugging-address=127.0.0.1 \\\n"
        '     --user-data-dir=\"$HOME/browserclaw-profile\"\n\n'
        "3) Verify:\n\n"
        "   curl -s http://127.0.0.1:9222/json/version\n\n"
        "4) Re-run this command.\n"
    )


async def connect_over_cdp(playwright: Any, cdp_url: str) -> Any:
    """Attach Playwright to a running Chromium-based browser."""
    endpoint = normalize_cdp_url(cdp_url)
    return await playwright.chromium.connect_over_cdp(endpoint)


async def acquire_page(browser: Any, *, reuse_existing: bool = False) -> tuple[Any, Any, bool]:
    """Return (browser, page, owns_page). Creates a tab when none is suitable."""
    contexts = browser.contexts
    if not contexts:
        context = await browser.new_context()
        page = await context.new_page()
        return browser, page, True

    context = contexts[0]
    if reuse_existing and context.pages:
        for page in context.pages:
            url = page.url or ""
            if url and url != "about:blank":
                return browser, page, False
        return browser, context.pages[0], False

    page = await context.new_page()
    return browser, page, True
