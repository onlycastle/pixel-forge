---
name: digital-being-spritegen
description: Create game-ready Sunny Street Digital Being pixel sprite assets by combining imagegen for identity and raw spritesheet generation with pixel-sprite-pipeline for grids, pose extraction, per-frame cleanup, anchor normalization, contact sheets, and GIF previews.
---

# Digital Being Spritegen

Use this skill when the requested output is a character sprite, animation sheet,
walk cycle, idle cycle, action cycle, or game-ready pixel animation.

## Required Skill Routing

- Use `imagegen` for identity art and raw visual generation.
- Use `pixel-sprite-pipeline` for checker grids, pose extraction,
  transparency cleanup, normalized assembly, contact sheets, and GIF previews.
- Use `digital-being-runbook` to record prompts and curation choices.
- Read `references/sunny-street-targets.md` when the user requests Sunny Street
  runtime compatibility.

## Sunny Street Sprite Targets

- `--sunny-type npc-premade`: `32x64` frames, `56` columns, top rows
  preview/idle/walk, 6 frames per direction in `right, up, left, down` order.
- `--sunny-type player-farmer`: `32x64` frames, `24` columns, top rows
  preview/idle/walk.
- `--sunny-type animal-livestock24`: `32x32` frames, `24` columns, 4 rows.
- `--sunny-type concept-only`: identity or non-runtime preview only.

If the user asks for a Sunny Street NPC/Digital Being and gives no target,
default to `npc-premade`. Do not call a `128x128` custom sheet runtime-ready
unless Sunny Street has a loader for that shape.

## Workflow

1. Create or identify `out/digital-beings/<slug>/`.
2. Generate a 1024x1024 checker reference grid with
   `pixel-sprite-pipeline` tooling.
3. Use `imagegen` to create the character identity reference in pixel art
   style. Save it under `source/identity.png` or the run's canonical
   `identity.png` when final.
4. Generate a raw spritesheet using the identity image plus a fixed sheet grid
   reference for the selected `--sunny-type`. Keep frame size, rows, columns,
   direction order, and animation name in `prompts.md`.
5. Do not slice raw cells directly. Extract foreground pose components from
   the full sheet with `pixel-sprite-pipeline`.
6. Remove backgrounds per crop. For simple opaque subjects, use the `imagegen`
   chroma-key path and local removal guidance; use external/native
   transparency only when the user explicitly approves that route.
7. Normalize cleaned frames onto fixed-size cells with shared center X and
   bottom/contact Y.
8. Assemble final sheet, labeled contact sheet, and preview GIF.
9. Curate frame order by animation read, then record the chosen order in
   `learnings.md`.
10. Run validation when the output is promoted into a full Digital Being run.

## Quality Gate

Do not call a sprite ready until:

- transparent background is correct for each frame
- contact point or feet share the same bottom Y
- center drift is intentional or corrected
- no neighboring-frame bleed remains
- no limbs, hair, hat, or tools are cropped
- contact sheet labels match the final frame order
- GIF reads correctly at expected in-game size
- sheet dimensions match the selected Sunny Street target
