"""Tests for CharacterBundle manifest I/O.

The bundle module is a pure data container — these tests exercise
serialization round-trips, slug safety, schema version handling, and
partial-bundle states (portrait-only, walking-only, actions-only).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from pixel_forge.bundles import (
    BUNDLE_MANIFEST_NAME,
    BUNDLE_SCHEMA_VERSION,
    BundleSchemaError,
    BundleSheet,
    CharacterBundle,
    bundle_dir,
    bundle_from_json,
    bundle_to_json,
    load_bundle,
    save_bundle,
)


def _make_walking_sheet() -> BundleSheet:
    return BundleSheet(
        path="walking.png",
        profile_id="person-premade",
        cell=(32, 64),
        rows=3,
        cols=56,
        direction_order=("right", "up", "left", "down"),
        frames_per_dir=None,
    )


def _make_chop_sheet() -> BundleSheet:
    return BundleSheet(
        path="actions/chop.png",
        profile_id="farmer-chop",
        cell=(64, 64),
        rows=4,
        cols=10,
        direction_order=("right", "up", "left", "down"),
        frames_per_dir=10,
    )


def _make_full_bundle() -> CharacterBundle:
    return CharacterBundle(
        schema_version=BUNDLE_SCHEMA_VERSION,
        slug="barnaby-the-tanner",
        source_prompt="stocky farmer with a leather apron and tanned skin",
        created_at="2026-04-14T12:00:00+00:00",
        portrait="portrait.png",
        walking=_make_walking_sheet(),
        actions={
            "chop": _make_chop_sheet(),
        },
    )


def test_round_trip_full_bundle(tmp_path: Path) -> None:
    bundle = _make_full_bundle()
    out_dir = tmp_path / "bun"
    save_bundle(out_dir, bundle)

    # File layout
    manifest = out_dir / BUNDLE_MANIFEST_NAME
    assert manifest.is_file()

    # Reload and compare
    loaded = load_bundle(out_dir)
    assert loaded == bundle


def test_round_trip_preserves_tuples(tmp_path: Path) -> None:
    """JSON stores tuples as lists; loader must convert back to tuples so
    the dataclass equality check (and any downstream tuple-keyed lookups)
    keeps working."""
    bundle = _make_full_bundle()
    save_bundle(tmp_path, bundle)
    loaded = load_bundle(tmp_path)
    assert isinstance(loaded.walking.cell, tuple)
    assert isinstance(loaded.walking.direction_order, tuple)
    assert isinstance(loaded.actions["chop"].cell, tuple)


def test_partial_bundle_portrait_only(tmp_path: Path) -> None:
    """A bundle with only the portrait (pipe 1) saves and loads cleanly —
    partial state is normal during incremental generation."""
    bundle = CharacterBundle(
        schema_version=BUNDLE_SCHEMA_VERSION,
        slug="sketch-only",
        source_prompt="quick concept sketch",
        created_at="2026-04-14T12:00:00+00:00",
        portrait="portrait.png",
    )
    save_bundle(tmp_path, bundle)
    loaded = load_bundle(tmp_path)
    assert loaded.portrait == "portrait.png"
    assert loaded.walking is None
    assert loaded.actions == {}


def test_partial_bundle_actions_only(tmp_path: Path) -> None:
    bundle = CharacterBundle(
        schema_version=BUNDLE_SCHEMA_VERSION,
        slug="anim-only",
        source_prompt="just needed new action sheets",
        created_at="2026-04-14T12:00:00+00:00",
        actions={"chop": _make_chop_sheet()},
    )
    save_bundle(tmp_path, bundle)
    loaded = load_bundle(tmp_path)
    assert loaded.portrait is None
    assert loaded.walking is None
    assert "chop" in loaded.actions


def test_save_creates_directory(tmp_path: Path) -> None:
    """The save helper should create the bundle directory if it doesn't
    exist yet — bundle dirs are usually created on first save."""
    target = tmp_path / "nonexistent" / "deeper" / "bundle_dir"
    save_bundle(target, _make_full_bundle())
    assert (target / BUNDLE_MANIFEST_NAME).is_file()


def test_bundle_dir_computes_predictable_path(tmp_path: Path) -> None:
    out_root = tmp_path / "out"
    d = bundle_dir(out_root, "foxy-mcfoxface")
    assert d == out_root / "characters" / "bundles" / "foxy-mcfoxface"


@pytest.mark.parametrize(
    "bad_slug",
    [
        "",                      # empty
        "has space",             # space
        "slash/in/slug",         # path traversal vector
        "dot.in.slug",           # dots are ambiguous on case-insensitive FS
        "unicode-ƒoo",           # non-ASCII
        "a" * 65,                # too long
        "../escape",             # classic traversal
    ],
)
def test_bundle_dir_rejects_unsafe_slug(tmp_path: Path, bad_slug: str) -> None:
    with pytest.raises(BundleSchemaError):
        bundle_dir(tmp_path, bad_slug)


def test_load_missing_manifest_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_bundle(tmp_path / "no-such-dir")


def test_load_invalid_json_raises(tmp_path: Path) -> None:
    (tmp_path / BUNDLE_MANIFEST_NAME).write_text("{ this is not valid json")
    with pytest.raises(BundleSchemaError):
        load_bundle(tmp_path)


def test_load_rejects_wrong_schema_version(tmp_path: Path) -> None:
    """Future schema bumps should force explicit migration, not silently
    degrade-load. This is the mechanism that enforces that."""
    payload = {
        "schema_version": 99,
        "slug": "any",
        "source_prompt": "x",
        "created_at": "2026-04-14T12:00:00+00:00",
        "portrait": None,
        "walking": None,
        "actions": {},
    }
    (tmp_path / BUNDLE_MANIFEST_NAME).write_text(json.dumps(payload))
    with pytest.raises(BundleSchemaError, match="schema_version"):
        load_bundle(tmp_path)


def test_bundle_from_json_rejects_missing_required_field() -> None:
    payload = bundle_to_json(_make_full_bundle())
    del payload["source_prompt"]
    with pytest.raises(BundleSchemaError):
        bundle_from_json(payload)


def test_manifest_is_human_readable_and_sorted(tmp_path: Path) -> None:
    """Bundle manifests get committed or reviewed by humans sometimes;
    indent + sort_keys keeps diffs stable. This test protects that choice
    from being accidentally reverted."""
    save_bundle(tmp_path, _make_full_bundle())
    text = (tmp_path / BUNDLE_MANIFEST_NAME).read_text()
    assert "\n  " in text  # indented
    # Keys appear in sorted order: actions, created_at, portrait, schema_version, slug, source_prompt, walking
    first_keys_in_text = [
        line.strip().split('"')[1]
        for line in text.splitlines()
        if line.startswith("  \"")
    ]
    assert first_keys_in_text == sorted(first_keys_in_text)
