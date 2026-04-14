from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image as _PILImage

from pixel_forge.adapters.sunny_street import (
    export_all_characters,
    export_all_placeables,
    export_map,
    split_pixel_forge_tilesets,
)
from pixel_forge.assets import (
    SCHEMA_VERSION,
    AssetKind,
    AssetSidecar,
    Footprint,
    Sheet,
    save_sidecar,
)
from pixel_forge.backends.stub import StubBackend
from pixel_forge.compose import ComposeError, compose
from pixel_forge.generate import GenerateRequest, GenerateRequestError, run
from pixel_forge.migrate_legacy_kinds import migrate_project
from pixel_forge.paperdoll import (
    PaperdollError,
    Recipe,
    compose as paperdoll_compose,
    recipe_to_sidecar_animation,
)
from pixel_forge.paths import KIND_TO_SUBDIR, REJECTED_SUBDIR, ProjectPaths
from pixel_forge.sheet import (
    SHEET_PROFILES,
    SheetRequest,
    run as sheet_run,
)
from pixel_forge.profiles.limezu import (
    LAYER_ACCESSORY,
    LAYER_BODY,
    LAYER_EYES,
    LAYER_HAIR,
    LAYER_OUTFIT,
    PROFILES,
    ProfileError,
    get_profile,
)
from pixel_forge.project import ProjectConfigError, load_project
from pixel_forge.validate import check_alpha, check_grid, check_palette


_LEGACY_KIND_HINT = {
    "tile": "Use --kind ground-tileset (with --sheet CxR) or --kind placeable.",
    "prop": "Use --kind placeable (optionally with --footprint WxH).",
}

_TILESET_KINDS = {"ground-tileset", "object-tileset"}


def _parse_sheet(value: str | None) -> Sheet | None:
    if value is None:
        return None
    try:
        cols_s, rows_s = value.lower().split("x", 1)
        return Sheet(cols=int(cols_s), rows=int(rows_s))
    except ValueError as err:
        raise argparse.ArgumentTypeError(
            f"--sheet must look like CxR (e.g. 4x4), got {value!r}"
        ) from err


def _parse_footprint(value: str | None) -> Footprint | None:
    if value is None:
        return None
    try:
        w_s, h_s = value.lower().split("x", 1)
        return Footprint(w=int(w_s), h=int(h_s))
    except ValueError as err:
        raise argparse.ArgumentTypeError(
            f"--footprint must look like WxH (e.g. 2x3), got {value!r}"
        ) from err


PROJECT_TOML_TEMPLATE = """[project]
name = "{name}"
tile_size = {tile_size}
output_root = "out"

[style]
palette = "style/palette.hex"
prose = "style/prose.md"
# hero_reference is optional. Uncomment and point at a PNG to anchor
# generated assets to a canonical visual reference. Without it, the
# prose + palette still constrain the style, but cross-variant
# consistency is weaker.
# hero_reference = "style/reference/hero.png"
extra_references = []

[generation]
backend = "gemini"
variants_per_prompt = 4

[validation]
max_off_palette_pixels = 0
"""

PALETTE_PLACEHOLDER = """#! Replace these placeholder colors with your real palette before running generate.
#! With enforce_palette=true and max_off_palette_pixels=0 (the default), every
#! generated variant will fail validation until this file holds your real palette.
#000000
#ffffff
#888888
"""

PROSE_PLACEHOLDER = """# Style guide

Replace this file with a prose description of your pixel art style.
Line weight, shading rules, palette rationale, detail density, examples.
"""


