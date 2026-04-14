"""LimeZu paper-doll generator profiles.

Two parallel asset packs are supported:

- **townspeople** — `moderninteriors-win/2_Characters/Character_Generator/`
  Canvas 1792x1312, body sheets are 1854x1312 (62px right-side annotation
  strip that must be cropped). Used for premade-NN slots in sunny-street.

- **farmers** — `Modern_Farm_v1.2/Farmer_Generator_Pieces/Character Pieces/`
  Canvas 1792x704, no body crop. Used for farmer-NN slots in sunny-street.

Both packs share a Body / Outfit / Hairstyle / Eyes / Accessory layer
ontology and use straight alpha compositing in that z-order.

The asset pack root lives outside this repo (the user's private LimeZu
purchase). Path resolution goes through the LIMEZU_ASSETS_ROOT env var so
no asset paths are hardcoded into pixel-forge.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Layer slot identifiers — the compositor and CLI use these as a stable
# vocabulary, independent of the on-disk filename conventions of any
# specific pack.
LAYER_BODY = "body"
LAYER_OUTFIT = "outfit"
LAYER_HAIR = "hair"
LAYER_EYES = "eyes"
LAYER_ACCESSORY = "accessory"

# Z-order from bottom to top. Accessories sit on top so hats/glasses
# render above hair.
DEFAULT_Z_ORDER: tuple[str, ...] = (
    LAYER_BODY,
    LAYER_OUTFIT,
    LAYER_HAIR,
    LAYER_EYES,
    LAYER_ACCESSORY,
)


class ProfileError(Exception):
    """Raised when a profile is misconfigured or its asset root is missing."""


@dataclass(frozen=True)
class CropRule:
    """How to normalize a layer's native canvas to the profile canvas.

    Some packs ship body sheets with a label/annotation strip outside the
    art area. The compositor crops to (x, y, x+w, y+h) before alpha
    compositing.
    """
    native_size: tuple[int, int]
    crop_box: tuple[int, int, int, int]  # (left, top, right, bottom)


@dataclass(frozen=True)
class LayerSlot:
    """One slot in the paper-doll layer stack.

    `subdir` is relative to the profile's `generator_root`. `required`
    means the recipe MUST resolve this slot (otherwise the compositor
    rejects it). Optional slots can be omitted from a recipe.

    `crop_rule` is per-slot because only some slots (typically body) ship
    with annotation strips that need cropping.
    """
    name: str
    subdir: str
    required: bool
    crop_rule: CropRule | None = None


@dataclass(frozen=True)
class CharacterProfile:
    """A complete paper-doll layout for one third-party generator pack."""
    id: str
    canvas_size: tuple[int, int]   # (w, h) of composed output
    frame_size: tuple[int, int]    # (w, h) of one animation cell
    sheet_cols: int                # columns of frames across the canvas
    z_order: tuple[str, ...]
    slots: dict[str, LayerSlot]
    generator_root_relative: str   # under LIMEZU_ASSETS_ROOT
    # Animation row map for the locomotion band sunny-street currently uses.
    # Keys are anim names, values are row indices (0-based) within the sheet.
    locomotion_rows: dict[str, int] = field(default_factory=dict)
    # Frames-per-direction for each locomotion anim (e.g. {"idle": 6, "walk": 6}).
    locomotion_frames_per_dir: dict[str, int] = field(default_factory=dict)
    # Direction order for animations.
    direction_order: tuple[str, ...] = ("right", "up", "left", "down")

    def required_slots(self) -> list[str]:
        return [name for name, slot in self.slots.items() if slot.required]


# ---------- Asset root resolution ----------


def _assets_root() -> Path:
    """Resolve the LimeZu asset pack root from the environment.

    LimeZu packs are licensed for use in the user's own game but cannot be
    redistributed. Pixel-forge therefore never copies them into its own
    repo — it reads them at runtime from the user's private path.
    """
    env = os.environ.get("LIMEZU_ASSETS_ROOT")
    if env:
        return Path(env).expanduser()
    return Path.home() / "projects" / "sunny-street-assets"


def assets_root() -> Path:
    """Public accessor (for CLI error messages and tests)."""
    return _assets_root()


def generator_root_for(profile: CharacterProfile) -> Path:
    """Absolute path to the profile's generator pieces directory."""
    return _assets_root() / profile.generator_root_relative


def slot_dir(profile: CharacterProfile, slot_name: str) -> Path:
    """Absolute path to one layer slot directory."""
    if slot_name not in profile.slots:
        raise ProfileError(
            f"profile {profile.id!r} has no slot named {slot_name!r}; "
            f"valid slots: {sorted(profile.slots)}"
        )
    return generator_root_for(profile) / profile.slots[slot_name].subdir


