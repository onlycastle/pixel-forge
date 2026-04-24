"""Farmer action sprite sheet profiles, LimeZu loader, and AI pipeline.

LimeZu Modern_Farm ships farmer action sheets (chop, dig, water, fishing,
harvest) as single horizontal strips where all four directions are
concatenated left-to-right in the order (right, up, left, down). Some
sheets include a "Loop___" / "Throw___" annotation row below the content
row that must be stripped before the sheet is usable.

This module exposes three things:

1. `ActionProfile` + `FARMER_ACTIONS` — per-action records listing the
   exact cell size, frame count, direction order, and LimeZu source path
   for every farmer action we verified end-to-end against the physical
   pack (see /tmp/pf-action-verify/ artifacts from the verification pass).

2. `load_limezu_action_sheet()` — the loader that reads the source PNG,
   crops the annotation strip via the uniform rule `crop_y=(0, cell_h)`,
   and RESHAPES the 1-row × (fpd × 4) source layout into a 4-row × fpd
   layout (row r = direction r). In the AI pipeline this reshaped image
   is used as a LAYOUT REFERENCE sent to Gemini — not as the output.
   sunny-street's phaser code expects multi-row sheets, so the reshape
   is also what downstream consumers see.

3. `run_action_sheet()` — the end-to-end AI pipeline that takes an
   ActionProfile plus a character prompt plus a portrait (identity
   anchor) and asks Gemini to paint the character doing that action
   into the same 4-row direction grid. Mirrors `sheet.run` for the
   locomotion path, so the two pipelines can be reasoned about as a
   pair: one for walking, one per action, both reference-guided and
   identity-anchored.

The LimeZu pack root is user-local and cannot be committed to this repo,
so path resolution goes through `LIMEZU_ASSETS_ROOT` (shared with the
paper-doll profiles module).
"""
from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from pixel_forge.profiles.limezu import assets_root


# Every farmer action profile shares the same LimeZu subdirectory. The
# filenames encode total frame count so profile entries carry it too.
_FARMER_LIMEZU_DIR = "Modern_Farm_v1.2/32x32/Characters_32x32"


@dataclass(frozen=True)
class ActionProfile:
    """One farmer action sprite sheet contract.

    Fields describe both the LimeZu source layout (for loading) and the
    target game layout (for Gemini prompts + sheet_extract).

    - `cell_w`, `cell_h`: size of one animation cell in pixels. Varies
      per action because tool footprint varies (chop/dig 64x64,
      water 96x96, fishing 96x128 for the long rod, harvest 32x64).
    - `frames_per_dir`: frames in one direction's animation loop.
    - `crop_y`: (y0, y1) slice applied to the source PNG to remove the
      "Loop___"/"Throw___" annotation strip. Uniform rule across all
      farmer actions: `(0, cell_h)`, but stored explicitly so future
      non-uniform actions (e.g. packs that put content below a label)
      can override it.
    - `direction_order`: row order in the RESHAPED output sheet. Verified
      visually for all 5 farmer actions to be (right, up, left, down).
    - `limezu_rel_path`: path under LIMEZU_ASSETS_ROOT of the source PNG.
    """
    id: str
    cell_w: int
    cell_h: int
    frames_per_dir: int
    crop_y: tuple[int, int]
    direction_order: tuple[str, ...]
    limezu_rel_path: str

    @property
    def total_frames(self) -> int:
        return self.frames_per_dir * len(self.direction_order)

    @property
    def output_size(self) -> tuple[int, int]:
        """Reshaped output dimensions: (fpd * cell_w, 4 * cell_h)."""
        return (
            self.frames_per_dir * self.cell_w,
            len(self.direction_order) * self.cell_h,
        )


# All values below were verified on 2026-04-14 against the physical
# Modern_Farm_v1.2 pack — see /tmp/pf-action-verify/ for per-action visual
# confirmation (full animation strips, Loop vs cropped comparisons, and
# the direction-order grid). Pixel counts removed by crop were:
#   chop 13.2%  water 12.6%  fishing 23.1%  (dig/harvest have no strip)
FARMER_ACTIONS: dict[str, ActionProfile] = {
    "chop": ActionProfile(
        id="farmer-chop",
        cell_w=64,
        cell_h=64,
        frames_per_dir=10,
        crop_y=(0, 64),
        direction_order=("right", "up", "left", "down"),
        limezu_rel_path=f"{_FARMER_LIMEZU_DIR}/Farmer_1_Chopping_40_frames_32x32.png",
    ),
    "dig": ActionProfile(
        id="farmer-dig",
        cell_w=64,
        cell_h=64,
        frames_per_dir=9,
        crop_y=(0, 64),
        direction_order=("right", "up", "left", "down"),
        limezu_rel_path=f"{_FARMER_LIMEZU_DIR}/Farmer_1_Dig_36_frames_32x32.png",
    ),
    "water": ActionProfile(
        id="farmer-water",
        cell_w=96,
        cell_h=96,
        frames_per_dir=14,
        crop_y=(0, 96),
        direction_order=("right", "up", "left", "down"),
        limezu_rel_path=f"{_FARMER_LIMEZU_DIR}/Farmer_1_Watering_56_frames_32x32.png",
    ),
    "fishing": ActionProfile(
        id="farmer-fishing",
        cell_w=96,
        cell_h=128,
        frames_per_dir=32,
        crop_y=(0, 128),
        direction_order=("right", "up", "left", "down"),
        limezu_rel_path=f"{_FARMER_LIMEZU_DIR}/Farmer_1_Fishing_128_frames_32x32.png",
    ),
    "harvest": ActionProfile(
        id="farmer-harvest",
        cell_w=32,
        cell_h=64,
        frames_per_dir=9,
        crop_y=(0, 64),
        direction_order=("right", "up", "left", "down"),
        limezu_rel_path=f"{_FARMER_LIMEZU_DIR}/Farmer_1_Harvesting_36_frames_32x32.png",
    ),
}


