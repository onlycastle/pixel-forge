"""Split pixel-forge sheet PNGs in `public/tilesets/` into individual cell
PNGs under `public/placeables/generated/`.

Why: the old `--kind tile` pipeline stitched multiple 32x32 tiles into one
sheet. The sunny-street runtime uses those sheets as Tiled image-tilesets
for `ground` / `object` tile painting, which is correct. But the editor's
Asset Browser (which is file-path-based for placeable stamps) sees the
sheet as a single 3x3 placeable. This module materializes one PNG per cell
so each cell becomes an independent placeable registered in the runtime
manifest and the placeables-collection tileset.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from pixel_forge.adapters.sunny_street import split_pixel_forge_tilesets


def _mk_grid_png(path: Path, cols: int, rows: int, tile_size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGBA", (cols * tile_size, rows * tile_size), (0, 0, 0, 0))
    # Paint each cell a distinct color so tests can verify the slicer
    # preserved the right region.
    for r in range(rows):
        for c in range(cols):
            color = (20 + c * 40, 20 + r * 40, 120, 255)
            for y in range(r * tile_size, (r + 1) * tile_size):
                for x in range(c * tile_size, (c + 1) * tile_size):
                    img.putpixel((x, y), color)
    img.save(path)


def _scaffold_target(tmp_path: Path, tile_size: int = 32) -> Path:
    root = tmp_path / "sunny-street"
    (root / "public" / "tilesets").mkdir(parents=True)
    (root / "public" / "placeables" / "generated").mkdir(parents=True)
    (root / "public" / "maps").mkdir(parents=True)
    (root / "src" / "phaser" / "data").mkdir(parents=True)
    (root / "public" / "maps" / "placeables-collection.tsj").write_text(
        json.dumps(
            {
                "name": "placeables-collection",
                "type": "tileset",
                "columns": 0,
                "tilewidth": tile_size,
                "tileheight": tile_size,
                "tilecount": 0,
                "tiles": [],
            }
        )
    )
    (root / "src" / "phaser" / "data" / "placeable-asset-manifest.json").write_text("{}")
    return root


def test_split_3x3_sheet_produces_9_cell_pngs(tmp_path: Path) -> None:
    target = _scaffold_target(tmp_path)
    _mk_grid_png(
        target / "public" / "tilesets" / "pixel-forge-beach-tiles.png",
        cols=3, rows=3, tile_size=32,
    )

    report = split_pixel_forge_tilesets(target, tile_size=32)

    assert report.split_sheets == 1
    assert report.cells_written == 9

    generated = target / "public" / "placeables" / "generated"
    cell_pngs = sorted(generated.glob("pixel-forge-beach-*.png"))
    assert len(cell_pngs) == 9

    # Each cell PNG is tile_size × tile_size.
    for cp in cell_pngs:
        with Image.open(cp) as img:
            assert img.size == (32, 32)


def test_split_preserves_cell_content(tmp_path: Path) -> None:
    target = _scaffold_target(tmp_path)
    sheet = target / "public" / "tilesets" / "pixel-forge-beach-tiles.png"
    _mk_grid_png(sheet, cols=3, rows=3, tile_size=32)

    split_pixel_forge_tilesets(target, tile_size=32)

    # Row 0 col 0: color (20, 20, 120, 255)
    # Row 2 col 2: color (20 + 2*40, 20 + 2*40, 120, 255) = (100, 100, 120)
    r0c0 = Image.open(
        target / "public" / "placeables" / "generated" / "pixel-forge-beach-tiles-r0-c0.png"
    )
    assert r0c0.getpixel((0, 0)) == (20, 20, 120, 255)

    r2c2 = Image.open(
        target / "public" / "placeables" / "generated" / "pixel-forge-beach-tiles-r2-c2.png"
    )
    assert r2c2.getpixel((0, 0)) == (100, 100, 120, 255)


def test_split_updates_placeables_collection_tsj(tmp_path: Path) -> None:
    target = _scaffold_target(tmp_path)
    _mk_grid_png(
        target / "public" / "tilesets" / "pixel-forge-beach-tiles.png",
        cols=3, rows=3, tile_size=32,
    )

    split_pixel_forge_tilesets(target, tile_size=32)

    coll = json.loads(
        (target / "public" / "maps" / "placeables-collection.tsj").read_text()
    )
    # Collection grew by 9 entries.
    assert coll["tilecount"] == 9
    names = [Path(t["image"]).stem for t in coll["tiles"]]
    assert "pixel-forge-beach-tiles-r0-c0" in names
    assert "pixel-forge-beach-tiles-r2-c2" in names


def test_split_updates_runtime_manifest(tmp_path: Path) -> None:
    target = _scaffold_target(tmp_path)
    _mk_grid_png(
        target / "public" / "tilesets" / "pixel-forge-beach-tiles.png",
        cols=3, rows=3, tile_size=32,
    )

    split_pixel_forge_tilesets(target, tile_size=32)

    manifest = json.loads(
        (target / "src" / "phaser" / "data" / "placeable-asset-manifest.json").read_text()
    )
    # One entry per cell, keyed by textureKey.
    cell_keys = [k for k in manifest if "pixel-forge-beach-tiles" in k]
    assert len(cell_keys) == 9
    for key in cell_keys:
        entry = manifest[key]
        assert entry["publicPath"].startswith("/placeables/generated/")
        # sourcePath uses a virtual subfolder named after the sheet stem so
        # the editor's category derivation groups every cell of one sheet
        # under a single category.
        assert entry["sourcePath"].startswith("../tilesets/pixel-forge-beach-tiles/")
        # Provenance stays in splitFromSheet.
        assert entry["splitFromSheet"]["sheet"] == "pixel-forge-beach-tiles.png"


def test_split_leaves_parent_sheet_in_place(tmp_path: Path) -> None:
    target = _scaffold_target(tmp_path)
    sheet = target / "public" / "tilesets" / "pixel-forge-beach-tiles.png"
    _mk_grid_png(sheet, cols=3, rows=3, tile_size=32)

    split_pixel_forge_tilesets(target, tile_size=32)

    # Parent sheet still exists — beach.tmj's ground/object layers rely on
    # it as a Tiled image-tileset via gid references.
    assert sheet.exists()
    with Image.open(sheet) as img:
        assert img.size == (96, 96)


def test_split_handles_5x2_non_square_sheet(tmp_path: Path) -> None:
    target = _scaffold_target(tmp_path)
    _mk_grid_png(
        target / "public" / "tilesets" / "pixel-forge-farmstead-tiles.png",
        cols=5, rows=2, tile_size=32,
    )

    report = split_pixel_forge_tilesets(target, tile_size=32)
    assert report.cells_written == 10

    cells = sorted(
        (target / "public" / "placeables" / "generated").glob(
            "pixel-forge-farmstead-*.png"
        )
    )
    assert len(cells) == 10


def test_split_is_idempotent(tmp_path: Path) -> None:
    target = _scaffold_target(tmp_path)
    _mk_grid_png(
        target / "public" / "tilesets" / "pixel-forge-beach-tiles.png",
        cols=3, rows=3, tile_size=32,
    )

    first = split_pixel_forge_tilesets(target, tile_size=32)
    second = split_pixel_forge_tilesets(target, tile_size=32)

    assert first.cells_written == 9
    assert second.cells_written == 0  # already split, no new work

    coll = json.loads(
        (target / "public" / "maps" / "placeables-collection.tsj").read_text()
    )
    assert coll["tilecount"] == 9  # not duplicated


def test_split_skips_non_grid_aligned_sheets(tmp_path: Path) -> None:
    # A 97x96 sheet is NOT an exact multiple of tile_size and should be
    # reported as skipped rather than silently mis-sliced.
    target = _scaffold_target(tmp_path)
    bad = target / "public" / "tilesets" / "pixel-forge-bad-tiles.png"
    bad.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (97, 96), (0, 0, 0, 0)).save(bad)

    report = split_pixel_forge_tilesets(target, tile_size=32)

    assert report.cells_written == 0
    assert any("bad-tiles" in s for s in report.skipped)


def test_split_only_touches_pixel_forge_prefixed_sheets(tmp_path: Path) -> None:
    # Farm tilesets and other non-pixel-forge PNGs must be left alone —
    # the splitter is scoped to pixel-forge output only.
    target = _scaffold_target(tmp_path)
    _mk_grid_png(
        target / "public" / "tilesets" / "pixel-forge-beach-tiles.png",
        cols=3, rows=3, tile_size=32,
    )
    _mk_grid_png(
        target / "public" / "tilesets" / "farm-tiles.png",
        cols=32, rows=32, tile_size=32,  # the legitimate Modern Farm sheet
    )

    report = split_pixel_forge_tilesets(target, tile_size=32)

    assert report.cells_written == 9  # only the pixel-forge sheet was split
    # The farm sheet is still intact.
    generated = target / "public" / "placeables" / "generated"
    assert not list(generated.glob("farm-*.png"))