def _cmd_new_project(args: argparse.Namespace) -> int:
    projects_root = Path(args.projects_root).resolve()
    project_dir = projects_root / args.name
    if project_dir.exists():
        print(json.dumps({"error": f"project already exists: {project_dir}"}), file=sys.stderr)
        return 2

    try:
        (project_dir / "style" / "reference").mkdir(parents=True)
        # Iterate KIND_TO_SUBDIR.values() instead of hardcoding the tuple (Task 3 carry-forward).
        for subdir in KIND_TO_SUBDIR.values():
            (project_dir / "out" / subdir).mkdir(parents=True)
            (project_dir / "out" / subdir / REJECTED_SUBDIR).mkdir()

        (project_dir / "project.toml").write_text(
            PROJECT_TOML_TEMPLATE.format(name=args.name, tile_size=args.tile_size)
        )
        (project_dir / "style" / "palette.hex").write_text(PALETTE_PLACEHOLDER)
        (project_dir / "style" / "prose.md").write_text(PROSE_PLACEHOLDER)
    except Exception as err:  # noqa: BLE001 - top-level boundary
        # Clean up partial state so a retry with the same --name is not
        # blocked by "project already exists" on a corrupted directory.
        shutil.rmtree(project_dir, ignore_errors=True)
        print(
            json.dumps({"error": f"{type(err).__name__}: {err}"}),
            file=sys.stderr,
        )
        return 3

    print(
        json.dumps(
            {
                "project_dir": str(project_dir),
                "next_steps": [
                    "Replace style/palette.hex with your real palette",
                    "Replace style/prose.md with your style guide",
                    "Drop a hero reference at style/reference/hero.png",
                ],
            }
        )
    )
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    projects_root = Path(args.projects_root).resolve()
    try:
        project = load_project(projects_root / args.project)
    except ProjectConfigError as err:
        print(json.dumps({"error": str(err)}), file=sys.stderr)
        return 2

    img_path = Path(args.path).resolve()
    if not img_path.exists():
        print(json.dumps({"error": f"image not found: {img_path}"}), file=sys.stderr)
        return 2

    try:
        with _PILImage.open(img_path) as img:
            img.load()
            palette_result = check_palette(
                img, project.palette, project.max_off_palette_pixels
            )
            grid_result = (
                check_grid(img, project.tile_size)
                if args.kind in _TILESET_KINDS
                else None
            )
            alpha_result = check_alpha(img)
    except Exception as err:  # noqa: BLE001 - top-level boundary
        print(
            json.dumps({"error": f"{type(err).__name__}: {err}"}),
            file=sys.stderr,
        )
        return 3

    validation = {
        "palette": palette_result.status,
        "grid": grid_result.status if grid_result is not None else "n/a",
        "alpha": alpha_result.status,
    }
    validation_details: dict = {
        "palette": palette_result.details,
        "alpha": alpha_result.details,
    }
    if grid_result is not None:
        validation_details["grid"] = grid_result.details

    passed = palette_result.status != "fail" and (
        grid_result is None or grid_result.status != "fail"
    )

    payload = {
        "path": str(img_path),
        "validation": validation,
        "validation_details": validation_details,
        "passed": passed,
    }
    print(json.dumps(payload))
    return 0