class ActionSourceMissingError(FileNotFoundError):
    """Raised when a LimeZu source PNG cannot be found on disk."""


def resolve_limezu_path(profile: ActionProfile) -> Path:
    """Absolute path to the profile's LimeZu source PNG."""
    return assets_root() / profile.limezu_rel_path


def load_limezu_action_row(
    profile: ActionProfile,
    direction_index: int,
    src_path: Path | None = None,
) -> Image.Image:
    """Extract one direction's horizontal strip from a LimeZu action sheet.

    The LimeZu source is a single 1-row strip of (fpd × 4) cells laid
    out in direction order. This helper slices out just one direction's
    worth — cells `[dir_idx * fpd : (dir_idx + 1) * fpd]` — and returns
    them as a compact (fpd × cell_w, cell_h) RGBA strip.

    Used by the per-direction pipeline in `run_action_sheet`: sending a
    single-row ref forces a much more extreme aspect ratio (e.g. 10:1
    for chop) than the full 4-row layout (2.5:1 for chop), which is
    load-bearing for coaxing Gemini 2.5 Flash Image off its square
    default output canvas. Splitting directions into separate calls
    also preserves the per-cell frame count — the full-grid single
    call collapses to ~6×6 layouts that can't be recovered to 10 × 4.

    The annotation-strip crop (`profile.crop_y`) is applied the same way
    as in `load_limezu_action_sheet`, so this helper is a strict subset
    of that one: the same content row is cropped, then one direction's
    worth is sliced out instead of the whole strip.
    """
    if direction_index < 0 or direction_index >= len(profile.direction_order):
        raise ValueError(
            f"direction_index {direction_index} out of range for profile "
            f"{profile.id} (direction_order={profile.direction_order})"
        )

    path = src_path if src_path is not None else resolve_limezu_path(profile)
    if not path.is_file():
        raise ActionSourceMissingError(
            f"LimeZu source missing for {profile.id}: {path}"
        )

    src = Image.open(path).convert("RGBA")
    W, H = src.size
    cy0, cy1 = profile.crop_y
    if cy1 > H or cy0 < 0 or cy0 >= cy1:
        raise ValueError(
            f"{profile.id}: crop_y={profile.crop_y} is invalid for "
            f"source height {H}"
        )

    expected_w = profile.total_frames * profile.cell_w
    if W != expected_w:
        raise ValueError(
            f"{profile.id}: source width {W} != expected "
            f"{expected_w} (fpd={profile.frames_per_dir} * dirs="
            f"{len(profile.direction_order)} * cell_w={profile.cell_w})"
        )

    content = src.crop((0, cy0, W, cy1))
    fpd = profile.frames_per_dir
    cw, ch = profile.cell_w, profile.cell_h
    x0 = direction_index * fpd * cw
    x1 = (direction_index + 1) * fpd * cw
    row = content.crop((x0, 0, x1, ch))
    return row


def load_limezu_action_sheet(
    profile: ActionProfile,
    src_path: Path | None = None,
) -> Image.Image:
    """Load, crop, and reshape a LimeZu farmer action sheet.

    Returns an RGBA image of size (fpd * cell_w, 4 * cell_h) with one
    direction per row in `profile.direction_order`.

    Steps:

    1. Open `src_path` (or resolve via `LIMEZU_ASSETS_ROOT` if None).
    2. Crop the content row `profile.crop_y` to drop annotation strips.
    3. Reshape the 1-row × (fpd × 4) source into a 4-row × fpd grid:
       source cell index `c` → output (row = c // fpd, col = c % fpd).

    The reshape is what makes the output drop-in compatible with any
    phaser sprite sheet loader expecting one direction per row.
    """
    path = src_path if src_path is not None else resolve_limezu_path(profile)
    if not path.is_file():
        raise ActionSourceMissingError(
            f"LimeZu source missing for {profile.id}: {path}"
        )

    src = Image.open(path).convert("RGBA")
    W, H = src.size
    cy0, cy1 = profile.crop_y
    if cy1 > H or cy0 < 0 or cy0 >= cy1:
        raise ValueError(
            f"{profile.id}: crop_y={profile.crop_y} is invalid for "
            f"source height {H}"
        )

    expected_w = profile.total_frames * profile.cell_w
    if W != expected_w:
        raise ValueError(
            f"{profile.id}: source width {W} != expected "
            f"{expected_w} (fpd={profile.frames_per_dir} * dirs="
            f"{len(profile.direction_order)} * cell_w={profile.cell_w})"
        )

    content = src.crop((0, cy0, W, cy1))

    out_w, out_h = profile.output_size
    out = Image.new("RGBA", (out_w, out_h), (0, 0, 0, 0))
    cw, ch = profile.cell_w, profile.cell_h
    fpd = profile.frames_per_dir
    for c in range(profile.total_frames):
        row = c // fpd
        col = c % fpd
        cell = content.crop((c * cw, 0, (c + 1) * cw, ch))
        out.paste(cell, (col * cw, row * ch))
    return out


