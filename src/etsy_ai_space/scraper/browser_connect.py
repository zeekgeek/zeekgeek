"""Connect Playwright to an existing Chromium instance (BrowserClaw / CDP)."""

from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import urlparse

DEFAULT_CDP_URL = "http://127.0.0.1:9222"
CDP_ENV_VARS = ("BROWSERCLAW_CDP_URL", "BROWSER_CDP_URL", "CDP_URL")


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
