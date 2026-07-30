"""Resolve scrape mode for the agentic loop (demo / playwright / BrowserClaw CDP)."""

from __future__ import annotations

from dataclasses import dataclass

from .browser_connect import cdp_setup_hint, discover_cdp_url, probe_cdp_url, resolve_cdp_url

SCRAPE_MODES = frozenset({"demo", "playwright", "browserclaw"})


@dataclass
class ScrapeSettings:
    use_demo: bool
    scrape_mode: str
    cdp_url: str | None = None
    reuse_browser_tab: bool = False
    cdp_fallback: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "use_demo": self.use_demo,
            "scrape_mode": self.scrape_mode,
            "cdp_url": self.cdp_url,
            "reuse_browser_tab": self.reuse_browser_tab,
            "cdp_fallback": self.cdp_fallback,
        }


def resolve_scrape_settings(
    *,
    demo: bool = True,
    scrape_mode: str = "demo",
    cdp_url: str | None = None,
    reuse_browser_tab: bool = False,
    cdp_auto_discover: bool = True,
    cdp_fallback_demo: bool = True,
) -> ScrapeSettings:
    """Pick demo, headless Playwright, or BrowserClaw CDP attach for a cycle."""
    mode = scrape_mode.lower().strip() or "browserclaw"
    if mode not in SCRAPE_MODES:
        raise ValueError(f"Unknown scrape_mode {scrape_mode!r}; use demo, playwright, or browserclaw")

    if demo:
        return ScrapeSettings(use_demo=True, scrape_mode="demo")

    if mode == "playwright":
        return ScrapeSettings(use_demo=False, scrape_mode="playwright")

    # browserclaw — attach Playwright to a running Chromium CDP session
    candidates: list[str] = []
    if cdp_url:
        candidates.append(resolve_cdp_url(cdp_url))
    else:
        try:
            candidates.append(resolve_cdp_url(None))
        except ValueError:
            pass
        if cdp_auto_discover:
            discovered = discover_cdp_url()
            if discovered:
                candidates.append(discovered)

    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if probe_cdp_url(candidate):
            return ScrapeSettings(
                use_demo=False,
                scrape_mode="browserclaw",
                cdp_url=candidate,
                reuse_browser_tab=reuse_browser_tab,
            )

    if cdp_fallback_demo:
        return ScrapeSettings(
            use_demo=True,
            scrape_mode="demo",
            cdp_fallback=True,
        )

    raise RuntimeError(cdp_setup_hint())