def _cmd_generate(args: argparse.Namespace) -> int:
    if args.kind in _LEGACY_KIND_HINT:
        print(
            json.dumps(
                {
                    "error": (
                        f"kind {args.kind!r} was removed. "
                        f"{_LEGACY_KIND_HINT[args.kind]}"
                    )
                }
            ),
            file=sys.stderr,
        )
        return 2

    projects_root = Path(args.projects_root).resolve()
    project_dir = projects_root / args.project
    try:
        project = load_project(project_dir)
    except ProjectConfigError as err:
        print(json.dumps({"error": str(err)}), file=sys.stderr)
        return 2

    try:
        sheet = _parse_sheet(args.sheet)
        footprint = _parse_footprint(args.footprint)
    except argparse.ArgumentTypeError as err:
        print(json.dumps({"error": str(err)}), file=sys.stderr)
        return 2

    # CLI flags override project.toml when explicitly passed; otherwise the
    # project's configured defaults win.
    effective_backend = args.backend or project.backend
    effective_variants = (
        args.variants if args.variants is not None else project.variants_per_prompt
    )

    if effective_backend == "stub":
        if not args.stub_template:
            print(
                json.dumps({"error": "--stub-template required when backend=stub"}),
                file=sys.stderr,
            )
            return 2
        backend = StubBackend(
            template_path=Path(args.stub_template).resolve(),
            output_dir=project_dir / "out" / "_raw",
        )
    elif effective_backend == "gemini":
        from pixel_forge.backends.gemini import GeminiBackend

        backend = GeminiBackend(output_dir=project_dir / "out" / "_raw")
    else:
        print(json.dumps({"error": f"unknown backend: {effective_backend}"}), file=sys.stderr)
        return 2

    # Carry-forward from Task 10 review: run() raises on hard errors. Wrap it
    # so the CLI always emits structured JSON on stderr instead of a traceback.
    extra_ref: Path | None = None
    if args.ref_image:
        extra_ref = Path(args.ref_image).expanduser().resolve()
        if not extra_ref.is_file():
            print(
                json.dumps({"error": f"--ref-image not found: {extra_ref}"}),
                file=sys.stderr,
            )
            return 2

    try:
        result = run(
            GenerateRequest(
                project=project,
                kind=args.kind,
                prompt=args.prompt,
                variants=effective_variants,
                footprint=footprint,
                sheet=sheet,
                anchor=args.anchor,
                extra_reference=extra_ref,
            ),
            backend=backend,
        )
    except (ProjectConfigError, GenerateRequestError) as err:
        print(json.dumps({"error": str(err)}), file=sys.stderr)
        return 2
    except Exception as err:  # noqa: BLE001 - top-level boundary
        print(
            json.dumps({"error": f"{type(err).__name__}: {err}"}),
            file=sys.stderr,
        )
        return 3

    payload = {
        "variants": [
            {
                "path": str(v.path),
                "sidecar_path": str(v.sidecar_path),
                "validation": v.validation,
                "validation_details": v.validation_details,
                "passed": v.passed,
            }
            for v in result.variants
        ],
        "errors": result.errors,
    }
    print(json.dumps(payload))
    return 0


def _cmd_promote(args: argparse.Namespace) -> int:
    variant_path = Path(args.path).resolve()
    if not variant_path.exists():
        print(json.dumps({"error": f"path not found: {variant_path}"}), file=sys.stderr)
        return 2

    tiles_dir = variant_path.parent

    match = re.match(r"(.+)-(\d{8}-\d{6})-v\d+\.png$", variant_path.name)
    if not match:
        print(
            json.dumps(
                {"error": "filename does not match <base>-<timestamp>-v<n>.png pattern"}
            ),
            file=sys.stderr,
        )
        return 2
    _, timestamp = match.groups()

    canonical_path: Path | None = None
    reject_bucket: Path | None = None
    try:
        rejected_root = tiles_dir / REJECTED_SUBDIR
        rejected_root.mkdir(parents=True, exist_ok=True)

        siblings = sorted(tiles_dir.glob(f"*-{timestamp}-v*.png"))
        reject_bucket = rejected_root / timestamp
        reject_bucket.mkdir(parents=True, exist_ok=True)

        canonical_path = tiles_dir / f"{args.canonical_name}.png"
        shutil.copyfile(variant_path, canonical_path)

        for sibling in siblings:
            if sibling == variant_path:
                sibling.unlink()
            else:
                sibling.rename(reject_bucket / sibling.name)
    except Exception as err:  # noqa: BLE001 - top-level boundary
        print(
            json.dumps({"error": f"{type(err).__name__}: {err}"}),
            file=sys.stderr,
        )
        return 3

    assert canonical_path is not None and reject_bucket is not None
    print(json.dumps({"canonical": str(canonical_path), "rejected": str(reject_bucket)}))
    return 0


