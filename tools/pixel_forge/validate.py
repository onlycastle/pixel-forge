from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from PIL import Image

Status = Literal["pass", "warn", "fail"]


@dataclass(frozen=True)
class CheckResult:
    status: Status
    details: dict[str, Any] = field(default_factory=dict)


def check_palette(
    img: Image.Image,
    palette: list[tuple[int, int, int]],
    max_off_palette: int,
) -> CheckResult:
    """Count opaque pixels whose RGB is not in the palette.

    Transparent pixels (alpha == 0) are ignored — they have no observable
    color. Returns `pass` if off-palette count is at or below `max_off_palette`,
    otherwise `fail`. Binary for v1; the `warn` tier on `Status` is reserved
    for a future fuzz-palette policy.
    """
    palette_set = set(palette)
    rgba = img.convert("RGBA")
    pixels = rgba.load()
    off_count = 0
    for y in range(rgba.height):
        for x in range(rgba.width):
            r, g, b, a = pixels[x, y]
            if a == 0:
                continue
            if (r, g, b) not in palette_set:
                off_count += 1

    status: Status = "pass" if off_count <= max_off_palette else "fail"
    return CheckResult(status=status, details={"off_palette_count": off_count})


def check_grid(img: Image.Image, tile_size: int) -> CheckResult:
    """Check that image dimensions are exact multiples of `tile_size`.

    v1 only validates dimensional alignment. The design doc's "seamless-edge
    check for tiles" is deferred to v2. Returns on the first failing dimension
    (width before height) with a short reason string.
    """
    if img.width % tile_size != 0:
        return CheckResult(
            status="fail",
            details={"reason": f"width {img.width} not a multiple of {tile_size}"},
        )
    if img.height % tile_size != 0:
        return CheckResult(
            status="fail",
            details={"reason": f"height {img.height} not a multiple of {tile_size}"},
        )
    return CheckResult(status="pass", details={})


def check_alpha(img: Image.Image) -> CheckResult:
    """Warn if any pixel has partial transparency (0 < alpha < 255).

    Fully transparent (alpha == 0) and fully opaque (alpha == 255) pixels
    are fine. Semi-transparent pixels are a common Nano Banana artifact and
    should have been cleaned up by `postprocess.ensure_alpha` upstream; this
    check catches cases where that pass was skipped or insufficient.
    """
    rgba = img.convert("RGBA")
    pixels = rgba.load()
    semi_count = 0
    for y in range(rgba.height):
        for x in range(rgba.width):
            _, _, _, a = pixels[x, y]
            if 0 < a < 255:
                semi_count += 1
    if semi_count == 0:
        return CheckResult(status="pass", details={})
    return CheckResult(status="warn", details={"semi_transparent_pixels": semi_count})
