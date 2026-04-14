"""One-off smoke test: can Gemini 2.5 Flash Image produce a 24x4
animal sprite sheet matching LimeZu's livestock24 layout, with a
brand-new species (fox)?

Not part of pixel-forge's library or CLI. Runs standalone:

    python -m pixel_forge.smoke_animal_sheet

Reads the duck-brown reference from sunny-street's public/sprites/animals
directory (purchased LimeZu pack, drop-in copy). Writes raw Gemini
output PNGs to projects/sunny-street/out/smoke/animal-fox-v{1,2}.png
with NO post-processing — the smoke test is about the model's raw
capability to honor a grid contract.

Cost: ~$0.05 per call. Default 2 variants.
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "projects/sunny-street/out/smoke"

REFERENCE_PATH = Path(
    os.environ.get(
        "ANIMAL_REFERENCE_PNG",
        str(Path.home() / "projects/sunny-street/public/sprites/animals/duck-brown.png"),
    )
)

VARIANTS = int(os.environ.get("SMOKE_VARIANTS", "2"))
EXPECTED_CANVAS = (768, 128)

PROMPT = """Generate a pixel-art animal sprite sheet that matches the grid
layout of the attached reference image. The reference is used only for
its grid structure. Design a brand new animal (a red fox, described
below) and paint it into the cells.

The attached reference is 768 x 128 pixels: a regular grid of 24 columns
by 4 rows of 32 x 32 cells. There are no borders, no gutters, no text,
no labels, no annotations of any kind in the desired output. Background
is fully transparent.

The first row contains stationary poses, one per facing direction in
the leftmost four cells:
  column 0 -> the fox facing right, standing still, neutral pose
  column 1 -> the fox facing up (viewer sees the fox from behind)
  column 2 -> the fox facing left, standing still, neutral pose
  column 3 -> the fox facing down (viewer sees the fox from the front)
Columns 4 through 23 in the first row must be fully transparent — do
not draw anything in those cells.

The second row contains a six-frame walk cycle for each of the four
facing directions, grouped left to right:
  columns 0..5   -> facing right, six-frame walk cycle, legs alternating
  columns 6..11  -> facing up,    six-frame walk cycle, back view
  columns 12..17 -> facing left,  six-frame walk cycle, mirror of right
  columns 18..23 -> facing down,  six-frame walk cycle, front view
The six frames per direction must read as a smooth cyclic animation,
not six static poses. Legs visibly alternate, body bobs one pixel
vertically, tail sways slightly.

The third and fourth rows must be fully transparent. Every pixel in
those two rows has alpha equal to zero. Do not draw anything in them.

The animal is a small red fox (Vulpes vulpes), rendered top-down 3/4
view to match the reference perspective. Defining features: reddish
orange fur on the back, head, and upper sides; white fur on the
underbelly, throat, and chin; a long bushy tail with a white tip;
darker (black) lower legs like socks; triangular pointed ears with
black tips, alert and upright; a sharp pointed snout; slim build,
slightly larger than a chicken, smaller than a dog. The exact same fox
must appear in every filled cell — same fur color zones, same ear
shape, same tail length, same body proportions. Do not introduce
different foxes or color variants.

Style: 16-bit-era top-down 3/4 view pixel art. Crisp 1-pixel edges. No
anti-aliasing. No dithering gradients. Flat shading with two or three
tonal steps per fur region. A 1-pixel dark outline on the fox
silhouette using a very dark desaturated brown (not pure black). The
fox occupies most of each 32 x 32 cell, centered horizontally, with
feet near the bottom edge of the cell. Every filled cell has a fully
transparent background.

