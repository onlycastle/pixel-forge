"""Phase 3 — LLM-backed marker placement suggester tests.

The suggester takes a context describing the map + spec-declared constraints
and a thin LLM callable (so tests can inject fixed JSON). It returns a list
of Tiled-compatible marker objects ready to drop into the markers layer of
a composed TMJ.
"""
from __future__ import annotations

import json

import pytest

from pixel_forge.markers import (
    MarkerContext,
    MarkerSchemaError,
    suggest_markers,
)


def _ctx(**overrides) -> MarkerContext:
    defaults = dict(
        map_name="tiny-beach",
        map_width=8,
        map_height=6,
        tile_size=16,
        ground_prompt="warm beach sand",
        object_prompt=None,
        placeable_prompts=[],
        requested_npcs=[],
        requested_transitions=[],
    )
    defaults.update(overrides)
    return MarkerContext(**defaults)


def test_suggest_markers_parses_transition_response() -> None:
    fake_response = json.dumps(
        {
            "markers": [
                {
                    "markerType": "transition",
                    "name": "beach-to-town",
                    "x": 960,
                    "y": 0,
                    "width": 128,
                    "height": 32,
                    "targetMap": "town-center",
                    "targetSpawn": "town-from-beach",
                    "requiredFacing": "up",
                }
            ]
        }
    )
    markers = suggest_markers(
        context=_ctx(
            requested_transitions=[{"to": "town-center", "side": "top"}],
        ),
        llm=lambda _prompt: fake_response,
    )

    assert len(markers) == 1
    obj = markers[0]
    assert obj["type"] == ""  # Tiled's object.type always empty for markers
    assert obj["name"] == "beach-to-town"
    assert obj["x"] == 960 and obj["y"] == 0
    assert obj["rotation"] == 0
    assert obj["visible"] is True
    props = {p["name"]: p["value"] for p in obj["properties"]}
    assert props["markerType"] == "transition"
    assert props["targetMap"] == "town-center"
    assert props["targetSpawn"] == "town-from-beach"
    assert props["requiredFacing"] == "up"


def test_suggest_markers_assigns_incrementing_ids() -> None:
    fake = json.dumps(
        {
            "markers": [
                {"markerType": "spawn", "name": "a", "x": 0, "y": 0, "point": True},
                {"markerType": "spawn", "name": "b", "x": 32, "y": 0, "point": True},
                {"markerType": "spawn", "name": "c", "x": 64, "y": 0, "point": True},
            ]
        }
    )
    markers = suggest_markers(context=_ctx(), llm=lambda _: fake)
    assert [m["id"] for m in markers] == [1, 2, 3]


def test_suggest_markers_rejects_unknown_marker_type() -> None:
    fake = json.dumps(
        {
            "markers": [
                {"markerType": "alien", "name": "x", "x": 0, "y": 0, "point": True}
            ]
        }
    )
    with pytest.raises(MarkerSchemaError, match="markerType"):
        suggest_markers(context=_ctx(), llm=lambda _: fake)


def test_suggest_markers_rejects_transition_without_target_map() -> None:
    fake = json.dumps(
        {
            "markers": [
                {
                    "markerType": "transition",
                    "name": "x",
                    "x": 0,
                    "y": 0,
                    "width": 32,
                    "height": 32,
                    # missing targetMap
                }
            ]
        }
    )
    with pytest.raises(MarkerSchemaError, match="targetMap"):
        suggest_markers(context=_ctx(), llm=lambda _: fake)


def test_suggest_markers_handles_point_markers_with_zero_bounds() -> None:
    fake = json.dumps(
        {
            "markers": [
                {
                    "markerType": "npc",
                    "name": "market-clerk",
                    "x": 64,
                    "y": 64,
                    "npcId": "market-clerk",
                    "point": True,
                }
            ]
        }
    )
    markers = suggest_markers(
        context=_ctx(requested_npcs=["market-clerk"]),
        llm=lambda _: fake,
    )

    assert markers[0]["width"] == 0
    assert markers[0]["height"] == 0
    assert markers[0].get("point") is True


def test_suggest_markers_rejects_non_json_response() -> None:
    with pytest.raises(MarkerSchemaError, match="JSON"):
        suggest_markers(
            context=_ctx(),
            llm=lambda _: "not json",
        )


def test_suggest_markers_prompt_mentions_map_dimensions_and_constraints() -> None:
    captured_prompts: list[str] = []

    def spy_llm(prompt: str) -> str:
        captured_prompts.append(prompt)
        return json.dumps({"markers": []})

    suggest_markers(
        context=_ctx(
            map_width=40,
            map_height=30,
            requested_npcs=["market-clerk", "wisdom-guy"],
            requested_transitions=[{"to": "town-center", "side": "right"}],
        ),
        llm=spy_llm,
    )

    assert len(captured_prompts) == 1
    prompt = captured_prompts[0]
    # Map dimensions must be in the prompt so the model picks sensible coords.
    assert "40" in prompt and "30" in prompt
    # Requested constraints must be echoed.
    assert "market-clerk" in prompt
    assert "town-center" in prompt


def test_suggest_markers_handles_empty_markers_response() -> None:
    # The LLM is allowed to decide no markers are needed — empty list is valid.
    markers = suggest_markers(
        context=_ctx(),
        llm=lambda _: json.dumps({"markers": []}),
    )
    assert markers == []


def test_suggest_markers_strips_extra_fields_from_llm_response() -> None:
    # LLM sometimes adds helpful-but-wrong fields. Validator must not crash
    # on extras; it just ignores them.
    fake = json.dumps(
        {
            "markers": [
                {
                    "markerType": "spawn",
                    "name": "origin",
                    "x": 0,
                    "y": 0,
                    "point": True,
                    "commentary": "looks good here",  # extra
                }
            ]
        }
    )
    markers = suggest_markers(context=_ctx(), llm=lambda _: fake)
    assert len(markers) == 1
    # The extra field is not in the output marker's properties.
    prop_names = {p["name"] for p in markers[0]["properties"]}
    assert "commentary" not in prop_names
