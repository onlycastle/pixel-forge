"""Phase 0: sidecar schema + load/save round-trip tests.

These tests lock the sidecar JSON contract that every later phase reads.
Changing the schema should force every test here to be updated intentionally.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from pixel_forge.assets import (
    AssetKind,
    AssetSidecar,
    Footprint,
    SchemaError,
    Sheet,
    load_sidecar,
    save_sidecar,
    sidecar_path_for,
)


def test_asset_kind_enum_values() -> None:
    # The authoritative set of kinds. Changing this is a schema-version bump.
    assert {k.value for k in AssetKind} == {
        "ground-tileset",
        "object-tileset",
        "placeable",
        "character",
        "map",
    }


def test_sidecar_path_is_png_stem_plus_meta_json(tmp_path: Path) -> None:
    png = tmp_path / "wooden-cart-empty.png"
    assert sidecar_path_for(png) == tmp_path / "wooden-cart-empty.meta.json"


def test_placeable_sidecar_round_trip(tmp_path: Path) -> None:
    png = tmp_path / "wooden-cart-empty.png"
    sidecar = AssetSidecar(
        schema_version=1,
        kind=AssetKind.PLACEABLE,
        layer_target="placeables",
        tile_size=32,
        slug="wooden-cart-empty",
        footprint=Footprint(w=2, h=1),
        anchor="bottom-center",
        source_prompt="weathered wooden cart, empty bed, side view",
        created_at="2026-04-13T12:00:00Z",
    )
    save_sidecar(png, sidecar)

    loaded = load_sidecar(png)
    assert loaded == sidecar


def test_ground_tileset_sidecar_round_trip(tmp_path: Path) -> None:
    png = tmp_path / "beach-sand.png"
    sidecar = AssetSidecar(
        schema_version=1,
        kind=AssetKind.GROUND_TILESET,
        layer_target="ground",
        tile_size=32,
        slug="beach-sand",
        sheet=Sheet(cols=4, rows=4),
        source_prompt="warm beach sand, 4x4 variations",
        created_at="2026-04-13T12:00:00Z",
    )
    save_sidecar(png, sidecar)
    assert load_sidecar(png) == sidecar


def test_character_sidecar_with_animation(tmp_path: Path) -> None:
    png = tmp_path / "market-clerk-idle.png"
    sidecar = AssetSidecar(
        schema_version=1,
        kind=AssetKind.CHARACTER,
        layer_target="none",
        tile_size=32,
        slug="market-clerk-idle",
        animation={"frame_w": 32, "frame_h": 64, "frame_rate": 6},
        source_prompt="market clerk idle frame",
        created_at="2026-04-13T12:00:00Z",
    )
    save_sidecar(png, sidecar)
    assert load_sidecar(png) == sidecar


def test_placeable_without_footprint_rejected(tmp_path: Path) -> None:
    png = tmp_path / "x.png"
    with pytest.raises(SchemaError, match="footprint"):
        save_sidecar(
            png,
            AssetSidecar(
                schema_version=1,
                kind=AssetKind.PLACEABLE,
                layer_target="placeables",
                tile_size=32,
                slug="x",
                source_prompt="p",
                created_at="t",
            ),
        )


def test_ground_tileset_without_sheet_rejected(tmp_path: Path) -> None:
    png = tmp_path / "x.png"
    with pytest.raises(SchemaError, match="sheet"):
        save_sidecar(
            png,
            AssetSidecar(
                schema_version=1,
                kind=AssetKind.GROUND_TILESET,
                layer_target="ground",
                tile_size=32,
                slug="x",
                source_prompt="p",
                created_at="t",
            ),
        )


def test_placeable_must_target_placeables_layer(tmp_path: Path) -> None:
    png = tmp_path / "x.png"
    with pytest.raises(SchemaError, match="layer_target"):
        save_sidecar(
            png,
            AssetSidecar(
                schema_version=1,
                kind=AssetKind.PLACEABLE,
                layer_target="ground",  # wrong
                tile_size=32,
                slug="x",
                footprint=Footprint(w=1, h=1),
                source_prompt="p",
                created_at="t",
            ),
        )


def test_unknown_schema_version_rejected(tmp_path: Path) -> None:
    png = tmp_path / "x.png"
    sidecar_path_for(png).write_text(
        json.dumps(
            {
                "schema_version": 999,
                "kind": "placeable",
                "layer_target": "placeables",
                "tile_size": 32,
                "slug": "x",
                "footprint": {"w": 1, "h": 1},
                "source_prompt": "p",
                "created_at": "t",
            }
        )
    )
    with pytest.raises(SchemaError, match="schema_version"):
        load_sidecar(png)


def test_save_sidecar_is_atomic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A crash mid-write must not leave a half-written meta.json on disk.
    png = tmp_path / "x.png"
    target = sidecar_path_for(png)

    real_replace = Path.replace

    def boom(self: Path, target: Path) -> None:  # type: ignore[no-redef]
        raise RuntimeError("simulated crash")

    monkeypatch.setattr(Path, "replace", boom)
    with pytest.raises(RuntimeError):
        save_sidecar(
            png,
            AssetSidecar(
                schema_version=1,
                kind=AssetKind.PLACEABLE,
                layer_target="placeables",
                tile_size=32,
                slug="x",
                footprint=Footprint(w=1, h=1),
                source_prompt="p",
                created_at="t",
            ),
        )

    # The final path must not exist since .replace() was the crash point,
    # but the temp file under the same parent should have been cleaned up.
    assert not target.exists()
    monkeypatch.setattr(Path, "replace", real_replace)
    stray_temps = [p for p in tmp_path.glob("*.meta.json.tmp-*")]
    assert stray_temps == [], f"stray temp files remain: {stray_temps}"
