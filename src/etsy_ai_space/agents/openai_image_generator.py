"""OpenAI GPT Image generation for print-ready transparent PNGs.

Used by autopilot's n8n-style path (WF2): concept → image → SEO already in draft.
Falls back to a tiny placeholder PNG when ``provider=demo`` (offline / no API key).
"""

from __future__ import annotations

import base64
import json
import logging
import os
import struct
import urllib.error
import urllib.request
import zlib
from pathlib import Path
from typing import Any

from ..db import StoreDatabase
from .cursor_image_generator import (
    default_images_dir,
    list_pending_image_jobs,
    prepare_image_prompt,
    save_generated_image,
)

LOGGER = logging.getLogger(__name__)

OPENAI_IMAGES_URL = "https://api.openai.com/v1/images/generations"
DEFAULT_MODEL = "gpt-image-1"
DEFAULT_SIZE = "1024x1024"
DEFAULT_QUALITY = "medium"


class ImageGenerationError(RuntimeError):
    """Raised when image generation fails."""


def _chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def placeholder_png_bytes(*, width: int = 64, height: int = 64) -> bytes:
    """Return a minimal RGBA PNG (transparent) for demo/offline mode."""
    raw = b""
    for _y in range(height):
        raw += b"\x00" + (b"\x00\x00\x00\x00" * width)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(raw, 9))
        + _chunk(b"IEND", b"")
    )


class OpenAIImageClient:
    """Minimal OpenAI Images API client (stdlib urllib)."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        model: str = DEFAULT_MODEL,
        size: str = DEFAULT_SIZE,
        quality: str = DEFAULT_QUALITY,
        timeout: float = 180.0,
    ) -> None:
        self.api_key = (api_key or os.environ.get("OPENAI_API_KEY") or "").strip()
        if not self.api_key:
            raise ImageGenerationError(
                "OPENAI_API_KEY is not set. Export it to enable auto image generation."
            )
        self.model = model
        self.size = size
        self.quality = quality
        self.timeout = timeout

    def generate_png(self, prompt: str) -> bytes:
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "n": 1,
            "size": self.size,
            "quality": self.quality,
            "output_format": "png",
            "background": "transparent",
        }
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            OPENAI_IMAGES_URL,
            data=data,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "etsy-ai-space/0.1",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            raise ImageGenerationError(
                f"OpenAI images API failed ({exc.code}): {err_body[:500]}"
            ) from exc
        except urllib.error.URLError as exc:
            raise ImageGenerationError(f"OpenAI images network error: {exc}") from exc

        items = body.get("data") if isinstance(body, dict) else None
        if not items:
            raise ImageGenerationError(f"Unexpected OpenAI images response: {body!r}")
        item = items[0]
        b64 = item.get("b64_json")
        if b64:
            return base64.b64decode(b64)
        url = item.get("url")
        if url:
            with urllib.request.urlopen(url, timeout=self.timeout) as img_resp:
                return img_resp.read()
        raise ImageGenerationError(f"No image payload in OpenAI response: {item!r}")


def resolve_image_provider(requested: str, *, demo_mode: bool) -> str:
    """Pick openai vs demo based on config, keys, and demo scrape mode."""
    provider = (requested or "openai").strip().lower()
    if provider == "demo":
        return "demo"
    if demo_mode and not os.environ.get("OPENAI_API_KEY"):
        return "demo"
    if provider == "openai" and not os.environ.get("OPENAI_API_KEY"):
        LOGGER.warning("OPENAI_API_KEY missing; falling back to demo placeholder images")
        return "demo"
    return provider


def generate_images_for_pending_drafts(
    db: StoreDatabase,
    *,
    limit: int = 2,
    provider: str = "openai",
    model: str = DEFAULT_MODEL,
    size: str = DEFAULT_SIZE,
    quality: str = DEFAULT_QUALITY,
    images_dir: Path | None = None,
    client: OpenAIImageClient | None = None,
    statuses: list[str] | None = None,
) -> dict[str, Any]:
    """Generate and attach images for drafts that still need artwork."""
    # Orchestrator export marks drafts ``exported``; also cover pre-export statuses.
    target_statuses = statuses or [
        "approved_for_export",
        "exported",
        "pending_review",
    ]
    jobs: list[dict[str, Any]] = []
    seen: set[int] = set()
    for status in target_statuses:
        for job in list_pending_image_jobs(db, status=status):
            draft_id = int(job["id"])
            if draft_id in seen:
                continue
            seen.add(draft_id)
            jobs.append(job)
    jobs.sort(key=lambda item: int(item["id"]))
    jobs = jobs[: max(0, limit)]
    if not jobs:
        return {"generated": 0, "results": [], "provider": provider}

    dest_dir = images_dir or default_images_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    openai_client = client

    for job in jobs:
        draft_id = int(job["id"])
        prompt = str(job.get("cursor_prompt") or prepare_image_prompt(job))
        tmp_path = dest_dir / f".tmp-draft-{draft_id}.png"
        try:
            if provider == "demo":
                png = placeholder_png_bytes()
            else:
                if openai_client is None:
                    openai_client = OpenAIImageClient(
                        model=model,
                        size=size,
                        quality=quality,
                    )
                png = openai_client.generate_png(prompt)
            tmp_path.write_bytes(png)
            dest = save_generated_image(
                draft_id,
                tmp_path,
                db,
                images_dir=dest_dir,
                force=True,
            )
            results.append(
                {
                    "draft_id": draft_id,
                    "title": job.get("title"),
                    "image_path": str(dest),
                    "provider": provider,
                }
            )
            LOGGER.info("Generated image for draft %s via %s → %s", draft_id, provider, dest)
        finally:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

    return {"generated": len(results), "results": results, "provider": provider}
