import json
import subprocess
import sys
from pathlib import Path


def _write_minimal_project(projects_root: Path) -> Path:
    project_dir = projects_root / "val-test"
    (project_dir / "style" / "reference").mkdir(parents=True)
    (project_dir / "style" / "palette.hex").write_text(
        Path("tests/fixtures/palette-4.hex").read_text()
    )
    (project_dir / "style" / "prose.md").write_text("test.\n")
    (project_dir / "style" / "reference" / "hero.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (project_dir / "project.toml").write_text(
        """
[project]
name = "val-test"
tile_size = 16
output_root = "out"

[style]
palette = "style/palette.hex"
prose = "style/prose.md"
hero_reference = "style/reference/hero.png"
extra_references = []

[generation]
backend = "stub"
variants_per_prompt = 1

[validation]
max_off_palette_pixels = 0
"""
    )
    return project_dir


def test_cli_validate_reports_bad_tile_as_fail(tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    projects_root.mkdir()
    _write_minimal_project(projects_root)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pixel_forge",
            "validate",
            "--projects-root",
            str(projects_root),
            "--project",
            "val-test",
            "--path",
            "tests/fixtures/bad-tile.png",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["validation"]["palette"] == "fail"
    assert payload["validation"]["grid"] == "pass"
    assert payload["passed"] is False
    assert "validation_details" in payload
    assert payload["validation_details"]["palette"]["off_palette_count"] >= 1


def test_cli_validate_good_tile_passes_all_checks(tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    projects_root.mkdir()
    _write_minimal_project(projects_root)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pixel_forge",
            "validate",
            "--projects-root",
            str(projects_root),
            "--project",
            "val-test",
            "--path",
            "tests/fixtures/good-tile.png",
            "--kind",
            "tile",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["validation"]["palette"] == "pass"
    assert payload["validation"]["grid"] == "pass"
    assert payload["validation"]["alpha"] == "pass"
    assert payload["passed"] is True


def test_cli_validate_non_tile_kind_marks_grid_na(tmp_path: Path) -> None:
    """For --kind character, grid is skipped and reported as 'n/a'."""
    projects_root = tmp_path / "projects"
    projects_root.mkdir()
    _write_minimal_project(projects_root)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pixel_forge",
            "validate",
            "--projects-root",
            str(projects_root),
            "--project",
            "val-test",
            "--path",
            "tests/fixtures/good-tile.png",
            "--kind",
            "character",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["validation"]["grid"] == "n/a"
    assert payload["validation"]["palette"] == "pass"
    # passed is True even with grid n/a, because palette passed
    assert payload["passed"] is True
    # validation_details should NOT have a grid key for non-tile kinds
    assert "grid" not in payload["validation_details"]
