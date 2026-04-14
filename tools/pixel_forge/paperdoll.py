"""Paper-doll compositor.

Takes a `CharacterProfile` plus a `Recipe` selecting one file per layer
slot and produces a single composed RGBA sprite sheet, plus the metadata
the sidecar needs to record what was composed.

This is the AI-free path for new character generation: when a third-party
asset pack already provides body + outfit + hair + eyes + accessory
layers, we don't need a model to invent a 72-frame walk cycle — we just
alpha-composite the layers in z-order. Smoke test in
`tools/pixel_forge/smoke_paperdoll.py` proved the moderninteriors pack
composes cleanly with this approach.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image

from pixel_forge.profiles.limezu import (
    CharacterProfile,
    ProfileError,
    slot_dir,
)


class PaperdollError(Exception):
    """Raised when a recipe cannot be composed against a profile."""


@dataclass(frozen=True)
class Recipe:
    """Which file to use for each layer slot.

    Keys are slot names (see `pixel_forge.profiles.limezu` constants).
    Values are filenames (basenames) within the slot's directory — NOT
    absolute paths. Resolution to absolute paths happens in `_resolve`.
    Optional slots may be omitted entirely.
    """
    profile_id: str
    layers: dict[str, str]  # slot_name → filename


@dataclass(frozen=True)
class ComposedCharacter:
    image: Image.Image
    canvas_size: tuple[int, int]
    layer_paths: dict[str, Path]   # slot_name → absolute layer file path
    layer_sha1: dict[str, str]     # slot_name → hex sha1 of source bytes


def _sha1_of(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


def _resolve(profile: CharacterProfile, recipe: Recipe) -> dict[str, Path]:
    """Map each recipe slot to an absolute layer file path.

    Validates: required slots are present, declared slots exist on the
    profile, files exist on disk. Optional slots that are missing from the
    recipe are simply not returned.
    """
    if recipe.profile_id != profile.id:
        raise PaperdollError(
            f"recipe profile {recipe.profile_id!r} != profile {profile.id!r}"
        )

    resolved: dict[str, Path] = {}
    for slot_name, filename in recipe.layers.items():
        if slot_name not in profile.slots:
            raise PaperdollError(
                f"unknown slot {slot_name!r} for profile {profile.id!r}; "
                f"valid: {sorted(profile.slots)}"
            )
        try:
            d = slot_dir(profile, slot_name)
        except ProfileError as err:
            raise PaperdollError(str(err)) from err
        candidate = d / filename
        if not candidate.is_file():
            raise PaperdollError(
                f"layer file missing: {candidate} "
                f"(slot={slot_name}, profile={profile.id})"
            )
        resolved[slot_name] = candidate

    missing_required = [
        name for name in profile.required_slots() if name not in resolved
    ]
    if missing_required:
        raise PaperdollError(
            f"recipe is missing required slots {missing_required} "
            f"for profile {profile.id!r}"
        )
    return resolved


def _load_normalized(
    profile: CharacterProfile,
    slot_name: str,
    path: Path,
) -> Image.Image:
    """Open a layer PNG and crop/normalize it to the profile canvas.

    Some packs (e.g. moderninteriors body sheets) include an annotation
    strip outside the art area — the slot's `crop_rule` describes how to
    trim it. After cropping, every layer must match `profile.canvas_size`
    exactly; otherwise the recipe + profile combination is broken.
    """
    img = Image.open(path).convert("RGBA")
    slot = profile.slots[slot_name]
    if slot.crop_rule is not None and img.size == slot.crop_rule.native_size:
        img = img.crop(slot.crop_rule.crop_box)

    if img.size != profile.canvas_size:
        raise PaperdollError(
            f"layer {slot_name}={path.name} size {img.size} does not match "
            f"profile {profile.id!r} canvas {profile.canvas_size} "
            f"(after any crop_rule)"
        )
    return img


def compose(profile: CharacterProfile, recipe: Recipe) -> ComposedCharacter:
    """Resolve a recipe against a profile and produce the composed sheet."""
    resolved = _resolve(profile, recipe)

    canvas = Image.new("RGBA", profile.canvas_size, (0, 0, 0, 0))
    layer_sha1: dict[str, str] = {}

    for slot_name in profile.z_order:
        if slot_name not in resolved:
            continue  # optional slot not in recipe
        layer_path = resolved[slot_name]
        layer_img = _load_normalized(profile, slot_name, layer_path)
        canvas = Image.alpha_composite(canvas, layer_img)
        layer_sha1[slot_name] = _sha1_of(layer_path)

    return ComposedCharacter(
        image=canvas,
        canvas_size=profile.canvas_size,
        layer_paths=resolved,
        layer_sha1=layer_sha1,
    )


def recipe_to_sidecar_animation(
    profile: CharacterProfile,
    recipe: Recipe,
    composed: ComposedCharacter,
) -> dict[str, Any]:
    """Build the dict that goes into AssetSidecar.animation for a paperdoll
    character. The sidecar schema's `animation` field is open-ended dict,
    so this is the structural contract that downstream tools (sunny-street
    adapter, runtime registration) will read.
    """
    return {
        "system": "paperdoll",
        "profile": profile.id,
        "canvas": {"w": profile.canvas_size[0], "h": profile.canvas_size[1]},
        "frame": {"w": profile.frame_size[0], "h": profile.frame_size[1]},
        "sheet_cols": profile.sheet_cols,
        "direction_order": list(profile.direction_order),
        "locomotion_rows": dict(profile.locomotion_rows),
        "locomotion_frames_per_dir": dict(profile.locomotion_frames_per_dir),
        "recipe": {slot: filename for slot, filename in recipe.layers.items()},
        "layer_sha1": dict(composed.layer_sha1),
    }
