---
name: pf-new-project
description: Bootstrap a new pixel-forge project with its own palette, prose style guide, and hero reference. Use when the user says "create a new project" or when another skill reports "project not found".
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

4. Tell the user that three follow-up actions are required before generation will work:

   a. **Palette** — `projects/<name>/style/palette.hex` now has three placeholder colors. Ask the user if they want to (i) paste a palette inline, (ii) point at an existing `.hex` file, or (iii) leave the placeholder for now and iterate later. If (i), write the file. If (ii), copy it. If (iii), warn them that generations will be washed out until it's replaced.

   b. **Prose style guide** — `projects/<name>/style/prose.md` has a placeholder. Ask the user if they want to write one now (offer to draft from a description of their game) or leave the placeholder for now.

   c. **Hero reference image** — `projects/<name>/style/reference/hero.png` does not exist. The Gemini backend will fail until it does. Ask the user to drop an existing image there or to generate one later with a deliberately simple first prompt using a different reference (the palette fixtures work as a bootstrap).

5. Print a clear "next step" line: once all three are set, you can run `pf-generate-tile` (or the others) against this project.

## Never do

- Never generate a hero reference image via the Gemini backend during this skill. It's the user's call what their first anchor looks like.
- Never overwrite an existing project without asking.