def _cmd_split_tilesets(args: argparse.Namespace) -> int:
    target_root = Path(args.to).resolve()
    if args.adapter != "sunny-street":
        print(
            json.dumps({"error": f"unknown adapter: {args.adapter}"}),
            file=sys.stderr,
        )
        return 2
    try:
        report = split_pixel_forge_tilesets(target_root, tile_size=args.tile_size)
    except Exception as err:  # noqa: BLE001 - top-level boundary
        print(
            json.dumps({"error": f"{type(err).__name__}: {err}"}),
            file=sys.stderr,
        )
        return 3

    print(
        json.dumps(
            {
                "split_sheets": report.split_sheets,
                "cells_written": report.cells_written,
                "skipped": report.skipped,
            }
        )
    )
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    projects_root = Path(args.projects_root).resolve()
    project_dir = projects_root / args.project
    target_root = Path(args.to).resolve()

    if not (project_dir / "project.toml").exists():
        print(
            json.dumps({"error": f"project not found: {project_dir}"}),
            file=sys.stderr,
        )
        return 2

    if args.adapter != "sunny-street":
        print(
            json.dumps({"error": f"unknown adapter: {args.adapter}"}),
            file=sys.stderr,
        )
        return 2

    try:
        pl_report = export_all_placeables(project_dir, target_root)
        ch_report = export_all_characters(project_dir, target_root)

        map_reports: list[dict[str, Any]] = []
        maps_root = project_dir / "out" / "maps"
        if maps_root.is_dir():
            for map_dir in sorted(maps_root.iterdir()):
                if not map_dir.is_dir() or not (map_dir / "map.tmj").is_file():
                    continue
                if args.map and map_dir.name != args.map:
                    continue
                mr = export_map(map_dir, target_root)
                map_reports.append(
                    {
                        "map": mr.map_name,
                        "map_written": mr.map_written,
                        "tilesets_copied": mr.tilesets_copied,
                    }
                )
    except Exception as err:  # noqa: BLE001 - top-level boundary
        print(
            json.dumps({"error": f"{type(err).__name__}: {err}"}),
            file=sys.stderr,
        )
        return 3

    print(
        json.dumps(
            {
                "placeables": {
                    "copied": pl_report.copied,
                    "skipped": pl_report.skipped,
                    "failed": pl_report.failed,
                },
                "characters": {
                    "copied": ch_report.copied,
                    "overwritten": ch_report.overwritten,
                    "skipped": ch_report.skipped,
                    "failed": ch_report.failed,
                    "written_paths": ch_report.written_paths,
                },
                "maps": map_reports,
            }
        )
    )
    return 0


def _slugify_recipe(recipe: Recipe) -> str:
    """Compact filesystem-safe slug for a paperdoll recipe."""
    parts = [recipe.profile_id]
    for slot in (LAYER_BODY, LAYER_OUTFIT, LAYER_HAIR, LAYER_EYES, LAYER_ACCESSORY):
        if slot in recipe.layers:
            stem = Path(recipe.layers[slot]).stem
            parts.append(f"{slot}-{stem}")
    return "__".join(parts)


def _cmd_sheet(args: argparse.Namespace) -> int:
    projects_root = Path(args.projects_root).resolve()
    project_dir = projects_root / args.project
    try:
        project = load_project(project_dir)
    except ProjectConfigError as err:
        print(json.dumps({"error": str(err)}), file=sys.stderr)
        return 2

    if args.profile not in SHEET_PROFILES:
        print(
            json.dumps(
                {
                    "error": (
                        f"unknown sheet profile {args.profile!r}; "
                        f"valid: {sorted(SHEET_PROFILES)}"
                    )
                }
            ),
            file=sys.stderr,
        )
        return 2
    profile = SHEET_PROFILES[args.profile]

    reference_path = Path(args.reference).expanduser().resolve()
    extra_ref: Path | None = None
    if args.ref_image:
        extra_ref = Path(args.ref_image).expanduser().resolve()
        if not extra_ref.is_file():
            print(
                json.dumps({"error": f"--ref-image not found: {extra_ref}"}),
                file=sys.stderr,
            )
            return 2

    try:
        result = sheet_run(
            SheetRequest(
                project=project,
                profile=profile,
                prompt=args.prompt,
                reference_path=reference_path,
                variants=args.variants,
                extra_reference=extra_ref,
            )
        )
    except Exception as err:  # noqa: BLE001
        print(
            json.dumps({"error": f"{type(err).__name__}: {err}"}),
            file=sys.stderr,
        )
        return 3

    payload = {
        "variants": [
            {
                "path": str(v.clean_path),
                "sidecar_path": str(v.sidecar_path),
                "raw_path": str(v.raw_path),
                "detected_grid": list(v.detected_grid),
                "raw_size": list(v.raw_size),
                "final_size": list(v.final_size),
                "passed": True,
            }
            for v in result.variants
        ],
        "errors": result.errors,
    }
    print(json.dumps(payload))
    return 0 if not result.errors else 3