# ---------------------------------------------------------------------------
# Asset-type dispatch
# ---------------------------------------------------------------------------
#
# The bundle CLI supports `--asset-type {person,animal,decoration}` so that a
# single code path can build portrait+walking+action-state bundles for
# arbitrary asset types. `FARMER_ACTIONS` is farmer-specific; `HUMAN_ACTIONS`
# is the generalized alias other human professions can contribute to.
#
# `ANIMAL_STATES` and `PLACEABLE_STATES` are deliberately empty in this
# scoping: Modern_Farm animal sheets show high layout variance (inspected
# live: 768×128 chickens, 1536×256 uniform livestock, 2304×384 cow, 2304×832
# dogs, etc.) and no uniform "action" concept maps cleanly to the farmer
# schema. Populating them is a separate design pass.
#
# Today the CLI dispatcher surfaces a clear "no catalog registered" error
# for animal/decoration so the plumbing is locked in and future work can
# simply fill in the dicts without touching cli.py again.

# Catalog key type is str because animal/decoration states may not share
# the farmer ActionProfile shape (animals use states like idle/walk/eat
# with different cell layouts; placeables use states like closed/open).
# Using dict[str, ActionProfile] here is a placeholder that will be
# revisited when the real catalogs are designed.
HUMAN_ACTIONS: dict[str, ActionProfile] = FARMER_ACTIONS
ANIMAL_STATES: dict[str, ActionProfile] = {}
PLACEABLE_STATES: dict[str, ActionProfile] = {}

# Valid asset types for `pf bundle --asset-type`. Kept as a tuple so the
# argparse `choices` binding is immutable and the CLI help enumerates
# them in a stable order.
BUNDLE_ASSET_TYPES: tuple[str, ...] = ("person", "animal", "decoration")

# Dispatch table consulted by `_cmd_bundle`. Each asset type maps to the
# catalog that owns its action/state definitions.
BUNDLE_CATALOG_BY_ASSET_TYPE: dict[str, dict[str, ActionProfile]] = {
    "person": HUMAN_ACTIONS,
    "animal": ANIMAL_STATES,
    "decoration": PLACEABLE_STATES,
}


def get_bundle_catalog(asset_type: str) -> dict[str, ActionProfile]:
    """Return the action/state catalog registered for `asset_type`.

    Raises KeyError if `asset_type` is not a recognized bundle asset type.
    The returned dict may be empty when the asset type is recognized but
    no catalog has been populated yet — callers must handle that case
    explicitly (CLI surfaces it as a validation error).
    """
    return BUNDLE_CATALOG_BY_ASSET_TYPE[asset_type]


# ---------------------------------------------------------------------------
# AI pipeline: generate a per-action sprite sheet matching a given character
# ---------------------------------------------------------------------------
#
# The bundle flow (pipes 1/2/3) wants each character's actions to show the
# GENERATED character, not the LimeZu farmer. This is the module that makes
# that work: it uses `load_limezu_action_sheet()` as the LAYOUT reference
# (grid geometry only), the portrait as the IDENTITY reference, and asks a
# backend (Gemini or a stub in tests) to paint the new character into the
# 4-row direction grid. The raw output goes through the same
# `sheet_extract` post-processor the walking pipeline uses, so the cleanup
# contract is shared.
#
# Design notes that repeat themselves whenever you edit this code:
#
# - The layout reference is written to disk inside the backend's output dir
#   before being passed to the backend. This is load-bearing — some backends
#   (GeminiBackend) expect file paths, not in-memory PIL images. Keeping the
#   reshaped image on disk also gives us a debug artifact when prompts go
#   wrong.
# - `target_cell` for `extract_sheet` is (cell_w, cell_h) of the ActionProfile,
#   NOT the per-row cell of the walking profile (32x64). Actions have their
#   own cell sizes (chop 64x64, fishing 96x128, harvest 32x64, ...).
# - `extract_sheet` already handles non-square cells (see
#   `sheet_extract.detect_grid`), so no special-casing is needed here.
# - The extra_reference (portrait) is OPTIONAL at the pipeline level but
#   REQUIRED at the CLI level for identity-anchoring to be meaningful. The
#   CLI is where we enforce the "portrait must exist" rule; this module
#   happily runs without one to keep it unit-testable.


