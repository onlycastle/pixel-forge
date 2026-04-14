"""Phase 4 — sunny-street consumer adapter.

Copies pixel-forge outputs into the sunny-street repo's expected layout
and rewrites firstgids so composed maps slot in without colliding with
existing tilesets.

Touchpoints inside sunny-street:
  public/placeables/generated/<textureKey>.png   ← PNG files
  public/maps/placeables-collection.tsj          ← Tiled collection tileset
  public/tilesets/*.png                          ← image-tileset PNGs
  public/maps/<name>.tmj                         ← exported composed maps
  src/phaser/data/placeable-asset-manifest.json  ← runtime manifest

Conventions (taken from the real sunny-street repo):
- textureKey format: `placeable-<slug>-<tile_size>x<tile_size>-<short-hash>`
- placeables-collection.tsj is a Tiled "collection of images" tileset
  (columns=0, tiles[] is authoritative). firstgid is conventionally 10000.
- Image-tilesets live in a pixel-forge-reserved range starting at
  PIXEL_FORGE_RESERVED_BASE (200000). The adapter picks the next free
  slot above the highest pixel-forge firstgid already in use.
- GIDs in Tiled have three top bits reserved for flip flags. Remapping
  MUST preserve those flags.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pixel_forge.assets import AssetKind, AssetSidecar, load_sidecar, sidecar_path_for
from pixel_forge.paths import ProjectPaths
from pixel_forge.project import load_project
from pixel_forge.schemas.placeable_manifest import (
    ManifestEntry,
    ManifestError,
    assert_entry_is_readable,
    load_manifest as load_manifest_entries,
    placeables_collection_path,
    resolve_public_path,
    runtime_manifest_path,
    save_manifest as save_manifest_entries,
    serialize_entry,
)


GID_VALUE_MASK = 0x1FFFFFFF
FLIP_FLAG_MASK = 0xE0000000

PIXEL_FORGE_RESERVED_BASE = 200_000
PLACEABLES_COLLECTION_FIRSTGID = 10_000


@dataclass
class ExportPlaceablesReport:
    copied: int = 0
    skipped: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    texture_keys: dict[str, str] = field(default_factory=dict)  # slug → textureKey


@dataclass
class ExportMapReport:
    map_written: bool = False
    map_name: str = ""
    tilesets_copied: int = 0
    gid_remap_summary: dict[int, int] = field(default_factory=dict)


@dataclass
class SplitReport:
    split_sheets: int = 0
    cells_written: int = 0
    skipped: list[str] = field(default_factory=list)


@dataclass
class ExportCharactersReport:
    copied: int = 0
    overwritten: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    written_paths: dict[str, str] = field(default_factory=dict)  # slug → target path


# ---------- GID primitives ----------


def remap_gid(gid: int, *, mapping: dict[int, int]) -> int:
    """Rewrite a Tiled gid using `mapping`, preserving flip flags.

    Gid 0 (empty cell) is returned unchanged. Unknown base gids are passed
    through — this lets a map that references pre-existing target tilesets
    survive remapping cleanly.
    """
    if gid == 0:
        return 0
    flags = gid & FLIP_FLAG_MASK
    base = gid & GID_VALUE_MASK
    new_base = mapping.get(base, base)
    return flags | new_base


# ---------- textureKey + path helpers ----------


def _short_hash(path: Path) -> str:
    """Deterministic 12-char digest of a file's bytes. Matches the format
    sunny-street's existing placeable keys use."""
    h = hashlib.sha1(path.read_bytes()).hexdigest()
    return h[:12]


def _texture_key_for(sidecar: AssetSidecar, png_path: Path) -> str:
    return (
        f"placeable-{sidecar.slug}-{sidecar.tile_size}x{sidecar.tile_size}"
        f"-{_short_hash(png_path)}"
    )


def _iter_placeable_assets(pf_project_root: Path) -> list[tuple[Path, AssetSidecar]]:
    project = load_project(pf_project_root)
    paths = ProjectPaths(project_root=project.root, output_root=project.output_root)
    placeables_dir = paths.kind_dir("placeable")
    if not placeables_dir.is_dir():
        return []
    out: list[tuple[Path, AssetSidecar]] = []
    for png in sorted(placeables_dir.glob("*.png")):
        if not sidecar_path_for(png).is_file():
            continue
        sidecar = load_sidecar(png)
        if sidecar.kind is not AssetKind.PLACEABLE:
            continue
        out.append((png, sidecar))
    return out


