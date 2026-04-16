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
    WalkRefineRequest,
    refine_sheet_walk,
    run as sheet_run,
)
from pixel_forge.actions import (
    BUNDLE_ASSET_TYPES,
    FARMER_ACTIONS,
    ActionSheetRequest,
    ActionSourceMissingError,
    get_bundle_catalog,
    load_limezu_action_sheet,
    run_action_sheet,
)
from pixel_forge.bundles import (
    BUNDLE_SCHEMA_VERSION,
    BundleSchemaError,
    BundleSheet,
    CharacterBundle,
    bundle_dir,
    save_bundle,
)
from pixel_forge.pricing import estimate_usd
from pixel_forge.usage import UsageRecord
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


def _cmd_sheet_refine_walk(args: argparse.Namespace) -> int:
    """Regenerate the walk row of an existing sheet, one direction at a time.

    Input is an already-generated clean sheet (e.g. from `pf sheet` or
    `pf bundle`) whose walk row is imperfect. Output is a new PNG in the
    same output directory with the walk row replaced by 4 per-direction
    strips, each generated in its own Gemini call with the base sheet's
    idle strip as an identity anchor.
    """
    projects_root = Path(args.projects_root).resolve()
    project_dir = projects_root / args.project
    try:
        project = load_project(project_dir)
    except ProjectConfigError as err:
        print(json.dumps({"error": str(err)}), file=sys.stderr)
        return 2

    if args.profile not in SHEET_PROFILES:
        print(
            json.dumps({"error": f"unknown profile {args.profile!r}"}),
            file=sys.stderr,
        )
        return 2
    profile = SHEET_PROFILES[args.profile]

    base_sheet = Path(args.base_sheet).expanduser().resolve()
    if not base_sheet.is_file():
        print(
            json.dumps({"error": f"--base-sheet not found: {base_sheet}"}),
            file=sys.stderr,
        )
        return 2

    layout_ref = Path(args.layout_reference).expanduser().resolve()
    if not layout_ref.is_file():
        print(
            json.dumps({"error": f"--layout-reference not found: {layout_ref}"}),
            file=sys.stderr,
        )
        return 2

    try:
        result = refine_sheet_walk(
            WalkRefineRequest(
                project=project,
                profile=profile,
                base_sheet=base_sheet,
                prompt=args.prompt,
                layout_reference=layout_ref,
                variants=args.variants,
            )
        )
    except Exception as err:  # noqa: BLE001 - top-level CLI boundary
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
                "final_size": list(v.final_size),
                "passed": True,
            }
            for v in result.variants
        ],
        "errors": result.errors,
        "usage": _usage_as_dict(result.usage),
    }
    print(json.dumps(payload))
    return 0 if not result.errors else 3


def _usage_as_dict(u: "UsageRecord | None") -> dict:
    """Flatten a UsageRecord into the JSON shape the CLI payload emits.

    None becomes a fully zero record with an empty model name so UIs
    can branch on `total_tokens == 0` rather than on None.
    """
    if u is None:
        return {
            "model": "",
            "prompt_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "call_count": 0,
            "usd": 0.0,
        }
    return {
        "model": u.model,
        "prompt_tokens": u.prompt_tokens,
        "output_tokens": u.output_tokens,
        "total_tokens": u.total_tokens,
        "call_count": u.call_count,
        "usd": estimate_usd(u.model, u.prompt_tokens, u.output_tokens),
    }


def _sum_usage_dicts(records: list["UsageRecord | None"]) -> dict:
    """Sum token counters across records and re-compute USD against
    the first non-empty model name encountered.
    """
    model = ""
    prompt = 0
    output = 0
    total = 0
    calls = 0
    for r in records:
        if r is None:
            continue
        if not model and r.model:
            model = r.model
        prompt += r.prompt_tokens
        output += r.output_tokens
        total += r.total_tokens
        calls += r.call_count
    return {
        "model": model,
        "prompt_tokens": prompt,
        "output_tokens": output,
        "total_tokens": total,
        "call_count": calls,
        "usd": estimate_usd(model, prompt, output),
    }


def _usage_from_summary_total(total_dict: dict) -> "UsageRecord | None":
    """Rehydrate a UsageRecord from a per-variant `total` summary dict.

    Returns None when the record has zero calls (so grand totals don't
    pollute `call_count` with empty pipe rows).
    """
    if total_dict["call_count"] == 0 and total_dict["total_tokens"] == 0:
        return None
    return UsageRecord(
        model=total_dict["model"],
        prompt_tokens=total_dict["prompt_tokens"],
        output_tokens=total_dict["output_tokens"],
        total_tokens=total_dict["total_tokens"],
        call_count=total_dict["call_count"],
    )


