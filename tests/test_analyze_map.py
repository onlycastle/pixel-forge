"""Tests for analyze_map() in the Gemini text backend."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image


# ---------------------------------------------------------------------------
# Helpers – build a Gemini-shaped fake response that returns text
# ---------------------------------------------------------------------------
def _make_text_response(text: str):
    """Return a fake Gemini response object whose first part carries *text*."""
    return type(
        "Response",
        (),
        {
            "candidates": [
                type(
                    "Candidate",
                    (),
                    {
                        "content": type(
                            "Content",
                            (),
                            {
                                "parts": [
                                    type("Part", (), {"text": text})()
                                ]
                            },
                        )()
                    },
                )()
            ]
        },
    )()


GOOD_JSON = json.dumps(
    {
        "map_description": "A sunny beach with palm trees",
        "suggestions": [
            {
                "name": "beach umbrella",
                "prompt": "pixel-art beach umbrella, centered, transparent background",
                "footprint": [2, 2],
                "category": "furniture",
            },
            {
                "name": "sandcastle",
                "prompt": "pixel-art sandcastle, centered, transparent background",
                "footprint": [1, 1],
                "category": "decor",
            },
        ],
    }
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture()
def tiny_png(tmp_path: Path) -> Path:
    """Create a 4x4 RGBA PNG so analyze_map has something to open."""
    p = tmp_path / "map.png"
    Image.new("RGBA", (4, 4), (0, 0, 0, 0)).save(p)
    return p


@pytest.fixture()
def _patch_genai(monkeypatch):
    """Patch google.generativeai inside the gemini_text module.

    Because gemini_text uses a local import, we need to patch the module
    that gets imported at call time. We inject a fake module into sys.modules.
    """
    import types
    import sys

    fake_genai = types.ModuleType("google.generativeai")
    fake_genai.configure = lambda **_: None  # type: ignore[attr-defined]

    # FakeModel is set per-test via the returned dict
    _state: dict = {"model_cls": None}

    class _FakeModelFactory:
        """Callable that delegates to whatever model_cls the test plugs in."""

        def __call__(self, *args, **kwargs):
            return _state["model_cls"](*args, **kwargs)

    fake_genai.GenerativeModel = _FakeModelFactory()  # type: ignore[attr-defined]

    # Patch sys.modules so `import google.generativeai as genai` resolves
    monkeypatch.setitem(sys.modules, "google.generativeai", fake_genai)
    monkeypatch.setitem(sys.modules, "google", types.ModuleType("google"))
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")

    return _state


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
class TestAnalyzeMap:
    def test_analyze_map_returns_suggestions(
        self, tiny_png: Path, _patch_genai, monkeypatch
    ):
        """Happy path: Gemini returns clean JSON, analyze_map parses it."""

        class FakeModel:
            def __init__(self, *a, **kw):
                pass

            def generate_content(self, contents):
                return _make_text_response(GOOD_JSON)

        _patch_genai["model_cls"] = FakeModel

        from pixel_forge.backends.gemini_text import analyze_map

        result = analyze_map(
            map_image_path=str(tiny_png),
            prose="Beach vibes",
            palette_hex=["#f0c040", "#20a0e0"],
        )

        assert isinstance(result, dict)
        assert "map_description" in result
        assert "suggestions" in result
        assert len(result["suggestions"]) == 2
        assert result["suggestions"][0]["name"] == "beach umbrella"

    def test_analyze_map_strips_code_fences(
        self, tiny_png: Path, _patch_genai, monkeypatch
    ):
        """Gemini sometimes wraps output in ```json ... ```. We strip that."""
        wrapped = f"```json\n{GOOD_JSON}\n```"

        class FakeModel:
            def __init__(self, *a, **kw):
                pass

            def generate_content(self, contents):
                return _make_text_response(wrapped)

        _patch_genai["model_cls"] = FakeModel

        from pixel_forge.backends.gemini_text import analyze_map

        result = analyze_map(
            map_image_path=str(tiny_png),
            prose="Beach vibes",
            palette_hex=["#f0c040"],
        )

        assert result["map_description"] == "A sunny beach with palm trees"
        assert len(result["suggestions"]) == 2

    def test_analyze_map_raises_on_bad_json(
        self, tiny_png: Path, _patch_genai, monkeypatch
    ):
        """Non-JSON responses should raise GeminiTextBackendError."""

        class FakeModel:
            def __init__(self, *a, **kw):
                pass

            def generate_content(self, contents):
                return _make_text_response("Sorry, I can't do that.")

        _patch_genai["model_cls"] = FakeModel

        from pixel_forge.backends.gemini_text import analyze_map
        from pixel_forge.backends.gemini_text import GeminiTextBackendError

        with pytest.raises(GeminiTextBackendError, match="parse"):
            analyze_map(
                map_image_path=str(tiny_png),
                prose="Beach vibes",
                palette_hex=["#aabbcc"],
            )
