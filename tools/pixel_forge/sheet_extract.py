"""Heuristic post-processor: raw AI output -> clean sprite sheet.

Gemini 2.5 Flash Image (and similar models) honor the *creative* part of
a sprite-sheet prompt — identity, style, row semantics, direction
handling — but they ignore pixel-precise canvas size and cell counts.
Typical raw output for a "768x128, 24x4 cells" request: 2048x512 RGB,
some N x M grid where N and M are NOT what we asked for.

This module turns that messy-but-rich raw output into a clean RGBA sheet
using only deterministic image ops (no CV libs):

1. **Grid detection** — try every cell size K in a sensible range, score
   each by how close (cols, rows) lands to what was requested. The best
   K must divide both image dimensions evenly.

2. **Background removal** — sample the image's edge pixels, take the
   most-common color as background, knock matching pixels (within a
   tolerance) to alpha 0. Handles both opaque-color and rendered-checker
   "transparency".

3. **Per-cell resize + assembly** — slice raw cells, NEAREST-resize each
   to the target frame size (preserves pixel-art crispness), paste back
   into a clean canvas at the detected (cols, rows) layout.

The output preserves the model's actual layout (cols, rows). It does NOT
try to re-arrange cells into a specific game contract — that is a
separate selection step done by the caller, who knows what the target
sprite-sheet contract is.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from PIL import Image


@dataclass(frozen=True)
class ExtractRequest:
    src: Path
    target_cell: tuple[int, int]  # (W, H) of one cell in the final sheet
    expected_cols: int            # hint for grid detection
    expected_rows: int            # hint for grid detection
    bg_tolerance: int = 12        # how close to bg counts as bg


@dataclass(frozen=True)
class ExtractResult:
    image: Image.Image
    detected_cols: int
    detected_rows: int
    detected_cell_size: tuple[int, int]
    background_color: tuple[int, int, int]
    raw_size: tuple[int, int]
    final_size: tuple[int, int]


# Cell sizes the model is likely to pick. Multiples of 16 cover the
# 16/32/48/64 game-art conventions; we also include 24/96/192 because
# image diffusion models sometimes round to 192 / 384 / etc.
_CANDIDATE_CELL_SIZES = (16, 24, 32, 48, 64, 96, 128, 192, 256)


def detect_grid(
    img: Image.Image,
    expected_cols: int,
    expected_rows: int,
    target_cell: tuple[int, int] | None = None,
) -> tuple[tuple[int, int], int, int]:
    """Pick (cell_px=(Kw,Kh), cols, rows) that fits the image.

    When `target_cell` is non-square (e.g. 32x64 for premade-style
    characters), we generate (Kw, Kh) candidate pairs that preserve the
    target aspect ratio — otherwise the heuristic would pick square
    cells and the extractor would squash characters vertically or
    horizontally. When `target_cell` is None or square, we fall back to
    square-cell search for backward compatibility.

    Scoring: row-count match dominates (rows are a stronger structural
    signal than cols because the model usually adjusts cell width before
    it adjusts row count). Among candidates with matching rows, col
    count breaks ties.

    Falls back to gcd(W, H) square cells if no candidate divides both
    dimensions cleanly.
    """
    W, H = img.size

    candidate_pairs: list[tuple[int, int]] = []
    if target_cell is not None and target_cell[0] != target_cell[1]:
        tw, th = target_cell
        ratio_num, ratio_den = th, tw
        # Iterate scale factors producing (Kw, Kh) = (s*tw, s*th) style
        # pairs but allow arbitrary integer scaling of base.
        for base_w in _CANDIDATE_CELL_SIZES:
            kh = base_w * ratio_num // ratio_den
            if base_w * ratio_num % ratio_den != 0:
                continue
            candidate_pairs.append((base_w, kh))
    else:
        for K in _CANDIDATE_CELL_SIZES:
            candidate_pairs.append((K, K))

    candidates: list[tuple[int, int, int, int, int]] = []
    for Kw, Kh in candidate_pairs:
        if W % Kw != 0 or H % Kh != 0:
            continue
        cols = W // Kw
        rows = H // Kh
        if cols < 1 or rows < 1 or cols > 128 or rows > 128:
            continue
        row_err = abs(rows - expected_rows)
        col_err = abs(cols - expected_cols)
        score = row_err * 100 + col_err
        candidates.append((score, Kw, Kh, cols, rows))

    if not candidates:
        from math import gcd
        K = gcd(W, H)
        return ((K, K), W // K, H // K)

    candidates.sort()
    _, Kw, Kh, cols, rows = candidates[0]
    return ((Kw, Kh), cols, rows)


def detect_background(img: Image.Image) -> tuple[int, int, int]:
    """Return the most common color among the image's outermost pixel ring.

    Edge pixels are almost always background for a sprite sheet (foxes
    don't bleed off the canvas). Sampling the ring rather than just the
    4 corners catches bg in the case where one corner happens to overlap
    a sprite.
    """
    rgb = img.convert("RGB")
    W, H = rgb.size
    pixels = rgb.load()

    samples: list[tuple[int, int, int]] = []
    # Top & bottom rows
    for x in range(W):
        samples.append(pixels[x, 0])
        samples.append(pixels[x, H - 1])
    # Left & right cols (skip corners we already counted)
    for y in range(1, H - 1):
        samples.append(pixels[0, y])
        samples.append(pixels[W - 1, y])

    counter = Counter(samples)
    return counter.most_common(1)[0][0]


def remove_background(
    img: Image.Image,
    bg: tuple[int, int, int],
    tolerance: int = 12,
) -> Image.Image:
    """Return an RGBA copy with bg-matching pixels set to alpha=0.

    Pixels whose RGB is within `tolerance` (Manhattan distance per
    channel) of `bg` are made fully transparent. Other pixels keep their
    original RGB and become fully opaque.
    """
    rgba = img.convert("RGBA")
    W, H = rgba.size
    pixels = rgba.load()
    br, bg_g, bb = bg
    for y in range(H):
        for x in range(W):
            r, g, b, _ = pixels[x, y]
            if (
                abs(r - br) <= tolerance
                and abs(g - bg_g) <= tolerance
                and abs(b - bb) <= tolerance
            ):
                pixels[x, y] = (0, 0, 0, 0)
            else:
                pixels[x, y] = (r, g, b, 255)
    return rgba


def extract_sheet(req: ExtractRequest) -> ExtractResult:
    """Convert a raw AI-output sprite sheet into a clean RGBA sheet."""
    raw = Image.open(req.src)
    raw_rgb = raw.convert("RGB")
    raw_size = raw_rgb.size

    (cell_w_raw, cell_h_raw), cols, rows = detect_grid(
        raw_rgb,
        req.expected_cols,
        req.expected_rows,
        target_cell=req.target_cell,
    )

    bg = detect_background(raw_rgb)
    cleaned = remove_background(raw_rgb, bg, tolerance=req.bg_tolerance)

    target_w, target_h = req.target_cell
    final_w = cols * target_w
    final_h = rows * target_h
    final = Image.new("RGBA", (final_w, final_h), (0, 0, 0, 0))

    for r in range(rows):
        for c in range(cols):
            box = (
                c * cell_w_raw,
                r * cell_h_raw,
                (c + 1) * cell_w_raw,
                (r + 1) * cell_h_raw,
            )
            cell = cleaned.crop(box)
            cell_resized = cell.resize(
                (target_w, target_h), Image.Resampling.NEAREST
            )
            final.paste(cell_resized, (c * target_w, r * target_h))

    return ExtractResult(
        image=final,
        detected_cols=cols,
        detected_rows=rows,
        detected_cell_size=(cell_w_raw, cell_h_raw),
        background_color=bg,
        raw_size=raw_size,
        final_size=(final_w, final_h),
    )


def _cli() -> int:
    """Tiny CLI for ad-hoc use: python -m pixel_forge.sheet_extract <src>"""
    import argparse
    import sys

    p = argparse.ArgumentParser(prog="pixel_forge.sheet_extract")
    p.add_argument("--src", required=True, help="Raw AI sprite sheet")
    p.add_argument("--out", required=True, help="Output PNG path")
    p.add_argument("--target-cell", default="32x32", help="Final cell size WxH")
    p.add_argument("--expected-cols", type=int, default=24)
    p.add_argument("--expected-rows", type=int, default=4)
    p.add_argument("--bg-tolerance", type=int, default=12)
    args = p.parse_args()

    tw, th = (int(x) for x in args.target_cell.lower().split("x"))
    res = extract_sheet(
        ExtractRequest(
            src=Path(args.src),
            target_cell=(tw, th),
            expected_cols=args.expected_cols,
            expected_rows=args.expected_rows,
            bg_tolerance=args.bg_tolerance,
        )
    )
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    res.image.save(args.out)
    print(
        f"raw={res.raw_size} cells={res.detected_cols}x{res.detected_rows}"
        f"@{res.detected_cell_size[0]}px bg={res.background_color}"
        f" final={res.final_size} -> {args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
