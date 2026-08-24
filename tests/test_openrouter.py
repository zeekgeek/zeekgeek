"""Tests for the OpenRouter Chat Completions client."""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from etsy_ai_space.llm.env import get_openrouter_key, load_dotenv, openrouter_model
from etsy_ai_space.llm.openrouter import OpenRouterError, chat_text, ping
from etsy_ai_space.pipeline.orchestrator import ManagerAgent


def _completion_body(text: str, model: str = "openai/gpt-4o") -> bytes:
    payload = {
        "id": "gen-test",
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}}],
    }
    return json.dumps(payload).encode("utf-8")


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None


class OpenRouterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._saved_key = os.environ.pop("OPENROUTER_API_KEY", None)
        self._saved_model = os.environ.pop("OPENROUTER_MODEL", None)

    def tearDown(self) -> None:
        if self._saved_key is None:
            os.environ.pop("OPENROUTER_API_KEY", None)
        else:
            os.environ["OPENROUTER_API_KEY"] = self._saved_key
        if self._saved_model is None:
            os.environ.pop("OPENROUTER_MODEL", None)
        else:
            os.environ["OPENROUTER_MODEL"] = self._saved_model

    def test_load_dotenv_does_not_override_existing(self) -> None:
        os.environ["OPENROUTER_API_KEY"] = "from-env"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("OPENROUTER_API_KEY=from-file\nOPENROUTER_MODEL=openai/gpt-4o\n", encoding="utf-8")
            loaded = load_dotenv(root=Path(tmp))
            self.assertEqual(loaded, path)
            self.assertEqual(os.environ["OPENROUTER_API_KEY"], "from-env")
            self.assertEqual(os.environ.get("OPENROUTER_MODEL"), "openai/gpt-4o")

    def test_openrouter_model_prefers_env(self) -> None:
        os.environ["OPENROUTER_MODEL"] = "moonshotai/kimi-k2"
        self.assertEqual(openrouter_model("openai/gpt-4o"), "moonshotai/kimi-k2")

    def test_chat_text_sends_bearer_and_returns_content(self) -> None:
        os.environ["OPENROUTER_API_KEY"] = "sk-or-test"
        captured: dict[str, object] = {}

        def fake_urlopen(request, timeout=60.0):  # noqa: ANN001
            captured["url"] = request.full_url
            captured["authorization"] = request.headers.get("Authorization")
            captured["content_type"] = request.headers.get("Content-type") or request.headers.get("Content-Type")
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return _FakeResponse(_completion_body("hello from openrouter"))

        with patch("etsy_ai_space.llm.openrouter.urllib.request.urlopen", fake_urlopen):
            text = chat_text([{"role": "user", "content": "hi"}], model="openai/gpt-4o")

        self.assertEqual(text, "hello from openrouter")
        self.assertEqual(captured["url"], "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(captured["authorization"], "Bearer sk-or-test")
        self.assertEqual(captured["body"]["model"], "openai/gpt-4o")
        self.assertEqual(captured["body"]["messages"][0]["content"], "hi")

    def test_chat_text_raises_on_http_error(self) -> None:
        os.environ["OPENROUTER_API_KEY"] = "sk-or-test"
        error = HTTPError(
            "https://openrouter.ai/api/v1/chat/completions",
            401,
            "Unauthorized",
            hdrs={},  # type: ignore[arg-type]
            fp=io.BytesIO(b'{"error":{"message":"User not found."}}'),
        )
        with patch("etsy_ai_space.llm.openrouter.urllib.request.urlopen", side_effect=error):
            with self.assertRaises(OpenRouterError) as ctx:
                chat_text([{"role": "user", "content": "hi"}])
        self.assertIn("401", str(ctx.exception))

    def test_ping_detects_ok_token(self) -> None:
        os.environ["OPENROUTER_API_KEY"] = "sk-or-test"

        def fake_urlopen(request, timeout=60.0):  # noqa: ANN001
            return _FakeResponse(_completion_body("openrouter-ok"))

        with patch("etsy_ai_space.llm.openrouter.urllib.request.urlopen", fake_urlopen):
            result = ping()
        self.assertEqual(result["ok"], "true")
        self.assertEqual(result["reply"], "openrouter-ok")
        self.assertEqual(result["cursor_base_url"], "https://openrouter.ai/api/v1/cursor")

    async def test_manager_uses_openrouter_when_key_set(self) -> None:
        os.environ["OPENROUTER_API_KEY"] = "sk-or-test"
        payload = json.dumps(
            {
                "concepts": [
                    {"concept_name": "OR Concept 1", "hook": "h1", "angle": "a1"},
                    {"concept_name": "OR Concept 2", "hook": "h2", "angle": "a2"},
                ]
            }
        )
        with patch("etsy_ai_space.llm.openrouter.chat_text", return_value=payload):
            manager = ManagerAgent()
            concepts = await manager.generate_concepts_with_claude(
                "retro cat shirt",
                [{"title": "Retro Cat Shirt", "tags": ["cat"], "etsy_listing_id": "1"}],
                count=2,
            )
        self.assertEqual(manager.model, "openai/gpt-4o")
        self.assertEqual([c.concept_name for c in concepts], ["OR Concept 1", "OR Concept 2"])

    def test_missing_key_raises(self) -> None:
        with self.assertRaises(OpenRouterError):
            chat_text([{"role": "user", "content": "hi"}])

    def test_get_openrouter_key_none_when_unset(self) -> None:
        self.assertIsNone(get_openrouter_key())


if __name__ == "__main__":
    unittest.main()
