from PIL import Image

from pixel_forge.postprocess import (
    ensure_alpha,
    quantize_to_palette,
    resize_to_tile,
    snap_to_grid,
)


def test_ensure_alpha_converts_rgb_to_rgba() -> None:
    img = Image.new("RGB", (4, 4), (255, 0, 0))

    result = ensure_alpha(img)

    assert result.mode == "RGBA"
    assert result.size == (4, 4)
    assert result.getpixel((0, 0)) == (255, 0, 0, 255)


def test_ensure_alpha_snaps_semi_transparent_edges_to_fully_transparent() -> None:
    img = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
    img.putpixel((0, 0), (255, 255, 255, 200))  # semi-transparent
    img.putpixel((1, 1), (255, 255, 255, 255))  # fully opaque, should stay

    result = ensure_alpha(img, alpha_threshold=220)

    assert result.getpixel((0, 0)) == (0, 0, 0, 0)
    assert result.getpixel((1, 1)) == (255, 255, 255, 255)


def test_ensure_alpha_keeps_pixel_exactly_at_threshold() -> None:
    """Pins the `<` (not `<=`) comparison so downstream tasks can rely on it."""
    img = Image.new("RGBA", (2, 2), (0, 0, 0, 0))
    img.putpixel((0, 0), (10, 20, 30, 220))  # exactly at threshold, must stay
    img.putpixel((1, 0), (10, 20, 30, 219))  # one below, must drop

    result = ensure_alpha(img, alpha_threshold=220)

    assert result.getpixel((0, 0)) == (10, 20, 30, 220)
    assert result.getpixel((1, 0)) == (0, 0, 0, 0)


def test_quantize_maps_off_palette_to_nearest() -> None:
    palette = [(0, 0, 0), (255, 255, 255), (255, 0, 0)]
    img = Image.new("RGBA", (2, 2), (0, 0, 0, 0))
    img.putpixel((0, 0), (10, 10, 10, 255))      # near black
    img.putpixel((1, 0), (250, 0, 5, 255))       # near red
    img.putpixel((0, 1), (200, 200, 200, 255))   # near white
    img.putpixel((1, 1), (0, 0, 0, 0))           # transparent stays

    result = quantize_to_palette(img, palette)

    assert result.getpixel((0, 0)) == (0, 0, 0, 255)
    assert result.getpixel((1, 0)) == (255, 0, 0, 255)
    assert result.getpixel((0, 1)) == (255, 255, 255, 255)
    assert result.getpixel((1, 1)) == (0, 0, 0, 0)


def test_quantize_preserves_exact_matches() -> None:
    palette = [(0, 0, 0), (255, 255, 255)]
    img = Image.new("RGBA", (1, 1), (255, 255, 255, 255))

    result = quantize_to_palette(img, palette)

    assert result.getpixel((0, 0)) == (255, 255, 255, 255)


def test_snap_to_grid_resizes_to_nearest_multiple() -> None:
    img = Image.new("RGBA", (18, 14), (255, 0, 0, 255))

    result = snap_to_grid(img, tile_size=16)

    assert result.size == (16, 16)


def test_snap_to_grid_passthrough_when_already_multiple() -> None:
    img = Image.new("RGBA", (32, 16), (255, 0, 0, 255))

    result = snap_to_grid(img, tile_size=16)

    assert result.size == (32, 16)


def test_resize_to_tile_downscales_square_gemini_output_to_tile_size() -> None:
    """Gemini commonly outputs 1024×1024; tile kind must downscale to exactly 32×32."""
    img = Image.new("RGBA", (1024, 1024), (0, 128, 0, 255))

    result = resize_to_tile(img, tile_size=32)

    assert result.size == (32, 32)


def test_resize_to_tile_center_crops_non_square_before_downscale() -> None:
    """A 1408×736 scene-shaped output must not get non-uniformly stretched."""
    img = Image.new("RGBA", (1408, 736), (0, 128, 0, 255))

    result = resize_to_tile(img, tile_size=32)

    assert result.size == (32, 32)


def test_resize_to_tile_passthrough_when_already_exact() -> None:
    img = Image.new("RGBA", (32, 32), (0, 128, 0, 255))

    result = resize_to_tile(img, tile_size=32)

    assert result.size == (32, 32)
    # Passthrough preserves the original pixels exactly — no interpolation.
    assert result.getpixel((0, 0)) == (0, 128, 0, 255)
