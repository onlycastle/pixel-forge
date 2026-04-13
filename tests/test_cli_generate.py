import json
import subprocess
import sys
from pathlib import Path


def _write_smoke_project(projects_root: Path) -> Path:
    project_dir = projects_root / "cli-smoke"
    (project_dir / "style" / "reference").mkdir(parents=True)
    (project_dir / "style" / "palette.hex").write_text(
        Path("tests/fixtures/palette-4.hex").read_text()
    )
    (project_dir / "style" / "prose.md").write_text("CLI smoke.\n")
    (project_dir / "style" / "reference" / "hero.png").write_bytes(
        Path("tests/fixtures/good-tile.png").read_bytes()
    )
    (project_dir / "project.toml").write_text(
        """
[project]
name = "cli-smoke"
tile_size = 16
output_root = "out"

[style]
palette = "style/palette.hex"
prose = "style/prose.md"
hero_reference = "style/reference/hero.png"
extra_references = []

[generation]
backend = "stub"
variants_per_prompt = 2
max_retries = 0

[validation]
enforce_palette = true
enforce_grid = true
max_off_palette_pixels = 0
"""
    )
    return project_dir


def test_cli_generate_returns_json_summary(tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    projects_root.mkdir()
    _write_smoke_project(projects_root)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pixel_forge",
            "generate",
            "--projects-root",
            str(projects_root),
            "--project",
            "cli-smoke",
            "--kind",
            "tile",
            "--prompt",
            "grass",
            "--variants",
            "2",
            "--backend",
            "stub",
            "--stub-template",
            "tests/fixtures/good-tile.png",
            "--output-json",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert len(payload["variants"]) == 2
    for v in payload["variants"]:
        assert v["passed"] is True
        assert v["validation"]["palette"] == "pass"
        assert Path(v["path"]).exists()
