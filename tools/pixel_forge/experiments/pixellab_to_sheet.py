"""Convert a PixelLab asset pack into a PERSON_PREMADE sprite sheet.

Companion to the 2026-04-15 multi-view API spike. PixelLab exports
characters as an asset-pack directory:

    <pack>/
    ├── metadata.json
    ├── rotations/
    │   ├── south.png  (single idle frame, per direction)
    │   ├── east.png
    │   ├── north.png
    │   ├── west.png
    │   ├── south-east.png   (diagonals — unused for 4-direction output)
    │   ├── north-east.png
    │   ├── north-west.png
    │   └── south-west.png
    └── animations/
        └── <animation-id>/
            └── <direction>/
                ├── frame_000.png
                ...
                └── frame_{N-1}.png

This script maps that asset pack into sunny-street's PERSON_PREMADE
layout (1792×192 RGBA, 56×3 grid of 32×64 cells, 6 frames per
direction for idle and walk rows, direction order right/up/left/down).

Direction name mapping (PixelLab → sunny-street):

    east  → right
    north → up
    west  → left
    south → down

Cell size mapping (PixelLab 48×48 → PERSON_PREMADE 32×64):

    1. Horizontal center-crop the 48×48 to a 32×48 slice (the character
       silhouette almost always fits inside the middle 32 px because the
       PixelLab template renders characters centered).
    2. Paste that 32×48 slice into a 32×64 transparent canvas at y=16
       so the character sits in the vertical middle of the cell.

Missing-walk fallback:

    If the asset pack has no walk animation for a direction, the walk
    row for that direction is filled with the rotation (idle) frame
    repeated 6 times. This keeps the output sheet loadable even from a
    partial pack — you just see a static character for that direction
    when the game's walk animation plays. The fallback is reported
    loudly in the script's stdout and in a `conversion_report.json`
    sidecar next to the output sheet.

Run:
    .venv/bin/python -m pixel_forge.experiments.pixellab_to_sheet \\
        --pack /path/to/pixellab-char-dir/ \\
        --out /tmp/my-character-sheet.png
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from PIL import Image


# ---- PERSON_PREMADE layout constants (must match sheet.py) ---------------
CELL_W = 32
CELL_H = 64
COLS = 56
ROWS = 3
CANVAS_W = COLS * CELL_W   # 1792
CANVAS_H = ROWS * CELL_H   # 192
FRAMES_PER_DIR = 6
# sunny-street/character-anims.ts direction order
SS_DIRECTIONS = ("right", "up", "left", "down")
# PixelLab uses compass names
PL_DIRECTION_MAP = {
    "right": "east",
    "up": "north",
    "left": "west",
    "down": "south",
}
IDLE_ROW_IDX = 1
WALK_ROW_IDX = 2
PREVIEW_ROW_IDX = 0


@dataclass
class ConversionReport:
    pack_dir: Path
    output_path: Path
    used_animation_id: str | None
    walks_found: dict[str, bool]
    warnings: list[str]


def _load_pack_metadata(pack_dir: Path) -> dict:
    meta_path = pack_dir / "metadata.json"
    if not meta_path.is_file():
        raise FileNotFoundError(f"pack metadata missing: {meta_path}")
    return json.loads(meta_path.read_text())


def _open_rotation(pack_dir: Path, pl_direction: str) -> Image.Image:
    path = pack_dir / "rotations" / f"{pl_direction}.png"
    if not path.is_file():
        raise FileNotFoundError(f"rotation missing: {path}")
    return Image.open(path).convert("RGBA")


def _load_walk_frames(
    pack_dir: Path,
    animation_id: str,
    pl_direction: str,
    frame_count: int,
) -> list[Image.Image] | None:
    """Return N walk frames for one direction, or None if unavailable.

    Reads whatever `frame_NNN.png` files exist in the pack's walk
    directory (up to a reasonable cap) and **ping-pong-extends** the
    sequence to exactly `frame_count` frames. Ping-pong means a 4-frame
    sequence [a, b, c, d] extends to [a, b, c, d, c, b] — smoother
    animation loops than simple repetition because there's no hard
    reset between cycles.

    PixelLab's UI-exported packs typically contain exactly
    frame_count frames (6 per direction), but the `animate_with_text`
    API endpoint currently returns 4 frames per call regardless of the
    `n_frames` parameter. This adapter papers over that discrepancy so
    the same pack format works for both input sources.

    Returns None when the pack has NO walk frames for this direction
    at all — callers fall back to the idle rotation in that case.
    """
    dir_path = pack_dir / "animations" / animation_id / pl_direction
    if not dir_path.is_dir():
        return None

    # Probe for however many contiguous frames exist, up to a sensible
    # upper bound. We stop at the first gap to avoid mixing numbered
    # frames from different animations.
    available: list[Image.Image] = []
    for i in range(32):  # hard cap well above any realistic per-dir count
        fp = dir_path / f"frame_{i:03d}.png"
        if not fp.is_file():
            break
        available.append(Image.open(fp).convert("RGBA"))
    if not available:
        return None

    if len(available) >= frame_count:
        return available[:frame_count]

    # Ping-pong extend: [0, 1, 2, 3] at frame_count=6 -> [0, 1, 2, 3, 2, 1].
    # We build the pattern by walking indices back and forth.
    extended: list[Image.Image] = list(available)
    direction_step = -1
    idx = len(available) - 1
    while len(extended) < frame_count:
        idx = idx + direction_step
        if idx < 0:
            idx = 1
            direction_step = 1
        elif idx >= len(available):
            idx = len(available) - 2
            direction_step = -1
        extended.append(available[idx])
    return extended[:frame_count]


def _remap_cell(src: Image.Image) -> Image.Image:
    """Remap a PixelLab source cell into a PERSON_PREMADE 32×64 cell.

    The source may be any square-ish cell (observed: 48×48 for the
    mannequin template). We horizontally center-crop to CELL_W, then
    paste the resulting slice into a CELL_W × CELL_H transparent canvas
    centered vertically. If the source is smaller than CELL_W in either
    dimension, we pad instead of cropping. If it's taller than CELL_H,
    we scale down proportionally first.
    """
    # Scale down if the source's height exceeds the target cell height.
    if src.height > CELL_H:
        scale = CELL_H / src.height
        new_w = max(1, int(round(src.width * scale)))
        src = src.resize((new_w, CELL_H), Image.NEAREST)

    # Horizontal fit: center-crop if wider than CELL_W, pad if narrower.
    if src.width >= CELL_W:
        x0 = (src.width - CELL_W) // 2
        src = src.crop((x0, 0, x0 + CELL_W, src.height))
        out_w_offset = 0
    else:
        out_w_offset = (CELL_W - src.width) // 2

    # Vertical fit: center inside CELL_H.
    out_h_offset = (CELL_H - src.height) // 2

    canvas = Image.new("RGBA", (CELL_W, CELL_H), (0, 0, 0, 0))
    canvas.paste(src, (out_w_offset, out_h_offset), src)
    return canvas


def _paste_strip(
    canvas: Image.Image,
    frames: Iterable[Image.Image],
    row_idx: int,
    direction_idx: int,
) -> None:
    """Paste a sequence of FRAMES_PER_DIR cells into (row_idx, direction_idx)."""
    x0 = direction_idx * FRAMES_PER_DIR * CELL_W
    y0 = row_idx * CELL_H
    for i, frame in enumerate(frames):
        remapped = _remap_cell(frame)
        canvas.paste(remapped, (x0 + i * CELL_W, y0), remapped)


def convert_pack(
    pack_dir: Path,
    output_path: Path,
    animation_id: str | None = None,
) -> ConversionReport:
    """Assemble a PERSON_PREMADE sheet from a PixelLab asset pack.

    When `animation_id` is None we pick the first animation in
    metadata.json. If the pack has no animations at all, the walk row
    falls back entirely to idle frames.
    """
    metadata = _load_pack_metadata(pack_dir)

    frames_meta = metadata.get("frames", {}) or {}
    animations_meta = frames_meta.get("animations", {}) or {}
    if animation_id is None and animations_meta:
        animation_id = next(iter(animations_meta.keys()))

    canvas = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
    warnings: list[str] = []
    walks_found: dict[str, bool] = {}

    # Preview row (row 0): one idle frame per direction, cols 0..3.
    for dir_idx, ss_dir in enumerate(SS_DIRECTIONS):
        pl_dir = PL_DIRECTION_MAP[ss_dir]
        rot = _open_rotation(pack_dir, pl_dir)
        cell = _remap_cell(rot)
        canvas.paste(cell, (dir_idx * CELL_W, PREVIEW_ROW_IDX * CELL_H), cell)

    # Idle row (row 1): 6 frames per direction.
    #
    # PixelLab rotations have only 1 idle frame per direction; we repeat
    # it FRAMES_PER_DIR times so the idle row is fully populated. A
    # future enhancement could use `animate_with_text(action="idle")` to
    # produce genuine idle variations.
    for dir_idx, ss_dir in enumerate(SS_DIRECTIONS):
        pl_dir = PL_DIRECTION_MAP[ss_dir]
        rot = _open_rotation(pack_dir, pl_dir)
        _paste_strip(canvas, [rot] * FRAMES_PER_DIR, IDLE_ROW_IDX, dir_idx)

    # Walk row (row 2): 6 walk frames per direction, with fallback to
    # the rotation when the pack is missing this direction's walk.
    for dir_idx, ss_dir in enumerate(SS_DIRECTIONS):
        pl_dir = PL_DIRECTION_MAP[ss_dir]
        walk_frames: list[Image.Image] | None = None
        if animation_id is not None:
            walk_frames = _load_walk_frames(
                pack_dir, animation_id, pl_dir, FRAMES_PER_DIR
            )
        if walk_frames is None:
            walks_found[ss_dir] = False
            warnings.append(
                f"walk frames missing for direction {ss_dir!r} "
                f"(PixelLab {pl_dir!r}); falling back to idle"
            )
            rot = _open_rotation(pack_dir, pl_dir)
            _paste_strip(canvas, [rot] * FRAMES_PER_DIR, WALK_ROW_IDX, dir_idx)
        else:
            walks_found[ss_dir] = True
            _paste_strip(canvas, walk_frames, WALK_ROW_IDX, dir_idx)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path)

    report = ConversionReport(
        pack_dir=pack_dir,
        output_path=output_path,
        used_animation_id=animation_id,
        walks_found=walks_found,
        warnings=warnings,
    )
    report_path = output_path.with_suffix(".conversion_report.json")
    report_path.write_text(
        json.dumps(
            {
                "pack_dir": str(pack_dir),
                "output_path": str(output_path),
                "used_animation_id": animation_id,
                "walks_found": walks_found,
                "warnings": warnings,
                "canvas_size": [CANVAS_W, CANVAS_H],
                "cell_size": [CELL_W, CELL_H],
                "frames_per_dir": FRAMES_PER_DIR,
                "direction_order": list(SS_DIRECTIONS),
            },
            indent=2,
        )
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Convert a PixelLab character asset pack into a PERSON_PREMADE "
            "sprite sheet (1792x192 RGBA)."
        )
    )
    parser.add_argument(
        "--pack",
        required=True,
        help="Path to the PixelLab asset pack directory",
    )
    parser.add_argument(
        "--out",
        required=True,
        help="Output PNG path",
    )
    parser.add_argument(
        "--animation-id",
        default=None,
        help="Specific animation ID to use (default: first in metadata)",
    )
    args = parser.parse_args()

    pack_dir = Path(args.pack).expanduser().resolve()
    output_path = Path(args.out).expanduser().resolve()

    if not pack_dir.is_dir():
        print(f"error: pack dir not found: {pack_dir}", file=sys.stderr)
        return 2

    try:
        report = convert_pack(pack_dir, output_path, animation_id=args.animation_id)
    except Exception as err:  # noqa: BLE001
        print(f"error: {type(err).__name__}: {err}", file=sys.stderr)
        return 3

    missing = [d for d, ok in report.walks_found.items() if not ok]
    status = "ok" if not missing else f"partial (walk missing: {','.join(missing)})"
    print(
        f"pixellab_to_sheet: {status} "
        f"canvas={CANVAS_W}x{CANVAS_H} anim={report.used_animation_id} "
        f"out={output_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
