from __future__ import annotations

import shutil
from pathlib import Path

from pixel_forge.usage import UsageRecord


class StubBackend:
    """A deterministic backend that copies a template PNG n times.

    Used only in tests so integration tests exercise the full pipeline without
    burning API calls.
    """

    def __init__(self, template_path: Path, output_dir: Path) -> None:
        self.template_path = template_path
        self.output_dir = output_dir
        self.last_usage: UsageRecord | None = None

    def generate(self, prompt: str, refs: list[Path], n: int) -> list[Path]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        for i in range(n):
            dest = self.output_dir / f"stub-v{i + 1}.png"
            shutil.copyfile(self.template_path, dest)
            paths.append(dest.resolve())
        # Stub backend has zero real-world cost — record it as such so
        # callers can uniformly read `backend.last_usage` without a None
        # check path.
        self.last_usage = UsageRecord(model="stub")
        return paths
