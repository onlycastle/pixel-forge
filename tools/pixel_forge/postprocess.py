from __future__ import annotations

from PIL import Image


def ensure_alpha(img: Image.Image, alpha_threshold: int = 220) -> Image.Image:
    """Return an RGBA copy where pixels with alpha below the threshold are fully transparent.

    Nano Banana frequently produces semi-transparent fringe pixels at edges.
    This collapses them to fully transparent so quantization doesn't fight them.
    """
    rgba = img.convert("RGBA")
    pixels = rgba.load()
    for y in range(rgba.height):
        for x in range(rgba.width):
            r, g, b, a = pixels[x, y]
            if a < alpha_threshold:
                pixels[x, y] = (0, 0, 0, 0)
    return rgba
