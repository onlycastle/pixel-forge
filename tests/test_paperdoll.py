"""Unit tests for the paperdoll compositor.

Uses tiny synthetic PNGs as layer fixtures so the suite has zero
dependency on third-party LimeZu assets (which we never commit to the
repo). Each test builds a minimal `CharacterProfile` whose generator root
points at `tmp_path`, then writes a few solid-color PNGs into the right
slot subdirectories.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from pixel_forge.paperdoll import (
    PaperdollError,
    Recipe,
    compose,
    recipe_to_sidecar_animation,
)
from pixel_forge.profiles.limezu import (
    DEFAULT_Z_ORDER,
    LAYER_ACCESSORY,
    LAYER_BODY,
    LAYER_EYES,
    LAYER_HAIR,
    LAYER_OUTFIT,
    CharacterProfile,
    CropRule,
    LayerSlot,
)

CANVAS = (8, 4)


def _solid(size: tuple[int, int], rgba: tuple[int, int, int, int]) -> Image.Image:
    return Image.new("RGBA", size, rgba)


def _build_profile(
    tmp_path: Path,
    *,
    body_crop: CropRule | None = None,
    optional_hair: bool = False,
) -> CharacterProfile:
    """Build a tiny profile rooted at tmp_path and create slot directories."""
    slots = {
        LAYER_BODY: LayerSlot(
            name=LAYER_BODY, subdir="Bodies", required=True, crop_rule=body_crop
        ),
        LAYER_OUTFIT: LayerSlot(name=LAYER_OUTFIT, subdir="Outfits", required=True),
        LAYER_HAIR: LayerSlot(
            name=LAYER_HAIR, subdir="Hair", required=not optional_hair
        ),
        LAYER_EYES: LayerSlot(name=LAYER_EYES, subdir="Eyes", required=False),
        LAYER_ACCESSORY: LayerSlot(
            name=LAYER_ACCESSORY, subdir="Accessories", required=False
        ),
    }
    profile = CharacterProfile(
        id="test-profile",
        canvas_size=CANVAS,
        frame_size=(2, 2),
        sheet_cols=4,
        z_order=DEFAULT_Z_ORDER,
        slots=slots,
        generator_root_relative="pack",
    )
    for slot in slots.values():
        (tmp_path / "pack" / slot.subdir).mkdir(parents=True, exist_ok=True)
    return profile


@pytest.fixture(autouse=True)
def _isolate_assets_root(monkeypatch, tmp_path):
    monkeypatch.setenv("LIMEZU_ASSETS_ROOT", str(tmp_path))
    monkeypatch.chdir(tmp_path)


def test_compose_z_order_top_layer_wins(tmp_path: Path) -> None:
    profile = _build_profile(tmp_path)
    pack = tmp_path / "pack"
    _solid(CANVAS, (255, 0, 0, 255)).save(pack / "Bodies" / "body.png")
    _solid(CANVAS, (0, 255, 0, 255)).save(pack / "Outfits" / "outfit.png")
    _solid(CANVAS, (0, 0, 255, 255)).save(pack / "Hair" / "hair.png")
    _solid(CANVAS, (255, 255, 0, 255)).save(pack / "Eyes" / "eyes.png")

    result = compose(
        profile,
        Recipe(
            profile_id=profile.id,
            layers={
                LAYER_BODY: "body.png",
                LAYER_OUTFIT: "outfit.png",
                LAYER_HAIR: "hair.png",
                LAYER_EYES: "eyes.png",
            },
        ),
    )

    # All layers are fully opaque — the top one (eyes per DEFAULT_Z_ORDER)
    # should win every pixel.
    assert result.image.getpixel((0, 0)) == (255, 255, 0, 255)
    assert result.canvas_size == CANVAS


def test_compose_alpha_blending_lets_lower_layers_show(tmp_path: Path) -> None:
    profile = _build_profile(tmp_path)
    pack = tmp_path / "pack"
    # Body is solid red, outfit is fully transparent — body should show through
    _solid(CANVAS, (255, 0, 0, 255)).save(pack / "Bodies" / "body.png")
    _solid(CANVAS, (0, 255, 0, 0)).save(pack / "Outfits" / "outfit.png")
    _solid(CANVAS, (0, 0, 255, 0)).save(pack / "Hair" / "hair.png")

    result = compose(
        profile,
        Recipe(
            profile_id=profile.id,
            layers={
                LAYER_BODY: "body.png",
                LAYER_OUTFIT: "outfit.png",
                LAYER_HAIR: "hair.png",
            },
        ),
    )

    assert result.image.getpixel((0, 0)) == (255, 0, 0, 255)


def test_body_crop_rule_drops_annotation_strip(tmp_path: Path) -> None:
    # Body native is wider than canvas; crop_rule pulls the leftmost CANVAS.w
    crop = CropRule(native_size=(12, 4), crop_box=(0, 0, 8, 4))
    profile = _build_profile(tmp_path, body_crop=crop)
    pack = tmp_path / "pack"

    body_native = Image.new("RGBA", (12, 4), (0, 0, 0, 0))
    # Left 8 columns: red. Right 4 columns: solid magenta (the "annotation strip")
    for x in range(8):
        for y in range(4):
            body_native.putpixel((x, y), (255, 0, 0, 255))
    for x in range(8, 12):
        for y in range(4):
            body_native.putpixel((x, y), (255, 0, 255, 255))
    body_native.save(pack / "Bodies" / "body.png")

    _solid(CANVAS, (0, 0, 0, 0)).save(pack / "Outfits" / "outfit.png")
    _solid(CANVAS, (0, 0, 0, 0)).save(pack / "Hair" / "hair.png")

    result = compose(
        profile,
        Recipe(
            profile_id=profile.id,
            layers={
                LAYER_BODY: "body.png",
                LAYER_OUTFIT: "outfit.png",
                LAYER_HAIR: "hair.png",
            },
        ),
    )
    assert result.canvas_size == CANVAS
    assert result.image.size == CANVAS
    # Every pixel of the result is the cropped body's red — magenta strip is gone.
    for x in range(CANVAS[0]):
        for y in range(CANVAS[1]):
            assert result.image.getpixel((x, y)) == (255, 0, 0, 255)


def test_canvas_size_mismatch_raises(tmp_path: Path) -> None:
    profile = _build_profile(tmp_path)
    pack = tmp_path / "pack"
    # Body has wrong size and no crop_rule that matches → raise
    Image.new("RGBA", (16, 8), (255, 0, 0, 255)).save(pack / "Bodies" / "body.png")
    _solid(CANVAS, (0, 0, 0, 0)).save(pack / "Outfits" / "outfit.png")
    _solid(CANVAS, (0, 0, 0, 0)).save(pack / "Hair" / "hair.png")

    with pytest.raises(PaperdollError, match="does not match"):
        compose(
            profile,
            Recipe(
                profile_id=profile.id,
                layers={
                    LAYER_BODY: "body.png",
                    LAYER_OUTFIT: "outfit.png",
                    LAYER_HAIR: "hair.png",
                },
            ),
        )


def test_missing_required_slot_raises(tmp_path: Path) -> None:
    profile = _build_profile(tmp_path)
    pack = tmp_path / "pack"
    _solid(CANVAS, (255, 0, 0, 255)).save(pack / "Bodies" / "body.png")
    _solid(CANVAS, (0, 255, 0, 255)).save(pack / "Outfits" / "outfit.png")
    # Hair is required by default but we omit it from the recipe

    with pytest.raises(PaperdollError, match="missing required slots"):
        compose(
            profile,
            Recipe(
                profile_id=profile.id,
                layers={
                    LAYER_BODY: "body.png",
                    LAYER_OUTFIT: "outfit.png",
                },
            ),
        )


def test_optional_slot_can_be_omitted(tmp_path: Path) -> None:
    profile = _build_profile(tmp_path, optional_hair=True)
    pack = tmp_path / "pack"
    _solid(CANVAS, (255, 0, 0, 255)).save(pack / "Bodies" / "body.png")
    _solid(CANVAS, (0, 255, 0, 255)).save(pack / "Outfits" / "outfit.png")

    result = compose(
        profile,
        Recipe(
            profile_id=profile.id,
            layers={
                LAYER_BODY: "body.png",
                LAYER_OUTFIT: "outfit.png",
            },
        ),
    )
    # Outfit (top opaque layer of the two) wins
    assert result.image.getpixel((0, 0)) == (0, 255, 0, 255)
    assert LAYER_HAIR not in result.layer_paths
    assert LAYER_HAIR not in result.layer_sha1


def test_recipe_profile_id_must_match(tmp_path: Path) -> None:
    profile = _build_profile(tmp_path)
    pack = tmp_path / "pack"
    _solid(CANVAS, (0, 0, 0, 0)).save(pack / "Bodies" / "body.png")
    _solid(CANVAS, (0, 0, 0, 0)).save(pack / "Outfits" / "outfit.png")
    _solid(CANVAS, (0, 0, 0, 0)).save(pack / "Hair" / "hair.png")

    with pytest.raises(PaperdollError, match="profile"):
        compose(
            profile,
            Recipe(
                profile_id="other",
                layers={
                    LAYER_BODY: "body.png",
                    LAYER_OUTFIT: "outfit.png",
                    LAYER_HAIR: "hair.png",
                },
            ),
        )


def test_unknown_slot_raises(tmp_path: Path) -> None:
    profile = _build_profile(tmp_path)
    pack = tmp_path / "pack"
    _solid(CANVAS, (0, 0, 0, 0)).save(pack / "Bodies" / "body.png")
    _solid(CANVAS, (0, 0, 0, 0)).save(pack / "Outfits" / "outfit.png")
    _solid(CANVAS, (0, 0, 0, 0)).save(pack / "Hair" / "hair.png")

    with pytest.raises(PaperdollError, match="unknown slot"):
        compose(
            profile,
            Recipe(
                profile_id=profile.id,
                layers={
                    LAYER_BODY: "body.png",
                    LAYER_OUTFIT: "outfit.png",
                    LAYER_HAIR: "hair.png",
                    "boots": "boots.png",
                },
            ),
        )


def test_missing_layer_file_raises(tmp_path: Path) -> None:
    profile = _build_profile(tmp_path)
    pack = tmp_path / "pack"
    _solid(CANVAS, (0, 0, 0, 0)).save(pack / "Bodies" / "body.png")
    _solid(CANVAS, (0, 0, 0, 0)).save(pack / "Outfits" / "outfit.png")
    # Hair file is referenced but not on disk

    with pytest.raises(PaperdollError, match="layer file missing"):
        compose(
            profile,
            Recipe(
                profile_id=profile.id,
                layers={
                    LAYER_BODY: "body.png",
                    LAYER_OUTFIT: "outfit.png",
                    LAYER_HAIR: "ghost.png",
                },
            ),
        )


def test_recipe_to_sidecar_animation_has_expected_shape(tmp_path: Path) -> None:
    profile = _build_profile(tmp_path)
    pack = tmp_path / "pack"
    for slot, name in (
        (LAYER_BODY, "Bodies"),
        (LAYER_OUTFIT, "Outfits"),
        (LAYER_HAIR, "Hair"),
    ):
        _solid(CANVAS, (1, 2, 3, 255)).save(pack / name / "x.png")

    recipe = Recipe(
        profile_id=profile.id,
        layers={LAYER_BODY: "x.png", LAYER_OUTFIT: "x.png", LAYER_HAIR: "x.png"},
    )
    composed = compose(profile, recipe)
    anim = recipe_to_sidecar_animation(profile, recipe, composed)

    assert anim["system"] == "paperdoll"
    assert anim["profile"] == profile.id
    assert anim["canvas"] == {"w": CANVAS[0], "h": CANVAS[1]}
    assert anim["frame"] == {"w": 2, "h": 2}
    assert anim["sheet_cols"] == 4
    assert anim["recipe"] == {
        LAYER_BODY: "x.png",
        LAYER_OUTFIT: "x.png",
        LAYER_HAIR: "x.png",
    }
    assert set(anim["layer_sha1"]) == {LAYER_BODY, LAYER_OUTFIT, LAYER_HAIR}
    # All three solid PNGs share the same sha1 since they're identical bytes
    assert len(set(anim["layer_sha1"].values())) == 1
