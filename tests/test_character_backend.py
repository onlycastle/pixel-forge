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


# ---------------------------------------------------------------------------
# _chroma_key and _stitch_direction_strips tests
# ---------------------------------------------------------------------------


def _make_strip(color, w=192, h=192):
    """Create a fake strip: colored character block on gray bg."""
    img = Image.new("RGBA", (w, h), (140, 140, 140, 255))
    for x in range(w // 4, 3 * w // 4):
        for y in range(h // 4, 3 * h // 4):
            img.putpixel((x, y), color + (255,))
    return img


def test_chroma_key_removes_background():
    from pixel_forge.backends.gemini_character import _chroma_key

    img = Image.new("RGBA", (10, 10), (140, 140, 140, 255))
    img.putpixel((5, 5), (255, 0, 0, 255))
    result = _chroma_key(img)
    # Background pixels should be transparent
    assert result.getpixel((0, 0))[3] == 0
    # Character pixel should be opaque
    assert result.getpixel((5, 5)) == (255, 0, 0, 255)


def test_stitch_direction_strips():
    from pixel_forge.backends.gemini_character import _stitch_direction_strips

    strips = {
        "right": _make_strip((255, 0, 0)),
        "up": _make_strip((0, 255, 0)),
        "left": _make_strip((0, 0, 255)),
        "down": _make_strip((255, 255, 0)),
    }
    sheet = _stitch_direction_strips(strips, cell_w=32, cell_h=64, frames_per_dir=6)
    assert sheet.size == (1792, 192)
    assert sheet.mode == "RGBA"

    # Row 0 col 0 = right preview: should have red pixels
    cell_00 = sheet.crop((0, 0, 32, 64))
    px = list(cell_00.getdata())
    red_px = [p for p in px if p[0] > 200 and p[1] < 50 and p[2] < 50 and p[3] > 200]
    assert len(red_px) > 0, "right preview cell should contain red character pixels"

    # Row 0 col 1 = up preview: should have green pixels
    cell_01 = sheet.crop((32, 0, 64, 64))
    px = list(cell_01.getdata())
    green_px = [p for p in px if p[1] > 200 and p[0] < 50 and p[3] > 200]
    assert len(green_px) > 0, "up preview cell should contain green character pixels"

    # Background should be transparent
    cell_00_px = list(cell_00.getdata())
    transparent_px = [p for p in cell_00_px if p[3] < 10]
    assert len(transparent_px) > 0, "background should be chroma-keyed to transparent"

    # Walk row col 12 = left walk strip start: should have blue pixels
    cell_walk_left = sheet.crop((12 * 32, 2 * 64, 13 * 32, 3 * 64))
    px = list(cell_walk_left.getdata())
    blue_px = [p for p in px if p[2] > 200 and p[0] < 50 and p[3] > 200]
    assert len(blue_px) > 0, "left walk cell should contain blue character pixels"
