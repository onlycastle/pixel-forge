#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


REQUIRED_ARTIFACTS = (
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
        print("usage: check_artifacts.py <run-dir>", file=sys.stderr)
        return 2

    run_dir = Path(args[0]).resolve()
    errors: list[str] = []
    if not run_dir.is_dir():
        print(f"run directory not found: {run_dir}", file=sys.stderr)
        return 2

    for rel in REQUIRED_ARTIFACTS:
        if not (run_dir / rel).is_file():
            errors.append(f"missing required artifact: {rel}")

    for rel_json in ("being-manifest.json", "pipeline-run.json", "run-summary.json"):
        path = run_dir / rel_json
        if path.is_file():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as err:
                errors.append(f"{rel_json}: invalid JSON: {err}")
                continue
            errors.extend(_referenced_path_errors(run_dir, rel_json, payload))

    capability_path = run_dir / "capability-matrix.json"
    if capability_path.is_file():
        try:
            capability = json.loads(capability_path.read_text(encoding="utf-8"))
            errors.extend(_capability_errors(capability))
        except json.JSONDecodeError as err:
            errors.append(f"capability-matrix.json: invalid JSON: {err}")

    for error in errors:
        print(error, file=sys.stderr)
    return 1 if errors else 0


def _referenced_path_errors(root: Path, label: str, payload: Any) -> list[str]:
    refs: list[str] = []
    _collect_path_refs(payload, refs)
    errors: list[str] = []
    for ref in refs:
        if _looks_external_or_non_file(ref):
            continue
        resolved = (root / ref).resolve()
        if not _is_relative_to(resolved, root):
            errors.append(f"{label}: path escapes run directory: {ref}")
        elif not resolved.exists():
            errors.append(f"{label}: referenced path missing: {ref}")
    return errors


def _collect_path_refs(value: Any, refs: list[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in PATH_KEYS:
                if isinstance(item, str):
                    refs.append(item)
            elif key in {"validation_reports"} and isinstance(item, list):
                refs.extend(str(v) for v in item if isinstance(v, str))
            elif key == "harness_artifacts" and isinstance(item, dict):
                refs.extend(str(v) for v in item.values() if isinstance(v, str))
            else:
                _collect_path_refs(item, refs)
    elif isinstance(value, list):
        for item in value:
            _collect_path_refs(item, refs)


def _capability_errors(payload: Any) -> list[str]:
    errors: list[str] = []
    routes = payload.get("routes", []) if isinstance(payload, dict) else []
    if not isinstance(routes, list):
        return ["capability-matrix.json: routes must be a list"]
    for index, route in enumerate(routes):
        if not isinstance(route, dict):
            errors.append(f"capability-matrix.json: route {index} is not an object")
            continue
        provider = str(route.get("phase_0_1_provider", "")).lower()
        status = str(route.get("status", "")).lower()
        if status == "active" and provider in {"gpt-image-2", "remove.bg", "image2video"}:
            errors.append(
                "capability-matrix.json: live provider marked active in v1: "
                f"{route.get('task', index)}"
            )
    return errors


PATH_KEYS = {
    "capability_matrix",
    "contact_sheet",
    "identity",
    "manifest",
    "path",
    "preview_gif",
    "sheet",
    "spec_path",
    "validation_report",
}


def _looks_external_or_non_file(ref: str) -> bool:
    return (
        not ref
        or ref.startswith(("http://", "https://"))
        or ref == "none"
        or ref == "null"
    )


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


if __name__ == "__main__":
    raise SystemExit(main())
