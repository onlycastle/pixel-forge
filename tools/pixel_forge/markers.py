"""Phase 3 — LLM-backed marker placement suggester.

Given a map context (dimensions, layer prompts, desired NPCs, desired
transitions), this module prompts a text LLM to return a list of Tiled
marker objects in strict JSON and validates the response before handing it
to the composer.

The LLM is injected as a `Callable[[str], str]` so tests can pass a fixed
response. Production uses the Gemini text model via
`pixel_forge.backends.gemini_text.gemini_text_llm`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable


MARKER_TYPES: set[str] = {
    "transition",
    "hotspot",
    "spawn",
    "npc",
    "resource",
    "animal",
    "fishing-spot",
    "crop-zone",
}

POINT_MARKER_TYPES: set[str] = {"spawn", "npc", "resource", "fishing-spot"}


class MarkerSchemaError(ValueError):
    """Raised when the LLM response doesn't match the expected marker schema."""


@dataclass(frozen=True)
class MarkerContext:
    map_name: str
    map_width: int       # in tiles
    map_height: int      # in tiles
    tile_size: int       # in pixels
    ground_prompt: str
    object_prompt: str | None = None
    placeable_prompts: list[str] = field(default_factory=list)
    requested_npcs: list[str] = field(default_factory=list)
    requested_transitions: list[dict[str, Any]] = field(default_factory=list)


def _build_marker_prompt(ctx: MarkerContext) -> str:
    lines: list[str] = []
    lines.append(
        "You are placing gameplay markers on a top-down tile-based map. "
        "Respond ONLY with valid JSON — no prose, no markdown fences."
    )
    lines.append("")
    lines.append(f"Map: {ctx.map_name}")
    lines.append(
        f"Dimensions: {ctx.map_width} × {ctx.map_height} tiles "
        f"({ctx.map_width * ctx.tile_size} × {ctx.map_height * ctx.tile_size} pixels)"
    )
    lines.append(f"Tile size: {ctx.tile_size} pixels")
    lines.append(f"Ground style: {ctx.ground_prompt}")
    if ctx.object_prompt:
        lines.append(f"Object tileset: {ctx.object_prompt}")
    if ctx.placeable_prompts:
        lines.append("Placeables on the map:")
        for p in ctx.placeable_prompts:
            lines.append(f"  - {p}")
    lines.append("")

    if ctx.requested_transitions:
        lines.append("Required transitions (edge doorways to other maps):")
        for t in ctx.requested_transitions:
            to = t.get("to", "?")
            side = t.get("side", "?")
            lines.append(f"  - side={side}, targetMap={to}")
    if ctx.requested_npcs:
        lines.append("Required NPCs:")
        for n in ctx.requested_npcs:
            lines.append(f"  - {n}")

    lines.append("")
    lines.append(
        "Return a JSON object: "
        '{ "markers": [ ... ] }. Each marker has:\n'
        '  - markerType: one of "transition","hotspot","spawn","npc",'
        '"resource","animal","fishing-spot","crop-zone"\n'
        "  - name: short string id\n"
        "  - x, y: pixel coordinates inside the map bounds\n"
        "  - For bounded markers (transition, hotspot, crop-zone): width, height in pixels.\n"
        "  - For point markers (spawn, npc, resource, fishing-spot): set point=true.\n"
        "  - transition markers must include targetMap and targetSpawn strings.\n"
        "  - transition markers may include requiredFacing: up|down|left|right.\n"
        "  - npc markers must include npcId: string.\n"
    )
    return "\n".join(lines)


