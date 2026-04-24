"""Batch spike: run gemini-3.1-flash-image-preview on N distinct subjects.

Follow-up to `try_gemini_31_flash.py`. The single-subject spike showed
that 3.1 Flash with aspect_ratio="8:1" can produce a full PERSON_PREMADE
locomotion band in one call. This batch runner exercises the same
pipeline across multiple subjects to check:

    1. Style consistency across diverse characters (young/old, casual/
       fantasy, different silhouettes)
    2. Latency variance per call
    3. Whether the sheet layout (3-row, 4-direction) is reliably honored
       across subjects, or only for the original test prompt

Each subject lands in its own subdir under a single timestamped batch
dir so all outputs from a run are grouped:

    out/<TS>-batch/
    ├── batch_meta.json                 — top-level summary
    ├── 01-young-woman-casual/
    │   ├── gemini31flash_raw.png       — model's raw output
    │   ├── gemini31flash_sheet.png     — LANCZOS-resized to 1792x192
    │   ├── gemini31flash_meta.json
    │   └── _prepared-ref.png
    ├── 02-elderly-wizard/
    │   ...
    └── 03-young-knight/
        ...

Run:
    GEMINI_API_KEY=... .venv/bin/python -m \\
        pixel_forge.experiments.try_gemini_31_flash_batch
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from google import genai
from google.genai import types as gtypes
from PIL import Image


MODEL_ID = "gemini-3.1-flash-image-preview"
ASPECT_RATIO = "8:1"
REFERENCE_PATH = Path(
    "/Users/sungmancho/projects/sunny-street/public/sprites/premade-01.png"
)
REF_CROP_BOX = (0, 0, 1792, 192)
TARGET_W = 1792
TARGET_H = 192

# Diverse subjects to stress-test style consistency:
#   1. A young woman in modern casual — closest to the existing
#      sunny-street character library, baseline expectation
#   2. An elderly wizard in robes — long hem, very different silhouette,
#      tests whether the model honors the 32x64 cell box for non-human
#      proportions
#   3. A child knight in plate armor — small body / large head ratio +
#      reflective armor, stresses the "consistent palette across cells"
#      requirement
SUBJECTS: list[tuple[str, str]] = [
    (
        "01-young-woman-casual",
        "a young woman in a yellow sundress and white sneakers, "
        "shoulder-length brown hair",
    ),
    (
        "02-elderly-wizard",
        "an elderly wizard with a long white beard, dark blue robe with "
        "gold trim, tall pointed hat",
    ),
    (
        "03-child-knight",
        "a small child in shining silver plate armor with a red tabard, "
        "carrying a tiny sword",
    ),
]


def _build_prompt(subject: str) -> str:
    # R1 simplified prompt (2026-04-15). Rationale: the nano-banana
    # 4-direction spike showed that removing pixel-art jargon ("3/4
    # view", "16-bit-era", grid dimensions, cell counts) dramatically
    # improved both L/R facing patterns and pairwise silhouette
    # distinctness. Hypothesis here: the same simplification applied
    # to 3.1 Flash 8:1 single-call will keep the style the user liked
    # from 20260415-110345-batch while fixing the diagonal facings.
    return (
        f"Generate a pixel-art sprite sheet for this character: "
        f"{subject}.\n\n"
        f"Match the layout of the attached reference image. The sheet "
        f"has three rows:\n"
        f"- The top row shows the character looking right, looking up, "
        f"looking left, and looking down (one cell per direction).\n"
        f"- The middle row shows several idle frames for each of those "
        f"four directions, in the same order.\n"
        f"- The bottom row shows several walk-cycle frames for each of "
        f"those four directions, in the same order.\n\n"
        f"The same character must appear in every filled cell — same "
        f"face, same outfit, same colors. Use the same overall look as "
        f"the attached reference image.\n\n"
        f"Style: pixel art. Crisp 1-pixel edges. No anti-aliasing. A "
        f"1-pixel dark outline on the silhouette. Transparent "
        f"background in every cell. No borders, no text, no labels."
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


def _usage_to_dict(response) -> dict | None:
    meta = getattr(response, "usage_metadata", None)
    if meta is None:
        return None
    return {
        "prompt_tokens": int(getattr(meta, "prompt_token_count", 0) or 0),
        "output_tokens": int(getattr(meta, "candidates_token_count", 0) or 0),
        "total_tokens": int(getattr(meta, "total_token_count", 0) or 0),
    }


# Hard per-call deadline. The google-genai SDK has no default timeout,
# so a stuck server-side generation hangs the process forever. The
# 2026-04-15 batch's first wizard call ran 7+ minutes with no response
# before being killed manually. 90s is well over the observed median
# (~20s) but still bounded.
PER_CALL_TIMEOUT_MS = 90_000
MAX_ATTEMPTS_PER_SUBJECT = 2


def _run_one(
    client: genai.Client,
    slug: str,
    subject: str,
    ref_img: Image.Image,
    out_dir: Path,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    ref_img.save(out_dir / "_prepared-ref.png")

    prompt_text = _build_prompt(subject)
    cfg = gtypes.GenerateContentConfig(
        response_modalities=["IMAGE"],
        image_config=gtypes.ImageConfig(aspect_ratio=ASPECT_RATIO),
        # Per-call timeout lives on the request config in google-genai.
        http_options=gtypes.HttpOptions(timeout=PER_CALL_TIMEOUT_MS),
    )

    started = time.monotonic()
    error: str | None = None
    raw_bytes: bytes | None = None
    usage: dict | None = None
    attempts = 0
    while attempts < MAX_ATTEMPTS_PER_SUBJECT and raw_bytes is None:
        attempts += 1
        try:
            response = client.models.generate_content(
                model=MODEL_ID,
                contents=[prompt_text, ref_img],
                config=cfg,
            )
            raw_bytes = _extract_image_bytes(response)
            usage = _usage_to_dict(response)
            error = None
        except Exception as err:  # noqa: BLE001
            error = f"attempt {attempts}: {type(err).__name__}: {err}"
            print(f"  ! {error}", flush=True)
    elapsed_ms = int((time.monotonic() - started) * 1000)

    raw_path = out_dir / "gemini31flash_raw.png"
    sheet_path = out_dir / "gemini31flash_sheet.png"
    raw_size: tuple[int, int] | None = None
    sheet_saved = False
    if raw_bytes is not None:
        raw_path.write_bytes(raw_bytes)
        try:
            img = Image.open(raw_path).convert("RGBA")
            raw_size = img.size
            # LANCZOS resize to PERSON_PREMADE target — alpha preserved.
            sheet = img.resize((TARGET_W, TARGET_H), Image.LANCZOS)
            sheet.save(sheet_path)
            sheet_saved = True
        except Exception as err:  # noqa: BLE001
            error = (error or "") + f" | resize failed: {err}"

    meta = {
        "slug": slug,
        "subject": subject,
        "model": MODEL_ID,
        "aspect_ratio_requested": ASPECT_RATIO,
        "raw_path": str(raw_path) if raw_bytes else None,
        "sheet_path": str(sheet_path) if sheet_saved else None,
        "raw_size": list(raw_size) if raw_size else None,
        "target_sheet_size": [TARGET_W, TARGET_H],
        "elapsed_ms": elapsed_ms,
        "usage": usage,
        "cost_usd_estimate": 0.04 if raw_bytes else 0.0,
        "error": error,
    }
    (out_dir / "gemini31flash_meta.json").write_text(json.dumps(meta, indent=2))
    return meta


def main() -> int:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("error: GEMINI_API_KEY not set", file=sys.stderr)
        return 2
    if not REFERENCE_PATH.is_file():
        print(f"error: reference missing: {REFERENCE_PATH}", file=sys.stderr)
        return 2

    ref_img = Image.open(REFERENCE_PATH).convert("RGBA").crop(REF_CROP_BOX)

    out_root = Path(__file__).parent / "out"
    # Allow `--resume <existing-batch-dir>` so a re-run after a hung call
    # only spends API budget on the missing subjects.
    resume_dir: Path | None = None
    if "--resume" in sys.argv:
        idx = sys.argv.index("--resume")
        resume_dir = Path(sys.argv[idx + 1])
    if resume_dir is not None:
        batch_dir = resume_dir
    else:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        batch_dir = out_root / f"{ts}-batch"
    batch_dir.mkdir(parents=True, exist_ok=True)

    client = genai.Client(api_key=api_key)

    results: list[dict] = []
    overall_started = time.monotonic()
    for slug, subject in SUBJECTS:
        existing_raw = batch_dir / slug / "gemini31flash_raw.png"
        if existing_raw.is_file() and existing_raw.stat().st_size > 0:
            existing_meta = batch_dir / slug / "gemini31flash_meta.json"
            if existing_meta.is_file():
                print(f"step: {slug} — skip (already complete)", flush=True)
                results.append(json.loads(existing_meta.read_text()))
                continue
        print(f"step: {slug} — {subject[:60]}...", flush=True)
        result = _run_one(client, slug, subject, ref_img, batch_dir / slug)
        status = "ok" if result["raw_path"] else "fail"
        size_str = (
            f"{result['raw_size'][0]}x{result['raw_size'][1]}"
            if result.get("raw_size")
            else "?"
        )
        print(
            f"  -> {status} {size_str} {result['elapsed_ms']}ms "
            f"{('err='+result['error']) if result['error'] else ''}",
            flush=True,
        )
        results.append(result)
    overall_elapsed_ms = int((time.monotonic() - overall_started) * 1000)

    n_ok = sum(1 for r in results if r["raw_path"])
    n_fail = len(results) - n_ok
    total_cost = sum(float(r.get("cost_usd_estimate") or 0) for r in results)

    batch_meta = {
        "script": "try_gemini_31_flash_batch",
        "model": MODEL_ID,
        "aspect_ratio": ASPECT_RATIO,
        "n_subjects": len(SUBJECTS),
        "n_ok": n_ok,
        "n_fail": n_fail,
        "overall_elapsed_ms": overall_elapsed_ms,
        "total_cost_usd_estimate": total_cost,
        "results": results,
    }
    (batch_dir / "batch_meta.json").write_text(json.dumps(batch_meta, indent=2))

    print(
        f"\nbatch_31flash: ok={n_ok}/{len(results)} "
        f"{overall_elapsed_ms}ms ~${total_cost:.3f} "
        f"out={batch_dir}"
    )
    return 0 if n_fail == 0 else 3


if __name__ == "__main__":
    sys.exit(main())