def _cmd_paperdoll(args: argparse.Namespace) -> int:
    projects_root = Path(args.projects_root).resolve()
    project_dir = projects_root / args.project
    try:
        project = load_project(project_dir)
    except ProjectConfigError as err:
        print(json.dumps({"error": str(err)}), file=sys.stderr)
        return 2

    try:
        profile = get_profile(args.profile)
    except ProfileError as err:
        print(json.dumps({"error": str(err)}), file=sys.stderr)
        return 2

    layers: dict[str, str] = {LAYER_BODY: args.body, LAYER_OUTFIT: args.outfit}
    if args.hair is not None:
        layers[LAYER_HAIR] = args.hair
    if args.eyes is not None:
        layers[LAYER_EYES] = args.eyes
    if args.accessory is not None:
        layers[LAYER_ACCESSORY] = args.accessory

    recipe = Recipe(profile_id=profile.id, layers=layers)

    try:
        composed = paperdoll_compose(profile, recipe)
    except PaperdollError as err:
        print(json.dumps({"error": str(err)}), file=sys.stderr)
        return 2
    except Exception as err:  # noqa: BLE001 - top-level boundary
        print(
            json.dumps({"error": f"{type(err).__name__}: {err}"}),
            file=sys.stderr,
        )
        return 3

    paths = ProjectPaths(project_root=project.root, output_root=project.output_root)
    paths.ensure("character")
    out_dir = paths.kind_dir("character")

    slug = args.name or _slugify_recipe(recipe)
    out_png = out_dir / f"{slug}.png"
    composed.image.save(out_png)

    animation = recipe_to_sidecar_animation(profile, recipe, composed)
    sidecar = AssetSidecar(
        schema_version=SCHEMA_VERSION,
        kind=AssetKind.CHARACTER,
        layer_target="none",
        tile_size=project.tile_size,
        slug=slug,
        source_prompt=f"paperdoll: {profile.id} / " + ", ".join(
            f"{k}={v}" for k, v in recipe.layers.items()
        ),
        created_at=datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
        animation=animation,
    )
    sidecar_path = save_sidecar(out_png, sidecar)

    payload = {
        "png": str(out_png),
        "sidecar": str(sidecar_path),
        "profile": profile.id,
        "canvas": list(composed.canvas_size),
        "recipe": recipe.layers,
        "layer_sha1": composed.layer_sha1,
    }
    print(json.dumps(payload))
    return 0


