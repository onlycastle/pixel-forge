"""Gemini 3.1 Flash character backend using the google-genai SDK.

Implements portrait and action-sheet pipes from the CharacterBackend
protocol. Walking-sheet (per-direction strips) is deferred to Task 4.
"""
from __future__ import annotations

import os
from pathlib import Path

from google import genai
from google.genai import types as gtypes
from PIL import Image

from pixel_forge.backends.character import (
    ActionSheetsRequest,
    ActionSheetsResult,
    PortraitRequest,
    PortraitResult,
    WalkingSheetRequest,
    WalkingSheetResult,
)

MODEL_ID = "gemini-3.1-flash-image-preview"
TIMEOUT_MS = 90_000
MAX_ATTEMPTS = 2


def _extract_image_bytes(response) -> bytes | None:
    """Walk the google-genai response tree and return the first image's bytes."""
    for cand in getattr(response, "candidates", []) or []:
        content = getattr(cand, "content", None)
        if content is None:
            continue
        for part in getattr(content, "parts", []) or []:
            inline = getattr(part, "inline_data", None)
            if inline is None:
                continue
            mime = getattr(inline, "mime_type", "") or ""
            if mime.startswith("image/"):
                return inline.data
    return None


class GeminiCharacterBackend:
    """Character backend backed by Gemini 3.1 Flash via the google-genai SDK."""

    def __init__(
        self,
        output_dir: Path,
        client: genai.Client | None = None,
        model_id: str = MODEL_ID,
    ) -> None:
        self.output_dir = output_dir
        self.model_id = model_id
        if client is not None:
            self._client = client
        else:
            api_key = os.environ.get("GEMINI_API_KEY", "")
            self._client = genai.Client(api_key=api_key)

    # ------------------------------------------------------------------
    # Internal helper
    # ------------------------------------------------------------------

    def _call(
        self,
        prompt: str,
        ref: Image.Image | None,
        aspect: str = "1:1",
    ) -> bytes:
        """Send a single image-generation request with timeout and retry."""
        contents: list = [prompt]
        if ref is not None:
            contents.append(ref)
        cfg = gtypes.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=gtypes.ImageConfig(aspect_ratio=aspect),
            http_options=gtypes.HttpOptions(timeout=TIMEOUT_MS),
        )
        last_err: Exception | None = None
        for _ in range(MAX_ATTEMPTS):
            try:
                resp = self._client.models.generate_content(
                    model=self.model_id,
                    contents=contents,
                    config=cfg,
                )
                data = _extract_image_bytes(resp)
                if data is not None:
                    return data
                last_err = RuntimeError("response contained no image")
            except Exception as err:  # noqa: BLE001
                last_err = err
        raise RuntimeError(
            f"gemini call failed after {MAX_ATTEMPTS} attempts: {last_err}"
        )

    # ------------------------------------------------------------------
    # CharacterBackend protocol methods
    # ------------------------------------------------------------------

    def generate_portrait(self, req: PortraitRequest) -> PortraitResult:
        ref_img = None
        if req.reference and req.reference.is_file():
            ref_img = Image.open(req.reference).convert("RGBA")
        prompt = (
            f"Generate ONE pixel-art character portrait. "
            f"Character: {req.prompt}.\n\n"
            f"Use the same overall look as the attached reference image.\n\n"
            f"Style: pixel art. Crisp 1-pixel edges. No anti-aliasing. "
            f"A 1-pixel dark outline on the silhouette. Solid neutral "
            f"gray background. No borders, no text, no labels."
        )
        data = self._call(prompt, ref_img, aspect="1:1")
        out = req.output_dir / "portrait.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        return PortraitResult(path=out)

    def generate_walking_sheet(self, req: WalkingSheetRequest) -> WalkingSheetResult:
        raise NotImplementedError("Task 4")

    def generate_action_sheets(self, req: ActionSheetsRequest) -> ActionSheetsResult:
        ref_img = None
        if req.reference and req.reference.is_file():
            ref_img = Image.open(req.reference).convert("RGBA")
        sheets: dict[str, Path] = {}
        for action in req.actions:
            prompt = (
                f"Generate a pixel-art sprite sheet of a character performing "
                f"the '{action}' action. Character: {req.prompt}.\n\n"
                f"Use the same overall look as the attached reference image.\n\n"
                f"Style: pixel art. Crisp 1-pixel edges. No anti-aliasing. "
                f"A 1-pixel dark outline. Solid neutral gray background."
            )
            data = self._call(prompt, ref_img, aspect="4:1")
            out = req.output_dir / f"{action}.png"
            out.write_bytes(data)
            sheets[action] = out
        return ActionSheetsResult(sheets=sheets)
