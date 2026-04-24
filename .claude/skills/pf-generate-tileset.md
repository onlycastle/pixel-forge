---
name: pf-generate-tileset
description: Generate a grid-aligned tileset sheet (ground or object) for a pixel-forge project. Use when the user wants multiple cells of terrain or object tiles in one PNG. For a single individual object, use pf-generate-placeable instead.
---

# pf-generate-tileset

Two sub-kinds share this skill:

- **`ground-tileset`** — seamless terrain cells (grass, sand, cobblestone, water). Must tile cleanly at every tile-size boundary. Destined for the `ground` tilelayer of a Tiled map.
- **`object-tileset`** — per-cell object tiles with transparent background (rocks, bushes, detail props grouped as a sheet). Destined for the `object` tilelayer.

Both produce a single PNG of size `(cols × tile_size) × (rows × tile_size)` plus a `<slug>.meta.json` sidecar that declares the sheet shape and layer target. The sidecar is written automatically by the generator — you don't manage it yourself.

## Flow

1. **Load `pixel-style-guide`** if not loaded.

2. Determine intent:
   - What terrain or object sheet does the user want?
   - Ground or object? (If unclear, ask.)
   - Sheet dimensions: how many cells wide × tall? Default `4x4` for ground if the user doesn't say; ask for object tilesets since intent varies more.
   - Which project.

3. Confirm before generating: "I'll generate 4 variants of a 4×4 warm beach sand ground tileset for sunny-street, ok?"

4. Shell out:

   ```
   python -m pixel_forge generate \
     --project <name> \
     --kind ground-tileset \
     --sheet 4x4 \
     --prompt "<refined prompt>" \
     --variants 4
   ```

   Or for an object tileset:

   ```
   python -m pixel_forge generate \
     --project <name> \
     --kind object-tileset \
     --sheet 3x3 \
     --prompt "<refined prompt>" \
     --variants 4
   ```

   Prompt refinement rules:
   - Keep the user's intent verbatim at the start.
   - For ground tilesets append `, seamless variations` so the model produces swappable cells.
   - Do not inject style words — the project's prose file already does that.

5. Parse the JSON summary. Each variant entry has both `path` (PNG) and `sidecar_path` (meta.json). Grid validation runs for tileset kinds and a failing `validation.grid` drops that variant from the candidate set.

6. Follow the N-of-K review loop from `pixel-style-guide`: Read each passing variant, describe what differs, present numbered list.

7. On user pick, propose a canonical kebab-case name and confirm before promoting.

## Never do

- Never run more than one generation call per turn unless explicitly asked.
- Never promote without user confirmation of the canonical name.
- Never inject style language into the prompt.
- Never use this skill for a single one-off object that doesn't tile — that's a placeable, use `pf-generate-placeable`.
