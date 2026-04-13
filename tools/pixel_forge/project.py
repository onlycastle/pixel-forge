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
    hero_reference: Path | None
    extra_references: list[Path]

    backend: str
    variants_per_prompt: int

    max_off_palette_pixels: int


def _parse_hex(color: str) -> tuple[int, int, int]:
    value = color.strip().lstrip("#")
    if len(value) != 6:
        raise ProjectConfigError(f"Invalid palette entry: {color!r}")
    try:
        return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))
    except ValueError as err:
        raise ProjectConfigError(f"Invalid palette entry: {color!r}") from err


def load_project(project_root: Path) -> Project:
    config_path = project_root / "project.toml"
    if not config_path.exists():
        raise ProjectConfigError(f"Missing project.toml in {project_root}")

    with config_path.open("rb") as fh:
        try:
            raw = tomllib.load(fh)
        except tomllib.TOMLDecodeError as err:
            raise ProjectConfigError(f"Invalid TOML in {config_path}: {err}") from err

    try:
        project_tbl = raw["project"]
        style_tbl = raw["style"]
        generation_tbl = raw["generation"]
        validation_tbl = raw["validation"]

        palette_path = project_root / style_tbl["palette"]
        if not palette_path.exists():
            raise ProjectConfigError(f"palette file missing: {palette_path}")
        palette = [
            _parse_hex(line)
            for line in palette_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#!")
        ]

        prose_path = project_root / style_tbl["prose"]
        if not prose_path.exists():
            raise ProjectConfigError(f"prose file missing: {prose_path}")
        prose = prose_path.read_text(encoding="utf-8")

        # hero_reference is optional. If the key is absent from [style], we
        # pass zero reference images to the backend. If the key is present,
        # the file must exist (declaring a reference is a promise).
        hero_ref_value = style_tbl.get("hero_reference")
        hero_path: Path | None = None
        if hero_ref_value:
            hero_path = project_root / hero_ref_value
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
            max_off_palette_pixels=int(validation_tbl.get("max_off_palette_pixels", 0)),
        )
    except KeyError as err:
        raise ProjectConfigError(
            f"Missing required key in project.toml: {err}. "
            f"See the v1 spec for the required schema."
        ) from err
