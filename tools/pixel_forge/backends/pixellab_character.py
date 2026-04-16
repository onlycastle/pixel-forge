"""PixelLab character backend wrapping the full generate/rotate/animate pipeline.

Implements the CharacterBackend protocol using the PixelLab SDK:

    - generate_portrait:       single pixflux call, south-facing, 64x64
    - generate_walking_sheet:  east base -> 3 rotations -> 4 walk animations
                               -> pack dir -> convert_pack() to PERSON_PREMADE sheet
    - generate_action_sheets:  no-op (PixelLab has no action endpoint)

Constructor accepts ``client: pixellab.Client | None`` for dependency
injection (testing). When None, instantiates a real client from
``PIXELLAB_API_KEY`` in the environment.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from pixel_forge.backends.character import (
    ActionSheetsRequest,
    ActionSheetsResult,
    PortraitRequest,
    PortraitResult,
    WalkingSheetRequest,
    WalkingSheetResult,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NATIVE_SIZE = 64
CARDINALS = ("east", "north", "west", "south")
WALK_ANIM_ID = "walk"
WALK_FRAMES_PER_DIR = 6

# PERSON_PREMADE sheet layout (must stay in sync with sheet.py / converter)
CELL_W = 32
CELL_H = 64
TARGET_COLS = 56
TARGET_ROWS = 3
PREVIEW_ROW = 0
IDLE_ROW = 1
WALK_ROW = 2
FRAMES_PER_DIR = 6
DIRECTION_ORDER = ["right", "up", "left", "down"]

# Common pixflux generation kwargs shared between portrait and base character
_PIXFLUX_COMMON = dict(
    image_size={"width": NATIVE_SIZE, "height": NATIVE_SIZE},
    view="low top-down",
    outline="single color black outline",
    shading="basic shading",
    detail="medium detail",
    no_background=True,
)


class PixelLabCharacterBackend:
    """Character backend backed by the PixelLab SDK."""

    def __init__(
        self,
        output_dir: Path,
        client=None,
    ) -> None:
        self.output_dir = output_dir
        if client is not None:
            self._client = client
        else:
            import pixellab

            api_key = os.environ.get("PIXELLAB_API_KEY", "")
            self._client = pixellab.Client(secret=api_key)

    # ------------------------------------------------------------------
    # CharacterBackend protocol: portrait
    # ------------------------------------------------------------------

    def generate_portrait(self, req: PortraitRequest) -> PortraitResult:
        """Generate a single south-facing portrait via pixflux."""
        kwargs = dict(
            description=req.prompt,
            direction="south",
            **_PIXFLUX_COMMON,
        )
        # Optionally pass a reference/style image
        if req.reference and req.reference.is_file():
            ref_img = Image.open(req.reference).convert("RGBA")
            kwargs["style_image"] = ref_img

        resp = self._client.generate_image_pixflux(**kwargs)
        pil_img: Image.Image = resp.image.pil_image().convert("RGBA")

        out = req.output_dir / "portrait.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        pil_img.save(out, "PNG")

        return PortraitResult(path=out)

    # ------------------------------------------------------------------
    # CharacterBackend protocol: walking sheet
    # ------------------------------------------------------------------

    def generate_walking_sheet(self, req: WalkingSheetRequest) -> WalkingSheetResult:
        """Run the full pipeline: generate -> rotate -> animate -> pack -> sheet."""
        pack_dir = req.output_dir / "pixellab_pack"
        rotations_dir = pack_dir / "rotations"
        animations_dir = pack_dir / "animations" / WALK_ANIM_ID
        pack_dir.mkdir(parents=True, exist_ok=True)
        rotations_dir.mkdir(parents=True, exist_ok=True)
        animations_dir.mkdir(parents=True, exist_ok=True)

        # -- Step 1: generate east-facing base character --
        base_resp = self._client.generate_image_pixflux(
            description=req.prompt,
            direction="east",
            **_PIXFLUX_COMMON,
        )
        east_img: Image.Image = base_resp.image.pil_image().convert("RGBA")
        east_img.save(rotations_dir / "east.png")

        # -- Step 2: rotate east -> north, west, south --
        rotations: dict[str, Image.Image] = {"east": east_img}
        for target in ("north", "west", "south"):
            resp = self._client.rotate(
                image_size={"width": NATIVE_SIZE, "height": NATIVE_SIZE},
                from_image=east_img,
                from_view="low top-down",
                to_view="low top-down",
                from_direction="east",
                to_direction=target,
            )
            img = resp.image.pil_image().convert("RGBA")
            rotations[target] = img
            img.save(rotations_dir / f"{target}.png")

        # -- Step 3: animate walk per 4 cardinals --
        for direction in CARDINALS:
            resp = self._client.animate_with_text(
                image_size={"width": NATIVE_SIZE, "height": NATIVE_SIZE},
                description=req.prompt,
                negative_description="",
                action="walk",
                reference_image=rotations[direction],
                view="low top-down",
                direction=direction,
                n_frames=WALK_FRAMES_PER_DIR,
            )
            frames = [img.pil_image().convert("RGBA") for img in resp.images]
            frame_dir = animations_dir / direction
            frame_dir.mkdir(parents=True, exist_ok=True)
            for i, frame in enumerate(frames):
                frame.save(frame_dir / f"frame_{i:03d}.png")

        # -- Step 4: write pack metadata.json --
        pack_metadata = {
            "character": {
                "id": f"pixellab-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
                "name": req.prompt[:80],
                "prompt": req.prompt,
                "size": {"width": NATIVE_SIZE, "height": NATIVE_SIZE},
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

        # -- Step 5: convert pack to PERSON_PREMADE sheet --
        sheet_path = req.output_dir / "walk.png"
        from pixel_forge.experiments.pixellab_to_sheet import convert_pack

        convert_pack(pack_dir, sheet_path)

        dims = {
            "cell": [CELL_W, CELL_H],
            "cols": TARGET_COLS,
            "rows": TARGET_ROWS,
            "direction_order": DIRECTION_ORDER,
            "locomotion_rows": {
                "preview": PREVIEW_ROW,
                "idle": IDLE_ROW,
                "walk": WALK_ROW,
            },
            "frames_per_dir": FRAMES_PER_DIR,
        }
        return WalkingSheetResult(sheet_path=sheet_path, dims=dims)

    # ------------------------------------------------------------------
    # CharacterBackend protocol: action sheets (no-op)
    # ------------------------------------------------------------------

    def generate_action_sheets(self, req: ActionSheetsRequest) -> ActionSheetsResult:
        """PixelLab has no action endpoint; return empty result."""
        return ActionSheetsResult(sheets={})
