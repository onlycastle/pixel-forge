---
name: pf-generate-placeable
description: Generate a single multi-tile stamp (building, prop, vehicle, decor) for a pixel-forge project. Use when the user wants ONE object that will be placed individually on a map, not a grid sheet of tiles. For grid-aligned terrain sheets use pf-generate-tileset.
---

# pf-generate-placeable

A placeable is a single PNG destined for the `placeables` objectgroup of a Tiled map. It has a **footprint** (how many tiles wide × tall it occupies) and an **anchor** (default `bottom-center`, so tall stamps sit correctly on the ground row). Every placeable also gets a `<slug>.meta.json` sidecar declaring its kind, layer target, footprint, and anchor. The sidecar is auto-written by the generator — you don't manage it.

## Flow

1. **Load `pixel-style-guide`** if not loaded.

2. Determine intent:
   - What object does the user want? (e.g. "weathered wooden rowboat", "2-story lighthouse base")
   - **Footprint**: how many tiles should it occupy? Ask if the user hasn't said. Typical examples:
     - A crate, sign, or small prop: 1×1
     - A cart or boat: 2×1 or 3×2
     - A barn or lighthouse: 2×3, 3×4, or larger
   - Which project.

3. Confirm before generating: "I'll generate 4 variants of a 2×1 weathered wooden rowboat for sunny-street, ok?"

4. Shell out:

   ```
   python -m pixel_forge generate \
     --project <name> \
     --kind placeable \
     --footprint 2x1 \
     --prompt "<refined prompt>" \
     --variants 4
   ```

   Footprint is strongly recommended. If you omit it, the generator will infer one from the final PNG dimensions via `ceil(px / tile_size)` — which is fine for truly generic props, but gives better bounds when declared upfront.

   Prompt refinement rules:
   - Keep the user's intent verbatim at the start.
   - Append `, side view, centered, transparent background` if the user hasn't described an angle.
   - Do not inject style words — the project's prose file already does that.

5. Parse the JSON summary. Grid validation is skipped for placeables — failures here are palette/alpha issues.

6. N-of-K review loop from `pixel-style-guide`: Read each, describe differences, present numbered list.

7. On user pick, propose a canonical kebab-case name and confirm before promoting.

## After promoting

Placeables in `out/placeables/` can later be:
- Referenced from a map composed via `pf-compose-map`
- Exported into sunny-street via `python -m pixel_forge export --project <name> --adapter sunny-street --to <repo>`

The export step copies the PNG to `public/placeables/generated/`, appends an entry to `placeables-collection.tsj`, and registers the `textureKey` in `placeable-asset-manifest.json`.

## Never do

- Never run more than one generation call per turn unless explicitly asked.
- Never promote without user confirmation of the canonical name.
- Never use this skill for a seamless ground tile — that's `pf-generate-tileset`.
- Never declare an absurd footprint (anything over 16×16 tiles is almost certainly wrong).
