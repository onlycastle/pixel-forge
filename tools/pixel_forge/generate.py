from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import ceil
from pathlib import Path
from typing import Any

from PIL import Image

from pixel_forge.assets import (
    SCHEMA_VERSION,
    AssetKind,
    AssetSidecar,
    Footprint,
    Sheet,
    save_sidecar,
)
from pixel_forge.backends.base import ImageBackend
from pixel_forge.paths import ProjectPaths
from pixel_forge.postprocess import ensure_alpha, quantize_to_palette, resize_to_tile
from pixel_forge.project import Project
from pixel_forge.usage import UsageRecord
from pixel_forge.validate import check_alpha, check_grid, check_palette


# Map AssetKind → the sunny-street layer the asset will feed. The editor and
# the sunny-street adapter both read this via the sidecar; nothing downstream
# guesses.
_KIND_LAYER: dict[AssetKind, str] = {
    AssetKind.GROUND_TILESET: "ground",
    AssetKind.OBJECT_TILESET: "object",
    AssetKind.PLACEABLE:      "placeables",
    AssetKind.CHARACTER:      "none",
    AssetKind.MAP:            "none",
}

# Kinds that require grid-aligned output. Placeables/characters have
# free-form bounds and skip grid validation.
_GRID_CHECKED_KINDS = {AssetKind.GROUND_TILESET, AssetKind.OBJECT_TILESET}


@dataclass(frozen=True)
class GenerateRequest:
    project: Project
    kind: str           # AssetKind value, e.g. "placeable"
    prompt: str
    variants: int
    # Kind-specific:
    footprint: Footprint | None = None  # placeable
    sheet: Sheet | None = None          # *-tileset
    anchor: str | None = None           # placeable
    # Optional ad-hoc reference image (in addition to project.hero_reference
    # and project.extra_references). When provided it gets appended to the
    # ref list passed to the backend, so the model sees it alongside the
    # project's standing style anchors.
    extra_reference: Path | None = None


@dataclass(frozen=True)
class Variant:
    """One generated asset with its validation results and sidecar path."""
    path: Path
    sidecar_path: Path
    validation: dict[str, str]
    validation_details: dict[str, Any]
    passed: bool


@dataclass(frozen=True)
class GenerateResult:
    variants: list[Variant]
    errors: list[str]
    # Token usage captured from the backend's last generate() call.
    # May be None when the backend doesn't track usage (older stubs,
    # external callers wiring a custom backend).
    usage: "UsageRecord | None" = None


class GenerateRequestError(ValueError):
    """Raised when a GenerateRequest has inconsistent kind-specific fields."""


def _coerce_kind(kind: str) -> AssetKind:
    try:
        return AssetKind(kind)
    except ValueError as err:
        raise GenerateRequestError(
            f"Unknown kind {kind!r}. Valid: {[k.value for k in AssetKind]}"
        ) from err


def _validate_request(req: GenerateRequest, asset_kind: AssetKind) -> None:
    if asset_kind in (AssetKind.GROUND_TILESET, AssetKind.OBJECT_TILESET):
        if req.sheet is None:
            raise GenerateRequestError(
                f"kind={asset_kind.value} requires --sheet CxR"
            )
        if req.footprint is not None:
            raise GenerateRequestError(
                f"kind={asset_kind.value} does not accept --footprint"
            )
    elif asset_kind is AssetKind.PLACEABLE:
        if req.sheet is not None:
            raise GenerateRequestError("kind=placeable does not accept --sheet")
    elif asset_kind is AssetKind.CHARACTER:
        if req.sheet is not None or req.footprint is not None:
            raise GenerateRequestError(
                "kind=character does not accept --sheet or --footprint"
            )
    elif asset_kind is AssetKind.MAP:
        raise GenerateRequestError(
            "kind=map is handled by the composer (pf compose), not generate"
        )


