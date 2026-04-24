"""Phase 2 — map composer.

Reads a map spec TOML, orchestrates per-kind generate() calls for every
asset the map references, then emits a Tiled-compatible `.tmj` skeleton plus
a `map.json` summary next to it.

Design notes:
- The composer never opens a model connection of its own. It delegates all
  image generation to `generate.run()`, which reads the backend argument.
  Tests pass a `StubBackend`.
- Every generated asset lands in the project's normal `out/<kind-dir>/`
  location (so downstream tooling that already reads those dirs keeps
  working). The TMJ references them via relative paths from the map
  directory — this matches the convention sunny-street already uses for its
  own .tmj files.
- FirstGID allocation for the composed map is self-contained: ground tileset
  starts at `PIXEL_FORGE_BASE_GID` (200000), the object tileset packs right
  after it, and a "placeables-collection" collection tileset sits at
  `PLACEABLES_COLLECTION_GID` (10000) matching sunny-street's historical
  reservation. The Phase 4 adapter may remap firstgids when merging into a
  target repo, preserving flip flags.
- Placeable positions are laid out deterministically on a simple grid so
  two compose runs of the same spec produce byte-identical TMJ output.
  Phase 3 will add LLM-proposed marker objects; for now the markers layer
  is emitted empty.
"""
from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from typing import Callable

from pixel_forge.assets import Footprint, Sheet
from pixel_forge.backends.base import ImageBackend
from pixel_forge.generate import GenerateRequest, run
from pixel_forge.markers import MarkerContext, suggest_markers
from pixel_forge.project import load_project


PIXEL_FORGE_BASE_GID = 200_000
PLACEABLES_COLLECTION_GID = 10_000


class ComposeError(ValueError):
    """Raised when a map spec is missing required fields or is self-inconsistent."""


@dataclass(frozen=True)
class TilesetLayerSpec:
    prompt: str
    sheet: Sheet


@dataclass(frozen=True)
class PlaceableSpec:
    prompt: str
    footprint: Footprint
    count: int = 1


@dataclass(frozen=True)
class MarkerSpec:
    suggest: bool = False
    npcs: list[str] = field(default_factory=list)
    transitions: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class MapSpec:
    name: str
    tile_size: int
    width: int        # in tiles
    height: int       # in tiles
    ground: TilesetLayerSpec
    placeables: list[PlaceableSpec]
    object_layer: TilesetLayerSpec | None = None
    markers: MarkerSpec | None = None


@dataclass(frozen=True)
class ComposeResult:
    tmj_path: Path
    summary_path: Path
    map_dir: Path


# ---------- spec loading ----------


def _require(table: dict[str, Any], key: str, context: str) -> Any:
    if key not in table:
        raise ComposeError(f"{context}: missing required key {key!r}")
    return table[key]


def _parse_sheet(value: Any, context: str) -> Sheet:
    if not isinstance(value, dict):
        raise ComposeError(f"{context}: sheet must be an inline table {{cols, rows}}")
    return Sheet(
        cols=int(_require(value, "cols", context)),
        rows=int(_require(value, "rows", context)),
    )


def _parse_footprint(value: Any, context: str) -> Footprint:
    if not isinstance(value, dict):
        raise ComposeError(f"{context}: footprint must be an inline table {{w, h}}")
    return Footprint(
        w=int(_require(value, "w", context)),
        h=int(_require(value, "h", context)),
    )


