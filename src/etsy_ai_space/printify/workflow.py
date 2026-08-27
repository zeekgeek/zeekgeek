"""Printify draft-push workflow with a human submit gate.

Flow:
1. ``push`` — upload design + create Printify product as **draft** (never publish)
2. ``pending`` — list products waiting for you to submit/publish in Printify
3. ``wait`` — poll until you mark them submitted (or Printify shows them published)
4. ``mark-submitted`` — record that you finished submitting in the Printify UI
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..models import iso_time
from ..pipeline.state_tracker import SwarmStateTracker
from .client import PrintifyClient, PrintifyError

LOGGER = logging.getLogger(__name__)

DEFAULT_CONFIG = Path.cwd() / "etsy_ai_space" / "printify.yaml"
DEFAULT_QUEUE = Path.cwd() / "etsy_ai_space" / "pipeline" / "printify_queue.json"


@dataclass
class PrintifyConfig:
    shop_id: int | None = None
    blueprint_id: int = 706
    print_provider_id: int | None = None
    default_price_cents: int = 2699
    enabled_colors: list[str] = field(default_factory=lambda: ["Black", "Pepper", "Charcoal", "Navy"])
    enabled_sizes: list[str] = field(default_factory=lambda: ["S", "M", "L", "XL", "2XL"])
    print_position: str = "front"
    print_scale: float = 1.0
    print_x: float = 0.5
    print_y: float = 0.45
    auto_publish: bool = False
    wait_timeout_seconds: float = 0.0
    wait_poll_seconds: float = 30.0


def load_printify_config(path: Path | None = None) -> PrintifyConfig:
    config_path = path or DEFAULT_CONFIG
    if not config_path.exists():
        return PrintifyConfig()
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    shop_id = raw.get("shop_id")
    provider = raw.get("print_provider_id")
    return PrintifyConfig(
        shop_id=int(shop_id) if shop_id is not None else None,
        blueprint_id=int(raw.get("blueprint_id", 706)),
        print_provider_id=int(provider) if provider is not None else None,
        default_price_cents=int(raw.get("default_price_cents", 2699)),
        enabled_colors=[str(c) for c in (raw.get("enabled_colors") or ["Black"])],
        enabled_sizes=[str(s) for s in (raw.get("enabled_sizes") or ["S", "M", "L", "XL", "2XL"])],
        print_position=str(raw.get("print_position", "front")),
        print_scale=float(raw.get("print_scale", 1.0)),
        print_x=float(raw.get("print_x", 0.5)),
        print_y=float(raw.get("print_y", 0.45)),
        auto_publish=bool(raw.get("auto_publish", False)),
        wait_timeout_seconds=float(raw.get("wait_timeout_seconds", 0)),
        wait_poll_seconds=float(raw.get("wait_poll_seconds", 30)),
    )


def default_queue_path() -> Path:
    return DEFAULT_QUEUE


def load_queue(path: Path | None = None) -> dict[str, Any]:
    queue_path = path or default_queue_path()
    if not queue_path.exists():
        return {"updated_at": iso_time(), "items": []}
    return json.loads(queue_path.read_text(encoding="utf-8"))


def save_queue(queue: dict[str, Any], path: Path | None = None) -> None:
    queue_path = path or default_queue_path()
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    queue["updated_at"] = iso_time()
    tmp = queue_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(queue, indent=2), encoding="utf-8")
    tmp.replace(queue_path)


def load_listing_package(package_dir: Path) -> dict[str, Any]:
    listing_path = package_dir / "listing.json"
    if not listing_path.exists():
        raise FileNotFoundError(f"No listing.json in {package_dir}")
    payload = json.loads(listing_path.read_text(encoding="utf-8"))
    images_dir = package_dir / "images"
    print_file = ""
    preferred_names = [
        "01-printify-print.png",
        "06-printify-transparent.png",
        "03-print-ready-graphic.png",
        "01-hero-black-lifestyle.png",
    ]
    for name in preferred_names:
        candidate = images_dir / name
        if candidate.exists():
            print_file = str(candidate)
            break
    if not print_file and images_dir.exists():
        pngs = sorted(images_dir.glob("*.png"))
        if pngs:
            print_file = str(pngs[0])
    if not print_file:
        raise FileNotFoundError(f"No print image found in {images_dir}")
    return {
        "package_dir": str(package_dir),
        "listing_number": payload.get("listing_number"),
        "title": payload["title"],
        "description": payload.get("description") or "",
        "tags": payload.get("tags") or [],
        "price_usd": float(payload.get("price_usd") or payload.get("price") or 26.99),
        "print_file": print_file,
        "printify": payload.get("printify") or {},
    }


def filter_variants(
    variants: list[dict[str, Any]],
    *,
    colors: list[str],
    sizes: list[str],
    price_cents: int,
) -> list[dict[str, Any]]:
    """Select enabled color/size variants and attach retail price."""
    color_set = {c.lower() for c in colors}
    size_set = {s.lower() for s in sizes}
    selected: list[dict[str, Any]] = []
    for variant in variants:
        options = variant.get("options") or {}
        # options may be dict {color,size} or nested differently
        color = str(options.get("color") or options.get("Color") or "").strip()
        size = str(options.get("size") or options.get("Size") or "").strip()
        title = str(variant.get("title") or "")
        if not color and "/" in title:
            parts = [p.strip() for p in title.split("/")]
            if len(parts) >= 2:
                color, size = parts[0], parts[1]
        if color_set and color.lower() not in color_set:
            # allow partial match e.g. "Black" in "Solid Black"
            if not any(c in color.lower() for c in color_set):
                continue
        if size_set and size.lower() not in size_set:
            continue
        selected.append(
            {
                "id": int(variant["id"]),
                "price": price_cents,
                "is_enabled": True,
            }
        )
    return selected


def build_product_payload(
    listing: dict[str, Any],
    *,
    config: PrintifyConfig,
    image_id: str,
    variants: list[dict[str, Any]],
) -> dict[str, Any]:
    variant_ids = [int(v["id"]) for v in variants]
    price_cents = int(round(float(listing.get("price_usd") or 26.99) * 100))
    if price_cents <= 0:
        price_cents = config.default_price_cents
    # Ensure prices on variants match listing
    for item in variants:
        item["price"] = price_cents
    return {
        "title": str(listing["title"])[:200],
        "description": str(listing.get("description") or ""),
        "tags": [str(tag)[:30] for tag in (listing.get("tags") or [])[:13]],
        "blueprint_id": config.blueprint_id,
        "print_provider_id": config.print_provider_id,
        "variants": variants,
        "print_areas": [
            {
                "variant_ids": variant_ids,
                "placeholders": [
                    {
                        "position": config.print_position,
                        "images": [
                            {
                                "id": image_id,
                                "x": config.print_x,
                                "y": config.print_y,
                                "scale": config.print_scale,
                                "angle": 0,
                            }
                        ],
                    }
                ],
            }
        ],
    }


class PrintifyWorkflow:
    """Push listing packages to Printify as drafts and wait for human submit."""

    def __init__(
        self,
        config: PrintifyConfig,
        *,
        client: PrintifyClient | None = None,
        queue_path: Path | None = None,
        tracker: SwarmStateTracker | None = None,
    ) -> None:
        self.config = config
        self.client = client
        self.queue_path = queue_path or default_queue_path()
        self.tracker = tracker or SwarmStateTracker()

    def _require_client(self) -> PrintifyClient:
        if self.client is None:
            self.client = PrintifyClient()
        return self.client

    def _require_shop_and_provider(self) -> tuple[int, int]:
        if self.config.shop_id is None:
            raise PrintifyError(
                "printify.yaml shop_id is not set. Run: python3 -m etsy_ai_space printify discover --shops"
            )
        if self.config.print_provider_id is None:
            raise PrintifyError(
                "printify.yaml print_provider_id is not set. Run: "
                "python3 -m etsy_ai_space printify discover --providers"
            )
        if self.config.auto_publish:
            raise PrintifyError(
                "auto_publish=true is not supported. This workflow always waits for human submit."
            )
        return int(self.config.shop_id), int(self.config.print_provider_id)

    def discover_shops(self) -> list[dict[str, Any]]:
        client = self._require_client()
        return [
            {"id": shop.get("id"), "title": shop.get("title"), "sales_channel": shop.get("sales_channel")}
            for shop in client.shops()
        ]

    def discover_providers(self) -> list[dict[str, Any]]:
        client = self._require_client()
        return [
            {"id": provider.get("id"), "title": provider.get("title")}
            for provider in client.print_providers(self.config.blueprint_id)
        ]

    def discover_variants_summary(self) -> dict[str, Any]:
        client = self._require_client()
        if self.config.print_provider_id is None:
            raise PrintifyError("Set print_provider_id before listing variants")
        variants = client.variants(self.config.blueprint_id, int(self.config.print_provider_id))
        colors = sorted(
            {
                str((v.get("options") or {}).get("color") or "").strip()
                for v in variants
                if (v.get("options") or {}).get("color")
            }
        )
        sizes = sorted(
            {
                str((v.get("options") or {}).get("size") or "").strip()
                for v in variants
                if (v.get("options") or {}).get("size")
            }
        )
        return {
            "blueprint_id": self.config.blueprint_id,
            "print_provider_id": self.config.print_provider_id,
            "variant_count": len(variants),
            "colors": colors,
            "sizes": sizes,
        }

    def push_package(self, package_dir: Path, *, dry_run: bool = False) -> dict[str, Any]:
        listing = load_listing_package(package_dir)
        price_cents = int(round(float(listing["price_usd"]) * 100)) or self.config.default_price_cents

        if dry_run:
            missing = []
            if self.config.shop_id is None:
                missing.append("shop_id")
            if self.config.print_provider_id is None:
                missing.append("print_provider_id")
            return {
                "dry_run": True,
                "action": "create_draft",
                "shop_id": self.config.shop_id,
                "blueprint_id": self.config.blueprint_id,
                "print_provider_id": self.config.print_provider_id,
                "title": listing["title"],
                "print_file": listing["print_file"],
                "price_cents": price_cents,
                "enabled_colors": self.config.enabled_colors,
                "enabled_sizes": self.config.enabled_sizes,
                "missing_config": missing,
                "next_step": (
                    "Set missing_config in printify.yaml + PRINTIFY_API_TOKEN, push for real, "
                    "then submit in Printify UI while `printify wait` runs"
                ),
            }

        shop_id, provider_id = self._require_shop_and_provider()

        client = self._require_client()
        with self.tracker.agent_activity("Uploader", "Pushing Printify draft"):
            upload = client.upload_image(Path(listing["print_file"]))
            image_id = str(upload.get("id") or upload.get("image_id") or "")
            if not image_id:
                raise PrintifyError(f"Upload succeeded but no image id returned: {upload}")

            catalog_variants = client.variants(self.config.blueprint_id, provider_id)
            selected = filter_variants(
                catalog_variants,
                colors=self.config.enabled_colors,
                sizes=self.config.enabled_sizes,
                price_cents=price_cents,
            )
            if not selected:
                raise PrintifyError(
                    "No variants matched enabled_colors/enabled_sizes. "
                    "Run printify discover --variants and update printify.yaml."
                )

            payload = build_product_payload(
                listing,
                config=self.config,
                image_id=image_id,
                variants=selected,
            )
            product = client.create_product(shop_id, payload)

        product_id = str(product.get("id") or "")
        item = {
            "id": product_id,
            "shop_id": shop_id,
            "title": listing["title"],
            "package_dir": listing["package_dir"],
            "listing_number": listing.get("listing_number"),
            "print_file": listing["print_file"],
            "image_id": image_id,
            "status": "awaiting_human_submit",
            "created_at": iso_time(),
            "submitted_at": None,
            "printify_url": f"https://printify.com/app/product-details/{product_id}" if product_id else "",
            "dashboard_hint": "Open Printify → Products → open this draft → Publish / Submit to your store",
        }
        queue = load_queue(self.queue_path)
        items = list(queue.get("items") or [])
        items = [existing for existing in items if existing.get("id") != product_id]
        items.append(item)
        queue["items"] = items
        save_queue(queue, self.queue_path)
        self.tracker.log(f"Printify draft created — awaiting human submit: {listing['title'][:80]}")
        return {
            "created": True,
            "product_id": product_id,
            "status": "awaiting_human_submit",
            "item": item,
            "message": "Draft created in Printify. Review and submit when ready, then run: printify wait",
        }

    def push_packages(self, package_dirs: list[Path], *, dry_run: bool = False) -> dict[str, Any]:
        results = []
        for directory in package_dirs:
            results.append(self.push_package(directory, dry_run=dry_run))
        return {
            "count": len(results),
            "results": results,
            "pending": self.pending(),
        }

    def pending(self) -> list[dict[str, Any]]:
        queue = load_queue(self.queue_path)
        return [
            item
            for item in (queue.get("items") or [])
            if item.get("status") == "awaiting_human_submit"
        ]

    def mark_submitted(self, product_id: str) -> dict[str, Any]:
        queue = load_queue(self.queue_path)
        found = None
        for item in queue.get("items") or []:
            if str(item.get("id")) == str(product_id):
                item["status"] = "submitted_by_human"
                item["submitted_at"] = iso_time()
                found = item
                break
        if found is None:
            raise PrintifyError(f"Product {product_id} not found in printify queue")
        save_queue(queue, self.queue_path)
        self.tracker.log(f"Marked Printify product submitted: {product_id}")
        self.tracker.bump_metric("successful_uploads", 1)
        return found

    def mark_all_submitted(self) -> list[dict[str, Any]]:
        pending = self.pending()
        return [self.mark_submitted(str(item["id"])) for item in pending]

    def refresh_remote_status(self) -> list[dict[str, Any]]:
        """If Printify reports a product visible/published, mark it submitted."""
        client = self._require_client()
        shop_id, _provider = self._require_shop_and_provider()
        queue = load_queue(self.queue_path)
        updated: list[dict[str, Any]] = []
        for item in queue.get("items") or []:
            if item.get("status") != "awaiting_human_submit":
                continue
            product_id = str(item.get("id") or "")
            if not product_id:
                continue
            try:
                product = client.get_product(shop_id, product_id)
            except PrintifyError as exc:
                LOGGER.warning("Could not refresh product %s: %s", product_id, exc)
                continue
            visible = bool(product.get("visible"))
            external = product.get("external") or {}
            published = visible or bool(external.get("id") or external.get("handle"))
            if published:
                item["status"] = "submitted_by_human"
                item["submitted_at"] = iso_time()
                item["remote_visible"] = visible
                updated.append(item)
        if updated:
            save_queue(queue, self.queue_path)
        return updated

    def wait_for_submit(self, *, timeout_seconds: float | None = None, poll_seconds: float | None = None) -> dict[str, Any]:
        """Block until the awaiting queue is empty (human submit or remote publish)."""
        timeout = self.config.wait_timeout_seconds if timeout_seconds is None else timeout_seconds
        poll = self.config.wait_poll_seconds if poll_seconds is None else poll_seconds
        started = time.time()
        self.tracker.set_agent("Uploader", "Waiting for human Printify submit", health="healthy")
        self.tracker.log("Printify wait started — submit drafts in the Printify dashboard when ready")

        while True:
            # Prefer local marks; also detect remote publish when API available
            try:
                self.refresh_remote_status()
            except PrintifyError:
                pass
            pending = self.pending()
            payload = {
                "awaiting_count": len(pending),
                "pending": pending,
                "elapsed_seconds": round(time.time() - started, 1),
                "instruction": (
                    "Open each printify_url, review the draft, then Publish/Submit to your store. "
                    "After submitting, run: python3 -m etsy_ai_space printify mark-submitted <product_id> "
                    "or: python3 -m etsy_ai_space printify mark-submitted --all"
                ),
            }
            if not pending:
                self.tracker.set_agent("Uploader", "Idle")
                self.tracker.log("All Printify drafts have been submitted")
                return {"done": True, **payload}

            print(json.dumps({"status": "waiting_for_human_submit", **payload}, indent=2), flush=True)

            if timeout and timeout > 0 and (time.time() - started) >= timeout:
                self.tracker.set_agent("Uploader", "Idle")
                return {"done": False, "timed_out": True, **payload}

            time.sleep(max(poll, 5.0))


def _collect_packages(args: argparse.Namespace) -> list[Path]:
    packages: list[Path] = []
    if args.package:
        packages.extend(Path(p) for p in args.package)
    if args.all_listings:
        root = Path.cwd() / "etsy_ai_space" / "exports"
        packages.extend(sorted(root.glob("listing-*/")))
    # de-dupe
    unique: list[Path] = []
    seen: set[str] = set()
    for path in packages:
        key = str(path.resolve())
        if key not in seen and path.is_dir():
            seen.add(key)
            unique.append(path)
    return unique


async def _cli(args: argparse.Namespace) -> int:
    # sync CLI — Printify uses blocking HTTP; wrap for etsy_ai_space async dispatch
    return cmd_printify(args)


def cmd_printify(args: argparse.Namespace) -> int:
    config = load_printify_config(args.config)
    workflow = PrintifyWorkflow(config, queue_path=args.queue)

    if args.printify_command == "discover":
        if args.shops:
            print(json.dumps(workflow.discover_shops(), indent=2))
            return 0
        if args.providers:
            print(json.dumps(workflow.discover_providers(), indent=2))
            return 0
        if args.variants:
            print(json.dumps(workflow.discover_variants_summary(), indent=2))
            return 0
        print(json.dumps({"shops": workflow.discover_shops(), "providers": workflow.discover_providers()}, indent=2))
        return 0

    if args.printify_command == "push":
        packages = _collect_packages(args)
        if not packages:
            print(
                "No packages specified. Use --package PATH or --all-listings",
                file=__import__("sys").stderr,
            )
            return 1
        result = workflow.push_packages(packages, dry_run=args.dry_run)
        print(json.dumps(result, indent=2))
        return 0

    if args.printify_command == "pending":
        print(json.dumps({"pending": workflow.pending()}, indent=2))
        return 0

    if args.printify_command == "wait":
        result = workflow.wait_for_submit(
            timeout_seconds=args.timeout,
            poll_seconds=args.poll,
        )
        print(json.dumps(result, indent=2))
        return 0 if result.get("done") else 2

    if args.printify_command == "mark-submitted":
        if args.all:
            updated = workflow.mark_all_submitted()
            print(json.dumps({"submitted": updated}, indent=2))
            return 0
        if not args.product_id:
            print("Provide product_id or --all", file=__import__("sys").stderr)
            return 1
        item = workflow.mark_submitted(args.product_id)
        print(json.dumps(item, indent=2))
        return 0

    print(f"Unknown printify command: {args.printify_command}", file=__import__("sys").stderr)
    return 1
