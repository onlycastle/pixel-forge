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