def _parse_llm_json(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as err:
        raise MarkerSchemaError(f"LLM did not return valid JSON: {err}") from err
    if not isinstance(payload, dict):
        raise MarkerSchemaError(f"LLM JSON must be an object, got {type(payload).__name__}")
    if "markers" not in payload:
        raise MarkerSchemaError("LLM JSON missing 'markers' key")
    if not isinstance(payload["markers"], list):
        raise MarkerSchemaError("'markers' must be a list")
    return payload


def _validate_one_marker(marker: dict[str, Any], idx: int) -> None:
    if not isinstance(marker, dict):
        raise MarkerSchemaError(f"marker[{idx}] must be a JSON object")
    mt = marker.get("markerType")
    if mt not in MARKER_TYPES:
        raise MarkerSchemaError(
            f"marker[{idx}] has invalid markerType {mt!r}; "
            f"expected one of {sorted(MARKER_TYPES)}"
        )
    if "name" not in marker or not isinstance(marker["name"], str):
        raise MarkerSchemaError(f"marker[{idx}] missing string 'name'")
    if not all(isinstance(marker.get(k), (int, float)) for k in ("x", "y")):
        raise MarkerSchemaError(f"marker[{idx}] missing numeric x/y")

    if mt == "transition":
        if "targetMap" not in marker or not isinstance(marker["targetMap"], str):
            raise MarkerSchemaError(
                f"marker[{idx}] (transition) missing string 'targetMap'"
            )
        if "targetSpawn" not in marker or not isinstance(marker["targetSpawn"], str):
            raise MarkerSchemaError(
                f"marker[{idx}] (transition) missing string 'targetSpawn'"
            )
        for dim in ("width", "height"):
            if dim not in marker or not isinstance(marker[dim], (int, float)):
                raise MarkerSchemaError(
                    f"marker[{idx}] (transition) missing numeric {dim!r}"
                )

    if mt == "npc":
        if "npcId" not in marker or not isinstance(marker["npcId"], str):
            raise MarkerSchemaError(f"marker[{idx}] (npc) missing string 'npcId'")


_TYPE_SPECIFIC_PROPERTY_FIELDS: dict[str, list[str]] = {
    "transition": ["targetMap", "targetSpawn", "requiredFacing"],
    "hotspot":   ["hotspotKind"],
    "spawn":     ["facing"],
    "npc":       ["npcId", "facing"],
    "resource":  ["resourceType"],
    "animal":    ["animalType", "variant"],
    "fishing-spot": ["fishType"],
    "crop-zone": ["cropKind"],
}


def _marker_to_tiled_object(marker: dict[str, Any], obj_id: int) -> dict[str, Any]:
    mt: str = marker["markerType"]
    is_point = mt in POINT_MARKER_TYPES and marker.get("point", True)

    x = float(marker["x"])
    y = float(marker["y"])
    if is_point:
        width = 0
        height = 0
    else:
        width = float(marker.get("width", 0))
        height = float(marker.get("height", 0))

    properties: list[dict[str, Any]] = [
        {"name": "markerType", "type": "string", "value": mt}
    ]
    for field_name in _TYPE_SPECIFIC_PROPERTY_FIELDS.get(mt, []):
        if field_name in marker and marker[field_name] is not None:
            properties.append(
                {"name": field_name, "type": "string", "value": str(marker[field_name])}
            )

    obj: dict[str, Any] = {
        "id": obj_id,
        "name": marker["name"],
        "type": "",
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "rotation": 0,
        "visible": True,
        "properties": properties,
    }
    if is_point:
        obj["point"] = True
    return obj


def suggest_markers(
    *,
    context: MarkerContext,
    llm: Callable[[str], str],
) -> list[dict[str, Any]]:
    """Ask the LLM for marker placements and return Tiled-ready object dicts.

    Raises MarkerSchemaError on malformed responses. Unknown extra fields in
    the response are ignored (permissively stripped).
    """
    prompt = _build_marker_prompt(context)
    raw = llm(prompt)
    payload = _parse_llm_json(raw)

    markers_raw = payload["markers"]
    result: list[dict[str, Any]] = []
    for idx, marker in enumerate(markers_raw):
        _validate_one_marker(marker, idx)
        result.append(_marker_to_tiled_object(marker, obj_id=idx + 1))
    return result