class ActionSheetPipelineError(Exception):
    """Raised when the action-sheet AI pipeline cannot complete.

    Distinct from `ActionSourceMissingError` (which is about the LimeZu
    pack itself) so callers can tell "the reference file is missing"
    apart from "the AI pipeline failed".
    """


@dataclass(frozen=True)
class ActionSheetRequest:
    """Inputs for one call to `run_action_sheet`.

    `project` is the Project used to anchor output paths (raw + clean +
    sidecar). `profile` is the ActionProfile whose grid contract we're
    targeting (e.g. FARMER_ACTIONS["chop"]). `prompt` is the subject
    description — the character we want painted into the cells.
    `extra_reference` is the identity anchor (typically the generated
    portrait for this character) and is passed to the backend alongside
    the layout reference so the model has a face/outfit/palette to lock
    onto.
    """
    project: "Project"  # noqa: F821 — string-quoted to avoid import cycle
    profile: ActionProfile
    prompt: str
    variants: int
    extra_reference: Path | None = None
    # Optional override of where the LimeZu source lives. Used in tests
    # that don't want to set LIMEZU_ASSETS_ROOT env var. None means "use
    # the profile's registered path under LIMEZU_ASSETS_ROOT".
    layout_source_override: Path | None = None


@dataclass(frozen=True)
class ActionSheetVariant:
    raw_path: Path
    clean_path: Path
    sidecar_path: Path
    detected_grid: tuple[int, int]
    raw_size: tuple[int, int]
    final_size: tuple[int, int]


@dataclass(frozen=True)
class ActionSheetResult:
    variants: list[ActionSheetVariant]
    errors: list[str]
    usage: "UsageRecord | None" = None  # noqa: F821


_ACTION_VERB_GLOSS: dict[str, str] = {
    "chop": "chopping wood with an axe",
    "dig": "digging soil with a shovel",
    "water": "watering crops with a watering can",
    "fishing": "fishing with a rod",
    "harvest": "harvesting crops by hand",
}


def _action_verb_gloss(profile_id: str) -> str:
    verb = profile_id.split("-", 1)[-1] if "-" in profile_id else profile_id
    return _ACTION_VERB_GLOSS.get(verb, f"performing a {verb} action")


def _build_action_row_prompt(
    profile: ActionProfile,
    subject: str,
    direction: str,
) -> str:
    """Assemble the Gemini prompt for ONE direction's action row.

    This prompt is used per-direction because Gemini 2.5 Flash Image
    clamps output canvas to ~1024×1024 when the reference aspect ratio
    is anywhere near square, and a full 10×4 chop grid at 2.5:1 was
    square enough to trigger the clamp (the full grid collapsed to a
    6×6 compositional layout we couldn't extract). Splitting directions
    out gives each call a 10:1 reference strip, extreme enough that
    Gemini honors the aspect and produces a genuinely horizontal
    output. See actions.run_action_sheet for the per-direction loop.
    """
    fpd = profile.frames_per_dir
    cell_w, cell_h = profile.cell_w, profile.cell_h
    canvas_w = fpd * cell_w
    canvas_h = cell_h
    verb_ing = _action_verb_gloss(profile.id)
    ratio_wh = canvas_w / canvas_h

    return (
        f"Generate a pixel-art horizontal strip of EXACTLY {fpd} animation "
        f"frames showing the subject {verb_ing} while facing {direction}. "
        f"The first attached reference image is a {fpd}-cell strip that "
        f"shows the exact pose progression for the {direction}-facing "
        f"animation; copy its pose skeleton cell for cell but design and "
        f"paint the subject described below into each cell.\n\n"
        f"The strip is EXACTLY {fpd} cells across, 1 cell tall. Each cell "
        f"is {cell_w} x {cell_h} pixels. The full strip is approximately "
        f"{canvas_w} x {canvas_h} pixels: a LONG HORIZONTAL STRIP with a "
        f"width-to-height ratio of about {ratio_wh:.1f} to 1. This is "
        f"NOT a square image — it is a narrow horizontal banner. "
        f"Reproduce the {fpd}-cell count exactly as shown in the first "
        f"reference. Do not merge cells, do not add cells, do not wrap "
        f"onto a second row. There are no borders, gutters, text, "
        f"labels, annotations, or watermarks in the output. Background "
        f"is fully transparent.\n\n"
        f"All {fpd} cells depict the same {direction}-facing pose cycle, "
        f"left-to-right from frame 0 (starting pose) to frame {fpd - 1} "
        f"(final pose). The subject's facing direction NEVER changes "
        f"within this strip — every cell faces {direction}.\n\n"
        f"Subject: {subject}\n\n"
        f"A second reference image is attached showing the subject's "
        f"face, outfit, colors, and silhouette. Every cell in the output "
        f"must depict THIS EXACT SAME SUBJECT — keep the face, hair, "
        f"outfit colors, and body proportions pixel-consistent across "
        f"every cell. Do not reuse the first reference's character; "
        f"borrow only its pose skeleton from it.\n\n"
        f"Style: 16-bit-era top-down 3/4 view pixel art. Crisp 1-pixel "
        f"edges. No anti-aliasing. No dithering gradients. Flat shading "
        f"with two or three tonal steps per region. A 1-pixel dark "
        f"outline on the silhouette using a very dark desaturated tone "
        f"(not pure black). The subject occupies most of each cell, "
        f"centered horizontally. Every filled cell has a fully "
        f"transparent background.\n\n"
        f"Output dimensions: a horizontal strip approximately "
        f"{canvas_w} x {canvas_h} pixels. PNG with alpha channel. No "
        f"written characters of any language, no numerals, no row/"
        f"column labels, no debug annotations, no watermarks, no "
        f"signatures, no borders.\n"
    )


