import json
import subprocess
import sys
from pathlib import Path


def test_full_pipeline_new_project_generate_promote(tmp_path: Path) -> None:
    """End-to-end: new-project -> add fixtures -> generate with stub -> promote."""
    projects_root = tmp_path / "projects"
    projects_root.mkdir()

    # 1. new-project
    new_proj = subprocess.run(
        [
            sys.executable,
            "-m",
            "pixel_forge",
            "new-project",
            "--projects-root",
            str(projects_root),
            "--name",
            "e2e",
            "--tile-size",
            "16",
        ],
        capture_output=True,
        text=True,
    )
    assert new_proj.returncode == 0, new_proj.stderr
    project_dir = projects_root / "e2e"

    # 2. Replace placeholder palette with the fixture palette so good-tile passes validation.
    (project_dir / "style" / "palette.hex").write_text(
        Path("tests/fixtures/palette-4.hex").read_text()
    )
    # Hero reference is required for load_project, even though stub backend won't use it.
    (project_dir / "style" / "reference" / "hero.png").write_bytes(
        Path("tests/fixtures/good-tile.png").read_bytes()
    )

    # 3. generate with stub backend pointing at good-tile fixture
    gen = subprocess.run(
        [
            sys.executable,
            "-m",
            "pixel_forge",
            "generate",
            "--projects-root",
            str(projects_root),
            "--project",
            "e2e",
            "--kind",
            "tile",
            "--prompt",
            "test grass",
            "--variants",
            "3",
            "--backend",
            "stub",
            "--stub-template",
            "tests/fixtures/good-tile.png",
        ],
        capture_output=True,
        text=True,
    )
    assert gen.returncode == 0, gen.stderr
    gen_payload = json.loads(gen.stdout)
    assert len(gen_payload["variants"]) == 3
    assert all(v["passed"] for v in gen_payload["variants"])
    chosen_path = gen_payload["variants"][1]["path"]

    # 4. promote the second variant
    promote = subprocess.run(
        [
            sys.executable,
            "-m",
            "pixel_forge",
            "promote",
            "--path",
            chosen_path,
            "--canonical-name",
            "test-grass",
        ],
        capture_output=True,
        text=True,
    )
    assert promote.returncode == 0, promote.stderr
    promote_payload = json.loads(promote.stdout)

    canonical = Path(promote_payload["canonical"])
    assert canonical.exists()
    assert canonical.name == "test-grass.png"

    tiles_dir = project_dir / "out" / "tiles"
    remaining_top_level = list(tiles_dir.glob("*.png"))
    assert len(remaining_top_level) == 1
    assert remaining_top_level[0] == canonical

    rejected = list((tiles_dir / "_rejected").rglob("*.png"))
    assert len(rejected) == 2
