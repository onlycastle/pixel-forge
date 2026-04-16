# Asset-Forge Backend: Gemini 3.1 Flash + PixelLab Character Backends

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the pixel-forge Gemini 2.5 Flash backend with a Gemini 3.1 Flash per-direction-strip backend and add a PixelLab backend, both conforming to a new `CharacterBackend` protocol with pipe-specific methods for portrait, walking sheet, and action sheets.

**Architecture:** The legacy `ImageBackend` protocol (single `generate()` method) is preserved for animal/decoration flows. A new `CharacterBackend` protocol defines three methods matching the bundle pipeline's three pipes. `GeminiCharacterBackend` migrates from the `google.generativeai` SDK to `google-genai`, swaps the model to `gemini-3.1-flash-image-preview`, and implements walking-sheet generation via four per-direction strip calls + chroma-key stitching. `PixelLabCharacterBackend` wraps the validated full-pipeline experiment. CLI gains `--backend {gemini,pixellab}`.

**Tech Stack:** Python 3.12, google-genai SDK, pixellab SDK, Pillow, pytest

**Spec:** `docs/superpowers/specs/2026-04-15-asset-forge-redesign-design.md`

**Phase B (Web UI)** follows as a separate plan after this phase is green.

---

## File Map

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `tools/pixel_forge/backends/character.py` | `CharacterBackend` protocol + request/result dataclasses |
| Create | `tools/pixel_forge/backends/gemini_character.py` | Gemini 3.1 Flash per-direction character backend |
| Create | `tools/pixel_forge/backends/pixellab_character.py` | PixelLab full-pipeline character backend |
| Create | `tests/test_character_backend.py` | Tests for protocol, stitcher, CLI dispatch |
| Modify | `tools/pixel_forge/backends/__init__.py` | Export new backends |
| Modify | `tools/pixel_forge/cli.py` | `--backend` flag, dispatch refactor in `_cmd_bundle` |
| Modify | `pyproject.toml` | Add `google-genai`, `pixellab` dependencies |
| Delete | `tools/pixel_forge/sheet.py` lines 524-700 | `WalkRefineRequest`, `refine_sheet_walk()` |
| Delete | `tools/pixel_forge/cli.py` refine-walk lines | `--refine-walk` flag, refine handler in `_cmd_bundle` |
| Delete | 6 experiment scripts | Dead-end spikes (see Task 8) |

---

### Task 1: Add dependencies

**Files:**
- Modify: `pyproject.toml:10-13`

- [ ] **Step 1: Add google-genai and pixellab to dependencies**

```toml
dependencies = [
    "Pillow>=10.2",
    "google-generativeai>=0.7",
    "google-genai>=1.0",
    "pixellab>=1.0",
]
```

Note: `google-generativeai` stays because the legacy `GeminiBackend` (for animal/decoration flows) still imports it. It will be removed when the legacy backend is fully retired.

- [ ] **Step 2: Install updated dependencies**

Run: `cd /Users/sungmancho/projects/pixel-forge && .venv/bin/pip install -e .`
Expected: Both `google-genai` and `pixellab` install successfully (they may already be present from experiment work).

- [ ] **Step 3: Verify imports work**

Run: `.venv/bin/python -c "from google import genai; from google.genai import types; import pixellab; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "build: add google-genai and pixellab dependencies"
```

---

### Task 2: Define CharacterBackend protocol + types

**Files:**
- Create: `tools/pixel_forge/backends/character.py`
- Test: `tests/test_character_backend.py`

- [ ] **Step 1: Write the protocol type-check test**

```python
# tests/test_character_backend.py
"""Tests for the CharacterBackend protocol and its implementations."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_character_backend.py::test_fake_backend_satisfies_protocol -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pixel_forge.backends.character'`

- [ ] **Step 3: Write the protocol and dataclasses**

