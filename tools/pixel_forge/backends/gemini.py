from __future__ import annotations

import os
from pathlib import Path

import google.generativeai as genai
from PIL import Image

from pixel_forge.usage import UsageRecord

MODEL_NAME = "gemini-2.5-flash-image"


class GeminiBackendError(RuntimeError):
    """Raised when the Gemini backend cannot produce an image."""


class GeminiBackend:
    def __init__(self, output_dir: Path, model_name: str = MODEL_NAME) -> None:
        self.output_dir = output_dir
        self.model_name = model_name
        # Populated at the end of every `generate()` call with the sum
        # of token usage across that call's N variants. Callers that
        # want per-variant accounting should invoke generate() once per
        # variant; the bundle CLI does this because pipes 1 and 2 each
        # map to their own generate() invocations.
        self.last_usage: UsageRecord | None = None

    def _configure(self) -> None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise GeminiBackendError("GEMINI_API_KEY is not set")
        genai.configure(api_key=api_key)

    def generate(self, prompt: str, refs: list[Path], n: int) -> list[Path]:
        self._configure()
        self.output_dir.mkdir(parents=True, exist_ok=True)

        model = genai.GenerativeModel(self.model_name)
        # Eagerly load ref images into memory so file handles close immediately
        # and all N variants see byte-identical ref data.
        ref_images: list[Image.Image] = []
        for p in refs:
            with Image.open(p) as im:
                im.load()
                ref_images.append(im.copy())

        usage = UsageRecord(model=self.model_name)
        paths: list[Path] = []
        for i in range(n):
            contents: list = [prompt, *ref_images]
            response = model.generate_content(contents)
            _accumulate_usage(usage, response)
            image_bytes = _extract_image_bytes(response)
            if image_bytes is None:
                raise GeminiBackendError(f"No image in response for variant {i + 1}")
            dest = self.output_dir / f"gemini-v{i + 1}.png"
            dest.write_bytes(image_bytes)
            paths.append(dest.resolve())
        self.last_usage = usage
        return paths


def _accumulate_usage(usage: UsageRecord, response) -> None:
    """Pull token counts off a Gemini response's usage_metadata.

    Gemini's response shape: `response.usage_metadata.prompt_token_count`,
    `candidates_token_count`, `total_token_count`. We defensively read
    via getattr so a missing field (older SDK, stubbed response) becomes
    zero instead of an AttributeError — token accounting is a nice-to-
    have, not a blocker for image generation itself.
    """
    meta = getattr(response, "usage_metadata", None)
    if meta is None:
        return
    usage.prompt_tokens += int(getattr(meta, "prompt_token_count", 0) or 0)
    usage.output_tokens += int(getattr(meta, "candidates_token_count", 0) or 0)
    usage.total_tokens += int(getattr(meta, "total_token_count", 0) or 0)
    usage.call_count += 1


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
