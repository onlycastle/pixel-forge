from pathlib import Path

import pytest

from pixel_forge.project import Project, ProjectConfigError, load_project


def _write_project(tmp_path: Path) -> Path:
    project_dir = tmp_path / "sunny-street"
    (project_dir / "style" / "reference").mkdir(parents=True)
    (project_dir / "style" / "palette.hex").write_text("#000000\n#ffffff\n")
    (project_dir / "style" / "prose.md").write_text("Pixel art style.\n")
    (project_dir / "style" / "reference" / "hero.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (project_dir / "project.toml").write_text(
        """
[project]
name = "sunny-street"
tile_size = 16
output_root = "out"

[style]
palette = "style/palette.hex"
prose = "style/prose.md"
hero_reference = "style/reference/hero.png"
extra_references = []

[generation]
backend = "gemini"
variants_per_prompt = 4
max_retries = 2

[validation]
enforce_palette = true
enforce_grid = true
max_off_palette_pixels = 0
"""
    )
    return project_dir


def test_load_project_happy_path(tmp_path: Path) -> None:
    project_dir = _write_project(tmp_path)

    project = load_project(project_dir)

    assert isinstance(project, Project)
    assert project.name == "sunny-street"
    assert project.tile_size == 16
    assert project.palette == [(0, 0, 0), (255, 255, 255)]
    assert project.prose.strip() == "Pixel art style."
    assert project.hero_reference == project_dir / "style" / "reference" / "hero.png"
    assert project.variants_per_prompt == 4


def test_load_project_missing_palette_raises(tmp_path: Path) -> None:
    project_dir = _write_project(tmp_path)
    (project_dir / "style" / "palette.hex").unlink()

    with pytest.raises(ProjectConfigError, match="palette"):
        load_project(project_dir)


def test_load_project_missing_hero_ref_raises(tmp_path: Path) -> None:
    project_dir = _write_project(tmp_path)
    (project_dir / "style" / "reference" / "hero.png").unlink()

    with pytest.raises(ProjectConfigError, match="hero"):
        load_project(project_dir)


def test_load_project_malformed_toml_raises_project_config_error(tmp_path: Path) -> None:
    project_dir = _write_project(tmp_path)
    (project_dir / "project.toml").write_text("this is not valid toml === [[[")

    with pytest.raises(ProjectConfigError, match="Invalid TOML"):
        load_project(project_dir)


def test_load_project_invalid_palette_hex_raises_project_config_error(tmp_path: Path) -> None:
    project_dir = _write_project(tmp_path)
    (project_dir / "style" / "palette.hex").write_text("#zzzzzz\n")

    with pytest.raises(ProjectConfigError, match="Invalid palette entry"):
        load_project(project_dir)


def test_load_project_missing_name_key_raises_project_config_error(tmp_path: Path) -> None:
    project_dir = _write_project(tmp_path)
    # Rewrite the TOML without the `name` key inside [project]
    (project_dir / "project.toml").write_text(
        """
[project]
tile_size = 16
output_root = "out"

[style]
palette = "style/palette.hex"
prose = "style/prose.md"
hero_reference = "style/reference/hero.png"
extra_references = []

[generation]
backend = "gemini"
variants_per_prompt = 4
max_retries = 2

[validation]
enforce_palette = true
enforce_grid = true
max_off_palette_pixels = 0
"""
    )

    with pytest.raises(ProjectConfigError, match="Missing required key"):
        load_project(project_dir)
