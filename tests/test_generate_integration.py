from pathlib import Path

from pixel_forge.backends.stub import StubBackend
from pixel_forge.generate import GenerateRequest, run
from pixel_forge.project import load_project


def _write_project_with_palette_4(tmp_path: Path) -> Path:
    project_dir = tmp_path / "smoke"
    (project_dir / "style" / "reference").mkdir(parents=True)
    # Re-use the palette-4 fixture verbatim.
    src_palette = Path("tests/fixtures/palette-4.hex").read_text()
    (project_dir / "style" / "palette.hex").write_text(src_palette)
    (project_dir / "style" / "prose.md").write_text("Test style.\n")
    # The hero reference doesn't need to be a real image — load_project just
    # checks that the file exists, and the stub backend doesn't call Gemini.
    (project_dir / "style" / "reference" / "hero.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (project_dir / "project.toml").write_text(
        """
[project]
name = "smoke"
tile_size = 16
output_root = "out"

[style]
palette = "style/palette.hex"
prose = "style/prose.md"
hero_reference = "style/reference/hero.png"
extra_references = []

[generation]
backend = "stub"
variants_per_prompt = 3
max_retries = 0

[validation]
enforce_palette = true
enforce_grid = true
max_off_palette_pixels = 0
"""
    )
    return project_dir


def test_generate_runs_pipeline_end_to_end_with_stub(tmp_path: Path) -> None:
    project_dir = _write_project_with_palette_4(tmp_path)
    project = load_project(project_dir)

    backend = StubBackend(
        template_path=Path("tests/fixtures/good-tile.png").resolve(),
        output_dir=tmp_path / "raw",
    )

    result = run(
        GenerateRequest(project=project, kind="tile", prompt="grass", variants=3),
        backend=backend,
    )

    assert len(result.variants) == 3
    out_dir = project_dir / "out" / "tiles"
    for variant in result.variants:
        assert variant.path.exists()
        assert variant.path.parent == out_dir
        assert variant.validation["palette"] == "pass"
        assert variant.validation["grid"] == "pass"
        assert variant.validation["alpha"] == "pass"
        assert variant.passed is True