# ---------- placeables export ----------


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _commit_manifest_entry(
    manifest: dict[str, Any],
    target_root: Path,
    *,
    texture_key: str,
    public_path: str,
    source_path: str,
    extra: dict[str, Any] | None = None,
) -> None:
    """Build a manifest entry, verify it resolves to a real file on disk,
    then commit it to the in-memory manifest dict.

    Raises `ManifestError` (loud, actionable) when publicPath doesn't
    resolve — which is the class of bug that produced the "asset catalog
    is mysteriously empty" symptom before the shared schema module
    existed. Failing at write time means the writer gets a clear error
    instead of the reader silently dropping everything.
    """
    entry = ManifestEntry(
        texture_key=texture_key,
        public_path=public_path,
        source_path=source_path,
        extra=dict(extra or {}),
    )
    assert_entry_is_readable(entry, target_root)
    manifest[texture_key] = serialize_entry(entry)


def export_all_placeables(
    pf_project_root: Path,
    target_root: Path,
) -> ExportPlaceablesReport:
    """Copy every placeable in `out/placeables/` into the target repo.

    Idempotent: a texture key already present in the runtime manifest is
    skipped (not re-copied, not duplicated in the collection tsj).
    """
    report = ExportPlaceablesReport()
    assets = _iter_placeable_assets(pf_project_root)
    if not assets:
        return report

    generated_dir = target_root / "public" / "placeables" / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = target_root / "src" / "phaser" / "data" / "placeable-asset-manifest.json"
    manifest: dict[str, Any] = _load_json(manifest_path) if manifest_path.is_file() else {}

    coll_path = target_root / "public" / "maps" / "placeables-collection.tsj"
    coll: dict[str, Any]
    if coll_path.is_file():
        coll = _load_json(coll_path)
    else:
        coll = {
            "name": "placeables-collection",
            "type": "tileset",
            "columns": 0,
            "tilewidth": 16,
            "tileheight": 16,
            "tilecount": 0,
            "tiles": [],
        }

    existing_images = {t.get("image", "") for t in coll.get("tiles", [])}
    next_tile_id = (
        max((t["id"] for t in coll.get("tiles", [])), default=-1) + 1
    )

    for png, sidecar in assets:
        texture_key = _texture_key_for(sidecar, png)
        if texture_key in manifest:
            report.skipped.append(f"{sidecar.slug}: already present as {texture_key}")
            report.texture_keys[sidecar.slug] = texture_key
            continue

        target_png = generated_dir / f"{texture_key}.png"
        if not target_png.exists():
            shutil.copyfile(png, target_png)

        rel_image = f"../placeables/generated/{target_png.name}"
        if rel_image in existing_images:
            # Someone added this file manually but forgot the manifest.
            # Don't double-add to the collection.
            report.skipped.append(f"{sidecar.slug}: image already in collection tsj")
            continue

        from PIL import Image
        with Image.open(target_png) as img:
            iw, ih = img.size

        coll.setdefault("tiles", []).append(
            {
                "id": next_tile_id,
                "image": rel_image,
                "imagewidth": iw,
                "imageheight": ih,
            }
        )
        existing_images.add(rel_image)
        next_tile_id += 1

        _commit_manifest_entry(
            manifest,
            target_root,
            texture_key=texture_key,
            public_path=f"/placeables/generated/{target_png.name}",
            source_path=str(png),
        )
        report.copied += 1
        report.texture_keys[sidecar.slug] = texture_key

    coll["tilecount"] = len(coll.get("tiles", []))
    _write_json(coll_path, coll)
    _write_json(manifest_path, manifest)
    return report


# ---------- character export ----------


def _iter_character_assets(pf_project_root: Path) -> list[tuple[Path, AssetSidecar]]:
    project = load_project(pf_project_root)
    paths = ProjectPaths(project_root=project.root, output_root=project.output_root)
    chars_dir = paths.kind_dir("character")
    if not chars_dir.is_dir():
        return []
    out: list[tuple[Path, AssetSidecar]] = []
    for png in sorted(chars_dir.glob("*.png")):
        if not sidecar_path_for(png).is_file():
            continue
        sidecar = load_sidecar(png)
        if sidecar.kind is not AssetKind.CHARACTER:
            continue
        out.append((png, sidecar))
    return out


