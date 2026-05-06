---
name: digital-being-assetgen
description: Generate Sunny Street Digital Being asset packs from a user prompt. Use when Codex is asked to create character concepts, sprite-ready identity art, props, tiles, maps, or complete Digital Being visual asset runs using the imagegen skill, pixel-sprite-pipeline when sprites are needed, and local runbook/validation artifacts.
---

# Digital Being Assetgen

Use this skill when the user says to make, create, generate, or iterate on
Digital Being assets for Sunny Street.

## Core Rule

This is an authoring skill, not a new engine backend. Use Codex's native
`imagegen` skill/tool for bitmap creation by default; do not fall back to the
OpenAI API/CLI path or require `OPENAI_API_KEY` unless the user explicitly asks
for that fallback. Use `pixel-sprite-pipeline` for sprite readiness, and the
local `pixel-forge` Digital Being contract for packaging and validation.

## Sunny Street Target Flags

When the asset is meant for Sunny Street, start by selecting a runtime target:

```text
digital-being-assetgen --sunny-type <target> --slug <slug> --prompt "<prompt>"
```

Valid `--sunny-type` values:

- `npc-premade`
- `player-farmer`
- `animal-livestock24`
- `placeable`
- `ground-tileset`
- `object-tileset`
- `map`
- `concept-only`

Read `references/sunny-street-targets.md` before claiming an asset is usable in
Sunny Street. If no target is provided, infer one and record the inference in
`prompts.md`; default character/NPC requests to `npc-premade`.

## Route By Asset Type

- Character identity or concept art: use `imagegen`, save into the run
  directory, and log the final prompt. Mark as `concept-only` unless it is
  promoted to a concrete Sunny Street target.
- Animated pixel sprites: use `digital-being-spritegen` with the selected
  `--sunny-type`.
- Props, tiles, room maps, streets, or scene mockups: use
  `digital-being-worldgen` with `placeable`, `ground-tileset`,
  `object-tileset`, or `map`.
- Prompt-driven maps: route through `pf mapgen` first and inspect the emitted
  `asset-plan.json`. Generate new bitmap assets only for `assetGaps`; do not
  duplicate existing Sunny Street placeables or tilesets already marked covered.
- Sunny runtime export: when the user asks for `--export-ready` and provides a
  Sunny Street repo root, run `pf being export-sunny --run-dir
  out/digital-beings/<slug> --to <sunny-street-root>` after validation. Use
  `--dry-run` first if the target repo is outside the current writable root.
- Existing run validation only: use `digital-being-validation`.

## Output Layout

Use `out/digital-beings/<slug>/` unless the user names another destination.

Recommended authoring layout:

- `source/` for generated reference images and raw model outputs
- `sprites/` for normalized sheets, contact sheets, GIF previews, and frames
- `world/` for maps, tiles, props, and scene concepts
- `plan.md`, `prompts.md`, `learnings.md` for runbook memory
- `capability-matrix.json` and `run-summary.json` for agent-readable state

## Workflow

1. Infer a slug from the user's request if one is not provided.
2. Select `--sunny-type` before generating. If the user asks for "Sunny Street
   usable", do not stay at `concept-only`.
3. Decide whether the request is character, sprite, world/map, prop, or mixed.
4. Use Codex native `imagegen` for each needed visual source. Project-bound
   images generated under `$CODEX_HOME/generated_images/` must be copied into
   the workspace before completion.
5. For sprite requests, hand off to `digital-being-spritegen` and follow
   `pixel-sprite-pipeline` for grid references, extraction, transparency,
   anchor normalization, contact sheets, and GIF previews.
6. For Sunny Street placeables, prompt and post-process toward existing
   Sunny Street / Modern Farm 32x32 singles: lower detail density, flatter
   2-3 tone shading, thinner outlines, readable silhouettes, and less
   high-frequency texture than raw imagegen tends to produce. Record any
   simplification pass in `learnings.md`.
7. Maintain `prompts.md` with the exact final prompts, target flag, and
   reference roles.
8. Maintain `learnings.md` with concrete gotchas, rejected outputs, and useful
   curation notes.
9. Run `digital-being-validation` when a run directory contains the required
   contract files. For early concept-only work, clearly mark validation as not
   applicable yet.
10. If `--export-ready` is requested, run `pf being export-sunny` for the run
   directory. For `placeable` assets this copies PNGs into
   `public/placeables/generated/` and updates both
   `src/phaser/data/placeable-asset-manifest.json` and
   `public/maps/placeables-collection.tsj`; only then call the placeable
   runtime-ready. Character and tileset targets may be copied/exported but
   remain subject to Sunny Street's current static sprite/map registries.
11. For Sunny Street TMJ editor visibility, use the target repo's existing
   category labels exactly. Do not invent title-case variants such as
   `Props And Buildings` when the editor category is `Props and Buildings`.
   After export, verify the target editor discovery path sees the asset under a
   visible category and that category aliases did not create duplicate dropdown
   entries.
12. When revising art that has already been exported and may already be placed
   in a TMJ map, always dry-run export first and inspect texture keys / tile IDs.
   The exporter uses content-hash texture keys, so a repaint can become a new
   placeable entry. If the intent is to update existing placements, preserve the
   manifest and collection entries and overwrite the existing generated PNG
   path instead of registering a duplicate.

## Constraints

- Do not route creative generation through `pixel_forge being generate`; that
  CLI backend is currently `stub` only.
- Do not block ordinary image generation on `OPENAI_API_KEY`; Codex native
  `imagegen` is the default path for bitmap sources.
- Do not create one-off images that are not saved into the project when the
  asset is meant for Sunny Street.
- Do not treat a good-looking raw spritesheet as game-ready. Sprite outputs
  require post-processing and preview review.
- Do not treat map concept art as a Sunny Street map. `--sunny-type map`
  should route through `pf mapgen` so the output has the Sunny Street TMJ
  layers, marker properties, placeable identities, and validation report.
- Do not claim `runtime-ready` for a generated placeable until
  `pf being export-sunny` has registered the generated PNG in both the runtime
  manifest and the `placeables-collection.tsj` Tiled collection.
