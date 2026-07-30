"""Connect to an image generation API for POD shirt art drafts."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import struct
import urllib.error
import urllib.request
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


OPENAI_IMAGES_URL = "https://api.openai.com/v1/images/generations"
DEFAULT_MODEL = "gpt-image-1"
DEFAULT_SIZE = "1024x1536"  # portrait — closer to print-file aspect


@dataclass
class ImageGenResult:
    path: Path
    provider: str
    model: str
    prompt: str
    revised_prompt: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "provider": self.provider,
            "model": self.model,
            "prompt": self.prompt,
            "revised_prompt": self.revised_prompt,
        }


def extract_api_prompt(image_prompt: str, *, prefer: str = "ideogram") -> str:
    """Pull the best machine-usable prompt section from a design brief."""
    text = image_prompt or ""
    sections = {
        "ideogram": re.search(
            r"--- IDEOGRAM[^\n]*---\n(.+?)(?:\n---|\Z)",
            text,
            flags=re.DOTALL | re.IGNORECASE,
        ),
        "midjourney": re.search(
            r"--- MIDJOURNEY[^\n]*---\n(.+?)(?:\n---|\Z)",
            text,
            flags=re.DOTALL | re.IGNORECASE,
        ),
        "shirt_text": re.search(
            r"SHIRT TEXT \(type this exactly in Canva\):\n(.+?)\n\n---",
            text,
            flags=re.DOTALL,
        ),
    }
    prefer = prefer.lower().strip()
    order = [prefer, "ideogram", "midjourney", "shirt_text"]
    seen: set[str] = set()
    for key in order:
        if key in seen:
            continue
        seen.add(key)
        match = sections.get(key)
        if match:
            prompt = match.group(1).strip()
            if prompt:
                return prompt
    return text.strip()


def load_prompt_from_design_pack(pack_path: Path, *, index: int = 0) -> tuple[str, dict[str, Any]]:
    payload = json.loads(pack_path.read_text(encoding="utf-8"))
    listings = payload.get("listings") or []
    if not listings:
        raise SystemExit(f"No listings found in design pack: {pack_path}")
    if index < 0 or index >= len(listings):
        raise SystemExit(f"Listing index {index} out of range (0–{len(listings) - 1})")
    listing = listings[index]
    raw = str(listing.get("image_prompt") or listing.get("shirt_text") or "")
    return extract_api_prompt(raw), listing


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def write_placeholder_png(path: Path, label: str = "DEMO") -> Path:
    """Write a tiny valid PNG so --demo works offline without Pillow."""
    path.parent.mkdir(parents=True, exist_ok=True)
    width, height = 64, 64
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter none
        for x in range(width):
            # soft teal swatch for recovery niche branding demos
            raw.extend((32, 120 if (x + y) % 8 else 150, 140, 255))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n"
    png += _png_chunk(b"IHDR", ihdr)
    png += _png_chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += _png_chunk(b"IEND", b"")
    path.write_bytes(png)
    side = path.with_suffix(".txt")
    side.write_text(f"demo placeholder for: {label}\n", encoding="utf-8")
    return path


class OpenAIImageClient:
    """Minimal OpenAI Images API client (stdlib urllib — no openai package required)."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        model: str = DEFAULT_MODEL,
        size: str = DEFAULT_SIZE,
        timeout: float = 120.0,
    ) -> None:
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.model = model
        self.size = size
        self.timeout = timeout

    def generate(self, prompt: str, *, out_path: Path, transparent: bool = True) -> ImageGenResult:
        if not self.api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. Export it, or use --demo to write a placeholder PNG."
            )

        body: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "n": 1,
            "size": self.size,
        }
        # GPT image models support transparent PNG backgrounds for print files.
        if self.model.startswith("gpt-image"):
            body["output_format"] = "png"
            if transparent:
                body["background"] = "transparent"
        else:
            body["response_format"] = "b64_json"

        request = urllib.request.Request(
            OPENAI_IMAGES_URL,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenAI Images API error {exc.code}: {detail}") from exc

        data = (payload.get("data") or [{}])[0]
        b64 = data.get("b64_json")
        if not b64:
            raise RuntimeError(f"OpenAI response missing b64_json: {payload}")

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(base64.b64decode(b64))
        return ImageGenResult(
            path=out_path,
            provider="openai",
            model=self.model,
            prompt=prompt,
            revised_prompt=data.get("revised_prompt"),
        )


def generate_image(
    prompt: str,
    *,
    out_dir: Path | None = None,
    filename: str | None = None,
    demo: bool = False,
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
    size: str = DEFAULT_SIZE,
    transparent: bool = True,
) -> ImageGenResult:
    """Generate one image via OpenAI, or a local placeholder in demo mode."""
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    out_dir = out_dir or Path.cwd() / "etsy_ai_space" / "exports" / "images"
    out_path = out_dir / (filename or f"shirt-art-{stamp}.png")

    if demo:
        write_placeholder_png(out_path, label=prompt[:80])
        return ImageGenResult(
            path=out_path,
            provider="demo",
            model="placeholder",
            prompt=prompt,
        )

    client = OpenAIImageClient(api_key=api_key, model=model, size=size)
    return client.generate(prompt, out_path=out_path, transparent=transparent)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate POD shirt art via OpenAI Images API (or --demo placeholder)",
    )
    parser.add_argument("prompt", nargs="?", default=None, help="Image prompt text")
    parser.add_argument(
        "--from-pack",
        type=Path,
        default=None,
        help="design-pack-*.json path; uses listing image_prompt",
    )
    parser.add_argument("--index", type=int, default=0, help="Listing index inside design pack")
    parser.add_argument("--prefer", default="ideogram", choices=["ideogram", "midjourney", "shirt_text"])
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--filename", default=None)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--size", default=DEFAULT_SIZE)
    parser.add_argument("--demo", action="store_true", help="Write local placeholder PNG (no API)")
    parser.add_argument("--no-transparent", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    listing: dict[str, Any] | None = None

    if args.from_pack:
        prompt, listing = load_prompt_from_design_pack(args.from_pack, index=args.index)
        prompt = extract_api_prompt(
            str(listing.get("image_prompt") or prompt),
            prefer=args.prefer,
        )
    elif args.prompt:
        prompt = args.prompt
    else:
        parser.error("Provide a prompt or --from-pack PATH")

    result = generate_image(
        prompt,
        out_dir=args.out_dir,
        filename=args.filename,
        demo=args.demo,
        model=args.model,
        size=args.size,
        transparent=not args.no_transparent,
    )
    payload = result.to_dict()
    if listing:
        payload["source_title"] = listing.get("title")
        payload["source_status"] = listing.get("status")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
