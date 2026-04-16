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


def test_resolve_gemini_backend(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-test")
    from pixel_forge.backends import resolve_character_backend

    backend = resolve_character_backend("gemini", tmp_path)
    assert type(backend).__name__ == "GeminiCharacterBackend"


def test_resolve_pixellab_backend(tmp_path):
    from pixel_forge.backends import resolve_character_backend

    backend = resolve_character_backend("pixellab", tmp_path)
    assert type(backend).__name__ == "PixelLabCharacterBackend"


def test_resolve_unknown_backend_raises(tmp_path):
    import pytest

    from pixel_forge.backends import resolve_character_backend

    with pytest.raises(ValueError, match="unknown character backend"):
        resolve_character_backend("nonexistent", tmp_path)


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


# ---------------------------------------------------------------------------
# PixelLabCharacterBackend tests
# ---------------------------------------------------------------------------


def _mock_pixellab_image(w=64, h=64):
    """Build a mock PixelLab image object whose .pil_image() returns a PIL Image."""
    pil_img = Image.new("RGBA", (w, h), (100, 100, 200, 255))
    mock_img = MagicMock()
    mock_img.pil_image.return_value = pil_img
    return mock_img


def test_pixellab_generate_portrait(tmp_path):
    from pixel_forge.backends.pixellab_character import PixelLabCharacterBackend

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.image = _mock_pixellab_image()
    mock_response.usage = MagicMock(usd=0)
    mock_client.generate_image_pixflux.return_value = mock_response

    backend = PixelLabCharacterBackend(output_dir=tmp_path, client=mock_client)
    result = backend.generate_portrait(
        PortraitRequest(prompt="a knight", reference=None, output_dir=tmp_path)
    )
    assert result.path.exists()
    assert result.path.suffix == ".png"
    img = Image.open(result.path)
    assert img.size == (64, 64)
    # Verify generate_image_pixflux was called with south direction for portrait
    call_kwargs = mock_client.generate_image_pixflux.call_args
    assert call_kwargs.kwargs["direction"] == "south"


def test_pixellab_generate_walking_sheet(tmp_path):
    """Walking sheet: generate east base, rotate x3, animate x4, convert pack."""
    from pixel_forge.backends.pixellab_character import PixelLabCharacterBackend

    mock_client = MagicMock()

    # generate_image_pixflux → east-facing base
    base_resp = MagicMock()
    base_resp.image = _mock_pixellab_image()
    base_resp.usage = MagicMock(usd=0)
    mock_client.generate_image_pixflux.return_value = base_resp

    # rotate → north, west, south
    rotate_resp = MagicMock()
    rotate_resp.image = _mock_pixellab_image()
    rotate_resp.usage = MagicMock(usd=0)
    mock_client.rotate.return_value = rotate_resp

    # animate_with_text → 6 frames per direction (returns 4, pipeline extends)
    anim_resp = MagicMock()
    anim_resp.images = [_mock_pixellab_image() for _ in range(4)]
    anim_resp.usage = MagicMock(usd=0)
    mock_client.animate_with_text.return_value = anim_resp

    backend = PixelLabCharacterBackend(output_dir=tmp_path, client=mock_client)
    result = backend.generate_walking_sheet(
        WalkingSheetRequest(prompt="a knight", reference=None, output_dir=tmp_path)
    )

    # Sheet should exist
    assert result.sheet_path.exists()
    assert result.sheet_path.suffix == ".png"

    # Dims should match PERSON_PREMADE layout
    assert result.dims["cell"] == [32, 64]
    assert result.dims["cols"] == 56
    assert result.dims["rows"] == 3
    assert result.dims["direction_order"] == ["right", "up", "left", "down"]
    assert result.dims["frames_per_dir"] == 6

    # Verify API call counts: 1 generate + 3 rotates + 4 animates
    assert mock_client.generate_image_pixflux.call_count == 1
    assert mock_client.rotate.call_count == 3
    assert mock_client.animate_with_text.call_count == 4


def test_pixellab_generate_action_sheets(tmp_path):
    """Action sheets: PixelLab has no action endpoint, returns empty dict."""
    from pixel_forge.backends.pixellab_character import PixelLabCharacterBackend

    mock_client = MagicMock()
    backend = PixelLabCharacterBackend(output_dir=tmp_path, client=mock_client)
    result = backend.generate_action_sheets(
        ActionSheetsRequest(prompt="a knight", reference=None, output_dir=tmp_path)
    )
    assert result.sheets == {}


def test_pixellab_portrait_with_reference(tmp_path):
    """Portrait generation should pass reference image to generate_image_pixflux."""
    from pixel_forge.backends.pixellab_character import PixelLabCharacterBackend

    # Create a reference image file
    ref_path = tmp_path / "ref.png"
    Image.new("RGBA", (64, 64), (255, 0, 0, 255)).save(ref_path)

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.image = _mock_pixellab_image()
    mock_response.usage = MagicMock(usd=0)
    mock_client.generate_image_pixflux.return_value = mock_response

    backend = PixelLabCharacterBackend(output_dir=tmp_path, client=mock_client)
    result = backend.generate_portrait(
        PortraitRequest(prompt="a knight", reference=ref_path, output_dir=tmp_path)
    )
    assert result.path.exists()
    # When reference is provided, style_image kwarg should be passed
    call_kwargs = mock_client.generate_image_pixflux.call_args.kwargs
    assert "style_image" in call_kwargs
