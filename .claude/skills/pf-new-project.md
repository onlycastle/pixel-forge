---
name: pf-new-project
description: Bootstrap a new pixel-forge project with its own palette and prose style guide. Use when the user says "create a new project" or when another skill reports "project not found".
---

# pf-new-project

Use when the user wants a new pixel-forge project or when another skill hits a "project not found" error.

## Flow

1. **Load `pixel-style-guide`** first if it isn't already loaded.

2. Ask the user for:
   - Project name (kebab-case, short). Default: what the user called it.
   - Tile size in pixels (default 16).

3. Shell out:

   ```
   python -m pixel_forge new-project --name <name> --tile-size <size>
   ```

   Parse the JSON for `project_dir` and `next_steps`.

4. Tell the user that two follow-up actions are **required** and one is **optional** before running a real generation:

   a. **Palette (required)** — `projects/<name>/style/palette.hex` ships with three placeholder colors and a warning comment. Ask the user if they want to (i) paste a palette inline, (ii) point at an existing `.hex` file, or (iii) leave the placeholder for now and iterate later. If (i), write the file. If (ii), copy it. If (iii), warn them that generations will be washed out until it's replaced.

   b. **Prose style guide (required)** — `projects/<name>/style/prose.md` has a placeholder. Ask the user if they want to write one now (offer to draft from a description of their game) or leave the placeholder for now.

   c. **Hero reference image (optional)** — A reference PNG is NOT required for pixel-forge to work. The scaffold's `project.toml` ships with `hero_reference` commented out in `[style]`. If the user has an existing pixel-art exemplar they want to anchor the style to, ask them to drop it at `projects/<name>/style/reference/hero.png` AND uncomment the `hero_reference` line in `project.toml`. If they don't have one, reassure them that prose + palette are enough to start, and they can add a reference later.

5. Print a clear "next step" line: once the palette and prose are set (with or without a hero reference), you can run `pf-generate-tile` against this project.

## Never do

- Never tell the user they MUST have a hero reference. It is optional.
- Never generate a hero reference image via the Gemini backend during this skill. It's the user's call what their first anchor looks like, and whether they want one at all.
- Never overwrite an existing project without asking.
