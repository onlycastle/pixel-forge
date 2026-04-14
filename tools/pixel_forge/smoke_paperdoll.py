"""One-off smoke test: verify that moderninteriors Character_Generator
layers alpha-composite into a coherent premade sprite sheet.

Not part of pixel-forge's library or CLI. Runs standalone:

    python -m pixel_forge.smoke_paperdoll

Reads LimeZu assets from the user's private directory (MODERNINTERIORS_GEN_ROOT
env var, defaults to ~/projects/sunny-street-assets/...). Never copies asset
files into this repo. Writes only the composed result and a diff image into
projects/sunny-street/out/smoke/.
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

from PIL import Image, ImageChops

CANVAS = (1792, 1312)
BODY_NATIVE = (1854, 1312)  # includes 62px right-side annotation strip

REPO_ROOT = Path(__file__).resolve().parents[2]

GEN_ROOT = Path(
    os.environ.get(
        "MODERNINTERIORS_GEN_ROOT",
        str(
            Path.home()
            / "projects/sunny-street-assets/moderninteriors-win/2_Characters/Character_Generator"
        ),
    )
)
OUT_DIR = REPO_ROOT / "projects/sunny-street/out/smoke"


def load_rgba(relpath: str) -> Image.Image:
    path = GEN_ROOT / relpath
    if not path.is_file():
        sys.exit(f"missing asset: {path}")
    img = Image.open(path).convert("RGBA")
    print(f"  loaded {relpath}  size={img.size}")
    return img


def alpha_coverage_pct(img: Image.Image) -> float:
    alpha = img.getchannel("A")
    total = alpha.size[0] * alpha.size[1]
    nonzero = sum(1 for px in alpha.getdata() if px > 0)
    return 100.0 * nonzero / total


def bbox_area(bbox: tuple[int, int, int, int] | None) -> int:
    if bbox is None:
        return 0
    x0, y0, x1, y1 = bbox
    return max(0, x1 - x0) * max(0, y1 - y0)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("PAPER-DOLL COMPOSITE SMOKE TEST")
    print("=" * 60)
    print(f"Asset root: {GEN_ROOT}")
    print(f"Output dir: {OUT_DIR}")
    print()
    print("Loading layers...")
    body = load_rgba("Bodies/32x32/Body_32x32_01.png")
    outfit = load_rgba("Outfits/32x32/Outfit_01_32x32_01.png")
    hair = load_rgba("Hairstyles/32x32/Hairstyle_01_32x32_01.png")
    eyes = load_rgba("Eyes/32x32/Eyes_32x32_01.png")

    # Body ships with a 62px annotation strip on the right. Drop it.
    if body.size == BODY_NATIVE:
        print(f"\nCropping body {BODY_NATIVE} -> {CANVAS} (dropping right 62px annotation strip)")
        body = body.crop((0, 0, CANVAS[0], CANVAS[1]))
    elif body.size != CANVAS:
        sys.exit(f"unexpected body size {body.size}; expected {BODY_NATIVE} or {CANVAS}")

    for name, layer in (("outfit", outfit), ("hair", hair), ("eyes", eyes)):
        if layer.size != CANVAS:
            sys.exit(f"{name} size {layer.size} != canvas {CANVAS}")

    print("\nCompositing z-order: body <- outfit <- hair <- eyes")
    composed = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    for layer in (body, outfit, hair, eyes):
        composed = Image.alpha_composite(composed, layer)

    # Save result
    recipe_slug = "body01-outfit01-hair01-eyes01"
    result_path = OUT_DIR / f"paperdoll-v1-{recipe_slug}.png"
    composed.save(result_path)
    result_sha = hashlib.sha1(composed.tobytes()).hexdigest()[:12]
    cov = alpha_coverage_pct(composed)
    print(f"\nResult saved: {result_path.relative_to(REPO_ROOT)}")
    print(f"  sha1            = {result_sha}")
    print(f"  size            = {composed.size}")
    print(f"  alpha coverage  = {cov:.2f}%")

    # Compare against an arbitrary premade reference to understand structure.
    # Bit-exact match is NOT expected — we don't know premade-01's recipe.
    ref_rel = "0_Premade_Characters/32x32/Premade_Character_32x32_01.png"
    print(f"\nStructural diff vs {ref_rel}")
    print("(bit-exact match NOT expected; this is a structural sanity check)")
    with Image.open(GEN_ROOT / ref_rel) as ref_img:
        ref = ref_img.convert("RGBA")
    ref_cov = alpha_coverage_pct(ref)

    diff = ImageChops.difference(composed, ref)
    diff_bbox = diff.getbbox()
    differing_area = bbox_area(diff_bbox)
    total_area = CANVAS[0] * CANVAS[1]

    print(f"  ref alpha coverage    = {ref_cov:.2f}%")
    print(f"  diff bbox             = {diff_bbox}")
    print(f"  diff bbox area / full = {differing_area}/{total_area} ({100*differing_area/total_area:.1f}%)")

    if diff_bbox is None:
        print("  VERDICT: BIT-EXACT MATCH (unexpected but great)")
    else:
        diff_path = OUT_DIR / f"paperdoll-v1-{recipe_slug}-diff-vs-premade01.png"
        diff.save(diff_path)
        print(f"  diff image saved: {diff_path.relative_to(REPO_ROOT)}")

    print()
    print("Open the result PNG and eyeball it. Success criteria:")
    print("  1. File opens without error at 1792x1312 RGBA")
    print("  2. Character reads as a dressed person with hair (not a naked body)")
    print("  3. Layers align: hair sits on head, outfit covers torso")
    print("  4. No obvious layer-order glitches (hair under scalp, outfit behind arms)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
