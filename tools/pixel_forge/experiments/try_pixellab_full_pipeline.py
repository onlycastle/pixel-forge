"""End-to-end PixelLab character pipeline spike.

Follow-up to the 2026-04-15 multi-view API spike. The first PixelLab
spike tested a SINGLE `generate_image_pixflux` call; this one exercises
the **full chain** required to build a sunny-street-conformant sprite
sheet automatically:

    1. generate_image_pixflux(direction="east")
       → base character in the east-facing pose (identity anchor)

    2. rotate(from_direction="east", to_direction=<other cardinal>) x3
       → north, west, south rotations with identity preserved from (1)

    3. animate_with_text(direction=<cardinal>, action="walk") x4
       → 6-frame walk cycles, one per cardinal direction, each seeded
         with the corresponding rotation as the reference image

    4. Write everything into a PixelLab-style asset-pack layout on disk
       so `pixellab_to_sheet.py` can compose it into a PERSON_PREMADE
       sheet via the shared post-processing.

This script answers the open questions from the findings doc:

    - Does the programmatic chain produce comparable quality to
      PixelLab's UI-driven export?
    - Is identity preserved across all 4 rotations?
    - What is the actual end-to-end cost and latency?
    - Do animate_with_text walk frames line up with rotation poses?

Run:
    PIXELLAB_API_KEY=... .venv/bin/python -m pixel_forge.experiments.try_pixellab_full_pipeline

Output (a full PixelLab-style asset pack):
    tools/pixel_forge/experiments/out/<YYYYMMDD-HHMMSS>/pack/
    ├── metadata.json
    ├── rotations/{east,north,west,south}.png
    └── animations/walk/{east,north,west,south}/frame_NNN.png

    ...plus a top-level `pipeline_meta.json` with the empirical
    cost + timing + balance delta.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pixellab
from PIL import Image


SUBJECT_PROMPT = (
    "1974 california farmhand, weathered denim overalls, sun-bleached "
    "blue shirt, brown leather boots, wide-brim straw hat, tan skin, "
    "short brown hair"
)
# Native PixelLab size. Must be one of the square sizes the `rotate`
# endpoint accepts: 16/32/64/128. 64x64 gives plenty of detail while
# still producing small/fast API calls; the converter
# (`pixellab_to_sheet.py`) remaps into 32x64 cells afterward. (The
# user's hand-crafted pack was 48x48 via a UI-only template path that
# bypasses the public rotate endpoint; we can't replicate that 48x48
# workflow from the SDK.)
NATIVE_W = 64
NATIVE_H = 64
WALK_FRAMES_PER_DIR = 6

# Four cardinal directions we need for sunny-street (east, north, west,
# south map to right, up, left, down via pixellab_to_sheet.py).
CARDINALS: tuple[str, ...] = ("east", "north", "west", "south")
# Animation id — the converter already supports any ID via metadata, so
# we pick a stable human-readable name here.
WALK_ANIM_ID = "walk"


def _save_pil(img: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


def _usage_sum(events: list[dict]) -> float:
    """Sum the `.usd` field from each per-call usage record."""
    return sum(float(e.get("usd", 0) or 0) for e in events)


def main() -> int:
    api_key = os.environ.get("PIXELLAB_API_KEY")
    if not api_key:
        print("error: PIXELLAB_API_KEY not set", file=sys.stderr)
        return 2

    client = pixellab.Client(secret=api_key)

    # Record the starting balance — this is the empirical cost source
    # of truth. The per-call `usage.usd` is useful for attribution but
    # the balance delta is the authoritative total.
    balance_before = float(client.get_balance().usd or 0.0)

    out_root = Path(__file__).parent / "out"
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = out_root / ts
    pack_dir = out_dir / "pack"
    rotations_dir = pack_dir / "rotations"
    animations_dir = pack_dir / "animations" / WALK_ANIM_ID
    pack_dir.mkdir(parents=True, exist_ok=True)
    rotations_dir.mkdir(parents=True, exist_ok=True)
    animations_dir.mkdir(parents=True, exist_ok=True)

    timeline: list[dict] = []
    usage_events: list[dict] = []

    def _log(step: str, start: float, extra: dict | None = None) -> None:
        entry = {"step": step, "elapsed_ms": int((time.monotonic() - start) * 1000)}
        if extra:
            entry.update(extra)
        timeline.append(entry)

    overall_start = time.monotonic()

    # ---- Step 1: generate the east-facing base character -------------
    print("step 1/9: generate east-facing base character...", flush=True)
    step_start = time.monotonic()
    base_resp = client.generate_image_pixflux(
        description=SUBJECT_PROMPT,
        image_size={"width": NATIVE_W, "height": NATIVE_H},
        # metadata.json from the user's hand-crafted pack shows
        # view="low top-down" works well for LimeZu-matching output
        # even though the UI label may differ.
        view="low top-down",
        direction="east",
        outline="single color black outline",
        shading="basic shading",
        detail="medium detail",
        no_background=True,
    )
    east_img: Image.Image = base_resp.image.pil_image().convert("RGBA")
    _save_pil(east_img, rotations_dir / "east.png")
    usage_events.append(
        {"step": "generate_east", "usd": float(getattr(base_resp.usage, "usd", 0) or 0)}
    )
    _log("generate_east", step_start, {"size": list(east_img.size)})

    # ---- Step 2-4: rotate east → north, west, south ------------------
    #
    # Each rotate call takes the previously generated image as
    # `from_image` and returns the same character facing a new
    # cardinal. We chain off the east base rather than chaining
    # sequentially (east→north→west→south) because chaining would
    # accumulate identity drift across 3 hops.
    rotations_by_dir: dict[str, Image.Image] = {"east": east_img}
    for target in ("north", "west", "south"):
        print(f"step: rotate east → {target}...", flush=True)
        step_start = time.monotonic()
        resp = client.rotate(
            image_size={"width": NATIVE_W, "height": NATIVE_H},
            from_image=east_img,
            # `rotate` requires both view AND direction info — passing
            # direction alone returns "view_change or from_view and
            # to_view must be provided". We keep the view constant
            # ("low top-down" matches the generation call) so only the
            # facing direction changes.
            from_view="low top-down",
            to_view="low top-down",
            from_direction="east",
            to_direction=target,
        )
        img = resp.image.pil_image().convert("RGBA")
        rotations_by_dir[target] = img
        _save_pil(img, rotations_dir / f"{target}.png")
        usage_events.append(
            {"step": f"rotate_{target}", "usd": float(getattr(resp.usage, "usd", 0) or 0)}
        )
        _log(f"rotate_{target}", step_start, {"size": list(img.size)})

    # ---- Step 5-8: animate walk cycle per direction ------------------
    #
    # animate_with_text takes the direction's rotation as the
    # reference_image, so each walk cycle is identity-anchored to the
    # matching idle pose. This is the per-direction equivalent of our
    # existing refine_sheet_walk pipeline but running inside PixelLab
    # instead of Gemini.
    walks_by_dir: dict[str, list[Image.Image]] = {}
    for direction in CARDINALS:
        print(f"step: animate walk for {direction}...", flush=True)
        step_start = time.monotonic()
        resp = client.animate_with_text(
            image_size={"width": NATIVE_W, "height": NATIVE_H},
            description=SUBJECT_PROMPT,
            # PixelLab's server validates `negative_description` as a
            # string — passing None (SDK default) triggers 422. Use
            # an empty string to satisfy the validator without
            # actually negating anything.
            negative_description="",
            action="walk",
            reference_image=rotations_by_dir[direction],
            view="low top-down",
            direction=direction,
            n_frames=WALK_FRAMES_PER_DIR,
        )
        frames = [img.pil_image().convert("RGBA") for img in resp.images]
        walks_by_dir[direction] = frames
        frame_dir = animations_dir / direction
        frame_dir.mkdir(parents=True, exist_ok=True)
        for i, frame in enumerate(frames):
            _save_pil(frame, frame_dir / f"frame_{i:03d}.png")
        usage_events.append(
            {
                "step": f"animate_walk_{direction}",
                "usd": float(getattr(resp.usage, "usd", 0) or 0),
                "n_frames": len(frames),
            }
        )
        _log(f"animate_walk_{direction}", step_start, {"n_frames": len(frames)})

    overall_elapsed_ms = int((time.monotonic() - overall_start) * 1000)

    # ---- Write PixelLab-style metadata.json --------------------------
    #
    # Mirror the shape we observed in the user's hand-crafted pack so
    # the existing `pixellab_to_sheet.py` converter can consume this
    # output without modification.
    pack_metadata = {
        "character": {
            "id": f"spike-{ts}",
            "name": SUBJECT_PROMPT[:80],
            "prompt": SUBJECT_PROMPT,
            "size": {"width": NATIVE_W, "height": NATIVE_H},
            "template_id": "programmatic",
            "directions": 4,
            "view": "low top-down",
            "created_at": datetime.now(tz=timezone.utc).isoformat(),
        },
        "frames": {
            "rotations": {
                d: f"rotations/{d}.png" for d in CARDINALS
            },
            "animations": {
                WALK_ANIM_ID: {
                    d: [
                        f"animations/{WALK_ANIM_ID}/{d}/frame_{i:03d}.png"
                        for i in range(WALK_FRAMES_PER_DIR)
                    ]
                    for d in CARDINALS
                }
            },
        },
        "export_version": "2.0",
        "export_date": datetime.now(tz=timezone.utc).isoformat(),
    }
    (pack_dir / "metadata.json").write_text(json.dumps(pack_metadata, indent=2))

    # ---- Final balance + cost summary --------------------------------
    balance_after = float(client.get_balance().usd or 0.0)
    cost_empirical = max(0.0, balance_before - balance_after)
    cost_from_events = _usage_sum(usage_events)

    pipeline_meta = {
        "subject": SUBJECT_PROMPT,
        "native_size": {"width": NATIVE_W, "height": NATIVE_H},
        "pack_dir": str(pack_dir),
        "overall_elapsed_ms": overall_elapsed_ms,
        "balance_before_usd": balance_before,
        "balance_after_usd": balance_after,
        "cost_usd_empirical": cost_empirical,
        "cost_usd_from_events": cost_from_events,
        "n_api_calls": len(usage_events),
        "usage_events": usage_events,
        "timeline": timeline,
    }
    (out_dir / "pipeline_meta.json").write_text(json.dumps(pipeline_meta, indent=2))

    print(
        f"pixellab_full: ok calls={len(usage_events)} "
        f"{overall_elapsed_ms}ms "
        f"empirical=${cost_empirical:.4f} "
        f"events=${cost_from_events:.4f} "
        f"pack={pack_dir}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
