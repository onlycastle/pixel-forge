from pathlib import Path

from pixel_forge.paths import ProjectPaths


def test_project_paths_for_tile_kind(tmp_path: Path) -> None:
    paths = ProjectPaths(project_root=tmp_path, output_root="out")

    assert paths.kind_dir("tile") == tmp_path / "out" / "tiles"
    assert paths.kind_dir("prop") == tmp_path / "out" / "props"
    assert paths.kind_dir("character") == tmp_path / "out" / "characters"


def test_project_paths_rejected_dir(tmp_path: Path) -> None:
    paths = ProjectPaths(project_root=tmp_path, output_root="out")

    assert paths.rejected_dir("tile") == tmp_path / "out" / "tiles" / "_rejected"


def test_ensure_creates_dirs(tmp_path: Path) -> None:
    paths = ProjectPaths(project_root=tmp_path, output_root="out")

    paths.ensure("tile")

    assert (tmp_path / "out" / "tiles").is_dir()
    assert (tmp_path / "out" / "tiles" / "_rejected").is_dir()
