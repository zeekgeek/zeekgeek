"""Human-like scroll patterns for browser automation."""

from __future__ import annotations

import random
from typing import Any

from .delays import micro_delay


async def natural_scroll(
    page: Any,
    *,
    passes: int | None = None,
    load_more_clicks: int = 0,
) -> None:
    """Scroll search results with variable speed, pauses, and occasional back-scroll."""
    viewport = await page.evaluate(
        "() => ({ height: window.innerHeight, total: document.body.scrollHeight })"
    )
    height = max(int(viewport.get("height") or 900), 400)
    total = int(viewport.get("total") or height * 3)
    scroll_passes = passes or max(4, min(8, total // height))

    current_y = 0
    for index in range(scroll_passes):
        if random.random() < 0.12:
            delta = -random.randint(120, min(420, height // 2))
        else:
            delta = random.randint(int(height * 0.35), int(height * 0.9))

        await page.mouse.wheel(0, delta)
        current_y = max(0, current_y + delta)

        if random.random() < 0.35:
            x = random.randint(180, max(220, height))
            y = random.randint(160, min(720, height))
            await page.mouse.move(x, y)

        await micro_delay(0.45, 1.75 if index % 2 else 1.25)

        if random.random() < 0.08:
            await page.keyboard.press("PageDown")
            await micro_delay(0.3, 0.9)

    for _ in range(load_more_clicks):
        button = page.locator("button:has-text('See more'), a:has-text('See more')").first
        if await button.count() == 0:
            break
        try:
            await button.click(timeout=2500)
            await micro_delay(0.8, 1.6)
            await page.mouse.wheel(0, random.randint(300, 700))
            await micro_delay(0.4, 1.0)
        except Exception:
            break
