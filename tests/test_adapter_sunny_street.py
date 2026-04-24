"""Phase 4 — sunny-street consumer adapter tests.

These tests fake a sunny-street repo inside tmp_path with the minimum
structure the adapter touches, run exports against it, and assert that
files land where the real sunny-street editor expects to read them from.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from pixel_forge.adapters.sunny_street import (
    FLIP_FLAG_MASK,
    GID_VALUE_MASK,
    _commit_manifest_entry,
    export_all_placeables,
    export_map,
    remap_gid,
)
from pixel_forge.schemas.placeable_manifest import ManifestError
from pixel_forge.assets import (
    SCHEMA_VERSION,
    AssetKind,
    AssetSidecar,
    Footprint,
    Sheet,
    save_sidecar,
)


# ---------- fake target repo scaffolding ----------


def _mk_png(path: Path, size: tuple[int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", size, (0, 0, 255, 255)).save(path)


def _scaffold_fake_sunny_street(tmp_path: Path) -> Path:
    """Build the minimum sunny-street layout the adapter writes into."""
    root = tmp_path / "fake-sunny-street"
    (root / "public" / "placeables" / "generated").mkdir(parents=True)
    (root / "public" / "tilesets").mkdir(parents=True)
    (root / "public" / "maps").mkdir(parents=True)
    (root / "src" / "phaser" / "data").mkdir(parents=True)

    # Pre-existing placeables-collection.tsj with two historical tiles
    (root / "public" / "maps" / "placeables-collection.tsj").write_text(
        json.dumps(
            {
                "name": "placeables-collection",
                "type": "tileset",
                "columns": 0,
                "tilewidth": 16,
                "tileheight": 16,
                "tilecount": 2,
                "tiles": [
                    {
                        "id": 0,
                        "image": "../placeables/generated/legacy-a.png",
                        "imagewidth": 16,
                        "imageheight": 16,
                    },
                    {
                        "id": 1,
                        "image": "../placeables/generated/legacy-b.png",
                        "imagewidth": 16,
                        "imageheight": 16,
                    },
                ],
            },
            indent=2,
        )
    )

    # Pre-existing runtime manifest with one entry
    (root / "src" / "phaser" / "data" / "placeable-asset-manifest.json").write_text(
        json.dumps(
            {
                "placeable-legacy-a-16x16-aaaaaa": {
                    "textureKey": "placeable-legacy-a-16x16-aaaaaa",
                    "publicPath": "/placeables/generated/legacy-a.png",
                    "sourcePath": "../legacy/a.png",
                }
            },
            indent=2,
        )
    )
    return root


def _scaffold_pf_project_with_placeables(tmp_path: Path, count: int = 2) -> Path:
    project_dir = tmp_path / "pf-proj"
    (project_dir / "style" / "reference").mkdir(parents=True)
    (project_dir / "style" / "palette.hex").write_text("#000000\n#ffffff\n")
    (project_dir / "style" / "prose.md").write_text("adapter test\n")
    (project_dir / "style" / "reference" / "hero.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (project_dir / "project.toml").write_text(
        """
[project]
name = "pf-proj"
tile_size = 16
output_root = "out"

[style]
palette = "style/palette.hex"
prose = "style/prose.md"
hero_reference = "style/reference/hero.png"
extra_references = []

[generation]
backend = "stub"
variants_per_prompt = 1