def _slugify_subject(prompt: str) -> str:
    cleaned = "".join(c if c.isalnum() else "-" for c in prompt.lower())
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-")[:32] or "action"


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _prepare_portrait_thumbnail(
    extra_reference: Path,
    raw_dir: Path,
    profile_id: str,
) -> tuple[Path | None, str | None]:
    """Return (thumbnail_path, error). Downsizes the identity anchor.

    The portrait is downsized to 256 on the longest side before being
    attached to each per-direction Gemini call. Gemini 2.5 Flash Image
    picks its output aspect ratio by weighing reference images, and a
    1024x1024 portrait was dominant enough to clamp per-row outputs
    back toward square. Shrinking preserves face/outfit/palette signal
    while demoting portrait in the aspect-ratio tiebreaker.

    Returns (None, err) when the portrait cannot be loaded so the
    caller can surface a clean error without crashing the pipeline.
    """
    if not extra_reference.is_file():
        return None, f"extra reference missing: {extra_reference}"
    try:
        portrait_img = Image.open(extra_reference).convert("RGBA")
    except Exception as err:  # noqa: BLE001
        return None, f"extra reference unreadable: {type(err).__name__}: {err}"

    pw, ph = portrait_img.size
    thumb_longest = 256
    p_scale = thumb_longest / max(pw, ph)
    if p_scale < 1:
        portrait_img = portrait_img.resize(
            (max(1, int(round(pw * p_scale))), max(1, int(round(ph * p_scale)))),
            Image.Resampling.LANCZOS,
        )
    thumb_path = raw_dir / f"_identity-thumb-{profile_id}.png"
    portrait_img.save(thumb_path)
    return thumb_path, None


def _content_bbox(rgba: Image.Image) -> tuple[int, int, int, int] | None:
    """Return the bounding box of the non-background content in `rgba`.

    The bbox is the tight rectangle enclosing pixels whose alpha is
    non-zero OR whose RGB differs from the detected background. We use
    this to crop Gemini's raw output to the actual subject area before
    squashing it into the target row shape — otherwise padding/letter-
    boxing would leave the character sitting in a small part of the
    resize target and most pixels would be empty.

    Returns None when the image appears to have no discernible content
    (every pixel is background), so the caller can fall back to the
    un-cropped raw.
    """
    from pixel_forge.sheet_extract import detect_background

    rgb = rgba.convert("RGB")
    bg = detect_background(rgb)
    br, bgc, bb = bg
    W, H = rgba.size
    px = rgba.load()
    tol = 16

    min_x, min_y, max_x, max_y = W, H, -1, -1
    for y in range(H):
        for x in range(W):
            r, g, b, a = px[x, y]
            if a < 8:
                continue
            if (
                abs(r - br) <= tol
                and abs(g - bgc) <= tol
                and abs(b - bb) <= tol
            ):
                continue
            if x < min_x:
                min_x = x
            if y < min_y:
                min_y = y
            if x > max_x:
                max_x = x
            if y > max_y:
                max_y = y

    if max_x < 0:
        return None
    return (min_x, min_y, max_x + 1, max_y + 1)