def export_all_characters(
    pf_project_root: Path,
    target_root: Path,
) -> ExportCharactersReport:
    """Copy every paperdoll character in `out/characters/` into the target
    repo's `public/sprites/<slug>.png`.

    The sidecar slug is the target filename — so a user who wants the
    output to land in sunny-street's `premade-21` slot should run
    `pf paperdoll --name premade-21 ...` and then export.

    Behavior on existing files: byte-identical files are skipped silently
    (idempotent re-export); content differences are overwritten and
    reported. The runtime manifest hookup is deferred to Phase 2 — for
    now this just lands the PNG bytes in the right place so sunny-street's
    existing static spriteSheets registry can pick them up after a
    rebuild.
    """
    report = ExportCharactersReport()
    assets = _iter_character_assets(pf_project_root)
    if not assets:
        return report

    sprites_dir = target_root / "public" / "sprites"
    sprites_dir.mkdir(parents=True, exist_ok=True)

    for png, sidecar in assets:
        target_png = sprites_dir / f"{sidecar.slug}.png"
        try:
            if target_png.is_file():
                same = target_png.read_bytes() == png.read_bytes()
                if same:
                    report.skipped.append(f"{sidecar.slug}: identical content already at target")
                    report.written_paths[sidecar.slug] = str(target_png)
                    continue
                report.overwritten.append(sidecar.slug)
            shutil.copyfile(png, target_png)
            report.copied += 1
            report.written_paths[sidecar.slug] = str(target_png)
        except Exception as err:  # noqa: BLE001
            report.failed.append(f"{sidecar.slug}: {type(err).__name__}: {err}")
    return report


# ---------- map export ----------


def _find_next_free_firstgid(target_root: Path, needed_cells: int) -> int:
    """Scan existing .tmj files for firstgids in the pixel-forge range and
    return the next free slot."""
    max_end = PIXEL_FORGE_RESERVED_BASE
    maps_dir = target_root / "public" / "maps"
    if not maps_dir.is_dir():
        return max_end
    for tmj_path in maps_dir.glob("*.tmj"):
        try:
            tmj = _load_json(tmj_path)
        except json.JSONDecodeError:
            continue
        for ts in tmj.get("tilesets", []):
            fg = int(ts.get("firstgid", 0))
            if fg < PIXEL_FORGE_RESERVED_BASE:
                continue
            tc = int(ts.get("tilecount", 0))
            end = fg + tc
            if end > max_end:
                max_end = end
    return max_end


def _load_target_placeables_collection(target_root: Path) -> dict[str, Any]:
    path = target_root / "public" / "maps" / "placeables-collection.tsj"
    if not path.is_file():
        return {
            "name": "placeables-collection",
            "columns": 0,
            "tilewidth": 16,
            "tileheight": 16,
            "tilecount": 0,
            "tiles": [],
        }
    return _load_json(path)


def _placeable_image_to_target_local_id(
    target_coll: dict[str, Any],
    composed_image_rel: str,
) -> int | None:
    """Match a composed map's placeable image to its target-local id.

    The composed map references placeables by relative paths like
    `../../placeables/prop-0.png`. The target collection references them as
    `../placeables/generated/placeable-prop-0-16x16-<hash>.png`. We compare
    by slug-stem: the part before the first dash block.
    """
    composed_stem = Path(composed_image_rel).stem  # e.g. "prop-0"
    for tile in target_coll.get("tiles", []):
        target_stem = Path(tile["image"]).stem  # "placeable-prop-0-16x16-<hash>"
        if f"-{composed_stem}-" in target_stem or target_stem.endswith(composed_stem):
            return int(tile["id"])
    return None


