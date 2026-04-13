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


def quantize_to_palette(
    img: Image.Image,
    palette: list[tuple[int, int, int]],
) -> Image.Image:
    """Snap every opaque pixel to the nearest palette color (Euclidean RGB distance).

    Transparent pixels (alpha == 0) are left untouched so empty areas stay empty.
    """
    rgba = img.convert("RGBA")
    pixels = rgba.load()
    for y in range(rgba.height):
        for x in range(rgba.width):
            r, g, b, a = pixels[x, y]
            if a == 0:
                continue
            best = min(
                palette,
                key=lambda p: (p[0] - r) ** 2 + (p[1] - g) ** 2 + (p[2] - b) ** 2,
            )
            pixels[x, y] = (best[0], best[1], best[2], a)
    return rgba


def snap_to_grid(img: Image.Image, tile_size: int) -> Image.Image:
    """Resize the image so width and height are multiples of tile_size.

    Rounds each dimension to the nearest multiple, with a minimum of one tile.
    Uses nearest-neighbor so pixel art stays crisp.
    """
    def _snap(value: int) -> int:
        return max(tile_size, round(value / tile_size) * tile_size)

    target = (_snap(img.width), _snap(img.height))
    if target == img.size:
        return img
    return img.resize(target, Image.Resampling.NEAREST)