def _build_prompt(
    project: Project,
    user_prompt: str,
    kind: str,
    *,
    footprint: Footprint | None = None,
    sheet: Sheet | None = None,
) -> str:
    """Build the layered prompt for the backend.

    Layered anchors are: (1) project prose, (2) palette lines, (3) optional
    hero reference. The output line is kind-specific so the model knows
    whether to produce a seamless grid sheet, a single stamp, or a sprite.
    """
    asset_kind = _coerce_kind(kind)
    palette_lines = "\n".join(f"#{r:02x}{g:02x}{b:02x}" for r, g, b in project.palette)
    reference_line = (
        "Reference image attached: match its line weight, shading, detail density.\n"
        if project.hero_reference is not None
        else ""
    )

    ts = project.tile_size
    if asset_kind is AssetKind.GROUND_TILESET:
        assert sheet is not None  # validated upstream
        w = sheet.cols * ts
        h = sheet.rows * ts
        output_line = (
            f"Output: {w}x{h} PNG containing a {sheet.cols} columns × {sheet.rows} rows "
            f"grid of seamless {ts}x{ts} ground tiles. Tiles must tile cleanly at every "
            f"{ts}-pixel boundary. Transparent background, pixel art."
        )
    elif asset_kind is AssetKind.OBJECT_TILESET:
        assert sheet is not None
        w = sheet.cols * ts
        h = sheet.rows * ts
        output_line = (
            f"Output: {w}x{h} PNG containing a {sheet.cols} columns × {sheet.rows} rows "
            f"grid of {ts}x{ts} object tiles (individual props, not seamless). "
            f"Transparent background so cells drop onto ground cleanly. Pixel art."
        )
    elif asset_kind is AssetKind.PLACEABLE:
        if footprint is not None:
            w = footprint.w * ts
            h = footprint.h * ts
            output_line = (
                f"Output: {w}x{h} PNG (a single {footprint.w}×{footprint.h} tile "
                f"stamp). Transparent background, pixel art. Use the {ts}-pixel grid "
                f"as the unit scale."
            )
        else:
            output_line = (
                f"Output: PNG with transparent background, pixel art, sized to the "
                f"subject in whole {ts}-pixel tile units."
            )
    elif asset_kind is AssetKind.CHARACTER:
        output_line = (
            f"Output: PNG with transparent background, pixel art, sized to the "
            f"subject. Use the project's {ts}-pixel grid as the unit scale."
        )
    else:  # pragma: no cover — MAP is rejected upstream
        raise GenerateRequestError(f"no prompt builder for kind {kind!r}")

    return (
        f"{project.prose}\n"
        f"Palette (use ONLY these colors):\n{palette_lines}\n"
        f"{reference_line}"
        f"Task: {user_prompt}\n"
        f"{output_line}\n"
    )


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


def _infer_footprint(img: Image.Image, tile_size: int) -> Footprint:
    return Footprint(
        w=max(1, ceil(img.width / tile_size)),
        h=max(1, ceil(img.height / tile_size)),
    )


def _resize_for_kind(
    img: Image.Image,
    asset_kind: AssetKind,
    tile_size: int,
    sheet: Sheet | None,
    footprint: Footprint | None,
) -> Image.Image:
    """Normalize the raw backend image to the kind's expected bounds.

    Tileset kinds get a crisp downscale to the declared sheet size so grid
    validation passes. Placeables with explicit footprints get the same.
    Everything else is left at native resolution.
    """
    if asset_kind in _GRID_CHECKED_KINDS:
        assert sheet is not None
        target = (sheet.cols * tile_size, sheet.rows * tile_size)
        # Center-crop to the target aspect, then LANCZOS resize. Re-uses the
        # square-crop logic from resize_to_tile when cols == rows.
        if sheet.cols == sheet.rows:
            return resize_to_tile(img, target[0])  # square path
        return _crop_and_resize(img, target)
    if asset_kind is AssetKind.PLACEABLE and footprint is not None:
        target = (footprint.w * tile_size, footprint.h * tile_size)
        if footprint.w == footprint.h:
            return resize_to_tile(img, target[0])
        return _crop_and_resize(img, target)
    return img


def _crop_and_resize(img: Image.Image, target: tuple[int, int]) -> Image.Image:
    """Center-crop to the target aspect ratio, then LANCZOS downscale."""
    tw, th = target
    src_w, src_h = img.size
    src_aspect = src_w / src_h
    tgt_aspect = tw / th
    if src_aspect > tgt_aspect:
        # Source is wider: crop horizontally.
        new_w = int(round(src_h * tgt_aspect))
        left = (src_w - new_w) // 2
        cropped = img.crop((left, 0, left + new_w, src_h))
    else:
        new_h = int(round(src_w / tgt_aspect))
        top = (src_h - new_h) // 2
        cropped = img.crop((0, top, src_w, top + new_h))
    if cropped.size == target:
        return cropped
    return cropped.resize(target, Image.Resampling.LANCZOS)