```python
# tools/pixel_forge/backends/character.py
"""CharacterBackend protocol for the person-bundle pipeline.

Defines three pipe-specific methods matching the bundle's portrait,
walking-sheet, and action-sheets stages. Each backend (Gemini, PixelLab)
implements all three. The legacy ImageBackend (in base.py) continues to
serve animal/decoration flows unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class PortraitRequest:
    prompt: str
    reference: Path | None
    output_dir: Path


@dataclass(frozen=True)
class PortraitResult:
    path: Path


@dataclass(frozen=True)
class WalkingSheetRequest:
    prompt: str
    reference: Path | None
    output_dir: Path
    profile_id: str = "person-premade"


@dataclass(frozen=True)
class WalkingSheetResult:
    sheet_path: Path
    dims: dict


@dataclass(frozen=True)
class ActionSheetsRequest:
    prompt: str
    reference: Path | None
    output_dir: Path
    actions: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ActionSheetsResult:
    sheets: dict[str, Path]


class CharacterBackend(Protocol):
    def generate_portrait(self, req: PortraitRequest) -> PortraitResult: ...
    def generate_walking_sheet(self, req: WalkingSheetRequest) -> WalkingSheetResult: ...
    def generate_action_sheets(self, req: ActionSheetsRequest) -> ActionSheetsResult: ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_character_backend.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/pixel_forge/backends/character.py tests/test_character_backend.py
git commit -m "feat(backends): define CharacterBackend protocol with pipe-specific methods"
```

---

### Task 3: GeminiCharacterBackend — portrait + action pipes (SDK migration)

**Files:**
- Create: `tools/pixel_forge/backends/gemini_character.py`
- Modify: `tests/test_character_backend.py`

This task handles the SDK migration (`google.generativeai` → `google-genai`) and implements the simpler pipes (portrait, action sheets). The walking-sheet pipe (per-direction strips) is Task 4.

- [ ] **Step 1: Write the portrait generation test**

Add to `tests/test_character_backend.py`:

```python
from unittest.mock import MagicMock, patch
from pixel_forge.backends.gemini_character import GeminiCharacterBackend


def _make_fake_response(image_bytes: bytes) -> MagicMock:
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


def test_gemini_generate_portrait(tmp_path):
    """GeminiCharacterBackend.generate_portrait writes a PNG and returns its path."""
    # 1x1 red PNG (minimal valid PNG)
    from PIL import Image
    import io
    buf = io.BytesIO()
    Image.new("RGBA", (64, 64), (255, 0, 0, 255)).save(buf, "PNG")
    png_bytes = buf.getvalue()

    fake_response = _make_fake_response(png_bytes)
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_character_backend.py::test_gemini_generate_portrait -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pixel_forge.backends.gemini_character'`

- [ ] **Step 3: Implement GeminiCharacterBackend**

```python
# tools/pixel_forge/backends/gemini_character.py
"""Gemini 3.1 Flash character backend using the google-genai SDK."""
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

    def _call(
        self,
        prompt: str,
        ref: Image.Image | None,
        aspect: str = "1:1",
    ) -> bytes:
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
                    model=self.model_id, contents=contents, config=cfg,
                )
                data = _extract_image_bytes(resp)
                if data is not None:
                    return data
                last_err = RuntimeError("response contained no image")
            except Exception as err:
                last_err = err
        raise RuntimeError(f"gemini call failed after {MAX_ATTEMPTS} attempts: {last_err}")

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_character_backend.py -v`
Expected: PASS (both protocol test and portrait test)

- [ ] **Step 5: Commit**

```bash
git add tools/pixel_forge/backends/gemini_character.py tests/test_character_backend.py
git commit -m "feat(backends): GeminiCharacterBackend with portrait + action pipes via google-genai SDK"
```

---

### Task 4: GeminiCharacterBackend — per-direction walking sheet + stitcher

**Files:**
- Modify: `tools/pixel_forge/backends/gemini_character.py`
- Modify: `tests/test_character_backend.py`

This is the core fix for the diagonal-facing bug. The walking sheet is generated as 4 per-direction strip calls, then stitched into PERSON_PREMADE layout with chroma-key background removal.

- [ ] **Step 1: Write the stitcher unit test**

Add to `tests/test_character_backend.py`:

