"""CharacterBundle — data model for the 3-pipe character creation system.

A character "bundle" groups the three independent outputs the user
produces for a single new character:

    1. **portrait**     — concept art PNG (e.g. 1024×1024), no animation
    2. **walking**      — 3-row premade sheet (preview / idle / walk)
    3. **actions**      — N single-action sheets (chop / dig / water / ...)

The three pipes are generated INDEPENDENTLY (different Gemini calls,
different references, different profiles) but the user thinks of them as
"one character", so we need a manifest that collects them after the fact.

This module is intentionally a pure data container — no generation, no
file I/O orchestration of the actual PNGs. Callers (CLI / API route) are
responsible for producing the PNG + sidecar pairs; this module just reads
and writes the `bundle.json` manifest that lists which files belong to a
bundle and how they are laid out. Keeping it dumb makes it trivial to
test and easy to reason about when pipes fail partially (e.g. portrait
worked but one action sheet is missing — the bundle still serializes).

On-disk layout under `<project_out>/characters/bundles/<slug>/`:

    bundle.json                  <- this module's output
    portrait.png                 <- pipe 1 (relative path inside bundle)
    walking.png                  <- pipe 2
    walking.meta.json            <- the usual per-sheet sidecar (unchanged)
    actions/chop.png             <- pipe 3, one file per action
    actions/chop.meta.json
    actions/water.png
    actions/water.meta.json
    ...

The bundle manifest records *relative* paths inside its own directory so
bundles are relocatable. Per-sheet sidecars stay untouched; the bundle
only stores the minimum metadata needed for consumers (sunny-street boot
scene, asset-forge GUI) to know how to load each sheet without re-reading
every sidecar.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


BUNDLE_SCHEMA_VERSION = 1
BUNDLE_MANIFEST_NAME = "bundle.json"


class BundleSchemaError(ValueError):
    """Raised when a bundle manifest payload violates the schema contract."""


@dataclass(frozen=True)
class BundleSheet:
    """One animated sheet inside a bundle.

    Same shape is used for both walking (multi-row locomotion band) and
    per-action sheets (4-row direction layout). Fields that only apply to
    one kind are optional.

    - `path` is always RELATIVE to the bundle directory.
    - `profile_id` matches the SheetProfile / ActionProfile id that
      produced it (e.g. "person-premade", "farmer-chop"), so the consumer
      can look up the full contract without re-guessing.
    - `cell`, `rows`, `cols` give the final game-layout dimensions.
    - `frames_per_dir` is meaningful for action sheets (one row = one
      direction, N frames per direction). For the walking sheet it's
      None because rows carry different semantics (preview / idle / walk).
    - `direction_order` documents the row order so consumers don't have
      to assume (right, up, left, down) — it's true for all our current
      profiles but tying consumers to that assumption would be fragile.
    """
    path: str
    profile_id: str
    cell: tuple[int, int]
    rows: int
    cols: int
    direction_order: tuple[str, ...]
    frames_per_dir: int | None = None


@dataclass(frozen=True)
class CharacterBundle:
    """Manifest for a complete 3-pipe character."""
    schema_version: int
    slug: str
    source_prompt: str
    created_at: str                          # ISO-8601 UTC
    portrait: str | None = None              # relative path to PNG
    walking: BundleSheet | None = None       # pipe 2 result
    actions: dict[str, BundleSheet] = field(default_factory=dict)  # pipe 3


# ---------- Path helpers ----------


def bundle_dir(project_out_root: Path, slug: str) -> Path:
    """Compute the bundle directory for a slug under a project's out root.

    Does NOT create the directory — callers that write the manifest are
    responsible for `mkdir(parents=True, exist_ok=True)`. Keeps this
    module free of filesystem side effects at import time.
    """
    _require_safe_slug(slug)
    return project_out_root / "characters" / "bundles" / slug


def manifest_path(bundle_directory: Path) -> Path:
    return bundle_directory / BUNDLE_MANIFEST_NAME


def _require_safe_slug(slug: str) -> None:
    """Reject slugs that could escape the bundle directory or be ambiguous
    across case-insensitive filesystems.

    Rules: ASCII letters, digits, hyphen, underscore. 1–64 chars.
    Deliberately stricter than strictly necessary — the loser a rule is
    the more mysterious the debugging when someone pastes a path into a
    slug field and ends up with a traversal attempt in the manifest.
    """
    if not slug:
        raise BundleSchemaError("slug must not be empty")
    if len(slug) > 64:
        raise BundleSchemaError(f"slug too long ({len(slug)} > 64 chars)")
    for ch in slug:
        if not (ch.isascii() and (ch.isalnum() or ch in "-_")):
            raise BundleSchemaError(
                f"slug {slug!r} contains invalid character {ch!r}; "
                "use ASCII letters, digits, hyphen, underscore"
            )


# ---------- Serialization ----------


def _sheet_to_json(sheet: BundleSheet) -> dict:
    d = asdict(sheet)
    # Tuples become lists in JSON; asdict already does that for `cell`
    # and `direction_order`, but we re-state explicitly for clarity.
    d["cell"] = list(sheet.cell)
    d["direction_order"] = list(sheet.direction_order)
    return d


def _sheet_from_json(payload: dict) -> BundleSheet:
    try:
        return BundleSheet(
            path=payload["path"],
            profile_id=payload["profile_id"],
            cell=tuple(payload["cell"]),
            rows=int(payload["rows"]),
            cols=int(payload["cols"]),
            direction_order=tuple(payload["direction_order"]),
            frames_per_dir=(
                int(payload["frames_per_dir"])
                if payload.get("frames_per_dir") is not None
                else None
            ),
        )
    except (KeyError, TypeError, ValueError) as err:
        raise BundleSchemaError(f"invalid sheet payload: {err}") from err


def bundle_to_json(bundle: CharacterBundle) -> dict:
    return {
        "schema_version": bundle.schema_version,
        "slug": bundle.slug,
        "source_prompt": bundle.source_prompt,
        "created_at": bundle.created_at,
        "portrait": bundle.portrait,
        "walking": _sheet_to_json(bundle.walking) if bundle.walking else None,
        "actions": {
            key: _sheet_to_json(sheet) for key, sheet in bundle.actions.items()
        },
    }


def bundle_from_json(payload: dict) -> CharacterBundle:
    try:
        schema_version = int(payload["schema_version"])
    except (KeyError, TypeError, ValueError) as err:
        raise BundleSchemaError(f"missing or invalid schema_version: {err}") from err
    if schema_version != BUNDLE_SCHEMA_VERSION:
        raise BundleSchemaError(
            f"unsupported bundle schema_version {schema_version}; "
            f"this pixel-forge build speaks v{BUNDLE_SCHEMA_VERSION}"
        )

    try:
        slug = payload["slug"]
        _require_safe_slug(slug)
        walking_payload = payload.get("walking")
        actions_payload = payload.get("actions") or {}
        return CharacterBundle(
            schema_version=schema_version,
            slug=slug,
            source_prompt=payload["source_prompt"],
            created_at=payload["created_at"],
            portrait=payload.get("portrait"),
            walking=_sheet_from_json(walking_payload) if walking_payload else None,
            actions={
                key: _sheet_from_json(sheet) for key, sheet in actions_payload.items()
            },
        )
    except (KeyError, TypeError, ValueError) as err:
        if isinstance(err, BundleSchemaError):
            raise
        raise BundleSchemaError(f"invalid bundle payload: {err}") from err


def save_bundle(bundle_directory: Path, bundle: CharacterBundle) -> Path:
    """Write `bundle.json` into `bundle_directory`.

    Creates the directory if needed. Returns the absolute manifest path.
    The caller is still responsible for writing the actual PNG + per-sheet
    sidecar files that the manifest references; this function does NOT
    validate that those files exist (partial bundles are a valid state
    when a pipe fails and the user wants to retry just that pipe).
    """
    bundle_directory.mkdir(parents=True, exist_ok=True)
    out = manifest_path(bundle_directory)
    payload = bundle_to_json(bundle)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return out


def load_bundle(bundle_directory: Path) -> CharacterBundle:
    """Read `bundle.json` from `bundle_directory`."""
    mpath = manifest_path(bundle_directory)
    if not mpath.is_file():
        raise FileNotFoundError(f"bundle manifest missing: {mpath}")
    try:
        payload = json.loads(mpath.read_text())
    except json.JSONDecodeError as err:
        raise BundleSchemaError(f"bundle manifest is not valid JSON: {err}") from err
    return bundle_from_json(payload)
