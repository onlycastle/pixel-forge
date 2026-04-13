from pathlib import Path

from pixel_forge.backends.gemini import GeminiBackend


def test_gemini_backend_writes_n_png_files(tmp_path: Path, monkeypatch) -> None:
    class FakeResponse:
        def __init__(self, png_bytes: bytes) -> None:
            self.candidates = [
                type(
                    "Candidate",
                    (),
                    {
                        "content": type(
                            "Content",
                            (),
                            {
                                "parts": [
                                    type(
                                        "Part",
                                        (),
                                        {
                                            "inline_data": type(
                                                "InlineData",
                                                (),
                                                {"data": png_bytes, "mime_type": "image/png"},
                                            )()
                                        },
                                    )()
                                ]
                            },
                        )()
                    },
                )()
            ]

    fake_bytes = Path("tests/fixtures/good-tile.png").read_bytes()

    calls: list[dict] = []

    class FakeModel:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def generate_content(self, contents):
            calls.append({"contents": contents})
            return FakeResponse(fake_bytes)

    import pixel_forge.backends.gemini as gemini_mod

    monkeypatch.setattr(gemini_mod.genai, "GenerativeModel", FakeModel)
    monkeypatch.setattr(gemini_mod.genai, "configure", lambda **_: None)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")

    backend = GeminiBackend(output_dir=tmp_path)
    paths = backend.generate(
        prompt="draw a thing",
        refs=[Path("tests/fixtures/good-tile.png")],
        n=3,
    )

    assert len(paths) == 3
    for p in paths:
        assert p.exists()
        assert p.read_bytes() == fake_bytes
    assert len(calls) == 3


def test_gemini_backend_raises_when_api_key_missing(tmp_path: Path, monkeypatch) -> None:
    import pixel_forge.backends.gemini as gemini_mod

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    # Prevent actual SDK configuration regardless
    monkeypatch.setattr(gemini_mod.genai, "configure", lambda **_: None)

    backend = gemini_mod.GeminiBackend(output_dir=tmp_path)

    import pytest as _pytest
    with _pytest.raises(gemini_mod.GeminiBackendError, match="GEMINI_API_KEY"):
        backend.generate(prompt="anything", refs=[], n=1)


def test_gemini_backend_raises_when_response_has_no_image(tmp_path: Path, monkeypatch) -> None:
    import pixel_forge.backends.gemini as gemini_mod

    class EmptyResponse:
        # No candidates at all — _extract_image_bytes returns None
        candidates: list = []

    class FakeModel:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def generate_content(self, contents):
            return EmptyResponse()

    monkeypatch.setattr(gemini_mod.genai, "GenerativeModel", FakeModel)
    monkeypatch.setattr(gemini_mod.genai, "configure", lambda **_: None)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")

    backend = gemini_mod.GeminiBackend(output_dir=tmp_path)

    import pytest as _pytest
    with _pytest.raises(gemini_mod.GeminiBackendError, match="No image in response"):
        backend.generate(prompt="anything", refs=[], n=2)


def test_gemini_backend_accepts_empty_refs_list(tmp_path: Path, monkeypatch) -> None:
    """Text-only prompts (no reference images) should work and produce N files."""
    import pixel_forge.backends.gemini as gemini_mod

    fake_bytes = Path("tests/fixtures/good-tile.png").read_bytes()

    class OneImagePart:
        inline_data = type(
            "InlineData",
            (),
            {"data": fake_bytes, "mime_type": "image/png"},
        )()

    class FakeContent:
        parts = [OneImagePart()]

    class FakeCandidate:
        content = FakeContent()

    class FakeResponse:
        candidates = [FakeCandidate()]

    class FakeModel:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def generate_content(self, contents):
            return FakeResponse()

    monkeypatch.setattr(gemini_mod.genai, "GenerativeModel", FakeModel)
    monkeypatch.setattr(gemini_mod.genai, "configure", lambda **_: None)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")

    backend = gemini_mod.GeminiBackend(output_dir=tmp_path)
    paths = backend.generate(prompt="text only", refs=[], n=2)

    assert len(paths) == 2
    for p in paths:
        assert p.exists()
        assert p.is_absolute()
        assert p.read_bytes() == fake_bytes