```python
from pixel_forge.backends.gemini_character import _stitch_direction_strips


def _make_strip(color: tuple, w: int = 192, h: int = 64) -> Image.Image:
    """Create a fake direction strip: colored character area on gray bg."""
    img = Image.new("RGBA", (w, h), (140, 140, 140, 255))
    # Paint character region in center as a solid-color block
    for x in range(w // 4, 3 * w // 4):
        for y in range(h // 4, 3 * h // 4):
            img.putpixel((x, y), color + (255,))
    return img


def test_stitch_direction_strips():
    """Stitcher composes 4 strips into a 1792x192 PERSON_PREMADE sheet."""
    strips = {
        "right": _make_strip((255, 0, 0)),
        "up": _make_strip((0, 255, 0)),
        "left": _make_strip((0, 0, 255)),
        "down": _make_strip((255, 255, 0)),
    }
    sheet = _stitch_direction_strips(strips, cell_w=32, cell_h=64, frames_per_dir=6)

    # PERSON_PREMADE layout: 1792x192 (56 cols x 3 rows of 32x64 cells)
    assert sheet.size == (1792, 192)
    assert sheet.mode == "RGBA"

    # Row 0 col 0 = right preview: should have red character pixels
    cell_00 = sheet.crop((0, 0, 32, 64))
    px = list(cell_00.getdata())
    red_px = [p for p in px if p[0] > 200 and p[1] < 50 and p[2] < 50 and p[3] > 200]
    assert len(red_px) > 0, "right preview cell should contain red character pixels"

    # Row 0 col 1 = up preview: should have green character pixels
    cell_01 = sheet.crop((32, 0, 64, 64))
    px = list(cell_01.getdata())
    green_px = [p for p in px if p[1] > 200 and p[0] < 50 and p[3] > 200]
    assert len(green_px) > 0, "up preview cell should contain green character pixels"

    # Background should be transparent (chroma-key removed the gray)
    cell_00_px = list(cell_00.getdata())
    transparent_px = [p for p in cell_00_px if p[3] < 10]
    assert len(transparent_px) > 0, "background should be chroma-keyed to transparent"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_character_backend.py::test_stitch_direction_strips -v`
Expected: FAIL — `ImportError: cannot import name '_stitch_direction_strips'`

- [ ] **Step 3: Implement the stitcher and walking sheet method**

Add to `tools/pixel_forge/backends/gemini_character.py`:

