"""nano-banana-pro-preview Path A: full 4-direction validation.

Follow-up to the 2026-04-15 single-direction spike
(`try_nano_banana_singledir.py`) which showed nano-banana is the first
Gemini-family image model to break the symmetric front-view bias
(L/R=1.11 on the right-facing test vs ~1.00 for 3.1 Flash and 3 Pro).

Success criterion is DISTINCTNESS, not strict cardinal:
    - The 4 outputs (right, up, left, down) must be visually
      distinguishable from each other.
    - "LimeZu 3/4 top-down" has L/R only at 1.19 for right so absolute
      thresholds over-reject; instead we measure pairwise silhouette
      XOR + L/R + T/B and require all 6 pairs to differ meaningfully.

For each direction we use a tight per-cell reference from LimeZu
premade-01 row 0 (the canonical 4 facings) and a direction-specific
prompt that defines the facing in physical terms (what's visible,
where eyes are, where the body axis points).

Run:
    GEMINI_API_KEY=... .venv/bin/python -m \\
        pixel_forge.experiments.try_nano_banana_4dir
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from datetime import datetime
from itertools import combinations
from pathlib import Path

from google import genai
from google.genai import types as gtypes
from PIL import Image


MODEL_ID = "nano-banana-pro-preview"
ASPECT_RATIO = "1:1"
PER_CALL_TIMEOUT_MS = 120_000
MAX_ATTEMPTS = 2

SUBJECT = (
    "a small child in shining silver plate armor with a red tabard, "
    "carrying a tiny sword"
)
REFERENCE_PATH = Path(
    "/Users/sungmancho/projects/sunny-street/public/sprites/premade-01.png"
)
# LimeZu premade-01 row 0 = the 4 canonical facings.
DIRECTION_REF_BOX: dict[str, tuple[int, int, int, int]] = {
    "right": (0 * 32, 0, 1 * 32, 64),
    "up":    (1 * 32, 0, 2 * 32, 64),
    "left":  (2 * 32, 0, 3 * 32, 64),
    "down":  (3 * 32, 0, 4 * 32, 64),
}
# Simple physical statements of "which way the character is looking".
# Earlier drafts added elaborate explanations ("clockwise angled", "one
# eye on left side of face", etc.) that confused more than they clarified
# and risked leaking spurious constraints into the model's output.
FACING_DEFS: dict[str, str] = {
    "right": "The character is looking to the right.",
    "up":    "The character is looking upward (away from the viewer).",
    "left":  "The character is looking to the left.",
    "down":  "The character is looking downward (toward the viewer).",
}


def _build_prompt(direction: str, subject: str) -> str:
    return (
        f"Generate ONE pixel-art character. Character: {subject}.\n\n"
        f"{FACING_DEFS[direction]}\n\n"
        f"Use the same camera angle and overall look as the attached "
        f"reference image.\n\n"
        f"This image must contain EXACTLY ONE character pose. Not two, "
        f"not a sheet, not a grid, not animation frames — one pose.\n\n"
        f"STYLE: pixel art. Crisp 1-pixel edges. No anti-aliasing. Flat "
        f"shading with a small number of tonal steps per region. A "
        f"1-pixel dark outline on the silhouette. Solid neutral gray "
        f"background. No borders, no text, no labels, no grid, no "
        f"multiple poses."
    )


def _extract_image_bytes(response) -> bytes | None:
    for cand in getattr(response, "candidates", []) or []:
        content = getattr(cand, "content", None)
        if content is None:
            continue
        for part in getattr(content, "parts", []) or []:
            inline = getattr(part, "inline_data", None)
            if inline is None:
                continue
            mime = getattr(inline, "mime_type", "") or ""
            if mime.startswith("image/"):
                return inline.data
    return None


def _silhouette_mask(img: Image.Image, size: tuple[int, int] = (64, 64)) -> list[bool]:
    """Return a flat list of bool per pixel (True = character) for a
    uniformly-resized, bg-subtracted version of the image. Used to
    compute pairwise XOR differences between directions."""
    small = img.convert("RGBA").resize(size, Image.LANCZOS)
    px = list(small.getdata())
    quant = Counter((p[0] >> 3, p[1] >> 3, p[2] >> 3) for p in px)
    bg5 = quant.most_common(1)[0][0]
    bg = (bg5[0] << 3, bg5[1] << 3, bg5[2] << 3)
    return [
        (abs(p[0] - bg[0]) + abs(p[1] - bg[1]) + abs(p[2] - bg[2])) > 24
        for p in px
    ]


def _xor_distance(a: list[bool], b: list[bool]) -> float:
    """Jaccard-style distance between two silhouette masks — 1.0 means
    totally different, 0.0 means identical."""
    diff = sum(1 for x, y in zip(a, b) if x != y)
    union = sum(1 for x, y in zip(a, b) if x or y)
    return diff / union if union else 0.0


def _bias(img: Image.Image, bg_tol: int = 24) -> dict:
    img = img.convert("RGBA")
    w, h = img.size
    px = list(img.getdata())
    quant = Counter((p[0] >> 3, p[1] >> 3, p[2] >> 3) for p in px)
    bg5 = quant.most_common(1)[0][0]
    bg = (bg5[0] << 3, bg5[1] << 3, bg5[2] << 3)

    def is_char(p):
        return abs(p[0] - bg[0]) + abs(p[1] - bg[1]) + abs(p[2] - bg[2]) > bg_tol

    L = sum(1 for y in range(h) for x in range(w // 2) if is_char(px[y * w + x]))
    R = sum(1 for y in range(h) for x in range(w // 2, w) if is_char(px[y * w + x]))
    T = sum(1 for y in range(h // 2) for x in range(w) if is_char(px[y * w + x]))
    B = sum(1 for y in range(h // 2, h) for x in range(w) if is_char(px[y * w + x]))
    total = sum(1 for p in px if is_char(p))
    return {
        "char_px": total,
        "L_over_R": L / R if R else float("inf"),
        "T_over_B": T / B if B else float("inf"),
    }


def _run_one(
    client: genai.Client,
    direction: str,
    subject: str,
    out_dir: Path,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    ref = Image.open(REFERENCE_PATH).convert("RGBA").crop(DIRECTION_REF_BOX[direction])
    ref.save(out_dir / "_ref.png")

    prompt_text = _build_prompt(direction, subject)
    cfg = gtypes.GenerateContentConfig(
        response_modalities=["IMAGE"],
        image_config=gtypes.ImageConfig(aspect_ratio=ASPECT_RATIO),
        http_options=gtypes.HttpOptions(timeout=PER_CALL_TIMEOUT_MS),
    )

    started = time.monotonic()
    raw_bytes: bytes | None = None
    error: str | None = None
    attempts = 0
    while attempts < MAX_ATTEMPTS and raw_bytes is None:
        attempts += 1
        try:
            response = client.models.generate_content(
                model=MODEL_ID,
                contents=[prompt_text, ref],
                config=cfg,
            )
            raw_bytes = _extract_image_bytes(response)
            error = None
        except Exception as err:  # noqa: BLE001
            error = f"attempt {attempts}: {type(err).__name__}: {err}"
            print(f"  ! {error}", flush=True)
    elapsed_ms = int((time.monotonic() - started) * 1000)

    raw_path = out_dir / "raw.png"
    bias = None
    mask = None
    raw_size = None
    if raw_bytes is not None:
        raw_path.write_bytes(raw_bytes)
        img = Image.open(raw_path).convert("RGBA")
        raw_size = img.size
        bias = _bias(img)
        mask = _silhouette_mask(img)

    return {
        "direction": direction,
        "raw_path": str(raw_path) if raw_bytes else None,
        "raw_size": list(raw_size) if raw_size else None,
        "elapsed_ms": elapsed_ms,
        "attempts": attempts,
        "error": error,
        "bias": bias,
        "_mask": mask,  # stripped before serialization
    }


def main() -> int:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("error: GEMINI_API_KEY not set", file=sys.stderr)
        return 2

    out_root = Path(__file__).parent / "out"
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = out_root / f"{ts}-nanobanana-4dir"
    out_dir.mkdir(parents=True, exist_ok=True)

    client = genai.Client(api_key=api_key)
    overall_started = time.monotonic()

    results: list[dict] = []
    for direction in ("right", "up", "left", "down"):
        print(f"step: {direction}...", flush=True)
        res = _run_one(client, direction, SUBJECT, out_dir / direction)
        if res["raw_path"]:
            b = res["bias"]
            print(
                f"  -> {res['raw_size']} {res['elapsed_ms']}ms  "
                f"L/R={b['L_over_R']:.2f}  T/B={b['T_over_B']:.2f}"
            )
        else:
            print(f"  -> FAIL err={res['error']}")
        results.append(res)
    overall_elapsed_ms = int((time.monotonic() - overall_started) * 1000)

    # Pairwise distinctness via silhouette XOR. Threshold 0.30 = ~30%
    # of pixels differ — empirically "visually distinguishable".
    # (Two identical renders produce 0, two unrelated characters ~0.6+.)
    pairwise: dict[str, float] = {}
    min_distance = 1.0
    for a, b in combinations(results, 2):
        if not a.get("_mask") or not b.get("_mask"):
            continue
        d = _xor_distance(a["_mask"], b["_mask"])
        pairwise[f"{a['direction']}_vs_{b['direction']}"] = round(d, 3)
        if d < min_distance:
            min_distance = d

    # Distinct = all pairs differ by >= 0.30.
    DISTINCT_THRESHOLD = 0.30
    all_distinct = all(d >= DISTINCT_THRESHOLD for d in pairwise.values())

    # Strip masks before serialization
    for r in results:
        r.pop("_mask", None)

    summary = {
        "script": "try_nano_banana_4dir",
        "model": MODEL_ID,
        "subject": SUBJECT,
        "aspect_ratio": ASPECT_RATIO,
        "overall_elapsed_ms": overall_elapsed_ms,
        "results": results,
        "pairwise_silhouette_distance": pairwise,
        "min_pairwise_distance": round(min_distance, 3),
        "distinct_threshold": DISTINCT_THRESHOLD,
        "all_pairs_distinct": all_distinct,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    print("\n=== pairwise silhouette distance (0=identical, 1=totally different) ===")
    for k, v in pairwise.items():
        mark = "ok " if v >= DISTINCT_THRESHOLD else "NEAR"
        print(f"  [{mark}] {k:25s} {v:.3f}")
    print(f"\nmin distance: {min_distance:.3f}  (threshold {DISTINCT_THRESHOLD})")
    print(
        f"verdict: {'PASS — all 4 facings visually distinct' if all_distinct else 'FAIL — some facings too similar'}"
    )
    print(f"out={out_dir}")
    return 0 if all_distinct else 4


if __name__ == "__main__":
    sys.exit(main())