def load_spec(spec_path: Path) -> MapSpec:
    if not spec_path.is_file():
        raise ComposeError(f"spec not found: {spec_path}")
    try:
        raw = tomllib.loads(spec_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as err:
        raise ComposeError(f"invalid TOML in {spec_path}: {err}") from err

    map_tbl = raw.get("map")
    if not isinstance(map_tbl, dict):
        raise ComposeError("spec missing [map] table")

    name = _require(map_tbl, "name", "[map]")
    tile_size = int(_require(map_tbl, "tile_size", "[map]"))
    width = int(_require(map_tbl, "width", "[map]"))
    height = int(_require(map_tbl, "height", "[map]"))

    ground_tbl = _require(map_tbl, "ground", "[map]")
    if not isinstance(ground_tbl, dict):
        raise ComposeError("[map.ground] must be a table")
    ground = TilesetLayerSpec(
        prompt=str(_require(ground_tbl, "prompt", "[map.ground]")),
        sheet=_parse_sheet(_require(ground_tbl, "sheet", "[map.ground]"), "[map.ground]"),
    )

    object_layer: TilesetLayerSpec | None = None
    object_tbl = map_tbl.get("object")
    if isinstance(object_tbl, dict):
        object_layer = TilesetLayerSpec(
            prompt=str(_require(object_tbl, "prompt", "[map.object]")),
            sheet=_parse_sheet(
                _require(object_tbl, "sheet", "[map.object]"), "[map.object]"
            ),
        )

    placeables: list[PlaceableSpec] = []
    for idx, entry in enumerate(map_tbl.get("placeables", [])):
        if not isinstance(entry, dict):
            raise ComposeError(f"[[map.placeables]][{idx}]: must be a table")
        placeables.append(
            PlaceableSpec(
                prompt=str(_require(entry, "prompt", f"[[map.placeables]][{idx}]")),
                footprint=_parse_footprint(
                    _require(entry, "footprint", f"[[map.placeables]][{idx}]"),
                    f"[[map.placeables]][{idx}]",
                ),
                count=int(entry.get("count", 1)),
            )
        )

    markers: MarkerSpec | None = None
    markers_tbl = map_tbl.get("markers")
    if isinstance(markers_tbl, dict):
        markers = MarkerSpec(
            suggest=bool(markers_tbl.get("suggest", False)),
            npcs=list(markers_tbl.get("npcs", [])),
            transitions=list(markers_tbl.get("transitions", [])),
        )

    return MapSpec(
        name=str(name),
        tile_size=tile_size,
        width=width,
        height=height,
        ground=ground,
        object_layer=object_layer,
        placeables=placeables,
        markers=markers,
    )


# ---------- firstgid allocation ----------


def allocate_firstgids(tileset_cell_counts: list[int], base: int) -> list[int]:
    """Pack image tilesets into a contiguous firstgid range starting at `base`.

    Each returned value is the `firstgid` for the corresponding tileset. The
    next tileset's firstgid is `previous_firstgid + previous_cell_count`.

    >>> allocate_firstgids([4, 9], base=200000)
    [200000, 200004]
    """
    result: list[int] = []
    cursor = base
    for count in tileset_cell_counts:
        result.append(cursor)
        cursor += count
    return result


# ---------- orchestration ----------


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


def _generate_one(
    project_root: Path,
    backend: ImageBackend,
    kind: str,
    prompt: str,
    *,
    sheet: Sheet | None = None,
    footprint: Footprint | None = None,
) -> Path:
    """Run a single generate() call and return the first variant's PNG path.

    The composer always takes the first variant — review/promote is a
    separate workflow and not part of compose.
    """
    project = load_project(project_root)
    result = run(
        GenerateRequest(
            project=project,
            kind=kind,
            prompt=prompt,
            variants=1,
            sheet=sheet,
            footprint=footprint,
        ),
        backend=backend,
    )
    if not result.variants:
        raise ComposeError(f"generate({kind}) returned no variants for prompt {prompt!r}")
    return result.variants[0].path


def _relative_to_map(map_dir: Path, target: Path) -> str:
    """Relative path from the map directory to an asset, for TMJ references."""
    # Use os.path.relpath to get ../ hops when needed.
    import os

    return os.path.relpath(target, start=map_dir)


def _build_image_tileset(
    name: str,
    image_path_from_map: str,
    image_width: int,
    image_height: int,
    tile_size: int,
    firstgid: int,
) -> dict[str, Any]:
    cols = image_width // tile_size
    rows = image_height // tile_size
    return {
        "columns": cols,
        "firstgid": firstgid,
        "image": image_path_from_map,
        "imagewidth": image_width,
        "imageheight": image_height,
        "margin": 0,
        "name": name,
        "spacing": 0,
        "tilecount": cols * rows,
        "tileheight": tile_size,
        "tilewidth": tile_size,
    }


def _build_placeables_collection(
    tiles: list[dict[str, Any]],
    firstgid: int,
    tile_size: int,
) -> dict[str, Any]:
    return {
        "name": "placeables-collection",
        "type": "tileset",
        "columns": 0,
        "tilewidth": tile_size,
        "tileheight": tile_size,
        "tilecount": len(tiles),
        "firstgid": firstgid,
        "tiles": tiles,
    }


def _distribute_placeables_on_grid(
    placeables: list[PlaceableSpec],
    map_w: int,
    map_h: int,
) -> list[tuple[PlaceableSpec, int, int]]:
    """Deterministic grid layout — walks row by row, leaving a 1-tile margin.

    Returned coordinates are in tiles. Overflow is not an error — the
    composer relies on the spec author to keep counts sane.
    """
    placements: list[tuple[PlaceableSpec, int, int]] = []
    col = 1
    row = 1
    for spec in placeables:
        for _ in range(spec.count):
            if col + spec.footprint.w > map_w - 1:
                col = 1
                row += max(1, spec.footprint.h) + 1
            placements.append((spec, col, row))
            col += spec.footprint.w + 1
    return placements


def compose(
    spec_path: Path,
    project_root: Path,
    backend: ImageBackend,
    *,
    text_llm: Callable[[str], str] | None = None,
) -> ComposeResult:
    """Run the composer.

    `text_llm` is an optional callable used for marker suggestion when the
    spec has `[map.markers] suggest = true`. Pass a deterministic stub in
    tests; production wires it to `pixel_forge.backends.gemini_text.gemini_text_llm`.
    """
    spec = load_spec(spec_path)
    project = load_project(project_root)
    if spec.tile_size != project.tile_size:
        raise ComposeError(
            f"spec tile_size {spec.tile_size} does not match project "
            f"tile_size {project.tile_size}"
        )

    map_dir = project_root / project.output_root / "maps" / spec.name
    map_dir.mkdir(parents=True, exist_ok=True)

    summary: dict[str, Any] = {
        "spec_name": spec.name,
        "spec_path": str(spec_path.resolve()),
        "composed_at": _now_iso(),
        "prompts": {},
        "assets": [],
    }

    # --- generate ground tileset (always required) ---
    ground_png = _generate_one(
        project_root,
        backend,
        kind="ground-tileset",
        prompt=spec.ground.prompt,
        sheet=spec.ground.sheet,
    )
    summary["prompts"]["ground"] = spec.ground.prompt
    summary["assets"].append({"layer": "ground", "path": str(ground_png)})

    # --- generate object tileset (optional) ---
    object_png: Path | None = None
    if spec.object_layer is not None:
        object_png = _generate_one(
            project_root,
            backend,
            kind="object-tileset",
            prompt=spec.object_layer.prompt,
            sheet=spec.object_layer.sheet,
        )
        summary["prompts"]["object"] = spec.object_layer.prompt
        summary["assets"].append({"layer": "object", "path": str(object_png)})

    # --- generate placeables ---
    placeable_images: dict[str, Path] = {}
    for spec_entry in spec.placeables:
        if spec_entry.prompt in placeable_images:
            continue  # dedupe by prompt — same text = same visual
        png = _generate_one(
            project_root,
            backend,
            kind="placeable",
            prompt=spec_entry.prompt,
            footprint=spec_entry.footprint,
        )
        placeable_images[spec_entry.prompt] = png
        summary["assets"].append(
            {"layer": "placeables", "prompt": spec_entry.prompt, "path": str(png)}
        )

    # --- assemble tilesets for the TMJ ---
    from PIL import Image

    tilesets: list[dict[str, Any]] = []

    gcols = spec.ground.sheet.cols
    grows = spec.ground.sheet.rows
    ground_firstgid = PIXEL_FORGE_BASE_GID
    ground_tilecount = gcols * grows
    with Image.open(ground_png) as img:
        gw, gh = img.size
    tilesets.append(
        _build_image_tileset(
            name=f"{spec.name}-ground",
            image_path_from_map=_relative_to_map(map_dir, ground_png),
            image_width=gw,
            image_height=gh,
            tile_size=spec.tile_size,
            firstgid=ground_firstgid,
        )
    )

    next_firstgid = ground_firstgid + ground_tilecount
    object_firstgid: int | None = None
    if object_png is not None:
        ocols = spec.object_layer.sheet.cols  # type: ignore[union-attr]
        orows = spec.object_layer.sheet.rows  # type: ignore[union-attr]
        object_firstgid = next_firstgid
        with Image.open(object_png) as img:
            ow, oh = img.size
        tilesets.append(
            _build_image_tileset(
                name=f"{spec.name}-object",
                image_path_from_map=_relative_to_map(map_dir, object_png),
                image_width=ow,
                image_height=oh,
                tile_size=spec.tile_size,
                firstgid=object_firstgid,
            )
        )
        next_firstgid += ocols * orows

    # --- placeables-collection tileset ---
    placeable_tile_entries: list[dict[str, Any]] = []
    prompt_to_local_id: dict[str, int] = {}
    for local_id, (prompt, png_path) in enumerate(placeable_images.items()):
        with Image.open(png_path) as img:
            pw, ph = img.size
        placeable_tile_entries.append(
            {
                "id": local_id,
                "image": _relative_to_map(map_dir, png_path),
                "imagewidth": pw,
                "imageheight": ph,
            }
        )
        prompt_to_local_id[prompt] = local_id

    if placeable_tile_entries:
        tilesets.append(
            _build_placeables_collection(
                tiles=placeable_tile_entries,
                firstgid=PLACEABLES_COLLECTION_GID,
                tile_size=spec.tile_size,
            )
        )

    # --- assemble layers ---
    ground_data = [ground_firstgid] * (spec.width * spec.height)
    empty_tilelayer_data = [0] * (spec.width * spec.height)

    placements = _distribute_placeables_on_grid(spec.placeables, spec.width, spec.height)
    placeable_objects: list[dict[str, Any]] = []
    next_obj_id = 1
    for spec_entry, tile_x, tile_y in placements:
        local_id = prompt_to_local_id[spec_entry.prompt]
        gid = PLACEABLES_COLLECTION_GID + local_id
        placeable_objects.append(
            {
                "id": next_obj_id,
                "name": spec_entry.prompt,
                "type": "",
                "gid": gid,
                "x": tile_x * spec.tile_size,
                "y": (tile_y + spec_entry.footprint.h) * spec.tile_size,
                "width": spec_entry.footprint.w * spec.tile_size,
                "height": spec_entry.footprint.h * spec.tile_size,
                "rotation": 0,
                "visible": True,
                "properties": [],
            }
        )
        next_obj_id += 1

    # --- marker suggestion (Phase 3) ---
    marker_objects: list[dict[str, Any]] = []
    if spec.markers is not None and spec.markers.suggest:
        if text_llm is None:
            raise ComposeError(
                "spec requests marker suggestions but no text_llm was provided "
                "to compose()"
            )
        context = MarkerContext(
            map_name=spec.name,
            map_width=spec.width,
            map_height=spec.height,
            tile_size=spec.tile_size,
            ground_prompt=spec.ground.prompt,
            object_prompt=spec.object_layer.prompt if spec.object_layer else None,
            placeable_prompts=[p.prompt for p in spec.placeables],
            requested_npcs=list(spec.markers.npcs),
            requested_transitions=list(spec.markers.transitions),
        )
        marker_objects = suggest_markers(context=context, llm=text_llm)
        summary["markers_requested"] = True
        summary["markers_count"] = len(marker_objects)
    else:
        summary["markers_requested"] = False

    layers: list[dict[str, Any]] = [
        {
            "id": 1,
            "name": "ground",
            "type": "tilelayer",
            "opacity": 1,
            "visible": True,
            "x": 0,
            "y": 0,
            "width": spec.width,
            "height": spec.height,
            "data": ground_data,
        },
        {
            "id": 2,
            "name": "object",
            "type": "tilelayer",
            "opacity": 1,
            "visible": True,
            "x": 0,
            "y": 0,
            "width": spec.width,
            "height": spec.height,
            "data": empty_tilelayer_data,
        },
        {
            "id": 3,
            "name": "placeables",
            "type": "objectgroup",
            "opacity": 1,
            "visible": True,
            "x": 0,
            "y": 0,
            "objects": placeable_objects,
            "draworder": "topdown",
        },
        {
            "id": 4,
            "name": "markers",
            "type": "objectgroup",
            "opacity": 1,
            "visible": True,
            "x": 0,
            "y": 0,
            "objects": marker_objects,
            "draworder": "topdown",
        },
    ]

    tmj: dict[str, Any] = {
        "type": "map",
        "version": "1.10",
        "tiledversion": "pixel-forge-compose",
        "orientation": "orthogonal",
        "renderorder": "right-down",
        "infinite": False,
        "width": spec.width,
        "height": spec.height,
        "tilewidth": spec.tile_size,
        "tileheight": spec.tile_size,
        "nextlayerid": len(layers) + 1,
        "nextobjectid": next_obj_id,
        "compressionlevel": -1,
        "tilesets": tilesets,
        "layers": layers,
        "properties": [],
    }

    tmj_path = map_dir / "map.tmj"
    tmj_path.write_text(json.dumps(tmj, indent=2) + "\n", encoding="utf-8")

    summary_path = map_dir / "map.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    return ComposeResult(tmj_path=tmj_path, summary_path=summary_path, map_dir=map_dir)