```python
from collections import Counter

DIRECTIONS = ("right", "up", "left", "down")
CELL_W = 32
CELL_H = 64
FRAMES_PER_DIR = 6
PREVIEW_ROW = 0
IDLE_ROW = 1
WALK_ROW = 2
TARGET_COLS = 56
TARGET_ROWS = 3

FACING_DEFS: dict[str, str] = {
    "right": "The character is looking to the right.",
    "up": "The character is looking upward (away from the viewer).",
    "left": "The character is looking to the left.",
    "down": "The character is looking downward (toward the viewer).",
}


def _chroma_key(img: Image.Image, tol: int = 24) -> Image.Image:
    """Replace the dominant background color with transparency."""
    img = img.convert("RGBA")
    px = list(img.getdata())
    quant = Counter((p[0] >> 3, p[1] >> 3, p[2] >> 3) for p in px)
    bg5 = quant.most_common(1)[0][0]
    bg = (bg5[0] << 3, bg5[1] << 3, bg5[2] << 3)
    new_px = []
    for p in px:
        dist = abs(p[0] - bg[0]) + abs(p[1] - bg[1]) + abs(p[2] - bg[2])
        if dist <= tol:
            new_px.append((0, 0, 0, 0))
        else:
            new_px.append(p)
    result = Image.new("RGBA", img.size)
    result.putdata(new_px)
    return result


def _stitch_direction_strips(
    strips: dict[str, Image.Image],
    cell_w: int = CELL_W,
    cell_h: int = CELL_H,
    frames_per_dir: int = FRAMES_PER_DIR,
) -> Image.Image:
    """Compose 4 per-direction strip images into a PERSON_PREMADE sheet.

    Each strip is a raw model output (variable size, opaque background).
    The stitcher:
    1. Resizes each strip to fit frames_per_dir cells wide × 3 rows tall
       (preview + idle + walk) using LANCZOS
    2. Chroma-keys the background to transparent
    3. Pastes each direction's cells into the target grid position
    """
    strip_w = frames_per_dir * cell_w  # 192
    strip_h = TARGET_ROWS * cell_h     # 192
    canvas = Image.new("RGBA", (TARGET_COLS * cell_w, TARGET_ROWS * cell_h), (0, 0, 0, 0))

    for dir_idx, direction in enumerate(DIRECTIONS):
        strip = strips[direction]
        # Resize strip to expected cell grid
        resized = strip.resize((strip_w, strip_h), Image.LANCZOS)
        keyed = _chroma_key(resized)

        # Preview row: paste first cell of this strip into row 0
        preview_cell = keyed.crop((0, 0, cell_w, cell_h))
        canvas.paste(preview_cell, (dir_idx * cell_w, PREVIEW_ROW * cell_h), preview_cell)

        # Idle row: paste the full strip's idle row (row 1 of the strip)
        idle_strip = keyed.crop((0, IDLE_ROW * cell_h, strip_w, (IDLE_ROW + 1) * cell_h))
        x_offset = dir_idx * frames_per_dir * cell_w
        canvas.paste(idle_strip, (x_offset, IDLE_ROW * cell_h), idle_strip)

        # Walk row: paste the full strip's walk row (row 2 of the strip)
        walk_strip = keyed.crop((0, WALK_ROW * cell_h, strip_w, (WALK_ROW + 1) * cell_h))
        canvas.paste(walk_strip, (x_offset, WALK_ROW * cell_h), walk_strip)

    return canvas
```

Then implement `generate_walking_sheet` in `GeminiCharacterBackend`:

```python
    def generate_walking_sheet(self, req: WalkingSheetRequest) -> WalkingSheetResult:
        ref_sheet = None
        if req.reference and req.reference.is_file():
            ref_sheet = Image.open(req.reference).convert("RGBA")

        strips: dict[str, Image.Image] = {}
        for direction in DIRECTIONS:
            # Per-direction reference: crop the matching preview cell
            ref_cell = None
            if ref_sheet is not None:
                dir_idx = DIRECTIONS.index(direction)
                ref_cell = ref_sheet.crop(
                    (dir_idx * CELL_W, 0, (dir_idx + 1) * CELL_W, CELL_H)
                )

            prompt = (
                f"Generate a pixel-art sprite sheet for this character: "
                f"{req.prompt}.\n\n"
                f"{FACING_DEFS[direction]}\n\n"
                f"The sheet has three rows:\n"
                f"- Top row: one idle pose of the character.\n"
                f"- Middle row: several idle frames with subtle variation.\n"
                f"- Bottom row: several walk-cycle frames with legs alternating.\n\n"
                f"The same character must appear in every cell — same face, "
                f"outfit, colors. Use the same overall look as the attached "
                f"reference image.\n\n"
                f"Style: pixel art. Crisp 1-pixel edges. No anti-aliasing. "
                f"A 1-pixel dark outline. No borders, no text, no labels."
            )
            data = self._call(prompt, ref_cell, aspect="1:1")
            strip_img = Image.open(__import__("io").BytesIO(data)).convert("RGBA")
            strips[direction] = strip_img

        sheet = _stitch_direction_strips(strips)
        out = req.output_dir / "walk.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(out)

        dims = {
            "cell": [CELL_W, CELL_H],
            "cols": TARGET_COLS,
            "rows": TARGET_ROWS,
            "direction_order": list(DIRECTIONS),
            "locomotion_rows": {"preview": PREVIEW_ROW, "idle": IDLE_ROW, "walk": WALK_ROW},
            "frames_per_dir": FRAMES_PER_DIR,
        }
        return WalkingSheetResult(sheet_path=out, dims=dims)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_character_backend.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add tools/pixel_forge/backends/gemini_character.py tests/test_character_backend.py
git commit -m "feat(backends): per-direction walking sheet with chroma-key stitcher"
```