def _sidecar_for(
    asset_kind: AssetKind,
    slug: str,
    project: Project,
    prompt: str,
    footprint: Footprint | None,
    sheet: Sheet | None,
    anchor: str | None,
) -> AssetSidecar:
    return AssetSidecar(
        schema_version=SCHEMA_VERSION,
        kind=asset_kind,
        layer_target=_KIND_LAYER[asset_kind],
        tile_size=project.tile_size,
        slug=slug,
        footprint=footprint,
        sheet=sheet,
        anchor=anchor or ("bottom-center" if asset_kind is AssetKind.PLACEABLE else None),
        source_prompt=prompt,
        created_at=_now_iso(),
    )


def run(request: GenerateRequest, backend: ImageBackend) -> GenerateResult:
    asset_kind = _coerce_kind(request.kind)
    _validate_request(request, asset_kind)

    project = request.project
    paths = ProjectPaths(project_root=project.root, output_root=project.output_root)
    paths.ensure(request.kind)

    prompt = _build_prompt(
        project,
        request.prompt,
        request.kind,
        footprint=request.footprint,
        sheet=request.sheet,
    )
    refs: list[Path] = []
    if project.hero_reference is not None:
        refs.append(project.hero_reference)
    refs.extend(project.extra_references)
    if request.extra_reference is not None:
        if not request.extra_reference.is_file():
            raise GenerateRequestError(
                f"extra reference image not found: {request.extra_reference}"
            )
        refs.append(request.extra_reference)

    raw_paths = backend.generate(prompt=prompt, refs=refs, n=request.variants)
    # Capture backend usage (set by the backend's generate() call).
    # Missing attribute → None (old backends that don't implement usage
    # tracking still work; callers handle the None case).
    backend_usage: UsageRecord | None = getattr(backend, "last_usage", None)

    variants: list[Variant] = []
    ts = _timestamp()
    slug_base = request.prompt.lower().replace(" ", "-")[:32].strip("-") or "asset"

    for idx, raw_path in enumerate(raw_paths, start=1):
        with Image.open(raw_path) as raw:
            processed = ensure_alpha(raw)
        processed = _resize_for_kind(
            processed, asset_kind, project.tile_size, request.sheet, request.footprint
        )
        processed = ensure_alpha(processed)
        processed = quantize_to_palette(processed, project.palette)

        variant_slug = f"{slug_base}-{ts}-v{idx}"
        final_name = f"{variant_slug}.png"
        final_path = paths.kind_dir(request.kind) / final_name
        processed.save(final_path)

        # Footprint inference for placeables that didn't declare one.
        effective_footprint = request.footprint
        if asset_kind is AssetKind.PLACEABLE and effective_footprint is None:
            effective_footprint = _infer_footprint(processed, project.tile_size)

        sidecar = _sidecar_for(
            asset_kind=asset_kind,
            slug=variant_slug,
            project=project,
            prompt=request.prompt,
            footprint=effective_footprint,
            sheet=request.sheet,
            anchor=request.anchor,
        )
        sidecar_path = save_sidecar(final_path, sidecar)

        palette_result = check_palette(
            processed, project.palette, project.max_off_palette_pixels
        )
        grid_result = (
            check_grid(processed, project.tile_size)
            if asset_kind in _GRID_CHECKED_KINDS
            else None
        )
        alpha_result = check_alpha(processed)

        validation = {
            "palette": palette_result.status,
            "grid": grid_result.status if grid_result else "n/a",
            "alpha": alpha_result.status,
        }
        details: dict[str, Any] = {
            "palette": palette_result.details,
            "alpha": alpha_result.details,
        }
        if grid_result is not None:
            details["grid"] = grid_result.details

        passed = palette_result.status != "fail" and (
            grid_result is None or grid_result.status != "fail"
        )

        variants.append(
            Variant(
                path=final_path,
                sidecar_path=sidecar_path,
                validation=validation,
                validation_details=details,
                passed=passed,
            )
        )

    return GenerateResult(variants=variants, errors=[], usage=backend_usage)
