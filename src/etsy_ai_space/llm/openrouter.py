"""OpenRouter Chat Completions client (OpenAI-compatible HTTP)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from .env import get_openrouter_key, load_dotenv, openrouter_model

CHAT_COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"
CURSOR_BASE_URL = "https://openrouter.ai/api/v1/cursor"
DEFAULT_REFERER = "https://github.com/zeekgeek/zeekgeek"
DEFAULT_TITLE = "zeekgeek Cursor"


class OpenRouterError(RuntimeError):
    """Raised when OpenRouter returns an HTTP or payload error."""


def _headers(api_key: str) -> dict[str, str]:
    load_dotenv()
    return {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": os.environ.get("OPENROUTER_HTTP_REFERER", DEFAULT_REFERER),
        "X-Title": os.environ.get("OPENROUTER_APP_TITLE", DEFAULT_TITLE),
        "Content-Type": "application/json",
    }


def chat_completion(
    messages: list[dict[str, str]],
    *,
    api_key: str | None = None,
    model: str | None = None,
    max_tokens: int = 1200,
    temperature: float = 0.7,
    timeout: float = 60.0,
) -> dict[str, Any]:
    """POST /api/v1/chat/completions and return the parsed JSON body."""
    key = api_key or get_openrouter_key()
    if not key:
        raise OpenRouterError("OPENROUTER_API_KEY is not set")

    payload = {
        "model": openrouter_model(model),
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    request = urllib.request.Request(
        CHAT_COMPLETIONS_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers=_headers(key),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise OpenRouterError(f"OpenRouter HTTP {exc.code}: {detail[:500]}") from exc
    except urllib.error.URLError as exc:
        raise OpenRouterError(f"OpenRouter request failed: {exc.reason}") from exc

    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise OpenRouterError(f"OpenRouter returned non-JSON: {body[:200]}") from exc
    if data.get("error"):
        raise OpenRouterError(str(data["error"]))
    return data


def chat_text(
    messages: list[dict[str, str]],
    *,
    api_key: str | None = None,
    model: str | None = None,
    max_tokens: int = 1200,
    temperature: float = 0.7,
) -> str:
    """Return the first assistant message content from a chat completion."""
    data = chat_completion(
        messages,
        api_key=api_key,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise OpenRouterError(f"Unexpected OpenRouter payload: {data!r}"[:400]) from exc
    if not isinstance(content, str):
        raise OpenRouterError("OpenRouter message content was not a string")
    return content.strip()


def ping(*, api_key: str | None = None, model: str | None = None) -> dict[str, str]:
    """Send a tiny completion to verify the key and model work."""
    text = chat_text(
        [{"role": "user", "content": "Reply with exactly the token: openrouter-ok"}],
        api_key=api_key,
        model=model,
        max_tokens=16,
        temperature=0,
    )
    normalized = text.lower().replace(" ", "").replace("`", "")
    return {
        "ok": "true" if "openrouter-ok" in normalized else "false",
        "model": openrouter_model(model),
        "reply": text,
        "chat_completions_url": CHAT_COMPLETIONS_URL,
        "cursor_base_url": CURSOR_BASE_URL,
    }
