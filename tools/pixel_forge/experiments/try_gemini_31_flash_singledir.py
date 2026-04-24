"""Path A validation: single-direction calls to 3.1 Flash.

Key question: can `gemini-3.1-flash-image-preview` produce strict
cardinal facings (right / up / left / down as defined by LimeZu) when
the prompt asks for ONE direction at a time, isolated from the 4-cell
layout pressure?

The 2026-04-15 v1 batch and v2 prompt-engineering spike both showed
that whole-sheet generation produces a 3/4 isometric default that
ignores cardinal-direction instructions. The hypothesis behind Path A:
when the model isn't trying to fit 4 facings into one image, the
single-direction prompt has enough weight to overpower the iso default.

This script is the smallest possible test of that hypothesis:

    - 4 calls (right, up, left, down)
    - Each call uses a TIGHT 32×64 reference cropped from the matching
      LimeZu premade-01 cell (the canonical example of that facing)
    - Aspect ratio 1:1 (smallest supported, model returns ~1024x1024
      which we crop down)
    - Same subject across all 4 calls
    - Output: 4 raw images + 4 normalized 32x64 crops + analysis
      sidecar comparing L/R bias against LimeZu pattern

Decision rule (printed at end):
    LimeZu pattern: right L/R≈1.19, up≈1.00, left≈0.84, down≈1.00
    PASS if our 4 outputs satisfy:
        right.L/R > 1.10
        left.L/R  < 0.90
        up.L/R    in [0.85, 1.15]
        down.L/R  in [0.85, 1.15]
    Anything else = FAIL (Path A dead, recommend Path B).

Run:
    GEMINI_API_KEY=... .venv/bin/python -m \\
        pixel_forge.experiments.try_gemini_31_flash_singledir
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from google import genai
from google.genai import types as gtypes
from PIL import Image


MODEL_ID = "gemini-3.1-flash-image-preview"
ASPECT_RATIO = "1:1"
PER_CALL_TIMEOUT_MS = 90_000
MAX_ATTEMPTS = 2

# We use the same knight subject from v1/v2 since it had the clearest
# silhouette in the bg-relative analysis — easier to measure direction.
SUBJECT = (
    "a small child in shining silver plate armor with a red tabard, "
    "carrying a tiny sword"
)

REFERENCE_PATH = Path(
    "/Users/sungmancho/projects/sunny-street/public/sprites/premade-01.png"
)
# LimeZu row 0 of premade-01 holds the 4 canonical preview cells.
# Each cell is 32x64. We pick one per direction as the per-call ref.
DIRECTION_REF_BOX: dict[str, tuple[int, int, int, int]] = {
    "right": (0 * 32, 0, 1 * 32, 64),
    "up":    (1 * 32, 0, 2 * 32, 64),
    "left":  (2 * 32, 0, 3 * 32, 64),
    "down":  (3 * 32, 0, 4 * 32, 64),
}

# Per-direction strict perspective definitions. These are deliberately
# verbose and physical (talking about eyes, body axis, what's visible)
# rather than abstract direction labels.
FACING_DEFS: dict[str, str] = {
    "right": (
        "STRICT RIGHT-FACING SIDE PROFILE. The character's body and head "
        "point exactly toward the right edge of the image. We see the "
        "character from the LEFT side. ONE eye is visible (the eye on "
        "the side of the head facing the camera). The body silhouette "
        "is a clean side profile — shoulders are perpendicular to the "
        "camera. NO front view, NO back view, NO three-quarter angle."
    ),
    "up": (
        "STRICT REAR VIEW (character facing AWAY from the camera, walking "
        "AWAY from the viewer). We see the character's BACK ONLY. The "
        "back of the head, the back of the body, the back of the legs. "
        "NO face is visible. NO eyes are visible. The silhouette is "
        "left-right symmetric. NO front view, NO side view, NO "
        "three-quarter angle."
    ),
    "left": (
        "STRICT LEFT-FACING SIDE PROFILE — the exact mirror of right-"
        "facing. The character's body and head point exactly toward the "
        "left edge of the image. We see the character from the RIGHT "
        "side. ONE eye is visible. The body silhouette is a clean side "
        "profile. NO front view, NO back view, NO three-quarter angle."
    ),
    "down": (
        "STRICT FRONT VIEW (character facing TOWARD the camera, walking "
        "TOWARD the viewer). We see the character's FACE clearly with "
        "BOTH eyes visible. The body is square to the camera. The "
        "silhouette is left-right symmetric. NO back view, NO side "
        "view, NO three-quarter angle."
    ),
}


def _build_prompt(direction: str, subject: str) -> str:
    facing = FACING_DEFS[direction]
    return (
        f"Generate ONE pixel-art character portrait. Character: {subject}.\n\n"
        f"FACING: {facing}\n\n"
        f"This image must contain EXACTLY ONE character pose. Not two, "
        f"not a sheet, not a grid, not animation frames — one pose.\n\n"
        f"PERSPECTIVE: top-down 3/4 view, like the attached reference. "
        f"The camera is above and slightly in front of the character, "
        f"tilted ~30 degrees down. NEVER pure side-scroller, NEVER "
        f"isometric 45 degrees, NEVER top-down map view.\n\n"
        f"STYLE: 16-bit-era pixel art. Crisp 1-pixel edges. No anti-"
        f"aliasing. No dithering gradients. Flat shading with two or "
        f"three tonal steps per region. A 1-pixel dark outline on the "
        f"silhouette using a very dark desaturated tone. The background "
        f"is a single solid neutral gray color. No borders, no text, "
        f"no labels."
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


def _per_cell_lr_bias(img: Image.Image, bg_tol: int = 24) -> dict:
    """Background-aware L/R + T/B opaque-pixel measurement.

    Used to decide whether the model's output matches LimeZu's
    canonical facing pattern.
    """
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
        "char_pixels": total,
        "image_pixels": len(px),
        "L": L,
        "R": R,
        "T": T,
        "B": B,
        "L_over_R": L / R if R else float("inf"),
        "T_over_B": T / B if B else float("inf"),
    }


def _verdict(direction: str, bias: dict) -> tuple[bool, str]:
    """Apply the LimeZu pattern check for one direction."""
    lr = bias["L_over_R"]
    if direction == "right":
        ok = lr > 1.10
        why = f"L/R={lr:.2f}, need > 1.10 (LimeZu right=1.19)"
    elif direction == "left":
        ok = lr < 0.90
        why = f"L/R={lr:.2f}, need < 0.90 (LimeZu left=0.84)"
    else:  # up, down
        ok = 0.85 <= lr <= 1.15
        why = f"L/R={lr:.2f}, need 0.85-1.15 (LimeZu {direction}=1.00)"
    return ok, why


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
    error: str | None = None
    raw_bytes: bytes | None = None
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
    bias_full = None
    bias_center = None
    raw_size = None
    if raw_bytes is not None:
        raw_path.write_bytes(raw_bytes)
        img = Image.open(raw_path).convert("RGBA")
        raw_size = img.size
        # Full-image bias (most reliable when the model centered the character)
        bias_full = _per_cell_lr_bias(img)
        # Also measure the center 50% × 50% crop, in case there's
        # peripheral background that washes out the bias signal.
        cw, ch = img.size
        center = img.crop((cw // 4, ch // 4, 3 * cw // 4, 3 * ch // 4))
        bias_center = _per_cell_lr_bias(center)

    return {
        "direction": direction,
        "raw_path": str(raw_path) if raw_bytes else None,
        "raw_size": list(raw_size) if raw_size else None,
        "elapsed_ms": elapsed_ms,
        "attempts": attempts,
        "error": error,
        "bias_full": bias_full,
        "bias_center": bias_center,
    }


def main() -> int:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("error: GEMINI_API_KEY not set", file=sys.stderr)
        return 2
    if not REFERENCE_PATH.is_file():
        print(f"error: reference missing: {REFERENCE_PATH}", file=sys.stderr)
        return 2

    out_root = Path(__file__).parent / "out"
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = out_root / f"{ts}-singledir"
    out_dir.mkdir(parents=True, exist_ok=True)

    client = genai.Client(api_key=api_key)
    overall_started = time.monotonic()

    results: list[dict] = []
    for direction in ("right", "up", "left", "down"):
        print(f"step: {direction}...", flush=True)
        res = _run_one(client, direction, SUBJECT, out_dir / direction)
        if res["raw_path"]:
            full = res["bias_full"]
            ok, why = _verdict(direction, full)
            mark = "PASS" if ok else "FAIL"
            print(f"  -> {res['raw_size']} {res['elapsed_ms']}ms  [{mark}] {why}")
        else:
            print(f"  -> FAIL err={res['error']}")
        results.append(res)
    overall_elapsed_ms = int((time.monotonic() - overall_started) * 1000)

    # Final verdict: ALL 4 directions must pass for Path A to be viable.
    verdicts: dict[str, dict] = {}
    all_ok = True
    for r in results:
        if not r["raw_path"]:
            verdicts[r["direction"]] = {"ok": False, "why": "no output"}
            all_ok = False
            continue
        ok, why = _verdict(r["direction"], r["bias_full"])
        verdicts[r["direction"]] = {"ok": ok, "why": why}
        if not ok:
            all_ok = False

    summary = {
        "script": "try_gemini_31_flash_singledir",
        "model": MODEL_ID,
        "aspect_ratio": ASPECT_RATIO,
        "subject": SUBJECT,
        "n_calls": len(results),
        "overall_elapsed_ms": overall_elapsed_ms,
        "total_cost_usd_estimate": 0.04 * sum(1 for r in results if r["raw_path"]),
        "limezu_target": {
            "right_LR": 1.19,
            "up_LR": 1.00,
            "left_LR": 0.84,
            "down_LR": 1.00,
        },
        "verdicts": verdicts,
        "path_a_pass": all_ok,
        "results": results,
    }
    (out_dir / "singledir_meta.json").write_text(json.dumps(summary, indent=2))

    print("\n=== Path A verdict ===")
    for d, v in verdicts.items():
        print(f"  {d:5s}: {'PASS' if v['ok'] else 'FAIL'}  {v['why']}")
    print(f"\noverall: {'PASS — Path A viable' if all_ok else 'FAIL — recommend Path B (PixelLab)'}")
    print(f"out={out_dir}")
    return 0 if all_ok else 4


if __name__ == "__main__":
    sys.exit(main())
