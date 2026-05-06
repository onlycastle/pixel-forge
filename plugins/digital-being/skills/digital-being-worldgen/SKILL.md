---
name: digital-being-worldgen
description: Generate Sunny Street world assets for Digital Beings, including map concepts, room layouts, streets, props, tiles, environmental objects, and scene mockups using imagegen while preserving game-ready packaging, prompt logs, and validation notes.
---

# Digital Being Worldgen

Use this skill when the user asks for Sunny Street maps, rooms, streets,
props, tiles, UI scene mockups, or environmental assets around a Digital Being.

## Core Rule

Generate assets as usable game inputs, not isolated concept art. Save outputs
under the run directory, record prompts, and define what still needs slicing,
tiling, transparency, or collision metadata before game integration.

Read `references/sunny-street-targets.md` before choosing a Sunny Street output
shape.

## Sunny Street World Targets

- `--sunny-type placeable`: static object or prop. Requires or infers
  `--footprint WxH`; exports through the Sunny Street placeables manifest.
- `--sunny-type ground-tileset`: terrain sheet. Requires `--sheet CxR`.
- `--sunny-type object-tileset`: object-layer tile sheet. Requires
  `--sheet CxR`.
- `--sunny-type map`: editable Sunny Street-compatible Tiled `.tmj` produced
  through `pf mapgen` / the Pixel Forge mapgen contract. Registered Sunny
  Street world patches are opt-in and require stricter validation.
- `--sunny-type concept-only`: scene or mood reference, not runtime-ready.

## Asset Routes

- Props or objects: use Codex native `imagegen`; prefer flat, readable
  silhouettes and consistent camera angle. For cutouts, use the `imagegen`
  chroma-key workflow, then copy the generated source from
  `$CODEX_HOME/generated_images/` into the run directory before packaging.
- Sunny Street placeables should match existing Sunny Street / Modern Farm
  32x32 singles. Prompt and post-process for lower detail density, flatter
  2-3 tone shading, thinner outlines, restrained texture, and readable
  silhouettes; raw imagegen outputs that look too high-detail should be
  simplified before sidecars are marked adapter-ready.
- Tiles: use `imagegen` for tile concepts or sheets; then slice and inspect
  seams before treating them as a tileset.
- Maps or rooms: use `pf mapgen` for runtime-shaped editable TMJ output. Use
  `imagegen` only for mood/layout references or missing visual assets, then feed
  the curated assets back into the mapgen flow.
- For maps with a Sunny Street target root, inspect `asset-inventory.json` and
  `asset-plan.json` before generating new art. Treat `coverage` entries marked
  `covered` as usable existing assets, `available` as assets that may be chosen
  by a later layout pass, and `gap` as candidates for new placeable or tileset
  generation.
- Scene mockups: use `imagegen` to establish composition and art direction,
  but record which elements are reference-only versus shippable assets.

## Output Layout

Within `out/digital-beings/<slug>/world/`, prefer:

- `props/`
- `tiles/`
- `maps/`
- `scene-mockups/`
- `contact-sheets/`

## Workflow

1. Identify the target use: prop, tile, map, scene mockup, or mixed pack.
2. Use `imagegen` with explicit intended use, camera angle, style, and
   constraints.
3. For Sunny Street / Modern Farm matching, include explicit prompt constraints:
   "lower detail density, flatter 2-3 tone shading, thinner outlines, match
   existing Sunny Street/Modern Farm 32x32 singles."
4. Save selected outputs into `world/` with descriptive filenames.
5. Record exact prompts and reference roles in `prompts.md`.
6. Add curation notes to `learnings.md`: what is usable, what needs cleanup,
   and what should not be used directly.
7. For any transparent or grid-based output, run the relevant local cleanup or
   slicing step before marking it game-ready.
8. For `--sunny-type map`, default to editable TMJ output. Use registered patch
   mode only when the Sunny Street world registry, Tiled project enums, and
   runtime texture preload/update tasks are part of the requested scope.
9. For `--sunny-type map`, do not jump straight from prompt to image generation:
   run inventory, read the asset plan, decide what existing assets cover, then
   generate only the gap assets that the plan identifies.

## Quality Gate

- Output dimensions and framing fit the intended game use.
- Props have clean silhouettes and enough padding.
- Sunny Street placeables do not look more detailed, glossy, or high-contrast
  than nearby existing farm props when viewed at the same tile scale.
- Tiles do not rely on perspective that breaks tiling.
- Maps are not runtime-ready unless they pass the Pixel Forge mapgen contract:
  `ground`, `object`, `collision`, `placeables`, and `markers` layers,
  `placeablesVisualOwner=runtime`, valid marker properties, and resolvable
  placeable manifest/collection identities.
- Generated images are saved in the workspace, not left only in the default
  image generation location.
