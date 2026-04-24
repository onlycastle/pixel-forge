"""Phase 2 — map composer tests.

The composer orchestrates per-kind generate calls and emits a real Tiled
`.tmj` skeleton. Tests use the StubBackend so no model calls are made.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from pixel_forge.assets import Footprint, Sheet
from pixel_forge.backends.stub import StubBackend
from pixel_forge.compose import (
    ComposeError,
    MapSpec,
    PlaceableSpec,
    TilesetLayerSpec,
    allocate_firstgids,
    compose,
    load_spec,
)


FIXTURE_SPEC = Path("tests/fixtures/maps/tiny-beach.toml")


def _write_compose_project(tmp_path: Path) -> Path:
    project_dir = tmp_path / "compose-proj"
    (project_dir / "style" / "reference").mkdir(parents=True)
    (project_dir / "style" / "palette.hex").write_text(
        Path("tests/fixtures/palette-4.hex").read_text()
    )
    (project_dir / "style" / "prose.md").write_text("compose test style.\n")
    (project_dir / "style" / "reference" / "hero.png").write_bytes(
        Path("tests/fixtures/good-tile.png").read_bytes()
    )
    (project_dir / "project.toml").write_text(
        """
[project]
name = "compose-proj"
tile_size = 16
output_root = "out"

[style]
palette = "style/palette.hex"
prose = "style/prose.md"
hero_reference = "style/reference/hero.png"
extra_references = []

[generation]
backend = "stub"
variants_per_prompt = 1

