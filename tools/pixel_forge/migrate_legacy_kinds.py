"""Migrate canonical `tile`/`prop` assets from the old layout to `placeable`.

Background:
- Before Phase 1, pixel-forge emitted every single-asset PNG as either
  `--kind tile` (→ out/tiles) or `--kind prop` (→ out/props). Both kinds
  physically produced the same shape (an individual RGBA PNG) — the
  distinction was fictional.
- Phase 1 replaced that with a real taxonomy where the single-stamp kind is
  `placeable` (→ out/placeables) and actual grid sheets get `ground-tileset`
  or `object-tileset`.
- Legacy assets on disk pre-date the new schema, so this module sweeps them
  into the new home and back-fills the sidecar JSON.

Contract:
- Only top-level files in `out/tiles/` and `out/props/` are migrated. The
  `_rejected/` and `_backup-*` subdirs are left alone — they do not hold
  canonical assets.
- Every migrated asset gets a sidecar whose `footprint` is inferred from the
  PNG dimensions via `ceil(pixel / tile_size)`.
- Idempotent: running a second time on an already-migrated project is a
  no-op. Collisions (same slug already present under placeables/) are
  reported in `report.skipped` rather than overwritten.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import ceil
from pathlib import Path
from typing import Any

from PIL import Image

from pixel_forge.assets import (
    SCHEMA_VERSION,
    AssetKind,
    AssetSidecar,
    Footprint,
    save_sidecar,
    sidecar_path_for,
)
from pixel_forge.paths import LEGACY_KIND_SUBDIRS, ProjectPaths
from pixel_forge.project import load_project


@dataclass
class MigrationReport:
    moved: int = 0
    skipped: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    moved_paths: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "moved": self.moved,
            "skipped": list(self.skipped),
            "failed": list(self.failed),
            "moved_paths": list(self.moved_paths),
        }


def _iter_legacy_canonicals(legacy_dir: Path) -> list[Path]:
    """Top-level *.png files in the legacy directory, excluding underscored subdirs."""
    if not legacy_dir.is_dir():
        return []
    out: list[Path] = []
    for entry in sorted(legacy_dir.iterdir()):
        if entry.is_dir():
            # _rejected/, _backup-*/ etc. stay put
            continue
        if entry.suffix.lower() == ".png":
            out.append(entry)
    return out


def _infer_footprint(path: Path, tile_size: int) -> Footprint:
    with Image.open(path) as img:
        w, h = img.size
    return Footprint(
        w=max(1, ceil(w / tile_size)),
        h=max(1, ceil(h / tile_size)),
    )


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


def migrate_project(project_root: Path) -> MigrationReport:
    """Sweep legacy tile/prop files into placeables/ with sidecars.

    Reads `project.toml` for `tile_size`. The project must exist and be
    loadable; otherwise we can't infer footprints correctly.
    """
    project = load_project(project_root)
    paths = ProjectPaths(project_root=project.root, output_root=project.output_root)
    placeables_dir = paths.kind_dir("placeable")
    placeables_dir.mkdir(parents=True, exist_ok=True)

    report = MigrationReport()

    for legacy_kind, legacy_subdir in LEGACY_KIND_SUBDIRS.items():
        legacy_dir = project.root / project.output_root / legacy_subdir
        for src in _iter_legacy_canonicals(legacy_dir):
            dest = placeables_dir / src.name
            sidecar = sidecar_path_for(dest)

            if dest.exists() or sidecar.exists():
                # Collision — do not clobber.
                report.skipped.append(
                    f"{src.name}: destination already exists under placeables/"
                )
                continue

            try:
                footprint = _infer_footprint(src, project.tile_size)
                sidecar_obj = AssetSidecar(
                    schema_version=SCHEMA_VERSION,
                    kind=AssetKind.PLACEABLE,
                    layer_target="placeables",
                    tile_size=project.tile_size,
                    slug=src.stem,
                    footprint=footprint,
                    anchor="bottom-center",
                    source_prompt="<migrated from legacy --kind "
                    f"{legacy_kind}; original prompt unknown>",
                    created_at=_now_iso(),
                    migrated_from=legacy_subdir,
                )
                # Move the PNG, then write the sidecar. If the sidecar write
                # fails we roll the PNG back so the project stays consistent.
                src.rename(dest)
                try:
                    save_sidecar(dest, sidecar_obj)
                except Exception:
                    dest.rename(src)
                    raise
            except Exception as err:  # noqa: BLE001 - top-level boundary
                report.failed.append(f"{src.name}: {type(err).__name__}: {err}")
                continue

            report.moved += 1
            report.moved_paths.append(str(dest))

    return report
