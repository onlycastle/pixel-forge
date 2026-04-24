---
name: pf-compose-map
description: Compose a full Tiled .tmj map in one shot from a spec TOML — ground tileset + object tileset + placeables + LLM-suggested markers. Use when the user wants a whole map generated at once, not individual assets.
---

# pf-compose-map

The composer reads a map spec and orchestrates generator calls for every asset the map needs, then emits a real Tiled `.tmj` skeleton plus a `map.json` summary. Markers (NPCs, transitions, spawns) can be proposed by Gemini's text model when the spec opts in.

## Spec format

A map spec is a TOML file, by convention at `projects/<proj>/maps/<name>.toml`:

```toml
[map]
name = "beach-town"
tile_size = 32
width = 40
height = 30

[map.ground]
prompt = "warm beach sand and worn cobblestone path mix"
sheet = { cols = 4, rows = 4 }

[map.object]
prompt = "small driftwood, seaweed clumps, beach pebbles"
sheet = { cols = 3, rows = 3 }

[[map.placeables]]
prompt = "weathered wooden rowboat"
footprint = { w = 3, h = 2 }
count = 2

[[map.placeables]]
prompt = "lighthouse base, two stories"
footprint = { w = 2, h = 4 }
count = 1

[map.markers]
suggest = true
npcs = ["market-clerk"]
transitions = [{ to = "town-center", side = "right" }]
```

Rules:
- `tile_size` in the spec must match the project's `project.toml` `tile_size`.
- `[map.object]` is optional — skip the section entirely if the map has no object layer.
- Placeable `count > 1` places multiple copies of the same asset on a deterministic grid.
- `markers.suggest = true` triggers a Gemini text-model call to propose markers. Set `false` to get an empty markers layer you can fill manually in the editor.

## Flow

1. Clarify scope with the user: which project, what kind of map, any must-have NPCs or transitions. Offer to draft the spec inline.

2. Write the spec at `projects/<proj>/maps/<name>.toml`. Show it to the user and confirm before composing — composing runs many generate calls and costs real API time.

3. Shell out:

   ```
   python -m pixel_forge compose \
     --project <proj> \
     --spec projects/<proj>/maps/<name>.toml
   ```

   Parse the JSON reply for `tmj`, `summary`, and `map_dir`.

4. Report what was produced: N tilesets, M placeables, K markers. Tell the user the `.tmj` path and the summary JSON path.

5. Offer the export step. The map only lands in sunny-street when explicitly exported:

   ```
   python -m pixel_forge export \
     --project <proj> \
     --adapter sunny-street \
     --to /path/to/sunny-street \
     --map <name>
   ```

   This copies the tileset PNGs, appends every placeable to `placeables-collection.tsj` + `placeable-asset-manifest.json`, and rewrites firstgids so the map slots into sunny-street without colliding with existing tilesets.

## Re-composing a map

Compose is not idempotent on the generator side — running it twice creates two sets of timestamped variants in the project's `out/` directories. Only the latest compose run is referenced from the `.tmj`. This is intentional: the user reviews the newest output, and old variants stay around in case they want to roll back by hand.

## Never do

- Never compose without showing the spec TOML to the user first.
- Never override a spec's `tile_size` silently — it must match the project.
- Never skip the export step's confirmation if the target repo isn't a tmp path.
- Never request marker suggestions on a spec that sets `suggest = false` — the composer will error.