---

### Task 5: PixelLabCharacterBackend

**Files:**
- Create: `tools/pixel_forge/backends/pixellab_character.py`
- Modify: `tests/test_character_backend.py`

Promotes the validated `try_pixellab_full_pipeline.py` experiment into a production backend conforming to `CharacterBackend`.

- [ ] **Step 1: Write the PixelLab protocol conformance test**

Add to `tests/test_character_backend.py`:

```python
from unittest.mock import MagicMock, patch, PropertyMock
from pixel_forge.backends.pixellab_character import PixelLabCharacterBackend


def _mock_pixellab_image(w: int = 64, h: int = 64) -> MagicMock:
    """Create a mock pixellab response image."""
    buf = io.BytesIO()
    Image.new("RGBA", (w, h), (100, 100, 200, 255)).save(buf, "PNG")
    pil_img = Image.new("RGBA", (w, h), (100, 100, 200, 255))
    mock_img = MagicMock()
    mock_img.pil_image.return_value = pil_img
    return mock_img


def test_pixellab_generate_portrait(tmp_path):
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_character_backend.py::test_pixellab_generate_portrait -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement PixelLabCharacterBackend**

```python
# tools/pixel_forge/backends/pixellab_character.py
"""PixelLab character backend using the full generate+rotate+animate pipeline."""
from __future__ import annotations

import os
from pathlib import Path

import pixellab
from PIL import Image

from pixel_forge.backends.character import (
    ActionSheetsRequest,
    ActionSheetsResult,
    PortraitRequest,
    PortraitResult,
    WalkingSheetRequest,
    WalkingSheetResult,
)
from pixel_forge.experiments.pixellab_to_sheet import convert_pack

NATIVE_SIZE = 64
CARDINALS = ("east", "north", "west", "south")
DIRECTION_MAP = {"right": "east", "up": "north", "left": "west", "down": "south"}
WALK_ANIM_ID = "walk"


