"""Tests for the CharacterBackend protocol and its implementations."""
from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock

from PIL import Image

from pixel_forge.backends.character import (
    ActionSheetsRequest,
    ActionSheetsResult,
    CharacterBackend,
    PortraitRequest,
    PortraitResult,
    WalkingSheetRequest,
    WalkingSheetResult,
)


class _FakeBackend:
    """Minimal struct-subtype of CharacterBackend for type checking."""

    def generate_portrait(self, req: PortraitRequest) -> PortraitResult:
        return PortraitResult(path=Path("/fake/portrait.png"))

    def generate_walking_sheet(self, req: WalkingSheetRequest) -> WalkingSheetResult:
        return WalkingSheetResult(sheet_path=Path("/fake/walk.png"), dims={})

    def generate_action_sheets(self, req: ActionSheetsRequest) -> ActionSheetsResult:
        return ActionSheetsResult(sheets={})


def test_fake_backend_satisfies_protocol():
    """A class implementing the three methods structurally satisfies CharacterBackend."""
    backend: CharacterBackend = _FakeBackend()
    result = backend.generate_portrait(
        PortraitRequest(prompt="test", reference=None, output_dir=Path("/tmp"))
    )
    assert result.path == Path("/fake/portrait.png")


# ---------------------------------------------------------------------------
# Helpers for mocking the google-genai response shape
# ---------------------------------------------------------------------------


def _make_fake_genai_response(image_bytes: bytes) -> MagicMock:
    """Build a fake google-genai response with one inline image."""
    inline_data = MagicMock()
    inline_data.mime_type = "image/png"
    inline_data.data = image_bytes
    part = MagicMock()
    part.inline_data = inline_data
    content = MagicMock()
    content.parts = [part]
    candidate = MagicMock()
    candidate.content = content
    response = MagicMock()
    response.candidates = [candidate]
    response.usage_metadata = None
    return response


# ---------------------------------------------------------------------------
# GeminiCharacterBackend tests
# ---------------------------------------------------------------------------


def test_gemini_generate_portrait(tmp_path):
    from pixel_forge.backends.gemini_character import GeminiCharacterBackend

    buf = io.BytesIO()
    Image.new("RGBA", (64, 64), (255, 0, 0, 255)).save(buf, "PNG")
    png_bytes = buf.getvalue()

    fake_response = _make_fake_genai_response(png_bytes)
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = fake_response

    backend = GeminiCharacterBackend(output_dir=tmp_path, client=mock_client)
    result = backend.generate_portrait(
        PortraitRequest(prompt="a knight", reference=None, output_dir=tmp_path)
    )
    assert result.path.exists()
    assert result.path.suffix == ".png"
    img = Image.open(result.path)
    assert img.size == (64, 64)
