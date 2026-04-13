from __future__ import annotations

import shutil
from pathlib import Path


class StubBackend:
    """A deterministic backend that copies a template PNG n times.

    Used only in tests so integration tests exercise the full pipeline without
    burning API calls.
    """

    def __init__(self, template_path: Path, output_dir: Path) -> None:
        self.template_path = template_path
        self.output_dir = output_dir

    def generate(self, prompt: str, refs: list[Path], n: int) -> list[Path]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        for i in range(n):
            dest = self.output_dir / f"stub-v{i + 1}.png"
            shutil.copyfile(self.template_path, dest)
            paths.append(dest.resolve())
        return paths