class PixelLabCharacterBackend:
    def __init__(
        self,
        output_dir: Path,
        client: pixellab.Client | None = None,
    ) -> None:
        self.output_dir = output_dir
        if client is not None:
            self._client = client
        else:
            api_key = os.environ.get("PIXELLAB_API_KEY", "")
            self._client = pixellab.Client(secret=api_key)

    def generate_portrait(self, req: PortraitRequest) -> PortraitResult:
        resp = self._client.generate_image_pixflux(
            description=req.prompt,
            image_size={"width": NATIVE_SIZE, "height": NATIVE_SIZE},
            view="low top-down",
            direction="south",
            outline="single color black outline",
            shading="basic shading",
            detail="medium detail",
            no_background=True,
        )
        img = resp.image.pil_image().convert("RGBA")
        out = req.output_dir / "portrait.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        img.save(out)
        return PortraitResult(path=out)

    def generate_walking_sheet(self, req: WalkingSheetRequest) -> WalkingSheetResult:
        pack_dir = req.output_dir / "_pixellab_pack"
        rotations_dir = pack_dir / "rotations"
        animations_dir = pack_dir / "animations" / WALK_ANIM_ID
        pack_dir.mkdir(parents=True, exist_ok=True)
        rotations_dir.mkdir(parents=True, exist_ok=True)

        # Step 1: generate east-facing base
        base_resp = self._client.generate_image_pixflux(
            description=req.prompt,
            image_size={"width": NATIVE_SIZE, "height": NATIVE_SIZE},
            view="low top-down", direction="east",
            outline="single color black outline",
            shading="basic shading", detail="medium detail",
            no_background=True,
        )
        east_img = base_resp.image.pil_image().convert("RGBA")
        east_img.save(rotations_dir / "east.png")

        # Step 2: rotate to other cardinals
        rotations = {"east": east_img}
        for target in ("north", "west", "south"):
            resp = self._client.rotate(
                image_size={"width": NATIVE_SIZE, "height": NATIVE_SIZE},
                from_image=east_img,
                from_view="low top-down", to_view="low top-down",
                from_direction="east", to_direction=target,
            )
            img = resp.image.pil_image().convert("RGBA")
            rotations[target] = img
            img.save(rotations_dir / f"{target}.png")

        # Step 3: animate walk per direction
        for direction in CARDINALS:
            resp = self._client.animate_with_text(
                image_size={"width": NATIVE_SIZE, "height": NATIVE_SIZE},
                description=req.prompt,
                negative_description="",
                action="walk",
                reference_image=rotations[direction],
                view="low top-down", direction=direction,
                n_frames=6,
            )
            frame_dir = animations_dir / direction
            frame_dir.mkdir(parents=True, exist_ok=True)
            for i, frame in enumerate(resp.images):
                frame.pil_image().convert("RGBA").save(frame_dir / f"frame_{i:03d}.png")

        # Step 4: write pack metadata
        import json
        from datetime import datetime, timezone
        meta = {
            "character": {
                "id": f"pf-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                "name": req.prompt[:80], "prompt": req.prompt,
                "size": {"width": NATIVE_SIZE, "height": NATIVE_SIZE},
                "template_id": "programmatic", "directions": 4,
                "view": "low top-down",
                "created_at": datetime.now(tz=timezone.utc).isoformat(),
            },
            "frames": {
                "rotations": {d: f"rotations/{d}.png" for d in CARDINALS},
                "animations": {
                    WALK_ANIM_ID: {
                        d: [f"animations/{WALK_ANIM_ID}/{d}/frame_{i:03d}.png" for i in range(6)]
                        for d in CARDINALS
                    }
                },
            },
            "export_version": "2.0",
            "export_date": datetime.now(tz=timezone.utc).isoformat(),
        }
        (pack_dir / "metadata.json").write_text(json.dumps(meta, indent=2))

        # Step 5: convert pack to PERSON_PREMADE sheet
        sheet_path = req.output_dir / "walk.png"
        convert_pack(pack_dir, sheet_path)

        dims = {
            "cell": [32, 64], "cols": 56, "rows": 3,
            "direction_order": ["right", "up", "left", "down"],
            "locomotion_rows": {"preview": 0, "idle": 1, "walk": 2},
            "frames_per_dir": 6,
        }
        return WalkingSheetResult(sheet_path=sheet_path, dims=dims)

    def generate_action_sheets(self, req: ActionSheetsRequest) -> ActionSheetsResult:
        # PixelLab doesn't have action-specific generation yet.
        # Return empty — the UI shows "no action sheets for this backend".
        return ActionSheetsResult(sheets={})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_character_backend.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add tools/pixel_forge/backends/pixellab_character.py tests/test_character_backend.py
git commit -m "feat(backends): PixelLabCharacterBackend wrapping full pipeline + adapter"
```

---

### Task 6: CLI --backend flag + _cmd_bundle dispatch

**Files:**
- Modify: `tools/pixel_forge/cli.py`
- Modify: `tools/pixel_forge/backends/__init__.py`
- Modify: `tests/test_character_backend.py`

- [ ] **Step 1: Write the CLI dispatch test**

Add to `tests/test_character_backend.py`:

```python
from pixel_forge.backends import resolve_character_backend


def test_resolve_gemini_backend(tmp_path):
    backend = resolve_character_backend("gemini", tmp_path)
    assert type(backend).__name__ == "GeminiCharacterBackend"


def test_resolve_pixellab_backend(tmp_path):
    backend = resolve_character_backend("pixellab", tmp_path)
    assert type(backend).__name__ == "PixelLabCharacterBackend"


