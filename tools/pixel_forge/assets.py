"""Sidecar schema + load/save for pixel-forge generated assets.

Every PNG that pixel-forge emits gets a companion `<stem>.meta.json` file that
declares WHAT the asset is and WHICH consumer-side layer it belongs to. This
removes the ambiguity that used to force downstream tools (editors, adapters)
to guess whether a PNG is a tileset sheet or a multi-tile stamp.

Schema version 1. Any breaking change bumps this integer and forces a
migration.
"""
from __future__ import annotations

import json
import os
import secrets
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1


class SchemaError(ValueError):
    """Raised when a sidecar payload violates the schema contract."""


class AssetKind(str, Enum):
    GROUND_TILESET = "ground-tileset"
    OBJECT_TILESET = "object-tileset"
    PLACEABLE = "placeable"
    CHARACTER = "character"
    MAP = "map"


# Kind → allowed layer_target values. A sidecar whose layer_target is not in
# this set is rejected at save time.
_ALLOWED_LAYERS: dict[AssetKind, set[str]] = {
    AssetKind.GROUND_TILESET: {"ground"},
    AssetKind.OBJECT_TILESET: {"object"},
    AssetKind.PLACEABLE: {"placeables"},
    AssetKind.CHARACTER: {"none"},
    AssetKind.MAP: {"none"},
}


@dataclass(frozen=True)
class Footprint:
    w: int
    h: int


@dataclass(frozen=True)
class Sheet:
    cols: int
    rows: int


@dataclass(frozen=True)
class AssetSidecar:
    schema_version: int
    kind: AssetKind
    layer_target: str
    tile_size: int
    slug: str
    source_prompt: str
    created_at: str
    footprint: Footprint | None = None
    sheet: Sheet | None = None
    anchor: str | None = None
    animation: dict[str, Any] | None = None
    migrated_from: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def sidecar_path_for(png_path: Path) -> Path:
    return png_path.with_suffix(".meta.json")


def _validate(sidecar: AssetSidecar) -> None:
    if sidecar.schema_version != SCHEMA_VERSION:
        raise SchemaError(
            f"unsupported schema_version {sidecar.schema_version!r}, "
            f"expected {SCHEMA_VERSION}"
        )

    allowed = _ALLOWED_LAYERS.get(sidecar.kind)
    if allowed is None:
        raise SchemaError(f"unknown kind {sidecar.kind!r}")
    if sidecar.layer_target not in allowed:
        raise SchemaError(
            f"layer_target {sidecar.layer_target!r} is not valid for kind "
            f"{sidecar.kind.value!r}; expected one of {sorted(allowed)}"
        )

    if sidecar.kind is AssetKind.PLACEABLE and sidecar.footprint is None:
        raise SchemaError("placeable assets must declare a footprint {w,h}")

    if sidecar.kind in (AssetKind.GROUND_TILESET, AssetKind.OBJECT_TILESET) and sidecar.sheet is None:
        raise SchemaError(
            f"{sidecar.kind.value} assets must declare a sheet {{cols,rows}}"
        )

    if sidecar.tile_size <= 0:
        raise SchemaError(f"tile_size must be positive, got {sidecar.tile_size}")
    if not sidecar.slug:
        raise SchemaError("slug must be non-empty")


def _to_json_dict(sidecar: AssetSidecar) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": sidecar.schema_version,
        "kind": sidecar.kind.value,
        "layer_target": sidecar.layer_target,
        "tile_size": sidecar.tile_size,
        "slug": sidecar.slug,
        "source_prompt": sidecar.source_prompt,
        "created_at": sidecar.created_at,
    }
    if sidecar.footprint is not None:
        payload["footprint"] = asdict(sidecar.footprint)
    if sidecar.sheet is not None:
        payload["sheet"] = asdict(sidecar.sheet)
    if sidecar.anchor is not None:
        payload["anchor"] = sidecar.anchor
    if sidecar.animation is not None:
        payload["animation"] = dict(sidecar.animation)
    if sidecar.migrated_from is not None:
        payload["migrated_from"] = sidecar.migrated_from
    if sidecar.extra:
        payload["extra"] = dict(sidecar.extra)
    return payload


def _from_json_dict(payload: dict[str, Any]) -> AssetSidecar:
    if "schema_version" not in payload:
        raise SchemaError("sidecar payload is missing schema_version")
    if payload["schema_version"] != SCHEMA_VERSION:
        raise SchemaError(
            f"unsupported schema_version {payload['schema_version']!r}, "
            f"expected {SCHEMA_VERSION}"
        )
    try:
        kind = AssetKind(payload["kind"])
    except (KeyError, ValueError) as err:
        raise SchemaError(f"invalid kind in payload: {err}") from err

    footprint = None
    if "footprint" in payload:
        fp = payload["footprint"]
        footprint = Footprint(w=int(fp["w"]), h=int(fp["h"]))

    sheet = None
    if "sheet" in payload:
        sh = payload["sheet"]
        sheet = Sheet(cols=int(sh["cols"]), rows=int(sh["rows"]))

    return AssetSidecar(
        schema_version=payload["schema_version"],
        kind=kind,
        layer_target=payload["layer_target"],
        tile_size=int(payload["tile_size"]),
        slug=payload["slug"],
        source_prompt=payload.get("source_prompt", ""),
        created_at=payload.get("created_at", ""),
        footprint=footprint,
        sheet=sheet,
        anchor=payload.get("anchor"),
        animation=payload.get("animation"),
        migrated_from=payload.get("migrated_from"),
        extra=dict(payload.get("extra", {})),
    )


def save_sidecar(png_path: Path, sidecar: AssetSidecar) -> Path:
    """Write the sidecar next to `png_path` atomically.

    Raises SchemaError before touching disk if the payload violates the
    contract. On a mid-write crash the final target file will not exist and
    any temp file is removed.
    """
    _validate(sidecar)

    target = sidecar_path_for(png_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    tmp = target.with_name(f"{target.name}.tmp-{secrets.token_hex(4)}")
    payload = _to_json_dict(sidecar)
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        tmp.replace(target)
    except Exception:
        # Clean up the stray temp file so re-runs don't accumulate garbage.
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
    return target


def load_sidecar(png_path: Path) -> AssetSidecar:
    path = sidecar_path_for(png_path)
    if not path.is_file():
        raise SchemaError(f"sidecar not found for {png_path}: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return _from_json_dict(payload)
