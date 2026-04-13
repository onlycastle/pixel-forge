from PIL import Image

from pixel_forge.postprocess import ensure_alpha


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