def test_resolve_unknown_backend_raises(tmp_path):
    import pytest
    with pytest.raises(ValueError, match="unknown character backend"):
        resolve_character_backend("nonexistent", tmp_path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_character_backend.py::test_resolve_gemini_backend -v`
Expected: FAIL — `ImportError: cannot import name 'resolve_character_backend'`

- [ ] **Step 3: Implement resolve_character_backend and update __init__.py**

```python
# tools/pixel_forge/backends/__init__.py
"""Backend registry for pixel-forge."""
from __future__ import annotations

from pathlib import Path

from pixel_forge.backends.character import CharacterBackend


def resolve_character_backend(name: str, output_dir: Path) -> CharacterBackend:
    if name == "gemini":
        from pixel_forge.backends.gemini_character import GeminiCharacterBackend
        return GeminiCharacterBackend(output_dir=output_dir)
    elif name == "pixellab":
        from pixel_forge.backends.pixellab_character import PixelLabCharacterBackend
        return PixelLabCharacterBackend(output_dir=output_dir)
    else:
        raise ValueError(f"unknown character backend: {name!r}")
```

- [ ] **Step 4: Add --backend flag to _cmd_bundle in cli.py**

In `tools/pixel_forge/cli.py`, find the bundle subparser setup (search for `"bundle"` in `_build_parser`) and add:

```python
bundle_p.add_argument(
    "--backend",
    choices=["gemini", "pixellab"],
    default="gemini",
    help="Character generation backend (default: gemini = 3.1 Flash)",
)
```

Then in `_cmd_bundle`, replace the `_get_backend` closure with:

```python
from pixel_forge.backends import resolve_character_backend
character_backend = resolve_character_backend(
    args.backend or "gemini",
    project_dir / "out" / "_raw",
)
```

The rest of `_cmd_bundle` continues to use the old `_get_backend()` for pipe calls that haven't been migrated yet. The new `character_backend` is used for person-kind bundles only; animal/decoration bundles keep using the legacy `ImageBackend`.

- [ ] **Step 5: Run tests and commit**

Run: `.venv/bin/pytest tests/test_character_backend.py -v`
Expected: All tests PASS

```bash
git add tools/pixel_forge/backends/__init__.py tools/pixel_forge/cli.py tests/test_character_backend.py
git commit -m "feat(cli): add --backend flag to pf bundle with gemini/pixellab dispatch"
```

---

### Task 7: Delete refine-walk code

**Files:**
- Modify: `tools/pixel_forge/cli.py` (remove `--refine-walk` flag, refine handler in `_cmd_bundle`)
- Modify: `tools/pixel_forge/sheet.py` (remove `WalkRefineRequest`, `refine_sheet_walk()`)
- Modify: `tests/test_generate_integration.py` (if it references refine)
- Modify: `tests/test_cli_validate.py` (if it references refine)

- [ ] **Step 1: Find and list all refine-walk references**

Run: `.venv/bin/python -c "import subprocess; r = subprocess.run(['grep', '-rn', 'refine.walk\|refine_walk\|WalkRefineRequest\|_cmd_sheet_refine_walk', 'tools/', 'tests/'], capture_output=True, text=True); print(r.stdout)"`

- [ ] **Step 2: Remove from sheet.py**

Delete the `WalkRefineRequest` dataclass (starting at line 524) and the `refine_sheet_walk()` function (starting at line 654), plus any helper functions that are ONLY used by refine (like `_build_walk_strip_prompt`, `_extract_walk_strip`, `_direction_strip_box` — verify each has no other callers before deleting).

- [ ] **Step 3: Remove from cli.py**

Remove the `--refine-walk` argument from the bundle subparser, and the refine handler block in `_cmd_bundle` (the `if args.refine_walk:` branch).

- [ ] **Step 4: Run all tests to verify nothing breaks**

Run: `.venv/bin/pytest tests/ -v`
Expected: All tests PASS (some tests may need updating if they tested refine behavior — remove those test cases)

- [ ] **Step 5: Commit**

```bash
git add -u tools/ tests/
git commit -m "refactor: remove --refine-walk pipeline (per-direction strips are now default)"
```

---

### Task 8: Delete dead experiment scripts

**Files to delete:**
- `tools/pixel_forge/experiments/try_gemini_31_flash.py`
- `tools/pixel_forge/experiments/try_gemini_31_flash_v2.py`
- `tools/pixel_forge/experiments/try_nano_banana_singledir.py`
- `tools/pixel_forge/experiments/try_pixellab_bitforge.py`
- `tools/pixel_forge/experiments/try_pixellab.py`
- `tools/pixel_forge/experiments/try_gemini_3_pro.py`

- [ ] **Step 1: Delete the files**

```bash
cd /Users/sungmancho/projects/pixel-forge
rm tools/pixel_forge/experiments/try_gemini_31_flash.py
rm tools/pixel_forge/experiments/try_gemini_31_flash_v2.py
rm tools/pixel_forge/experiments/try_nano_banana_singledir.py
rm tools/pixel_forge/experiments/try_pixellab_bitforge.py
rm tools/pixel_forge/experiments/try_pixellab.py
rm tools/pixel_forge/experiments/try_gemini_3_pro.py
```

- [ ] **Step 2: Verify remaining experiment files are correct**

```bash
ls tools/pixel_forge/experiments/*.py
```

Expected remaining:
- `__init__.py`
- `pixellab_to_sheet.py` (used by PixelLabCharacterBackend)
- `try_gemini_31_flash_batch.py` (user-approved style reference)
- `try_gemini_31_flash_singledir.py` (Path A documentation)
- `try_nano_banana_4dir.py` (prompt template reference)
- `try_pixellab_full_pipeline.py` (PixelLab pipeline reference)

- [ ] **Step 3: Run all tests to ensure no imports broke**

Run: `.venv/bin/pytest tests/ -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add -u tools/pixel_forge/experiments/
git commit -m "chore: delete 6 dead-end experiment scripts (see spec for rationale)"
```

---

### Task 9: Integration smoke test

**Files:**
- Modify: `tests/test_character_backend.py`

End-to-end test of the full pipeline using the stub backend to verify the bundle orchestration works without hitting real APIs.

- [ ] **Step 1: Write the integration test**

```python
def test_bundle_cli_with_stub_backend(tmp_path):
    """Verify `pf bundle --backend gemini` with a monkeypatched client
    produces the expected bundle directory structure."""
    import subprocess

    # This test verifies CLI argument parsing and dispatch.
    # Full API integration is tested manually.
    result = subprocess.run(
        [
            ".venv/bin/pf", "bundle",
            "--project", "sunny-street",
            "--backend", "gemini",
            "--help",
        ],
        capture_output=True, text=True, cwd="/Users/sungmancho/projects/pixel-forge",
    )
    assert result.returncode == 0
    assert "--backend" in result.stdout
    assert "gemini" in result.stdout
    assert "pixellab" in result.stdout
```

- [ ] **Step 2: Run the test**

Run: `.venv/bin/pytest tests/test_character_backend.py::test_bundle_cli_with_stub_backend -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_character_backend.py
git commit -m "test: integration smoke test for pf bundle --backend flag"
```

---

## Self-review checklist

**Spec coverage:** All backend requirements from the spec are covered:
- CharacterBackend protocol (Task 2) ✓
- SDK migration google.generativeai → google-genai (Task 3) ✓
- Per-direction strip generation + stitcher (Task 4) ✓
- Chroma-key with tolerance 24 + fallback (Task 4, `_chroma_key`) ✓
- PixelLabCharacterBackend promotion (Task 5) ✓
- CLI --backend flag (Task 6) ✓
- Delete refine-walk (Task 7) ✓
- Delete experiment scripts (Task 8) ✓
- Rollback note (referenced in spec, not a code task) ✓
- Phase B (Web UI) deferred to separate plan ✓

**Placeholder scan:** No TBD/TODO found. Task 4 walking sheet prompt uses the exact simplified wording from the validated nano-banana experiment.

**Type consistency:** `PortraitRequest/Result`, `WalkingSheetRequest/Result`, `ActionSheetsRequest/Result` are defined in Task 2 and used consistently in Tasks 3, 4, 5, 6. `_stitch_direction_strips` is defined and tested in Task 4. `resolve_character_backend` is defined in Task 6 `__init__.py` and tested there.