def _sum_usage_records(records: list["UsageRecord | None"]) -> dict:
    return _sum_usage_dicts(records)


def _sum_usage_records_to_record(
    records: list["UsageRecord | None"],
) -> "UsageRecord | None":
    """Same summation as `_sum_usage_dicts` but returns a UsageRecord.

    Used by pipe 3, which fans out into N per-action backend calls and
    needs to surface a single collapsed UsageRecord for the pipe-level
    `pipe_usage["actions"]` slot. Returns None when every record is
    None/empty so the summary path below can cleanly represent "pipe
    didn't run or produced no API cost".
    """
    summed = _sum_usage_dicts(records)
    if summed["call_count"] == 0 and summed["total_tokens"] == 0:
        return None
    return UsageRecord(
        model=summed["model"],
        prompt_tokens=summed["prompt_tokens"],
        output_tokens=summed["output_tokens"],
        total_tokens=summed["total_tokens"],
        call_count=summed["call_count"],
    )


def _walking_dims_from_sidecar(sidecar_path: Path, profile) -> dict:
    """Extract the frame dimensions + layout from a walking sheet sidecar.

    The sidecar written by `sheet.run` contains the REAL per-asset
    grid (detected_grid, frame size, locomotion_rows, direction_order)
    which can differ from the profile defaults when the sheet extractor
    retargets the output. Reading it back gives consumers (GUI Player,
    downstream renderers) authoritative dims without having to re-read
    the sidecar themselves.

    Falls back to profile defaults if the sidecar is missing or malformed
    so the client still gets *something* and can animate the walking
    sheet even when the sidecar path is unusable.
    """
    fallback = {
        "cell": list(profile.target_cell),
        "rows": profile.target_rows,
        "cols": profile.target_cols,
        "direction_order": list(profile.direction_order),
        "locomotion_rows": (
            dict(profile.locomotion_rows) if profile.locomotion_rows else None
        ),
    }
    try:
        raw = sidecar_path.read_text()
    except OSError:
        return fallback
    try:
        parsed = json.loads(raw)
    except ValueError:
        return fallback
    anim = parsed.get("animation") if isinstance(parsed, dict) else None
    if not isinstance(anim, dict):
        return fallback
    frame = anim.get("frame")
    grid = anim.get("detected_grid")
    dims: dict = dict(fallback)
    if isinstance(frame, dict) and "w" in frame and "h" in frame:
        dims["cell"] = [int(frame["w"]), int(frame["h"])]
    if isinstance(grid, dict):
        if "cols" in grid:
            dims["cols"] = int(grid["cols"])
        if "rows" in grid:
            dims["rows"] = int(grid["rows"])
    if isinstance(anim.get("direction_order"), list):
        dims["direction_order"] = list(anim["direction_order"])
    if isinstance(anim.get("locomotion_rows"), dict):
        dims["locomotion_rows"] = dict(anim["locomotion_rows"])
    return dims


def _emit_progress(event: str, **fields) -> None:
    """Write a single JSON-lines progress event to stderr.

    Consumed by the streaming API route (`/api/asset-forge/generate-
    stream/route.ts`) which forwards each line as a `progress` SSE
    event to the browser. Stdout is reserved for the final JSON
    payload — callers that ignore stderr (CI, non-streaming tests)
    keep working unchanged.
    """
    import time as _time
    payload = {"event": event, "ts_ms": int(_time.time() * 1000), **fields}
    sys.stderr.write(json.dumps(payload) + "\n")
    sys.stderr.flush()