def list_layer_files(profile: CharacterProfile, slot_name: str) -> list[Path]:
    """Enumerate available layer PNGs for one slot, sorted by filename."""
    d = slot_dir(profile, slot_name)
    if not d.is_dir():
        raise ProfileError(
            f"slot directory missing for {profile.id}/{slot_name}: {d}"
        )
    return sorted(p for p in d.iterdir() if p.suffix.lower() == ".png")


# ---------- Built-in profiles ----------


# Townspeople — moderninteriors Character_Generator. Canvas 1792x1312, body
# has a 62px right annotation strip. Layers stack body/outfit/hair/eyes/acc.
TOWNSPEOPLE = CharacterProfile(
    id="townspeople",
    canvas_size=(1792, 1312),
    frame_size=(32, 64),
    sheet_cols=56,
    z_order=DEFAULT_Z_ORDER,
    slots={
        LAYER_BODY: LayerSlot(
            name=LAYER_BODY,
            subdir="Bodies/32x32",
            required=True,
            crop_rule=CropRule(
                native_size=(1854, 1312),
                crop_box=(0, 0, 1792, 1312),
            ),
        ),
        LAYER_OUTFIT: LayerSlot(
            name=LAYER_OUTFIT,
            subdir="Outfits/32x32",
            required=True,
        ),
        LAYER_HAIR: LayerSlot(
            name=LAYER_HAIR,
            subdir="Hairstyles/32x32",
            required=True,
        ),
        LAYER_EYES: LayerSlot(
            name=LAYER_EYES,
            subdir="Eyes/32x32",
            required=True,
        ),
        LAYER_ACCESSORY: LayerSlot(
            name=LAYER_ACCESSORY,
            subdir="Accessories/32x32",
            required=False,
        ),
    },
    generator_root_relative=(
        "moderninteriors-win/2_Characters/Character_Generator"
    ),
    # sunny-street's character-anims.ts treats the top 3 rows of every
    # premade sheet as: row 0 = direction preview, row 1 = idle, row 2 = walk.
    locomotion_rows={"preview": 0, "idle": 1, "walk": 2},
    locomotion_frames_per_dir={"idle": 6, "walk": 6},
)


# Farmers — Modern_Farm Farmer_Generator_Pieces. Canvas 1792x704, no
# body crop. Layer subdirs are named the same as townspeople but point
# at a different pack root.
FARMERS = CharacterProfile(
    id="farmers",
    canvas_size=(1792, 704),
    frame_size=(32, 64),
    sheet_cols=56,
    z_order=DEFAULT_Z_ORDER,
    slots={
        LAYER_BODY: LayerSlot(
            name=LAYER_BODY,
            subdir="Bodies/32x32",
            required=True,
        ),
        LAYER_OUTFIT: LayerSlot(
            name=LAYER_OUTFIT,
            subdir="Outfits/32x32",
            required=True,
        ),
        LAYER_HAIR: LayerSlot(
            name=LAYER_HAIR,
            subdir="Hairstyles/32x32",
            required=False,
        ),
        LAYER_EYES: LayerSlot(
            name=LAYER_EYES,
            subdir="Eyes/32x32",
            required=False,
        ),
        LAYER_ACCESSORY: LayerSlot(
            name=LAYER_ACCESSORY,
            subdir="Accessories/32x32",
            required=False,
        ),
    },
    generator_root_relative=(
        "Modern_Farm_v1.2/Farmer_Generator_Pieces/Character Pieces"
    ),
    # Modern_Farm farmer sheets use 24 cols, not 56 — but sunny-street
    # consumes the pack's pre-composed Farmer_NN_32x32.png sheets which
    # ARE 24 cols. The generator pieces here are at the larger canvas;
    # actual sunny-street wiring will need a separate cropping step.
    locomotion_rows={"preview": 0, "idle": 1, "walk": 2},
    locomotion_frames_per_dir={"idle": 6, "walk": 6},
)


PROFILES: dict[str, CharacterProfile] = {
    TOWNSPEOPLE.id: TOWNSPEOPLE,
    FARMERS.id: FARMERS,
}


def get_profile(profile_id: str) -> CharacterProfile:
    if profile_id not in PROFILES:
        raise ProfileError(
            f"unknown profile {profile_id!r}; valid: {sorted(PROFILES)}"
        )
    return PROFILES[profile_id]