[validation]
max_off_palette_pixels = 0
"""
    )
    return project_dir


def test_load_spec_parses_tiny_beach_fixture() -> None:
    spec = load_spec(FIXTURE_SPEC)

    assert spec.name == "tiny-beach"
    assert spec.tile_size == 16
    assert (spec.width, spec.height) == (8, 6)
    assert spec.ground.prompt == "warm beach sand"
    assert spec.ground.sheet == Sheet(cols=1, rows=1)
    assert spec.object_layer is not None
    assert spec.object_layer.prompt == "beach rocks and driftwood"
    assert [p.prompt for p in spec.placeables] == [
        "weathered wooden rowboat",
        "lighthouse base",
    ]
    assert spec.placeables[0].count == 2
    assert spec.placeables[0].footprint == Footprint(w=2, h=1)
    assert spec.placeables[1].footprint == Footprint(w=1, h=2)


def test_load_spec_rejects_missing_name(tmp_path: Path) -> None:
    bad = tmp_path / "bad.toml"
    bad.write_text("[map]\ntile_size = 16\nwidth = 4\nheight = 4\n")
    with pytest.raises(ComposeError, match="name"):
        load_spec(bad)


def test_allocate_firstgids_no_overlap() -> None:
    # Two image-tilesets of 4 and 9 cells starting at base 200000.
    allocs = allocate_firstgids(
        tileset_cell_counts=[4, 9],
        base=200000,
    )
    assert allocs == [200000, 200004]


def test_allocate_firstgids_empty_returns_empty() -> None:
    assert allocate_firstgids([], base=200000) == []


def test_compose_emits_tmj_skeleton_at_expected_path(tmp_path: Path) -> None:
    project_dir = _write_compose_project(tmp_path)
    backend = StubBackend(
        template_path=Path("tests/fixtures/good-tile.png").resolve(),
        output_dir=project_dir / "out" / "_raw",
    )

    result = compose(FIXTURE_SPEC, project_root=project_dir, backend=backend)

    tmj_path = project_dir / "out" / "maps" / "tiny-beach" / "map.tmj"
    assert tmj_path.exists()
    assert result.tmj_path == tmj_path

    # Must round-trip through json.load.
    tmj = json.loads(tmj_path.read_text())
    assert tmj["type"] == "map"
    assert tmj["orientation"] == "orthogonal"
    assert tmj["infinite"] is False
    assert tmj["width"] == 8
    assert tmj["height"] == 6
    assert tmj["tilewidth"] == 16
    assert tmj["tileheight"] == 16


def test_compose_tmj_has_four_layers_named_correctly(tmp_path: Path) -> None:
    project_dir = _write_compose_project(tmp_path)
    backend = StubBackend(
        template_path=Path("tests/fixtures/good-tile.png").resolve(),
        output_dir=project_dir / "out" / "_raw",
    )
    compose(FIXTURE_SPEC, project_root=project_dir, backend=backend)

    tmj_path = project_dir / "out" / "maps" / "tiny-beach" / "map.tmj"
    tmj = json.loads(tmj_path.read_text())

    layer_names = [l["name"] for l in tmj["layers"]]
    assert layer_names == ["ground", "object", "placeables", "markers"]

    types = {l["name"]: l["type"] for l in tmj["layers"]}
    assert types == {
        "ground": "tilelayer",
        "object": "tilelayer",
        "placeables": "objectgroup",
        "markers": "objectgroup",
    }


def test_compose_ground_layer_filled_with_ground_gid(tmp_path: Path) -> None:
    project_dir = _write_compose_project(tmp_path)
    backend = StubBackend(
        template_path=Path("tests/fixtures/good-tile.png").resolve(),
        output_dir=project_dir / "out" / "_raw",
    )
    compose(FIXTURE_SPEC, project_root=project_dir, backend=backend)

    tmj = json.loads(
        (project_dir / "out" / "maps" / "tiny-beach" / "map.tmj").read_text()
    )
    ground_layer = next(l for l in tmj["layers"] if l["name"] == "ground")
    assert ground_layer["type"] == "tilelayer"
    assert len(ground_layer["data"]) == 8 * 6
    # All cells point at the first ground tile (firstgid 200000 + 0 offset).
    ground_tileset = next(
        t for t in tmj["tilesets"] if t.get("name", "").endswith("-ground")
    )
    first_cell_gid = ground_tileset["firstgid"]
    assert all(cell == first_cell_gid for cell in ground_layer["data"])


def test_compose_placeables_objectgroup_has_one_object_per_count(tmp_path: Path) -> None:
    project_dir = _write_compose_project(tmp_path)
    backend = StubBackend(
        template_path=Path("tests/fixtures/good-tile.png").resolve(),
        output_dir=project_dir / "out" / "_raw",
    )
    compose(FIXTURE_SPEC, project_root=project_dir, backend=backend)

    tmj = json.loads(
        (project_dir / "out" / "maps" / "tiny-beach" / "map.tmj").read_text()
    )
    pl_layer = next(l for l in tmj["layers"] if l["name"] == "placeables")
    # 2 rowboats + 1 lighthouse = 3 objects
    assert len(pl_layer["objects"]) == 3

    names = sorted(o["name"] for o in pl_layer["objects"])
    assert names == sorted(
        ["weathered wooden rowboat", "weathered wooden rowboat", "lighthouse base"]
    )

    # Every object must reference a gid in the placeables-collection range.
    placeables_ts = next(
        t for t in tmj["tilesets"] if t.get("name") == "placeables-collection"
    )
    pc_first = placeables_ts["firstgid"]
    pc_count = placeables_ts["tilecount"]
    for obj in pl_layer["objects"]:
        assert pc_first <= obj["gid"] < pc_first + pc_count


def test_compose_emits_sidecar_summary_map_json(tmp_path: Path) -> None:
    project_dir = _write_compose_project(tmp_path)
    backend = StubBackend(
        template_path=Path("tests/fixtures/good-tile.png").resolve(),
        output_dir=project_dir / "out" / "_raw",
    )
    compose(FIXTURE_SPEC, project_root=project_dir, backend=backend)

    summary_path = project_dir / "out" / "maps" / "tiny-beach" / "map.json"
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text())
    assert summary["spec_name"] == "tiny-beach"
    assert "prompts" in summary
    assert "assets" in summary
    # At minimum: ground + object tilesets + placeable count entries.
    assert len(summary["assets"]) >= 3


def test_compose_invokes_marker_llm_when_spec_requests_suggestions(tmp_path: Path) -> None:
    project_dir = _write_compose_project(tmp_path)
    backend = StubBackend(
        template_path=Path("tests/fixtures/good-tile.png").resolve(),
        output_dir=project_dir / "out" / "_raw",
    )

    # Point at a spec that sets markers.suggest = true with a required transition.
    spec_src = FIXTURE_SPEC.read_text().replace(
        "suggest = false", 'suggest = true\nnpcs = ["market-clerk"]'
    )
    spec_path = tmp_path / "tiny-beach-with-markers.toml"
    spec_path.write_text(spec_src)

    captured: list[str] = []

    def fake_llm(prompt: str) -> str:
        captured.append(prompt)
        return json.dumps(
            {
                "markers": [
                    {
                        "markerType": "npc",
                        "name": "market-clerk",
                        "x": 64,
                        "y": 32,
                        "point": True,
                        "npcId": "market-clerk",
                    }
                ]
            }
        )

    compose(
        spec_path,
        project_root=project_dir,
        backend=backend,
        text_llm=fake_llm,
    )

    # LLM was called exactly once.
    assert len(captured) == 1
    assert "tiny-beach" in captured[0]
    assert "market-clerk" in captured[0]

    tmj = json.loads(
        (project_dir / "out" / "maps" / "tiny-beach" / "map.tmj").read_text()
    )
    markers_layer = next(l for l in tmj["layers"] if l["name"] == "markers")
    assert len(markers_layer["objects"]) == 1
    obj = markers_layer["objects"][0]
    assert obj["name"] == "market-clerk"
    props = {p["name"]: p["value"] for p in obj["properties"]}
    assert props["markerType"] == "npc"
    assert props["npcId"] == "market-clerk"


def test_compose_errors_when_markers_requested_without_llm(tmp_path: Path) -> None:
    project_dir = _write_compose_project(tmp_path)
    backend = StubBackend(
        template_path=Path("tests/fixtures/good-tile.png").resolve(),
        output_dir=project_dir / "out" / "_raw",
    )

    spec_src = FIXTURE_SPEC.read_text().replace("suggest = false", "suggest = true")
    spec_path = tmp_path / "needs-llm.toml"
    spec_path.write_text(spec_src)

    with pytest.raises(ComposeError, match="text_llm"):
        compose(spec_path, project_root=project_dir, backend=backend)


def test_compose_placeables_have_collection_tileset_entries(tmp_path: Path) -> None:
    project_dir = _write_compose_project(tmp_path)
    backend = StubBackend(
        template_path=Path("tests/fixtures/good-tile.png").resolve(),
        output_dir=project_dir / "out" / "_raw",
    )
    compose(FIXTURE_SPEC, project_root=project_dir, backend=backend)

    tmj = json.loads(
        (project_dir / "out" / "maps" / "tiny-beach" / "map.tmj").read_text()
    )
    placeables_ts = next(
        t for t in tmj["tilesets"] if t.get("name") == "placeables-collection"
    )
    # Collection tilesets: columns == 0, tiles[] is the authoritative list.
    assert placeables_ts["columns"] == 0
    assert "tiles" in placeables_ts
    # Two unique placeable PROMPTS (rowboat + lighthouse) → we can dedupe by
    # prompt, or keep a separate entry per generated variant. The test just
    # pins the minimum: at least one tile entry per unique prompt.
    prompts_in_collection = {
        Path(t["image"]).stem for t in placeables_ts["tiles"]
    }
    assert len(prompts_in_collection) >= 2
