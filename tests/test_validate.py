from PIL import Image

from pixel_forge.validate import (
    CheckResult,
    check_alpha,
    check_grid,
    check_palette,
)


def test_check_palette_pass_when_all_pixels_in_palette() -> None:
    palette = [(0, 0, 0), (255, 255, 255)]
    img = Image.new("RGBA", (2, 2), (255, 255, 255, 255))

    result = check_palette(img, palette, max_off_palette=0)

    assert result.status == "pass"
    assert result.details["off_palette_count"] == 0


def test_check_palette_fail_when_off_palette_pixel_present() -> None:
    palette = [(0, 0, 0), (255, 255, 255)]
    img = Image.new("RGBA", (2, 2), (255, 255, 255, 255))
    img.putpixel((0, 0), (255, 0, 0, 255))

    result = check_palette(img, palette, max_off_palette=0)

    assert result.status == "fail"
    assert result.details["off_palette_count"] == 1


def test_check_palette_ignores_transparent_pixels() -> None:
    palette = [(0, 0, 0)]
    img = Image.new("RGBA", (2, 2), (0, 0, 0, 0))

    result = check_palette(img, palette, max_off_palette=0)

    assert result.status == "pass"


def test_check_grid_pass_on_exact_tile_multiple() -> None:
    img = Image.new("RGBA", (32, 16), (0, 0, 0, 255))

    result = check_grid(img, tile_size=16)

    assert result.status == "pass"


def test_check_grid_fail_on_non_multiple_dimension() -> None:
    img = Image.new("RGBA", (18, 16), (0, 0, 0, 255))

    result = check_grid(img, tile_size=16)

    assert result.status == "fail"
    assert "width" in result.details["reason"]


def test_check_alpha_pass_when_edges_fully_transparent() -> None:
    img = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
    img.putpixel((1, 1), (255, 255, 255, 255))
    img.putpixel((2, 2), (255, 255, 255, 255))

    result = check_alpha(img)

    assert result.status == "pass"


def test_check_alpha_warn_when_semi_transparent_pixel_present() -> None:
    img = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
    img.putpixel((1, 1), (255, 255, 255, 180))

    result = check_alpha(img)

    assert result.status == "warn"


def test_check_palette_tolerance_allows_some_off_palette() -> None:
    palette = [(0, 0, 0), (255, 255, 255)]
    img = Image.new("RGBA", (4, 4), (255, 255, 255, 255))
    # Stamp 3 off-palette pixels
    img.putpixel((0, 0), (255, 0, 0, 255))
    img.putpixel((1, 0), (0, 255, 0, 255))
    img.putpixel((2, 0), (0, 0, 255, 255))

    # Tolerance of 5 accepts all 3 off-palette pixels
    result = check_palette(img, palette, max_off_palette=5)

    assert result.status == "pass"
    assert result.details["off_palette_count"] == 3


def test_check_grid_fail_on_non_multiple_height() -> None:
    img = Image.new("RGBA", (16, 18), (0, 0, 0, 255))

    result = check_grid(img, tile_size=16)

    assert result.status == "fail"
    assert "height" in result.details["reason"]


def test_check_alpha_reports_semi_transparent_count_in_details() -> None:
    img = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
    img.putpixel((0, 0), (255, 255, 255, 100))
    img.putpixel((1, 1), (255, 255, 255, 200))

    result = check_alpha(img)

    assert result.status == "warn"
    assert result.details["semi_transparent_pixels"] == 2
