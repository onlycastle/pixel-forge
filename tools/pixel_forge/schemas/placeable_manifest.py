"""Shared contract for `placeable-asset-manifest.json` and
`placeables-collection.tsj` as used by sunny-street (or any consumer) and
written by pixel-forge.

This module is the SINGLE SOURCE OF TRUTH for:

- How a `publicPath` string (URL-rooted like `/placeables/generated/x.png`)
  resolves to a filesystem path under a consumer repo root.
- The expected keys of a runtime manifest entry and a collection tsj tile.
- The directory conventions (`public/` as the public asset root, etc.).

**Both** `pixel_forge.adapters.sunny_street` (which writes manifests) and
`sunny_street/scripts/tmj_keyboard_editor.py` (which reads them) import
this module so that their understandings of the contract stay in lockstep.

Historical context (why this module exists):
  The editor used to hand-roll its own publicPath resolver via
  `ROOT / publicPath.lstrip("/")` — which is wrong, because `publicPath`
  is a URL-relative path served from the `public/` subdirectory, not a
  filesystem path rooted at the repo root. The editor therefore silently
  dropped every runtime manifest entry it was supposed to load. The
  symptom was "asset catalog is mysteriously empty" for months. This
  module exists so that regression cannot happen again: if pixel-forge's
  writer and sunny-street's reader ever disagree, they can disagree only
  at compile time (ImportError / AttributeError), never silently at
  runtime.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


#: Version of this schema contract. Bump when the manifest entry shape or
#: the path-resolution rule changes in a way that isn't backwards
#: compatible.
MANIFEST_SCHEMA_VERSION = 1

#: The subdirectory under a consumer repo's root where URL-accessible assets
#: live. Sunny-street follows the Next.js convention of serving everything
#: under `public/` at the URL root. If a new consumer uses a different
#: convention, it should override `resolve_public_path` or pass an explicit
#: `public_root`.
PUBLIC_ROOT_SUBDIR = "public"

#: Relative path from the consumer repo root to the runtime manifest.
RUNTIME_MANIFEST_RELATIVE = Path("src") / "phaser" / "data" / "placeable-asset-manifest.json"

#: Relative path from the consumer repo root to the placeables collection
#: tileset (the Tiled "collection of images" tileset that every composed
#: map implicitly references for placeable objects).
PLACEABLES_COLLECTION_RELATIVE = Path("public") / "maps" / "placeables-collection.tsj"


class ManifestError(ValueError):
    """Raised when a manifest entry violates the schema or fails a
    write-time contract check."""


@dataclass(frozen=True)
class ManifestEntry:
    """One entry in `placeable-asset-manifest.json`.

    Shape matches what the sunny-street editor's `_load_runtime_placeable_catalog`
    expects. Extra fields (e.g. `splitFromSheet` from the tileset splitter)
    ride along in `extra` and round-trip through serialize/deserialize
    without being lost.
    """
    texture_key: str
    public_path: str             # URL-rooted, e.g. "/placeables/generated/x.png"
    source_path: str             # Provenance — may be relative or synthetic
    anim_frame_width: int = 0
    anim_frame_height: int = 0
    anim_frame_rate: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


def resolve_public_path(public_path: str, target_root: Path) -> Path:
    """Turn a URL-rooted `publicPath` into the filesystem path a consumer
    repo serves it from.

    >>> resolve_public_path("/placeables/generated/x.png", Path("/repo"))
    PosixPath('/repo/public/placeables/generated/x.png')

    This is the ONE implementation that both writer (pixel-forge adapter)
    and reader (editor) must call. Do not inline the `public/` join in
    callers — it drifts.
    """
    if not public_path:
        raise ManifestError("publicPath must be non-empty")
    # Normalize to always be absolute-URL style.
    normalized = public_path.lstrip("/")
    return (target_root / PUBLIC_ROOT_SUBDIR / normalized).resolve()


def runtime_manifest_path(target_root: Path) -> Path:
    return target_root / RUNTIME_MANIFEST_RELATIVE


def placeables_collection_path(target_root: Path) -> Path:
    return target_root / PLACEABLES_COLLECTION_RELATIVE


def serialize_entry(entry: ManifestEntry) -> dict[str, Any]:
    """Render a `ManifestEntry` back into the JSON shape stored on disk."""
    payload: dict[str, Any] = {
        "textureKey": entry.texture_key,
        "publicPath": entry.public_path,
        "sourcePath": entry.source_path,
    }
    if entry.anim_frame_width or entry.anim_frame_height or entry.anim_frame_rate:
        payload["animation"] = {
            "frameWidth": entry.anim_frame_width,
            "frameHeight": entry.anim_frame_height,
            "frameRate": entry.anim_frame_rate,
        }
    for k, v in entry.extra.items():
        payload[k] = v
    return payload


def parse_entry(texture_key: str, payload: dict[str, Any]) -> ManifestEntry:
    """Inverse of `serialize_entry`. Extra keys ride along in `entry.extra`."""
    if not isinstance(payload, dict):
        raise ManifestError(f"entry {texture_key!r} is not a JSON object")
    public_path = payload.get("publicPath")
    source_path = payload.get("sourcePath")
    if not isinstance(public_path, str) or not public_path:
        raise ManifestError(f"entry {texture_key!r}: missing string publicPath")
    if not isinstance(source_path, str) or not source_path:
        raise ManifestError(f"entry {texture_key!r}: missing string sourcePath")

    anim = payload.get("animation") or {}
    afw = int(anim.get("frameWidth", 0)) if isinstance(anim, dict) else 0
    afh = int(anim.get("frameHeight", 0)) if isinstance(anim, dict) else 0
    afr = int(anim.get("frameRate", 0)) if isinstance(anim, dict) else 0

    known = {"textureKey", "publicPath", "sourcePath", "animation"}
    extra = {k: v for k, v in payload.items() if k not in known}

    return ManifestEntry(
        texture_key=texture_key,
        public_path=public_path,
        source_path=source_path,
        anim_frame_width=afw,
        anim_frame_height=afh,
        anim_frame_rate=afr,
        extra=extra,
    )


def load_manifest(path: Path) -> dict[str, ManifestEntry]:
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        raise ManifestError(f"{path}: invalid JSON: {err}") from err
    if not isinstance(raw, dict):
        raise ManifestError(f"{path}: top-level must be an object")
    return {key: parse_entry(key, val) for key, val in raw.items()}


def save_manifest(path: Path, entries: dict[str, ManifestEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {key: serialize_entry(entry) for key, entry in entries.items()}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def assert_entry_is_readable(entry: ManifestEntry, target_root: Path) -> None:
    """Write-time contract check: the PNG that `entry.publicPath` points to
    must actually exist on disk after the writer places it. Call this
    immediately after copying a PNG and before committing the manifest.

    Raises ManifestError (loud, actionable) on mismatch. This prevents the
    class of bugs where a writer uses publicPath "/x/y.png" and a reader
    looks for it at "<root>/x/y.png" instead of "<root>/public/x/y.png" —
    the writer will now fail at write time instead of silently producing a
    manifest the reader can't consume.
    """
    resolved = resolve_public_path(entry.public_path, target_root)
    if not resolved.is_file():
        raise ManifestError(
            f"manifest entry {entry.texture_key!r} has publicPath "
            f"{entry.public_path!r}, which resolves to {resolved}, but no "
            f"file exists at that path. The writer either wrote the PNG to "
            f"the wrong location or used the wrong publicPath format. "
            f"Expected format: URL-rooted path served from "
            f"{PUBLIC_ROOT_SUBDIR}/, e.g. '/placeables/generated/x.png'."
        )
