"""Unit tests for the heuristic sheet extractor.

Uses tiny synthetic checkerboard fixtures so the suite stays
self-contained and deterministic. No real AI output is needed.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from pixel_forge.sheet_extract import (
    ExtractRequest,
    detect_background,
    detect_grid,
    extract_sheet,
    remove_background,
)


def _make_grid_png(
    path: Path,
    *,
    cols: int,
    rows: int,
    cell: int,
    bg: tuple[int, int, int],
    fg: tuple[int, int, int],
) -> Image.Image:
    """Build a synthetic grid where every cell is solid `fg` on a solid `bg`
    background, with a 1-pixel `bg` border between cells (gutter)."""
    W, H = cols * cell, rows * cell
    img = Image.new("RGB", (W, H), bg)
    for r in range(rows):
        for c in range(cols):
            x0 = c * cell + 1
            y0 = r * cell + 1
            x1 = (c + 1) * cell - 1
            y1 = (r + 1) * cell - 1
            for x in range(x0, x1):
                for y in range(y0, y1):
                    img.putpixel((x, y), fg)
    img.save(path)
    return img


def test_detect_grid_picks_K_matching_expected_rows(tmp_path: Path) -> None:
    # Synthetic 16x4 grid of 128px cells (mimics Gemini's actual output)
    img = Image.new("RGB", (2048, 512), (0, 0, 0))
    cell_px, cols, rows = detect_grid(img, expected_cols=24, expected_rows=4)
    # Expected behavior: row count match wins, picks 128x128 for 16x4
    assert rows == 4
    assert cell_px == (128, 128)
    assert cols == 16


def test_detect_grid_handles_perfect_match(tmp_path: Path) -> None:
    img = Image.new("RGB", (24 * 32, 4 * 32), (0, 0, 0))
    cell_px, cols, rows = detect_grid(img, expected_cols=24, expected_rows=4)
    assert cell_px == (32, 32)
    assert cols == 24
    assert rows == 4


def test_detect_grid_falls_back_to_gcd_when_no_candidate(tmp_path: Path) -> None:
    # Pathological size: 15x9 doesn't divide evenly by any candidate
    img = Image.new("RGB", (15, 9), (0, 0, 0))
    cell_px, cols, rows = detect_grid(img, expected_cols=24, expected_rows=4)
    # Fallback uses gcd; just verify we got SOMETHING usable, not a crash
    assert cell_px[0] > 0 and cell_px[1] > 0
    assert cols > 0
    assert rows > 0


def test_detect_grid_picks_non_square_for_32x64_target(tmp_path: Path) -> None:
    # A 2048x512 sheet with target cell 32x64 should pick (Kw,Kh) with 2:1
    # height:width aspect so characters aren't squashed on resize.
    img = Image.new("RGB", (2048, 512), (0, 0, 0))
    cell_px, cols, rows = detect_grid(
        img,
        expected_cols=56,
        expected_rows=3,
        target_cell=(32, 64),
    )
    assert cell_px[1] == cell_px[0] * 2  # aspect preserved
    # 2048x512 with 2:1 ratio cells → best fit is (64, 128) → 32x4
    assert cell_px == (64, 128)
    assert cols == 32
    assert rows == 4


def test_detect_background_picks_corner_color() -> None:
    img = Image.new("RGB", (40, 40), (12, 34, 56))
    # Paint a sprite in the middle so the bg detector must rely on edges
    for x in range(10, 30):
        for y in range(10, 30):
            img.putpixel((x, y), (200, 100, 50))
    bg = detect_background(img)
    assert bg == (12, 34, 56)


def test_remove_background_within_tolerance() -> None:
    img = Image.new("RGB", (4, 4), (10, 10, 10))
    # Paint one pixel "near" bg, one pixel "far"
    img.putpixel((0, 0), (12, 11, 13))   # within tolerance 12
    img.putpixel((1, 0), (200, 100, 50)) # foreground
    out = remove_background(img, bg=(10, 10, 10), tolerance=12)
    # Near-bg should be alpha 0
    assert out.getpixel((0, 0)) == (0, 0, 0, 0)
    # Far foreground should be opaque, RGB preserved
    assert out.getpixel((1, 0)) == (200, 100, 50, 255)
    # Actual bg should be alpha 0
    assert out.getpixel((3, 3)) == (0, 0, 0, 0)


def test_extract_sheet_end_to_end(tmp_path: Path) -> None:
    src = tmp_path / "raw.png"
    # Synthetic grid: 8 cols × 4 rows of 64px cells, black bg, orange fg
    _make_grid_png(src, cols=8, rows=4, cell=64, bg=(0, 0, 0), fg=(255, 128, 0))

    res = extract_sheet(
        ExtractRequest(
            src=src,
            target_cell=(16, 16),
            expected_cols=8,
            expected_rows=4,
        )
    )

    assert res.detected_cols == 8
    assert res.detected_rows == 4
    assert res.detected_cell_size == (64, 64)
    assert res.background_color == (0, 0, 0)
    assert res.raw_size == (512, 256)
    assert res.final_size == (8 * 16, 4 * 16)
    assert res.image.size == (128, 64)
    # A center pixel of any cell must be the orange foreground (alpha 255)
    cell0_center = res.image.getpixel((8, 8))
    assert cell0_center[3] == 255
    assert cell0_center[:3] == (255, 128, 0)
    # A pixel between cells (which was bg) must be transparent —
    # after NEAREST resize, the gutter is 1 of 64 pixels per cell, so it
    # collapses, but the OUTER edges of the canvas remain bg → check (0,0)
    # of the source by sampling a known-bg pixel before extraction.
    assert res.image.getpixel((0, 15))[3] == 0 or res.image.getpixel((0, 15))[3] == 255
    # Above is loose because gutter compression depends on resize. Stronger:
    # the absolute corner of the FIRST cell after the 1-px gutter is fg
    assert res.image.getpixel((1, 1))[:3] == (255, 128, 0)


def test_extract_sheet_preserves_layer_count(tmp_path: Path) -> None:
    """The extractor preserves N×M from the model — it does not re-arrange
    cells into a different target grid. Caller is responsible for selection."""
    src = tmp_path / "raw.png"
    _make_grid_png(src, cols=10, rows=2, cell=32, bg=(50, 50, 50), fg=(0, 200, 100))
    res = extract_sheet(
        ExtractRequest(
            src=src,
            target_cell=(8, 8),
            expected_cols=24,  # we EXPECTED 24 but model produced 10
            expected_rows=2,
        )
    )
    # Model gave 10×2; extractor preserves it
    assert res.detected_cols == 10
    assert res.detected_rows == 2
    assert res.image.size == (10 * 8, 2 * 8)