[validation]
max_off_palette_pixels = 0
"""
    )

    placeables_dir = project_dir / "out" / "placeables"
    placeables_dir.mkdir(parents=True)
    for i in range(count):
        slug = f"prop-{i}"
        _mk_png(placeables_dir / f"{slug}.png", (16, 16))
        save_sidecar(
            placeables_dir / f"{slug}.png",
            AssetSidecar(
                schema_version=SCHEMA_VERSION,
                kind=AssetKind.PLACEABLE,
                layer_target="placeables",
                tile_size=16,
                slug=slug,
                footprint=Footprint(w=1, h=1),
                anchor="bottom-center",
                source_prompt=f"test prop {i}",
                created_at="2026-04-13T00:00:00Z",
            ),
        )
    return project_dir


# ---------- GID remap primitives ----------


def test_remap_gid_preserves_flip_flags() -> None:
    # Top bit = horizontal flip
    H_FLIP = 0x80000000
    gid = H_FLIP | 200003
    assert GID_VALUE_MASK == 0x1FFFFFFF
    assert FLIP_FLAG_MASK == 0xE0000000

    new_gid = remap_gid(gid, mapping={200000: 300000, 200003: 300003})

    # Base gid is remapped, flip flag is preserved
    assert new_gid & GID_VALUE_MASK == 300003
    assert new_gid & FLIP_FLAG_MASK == H_FLIP


def test_remap_gid_leaves_unknown_gids_alone() -> None:
    # If a gid isn't in the mapping (e.g. a farm-tiles gid from the target
    # repo that happens to show up in the map), pass it through unchanged.
    assert remap_gid(42, mapping={200000: 300000}) == 42


def test_remap_gid_zero_stays_zero() -> None:
    # Empty tile cells always encode as gid 0.
    assert remap_gid(0, mapping={200000: 300000}) == 0


# ---------- export_all_placeables ----------


def test_export_all_placeables_copies_pngs_and_appends_manifest(tmp_path: Path) -> None:
    target = _scaffold_fake_sunny_street(tmp_path)
    pf_project = _scaffold_pf_project_with_placeables(tmp_path, count=2)

    report = export_all_placeables(pf_project, target)

    assert report.copied == 2
    # PNGs land in the target's generated directory.
    generated = target / "public" / "placeables" / "generated"
    copied_names = [p.name for p in sorted(generated.glob("*.png"))]
    assert any("prop-0" in n for n in copied_names)
    assert any("prop-1" in n for n in copied_names)

    # placeable-asset-manifest.json has the new entries appended.
    manifest = json.loads(
        (target / "src" / "phaser" / "data" / "placeable-asset-manifest.json").read_text()
    )
    # Legacy entry still there...
    assert "placeable-legacy-a-16x16-aaaaaa" in manifest
    # ...and the two new ones are added.
    new_keys = [k for k in manifest if "prop-" in k]
    assert len(new_keys) == 2
    for key in new_keys:
        entry = manifest[key]
        assert entry["textureKey"] == key
        assert entry["publicPath"].startswith("/placeables/generated/")
        assert "sourcePath" in entry

    # placeables-collection.tsj has the new tiles appended.
    coll = json.loads((target / "public" / "maps" / "placeables-collection.tsj").read_text())
    assert coll["tilecount"] == 4  # 2 legacy + 2 new
    new_tile_images = [t["image"] for t in coll["tiles"] if "prop-" in t["image"]]
    assert len(new_tile_images) == 2


def test_commit_manifest_entry_raises_when_public_path_resolves_nowhere(tmp_path: Path) -> None:
    # Caller lied about publicPath — points to a file that doesn't exist
    # under `public/`. The write-time assert must catch this loudly.
    target = tmp_path / "target"
    (target / "public" / "placeables" / "generated").mkdir(parents=True)

    manifest: dict = {}
    with pytest.raises(ManifestError, match="no file exists"):
        _commit_manifest_entry(
            manifest,
            target,
            texture_key="ghost",
            public_path="/placeables/generated/i-do-not-exist.png",
            source_path="../nowhere.png",
        )
    # Manifest was not committed.
    assert "ghost" not in manifest


def test_commit_manifest_entry_raises_on_double_public_prefix(tmp_path: Path) -> None:
    # Caller put `/public/...` in publicPath — which would resolve to
    # `<target>/public/public/...` once the schema prepends its own
    # `public/`. Exactly the class of bug the contract exists to catch.
    target = tmp_path / "target"
    real_png = target / "public" / "placeables" / "generated" / "x.png"
    real_png.parent.mkdir(parents=True)
    real_png.write_bytes(b"\x89PNG")

    manifest: dict = {}
    with pytest.raises(ManifestError):
        _commit_manifest_entry(
            manifest,
            target,
            texture_key="k",
            public_path="/public/placeables/generated/x.png",  # WRONG
            source_path="../x.png",
        )


def test_export_all_placeables_is_idempotent(tmp_path: Path) -> None:
    target = _scaffold_fake_sunny_street(tmp_path)
    pf_project = _scaffold_pf_project_with_placeables(tmp_path, count=2)

    first = export_all_placeables(pf_project, target)
    second = export_all_placeables(pf_project, target)

    # Second run copies nothing new and does not add duplicate manifest
    # entries.
    assert first.copied == 2
    assert second.copied == 0

    coll = json.loads((target / "public" / "maps" / "placeables-collection.tsj").read_text())
    assert coll["tilecount"] == 4  # still 4, not 6


# ---------- export_map ----------


def _write_composed_map(pf_project: Path) -> Path:
    """Write a minimal out/maps/<name>/ structure the way compose would."""
    map_dir = pf_project / "out" / "maps" / "tiny-beach"
    map_dir.mkdir(parents=True, exist_ok=True)

    # Fake a ground tileset PNG — the adapter copies it into the target.
    ground_png = pf_project / "out" / "tilesets" / "ground" / "ground-v1.png"
    _mk_png(ground_png, (16, 16))
    save_sidecar(
        ground_png,
        AssetSidecar(
            schema_version=SCHEMA_VERSION,
            kind=AssetKind.GROUND_TILESET,
            layer_target="ground",
            tile_size=16,
            slug="ground-v1",
            sheet=Sheet(cols=1, rows=1),
            source_prompt="sand",
            created_at="t",
        ),
    )

    # Minimal TMJ with 1 ground tileset + 1 placeable object referencing
    # the placeables-collection.
    tmj = {
        "type": "map",
        "version": "1.10",
        "orientation": "orthogonal",
        "renderorder": "right-down",
        "infinite": False,
        "width": 2,
        "height": 2,
        "tilewidth": 16,
        "tileheight": 16,
        "nextlayerid": 5,
        "nextobjectid": 2,
        "tilesets": [
            {
                "columns": 1,
                "firstgid": 200000,
                "image": "../../tilesets/ground/ground-v1.png",
                "imagewidth": 16,
                "imageheight": 16,
                "margin": 0,
                "name": "tiny-beach-ground",
                "spacing": 0,
                "tilecount": 1,
                "tileheight": 16,
                "tilewidth": 16,
            },
            {
                "name": "placeables-collection",
                "type": "tileset",
                "columns": 0,
                "tilewidth": 16,
                "tileheight": 16,
                "tilecount": 1,
                "firstgid": 10000,
                "tiles": [
                    {
                        "id": 0,
                        "image": "../../placeables/prop-0.png",
                        "imagewidth": 16,
                        "imageheight": 16,
                    }
                ],
            },
        ],
        "layers": [
            {
                "id": 1,
                "name": "ground",
                "type": "tilelayer",
                "opacity": 1,
                "visible": True,
                "x": 0,
                "y": 0,
                "width": 2,
                "height": 2,
                "data": [200000, 200000, 200000, 200000],
            },
            {
                "id": 2,
                "name": "placeables",
                "type": "objectgroup",
                "opacity": 1,
                "visible": True,
                "x": 0,
                "y": 0,
                "objects": [
                    {
                        "id": 1,
                        "name": "test prop 0",
                        "type": "",
                        "gid": 10000,
                        "x": 0,
                        "y": 16,
                        "width": 16,
                        "height": 16,
                        "rotation": 0,
                        "visible": True,
                        "properties": [],
                    }
                ],
                "draworder": "topdown",
            },
        ],
    }
    (map_dir / "map.tmj").write_text(json.dumps(tmj) + "\n")
    return map_dir


def test_export_map_copies_tilesets_and_rewrites_gid_data(tmp_path: Path) -> None:
    target = _scaffold_fake_sunny_street(tmp_path)
    pf_project = _scaffold_pf_project_with_placeables(tmp_path, count=2)
    map_dir = _write_composed_map(pf_project)

    # Placeables must be exported first so the map's placeable gids can be
    # remapped to the target's collection local ids.
    export_all_placeables(pf_project, target)
    report = export_map(map_dir, target)

    assert report.map_written is True

    # Target map file exists.
    target_map = target / "public" / "maps" / "tiny-beach.tmj"
    assert target_map.exists()

    # Ground tileset PNG copied into target public/tilesets/
    target_ground = target / "public" / "tilesets"
    copied = [p.name for p in target_ground.glob("*ground*")]
    assert copied, f"expected ground tileset to be copied, saw {list(target_ground.iterdir())}"

    # The target map references the ground tileset with a NEW firstgid that
    # does not collide with anything pre-existing. The data[] array was
    # rewritten accordingly.
    tmj_out = json.loads(target_map.read_text())
    ground_ts = next(
        t for t in tmj_out["tilesets"] if "ground" in t.get("name", "") and t.get("image")
    )
    assert ground_ts["firstgid"] != 200000 or ground_ts["firstgid"] >= 200000

    ground_layer = next(l for l in tmj_out["layers"] if l["name"] == "ground")
    assert all(cell == ground_ts["firstgid"] for cell in ground_layer["data"])

    # Placeable object's gid now points into the target's placeables-collection
    # (firstgid 10000 + target-local id for prop-0).
    pl_layer = next(l for l in tmj_out["layers"] if l["name"] == "placeables")
    pl_obj = pl_layer["objects"][0]
    coll = json.loads((target / "public" / "maps" / "placeables-collection.tsj").read_text())
    # Find the local id of prop-0 in the target collection
    prop0 = next(
        t for t in coll["tiles"] if "prop-0" in t["image"]
    )
    assert (pl_obj["gid"] & GID_VALUE_MASK) == 10000 + prop0["id"]
