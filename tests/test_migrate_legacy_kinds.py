"""Phase 5 — migrate 78 canonical `tile`/`prop` assets to new `placeable` kind.

Tests use PIL to fabricate PNGs of known dimensions so we can assert that
footprint inference (ceil(px / tile_size)) does the right thing for both
1x1 single-tile icons and multi-tile props.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from pixel_forge.assets import AssetKind, load_sidecar
from pixel_forge.migrate_legacy_kinds import MigrationReport, migrate_project


def _write_png(path: Path, size: tuple[int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", size, (255, 0, 0, 255)).save(path)


def _scaffold_project(tmp_path: Path, tile_size: int = 32) -> Path:
    project_dir = tmp_path / "legacy-proj"
    (project_dir / "style" / "reference").mkdir(parents=True)
    (project_dir / "style" / "palette.hex").write_text(
        "#000000\n#ffffff\n#ff0000\n#00ff00\n"
    )
    (project_dir / "style" / "prose.md").write_text("legacy migration test\n")
    (project_dir / "style" / "reference" / "hero.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (project_dir / "project.toml").write_text(
        f"""
[project]
name = "legacy-proj"
tile_size = {tile_size}
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
    return project_dir


def test_migrate_moves_tile_kind_to_placeable_with_1x1_footprint(tmp_path: Path) -> None:
    project_dir = _scaffold_project(tmp_path)
    # Mimic two legacy --kind tile outputs (single-cell PNGs)
    _write_png(project_dir / "out" / "tiles" / "grass-fill.png", (32, 32))
    _write_png(project_dir / "out" / "tiles" / "beach-boulder.png", (32, 32))

    report = migrate_project(project_dir)

    assert report.moved == 2
    assert report.skipped == []
    assert report.failed == []

    # Files land under placeables/ with sidecars
    new_png = project_dir / "out" / "placeables" / "grass-fill.png"
    assert new_png.exists()
    sidecar = load_sidecar(new_png)
    assert sidecar.kind is AssetKind.PLACEABLE
    assert sidecar.layer_target == "placeables"
    assert sidecar.footprint is not None
    assert sidecar.footprint.w == 1 and sidecar.footprint.h == 1
    assert sidecar.migrated_from == "tiles"
    assert sidecar.tile_size == 32
    assert sidecar.anchor == "bottom-center"

    # Legacy dir keeps its shell but has no canonical files left
    assert not (project_dir / "out" / "tiles" / "grass-fill.png").exists()


def test_migrate_infers_multi_tile_footprint_for_prop_kind(tmp_path: Path) -> None:
    project_dir = _scaffold_project(tmp_path)
    # 2x1 tile wide cart + 3x2 market stall
    _write_png(project_dir / "out" / "props" / "wooden-cart.png", (64, 32))
    _write_png(project_dir / "out" / "props" / "market-stall.png", (96, 64))
    # Odd pixel dimensions round up via ceil.
    _write_png(project_dir / "out" / "props" / "lopsided.png", (65, 33))

    report = migrate_project(project_dir)

    assert report.moved == 3

    def fp(name: str) -> tuple[int, int]:
        sidecar = load_sidecar(project_dir / "out" / "placeables" / name)
        assert sidecar.footprint is not None
        return (sidecar.footprint.w, sidecar.footprint.h)

    assert fp("wooden-cart.png") == (2, 1)
    assert fp("market-stall.png") == (3, 2)
    assert fp("lopsided.png") == (3, 2)  # ceil(65/32)=3, ceil(33/32)=2


def test_migrate_skips_rejected_and_backup_subdirs(tmp_path: Path) -> None:
    project_dir = _scaffold_project(tmp_path)
    _write_png(project_dir / "out" / "tiles" / "canonical.png", (32, 32))
    _write_png(project_dir / "out" / "tiles" / "_rejected" / "bad.png", (32, 32))
    _write_png(project_dir / "out" / "tiles" / "_backup-before-strip" / "old.png", (32, 32))

    report = migrate_project(project_dir)

    # Only the one canonical file moves.
    assert report.moved == 1
    # Rejected and backup files stay where they are.
    assert (project_dir / "out" / "tiles" / "_rejected" / "bad.png").exists()
    assert (project_dir / "out" / "tiles" / "_backup-before-strip" / "old.png").exists()
    # Placeables dir only has the canonical one.
    placeables = sorted((project_dir / "out" / "placeables").glob("*.png"))
    assert len(placeables) == 1
    assert placeables[0].name == "canonical.png"


def test_migrate_is_idempotent(tmp_path: Path) -> None:
    project_dir = _scaffold_project(tmp_path)
    _write_png(project_dir / "out" / "tiles" / "grass-fill.png", (32, 32))

    first = migrate_project(project_dir)
    second = migrate_project(project_dir)

    assert first.moved == 1
    # Second run finds nothing new to move; the file already lives in placeables/
    assert second.moved == 0
    # Not treated as a failure either — idempotent success.
    assert second.failed == []


def test_migrate_preserves_existing_placeables_dir(tmp_path: Path) -> None:
    # If the new placeables/ dir already has a file, migration must not clobber it.
    project_dir = _scaffold_project(tmp_path)
    _write_png(project_dir / "out" / "placeables" / "grass-fill.png", (32, 32))
    # Legacy dir also has the same slug — this is a collision.
    _write_png(project_dir / "out" / "tiles" / "grass-fill.png", (64, 32))

    report = migrate_project(project_dir)

    # Conflict is reported, not silently overwritten.
    assert report.moved == 0
    assert any("grass-fill" in s for s in report.skipped)
    # The pre-existing placeables/ file is untouched.
    existing = Image.open(project_dir / "out" / "placeables" / "grass-fill.png")
    assert existing.size == (32, 32)


def test_migration_report_is_serializable_to_json(tmp_path: Path) -> None:
    project_dir = _scaffold_project(tmp_path)
    _write_png(project_dir / "out" / "tiles" / "a.png", (32, 32))

    report = migrate_project(project_dir)

    payload = report.to_dict()
    assert set(payload.keys()) >= {"moved", "skipped", "failed", "moved_paths"}
    assert payload["moved"] == 1
    assert isinstance(payload["moved_paths"], list)


def test_migrate_uses_project_tile_size_for_footprint_inference(tmp_path: Path) -> None:
    project_dir = _scaffold_project(tmp_path, tile_size=16)
    # At 16px tiles, a 32x32 image is a 2x2 placeable
    _write_png(project_dir / "out" / "tiles" / "shrub.png", (32, 32))

    report = migrate_project(project_dir)
    assert report.moved == 1

    sidecar = load_sidecar(project_dir / "out" / "placeables" / "shrub.png")
    assert sidecar.tile_size == 16
    assert sidecar.footprint is not None
    assert (sidecar.footprint.w, sidecar.footprint.h) == (2, 2)
