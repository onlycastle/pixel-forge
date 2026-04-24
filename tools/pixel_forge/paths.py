from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

REJECTED_SUBDIR = "_rejected"

# Active kinds — every new generate call must use one of these.
# Sidecar `layer_target` values are defined in pixel_forge.assets.
KIND_TO_SUBDIR = {
    "ground-tileset": "tilesets/ground",
    "object-tileset": "tilesets/object",
    "placeable":      "placeables",
    "character":      "characters",
    "map":            "maps",
}

# Legacy kinds — not accepted by the CLI or generator, but the migration
# script in Phase 5 reads these paths to discover existing canonical assets
# and back-fill sidecars under the new layout.
LEGACY_KIND_SUBDIRS = {
    "tile": "tiles",
    "prop": "props",
}


@dataclass(frozen=True)
class ProjectPaths:
    project_root: Path
    output_root: str

    def _out(self) -> Path:
        return self.project_root / self.output_root

    def kind_dir(self, kind: str) -> Path:
        if kind not in KIND_TO_SUBDIR:
            raise ValueError(
                f"Unknown kind: {kind!r}. "
                f"Expected one of {sorted(KIND_TO_SUBDIR)}."
            )
        return self._out() / KIND_TO_SUBDIR[kind]

    def rejected_dir(self, kind: str) -> Path:
        return self.kind_dir(kind) / REJECTED_SUBDIR

    def ensure(self, kind: str) -> None:
        self.kind_dir(kind).mkdir(parents=True, exist_ok=True)
        self.rejected_dir(kind).mkdir(parents=True, exist_ok=True)

    def legacy_kind_dir(self, legacy_kind: str) -> Path:
        """Return the legacy kind directory (used only by the migration script)."""
        if legacy_kind not in LEGACY_KIND_SUBDIRS:
            raise ValueError(
                f"Unknown legacy kind: {legacy_kind!r}. "
                f"Expected one of {sorted(LEGACY_KIND_SUBDIRS)}."
            )
        return self._out() / LEGACY_KIND_SUBDIRS[legacy_kind]
