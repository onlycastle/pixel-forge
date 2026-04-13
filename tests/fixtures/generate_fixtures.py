"""Generate deterministic test fixtures for pixel_forge tests.

Run this once from the repo root: `python tests/fixtures/generate_fixtures.py`
The outputs are committed to the repo.

WARNING — DO NOT re-run this script casually. Downstream tests (see Task 8
in the v1 plan) byte-compare the committed PNGs via `read_bytes() ==`. Pillow
version differences can rewrite PNG byte streams (compression level, IDAT
chunking, metadata) even when pixel content is identical. If you DO re-run
this on a different Pillow version, you MUST also update every byte-compare
assertion in the test suite. The fixtures were originally generated on
Pillow 12.2.0.
"""
from pathlib import Path

from PIL import Image

FIXTURE_DIR = Path(__file__).parent

PALETTE_4 = [
    (0, 0, 0, 255),        # black   #000000
    (255, 255, 255, 255),  # white   #ffffff
    (255, 0, 0, 255),      # red     #ff0000
    (0, 0, 0, 0),          # transparent
]


def write_palette_file() -> None:
    lines = ["#000000", "#ffffff", "#ff0000"]
    (FIXTURE_DIR / "palette-4.hex").write_text("\n".join(lines) + "\n")


def write_good_tile() -> None:
    """16x16 tile using only palette colors."""
    img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    for y in range(16):
        for x in range(16):
            if (x + y) % 2 == 0:
                img.putpixel((x, y), (255, 0, 0, 255))
            else:
                img.putpixel((x, y), (255, 255, 255, 255))
    img.save(FIXTURE_DIR / "good-tile.png")


def write_bad_tile() -> None:
    """16x16 tile with one off-palette pixel (pure blue)."""
    img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    for y in range(16):
        for x in range(16):
            img.putpixel((x, y), (255, 255, 255, 255))
    img.putpixel((8, 8), (0, 0, 255, 255))  # off-palette
    img.save(FIXTURE_DIR / "bad-tile.png")


if __name__ == "__main__":
    write_palette_file()
    write_good_tile()
    write_bad_tile()
    print(f"Wrote fixtures to {FIXTURE_DIR}")
