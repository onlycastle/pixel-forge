#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


REQUIRED = (
    "spec.json",
    "identity.png",
    "walk.png",
    "walk-contact.png",
    "walk.gif",
    "walk-validation.json",
    "being-manifest.json",
    "pipeline-run.json",
    "run-summary.json",
    "capability-matrix.json",
    "plan.md",
    "prompts.md",
    "learnings.md",
)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: summarize_run.py <run-dir>", file=sys.stderr)
        return 2

    run_dir = Path(args[0]).resolve()
    try:
        manifest = _read_json(run_dir / "being-manifest.json")
        pipeline = _read_json(run_dir / "pipeline-run.json")
        capability = _read_json(run_dir / "capability-matrix.json")
    except (FileNotFoundError, json.JSONDecodeError) as err:
        print(str(err), file=sys.stderr)
        return 1

    stages = pipeline.get("stages", []) if isinstance(pipeline, dict) else []
    failed_stage = next(
        (
            stage.get("name")
            for stage in stages
            if isinstance(stage, dict) and stage.get("status") == "failed"
        ),
        None,
    )
    missing = [rel for rel in REQUIRED if not (run_dir / rel).exists()]
    validation_reports = _validation_reports(manifest, run_dir)
    summary = {
        "schema": "pixel-forge.plugin.digital-being.run-summary.v1",
        "status": "failed" if failed_stage else "passed",
        "slug": manifest.get("slug") if isinstance(manifest, dict) else None,
        "manifest": "being-manifest.json",
        "failed_stage": failed_stage,
        "required_artifact_coverage": {
            "required": list(REQUIRED),
            "missing": missing,
        },
        "validation_reports": validation_reports,
        "stages": [
            {
                "name": stage.get("name"),
                "status": stage.get("status"),
                "error": stage.get("error"),
            }
            for stage in stages
            if isinstance(stage, dict)
        ],
        "capability_routes": capability.get("routes", [])
        if isinstance(capability, dict)
        else [],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 1 if missing else 0


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _validation_reports(manifest: Any, run_dir: Path) -> list[str]:
    reports: list[str] = []
    if not isinstance(manifest, dict):
        return reports
    top_level = manifest.get("validation_report")
    if isinstance(top_level, str) and (run_dir / top_level).exists():
        reports.append(top_level)
    animations = manifest.get("animations", {})
    if isinstance(animations, dict):
        for animation in animations.values():
            if not isinstance(animation, dict):
                continue
            metadata = animation.get("metadata", {})
            if isinstance(metadata, dict):
                report = metadata.get("validation_report")
                if isinstance(report, str) and report not in reports:
                    reports.append(report)
    return reports


if __name__ == "__main__":
    raise SystemExit(main())
