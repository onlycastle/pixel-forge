"""Batch re-generate legacy props with proper footprints.

Background: the pre-Phase-1 `--kind prop` pipeline never downscaled
Gemini's raw 1024×1024 output, so every migrated prop has a nonsensical
32×32 tile footprint in its sidecar. This one-shot script regenerates
each prop via the new `pf generate --kind placeable --footprint WxH`
path, writing fresh variants into a review directory for manual approval.

Usage
-----

    python tools/pixel_forge/batch_regenerate_props.py \
        --project sunny-street \
        --variants 4

Add `--dry-run` to see what it *would* do without calling the backend.
Add `--only <slug>` to regenerate one prop at a time for spot-checking.

The table below is the authoritative footprint map — keep it in sync
with `projects/sunny-street/out/placeables/REGENERATION_PLAN.md`.

Outputs land in `<project>/out/placeables/_regenerated/<timestamp>/`
so the legacy 1024×1024 PNGs stay untouched until you've reviewed the
new ones. After review, `pf promote --path <variant.png> --canonical-name
<slug>` moves the accepted variant to `out/placeables/<slug>.png`.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


# Hardcoded — keep in sync with REGENERATION_PLAN.md. Slug → (w, h) in tiles.
PROP_FOOTPRINTS: dict[str, tuple[int, int]] = {
    "apple-barrel":          (1, 1),
    "beach-umbrella-open":   (2, 2),
    "bread-basket":          (1, 1),
    "buoy-red":              (1, 1),
    "cheese-wheel-stack":    (1, 1),
    "crab-trap-wicker":      (1, 1),
    "dock-lantern-pole":     (1, 2),
    "feed-sack":             (1, 1),
    "fishing-barrel":        (1, 1),
    "flag-pole-tall":        (1, 3),
    "flower-stall":          (2, 2),
    "fruit-stall-loaded":    (2, 2),
    "hanging-fishing-net":   (2, 2),
    "hay-bale-round-large":  (2, 2),
    "market-stall-empty":    (2, 2),
    "message-in-bottle":     (1, 1),
    "pitchfork-leaning":     (1, 2),
    "pumpkin-crate":         (1, 1),
    "sandcastle":            (1, 1),
    "spice-jar-row":         (1, 1),
    "vegetable-crate-full":  (1, 1),
    "wheelbarrow-empty":     (2, 1),
    "wheelbarrow-with-hay":  (2, 1),
    "wooden-cart-empty":     (2, 2),
    "wooden-crate-large":    (1, 1),
    "wooden-crate-small":    (1, 1),
    "wooden-rowboat":        (3, 1),
    "wooden-signpost":       (1, 2),
}


def _slug_to_prompt(slug: str) -> str:
    """Humanize a slug back into a natural-language prompt.

    `wooden-rowboat` → `weathered wooden rowboat, side view, centered,
    transparent background`. The style guide adds art direction on top
    — this function only names the subject.
    """
    subject = slug.replace("-", " ")
    return f"{subject}, side view, centered, transparent background"


def _eligible_slugs(
    pf_project: Path,
    only: str | None,
) -> list[str]:
    """Return the slug list to regenerate.

    A slug is eligible if:
      - it's in PROP_FOOTPRINTS, AND
      - the canonical file `<project>/out/placeables/<slug>.png` exists, AND
      - its sidecar says migrated_from = "props" (so we don't touch the
        47 ex-`tiles/` files that migrated cleanly).
    """
    placeables = pf_project / "out" / "placeables"
    slugs: list[str] = []
    for slug in PROP_FOOTPRINTS:
        if only and slug != only:
            continue
        png = placeables / f"{slug}.png"
        meta = placeables / f"{slug}.meta.json"
        if not png.is_file() or not meta.is_file():
            print(f"skip {slug}: missing canonical PNG or sidecar", file=sys.stderr)
            continue
        try:
            sidecar = json.loads(meta.read_text())
        except json.JSONDecodeError:
            print(f"skip {slug}: sidecar unreadable", file=sys.stderr)
            continue
        if sidecar.get("migrated_from") != "props":
            print(
                f"skip {slug}: migrated_from={sidecar.get('migrated_from')!r}, "
                f"not a legacy prop",
                file=sys.stderr,
            )
            continue
        slugs.append(slug)
    return slugs


def _run_generate_once(
    projects_root: Path,
    project_name: str,
    slug: str,
    footprint: tuple[int, int],
    variants: int,
    backend: str,
    stub_template: Path | None,
) -> dict:
    w, h = footprint
    cmd = [
        sys.executable,
        "-m",
        "pixel_forge",
        "generate",
        "--projects-root",
        str(projects_root),
        "--project",
        project_name,
        "--kind",
        "placeable",
        "--footprint",
        f"{w}x{h}",
        "--prompt",
        _slug_to_prompt(slug),
        "--variants",
        str(variants),
        "--backend",
        backend,
    ]
    if stub_template is not None:
        cmd.extend(["--stub-template", str(stub_template)])
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"generate failed for {slug}: rc={proc.returncode} "
            f"stderr={proc.stderr.strip()}"
        )
    return json.loads(proc.stdout)


def _move_variants_to_review(
    pf_project: Path,
    slug: str,
    variant_paths: list[Path],
    review_dir: Path,
) -> list[Path]:
    """Move fresh variants out of `out/placeables/` into a review bucket.

    This keeps the top-level `out/placeables/` tidy (just canonical files)
    and makes the review workflow obvious — the user only sees new work
    in one place.
    """
    slug_dir = review_dir / slug
    slug_dir.mkdir(parents=True, exist_ok=True)
    moved: list[Path] = []
    for vp in variant_paths:
        target_png = slug_dir / vp.name
        shutil.move(str(vp), target_png)
        # The sidecar rides along.
        sidecar = vp.with_suffix(".meta.json")
        if sidecar.is_file():
            shutil.move(str(sidecar), slug_dir / sidecar.name)
        moved.append(target_png)
    return moved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Batch re-generate legacy props with proper footprints"
    )
    parser.add_argument("--projects-root", default="projects")
    parser.add_argument("--project", required=True)
    parser.add_argument("--variants", type=int, default=4)
    parser.add_argument(
        "--backend",
        choices=["gemini", "stub"],
        default="gemini",
        help="Use 'stub' with --stub-template for dry validation",
    )
    parser.add_argument("--stub-template", help="PNG path for stub backend")
    parser.add_argument(
        "--only",
        help="Regenerate a single slug (for spot-checking)",
        default=None,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would run without calling the backend",
    )
    args = parser.parse_args(argv)

    projects_root = Path(args.projects_root).resolve()
    pf_project = projects_root / args.project
    if not (pf_project / "project.toml").is_file():
        print(
            json.dumps({"error": f"project not found: {pf_project}"}),
            file=sys.stderr,
        )
        return 2

    eligible = _eligible_slugs(pf_project, args.only)
    if not eligible:
        print(json.dumps({"error": "no eligible slugs to regenerate"}), file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "project": args.project,
                "eligible_count": len(eligible),
                "variants_per_slug": args.variants,
                "backend": args.backend,
                "dry_run": args.dry_run,
            }
        )
    )

    if args.dry_run:
        for slug in eligible:
            w, h = PROP_FOOTPRINTS[slug]
            print(f"[dry-run] {slug}  --footprint {w}x{h}  --variants {args.variants}")
        return 0

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    review_root = pf_project / "out" / "placeables" / "_regenerated" / ts
    review_root.mkdir(parents=True, exist_ok=True)

    stub_template_path = Path(args.stub_template).resolve() if args.stub_template else None

    report: dict = {"regenerated": [], "failed": [], "review_dir": str(review_root)}

    for slug in eligible:
        footprint = PROP_FOOTPRINTS[slug]
        try:
            payload = _run_generate_once(
                projects_root=projects_root,
                project_name=args.project,
                slug=slug,
                footprint=footprint,
                variants=args.variants,
                backend=args.backend,
                stub_template=stub_template_path,
            )
        except Exception as err:  # noqa: BLE001 - top-level boundary
            report["failed"].append({"slug": slug, "error": str(err)})
            print(f"FAIL {slug}: {err}", file=sys.stderr)
            continue

        variant_png_paths = [Path(v["path"]) for v in payload.get("variants", [])]
        moved = _move_variants_to_review(
            pf_project=pf_project,
            slug=slug,
            variant_paths=variant_png_paths,
            review_dir=review_root,
        )
        report["regenerated"].append(
            {
                "slug": slug,
                "footprint": {"w": footprint[0], "h": footprint[1]},
                "variants": [str(p) for p in moved],
                "passed": sum(1 for v in payload.get("variants", []) if v["passed"]),
            }
        )
        print(f"OK   {slug}  footprint={footprint}  variants={len(moved)}")

    (review_root / "batch-report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"summary": {
        "regenerated": len(report["regenerated"]),
        "failed": len(report["failed"]),
        "review_dir": str(review_root),
    }}))
    return 0 if not report["failed"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
