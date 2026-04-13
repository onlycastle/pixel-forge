from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

from pixel_forge.backends.stub import StubBackend
from pixel_forge.generate import GenerateRequest, run
from pixel_forge.paths import REJECTED_SUBDIR
from pixel_forge.project import ProjectConfigError, load_project


def _cmd_generate(args: argparse.Namespace) -> int:
    projects_root = Path(args.projects_root).resolve()
    project_dir = projects_root / args.project
    try:
        project = load_project(project_dir)
    except ProjectConfigError as err:
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
    try:
        result = run(
            GenerateRequest(
                project=project,
                kind=args.kind,
                prompt=args.prompt,
                variants=effective_variants,
            ),
            backend=backend,
        )
    except ProjectConfigError as err:
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pixel_forge")
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="Generate N variants and save them")
    gen.add_argument("--projects-root", default="projects")
    gen.add_argument("--project", required=True)
    gen.add_argument("--kind", choices=["tile", "prop", "character"], required=True)
    gen.add_argument("--prompt", required=True)
    gen.add_argument("--variants", type=int, default=None)
    gen.add_argument("--backend", choices=["gemini", "stub"], default=None)
    gen.add_argument("--stub-template", help="Path to a PNG (only with --backend stub)")
    gen.set_defaults(func=_cmd_generate)

    promote = sub.add_parser("promote", help="Promote a variant to canonical, reject siblings")
    promote.add_argument("--path", required=True)
    promote.add_argument("--canonical-name", required=True)
    promote.set_defaults(func=_cmd_promote)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
