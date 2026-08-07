"""Minimal Printify REST client (stdlib urllib — no extra deps)."""

from __future__ import annotations

import base64
import json
import logging
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.printify.com/v1"
DEFAULT_USER_AGENT = "etsy-ai-space/0.1 (+https://github.com/local/etsy-ai-space)"


class PrintifyError(RuntimeError):
    """Raised when the Printify API returns an error or credentials are missing."""

    def __init__(self, message: str, *, status: int | None = None, body: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.body = body


class PrintifyClient:
    """Thin wrapper around Printify v1 endpoints used for product publish."""

    def __init__(
        self,
        token: str | None = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: float = 60.0,
    ) -> None:
        self.token = (token or os.environ.get("PRINTIFY_API_TOKEN") or "").strip()
        if not self.token:
            raise PrintifyError(
                "PRINTIFY_API_TOKEN is not set. Create a Personal Access Token in "
                "Printify → Account → Connections / API and export it."
            )
        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent
        self.timeout = timeout

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        data = None
        headers = {
            "Authorization": f"Bearer {self.token}",
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        }
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
                if not raw:
                    return {}
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            try:
                body = json.loads(body_text) if body_text else None
            except json.JSONDecodeError:
                body = body_text
            raise PrintifyError(
                f"Printify {method} {path} failed ({exc.code}): {body_text[:500]}",
                status=exc.code,
                body=body,
            ) from exc
        except urllib.error.URLError as exc:
            raise PrintifyError(f"Printify network error for {method} {path}: {exc}") from exc

    def list_shops(self) -> list[dict[str, Any]]:
        result = self._request("GET", "/shops.json")
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and isinstance(result.get("data"), list):
            return list(result["data"])
        return []

    def list_blueprint_providers(self, blueprint_id: int) -> list[dict[str, Any]]:
        result = self._request("GET", f"/catalog/blueprints/{blueprint_id}/print_providers.json")
        return result if isinstance(result, list) else []

    def list_variants(self, blueprint_id: int, print_provider_id: int) -> list[dict[str, Any]]:
        result = self._request(
            "GET",
            f"/catalog/blueprints/{blueprint_id}/print_providers/{print_provider_id}/variants.json",
        )
        if isinstance(result, dict) and isinstance(result.get("variants"), list):
            return list(result["variants"])
        if isinstance(result, list):
            return result
        return []

    def upload_image_file(self, path: Path, *, file_name: str | None = None) -> dict[str, Any]:
        image_path = Path(path)
        if not image_path.exists():
            raise PrintifyError(f"Image file not found: {image_path}")
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        payload = {
            "file_name": file_name or image_path.name,
            "contents": encoded,
        }
        result = self._request("POST", "/uploads/images.json", payload=payload)
        if not isinstance(result, dict) or not result.get("id"):
            raise PrintifyError(f"Unexpected upload response: {result!r}")
        LOGGER.info("Uploaded image %s → Printify id=%s", image_path.name, result["id"])
        return result

    def create_product(self, shop_id: int | str, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._request("POST", f"/shops/{shop_id}/products.json", payload=payload)
        if not isinstance(result, dict) or not result.get("id"):
            raise PrintifyError(f"Unexpected create-product response: {result!r}")
        LOGGER.info("Created Printify product id=%s title=%r", result["id"], result.get("title"))
        return result

    def publish_product(
        self,
        shop_id: int | str,
        product_id: str,
        *,
        title: bool = True,
        description: bool = True,
        images: bool = True,
        variants: bool = True,
        tags: bool = True,
        key_features: bool = True,
        shipping_template: bool = True,
    ) -> dict[str, Any]:
        payload = {
            "title": title,
            "description": description,
            "images": images,
            "variants": variants,
            "tags": tags,
            "keyFeatures": key_features,
            "shipping_template": shipping_template,
        }
        result = self._request(
            "POST",
            f"/shops/{shop_id}/products/{product_id}/publish.json",
            payload=payload,
        )
        LOGGER.info("Published Printify product id=%s to connected sales channel", product_id)
        return result if isinstance(result, dict) else {}
