"""Contract tests for the shared manifest schema module.

Both pixel-forge's adapter and sunny-street's editor import from this
module, so behavior changes here are load-bearing for both sides.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from pixel_forge.schemas.placeable_manifest import (
    MANIFEST_SCHEMA_VERSION,
    PUBLIC_ROOT_SUBDIR,
    ManifestEntry,
    ManifestError,
    assert_entry_is_readable,
    load_manifest,
    parse_entry,
    resolve_public_path,
    save_manifest,
    serialize_entry,
)


def test_schema_version_is_locked() -> None:
    # Any change is an intentional contract bump — update both writer
    # and reader when this changes.
    assert MANIFEST_SCHEMA_VERSION == 1


def test_resolve_public_path_prepends_public_subdir() -> None:
    root = Path("/some/repo")
    got = resolve_public_path("/placeables/generated/x.png", root)
    assert got == (root / "public" / "placeables" / "generated" / "x.png").resolve()


def test_resolve_public_path_accepts_missing_leading_slash() -> None:
    # Historical manifests sometimes omit the leading slash.
    root = Path("/some/repo")
    got = resolve_public_path("placeables/generated/x.png", root)
    assert got == (root / "public" / "placeables" / "generated" / "x.png").resolve()


def test_resolve_public_path_rejects_empty() -> None:
    with pytest.raises(ManifestError, match="non-empty"):
        resolve_public_path("", Path("/repo"))


def test_public_root_subdir_constant() -> None:
    assert PUBLIC_ROOT_SUBDIR == "public"


def test_manifest_entry_round_trip_without_animation() -> None:
    entry = ManifestEntry(
        texture_key="placeable-rowboat-32x32-abc",
        public_path="/placeables/generated/placeable-rowboat-32x32-abc.png",
        source_path="../sunny-street-assets/whatever.png",
    )
    payload = serialize_entry(entry)
    assert payload == {
        "textureKey": entry.texture_key,
        "publicPath": entry.public_path,
        "sourcePath": entry.source_path,
    }
    parsed = parse_entry(entry.texture_key, payload)
    assert parsed == entry


def test_manifest_entry_round_trip_with_animation() -> None:
    entry = ManifestEntry(
        texture_key="placeable-chicken-sheet",
        public_path="/placeables/generated/placeable-chicken-sheet.png",
        source_path="../sunny-street-assets/chicken.png",
        anim_frame_width=16,
        anim_frame_height=16,
        anim_frame_rate=6,
    )
    payload = serialize_entry(entry)
    assert payload["animation"] == {
        "frameWidth": 16,
        "frameHeight": 16,
        "frameRate": 6,
    }
    parsed = parse_entry(entry.texture_key, payload)
    assert parsed == entry


def test_parse_entry_preserves_extra_fields_in_round_trip() -> None:
    payload = {
        "textureKey": "k",
        "publicPath": "/p.png",
        "sourcePath": "../s.png",
        "splitFromSheet": {"sheet": "foo.png", "row": 1, "col": 2},
        "customField": "anything",
    }
    parsed = parse_entry("k", payload)
    assert parsed.extra["splitFromSheet"] == {"sheet": "foo.png", "row": 1, "col": 2}
    assert parsed.extra["customField"] == "anything"
    # Round-trip preserves extras.
    re_serialized = serialize_entry(parsed)
    assert re_serialized["splitFromSheet"] == payload["splitFromSheet"]
    assert re_serialized["customField"] == "anything"


def test_parse_entry_rejects_missing_public_path() -> None:
    with pytest.raises(ManifestError, match="publicPath"):
        parse_entry("k", {"textureKey": "k", "sourcePath": "x"})


def test_parse_entry_rejects_missing_source_path() -> None:
    with pytest.raises(ManifestError, match="sourcePath"):
        parse_entry("k", {"textureKey": "k", "publicPath": "/x.png"})


def test_load_manifest_on_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_manifest(tmp_path / "missing.json") == {}


def test_save_then_load_manifest_round_trip(tmp_path: Path) -> None:
    entries = {
        "a": ManifestEntry(
            texture_key="a",
            public_path="/placeables/generated/a.png",
            source_path="../src/a.png",
        ),
        "b": ManifestEntry(
            texture_key="b",
            public_path="/placeables/generated/b.png",
            source_path="../src/b.png",
            anim_frame_width=32,
            anim_frame_height=32,
            anim_frame_rate=8,
            extra={"splitFromSheet": {"sheet": "foo.png", "row": 0, "col": 3}},
        ),
    }
    path = tmp_path / "manifest.json"
    save_manifest(path, entries)
    loaded = load_manifest(path)
    assert loaded == entries


def test_assert_entry_is_readable_passes_when_file_exists(tmp_path: Path) -> None:
    png_target = tmp_path / "public" / "placeables" / "generated" / "x.png"
    png_target.parent.mkdir(parents=True)
    png_target.write_bytes(b"\x89PNG")

    entry = ManifestEntry(
        texture_key="k",
        public_path="/placeables/generated/x.png",
        source_path="../src/x.png",
    )
    # Does not raise.
    assert_entry_is_readable(entry, tmp_path)


def test_assert_entry_is_readable_raises_on_wrong_publicpath_format(tmp_path: Path) -> None:
    # PNG lives at the correct place, but the entry uses a publicPath that
    # DOESN'T include the /public/ convention — the exact historical bug.
    png_target = tmp_path / "public" / "placeables" / "generated" / "x.png"
    png_target.parent.mkdir(parents=True)
    png_target.write_bytes(b"\x89PNG")

    bad_entry = ManifestEntry(
        texture_key="k",
        public_path="/public/placeables/generated/x.png",  # WRONG — double public/
        source_path="../src/x.png",
    )
    with pytest.raises(ManifestError, match="no file exists"):
        assert_entry_is_readable(bad_entry, tmp_path)


def test_assert_entry_is_readable_raises_when_file_missing(tmp_path: Path) -> None:
    (tmp_path / "public" / "placeables" / "generated").mkdir(parents=True)
    entry = ManifestEntry(
        texture_key="k",
        public_path="/placeables/generated/missing.png",
        source_path="../src/x.png",
    )
    with pytest.raises(ManifestError, match="no file exists"):
        assert_entry_is_readable(entry, tmp_path)