def split_pixel_forge_tilesets(
    target_root: Path,
    *,
    tile_size: int = 32,
) -> SplitReport:
    """Slice every `public/tilesets/pixel-forge-*-tiles.png` into individual
    cell PNGs under `public/placeables/generated/`, then register each cell
    in the runtime manifest and the placeables-collection.tsj so the editor
    sees it as an independent placeable.

    The parent sheet is left in place — the sunny-street runtime still
    references it as a Tiled image-tileset for tile-layer painting via
    firstgid-based gids. We are adding a second, file-based view of the
    same pixels for the object-layer placeable browser.

    Idempotent: textureKeys are derived from the cell image content, so
    re-running on a project that's already been split is a no-op.
    """
    from PIL import Image

    report = SplitReport()

    tilesets_dir = target_root / "public" / "tilesets"
    if not tilesets_dir.is_dir():
        return report

    generated_dir = target_root / "public" / "placeables" / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = target_root / "src" / "phaser" / "data" / "placeable-asset-manifest.json"
    manifest: dict[str, Any] = _load_json(manifest_path) if manifest_path.is_file() else {}

    coll_path = target_root / "public" / "maps" / "placeables-collection.tsj"
    coll: dict[str, Any]
    if coll_path.is_file():
        coll = _load_json(coll_path)
    else:
        coll = {
            "name": "placeables-collection",
            "type": "tileset",
            "columns": 0,
            "tilewidth": tile_size,
            "tileheight": tile_size,
            "tilecount": 0,
            "tiles": [],
        }

    existing_images = {t.get("image", "") for t in coll.get("tiles", [])}
    next_tile_id = max((t["id"] for t in coll.get("tiles", [])), default=-1) + 1

    for sheet in sorted(tilesets_dir.glob("pixel-forge-*.png")):
        with Image.open(sheet) as img:
            img.load()
            sw, sh = img.size
            if sw % tile_size != 0 or sh % tile_size != 0:
                report.skipped.append(
                    f"{sheet.name}: dimensions {sw}×{sh} not a multiple of {tile_size}"
                )
                continue
            cols = sw // tile_size
            rows = sh // tile_size
            if cols < 1 or rows < 1:
                report.skipped.append(f"{sheet.name}: no cells to split")
                continue

            this_sheet_cells = 0
            for r in range(rows):
                for c in range(cols):
                    cell_name = f"{sheet.stem}-r{r}-c{c}.png"
                    cell_path = generated_dir / cell_name
                    texture_key = f"placeable-{sheet.stem}-r{r}-c{c}-{tile_size}x{tile_size}"
                    # Virtual sourcePath with the sheet stem as a synthetic
                    # subfolder name. The editor's `_runtime_placeable_category`
                    # derives the category from `parent.name`, so each sheet
                    # becomes its own tight category (e.g. "PF: Beach") instead
                    # of all cells lumping together under a generic "Tilesets".
                    source_path_value = f"../tilesets/{sheet.stem}/{cell_name}"
                    rel_image = f"../placeables/generated/{cell_name}"

                    existing = manifest.get(texture_key)
                    if existing and existing.get("sourcePath") == source_path_value:
                        continue  # already correct, nothing to do
                    if existing:
                        # Stale entry from an earlier splitter run — rewrite
                        # in place so the category derivation updates.
                        existing["sourcePath"] = source_path_value
                        existing.setdefault("splitFromSheet", {}).update(
                            {
                                "sheet": sheet.name,
                                "row": r,
                                "col": c,
                                "cols": cols,
                                "rows": rows,
                            }
                        )
                        # The collection tsj already has this tile entry —
                        # its image path doesn't change, so no tsj edit needed.
                        report.cells_written += 1
                        this_sheet_cells += 1
                        continue

                    if rel_image in existing_images:
                        # Tsj already has this image under a different key —
                        # skip rather than double-register.
                        continue

                    if not cell_path.exists():
                        cell = img.crop(
                            (
                                c * tile_size,
                                r * tile_size,
                                (c + 1) * tile_size,
                                (r + 1) * tile_size,
                            )
                        )
                        cell.save(cell_path)

                    coll.setdefault("tiles", []).append(
                        {
                            "id": next_tile_id,
                            "image": rel_image,
                            "imagewidth": tile_size,
                            "imageheight": tile_size,
                        }
                    )
                    existing_images.add(rel_image)
                    next_tile_id += 1

                    _commit_manifest_entry(
                        manifest,
                        target_root,
                        texture_key=texture_key,
                        public_path=f"/placeables/generated/{cell_name}",
                        source_path=source_path_value,
                        extra={
                            "splitFromSheet": {
                                "sheet": sheet.name,
                                "row": r,
                                "col": c,
                                "cols": cols,
                                "rows": rows,
                            },
                        },
                    )
                    report.cells_written += 1
                    this_sheet_cells += 1

            if this_sheet_cells > 0:
                report.split_sheets += 1

    coll["tilecount"] = len(coll.get("tiles", []))
    _write_json(coll_path, coll)
    _write_json(manifest_path, manifest)
    return report


