"""Randomized, human-like delays for scraper pacing."""

from __future__ import annotations

import asyncio
import random


def jittered_range(min_seconds: float, max_seconds: float) -> float:
    """Return a uniform random delay between min and max seconds."""
    if min_seconds > max_seconds:
        min_seconds, max_seconds = max_seconds, min_seconds
    return random.uniform(min_seconds, max_seconds)


async def human_delay(min_seconds: float = 1.5, max_seconds: float = 4.5) -> float:
    """Sleep for a randomized interval and return the chosen duration."""
    delay = jittered_range(min_seconds, max_seconds)
    await asyncio.sleep(delay)
    return delay


async def micro_delay(min_seconds: float = 0.3, max_seconds: float = 1.2) -> float:
    """Short pause between low-risk actions (scroll, hover)."""
    delay = jittered_range(min_seconds, max_seconds)
    await asyncio.sleep(delay)
    return delay
