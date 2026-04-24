from pathlib import Path

import pytest

from pixel_forge.paths import KIND_TO_SUBDIR, LEGACY_KIND_SUBDIRS, ProjectPaths


def test_project_paths_for_new_kinds(tmp_path: Path) -> None:
    paths = ProjectPaths(project_root=tmp_path, output_root="out")

    assert paths.kind_dir("ground-tileset") == tmp_path / "out" / "tilesets" / "ground"
    assert paths.kind_dir("object-tileset") == tmp_path / "out" / "tilesets" / "object"
    assert paths.kind_dir("placeable") == tmp_path / "out" / "placeables"
    assert paths.kind_dir("character") == tmp_path / "out" / "characters"
    assert paths.kind_dir("map") == tmp_path / "out" / "maps"


def test_project_paths_rejected_dir(tmp_path: Path) -> None:
    paths = ProjectPaths(project_root=tmp_path, output_root="out")

    assert (
        paths.rejected_dir("placeable")
        == tmp_path / "out" / "placeables" / "_rejected"
    )


def test_ensure_creates_dirs(tmp_path: Path) -> None:
    paths = ProjectPaths(project_root=tmp_path, output_root="out")

    paths.ensure("ground-tileset")

    assert (tmp_path / "out" / "tilesets" / "ground").is_dir()
    assert (tmp_path / "out" / "tilesets" / "ground" / "_rejected").is_dir()


def test_legacy_kinds_rejected_from_new_api(tmp_path: Path) -> None:
    paths = ProjectPaths(project_root=tmp_path, output_root="out")

    with pytest.raises(ValueError, match="Unknown kind"):
        paths.kind_dir("tile")
    with pytest.raises(ValueError, match="Unknown kind"):
        paths.kind_dir("prop")


def test_legacy_kind_dir_helper_still_available_for_migration(tmp_path: Path) -> None:
    paths = ProjectPaths(project_root=tmp_path, output_root="out")

    assert paths.legacy_kind_dir("tile") == tmp_path / "out" / "tiles"
    assert paths.legacy_kind_dir("prop") == tmp_path / "out" / "props"


def test_kind_to_subdir_is_the_authoritative_enum() -> None:
    # Locks the active kind set; any change is an intentional schema bump.
    assert set(KIND_TO_SUBDIR.keys()) == {
        "ground-tileset",
        "object-tileset",
        "placeable",
        "character",
        "map",
    }


def test_legacy_kinds_are_only_tile_and_prop() -> None:
    # Legacy kinds are frozen — new code never creates more of these.
    assert set(LEGACY_KIND_SUBDIRS.keys()) == {"tile", "prop"}
