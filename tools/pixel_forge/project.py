from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


class ProjectConfigError(Exception):
    """Raised when a project config is missing, invalid, or has unreadable assets."""


@dataclass(frozen=True)
class Project:
    name: str
    root: Path
    tile_size: int
    output_root: str

    palette: list[tuple[int, int, int]]
    prose: str
    hero_reference: Path
    extra_references: list[Path]

    backend: str
    variants_per_prompt: int
    max_retries: int

    enforce_palette: bool
    enforce_grid: bool
    max_off_palette_pixels: int


def _parse_hex(color: str) -> tuple[int, int, int]:
    value = color.strip().lstrip("#")
    if len(value) != 6:
        raise ProjectConfigError(f"Invalid palette entry: {color!r}")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def load_project(project_root: Path) -> Project:
    config_path = project_root / "project.toml"
    if not config_path.exists():
        raise ProjectConfigError(f"Missing project.toml in {project_root}")

    with config_path.open("rb") as fh:
        raw = tomllib.load(fh)

    try:
        project_tbl = raw["project"]
        style_tbl = raw["style"]
        generation_tbl = raw["generation"]
        validation_tbl = raw["validation"]
    except KeyError as err:
        raise ProjectConfigError(f"Missing required table in project.toml: {err}") from err

    palette_path = project_root / style_tbl["palette"]
    if not palette_path.exists():
        raise ProjectConfigError(f"palette file missing: {palette_path}")
    palette = [
        _parse_hex(line)
        for line in palette_path.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#!")
    ]

    prose_path = project_root / style_tbl["prose"]
    if not prose_path.exists():
        raise ProjectConfigError(f"prose file missing: {prose_path}")
    prose = prose_path.read_text()

    hero_path = project_root / style_tbl["hero_reference"]
    if not hero_path.exists():
        raise ProjectConfigError(f"hero reference missing: {hero_path}")

    extra_refs = [project_root / p for p in style_tbl.get("extra_references", [])]

    return Project(
        name=project_tbl["name"],
        root=project_root,
        tile_size=int(project_tbl["tile_size"]),
        output_root=project_tbl.get("output_root", "out"),
        palette=palette,
        prose=prose,
        hero_reference=hero_path,
        extra_references=extra_refs,
        backend=generation_tbl.get("backend", "gemini"),
        variants_per_prompt=int(generation_tbl.get("variants_per_prompt", 4)),
        max_retries=int(generation_tbl.get("max_retries", 2)),
        enforce_palette=bool(validation_tbl.get("enforce_palette", True)),
        enforce_grid=bool(validation_tbl.get("enforce_grid", True)),
        max_off_palette_pixels=int(validation_tbl.get("max_off_palette_pixels", 0)),
    )
