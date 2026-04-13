---
name: pixel-style-guide
description: Anchor skill for pixel-forge. Use when generating any pixel asset (tile, prop, or character) via pf-generate-* skills. Loads project config, builds layered prompts, runs the N-of-K loop.
---

# pixel-style-guide

You are working inside a `pixel-forge` repo. Every pixel asset generation flows through this skill. Load it first, then the specific `pf-generate-*` skill for the task.

## How projects work

Projects live at `projects/<name>/`. Each has:

- `project.toml` — config (tile size, backend, validation rules)
- `style/palette.hex` — one hex color per line, the **only** colors allowed in output
- `style/prose.md` — the human-readable style guide, always prepended to generation prompts
- `style/reference/hero.png` — **optional** canonical visual anchor, attached to generation requests when the `hero_reference` key is set in `project.toml`. Projects without one still work; cross-variant consistency is weaker.
- `style/reference/extras/*.png` — optional additional references
- `out/{tiles,props,characters,maps}/` — where generated assets land; `_rejected/` holds variants the user didn't pick

Before running any generation, confirm the target project exists. If it doesn't, say so and suggest running `pf-new-project`.

## The generation contract

Palette and prose are always loaded into every generation — no exceptions. The hero reference is loaded when the project declares one. This is enforced by `tools/pixel_forge/generate.py` — you never build the prompt yourself, you just call the CLI.

## The N-of-K loop

1. Shell out to the CLI:

   ```
   python -m pixel_forge generate \
     --project <name> \
     --kind <tile|prop|character> \
     --prompt "<user intent>" \
     --variants 4
   ```

2. Parse the JSON output. It looks like:

   ```json
   {
     "variants": [
       {"path": "...", "validation": {"palette": "pass", "grid": "pass", "alpha": "pass"}, "passed": true},
       ...
     ],
     "errors": []
   }
   ```

3. **Drop variants where `passed: false`.** Tell the user how many failed and why (e.g. "v3 failed palette check: 47 off-palette pixels"). Do not ask the user to pick from a failed variant.

4. **For each passed variant, use the Read tool on the PNG file** to view it. Then write a one-line description of what you see. Focus on what makes each variant different from the others (color balance, line weight, composition, detail).

5. Present the passing variants to the user as a numbered list with your descriptions. Ask which one they want to promote to canonical.

6. When the user picks a variant (by number or by saying "variant 2"), shell out:

   ```
   python -m pixel_forge promote \
     --path <chosen variant path> \
     --canonical-name <a short kebab-case name you propose from the prompt>
   ```

   Confirm the canonical name with the user before running promote. Say "I'll promote this as `mossy-grass.png`, ok?" and wait.

## Error handling

If the CLI exits non-zero, read stderr as JSON and tell the user in plain English what went wrong. Common cases:

- `GEMINI_API_KEY is not set` — tell them to copy `.env.example` to `.env` and fill in their key.
- `project not found` — offer to run `pf-new-project`.
- `hero reference missing` — tell them which file path is expected, and ask them to drop an image there.

If **all** variants fail validation, do not keep retrying with the same prompt. Surface the failure details and ask the user if they want to (a) change the prompt, (b) loosen validation in `project.toml`, or (c) see the rejected images anyway.

## Never do

- Never fabricate tile IDs, marker IDs, or TMJ content. pixel-forge does not touch TMJ — that's a future adapter's job.
- Never edit the palette, prose, or hero reference on the user's behalf without asking.
- Never skip the `passed: true` filter. Bad variants are bad; don't rationalize them.
