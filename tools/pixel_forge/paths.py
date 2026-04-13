from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

REJECTED_SUBDIR = "_rejected"

KIND_TO_SUBDIR = {
    "tile": "tiles",
    "prop": "props",
    "character": "characters",
    "map": "maps",
}


@dataclass(frozen=True)
class ProjectPaths:
    project_root: Path
    output_root: str

    def _out(self) -> Path:
        return self.project_root / self.output_root

    def kind_dir(self, kind: str) -> Path:
        if kind not in KIND_TO_SUBDIR:
            raise ValueError(f"Unknown kind: {kind!r}")
        return self._out() / KIND_TO_SUBDIR[kind]

    def rejected_dir(self, kind: str) -> Path:
        return self.kind_dir(kind) / REJECTED_SUBDIR

    def ensure(self, kind: str) -> None:
        self.kind_dir(kind).mkdir(parents=True, exist_ok=True)
        self.rejected_dir(kind).mkdir(parents=True, exist_ok=True)