def export_map(
    map_dir: Path,
    target_root: Path,
) -> ExportMapReport:
    """Copy a composed map into the sunny-street repo, remapping firstgids.

    Expects `map_dir/map.tmj` as the input. Placeables referenced by the
    map must have already been exported via `export_all_placeables` so the
    adapter can resolve each placeable gid to a target-local id.
    """
    report = ExportMapReport()
    tmj_path = map_dir / "map.tmj"
    if not tmj_path.is_file():
        raise FileNotFoundError(f"no map.tmj in {map_dir}")
    tmj = _load_json(tmj_path)

    map_name = map_dir.name
    report.map_name = map_name

    # Count how many cells we need to reserve above the existing max.
    image_tilesets = [
        ts
        for ts in tmj.get("tilesets", [])
        if ts.get("image") and ts.get("name") != "placeables-collection"
    ]
    total_needed = sum(int(ts.get("tilecount", 0)) for ts in image_tilesets)
    new_base = _find_next_free_firstgid(target_root, total_needed)

    # Build the firstgid remap table (old → new) for image tilesets.
    gid_mapping: dict[int, int] = {}
    cursor = new_base
    for ts in image_tilesets:
        old_first = int(ts["firstgid"])
        tilecount = int(ts["tilecount"])
        new_first = cursor
        cursor += tilecount
        for offset in range(tilecount):
            gid_mapping[old_first + offset] = new_first + offset
        # Update tileset's firstgid in-place.
        ts["firstgid"] = new_first
        # Copy the tileset image PNG into the target public/tilesets/.
        src_rel = ts["image"]
        src_abs = (map_dir / src_rel).resolve()
        if src_abs.is_file():
            target_png = target_root / "public" / "tilesets" / f"pixel-forge-{map_name}-{Path(src_rel).name}"
            target_png.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src_abs, target_png)
            # Rewrite the tileset's image reference so it resolves from the
            # target's public/maps/ location.
            ts["image"] = f"../tilesets/{target_png.name}"
            report.tilesets_copied += 1

    # Placeables collection: remap each composed local id to the matching
    # target-local id and drop the collection tileset from the map (the
    # target has its own global collection tsj). We keep the reference via
    # gid only — no inline collection in the exported map.
    target_coll = _load_target_placeables_collection(target_root)
    composed_coll = next(
        (
            ts
            for ts in tmj.get("tilesets", [])
            if ts.get("name") == "placeables-collection"
        ),
        None,
    )
    if composed_coll is not None:
        composed_firstgid = int(composed_coll["firstgid"])
        for local_id, tile in enumerate(composed_coll.get("tiles", [])):
            composed_image_rel = tile["image"]
            target_local = _placeable_image_to_target_local_id(
                target_coll, composed_image_rel
            )
            if target_local is None:
                # Missing from target — caller forgot export_all_placeables,
                # or the placeable simply isn't in the adapter's inventory.
                # Leave the gid unmapped; it will break at runtime and the
                # user will get a clear error they can fix by re-exporting.
                continue
            gid_mapping[composed_firstgid + local_id] = (
                PLACEABLES_COLLECTION_FIRSTGID + target_local
            )

        # Replace the inline composed collection with a reference to the
        # target's global one.
        composed_coll.clear()
        composed_coll["firstgid"] = PLACEABLES_COLLECTION_FIRSTGID
        composed_coll["source"] = "placeables-collection.tsj"

    # Rewrite every gid in tilelayer.data and objectgroup.objects[].gid.
    for layer in tmj.get("layers", []):
        if layer.get("type") == "tilelayer":
            layer["data"] = [
                remap_gid(int(cell), mapping=gid_mapping) for cell in layer["data"]
            ]
        elif layer.get("type") == "objectgroup":
            for obj in layer.get("objects", []):
                if "gid" in obj:
                    obj["gid"] = remap_gid(int(obj["gid"]), mapping=gid_mapping)

    target_map_path = target_root / "public" / "maps" / f"{map_name}.tmj"
    _write_json(target_map_path, tmj)

    report.map_written = True
    report.gid_remap_summary = gid_mapping
    return report
