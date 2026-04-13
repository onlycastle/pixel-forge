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
    palette_set = set(palette)
    rgba = img.convert("RGBA")
    off_count = 0
    for y in range(rgba.height):
        for x in range(rgba.width):
            r, g, b, a = rgba.getpixel((x, y))
            if a == 0:
                continue
            if (r, g, b) not in palette_set:
                off_count += 1

    status: Status = "pass" if off_count <= max_off_palette else "fail"
    return CheckResult(status=status, details={"off_palette_count": off_count})


def check_grid(img: Image.Image, tile_size: int) -> CheckResult:
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
    rgba = img.convert("RGBA")
    semi_count = 0
    for y in range(rgba.height):
        for x in range(rgba.width):
            _, _, _, a = rgba.getpixel((x, y))
            if 0 < a < 255:
                semi_count += 1
    if semi_count == 0:
        return CheckResult(status="pass", details={})
    return CheckResult(status="warn", details={"semi_transparent_pixels": semi_count})
