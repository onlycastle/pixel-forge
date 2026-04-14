"""End-to-end AI sprite sheet generation pipeline.

Wraps the three pieces validated by smoke tests into one callable:

  1. Mask the LimeZu debug label out of the reference image so the
     model has nothing to copy
  2. Call Gemini with a sprite-sheet prompt that describes the target
     grid contract (rows = idle/walk/etc, frame size, direction order)
  3. Run the heuristic sheet_extract post-processor on each raw output
     to produce a clean RGBA sheet at the target cell resolution

The result is a sprite sheet drop-in compatible with sunny-street's
existing per-profile contract (livestock24 for animals, premade-format
for townspeople, etc).

This module is invoked by `pf sheet` and by the asset-forge GUI's
"animated sheet" output mode. It does NOT touch the existing
single-frame `pf generate` path - that one stays exactly as it was for
concept art / static decoration use.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw

from pixel_forge.assets import (
    SCHEMA_VERSION,
    AssetKind,
    AssetSidecar,
    save_sidecar,
)
from pixel_forge.backends.gemini import GeminiBackend
from pixel_forge.paths import ProjectPaths
from pixel_forge.project import Project
from pixel_forge.sheet_extract import (
    ExtractRequest,
    ExtractResult,
    extract_sheet,
)


# Animation profiles describe the sprite-sheet contract the model must
# honor and the post-processor must emit. The canvas is the FINAL clean
# sheet size sunny-street loads. The reference is what we send Gemini -
# its grid is the authoritative layout signal.
@dataclass(frozen=True)
class SheetProfile:
    id: str
    target_cell: tuple[int, int]   # (W, H) of one cell in the final sheet
    target_cols: int               # cells across in the final sheet
    target_rows: int               # cells down in the final sheet
    label_mask_box: tuple[int, int, int, int]  # mask coords on reference
    direction_order: tuple[str, ...] = ("right", "up", "left", "down")
    locomotion_rows: dict[str, int] | None = None
    # Additional STYLE reference images (relative paths under the
    # sunny-street public/ tree) that get sent to Gemini alongside the
    # primary layout reference. More references = richer style signal
    # (different skin tones / outfits / hair) so the model sees what
    # "the right kind of sprite sheet" looks like instead of just one
    # example. The primary layout reference is passed separately via
    # SheetRequest.reference_path; these are additive.
    style_references: tuple[str, ...] = ()


# Animal sheet contract (matches sunny-street's livestock24 profile).
# Reference is duck-brown.png (32x32 frames, 24x4 sheet).
ANIMAL_LIVESTOCK24 = SheetProfile(
    id="animal-livestock24",
    target_cell=(32, 32),
    target_cols=24,
    target_rows=4,
    label_mask_box=(0, 0, 120, 24),
    locomotion_rows={"idle": 0, "walk": 1},
    # Additional 32x32 livestock animals as style anchors. All share
    # the livestock24 layout so they reinforce the grid + style signal.
    style_references=(
        "public/sprites/animals/pig-pink.png",
        "public/sprites/animals/sheep-white.png",
    ),
)

# Townsperson sheet contract. Target is the top 3 rows of a premade
# sheet: direction preview + idle + walk = exactly what sunny-street's
# character-anims.ts currently loads. Target canvas 1792x192 is a
# 9.3:1 aspect ratio — Gemini honors this ratio iff the reference we
# send also has it, so `run()` crops the layout reference to this
# exact canvas before passing it to the model.
PERSON_PREMADE = SheetProfile(
    id="person-premade",
    target_cell=(32, 64),
    target_cols=56,
    target_rows=3,
    # premade-01 has no debug label in the top-left (unlike LimeZu's
    # Modern_Farm sheets), so the mask is a no-op rectangle.
    label_mask_box=(0, 0, 0, 0),
    locomotion_rows={"preview": 0, "idle": 1, "walk": 2},
    # Three additional premade sheets act as style anchors. They all
    # share the exact same layout and pixel-art style; showing Gemini
    # multiple examples of "this is what a townsperson sprite sheet
    # looks like" dramatically improves its chances of matching the
    # style and layout of the output vs a single example.
    style_references=(
        "public/sprites/premade-02.png",
        "public/sprites/premade-04.png",
        "public/sprites/premade-06.png",
    ),
)


SHEET_PROFILES: dict[str, SheetProfile] = {
    ANIMAL_LIVESTOCK24.id: ANIMAL_LIVESTOCK24,
    PERSON_PREMADE.id: PERSON_PREMADE,
}


def _style_references_root() -> Path:
    """Where profile-declared style references are resolved from.

    Defaults to the user's sunny-street checkout (where purchased
    LimeZu sheets live). Overridable via SUNNY_STREET_ROOT env var for
    tests that want to point at a different root.
    """
    import os

    env = os.environ.get("SUNNY_STREET_ROOT")
    if env:
        return Path(env).expanduser()
    return Path.home() / "projects" / "sunny-street"


@dataclass(frozen=True)
class SheetRequest:
    project: Project
    profile: SheetProfile
    prompt: str               # user-supplied subject description
    reference_path: Path      # absolute path to the layout reference PNG
    variants: int             # how many candidates to ask Gemini for
    # Optional second reference image (e.g. an uploaded identity anchor).
    # When provided, it is sent to Gemini alongside the masked layout
    # reference. The model gets two refs: layout from one, identity from
    # the other.
    extra_reference: Path | None = None


@dataclass(frozen=True)
class SheetVariant:
    raw_path: Path            # uncropped Gemini output (for debugging)
    clean_path: Path          # post-processed RGBA sheet (the deliverable)
    sidecar_path: Path
    detected_grid: tuple[int, int]
    raw_size: tuple[int, int]
    final_size: tuple[int, int]


@dataclass(frozen=True)
class SheetResult:
    variants: list[SheetVariant]
    errors: list[str]


def _build_sheet_prompt(profile: SheetProfile, subject: str) -> str:
    """Assemble the Gemini prompt for a target SheetProfile.

    Tone-softened intentionally — the smoke test showed that uppercase
    block headers like 'IDLE row' get hallucinated into the output as
    visible text. Sentence-case description voice avoids that.
    """
    rows_desc_lines: list[str] = []
    if profile.locomotion_rows is not None:
        if "preview" in profile.locomotion_rows:
            rows_desc_lines.append(
                "The first row contains four direction-preview frames in "
                "the leftmost cells (right, up, left, down)."
            )
        if "idle" in profile.locomotion_rows:
            rows_desc_lines.append(
                f"The row at index {profile.locomotion_rows['idle']} contains "
                "stationary idle poses, one per facing direction in the "
                "leftmost four cells (right, up, left, down). Cells beyond "
                "those four are fully transparent."
            )
        if "walk" in profile.locomotion_rows:
            rows_desc_lines.append(
                f"The row at index {profile.locomotion_rows['walk']} contains "
                "a walk cycle: six frames per facing direction grouped left "
                "to right (right, up, left, down). Legs alternate visibly, "
                "body bobs one pixel vertically."
            )
    rows_block = "\n".join(rows_desc_lines)

    cell_w, cell_h = profile.target_cell
    canvas_w = profile.target_cols * cell_w
    canvas_h = profile.target_rows * cell_h
    return (
        f"Generate a pixel-art sprite sheet that matches the grid layout "
        f"of the attached reference image. The reference is used only for "
        f"its grid structure. Design a brand new subject (described below) "
        f"and paint it into the cells.\n\n"
        f"The attached reference is approximately {canvas_w} x {canvas_h} "
        f"pixels: a regular grid of {profile.target_cols} columns by "
        f"{profile.target_rows} rows of {cell_w} x {cell_h} cells. There "
        f"are no borders, no gutters, no text, no labels, no annotations "
        f"of any kind in the desired output. Background is fully transparent.\n\n"
        f"{rows_block}\n\n"
        f"Rows beyond the locomotion rows must be fully transparent. Do "
        f"not draw anything in them.\n\n"
        f"Subject: {subject}\n\n"
        f"The exact same subject must appear in every filled cell. Color "
        f"zones, shape, and proportions must remain pixel-consistent. Do "
        f"not introduce variants or alternate subjects.\n\n"
        f"Style: 16-bit-era top-down 3/4 view pixel art. Crisp 1-pixel "
        f"edges. No anti-aliasing. No dithering gradients. Flat shading "
        f"with two or three tonal steps per region. A 1-pixel dark outline "
        f"on the silhouette using a very dark desaturated tone (not pure "
        f"black). The subject occupies most of each cell, centered "
        f"horizontally, with feet near the bottom edge of the cell. Every "
        f"filled cell has a fully transparent background.\n\n"
        f"Output dimensions: approximately {canvas_w} x {canvas_h} pixels. "
        f"PNG with alpha channel. The output image must contain no written "
        f"characters of any language, no numerals, no row labels, no "
        f"column labels, no debug annotations, no watermarks, no "
        f"signatures, no borders. Do not reuse the reference subject's "
        f"pixels - borrow only the grid geometry.\n"
    )


def _prepare_reference(
    reference_path: Path,
    profile: SheetProfile,
) -> Image.Image:
    """Open, crop, and mask the layout reference before sending to Gemini.

    Two things this function does, both load-bearing:

    1. **Crop to the profile's target canvas**. Gemini 2.5 Flash Image
       preserves the *reference* image's aspect ratio in its output,
       IGNORING any dimensions mentioned in the prompt. If the caller
       passes a 1792x1312 premade sheet but the profile targets a
       1792x192 locomotion band, Gemini would produce 1.37:1 output
       instead of 9.3:1. Cropping the reference to the exact target
       canvas makes Gemini honor the shape automatically. For profiles
       whose reference already matches the target (e.g. animal +
       duck-brown), this is a no-op.

    2. **Mask the asset pack's debug annotation** (e.g. 'ROW: 4 COL: 24'
       in LimeZu sheets). The smoke test proved that Gemini copies
       that text into its output; black-painting the mask box solves
       it deterministically.
    """
    img = Image.open(reference_path).convert("RGBA")

    target_w = profile.target_cols * profile.target_cell[0]
    target_h = profile.target_rows * profile.target_cell[1]
    if img.size != (target_w, target_h):
        if img.width < target_w or img.height < target_h:
            raise ValueError(
                f"reference {reference_path} is {img.size}, smaller than "
                f"profile target {(target_w, target_h)} — cannot crop"
            )
        # Always crop top-left. For premade-style sheets the top rows
        # are the locomotion band the profile targets.
        img = img.crop((0, 0, target_w, target_h))

    x0, y0, x1, y1 = profile.label_mask_box
    if x1 > x0 and y1 > y0:
        draw = ImageDraw.Draw(img)
        draw.rectangle(profile.label_mask_box, fill=(0, 0, 0, 255))
    return img


def _slugify(prompt: str) -> str:
    cleaned = "".join(c if c.isalnum() else "-" for c in prompt.lower())
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-")[:32] or "sheet"


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def run(request: SheetRequest) -> SheetResult:
    """Execute the AI sheet pipeline end-to-end.

    Writes raw + clean PNGs into the project's out/characters/ directory,
    plus a sidecar per clean PNG describing the sheet contract.
    """
    project = request.project
    paths = ProjectPaths(project_root=project.root, output_root=project.output_root)
    paths.ensure("character")
    out_dir = paths.kind_dir("character")

    if not request.reference_path.is_file():
        return SheetResult(variants=[], errors=[f"reference missing: {request.reference_path}"])

    try:
        masked_ref = _prepare_reference(request.reference_path, request.profile)
    except ValueError as err:
        return SheetResult(variants=[], errors=[str(err)])

    backend = GeminiBackend(output_dir=out_dir / "_raw")
    backend.output_dir.mkdir(parents=True, exist_ok=True)

    prompt = _build_sheet_prompt(request.profile, request.prompt)

    # Save the masked reference next to the variants so debugging is easy
    masked_ref_path = backend.output_dir / f"_masked-ref-{request.profile.id}.png"
    masked_ref.save(masked_ref_path)

    refs = [masked_ref_path]

    # Style references: extra sheets from the same profile family that
    # reinforce the layout + style signal. Each one is cropped + masked
    # through the same pipeline so Gemini sees a consistent set of
    # "what sprite sheets look like" examples.
    style_refs_root = _style_references_root()
    for rel in request.profile.style_references:
        style_path = style_refs_root / rel
        if not style_path.is_file():
            # A missing style ref is non-fatal — the primary layout
            # reference still carries the contract. Log and skip.
            print(f"  (style ref missing, skipping: {style_path})")
            continue
        try:
            prepared = _prepare_reference(style_path, request.profile)
        except ValueError:
            continue
        style_out = backend.output_dir / f"_style-ref-{request.profile.id}-{style_path.stem}.png"
        prepared.save(style_out)
        refs.append(style_out)

    if request.extra_reference is not None:
        if not request.extra_reference.is_file():
            return SheetResult(
                variants=[],
                errors=[f"extra reference missing: {request.extra_reference}"],
            )
        refs.append(request.extra_reference)

    raw_paths = backend.generate(
        prompt=prompt,
        refs=refs,
        n=request.variants,
    )

    slug = _slugify(request.prompt)
    ts = _timestamp()
    variants: list[SheetVariant] = []
    errors: list[str] = []

    for idx, raw_path in enumerate(raw_paths, start=1):
        try:
            extracted: ExtractResult = extract_sheet(
                ExtractRequest(
                    src=raw_path,
                    target_cell=request.profile.target_cell,
                    expected_cols=request.profile.target_cols,
                    expected_rows=request.profile.target_rows,
                )
            )
        except Exception as err:  # noqa: BLE001
            errors.append(f"variant {idx} extract failed: {err}")
            continue

        clean_name = f"{slug}-{ts}-v{idx}.png"
        clean_path = out_dir / clean_name
        extracted.image.save(clean_path)

        sidecar = AssetSidecar(
            schema_version=SCHEMA_VERSION,
            kind=AssetKind.CHARACTER,
            layer_target="none",
            tile_size=project.tile_size,
            slug=Path(clean_name).stem,
            source_prompt=f"sheet[{request.profile.id}]: {request.prompt}",
            created_at=_now_iso(),
            animation={
                "system": "ai-sheet",
                "profile": request.profile.id,
                "canvas": {
                    "w": extracted.final_size[0],
                    "h": extracted.final_size[1],
                },
                "frame": {
                    "w": request.profile.target_cell[0],
                    "h": request.profile.target_cell[1],
                },
                "detected_grid": {
                    "cols": extracted.detected_cols,
                    "rows": extracted.detected_rows,
                    "raw_cell_px": extracted.detected_cell_size[0],
                },
                "raw_size": {
                    "w": extracted.raw_size[0],
                    "h": extracted.raw_size[1],
                },
                "direction_order": list(request.profile.direction_order),
                "locomotion_rows": dict(request.profile.locomotion_rows or {}),
                "raw_source": str(raw_path),
                "raw_sha1": hashlib.sha1(raw_path.read_bytes()).hexdigest(),
            },
        )
        sidecar_path = save_sidecar(clean_path, sidecar)

        variants.append(
            SheetVariant(
                raw_path=raw_path,
                clean_path=clean_path,
                sidecar_path=sidecar_path,
                detected_grid=(extracted.detected_cols, extracted.detected_rows),
                raw_size=extracted.raw_size,
                final_size=extracted.final_size,
            )
        )

    return SheetResult(variants=variants, errors=errors)