def _cmd_compose(args: argparse.Namespace) -> int:
    projects_root = Path(args.projects_root).resolve()
    project_dir = projects_root / args.project
    spec_path = Path(args.spec).resolve()

    try:
        project = load_project(project_dir)
    except ProjectConfigError as err:
        print(json.dumps({"error": str(err)}), file=sys.stderr)
        return 2

    effective_backend = args.backend or project.backend
    if effective_backend == "stub":
        if not args.stub_template:
            print(
                json.dumps({"error": "--stub-template required when backend=stub"}),
                file=sys.stderr,
            )
            return 2
        backend = StubBackend(
            template_path=Path(args.stub_template).resolve(),
            output_dir=project_dir / "out" / "_raw",
        )
    elif effective_backend == "gemini":
        from pixel_forge.backends.gemini import GeminiBackend

        backend = GeminiBackend(output_dir=project_dir / "out" / "_raw")
    else:
        print(
            json.dumps({"error": f"unknown backend: {effective_backend}"}),
            file=sys.stderr,
        )
        return 2

    # Wire a text LLM only when the backend is gemini. Stub mode always
    # gets a deterministic fake llm so `pf compose` stays reproducible in
    # tests and smoke runs.
    text_llm = None
    if effective_backend == "gemini":
        from pixel_forge.backends.gemini_text import gemini_text_llm

        text_llm = gemini_text_llm

    try:
        result = compose(
            spec_path,
            project_root=project_dir,
            backend=backend,
            text_llm=text_llm,
        )
    except (ProjectConfigError, ComposeError, GenerateRequestError) as err:
        print(json.dumps({"error": str(err)}), file=sys.stderr)
        return 2
    except Exception as err:  # noqa: BLE001 - top-level boundary
        print(
            json.dumps({"error": f"{type(err).__name__}: {err}"}),
            file=sys.stderr,
        )
        return 3

    print(
        json.dumps(
            {
                "tmj": str(result.tmj_path),
                "summary": str(result.summary_path),
                "map_dir": str(result.map_dir),
            }
        )
    )
    return 0


