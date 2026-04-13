from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image

from pixel_forge.backends.base import ImageBackend
from pixel_forge.paths import ProjectPaths
from pixel_forge.postprocess import ensure_alpha, quantize_to_palette, snap_to_grid
from pixel_forge.project import Project
from pixel_forge.validate import check_alpha, check_grid, check_palette


@dataclass(frozen=True)
class GenerateRequest:
    project: Project
    kind: str
    prompt: str
    variants: int


@dataclass(frozen=True)
class Variant:
    """One generated asset with its validation results.

    `validation["grid"]` is `"pass"`, `"warn"`, or `"fail"` for `kind == "tile"`,
    and the sentinel `"n/a"` for `kind in {"prop", "character"}` where grid
    alignment is not enforced.
    """
    path: Path
    validation: dict[str, str]
    validation_details: dict[str, Any]
    passed: bool


@dataclass(frozen=True)
class GenerateResult:
    variants: list[Variant]
    errors: list[str]


def _build_prompt(project: Project, user_prompt: str, kind: str) -> str:
    palette_lines = "\n".join(f"#{r:02x}{g:02x}{b:02x}" for r, g, b in project.palette)
    if kind == "tile":
        output_line = (
            f"Output: {project.tile_size}x{project.tile_size} PNG, seamless tile, "
            f"transparent background, pixel art."
        )
    else:
        output_line = (
            "Output: PNG with transparent background, pixel art, sized to the subject. "
            f"Use the project's {project.tile_size}-pixel grid as the unit scale."
        )
    reference_line = (
        "Reference image attached: match its line weight, shading, detail density.\n"
        if project.hero_reference is not None
        else ""
    )
    return (
        f"{project.prose}\n"
        f"Palette (use ONLY these colors):\n{palette_lines}\n"
        f"{reference_line}"
        f"Task: {user_prompt}\n"
        f"{output_line}\n"
    )


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def run(request: GenerateRequest, backend: ImageBackend) -> GenerateResult:
    project = request.project
    paths = ProjectPaths(project_root=project.root, output_root=project.output_root)
    paths.ensure(request.kind)

    prompt = _build_prompt(project, request.prompt, request.kind)
    refs: list[Path] = []
    if project.hero_reference is not None:
        refs.append(project.hero_reference)
    refs.extend(project.extra_references)

    raw_paths = backend.generate(prompt=prompt, refs=refs, n=request.variants)

    variants: list[Variant] = []
    ts = _timestamp()
    slug = request.prompt.lower().replace(" ", "-")[:32].strip("-") or "asset"

    for idx, raw_path in enumerate(raw_paths, start=1):
        with Image.open(raw_path) as raw:
            processed = ensure_alpha(raw)
        processed = quantize_to_palette(processed, project.palette)
        if request.kind == "tile":
            processed = snap_to_grid(processed, project.tile_size)

        final_name = f"{slug}-{ts}-v{idx}.png"
        final_path = paths.kind_dir(request.kind) / final_name
        processed.save(final_path)

        palette_result = check_palette(
            processed, project.palette, project.max_off_palette_pixels
        )
        grid_result = (
            check_grid(processed, project.tile_size)
            if request.kind == "tile"
            else None
        )
        alpha_result = check_alpha(processed)

        validation = {
            "palette": palette_result.status,
            "grid": grid_result.status if grid_result else "n/a",
            "alpha": alpha_result.status,
        }
        details: dict[str, Any] = {
            "palette": palette_result.details,
            "alpha": alpha_result.details,
        }
        if grid_result is not None:
            details["grid"] = grid_result.details

        passed = palette_result.status != "fail" and (
            grid_result is None or grid_result.status != "fail"
        )

        variants.append(
            Variant(
                path=final_path,
                validation=validation,
                validation_details=details,
                passed=passed,
            )
        )

    # errors=[] is reserved for future partial-failure paths (e.g. one backend retry that succeeded).
    # Today run() raises on any hard error; Variant.validation_details carries per-variant check results.
    return GenerateResult(variants=variants, errors=[])
