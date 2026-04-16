"""Backend registry for pixel-forge."""
from __future__ import annotations

from pathlib import Path

from pixel_forge.backends.character import CharacterBackend


def resolve_character_backend(name: str, output_dir: Path) -> CharacterBackend:
    if name == "gemini":
        from pixel_forge.backends.gemini_character import GeminiCharacterBackend

        return GeminiCharacterBackend(output_dir=output_dir)
    elif name == "pixellab":
        from pixel_forge.backends.pixellab_character import PixelLabCharacterBackend

        return PixelLabCharacterBackend(output_dir=output_dir)
    else:
        raise ValueError(f"unknown character backend: {name!r}")
