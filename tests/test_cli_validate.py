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
max_retries = 0

[validation]
enforce_palette = true
enforce_grid = true
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
