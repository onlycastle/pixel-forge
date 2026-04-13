---
name: pf-generate-tile
description: Generate a pixel tile or prop for a pixel-forge project. Use when the user says "generate a tile", "generate a prop", or similar requests for single static pixel assets.
---

# pf-generate-tile

Use for both tiles (grid-constrained) and props (free-form). One skill, one `--kind` flag.

## Flow

1. **Load `pixel-style-guide`** if not loaded.

2. Determine intent:
   - What does the user want? (e.g. "mossy forest floor", "crab trap", "weathered fence post")
   - Is it a **tile** (must be tileable, fits the grid) or a **prop** (free-form object with transparent bg)?
   - Which project? If the user doesn't say, ask. Do not assume sunny-street.

3. Confirm with the user before generating: "I'll generate 4 variants of a mossy forest floor tile for sunny-street, ok?" Wait for confirmation.

4. Shell out:

   ```
   python -m pixel_forge generate \
     --project <name> \
     --kind <tile|prop> \
     --prompt "<refined prompt>" \
     --variants 4
   ```

   Prompt refinement rules:
   - Keep the user's intent word-for-word at the start of the prompt.
   - Append `, seamless` for tiles if they should tile horizontally/vertically.
   - Append `, centered, transparent background` for props.
   - Do not inject style words — the prose style guide already does that.

5. Parse JSON. Follow the N-of-K loop from `pixel-style-guide`:
   - Drop failed variants, report how many and why.
   - Use Read tool on each passing variant.
   - Describe each in one line, focused on what differs between them.
   - Present numbered list.

6. On user pick, propose a canonical kebab-case name derived from the prompt. Example: `mossy forest floor` → `mossy-forest-floor`. Confirm with user, then promote.

## If all variants fail

Say so in plain English. Show the failure reasons from the JSON. Offer three options:
- Retry with a modified prompt
- Temporarily loosen `max_off_palette_pixels` in `project.toml` for this session
- Show the rejected images anyway (the user can still Read them)

Do NOT silently retry. Every retry costs real API calls.

## Never do

- Never run more than one generation call per user turn unless the user explicitly asks for another batch.
- Never promote a variant without user confirmation of the canonical name.
- Never inject style descriptions into the prompt — the project's prose file is the single source of style truth.
