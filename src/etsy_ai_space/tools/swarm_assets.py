"""Turn a design pack into ready-to-run Cursor Agent CLI prompts.

Cursor's built-in image generation (the same tool available in Cursor chat)
is included with a Cursor Pro subscription — no separate image-generation
API key needed. `cursor-agent` (the Cursor CLI) exposes that same tool in
headless/print mode, so this module builds one shell command per listing
that a user can run locally to generate art and save it into a chosen
folder (e.g. ~/SwarmAssets on their Mac).

This module only builds prompts/commands; it does not call any network
API itself.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
from pathlib import Path
from typing import Any


def slugify(text: str, *, max_len: int = 60) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug[:max_len] or "shirt-design"


def _extract_shirt_text(image_prompt: str) -> str:
    match = re.search(
        r"SHIRT TEXT \(type this exactly in Canva\):\n(.*?)\n\n---",
        image_prompt or "",
        flags=re.DOTALL,
    )
    return match.group(1).strip() if match else ""


def _extract_style(image_prompt: str) -> str:
    match = re.search(r"=== STYLE:\s*(.+?)\s*===", image_prompt or "")
    return match.group(1).strip() if match else "typography"


def build_image_description(listing: dict[str, Any]) -> str:
    """Build a natural-language image request from a listing draft."""
    image_prompt = str(listing.get("image_prompt") or "")
    shirt_text = listing.get("shirt_text") or _extract_shirt_text(image_prompt)
    style = _extract_style(image_prompt)

    if shirt_text:
        return (
            "T-shirt print design, transparent-background typography artwork, "
            f"{style} style. Centered text block reads exactly:\n"
            f"{shirt_text}\n"
            "Clean, print-ready, high contrast, no mockup, no shirt visible, "
            "no watermark — just the design artwork."
        )
    return (
        f"T-shirt print design, {style} style, print-ready artwork based on: "
        f"{listing.get('title', 'original graphic design')}. Transparent background, "
        "no mockup, no shirt visible, no watermark."
    )


def build_asset_jobs(pack_path: Path) -> list[dict[str, Any]]:
    payload = json.loads(pack_path.read_text(encoding="utf-8"))
    listings = payload.get("listings") or []
    jobs: list[dict[str, Any]] = []
    for index, listing in enumerate(listings):
        title = str(listing.get("title") or f"design-{index}")
        jobs.append(
            {
                "index": index,
                "title": title,
                "slug": slugify(title),
                "status": listing.get("status"),
                "description": build_image_description(listing),
            }
        )
    return jobs


def build_cli_commands(
    jobs: list[dict[str, Any]],
    *,
    out_dir: str = "$HOME/SwarmAssets",
    model: str | None = None,
) -> list[str]:
    """Build one `cursor-agent -p --force` command per design job."""
    commands = []
    for job in jobs:
        target = f"{out_dir}/{job['slug']}.png"
        prompt = (
            f"Generate this image: {job['description']}\n\n"
            f"Save the generated image file to exactly this path: {target} "
            "(create the parent directory first if needed, then move/copy the "
            "generated file there and confirm the final path)."
        )
        cmd = ["cursor-agent", "-p", "--force"]
        if model:
            cmd += ["--model", model]
        cmd.append(prompt)
        commands.append(shlex.join(cmd))
    return commands


def write_run_script(
    pack_path: Path,
    out_path: Path,
    *,
    out_dir: str = "$HOME/SwarmAssets",
    model: str | None = None,
) -> Path:
    jobs = build_asset_jobs(pack_path)
    commands = build_cli_commands(jobs, out_dir=out_dir, model=model)

    lines = [
        "#!/bin/bash",
        "# Generate shirt art with Cursor's built-in image generation (Cursor Pro —",
        "# no separate image-generation API key) and save it into SwarmAssets.",
        "#",
        "# Requires the Cursor CLI: curl https://cursor.com/install -fsS | bash",
        "# Then sign in once: cursor-agent login",
        "",
        "set -euo pipefail",
        f'mkdir -p "{out_dir}"',
        "",
    ]
    for job, cmd in zip(jobs, commands, strict=True):
        lines.append(f"echo '--- {job['title']} ---'")
        lines.append(cmd)
        lines.append("")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out_path.chmod(0o755)
    return out_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build a Cursor CLI script that generates shirt art with your "
            "Cursor Pro subscription (no separate image API) into SwarmAssets"
        )
    )
    parser.add_argument("pack", type=Path, help="Path to a design-pack-*.json file")
    parser.add_argument(
        "--out-script",
        type=Path,
        default=Path("generate_swarm_assets.sh"),
        help="Where to write the generated shell script",
    )
    parser.add_argument(
        "--assets-dir",
        default="$HOME/SwarmAssets",
        help="Target folder for generated images (default: $HOME/SwarmAssets)",
    )
    parser.add_argument("--model", default=None, help="Optional cursor-agent --model override")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    out_path = write_run_script(
        args.pack,
        args.out_script,
        out_dir=args.assets_dir,
        model=args.model,
    )
    print(json.dumps({"script": str(out_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