def _find_content_bands(
    rgba: Image.Image,
    alpha_threshold: int = 8,
    min_band_height: int = 8,
) -> list[tuple[int, int]]:
    """Return (y0, y1) ranges where opaque pixels run contiguously.

    Scans the per-scanline opaque-pixel count and groups contiguous
    rows with ≥2.5% of width opaque into bands, filtering out runs
    shorter than `min_band_height` (noise, stray pixels). Used by the
    row-extractor to pick ONE content strip when Gemini lays out a
    multi-row grid instead of the requested single row.
    """
    W, H = rgba.size
    px = rgba.load()
    min_fill = max(1, W // 40)

    row_fill = [0] * H
    for y in range(H):
        cnt = 0
        for x in range(W):
            if px[x, y][3] >= alpha_threshold:
                cnt += 1
        row_fill[y] = cnt

    bands: list[tuple[int, int]] = []
    in_band = False
    band_start = 0
    for y, fill in enumerate(row_fill):
        if fill >= min_fill and not in_band:
            in_band = True
            band_start = y
        elif fill < min_fill and in_band:
            in_band = False
            if y - band_start >= min_band_height:
                bands.append((band_start, y))
    if in_band and H - band_start >= min_band_height:
        bands.append((band_start, H))

    return bands


def _horizontal_bbox(rgba: Image.Image, alpha_threshold: int = 8) -> tuple[int, int] | None:
    """Return (x0, x1) of the opaque-pixel span across all rows.

    Used after picking a content band to trim any horizontal padding
    around the cells within that band. Returns None if the band has
    no visible content at all.
    """
    W, H = rgba.size
    px = rgba.load()
    min_x, max_x = W, -1
    for y in range(H):
        for x in range(W):
            if px[x, y][3] >= alpha_threshold:
                if x < min_x:
                    min_x = x
                if x > max_x:
                    max_x = x
    if max_x < 0:
        return None
    return (min_x, max_x + 1)


def _extract_action_row(
    raw_path: Path,
    profile: ActionProfile,
    bg_tolerance: int = 16,
) -> Image.Image:
    """Turn a raw per-direction Gemini output into a clean row strip.

    Steps:
      1. Background removal: find the dominant bg color, knock matching
         pixels to alpha 0.
      2. Band detection: find horizontal content bands so we can pick
         one row when Gemini produced a multi-row grid.
      3. Band selection: pick the band with the most total opaque fill,
         which is almost always the primary animation row (Gemini
         sometimes adds smaller preview rows above or below).
      4. Horizontal bbox trim: crop away empty columns around the band
         so the subject fills the target canvas after resize.
      5. Rigid NEAREST resize to (fpd * cell_w, cell_h).

    Why band detection + rigid resize instead of sheet_extract:
    Gemini 2.5 Flash Image consistently outputs ~1024×1024 canvases
    regardless of the reference aspect ratio, and populates them with
    6 cells in a row, 3 rows of 6, or other shapes that aren't cleanly
    divisible by `sheet_extract`'s 2-power candidate cell sizes. Band
    detection on alpha content lets us recover at least the "best row"
    of content for each call. Stretching 6 cells of content across a
    10-cell target canvas distorts horizontally by ~1.6x but keeps the
    character recognizable and the animation legible.
    """
    raw = Image.open(raw_path).convert("RGBA")
    raw_rgb = raw.convert("RGB")

    # Iterated background removal.
    #
    # Gemini 2.5 Flash Image hands us an RGB (no alpha) canvas whose
    # background can contain several visually "neutral" colors at once:
    # the checker-pattern alternation renders as two grays ~25 apart
    # (e.g. 247,247,247 and 222,222,222), AND Gemini sometimes adds a
    # solid black "filmstrip" band around the characters. A single
    # detect_background + remove_background pass only catches one of
    # these because remove_background's tolerance (16) is narrower than
    # the gap between the two checker grays.
    #
    # Instead of widening the tolerance (which would eat character
    # outlines), we iterate: sample the CURRENT OPAQUE edge pixels,
    # pick the most common one, knock out matching pixels, repeat.
    # Skipping already-transparent edges is what makes the loop
    # progress — if we flattened to RGB each iteration, prior-removed
    # pixels would re-appear as black and the loop would stall on
    # black forever. Cap at 5 iterations to avoid pathological loops.
    from collections import Counter

    cleaned_rgba = raw_rgb.convert("RGBA")  # start fully opaque
    W, H = cleaned_rgba.size
    cpx = cleaned_rgba.load()

    for _ in range(5):
        edge_samples: list[tuple[int, int, int]] = []
        for x in range(W):
            if cpx[x, 0][3] > 0:
                r, g, b, _ = cpx[x, 0]
                edge_samples.append((r, g, b))
            if cpx[x, H - 1][3] > 0:
                r, g, b, _ = cpx[x, H - 1]
                edge_samples.append((r, g, b))
        for y in range(1, H - 1):
            if cpx[0, y][3] > 0:
                r, g, b, _ = cpx[0, y]
                edge_samples.append((r, g, b))
            if cpx[W - 1, y][3] > 0:
                r, g, b, _ = cpx[W - 1, y]
                edge_samples.append((r, g, b))

        if not edge_samples:
            break

        bg_color, _ = Counter(edge_samples).most_common(1)[0]
        br, bgc, bb = bg_color

        # Knock out pixels matching the detected bg (tolerance-wide).
        removed = 0
        for y in range(H):
            for x in range(W):
                r, g, b, a = cpx[x, y]
                if a == 0:
                    continue
                if (
                    abs(r - br) <= bg_tolerance
                    and abs(g - bgc) <= bg_tolerance
                    and abs(b - bb) <= bg_tolerance
                ):
                    cpx[x, y] = (0, 0, 0, 0)
                    removed += 1
        if removed == 0:
            break

    target_w = profile.frames_per_dir * profile.cell_w
    target_h = profile.cell_h

    bands = _find_content_bands(cleaned_rgba)
    if not bands:
        # Nothing detectable — fall back to bbox-crop + rigid resize so
        # the pipeline still produces something instead of crashing.
        bbox = _content_bbox(cleaned_rgba)
        if bbox is not None:
            cleaned_rgba = cleaned_rgba.crop(bbox)
        return cleaned_rgba.resize(
            (target_w, target_h), Image.Resampling.NEAREST
        )

    # Build a per-scanline opaque pixel count to score bands by total fill.
    W, H = cleaned_rgba.size
    px = cleaned_rgba.load()
    row_fill = [0] * H
    for y in range(H):
        cnt = 0
        for x in range(W):
            if px[x, y][3] >= 8:
                cnt += 1
        row_fill[y] = cnt

    best_band = max(bands, key=lambda b: sum(row_fill[b[0]:b[1]]))
    y0, y1 = best_band
    band_img = cleaned_rgba.crop((0, y0, W, y1))

    h_bbox = _horizontal_bbox(band_img)
    if h_bbox is not None:
        x0, x1 = h_bbox
        band_img = band_img.crop((x0, 0, x1, band_img.height))

    return band_img.resize(
        (target_w, target_h), Image.Resampling.NEAREST
    )


def run_action_sheet(
    request: ActionSheetRequest,
    backend: "ImageBackend | None" = None,  # noqa: F821
) -> ActionSheetResult:
    """Execute the AI action-sheet pipeline for one profile.

    Architecture: one Gemini call per direction, stitched into the
    final (fpd × cell_w, 4 × cell_h) sheet. Each per-direction call
    uses a single-row LimeZu strip (e.g. 640×64 for chop's right-
    facing row) upscaled to a 10:1 horizontal banner so Gemini's
    aspect-ratio heuristic produces a strip-shaped output instead of
    defaulting to a square 1024×1024 canvas. The portrait is passed
    as a 256px identity thumbnail so it doesn't hijack the aspect.

    Per-direction raw outputs are cropped to their content bbox and
    rigid-resized into (fpd × cell_w, cell_h) rows. The four resulting
    rows are stitched top-to-bottom into the final sheet. A single
    sidecar records the per-direction raw paths for debugging plus
    the profile grid contract.

    This costs `len(direction_order)` backend calls per variant (×4 for
    the farmer profiles). The caller is responsible for anticipating
    the fan-out cost.
    """
    from pixel_forge.assets import (
        SCHEMA_VERSION,
        AssetKind,
        AssetSidecar,
        save_sidecar,
    )
    from pixel_forge.paths import ProjectPaths
    from pixel_forge.usage import UsageRecord

    profile = request.profile
    project = request.project
    paths = ProjectPaths(project_root=project.root, output_root=project.output_root)
    paths.ensure("character")
    out_dir = paths.kind_dir("character")
    raw_dir = out_dir / "_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    # Build the backend once; every per-direction call reuses it so
    # `last_usage` accumulates correctly for the summary path in cli.py.
    if backend is None:
        from pixel_forge.backends.gemini import GeminiBackend

        backend = GeminiBackend(output_dir=raw_dir)
    else:
        b_out = getattr(backend, "output_dir", None)
        if b_out is not None:
            Path(b_out).mkdir(parents=True, exist_ok=True)

    # Portrait thumbnail (optional). Built once and reused across all
    # per-direction calls for this action.
    portrait_thumb_path: Path | None = None
    if request.extra_reference is not None:
        portrait_thumb_path, err = _prepare_portrait_thumbnail(
            request.extra_reference, raw_dir, profile.id
        )
        if err is not None:
            return ActionSheetResult(variants=[], errors=[err])

    slug = _slugify_subject(request.prompt)
    ts = _timestamp()
    variants: list[ActionSheetVariant] = []
    errors: list[str] = []

    # Accumulated usage across all per-direction calls for this action.
    accumulated_usage: UsageRecord | None = None

    for variant_idx in range(1, request.variants + 1):
        direction_row_images: list[Image.Image] = []
        variant_raw_paths: list[Path] = []
        variant_layout_refs: list[Path] = []
        variant_errors: list[str] = []

        for dir_idx, dname in enumerate(profile.direction_order):
            # 1. Build the per-row layout reference.
            try:
                row_img = load_limezu_action_row(
                    profile,
                    dir_idx,
                    src_path=request.layout_source_override,
                )
            except (ActionSourceMissingError, ValueError) as err:
                variant_errors.append(
                    f"variant {variant_idx} {dname}: "
                    f"layout row unavailable: {err}"
                )
                break  # abort this variant entirely — no partial sheets

            # 2. Upscale the row so its longest dimension is ≥ 2048.
            #    NEAREST preserves pixel-art crispness. The goal is to
            #    give Gemini a banner strongly biased toward the strip
            #    aspect ratio so it doesn't clamp to square.
            src_w, src_h = row_img.size
            target_longest = 2048
            scale = max(1, target_longest // max(src_w, src_h))
            if scale > 1:
                row_img = row_img.resize(
                    (src_w * scale, src_h * scale),
                    Image.Resampling.NEAREST,
                )
            row_ref_path = raw_dir / (
                f"_action-row-{profile.id}-{dname}-v{variant_idx}.png"
            )
            row_img.save(row_ref_path)
            variant_layout_refs.append(row_ref_path)

            # 3. Build refs list + prompt.
            refs: list[Path] = [row_ref_path]
            if portrait_thumb_path is not None:
                refs.append(portrait_thumb_path)
            prompt = _build_action_row_prompt(profile, request.prompt, dname)

            # 4. Call the backend for this direction.
            try:
                raw_paths = backend.generate(prompt=prompt, refs=refs, n=1)
            except Exception as err:  # noqa: BLE001
                variant_errors.append(
                    f"variant {variant_idx} {dname}: "
                    f"backend.generate failed: {type(err).__name__}: {err}"
                )
                break

            if not raw_paths:
                variant_errors.append(
                    f"variant {variant_idx} {dname}: "
                    f"backend returned 0 raw outputs"
                )
                break

            # Backends (e.g. GeminiBackend) reuse filenames like
            # `gemini-v1.png` for every call, so consecutive per-direction
            # calls would overwrite each other. Copy each raw into a
            # per-direction archive path so debugging + sha1 bookkeeping
            # reflect the actual per-direction state, not whatever the
            # backend's last call happened to leave on disk.
            archived_raw = raw_dir / (
                f"_action-raw-{profile.id}-{dname}-v{variant_idx}.png"
            )
            shutil.copyfile(raw_paths[0], archived_raw)
            variant_raw_paths.append(archived_raw)

            # Accumulate usage from this call.
            call_usage: UsageRecord | None = getattr(
                backend, "last_usage", None
            )
            if call_usage is not None:
                if accumulated_usage is None:
                    accumulated_usage = call_usage
                else:
                    accumulated_usage = UsageRecord(
                        model=accumulated_usage.model or call_usage.model,
                        prompt_tokens=(
                            accumulated_usage.prompt_tokens
                            + call_usage.prompt_tokens
                        ),
                        output_tokens=(
                            accumulated_usage.output_tokens
                            + call_usage.output_tokens
                        ),
                        total_tokens=(
                            accumulated_usage.total_tokens
                            + call_usage.total_tokens
                        ),
                        call_count=(
                            accumulated_usage.call_count + call_usage.call_count
                        ),
                    )

            # 5. Extract a clean row from the archived raw.
            try:
                row_clean = _extract_action_row(archived_raw, profile)
            except Exception as err:  # noqa: BLE001
                variant_errors.append(
                    f"variant {variant_idx} {dname}: "
                    f"row extract failed: {type(err).__name__}: {err}"
                )
                break
            direction_row_images.append(row_clean)

        if variant_errors:
            errors.extend(variant_errors)
            continue

        if len(direction_row_images) != len(profile.direction_order):
            errors.append(
                f"variant {variant_idx}: expected "
                f"{len(profile.direction_order)} direction rows, "
                f"got {len(direction_row_images)}"
            )
            continue

        # 6. Stitch the 4 rows into the final sheet.
        final_w = profile.frames_per_dir * profile.cell_w
        final_h = len(profile.direction_order) * profile.cell_h
        final = Image.new("RGBA", (final_w, final_h), (0, 0, 0, 0))
        for r, row_img in enumerate(direction_row_images):
            final.paste(row_img, (0, r * profile.cell_h))

        clean_name = f"action-{profile.id}-{slug}-{ts}-v{variant_idx}.png"
        clean_path = out_dir / clean_name
        final.save(clean_path)

        sidecar = AssetSidecar(
            schema_version=SCHEMA_VERSION,
            kind=AssetKind.CHARACTER,
            layer_target="none",
            tile_size=project.tile_size,
            slug=Path(clean_name).stem,
            source_prompt=f"action[{profile.id}]: {request.prompt}",
            created_at=_now_iso(),
            animation={
                "system": "ai-action-sheet",
                "strategy": "per-direction-stitch",
                "profile": profile.id,
                "canvas": {"w": final_w, "h": final_h},
                "frame": {"w": profile.cell_w, "h": profile.cell_h},
                "direction_order": list(profile.direction_order),
                "frames_per_dir": profile.frames_per_dir,
                "per_direction_raw": [str(p) for p in variant_raw_paths],
                "per_direction_raw_sha1": [
                    hashlib.sha1(Path(p).read_bytes()).hexdigest()
                    for p in variant_raw_paths
                ],
                "per_direction_layout_ref": [
                    str(p) for p in variant_layout_refs
                ],
            },
        )
        sidecar_path = save_sidecar(clean_path, sidecar)

        variants.append(
            ActionSheetVariant(
                raw_path=variant_raw_paths[0] if variant_raw_paths else clean_path,
                clean_path=clean_path,
                sidecar_path=sidecar_path,
                detected_grid=(profile.frames_per_dir, len(profile.direction_order)),
                raw_size=(final_w, final_h),
                final_size=(final_w, final_h),
            )
        )

    return ActionSheetResult(
        variants=variants,
        errors=errors,
        usage=accumulated_usage,
    )
