"""Tests for the farmer action sheet profiles and LimeZu loader.

Uses synthetic fixtures that mimic the LimeZu layout — 1 horizontal row
of (fpd * 4) cells with a colored marker per cell — so we can verify both
the crop_y annotation strip removal AND the 1-row → 4-row reshape without
depending on the real (purchased, non-redistributable) LimeZu pack.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from pixel_forge.actions import (
    FARMER_ACTIONS,
    ActionProfile,
    ActionSourceMissingError,
    load_limezu_action_sheet,
)


def _make_limezu_strip(
    path: Path,
    *,
    cell_w: int,
    cell_h: int,
    fpd: int,
    loop_strip_h: int = 0,
) -> None:
    """Build a LimeZu-shape PNG: 1 row of fpd*4 cells with a color-coded
    marker per cell, optionally followed by a `loop_strip_h`-pixel bright
    band that mimics the "Loop___"/"Throw___" annotation the loader must
    crop away.

    Marker scheme: cell (c) is painted a unique RGB where R encodes
    direction index (0..3), G encodes within-direction frame index
    (0..fpd-1), and B is a constant 200 — this lets tests verify the
    reshape put each cell in the correct output row+col.
    """
    total = fpd * 4
    W = total * cell_w
    H = cell_h + loop_strip_h
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    px = img.load()
    for c in range(total):
        dir_idx = c // fpd
        frame_idx = c % fpd
        color = (dir_idx * 60 + 20, frame_idx * 20 + 10, 200, 255)
        for x in range(c * cell_w + 2, (c + 1) * cell_w - 2):
            for y in range(2, cell_h - 2):
                px[x, y] = color
    if loop_strip_h > 0:
        # bright-white strip so pixel counting can confirm it was removed
        for x in range(W):
            for y in range(cell_h, H):
                px[x, y] = (255, 255, 255, 255)
    img.save(path)


def test_farmer_action_profiles_registered() -> None:
    """All five farmer actions must be present and point at Farmer_1 files."""
    assert set(FARMER_ACTIONS.keys()) == {"chop", "dig", "water", "fishing", "harvest"}
    for key, prof in FARMER_ACTIONS.items():
        assert prof.direction_order == ("right", "up", "left", "down")
        assert prof.limezu_rel_path.startswith("Modern_Farm_v1.2/32x32/Characters_32x32/")
        assert "Farmer_1" in prof.limezu_rel_path
        assert prof.crop_y == (0, prof.cell_h), (
            f"{key}: uniform crop rule expects crop_y=(0, cell_h)"
        )


@pytest.mark.parametrize(
    "key,cell,fpd,total",
    [
        ("chop",    (64,  64), 10,  40),
        ("dig",     (64,  64),  9,  36),
        ("water",   (96,  96), 14,  56),
        ("fishing", (96, 128), 32, 128),
        ("harvest", (32,  64),  9,  36),
    ],
)
def test_farmer_profile_numbers_match_verified_limezu(key, cell, fpd, total) -> None:
    """Spot-check the numbers confirmed by the 2026-04-14 verification pass."""
    p = FARMER_ACTIONS[key]
    assert (p.cell_w, p.cell_h) == cell
    assert p.frames_per_dir == fpd
    assert p.total_frames == total
    # Output reshape preserves total pixel area
    out_w, out_h = p.output_size
    assert out_w == fpd * cell[0]
    assert out_h == 4 * cell[1]


def test_load_limezu_action_sheet_reshapes_1row_to_4rows(tmp_path: Path) -> None:
    """Confirm that source cell c lands at output (row=c//fpd, col=c%fpd).

    Uses a 4x4 synthetic profile (cell 8x8, fpd 4) because it's small
    enough to check every cell by sampling center pixels.
    """
    src = tmp_path / "synth_chop.png"
    _make_limezu_strip(src, cell_w=8, cell_h=8, fpd=4, loop_strip_h=0)

    profile = ActionProfile(
        id="synth",
        cell_w=8,
        cell_h=8,
        frames_per_dir=4,
        crop_y=(0, 8),
        direction_order=("right", "up", "left", "down"),
        limezu_rel_path="ignored",
    )
    out = load_limezu_action_sheet(profile, src_path=src)

    # Output canvas: 4 cols * 8w, 4 rows * 8h = 32x32
    assert out.size == (32, 32)

    # Each source cell c (dir_idx=c//4, frame_idx=c%4) must appear at
    # output (col=frame_idx, row=dir_idx). Sample the center pixel of each.
    for c in range(16):
        dir_idx = c // 4
        frame_idx = c % 4
        center_x = frame_idx * 8 + 4
        center_y = dir_idx * 8 + 4
        r, g, b, a = out.getpixel((center_x, center_y))
        assert a == 255, f"cell {c} expected opaque at ({center_x},{center_y})"
        assert r == dir_idx * 60 + 20, f"cell {c} wrong R channel"
        assert g == frame_idx * 20 + 10, f"cell {c} wrong G channel"
        assert b == 200


def test_load_limezu_action_sheet_crops_annotation_strip(tmp_path: Path) -> None:
    """The loop strip painted at y>=cell_h must not appear in the output."""
    src = tmp_path / "synth_with_loop.png"
    _make_limezu_strip(src, cell_w=8, cell_h=8, fpd=2, loop_strip_h=5)

    profile = ActionProfile(
        id="synth",
        cell_w=8,
        cell_h=8,
        frames_per_dir=2,
        crop_y=(0, 8),
        direction_order=("right", "up", "left", "down"),
        limezu_rel_path="ignored",
    )
    out = load_limezu_action_sheet(profile, src_path=src)

    # Output = 2 cols * 8w × 4 rows * 8h = 16x32
    assert out.size == (16, 32)

    # No pixel anywhere in output should be the bright-white strip color.
    px = out.load()
    white_hits = 0
    for y in range(out.height):
        for x in range(out.width):
            if px[x, y] == (255, 255, 255, 255):
                white_hits += 1
    assert white_hits == 0, "loop strip pixels leaked into output"


def test_load_limezu_action_sheet_rejects_bad_source_width(tmp_path: Path) -> None:
    """Source width must equal fpd*4*cell_w — otherwise something is wrong
    with the pack or the profile and the loader should refuse rather than
    silently produce a corrupt reshape."""
    src = tmp_path / "wrong.png"
    # fpd=2 but write fpd=3 worth of cells (24 wide instead of 16)
    _make_limezu_strip(src, cell_w=4, cell_h=4, fpd=3)

    profile = ActionProfile(
        id="synth",
        cell_w=4,
        cell_h=4,
        frames_per_dir=2,  # expects 2 * 4 * 4 = 32, source is 48
        crop_y=(0, 4),
        direction_order=("right", "up", "left", "down"),
        limezu_rel_path="ignored",
    )
    with pytest.raises(ValueError, match="source width"):
        load_limezu_action_sheet(profile, src_path=src)


def test_load_limezu_action_sheet_missing_file_raises(tmp_path: Path) -> None:
    profile = FARMER_ACTIONS["chop"]
    missing = tmp_path / "does_not_exist.png"
    with pytest.raises(ActionSourceMissingError):
        load_limezu_action_sheet(profile, src_path=missing)
