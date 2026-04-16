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

    def _generate_one_strip(
        self, direction: str, prompt_text: str, ref_img: Image.Image | None,
    ) -> tuple[str, Image.Image]:
        """Generate one direction's strip. Returns (direction, image)."""
        ref_cell = ref_img
        if ref_img is not None:
            dir_idx = DIRECTIONS.index(direction)
            rw, rh = ref_img.size
            cell_w_ref = rw // len(DIRECTIONS)
            ref_cell = ref_img.crop(
                (dir_idx * cell_w_ref, 0, (dir_idx + 1) * cell_w_ref, rh)
            )

        facing = FACING_DEFS[direction]
        prompt = (
            f"Generate a pixel-art sprite sheet showing a character "
            f"walking. {facing} Character: {prompt_text}.\n\n"
            f"The sheet should be a grid: 6 columns wide and 3 rows tall.\n"
            f"Row 1: standing preview. Row 2: idle animation frames. "
            f"Row 3: walk-cycle animation frames.\n\n"
            f"Style: pixel art. Crisp edges. No anti-aliasing. "
            f"Dark outline on the silhouette. Solid neutral gray background. "
            f"No borders, no text, no labels."
        )
        data = self._call(prompt, ref_cell, aspect="1:1")
        return direction, Image.open(io.BytesIO(data)).convert("RGBA")

    def generate_walking_sheet(self, req: WalkingSheetRequest) -> WalkingSheetResult:
        ref_img = None
        if req.reference and req.reference.is_file():
            ref_img = Image.open(req.reference).convert("RGBA")

        # Run 4 direction calls in parallel for ~4× speedup.
        from concurrent.futures import ThreadPoolExecutor, as_completed
        strips: dict[str, Image.Image] = {}
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {
                pool.submit(self._generate_one_strip, d, req.prompt, ref_img): d
                for d in DIRECTIONS
            }
            for future in as_completed(futures):
                direction, strip_img = future.result()
                strips[direction] = strip_img

        sheet = _stitch_direction_strips(strips)
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