def _cmd_migrate_legacy_kinds(args: argparse.Namespace) -> int:
    projects_root = Path(args.projects_root).resolve()
    project_dir = projects_root / args.project
    try:
        report = migrate_project(project_dir)
    except ProjectConfigError as err:
        print(json.dumps({"error": str(err)}), file=sys.stderr)
        return 2
    except Exception as err:  # noqa: BLE001 - top-level boundary
        print(
            json.dumps({"error": f"{type(err).__name__}: {err}"}),
            file=sys.stderr,
        )
        return 3

    print(json.dumps(report.to_dict()))
    return 0 if not report.failed else 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pixel_forge")
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="Generate N variants and save them")
    gen.add_argument("--projects-root", default="projects")
    gen.add_argument("--project", required=True)
    gen.add_argument(
        "--kind",
        # Legacy kinds are accepted here only so we can surface a helpful
        # deprecation error inside _cmd_generate instead of argparse aborting.
        choices=[k.value for k in AssetKind] + list(_LEGACY_KIND_HINT.keys()),
        required=True,
    )
    gen.add_argument("--prompt", required=True)
    gen.add_argument("--variants", type=int, default=None)
    gen.add_argument("--backend", choices=["gemini", "stub"], default=None)
    gen.add_argument("--stub-template", help="Path to a PNG (only with --backend stub)")
    gen.add_argument(
        "--sheet",
        help="Grid dimensions CxR for tileset kinds (e.g. 4x4)",
        default=None,
    )
    gen.add_argument(
        "--footprint",
        help="Tile footprint WxH for placeable kind (e.g. 2x3); inferred if omitted",
        default=None,
    )
    gen.add_argument(
        "--anchor",
        help="Placement anchor for placeable kind (default: bottom-center)",
        default=None,
    )
    gen.add_argument(
        "--ref-image",
        default=None,
        help=(
            "Optional ad-hoc reference image to append to the model call, in "
            "addition to the project's hero_reference. Useful for the GUI's "
            "reference upload feature."
        ),
    )
    gen.set_defaults(func=_cmd_generate)

    promote = sub.add_parser("promote", help="Promote a variant to canonical, reject siblings")
    promote.add_argument("--path", required=True)
    promote.add_argument("--canonical-name", required=True)
    promote.set_defaults(func=_cmd_promote)

    migrate = sub.add_parser(
        "migrate-legacy-kinds",
        help="Move canonical tile/prop assets into placeables/ with sidecars",
    )
    migrate.add_argument("--projects-root", default="projects")
    migrate.add_argument("--project", required=True)
    migrate.set_defaults(func=_cmd_migrate_legacy_kinds)

    comp = sub.add_parser(
        "compose",
        help="Compose a full map from a spec TOML — tilesets + placeables + .tmj",
    )
    comp.add_argument("--projects-root", default="projects")
    comp.add_argument("--project", required=True)
    comp.add_argument("--spec", required=True, help="Path to a map spec TOML")
    comp.add_argument("--backend", choices=["gemini", "stub"], default=None)
    comp.add_argument("--stub-template", help="Path to a PNG (only with --backend stub)")
    comp.set_defaults(func=_cmd_compose)

    split = sub.add_parser(
        "split-tilesets",
        help="Slice pixel-forge sheet PNGs in a consumer repo into individual cell placeables",
    )
    split.add_argument("--adapter", required=True, choices=["sunny-street"])
    split.add_argument("--to", required=True, help="Target consumer repo root")
    split.add_argument("--tile-size", type=int, default=32)
    split.set_defaults(func=_cmd_split_tilesets)

    exp = sub.add_parser(
        "export",
        help="Export pixel-forge outputs into a consumer repo layout",
    )
    exp.add_argument("--projects-root", default="projects")
    exp.add_argument("--project", required=True)
    exp.add_argument("--adapter", required=True, choices=["sunny-street"])
    exp.add_argument("--to", required=True, help="Target consumer repo root")
    exp.add_argument(
        "--map",
        default=None,
        help="Export only the named map (default: export all composed maps)",
    )
    exp.set_defaults(func=_cmd_export)

    sh = sub.add_parser(
        "sheet",
        help="Generate an AI sprite sheet (multi-frame), heuristic-extracted",
    )
    sh.add_argument("--projects-root", default="projects")
    sh.add_argument("--project", required=True)
    sh.add_argument(
        "--profile",
        required=True,
        choices=sorted(SHEET_PROFILES),
        help="Sheet contract profile (animal-livestock24, person-premade, ...)",
    )
    sh.add_argument("--prompt", required=True, help="Subject description")
    sh.add_argument(
        "--reference",
        required=True,
        help="Absolute path to a layout-reference PNG matching the profile",
    )
    sh.add_argument("--variants", type=int, default=2)
    sh.add_argument(
        "--ref-image",
        default=None,
        help="Optional second reference image (e.g. an uploaded identity anchor)",
    )
    sh.set_defaults(func=_cmd_sheet)

    pd = sub.add_parser(
        "paperdoll",
        help="Compose a character sheet from third-party generator layers (no AI)",
    )
    pd.add_argument("--projects-root", default="projects")
    pd.add_argument("--project", required=True)
    pd.add_argument(
        "--profile",
        required=True,
        choices=sorted(PROFILES),
        help="Generator profile (e.g. townspeople, farmers)",
    )
    pd.add_argument("--body", required=True, help="Body layer filename")
    pd.add_argument("--outfit", required=True, help="Outfit layer filename")
    pd.add_argument("--hair", default=None, help="Hairstyle layer filename")
    pd.add_argument("--eyes", default=None, help="Eyes layer filename")
    pd.add_argument("--accessory", default=None, help="Accessory layer filename")
    pd.add_argument(
        "--name",
        default=None,
        help="Output slug (default: derived from recipe)",
    )
    pd.set_defaults(func=_cmd_paperdoll)

    np = sub.add_parser("new-project", help="Create a new project scaffolding")
    np.add_argument("--projects-root", default="projects")
    np.add_argument("--name", required=True)
    np.add_argument("--tile-size", type=int, default=16)
    np.set_defaults(func=_cmd_new_project)

    val = sub.add_parser("validate", help="Validate an existing PNG against a project")
    val.add_argument("--projects-root", default="projects")
    val.add_argument("--project", required=True)
    val.add_argument("--path", required=True)
    val.add_argument(
        "--kind",
        choices=[k.value for k in AssetKind],
        default="placeable",
    )
    val.set_defaults(func=_cmd_validate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
