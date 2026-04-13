from __future__ import annotations

from pathlib import Path
from typing import Protocol


class ImageBackend(Protocol):
    def generate(self, prompt: str, refs: list[Path], n: int) -> list[Path]:
        """Generate n images and return local file paths to the raw PNGs.

        The caller is responsible for postprocessing and moving files into place.
        Backends may write into any writable directory; paths must be absolute.
        """
        ...
