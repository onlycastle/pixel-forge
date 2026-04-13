import subprocess
import sys
from pathlib import Path


def test_cli_new_project_scaffolds_project_dir(tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    projects_root.mkdir()

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pixel_forge",
            "new-project",
            "--projects-root",
            str(projects_root),
            "--name",
            "my-game",
            "--tile-size",
            "16",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    project_dir = projects_root / "my-game"
    assert (project_dir / "project.toml").exists()
    assert (project_dir / "style" / "palette.hex").exists()
    assert (project_dir / "style" / "prose.md").exists()
    assert (project_dir / "style" / "reference").is_dir()
    assert (project_dir / "out" / "tiles").is_dir()
    assert (project_dir / "out" / "characters").is_dir()
    assert (project_dir / "out" / "props").is_dir()

    toml_text = (project_dir / "project.toml").read_text()
    assert 'name = "my-game"' in toml_text
    assert "tile_size = 16" in toml_text
