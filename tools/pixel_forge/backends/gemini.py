from __future__ import annotations

import os
from pathlib import Path

import google.generativeai as genai
from PIL import Image

MODEL_NAME = "gemini-2.5-flash-image"


class GeminiBackendError(RuntimeError):
    """Raised when the Gemini backend cannot produce an image."""


class GeminiBackend:
    def __init__(self, output_dir: Path, model_name: str = MODEL_NAME) -> None:
        self.output_dir = output_dir
        self.model_name = model_name

    def _configure(self) -> None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise GeminiBackendError("GEMINI_API_KEY is not set")
        genai.configure(api_key=api_key)

    def generate(self, prompt: str, refs: list[Path], n: int) -> list[Path]:
        self._configure()
        self.output_dir.mkdir(parents=True, exist_ok=True)

        model = genai.GenerativeModel(self.model_name)
        ref_images = [Image.open(p) for p in refs]

        paths: list[Path] = []
        for i in range(n):
            contents: list = [prompt, *ref_images]
            response = model.generate_content(contents)
            image_bytes = _extract_image_bytes(response)
            if image_bytes is None:
                raise GeminiBackendError(f"No image in response for variant {i + 1}")
            dest = self.output_dir / f"gemini-v{i + 1}.png"
            dest.write_bytes(image_bytes)
            paths.append(dest.resolve())
        return paths


def _extract_image_bytes(response) -> bytes | None:
    for candidate in getattr(response, "candidates", []) or []:
        content = getattr(candidate, "content", None)
        if content is None:
            continue
        for part in getattr(content, "parts", []) or []:
            inline = getattr(part, "inline_data", None)
            if inline is None:
                continue
            mime = getattr(inline, "mime_type", "")
            if mime.startswith("image/"):
                return inline.data
    return None