def _cmd_bundle(args: argparse.Namespace) -> int:
    """Build one or more 3-pipe character bundles in a single invocation.

    All three pipes now run per variant with full AI generation:
      1. Pipe 1 (portrait, via `generate.run`) produces the character's
         portrait from the prompt.
      2. Pipe 2 (walking sheet, via `sheet.run`) produces the 3-row
         locomotion sheet, passing the portrait as an identity anchor
         via `extra_reference` so the walking character matches the
         portrait face/outfit.
      3. Pipe 3 (action sheets, via `actions.run_action_sheet`) produces
         one 4-row direction sheet per requested action. The LimeZu
         farmer action sheet is used as a LAYOUT reference only; the
         portrait is passed as the identity anchor so the generated
         frames show OUR character performing the action, not the
         farmer.

    Because all three pipes now depend on the portrait as an identity
    anchor, portrait generation must succeed before pipes 2 and 3 can
    run. If the caller passes `--skip-portrait`, an existing
    `portrait.png` in the target bundle directory is reused (useful for
    "regenerate just one action" workflows); otherwise pipes 2 and 3
    are rejected with a clear error BEFORE any filesystem side effects.

    Output layout:
      --variants 1 (default) → out/characters/bundles/<slug>/          (legacy path)
      --variants N  (N >= 2) → out/characters/bundles/<slug>-v1/
                              out/characters/bundles/<slug>-v2/
                              ...
                              out/characters/bundles/<slug>-vN/

    The CLI JSON response carries a `bundles` array with N entries. For
    N=1 the top-level `bundle_dir`, `manifest_path`, `slug`, `pipes`,
    `errors` fields mirror `bundles[0]` so existing single-variant
    callers (and tests) keep working unchanged.
    """
    projects_root = Path(args.projects_root).resolve()
    project_dir = projects_root / args.project
    try:
        project = load_project(project_dir)
    except ProjectConfigError as err:
        print(json.dumps({"error": str(err)}), file=sys.stderr)
        return 2

    # Validate variants count BEFORE touching the filesystem.
    n_variants = args.variants
    if n_variants < 1 or n_variants > 16:
        print(
            json.dumps({"error": f"variants must be between 1 and 16, got {n_variants}"}),
            file=sys.stderr,
        )
        return 2

    # Resolve output root (once). Project.output_root may be a relative
    # string; anchor it to the project dir so bundles always land under
    # the project's out tree regardless of CWD.
    out_root = Path(project.output_root)
    if not out_root.is_absolute():
        out_root = (project.root / out_root).resolve()

    # Derive per-variant slugs + dirs. Validate ALL of them upfront so a
    # malformed slug never leaves a partial bundle on disk. For N=1 we
    # use the unsuffixed slug (back-compat with existing consumers); for
    # N>=2 we suffix with -vK to disambiguate sibling candidates.
    def _variant_slug(idx: int) -> str:
        if n_variants == 1:
            return args.slug
        return f"{args.slug}-v{idx + 1}"

    try:
        variant_dirs: list[Path] = [
            bundle_dir(out_root, _variant_slug(i)) for i in range(n_variants)
        ]
    except BundleSchemaError as err:
        print(json.dumps({"error": str(err)}), file=sys.stderr)
        return 2

    # Select the pipe-3 catalog based on --asset-type. Catalog may be
    # empty when the asset type is recognized but not yet populated
    # (animal, decoration). That case gets a distinct error below so
    # users see a roadmap hint rather than "unknown action".
    asset_type = args.asset_type
    catalog = get_bundle_catalog(asset_type)

    # Parse --actions early so we can reject unknown keys before burning
    # any Gemini budget on pipes 1 and 2.
    requested_actions: list[str] = []
    if args.actions:
        requested_actions = [a.strip() for a in args.actions.split(",") if a.strip()]
        if requested_actions and not catalog:
            print(
                json.dumps(
                    {
                        "error": (
                            f"no action/state catalog registered for "
                            f"asset_type={asset_type!r}; bundle mode is "
                            f"fully wired for 'person' only in v1"
                        )
                    }
                ),
                file=sys.stderr,
            )
            return 2
        unknown = [a for a in requested_actions if a not in catalog]
        if unknown:
            print(
                json.dumps(
                    {
                        "error": (
                            f"unknown action(s) {unknown!r} for "
                            f"asset_type={asset_type!r}; valid: "
                            f"{sorted(catalog)}"
                        )
                    }
                ),
                file=sys.stderr,
            )
            return 2

    # Build the backend lazily — only pipes 1 and 2 need it. An
    # actions-only run (--skip-portrait --skip-walking) can proceed
    # without a configured backend at all, which is nice for tests and
    # for the "just regenerate my chop sheet" quick path.
    _backend_cache: list = []

    def _get_backend():
        if _backend_cache:
            return _backend_cache[0]
        effective_backend = args.backend or project.backend or "gemini"
        if effective_backend == "stub":
            if not args.stub_template:
                raise RuntimeError("--stub-template required when backend=stub")
            b = StubBackend(
                template_path=Path(args.stub_template).resolve(),
                output_dir=project_dir / "out" / "_raw",
            )
        elif effective_backend == "gemini":
            from pixel_forge.backends.gemini import GeminiBackend

            b = GeminiBackend(output_dir=project_dir / "out" / "_raw")
        else:
            raise RuntimeError(f"unknown backend: {effective_backend}")
        _backend_cache.append(b)
        return b

    # --- Portrait-ordering guard --------------------------------------
    # Pipes 2 and 3 both need a portrait to pass to the backend as an
    # identity anchor. If the caller skipped portrait generation, we
    # require that an existing portrait.png already lives in each
    # variant's bundle directory (typical re-run workflow: "just
    # regenerate my chop sheet, don't touch the portrait"). Enforcing
    # this BEFORE any filesystem side effects gives the user a clear
    # early error instead of a half-built bundle whose actions are
    # silently missing their identity anchor.
    needs_identity_anchor = (not args.skip_walking) or bool(requested_actions)
    if args.skip_portrait and needs_identity_anchor:
        missing_portraits: list[str] = []
        for bdir in variant_dirs:
            if not (bdir / "portrait.png").is_file():
                missing_portraits.append(str(bdir))
        if missing_portraits:
            print(
                json.dumps(
                    {
                        "error": (
                            "--skip-portrait requires an existing "
                            "portrait.png in every target bundle "
                            "directory because pipe 2 (walking) and "
                            "pipe 3 (actions) use the portrait as an "
                            "identity anchor. Missing in: "
                            f"{missing_portraits}"
                        )
                    }
                ),
                file=sys.stderr,
            )
            return 2

    # Pre-validate that every requested action's LimeZu source is on
    # disk. Previously this was also where we pre-reshaped them into a
    # shared cache; now each variant re-generates via `run_action_sheet`
    # so all we need is a reachability check that fails fast before any
    # variant burns Gemini budget on pipes 1/2 only to die on pipe 3.
    action_catalog_errors: dict[str, str] = {}
    for key in requested_actions:
        profile = catalog[key]
        try:
            load_limezu_action_sheet(profile)
        except (ActionSourceMissingError, ValueError) as err:
            action_catalog_errors[key] = f"{type(err).__name__}: {err}"

    created_at = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")

    # Announce the overall plan so the streaming UI can render empty
    # progress bars BEFORE any pipe starts working. Gives the user
    # immediate feedback that generation is under way.
    _emit_progress(
        "bundle_start",
        variants=n_variants,
        slug=args.slug,
        asset_type=asset_type,
        actions=requested_actions,
        skip_portrait=bool(args.skip_portrait),
        skip_walking=bool(args.skip_walking),
    )

    # --- Per-variant loop: pipes 1 + 2 fresh, pipe 3 copied ------------
    bundle_payloads: list[dict] = []
    for v_idx, bdir in enumerate(variant_dirs):
        variant_slug = _variant_slug(v_idx)
        bdir.mkdir(parents=True, exist_ok=True)

        _emit_progress(
            "variant_start",
            variant=v_idx + 1,
            variant_slug=variant_slug,
        )

        pipes_report: dict = {"portrait": None, "walking": None, "actions": {}}
        errors: list[str] = []
        # Per-pipe usage bookkeeping — populated if the pipe hit an AI
        # backend. All three pipes now touch the backend (pipe 3 moved
        # from a deterministic reshape to a full AI call per action), so
        # all three contribute to the total.
        pipe_usage: dict[str, UsageRecord | None] = {
            "portrait": None,
            "walking": None,
            "actions": None,
        }

        # Pipe 1: portrait
        portrait_rel: str | None = None
        # Absolute path to the portrait that will feed pipes 2 and 3 as
        # the identity anchor. Resolved either from a freshly generated
        # portrait (pipe 1) or from a pre-existing portrait on disk
        # (reuse case under --skip-portrait). Stays None if portrait
        # was both skipped AND absent — in that case the ordering
        # guard above would already have returned, so it only stays
        # None here when pipe 2 and pipe 3 are both also skipped.
        portrait_identity_path: Path | None = None
        if not args.skip_portrait:
            _emit_progress("pipe_start", variant=v_idx + 1, pipe="portrait")
            try:
                backend = _get_backend()
                result = run(
                    GenerateRequest(
                        project=project,
                        kind="character",
                        prompt=args.prompt,
                        variants=1,
                        footprint=None,
                        sheet=None,
                        anchor=None,
                        extra_reference=None,
                    ),
                    backend=backend,
                )
                if not result.variants:
                    raise RuntimeError("generate produced 0 variants")
                src = Path(result.variants[0].path)
                dst = bdir / "portrait.png"
                shutil.copyfile(src, dst)
                portrait_rel = "portrait.png"
                portrait_identity_path = dst
                pipes_report["portrait"] = {"ok": True, "path": str(dst)}
                pipe_usage["portrait"] = result.usage
                _emit_progress(
                    "pipe_done",
                    variant=v_idx + 1,
                    pipe="portrait",
                    ok=True,
                    usage=_usage_as_dict(result.usage),
                )
            except Exception as err:  # noqa: BLE001 - top-level boundary
                msg = f"{type(err).__name__}: {err}"
                errors.append(f"portrait: {msg}")
                pipes_report["portrait"] = {"ok": False, "error": msg}
                _emit_progress(
                    "pipe_done",
                    variant=v_idx + 1,
                    pipe="portrait",
                    ok=False,
                    error=msg,
                )
        else:
            # Skip path: ordering guard above already ensured the
            # portrait is on disk when pipes 2/3 need it. Surface it as
            # the identity anchor for this variant.
            existing = bdir / "portrait.png"
            if existing.is_file():
                portrait_identity_path = existing
                portrait_rel = "portrait.png"

        # Pipe 2: walking sheet
        walking_sheet_info: BundleSheet | None = None
        if not args.skip_walking:
            _emit_progress("pipe_start", variant=v_idx + 1, pipe="walking")
            if not args.walking_reference:
                msg = "--walking-reference required unless --skip-walking is set"
                errors.append(f"walking: {msg}")
                pipes_report["walking"] = {"ok": False, "error": msg}
                _emit_progress(
                    "pipe_done",
                    variant=v_idx + 1,
                    pipe="walking",
                    ok=False,
                    error=msg,
                )
            else:
                walking_ref = Path(args.walking_reference).expanduser().resolve()
                if not walking_ref.is_file():
                    msg = f"walking reference not found: {walking_ref}"
                    errors.append(f"walking: {msg}")
                    pipes_report["walking"] = {"ok": False, "error": msg}
                    _emit_progress(
                        "pipe_done",
                        variant=v_idx + 1,
                        pipe="walking",
                        ok=False,
                        error=msg,
                    )
                else:
                    profile = SHEET_PROFILES["person-premade"]
                    try:
                        # Pipe 2 receives the portrait as an identity
                        # anchor so the walking sheet's character face
                        # and outfit match pipe 1's output. Without this,
                        # the model would re-invent the character's
                        # appearance from the prompt alone and could
                        # drift from the portrait.
                        sres = sheet_run(
                            SheetRequest(
                                project=project,
                                profile=profile,
                                prompt=args.prompt,
                                reference_path=walking_ref,
                                variants=1,
                                extra_reference=portrait_identity_path,
                            )
                        )
                        if not sres.variants:
                            raise RuntimeError("sheet produced 0 clean variants")
                        src = Path(sres.variants[0].clean_path)
                        dst = bdir / "walking.png"
                        shutil.copyfile(src, dst)
                        src_sidecar = Path(sres.variants[0].sidecar_path)
                        if src_sidecar.is_file():
                            shutil.copyfile(src_sidecar, bdir / "walking.meta.json")
                        walking_sheet_info = BundleSheet(
                            path="walking.png",
                            profile_id=profile.id,
                            cell=profile.target_cell,
                            rows=profile.target_rows,
                            cols=profile.target_cols,
                            direction_order=profile.direction_order,
                            frames_per_dir=None,
                        )
                        pipes_report["walking"] = {
                            "ok": True,
                            "path": str(dst),
                            "dims": _walking_dims_from_sidecar(
                                bdir / "walking.meta.json", profile
                            ),
                        }
                        pipe_usage["walking"] = sres.usage
                        _emit_progress(
                            "pipe_done",
                            variant=v_idx + 1,
                            pipe="walking",
                            ok=True,
                            usage=_usage_as_dict(sres.usage),
                        )

                        # Optional post-step: regenerate the walk row
                        # direction-by-direction. Uses the just-generated
                        # walking.png as base_sheet (idle row = identity
                        # anchor) and the same walking_ref as layout anchor.
                        if args.refine_walk:
                            _emit_progress(
                                "pipe_start",
                                variant=v_idx + 1,
                                pipe="walk_refine",
                            )
                            try:
                                rres = refine_sheet_walk(
                                    WalkRefineRequest(
                                        project=project,
                                        profile=profile,
                                        base_sheet=dst,
                                        prompt=args.prompt,
                                        layout_reference=walking_ref,
                                        variants=1,
                                    )
                                )
                                if rres.variants:
                                    refined_src = rres.variants[0].clean_path
                                    shutil.copyfile(refined_src, dst)
                                    refined_meta = rres.variants[0].sidecar_path
                                    if refined_meta.is_file():
                                        shutil.copyfile(
                                            refined_meta,
                                            bdir / "walking.meta.json",
                                        )
                                    pipes_report["walking"]["refined"] = True
                                    pipes_report["walking"]["refine_errors"] = rres.errors
                                else:
                                    pipes_report["walking"]["refined"] = False
                                    pipes_report["walking"]["refine_errors"] = (
                                        rres.errors or ["no refined variants"]
                                    )
                                if rres.usage is not None:
                                    cur = pipe_usage["walking"]
                                    if cur is None:
                                        pipe_usage["walking"] = rres.usage
                                    else:
                                        cur.prompt_tokens += rres.usage.prompt_tokens
                                        cur.output_tokens += rres.usage.output_tokens
                                        cur.total_tokens += rres.usage.total_tokens
                                        cur.call_count += rres.usage.call_count
                                _emit_progress(
                                    "pipe_done",
                                    variant=v_idx + 1,
                                    pipe="walk_refine",
                                    ok=bool(rres.variants),
                                    usage=_usage_as_dict(rres.usage),
                                )
                            except Exception as err:  # noqa: BLE001
                                rmsg = f"{type(err).__name__}: {err}"
                                pipes_report["walking"]["refined"] = False
                                pipes_report["walking"]["refine_errors"] = [rmsg]
                                errors.append(f"walk_refine: {rmsg}")
                                _emit_progress(
                                    "pipe_done",
                                    variant=v_idx + 1,
                                    pipe="walk_refine",
                                    ok=False,
                                    error=rmsg,
                                )
                    except Exception as err:  # noqa: BLE001
                        msg = f"{type(err).__name__}: {err}"
                        errors.append(f"walking: {msg}")
                        pipes_report["walking"] = {"ok": False, "error": msg}
                        _emit_progress(
                            "pipe_done",
                            variant=v_idx + 1,
                            pipe="walking",
                            ok=False,
                            error=msg,
                        )

        # Pipe 3: per-action AI generation.
        #
        # For each requested action, call `run_action_sheet` which uses
        # the LimeZu farmer sheet as a layout reference and the portrait
        # as an identity anchor to produce a sprite sheet of OUR
        # character performing the action. Each variant produces fresh
        # outputs (no cross-variant sharing) because the generated
        # frames depend on the variant's own portrait.
        action_sheet_infos: dict[str, BundleSheet] = {}
        action_usage_records: list[UsageRecord | None] = []
        if requested_actions:
            _emit_progress(
                "pipe_start",
                variant=v_idx + 1,
                pipe="actions",
                actions=requested_actions,
            )
            actions_dir = bdir / "actions"
            actions_dir.mkdir(parents=True, exist_ok=True)
            # Backend is looked up lazily so a LimeZu-sources-missing
            # case (every action pre-errored) never needs a working
            # backend at all — important for tests that exercise the
            # error path without providing a stub template.
            action_backend = None
            for key in requested_actions:
                # Fail fast if the LimeZu source for this action was
                # missing at startup (pre-validated above). Keeping the
                # per-variant error structure consistent with the old
                # code path so downstream consumers don't break.
                if key in action_catalog_errors:
                    msg = action_catalog_errors[key]
                    errors.append(f"action {key}: {msg}")
                    pipes_report["actions"][key] = {"ok": False, "error": msg}
                    continue
                profile = catalog[key]
                try:
                    if action_backend is None:
                        action_backend = _get_backend()
                    ares = run_action_sheet(
                        ActionSheetRequest(
                            project=project,
                            profile=profile,
                            prompt=args.prompt,
                            variants=1,
                            extra_reference=portrait_identity_path,
                        ),
                        backend=action_backend,
                    )
                    if ares.errors and not ares.variants:
                        raise RuntimeError("; ".join(ares.errors))
                    if not ares.variants:
                        raise RuntimeError("action pipeline produced 0 variants")
                    src = Path(ares.variants[0].clean_path)
                    dst = actions_dir / f"{key}.png"
                    shutil.copyfile(src, dst)
                    # Sidecar tag-along so downstream tooling can see
                    # the same per-variant metadata the walking sheet
                    # gets. We name it `<action>.meta.json` next to the
                    # action PNG, mirroring walking's convention.
                    src_sidecar = Path(ares.variants[0].sidecar_path)
                    if src_sidecar.is_file():
                        shutil.copyfile(src_sidecar, actions_dir / f"{key}.meta.json")
                    action_sheet_infos[key] = BundleSheet(
                        path=f"actions/{key}.png",
                        profile_id=profile.id,
                        cell=(profile.cell_w, profile.cell_h),
                        rows=len(profile.direction_order),
                        cols=profile.frames_per_dir,
                        direction_order=profile.direction_order,
                        frames_per_dir=profile.frames_per_dir,
                    )
                    pipes_report["actions"][key] = {
                        "ok": True,
                        "path": str(dst),
                        "dims": {
                            "cell": [profile.cell_w, profile.cell_h],
                            "rows": len(profile.direction_order),
                            "cols": profile.frames_per_dir,
                            "frames_per_dir": profile.frames_per_dir,
                            "direction_order": list(profile.direction_order),
                        },
                    }
                    action_usage_records.append(ares.usage)
                except Exception as err:  # noqa: BLE001
                    msg = f"{type(err).__name__}: {err}"
                    errors.append(f"action {key}: {msg}")
                    pipes_report["actions"][key] = {"ok": False, "error": msg}
            # Summed action usage for this variant. Collected into a
            # single UsageRecord so the summary path below treats actions
            # symmetrically with portrait and walking.
            pipe_usage["actions"] = _sum_usage_records_to_record(
                action_usage_records
            )
            _emit_progress(
                "pipe_done",
                variant=v_idx + 1,
                pipe="actions",
                ok=not any(
                    p and not p.get("ok", False)
                    for p in pipes_report["actions"].values()
                ),
                usage=_usage_as_dict(pipe_usage["actions"]),
            )

        bundle_obj = CharacterBundle(
            schema_version=BUNDLE_SCHEMA_VERSION,
            slug=variant_slug,
            source_prompt=args.prompt,
            created_at=created_at,
            portrait=portrait_rel,
            walking=walking_sheet_info,
            actions=action_sheet_infos,
        )
        manifest = save_bundle(bdir, bundle_obj)

        # Build usage summary for this variant: per-pipe + total. All
        # three pipes now touch the backend, so all three are summed.
        usage_summary: dict = {
            "portrait": _usage_as_dict(pipe_usage["portrait"]),
            "walking": _usage_as_dict(pipe_usage["walking"]),
            "actions": _usage_as_dict(pipe_usage["actions"]),
            "total": _sum_usage_dicts(
                [
                    pipe_usage["portrait"],
                    pipe_usage["walking"],
                    pipe_usage["actions"],
                ]
            ),
        }

        bundle_payloads.append(
            {
                "bundle_dir": str(bdir),
                "manifest_path": str(manifest),
                "slug": variant_slug,
                "pipes": pipes_report,
                "errors": errors,
                "usage": usage_summary,
            }
        )
        _emit_progress(
            "variant_done",
            variant=v_idx + 1,
            variant_slug=variant_slug,
            errors=errors,
            usage=usage_summary["total"],
        )

    # Top-level response: back-compat fields mirror bundles[0]; N is
    # discoverable via the `bundles` array length. The top-level
    # `usage_total` is the grand total across ALL variants (useful for
    # "what did this run cost me" headline).
    first = bundle_payloads[0]
    grand_totals: list[UsageRecord | None] = []
    for b in bundle_payloads:
        grand_totals.append(
            _usage_from_summary_total(b["usage"]["total"])
        )
    payload = {
        "bundle_dir": first["bundle_dir"],
        "manifest_path": first["manifest_path"],
        "slug": first["slug"],
        "pipes": first["pipes"],
        "errors": first["errors"],
        "bundles": bundle_payloads,
        "usage_total": _sum_usage_records(grand_totals),
    }
    _emit_progress(
        "bundle_done",
        variants=len(bundle_payloads),
        usage_total=payload["usage_total"],
    )
    print(json.dumps(payload))
    # Exit code: 0 iff EVERY variant ran clean. 3 if any variant had an
    # error (matches the single-variant semantics of the prior version).
    any_errors = any(b["errors"] for b in bundle_payloads)
    return 0 if not any_errors else 3


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

    srw = sub.add_parser(
        "sheet-refine-walk",
        help=(
            "Regenerate the walk row of an existing sheet one direction "
            "at a time, using the base sheet's idle strip as identity anchor"
        ),
    )
    srw.add_argument("--projects-root", default="projects")
    srw.add_argument("--project", required=True)
    srw.add_argument(
        "--profile",
        required=True,
        choices=sorted(SHEET_PROFILES),
        help="Sheet contract profile (person-premade recommended)",
    )
    srw.add_argument(
        "--base-sheet",
        required=True,
        help="Absolute path to an existing clean sheet PNG to refine",
    )
    srw.add_argument(
        "--layout-reference",
        required=True,
        help=(
            "Absolute path to a known-good premade-style sheet whose walk "
            "row is used as the layout/style anchor for each direction"
        ),
    )
    srw.add_argument(
        "--prompt",
        required=True,
        help="Character description (same vocabulary as pf sheet --prompt)",
    )
    srw.add_argument(
        "--variants",
        type=int,
        default=1,
        help=(
            "Number of candidate composites to assemble (K). Each "
            "direction's generate() call produces K candidates in one "
            "API call, so total Gemini calls = 4, not 4*K — but cost per "
            "call scales with K."
        ),
    )
    srw.set_defaults(func=_cmd_sheet_refine_walk)

    bundle = sub.add_parser(
        "bundle",
        help="Build a 3-pipe character bundle (portrait + walking + actions)",
    )
    bundle.add_argument("--projects-root", default="projects")
    bundle.add_argument("--project", required=True)
    bundle.add_argument(
        "--slug",
        required=True,
        help="Bundle slug (ASCII alnum/-/_, <=64 chars); used as directory name",
    )
    bundle.add_argument(
        "--prompt",
        required=True,
        help="Character description, shared by portrait and walking pipes",
    )
    bundle.add_argument(
        "--actions",
        default="",
        help=(
            "Comma-separated action keys to include in pipe 3. Valid keys: "
            + ", ".join(sorted(FARMER_ACTIONS))
        ),
    )
    bundle.add_argument(
        "--walking-reference",
        default=None,
        help=(
            "Absolute path to the person-premade layout reference PNG. "
            "Required unless --skip-walking is set."
        ),
    )
    bundle.add_argument(
        "--skip-portrait",
        action="store_true",
        help="Skip pipe 1 (portrait generation)",
    )
    bundle.add_argument(
        "--skip-walking",
        action="store_true",
        help="Skip pipe 2 (walking sheet generation)",
    )
    bundle.add_argument(
        "--refine-walk",
        action="store_true",
        help=(
            "After pipe 2 succeeds, regenerate the walk row one direction "
            "at a time (4 extra Gemini calls per variant) using the just-"
            "generated idle row as the identity anchor. Improves walk "
            "cycle quality at the cost of 4x the walking-pipe API calls."
        ),
    )
    bundle.add_argument(
        "--backend",
        choices=["gemini", "pixellab", "stub"],
        default=None,
        help="Generation backend (default: project.toml setting or gemini)",
    )
    bundle.add_argument(
        "--stub-template",
        default=None,
        help="Path to a PNG template (only with --backend stub, for tests)",
    )
    bundle.add_argument(
        "--variants",
        type=int,
        default=1,
        help=(
            "Number of candidate bundles to produce in a single run. "
            "When >1, each variant is written to a sibling directory "
            "<slug>-v1/, <slug>-v2/, ... with its own bundle.json (slug "
            "'<slug>-vK'). ALL three pipes now re-run per variant, so "
            "N variants × M actions is N × (2 + M) backend calls — "
            "plan budget accordingly."
        ),
    )
    bundle.add_argument(
        "--asset-type",
        choices=BUNDLE_ASSET_TYPES,
        default="person",
        help=(
            "Selects the action/state catalog for pipe 3. 'person' uses "
            "HUMAN_ACTIONS (farmer actions today). 'animal' and "
            "'decoration' are plumbed but their catalogs are not yet "
            "populated — requesting actions for them surfaces a clear "
            "'no catalog registered' error."
        ),
    )
    bundle.set_defaults(func=_cmd_bundle)

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
