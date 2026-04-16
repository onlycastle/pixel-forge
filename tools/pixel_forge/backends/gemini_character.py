"""Gemini 3.1 Flash character backend using the google-genai SDK.

Implements portrait, walking-sheet, and action-sheet pipes from the
CharacterBackend protocol.
"""
from __future__ import annotations

import io
import os
from collections import Counter
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

# Walking sheet layout constants
DIRECTIONS = ("right", "up", "left", "down")
CELL_W = 32
CELL_H = 64
FRAMES_PER_DIR = 6
PREVIEW_ROW = 0
IDLE_ROW = 1
WALK_ROW = 2
TARGET_COLS = 56
TARGET_ROWS = 3

FACING_DEFS = {
    "right": "The character is looking to the right.",
    "up": "The character is looking upward (away from the viewer).",
    "left": "The character is looking to the left.",
    "down": "The character is looking downward (toward the viewer).",
}


# ------------------------------------------------------------------
# Walking-sheet helpers
# ------------------------------------------------------------------


def _chroma_key(img: Image.Image, tol: int = 24) -> Image.Image:
    """Replace the dominant background color with transparency."""
    img = img.convert("RGBA")
    pixels = list(img.getdata())

    # Find the most common 5-bit-quantized color
    quantized = Counter()
    for r, g, b, _a in pixels:
        quantized[(r >> 3, g >> 3, b >> 3)] += 1
    dominant_q = quantized.most_common(1)[0][0]
    bg_r, bg_g, bg_b = dominant_q[0] << 3, dominant_q[1] << 3, dominant_q[2] << 3

    # Replace pixels within tolerance
    new_pixels = []
    for r, g, b, a in pixels:
        dist = abs(r - bg_r) + abs(g - bg_g) + abs(b - bg_b)
        if dist <= tol:
            new_pixels.append((r, g, b, 0))
        else:
            new_pixels.append((r, g, b, a))

    result = Image.new("RGBA", img.size)
    result.putdata(new_pixels)
    return result


def _stitch_direction_strips(
    strips: dict[str, Image.Image],
    cell_w: int = CELL_W,
    cell_h: int = CELL_H,
    frames_per_dir: int = FRAMES_PER_DIR,
) -> Image.Image:
    """Stitch 4 direction strips into the PERSON_PREMADE sheet layout.

    Target: 1792x192 (56 cols x 3 rows of 32x64 cells).
    """
    target_w = TARGET_COLS * cell_w  # 1792
    target_h = TARGET_ROWS * cell_h  # 192
    canvas = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))

    strip_w = frames_per_dir * cell_w  # 192
    strip_h = TARGET_ROWS * cell_h  # 192

    for dir_idx, direction in enumerate(DIRECTIONS):
        strip = strips[direction]
        # Resize strip to expected dimensions and apply chroma key
        strip = strip.resize((strip_w, strip_h), Image.NEAREST)
        strip = _chroma_key(strip)

        # Extract each row from the strip
        raw_rows: list[Image.Image] = []
        for row_i in range(TARGET_ROWS):
            raw_rows.append(
                strip.crop((0, row_i * cell_h, strip_w, (row_i + 1) * cell_h))
            )

        # Preview row (row 0): shrink the full row into one cell (keeps
        # transparent margins so background stays see-through).
        preview_cell = raw_rows[PREVIEW_ROW].resize(
            (cell_w, cell_h), Image.NEAREST
        )
        canvas.paste(
            preview_cell,
            (dir_idx * cell_w, PREVIEW_ROW * cell_h),
            preview_cell,
        )

        # For idle / walk rows, auto-crop to the content bbox then resize to
        # fill the full row width so every cell contains character pixels.
        for target_row in (IDLE_ROW, WALK_ROW):
            row_img = raw_rows[target_row]
            bbox = row_img.getbbox()
            if bbox is not None:
                row_img = row_img.crop(bbox).resize(
                    (strip_w, cell_h), Image.NEAREST
                )
            canvas.paste(
                row_img,
                (dir_idx * frames_per_dir * cell_w, target_row * cell_h),
                row_img,
            )

    return canvas


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
        """Generate a full walking sheet in a single 8:1 API call.

        This approach produces the best style consistency (all cells
        generated in one image share visual context) and is 4× faster
        than per-direction strip calls. The raw output (~2928×352) is
        LANCZOS-resized to the PERSON_PREMADE target (1792×192) and
        chroma-keyed to alpha.
        """
        ref_img = None
        if req.reference and req.reference.is_file():
            ref_img = Image.open(req.reference).convert("RGBA")
            # Crop to locomotion band (rows 0-2) if the reference is
            # a full premade sheet (1792×1312).
            rw, rh = ref_img.size
            target_h = TARGET_ROWS * CELL_H  # 192
            if rh > target_h:
                ref_img = ref_img.crop((0, 0, rw, target_h))

        prompt = (
            f"Generate a pixel-art sprite sheet for this character: "
            f"{req.prompt}.\n\n"
            f"Match the layout of the attached reference image. The sheet "
            f"has three rows:\n"
            f"- The top row shows the character looking right, looking up, "
            f"looking left, and looking down.\n"
            f"- The middle row shows idle frames for each of those four "
            f"directions, in the same order.\n"
            f"- The bottom row shows walk-cycle frames for each of those "
            f"four directions, in the same order.\n\n"
            f"The same character must appear in every cell — same face, "
            f"same outfit, same colors. Use the same overall look as the "
            f"attached reference image.\n\n"
            f"Style: pixel art. Crisp 1-pixel edges. No anti-aliasing. "
            f"A 1-pixel dark outline on the silhouette. No borders, no "
            f"text, no labels."
        )
        data = self._call(prompt, ref_img, aspect="8:1")
        raw = Image.open(io.BytesIO(data)).convert("RGBA")

        # Resize to PERSON_PREMADE target
        target_w = TARGET_COLS * CELL_W  # 1792
        target_h = TARGET_ROWS * CELL_H  # 192
        sheet = raw.resize((target_w, target_h), Image.LANCZOS)

        # Chroma-key background to transparent
        sheet = _chroma_key(sheet)

        out = req.output_dir / "walk.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(out, "PNG")

        dims = {
            "cell": [CELL_W, CELL_H],
            "cols": TARGET_COLS,
            "rows": TARGET_ROWS,
            "direction_order": list(DIRECTIONS),
            "locomotion_rows": {
                "preview": PREVIEW_ROW,
                "idle": IDLE_ROW,
                "walk": WALK_ROW,
            },
            "frames_per_dir": FRAMES_PER_DIR,
        }
        return WalkingSheetResult(sheet_path=out, dims=dims)

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
