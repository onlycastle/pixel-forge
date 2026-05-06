#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


SUPPORTED_SCHEMA_VERSION = 1


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) not in {1, 2}:
        print(
            "usage: validate_manifest.py <being-manifest.json> [run-dir]",
            file=sys.stderr,
        )
        return 2

    manifest_path = Path(args[0]).resolve()
    run_dir = Path(args[1]).resolve() if len(args) == 2 else manifest_path.parent
    errors: list[str] = []

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"manifest not found: {manifest_path}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as err:
        print(f"invalid JSON: {err}", file=sys.stderr)
        return 1

    if not isinstance(manifest, dict):
        errors.append("manifest must be a JSON object")
    else:
        errors.extend(_validate_manifest(manifest, run_dir))

    for error in errors:
        print(error, file=sys.stderr)
    return 1 if errors else 0


def _validate_manifest(manifest: dict[str, Any], run_dir: Path) -> list[str]:
    errors: list[str] = []
    if manifest.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
        errors.append(
            "unsupported schema_version: "
            f"{manifest.get('schema_version')!r}, expected {SUPPORTED_SCHEMA_VERSION}"
        )
    for key in ("slug", "identity", "validation_report"):
        if not isinstance(manifest.get(key), str) or not manifest.get(key):
            errors.append(f"manifest missing non-empty string: {key}")

    animations = manifest.get("animations")
    if not isinstance(animations, dict) or not animations:
        errors.append("manifest must include at least one animation")
    elif isinstance(animations, dict):
        for name, animation in animations.items():
            errors.extend(_validate_animation(name, animation, run_dir))

    for key in ("identity", "validation_report"):
        value = manifest.get(key)
        if isinstance(value, str):
            errors.extend(_path_errors(run_dir, key, value))

    artifacts = manifest.get("artifacts", [])
    if not isinstance(artifacts, list):
        errors.append("manifest artifacts must be a list")
    else:
        for index, artifact in enumerate(artifacts):
            if not isinstance(artifact, dict):
                errors.append(f"artifact {index} is not an object")
                continue
            path = artifact.get("path")
            if not isinstance(path, str) or not path:
                errors.append(f"artifact {index} missing non-empty path")
                continue
            errors.extend(_path_errors(run_dir, f"artifact {index}", path))

    return errors


def _validate_animation(name: str, value: Any, run_dir: Path) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return [f"animation {name!r} is not an object"]
    frame_size = value.get("frame_size")
    if (
        not isinstance(frame_size, list)
        or len(frame_size) != 2
        or any(not isinstance(v, int) or v <= 0 for v in frame_size)
    ):
        errors.append(f"animation {name!r}: frame_size must be two positive integers")
    rows = value.get("rows")
    cols = value.get("cols")
    frames = value.get("frames")
    if not isinstance(rows, int) or rows <= 0:
        errors.append(f"animation {name!r}: rows must be positive")
    if not isinstance(cols, int) or cols <= 0:
        errors.append(f"animation {name!r}: cols must be positive")
    if not isinstance(frames, list):
        errors.append(f"animation {name!r}: frames must be a list")
    elif isinstance(rows, int) and isinstance(cols, int) and len(frames) != rows * cols:
        errors.append(
            f"animation {name!r}: frame count {len(frames)} != rows*cols {rows * cols}"
        )
    sheet = value.get("sheet")
    if not isinstance(sheet, str) or not sheet:
        errors.append(f"animation {name!r}: missing sheet")
    else:
        errors.extend(_path_errors(run_dir, f"animation {name!r} sheet", sheet))
    metadata = value.get("metadata", {})
    if isinstance(metadata, dict):
        report = metadata.get("validation_report")
        if isinstance(report, str):
            errors.extend(_path_errors(run_dir, f"animation {name!r} validation", report))
    return errors


def _path_errors(root: Path, label: str, rel: str) -> list[str]:
    resolved = (root / rel).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return [f"{label}: path escapes run directory: {rel}"]
    if not resolved.exists():
        return [f"{label}: path missing: {rel}"]
    return []


if __name__ == "__main__":
    raise SystemExit(main())