Output dimensions: exactly 768 x 128 pixels. Not larger, not smaller.
PNG with alpha channel. The output image must contain no written
characters of any language, no numerals, no row labels, no column
labels, no debug annotations, no watermarks, no signatures, no borders.
Do not reuse the duck pixels from the reference image — borrow only
the grid geometry.
"""

# Region of the reference image that contains LimeZu's debug annotation
# label ("ROW: 4 COL: 24" stamped in the top-left). Painted over with
# black before the reference is sent to Gemini so the model has nothing
# to copy. Coordinates are conservative — the label fits within ~80x16
# but we mask a wider band to be safe.
LABEL_MASK_BOX = (0, 0, 120, 24)


def _configure_gemini():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        sys.exit("GEMINI_API_KEY is not set; cannot run smoke test")
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    return genai


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if not REFERENCE_PATH.is_file():
        sys.exit(f"reference image missing: {REFERENCE_PATH}")

    print("=" * 60)
    print("ANIMAL SHEET SMOKE TEST")
    print("=" * 60)
    print(f"Reference : {REFERENCE_PATH}")
    print(f"Variants  : {VARIANTS}")
    print(f"Output    : {OUT_DIR}")
    print()

    with Image.open(REFERENCE_PATH) as ref_img:
        ref_img.load()
        ref_copy = ref_img.copy()
    print(f"Reference loaded: size={ref_copy.size}")
    if ref_copy.size != EXPECTED_CANVAS:
        print(
            f"WARNING: reference size {ref_copy.size} != expected {EXPECTED_CANVAS}; "
            f"prompt assumes 768x128 - results may be off"
        )

    # Paint over the LimeZu debug label so the model has nothing to copy.
    # We use opaque black to match the rest of the reference's background.
    from PIL import ImageDraw
    if ref_copy.mode != "RGBA":
        ref_copy = ref_copy.convert("RGBA")
    draw = ImageDraw.Draw(ref_copy)
    draw.rectangle(LABEL_MASK_BOX, fill=(0, 0, 0, 255))
    masked_path = OUT_DIR / "_reference-masked.png"
    ref_copy.save(masked_path)
    print(f"Reference masked label box {LABEL_MASK_BOX} -> {masked_path.relative_to(REPO_ROOT)}")

    genai = _configure_gemini()
    model = genai.GenerativeModel("gemini-2.5-flash-image")
    print(f"Model     : gemini-2.5-flash-image")
    print()

    for i in range(1, VARIANTS + 1):
        print(f"--- variant {i}/{VARIANTS} ---")
        try:
            response = model.generate_content([PROMPT, ref_copy])
        except Exception as err:  # noqa: BLE001
            print(f"  ERROR: {type(err).__name__}: {err}")
            continue

        png_bytes = _extract_png_bytes(response)
        if png_bytes is None:
            print(f"  ERROR: no image in response")
            continue

        out_path = OUT_DIR / f"animal-fox-v{i}.png"
        out_path.write_bytes(png_bytes)

        with Image.open(out_path) as v:
            sha = hashlib.sha1(v.tobytes()).hexdigest()[:12]
            print(f"  saved: {out_path.relative_to(REPO_ROOT)}")
            print(f"  size : {v.size}  mode={v.mode}  sha1={sha}")
            if v.size != EXPECTED_CANVAS:
                print(
                    f"  WARN : output {v.size} != target {EXPECTED_CANVAS}"
                )

    print()
    print("Open each output PNG and judge against:")
    print("  PASS:")
    print("    - canvas is exactly 768x128 (or close)")
    print("    - row 0 has 4 idle frames, rows 2-3 are empty")
    print("    - row 1 has 24 walk frames in 4 direction groups")
    print("    - same fox appears across all cells (identity holds)")
    print("    - walk frames show clear leg alternation")
    print("  SOFT FAIL: structure right but identity drifts or layout shifts")
    print("  HARD FAIL: model ignores the grid and renders 1-2 large foxes")
    return 0


def _extract_png_bytes(response) -> bytes | None:
    for candidate in getattr(response, "candidates", []) or []:
        content = getattr(candidate, "content", None)
        if content is None:
            continue
        for part in getattr(content, "parts", []) or []:
            inline = getattr(part, "inline_data", None)
            if inline is None:
                continue
            mime = getattr(inline, "mime_type", "")
            if mime.startswith("image/"):
                return inline.data
    return None


if __name__ == "__main__":
    raise SystemExit(main())
