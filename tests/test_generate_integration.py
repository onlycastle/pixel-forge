from pathlib import Path

from pixel_forge.assets import Footprint, Sheet, load_sidecar
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

[validation]
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
        GenerateRequest(
            project=project,
            kind="ground-tileset",
            prompt="grass",
            variants=3,
            sheet=Sheet(cols=1, rows=1),
        ),
        backend=backend,
    )

    assert len(result.variants) == 3
    out_dir = project_dir / "out" / "tilesets" / "ground"
    for variant in result.variants:
        assert variant.path.exists()
        assert variant.path.parent == out_dir
        assert variant.validation["palette"] == "pass"
        assert variant.validation["grid"] == "pass"
        assert variant.validation["alpha"] == "pass"
        assert variant.passed is True
        # Sidecar emitted alongside the PNG with the right layer target.
        sidecar = load_sidecar(variant.path)
        assert sidecar.kind.value == "ground-tileset"
        assert sidecar.layer_target == "ground"
        assert sidecar.sheet == Sheet(cols=1, rows=1)
        assert sidecar.tile_size == project.tile_size


def test_build_prompt_includes_all_three_style_anchor_layers(tmp_path: Path) -> None:
    """Pins the layered-anchor invariant so a future refactor cannot drop a layer."""
    from pixel_forge.generate import _build_prompt

    project_dir = _write_project_with_palette_4(tmp_path)
    project = load_project(project_dir)

    tile_out = _build_prompt(
        project,
        "mossy grass",
        kind="ground-tileset",
        sheet=Sheet(cols=1, rows=1),
    )

    # Layer 1: prose style guide
    assert project.prose.strip() in tile_out
    # Layer 2: palette hex lines (at least one)
    assert "#ff0000" in tile_out or "#ffffff" in tile_out or "#000000" in tile_out
    assert "Palette (use ONLY these colors)" in tile_out
    # Layer 3: hero reference instruction
    assert "Reference image attached" in tile_out
    # Task + output dimension (ground-tileset-specific)
    assert "Task: mossy grass" in tile_out
    assert f"{project.tile_size}x{project.tile_size}" in tile_out
    assert "seamless" in tile_out


def test_build_prompt_non_tile_kind_has_free_form_output_line(tmp_path: Path) -> None:
    """Characters and props must not be constrained to a single-tile square."""
    from pixel_forge.generate import _build_prompt

    project_dir = _write_project_with_palette_4(tmp_path)
    project = load_project(project_dir)

    char_out = _build_prompt(project, "1974 hardware store clerk", kind="character")

    # Still has all three layers
    assert project.prose.strip() in char_out
    assert "Palette (use ONLY these colors)" in char_out
    assert "Reference image attached" in char_out
    # But the output line is NOT a fixed NxN square
    assert f"{project.tile_size}x{project.tile_size}" not in char_out
    assert "sized to the subject" in char_out

    # Placeable without an explicit footprint falls back to "sized to the subject"
    # in whole tile units.
    place_out = _build_prompt(project, "wooden cart", kind="placeable")
    assert "sized to the subject" in place_out
    assert "Task: wooden cart" in place_out

    # Placeable with an explicit footprint bakes the target dimensions into
    # the prompt so the model aims for the right bounds.
    place_fp_out = _build_prompt(
        project,
        "wooden cart",
        kind="placeable",
        footprint=Footprint(w=2, h=1),
    )
    assert f"{2*project.tile_size}x{1*project.tile_size}" in place_fp_out


def _write_project_without_hero(tmp_path: Path) -> Path:
    """Bootstrap a project with the hero_reference key OMITTED from [style]."""
    project_dir = tmp_path / "no-hero"
    (project_dir / "style").mkdir(parents=True)
    (project_dir / "style" / "palette.hex").write_text(
        Path("tests/fixtures/palette-4.hex").read_text()
    )
    (project_dir / "style" / "prose.md").write_text("No-reference style.\n")
    (project_dir / "project.toml").write_text(
        """
[project]
name = "no-hero"
tile_size = 16
output_root = "out"

[style]
palette = "style/palette.hex"
prose = "style/prose.md"
extra_references = []

[generation]
backend = "stub"
variants_per_prompt = 2

[validation]
max_off_palette_pixels = 0
"""
    )
    return project_dir


def test_generate_runs_without_hero_reference(tmp_path: Path) -> None:
    """A project with no hero_reference key must still produce valid variants.
    The backend receives an empty refs list and the prompt omits the reference
    instruction line."""
    project_dir = _write_project_without_hero(tmp_path)
    project = load_project(project_dir)
    assert project.hero_reference is None

    # Record what the backend receives so we can assert refs is empty.
    captured: dict = {}

    class RecordingStub(StubBackend):
        def generate(self, prompt, refs, n):
            captured["prompt"] = prompt
            captured["refs"] = list(refs)
            return super().generate(prompt, refs, n)

    backend = RecordingStub(
        template_path=Path("tests/fixtures/good-tile.png").resolve(),
        output_dir=tmp_path / "raw",
    )

    result = run(
        GenerateRequest(
            project=project,
            kind="ground-tileset",
            prompt="grass",
            variants=2,
            sheet=Sheet(cols=1, rows=1),
        ),
        backend=backend,
    )

    assert captured["refs"] == []
    assert "Reference image attached" not in captured["prompt"]
    # Pipeline still produces valid variants
    assert len(result.variants) == 2
    for variant in result.variants:
        assert variant.passed is True


def test_build_prompt_omits_reference_line_when_hero_is_none(tmp_path: Path) -> None:
    """When Project.hero_reference is None, _build_prompt must not claim a
    reference image is attached."""
    from pixel_forge.generate import _build_prompt

    project_dir = _write_project_without_hero(tmp_path)
    project = load_project(project_dir)

    out = _build_prompt(
        project,
        "grass",
        kind="ground-tileset",
        sheet=Sheet(cols=1, rows=1),
    )

    assert "Reference image attached" not in out
    # Other layers still present
    assert project.prose.strip() in out
    assert "Palette (use ONLY these colors)" in out
    assert "Task: grass" in out
    assert "seamless" in out
