"""Minimal Printify REST client (stdlib urllib — no extra deps)."""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


class PrintifyError(RuntimeError):
    """Raised when the Printify API returns an error."""


class PrintifyClient:
    """Thin wrapper around https://api.printify.com/v1."""

    def __init__(self, api_token: str | None = None, *, base_url: str = "https://api.printify.com/v1") -> None:
        token = api_token or os.environ.get("PRINTIFY_API_TOKEN", "").strip()
        if not token:
            raise PrintifyError(
                "PRINTIFY_API_TOKEN is not set. Create a token in Printify → Account → Connections."
            )
        self.api_token = token
        self.base_url = base_url.rstrip("/")

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
            "Authorization": f"Bearer {self.api_token}",
            "User-Agent": "etsy-ai-space-printify/1.0",
            "Accept": "application/json",
        }
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = response.read().decode("utf-8")
                if not body:
                    return {}
                return json.loads(body)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise PrintifyError(f"Printify {method} {path} failed ({exc.code}): {detail}") from exc
        except urllib.error.URLError as exc:
            raise PrintifyError(f"Printify network error: {exc}") from exc

    def shops(self) -> list[dict[str, Any]]:
        result = self._request("GET", "/shops.json")
        return list(result) if isinstance(result, list) else list(result.get("data") or [])

    def blueprints(self) -> list[dict[str, Any]]:
        result = self._request("GET", "/catalog/blueprints.json")
        return list(result) if isinstance(result, list) else []

    def print_providers(self, blueprint_id: int) -> list[dict[str, Any]]:
        result = self._request("GET", f"/catalog/blueprints/{blueprint_id}/print_providers.json")
        return list(result) if isinstance(result, list) else []

    def variants(self, blueprint_id: int, print_provider_id: int) -> list[dict[str, Any]]:
        result = self._request(
            "GET",
            f"/catalog/blueprints/{blueprint_id}/print_providers/{print_provider_id}/variants.json",
        )
        if isinstance(result, dict) and "variants" in result:
            return list(result["variants"])
        return list(result) if isinstance(result, list) else []

    def upload_image(self, image_path: Path, *, file_name: str | None = None) -> dict[str, Any]:
        path = Path(image_path)
        if not path.exists():
            raise PrintifyError(f"Image not found: {path}")
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        payload = {
            "file_name": file_name or path.name,
            "contents": encoded,
        }
        # Mime hint is unused by API but kept for local validation
        _mime = mimetypes.guess_type(path.name)[0] or "image/png"
        return self._request("POST", "/uploads/images.json", payload=payload)

    def create_product(self, shop_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/shops/{shop_id}/products.json", payload=payload)

    def get_product(self, shop_id: int, product_id: str) -> dict[str, Any]:
        return self._request("GET", f"/shops/{shop_id}/products/{product_id}.json")

    def list_products(self, shop_id: int, *, page: int = 1, limit: int = 50) -> dict[str, Any]:
        query = urllib.parse.urlencode({"page": page, "limit": limit})
        return self._request("GET", f"/shops/{shop_id}/products.json?{query}")
