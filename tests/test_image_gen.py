"""Tests for OpenAI image generation helper."""

from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from etsy_ai_space.tools.image_gen import (
    OpenAIImageClient,
    extract_api_prompt,
    generate_image,
    load_prompt_from_design_pack,
    write_placeholder_png,
)


SAMPLE_BRIEF = """=== STYLE: definition ===

SHIRT TEXT (type this exactly in Canva):
recovery | noun
choosing yourself

--- CANVA (recommended for text shirts) ---
Type the text in Canva.

--- IDEOGRAM (good AI text rendering) ---
T-shirt design PNG, transparent background, text reads exactly: 'recovery | noun'

--- MIDJOURNEY (icons/texture only — fix text in Canva) ---
Minimal POD graphic element, NO TEXT --ar 1:1
"""


class ImageGenTests(unittest.TestCase):
    def test_extract_prefers_ideogram(self) -> None:
        prompt = extract_api_prompt(SAMPLE_BRIEF, prefer="ideogram")
        self.assertIn("T-shirt design PNG", prompt)
        self.assertNotIn("CANVA", prompt)

    def test_extract_shirt_text(self) -> None:
        prompt = extract_api_prompt(SAMPLE_BRIEF, prefer="shirt_text")
        self.assertIn("recovery | noun", prompt)

    def test_demo_writes_png(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = generate_image(
                "recovery definition shirt art",
                out_dir=Path(tmp),
                filename="demo.png",
                demo=True,
            )
            self.assertEqual(result.provider, "demo")
            self.assertTrue(result.path.exists())
            self.assertTrue(result.path.read_bytes().startswith(b"\x89PNG"))

    def test_load_prompt_from_design_pack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack = Path(tmp) / "design-pack.json"
            pack.write_text(
                json.dumps(
                    {
                        "listings": [
                            {"title": "Recovery Definition Shirt", "image_prompt": SAMPLE_BRIEF}
                        ]
                    }
                ),
                encoding="utf-8",
            )
            prompt, listing = load_prompt_from_design_pack(pack, index=0)
            self.assertIn("T-shirt design PNG", prompt)
            self.assertEqual(listing["title"], "Recovery Definition Shirt")

    def test_openai_client_decodes_b64(self) -> None:
        tiny = write_placeholder_png(Path(tempfile.mkdtemp()) / "src.png", label="src")
        b64 = base64.b64encode(tiny.read_bytes()).decode("ascii")
        fake_payload = json.dumps({"data": [{"b64_json": b64, "revised_prompt": "clean prompt"}]}).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = fake_payload
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = False

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.png"
            with patch("etsy_ai_space.tools.image_gen.urllib.request.urlopen", return_value=mock_resp):
                client = OpenAIImageClient(api_key="sk-test", model="gpt-image-1")
                result = client.generate("test prompt", out_path=out)
            self.assertTrue(out.exists())
            self.assertEqual(result.provider, "openai")
            self.assertEqual(result.revised_prompt, "clean prompt")


if __name__ == "__main__":
    unittest.main()
