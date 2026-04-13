---
name: pf-generate-character
description: Generate a single-frame idle-pose character sprite for a pixel-forge project. Use when the user asks for a character, NPC, or person sprite. Multi-frame walk cycles are explicitly out of scope and will be rejected.
---

# pf-generate-character

v1 scope: one frame, front-facing idle pose, anchored to the project's hero reference for identity. Multi-frame walk cycles and multi-direction sheets are v2 and must be declined.

## Flow

1. **Load `pixel-style-guide`** if not loaded.

2. Determine intent:
   - Character description (age, clothing era, role, vibe). Example: "1974 hardware store clerk, mid-40s, apron, kind eyes."
   - Which project.

3. **If the user asks for walk cycles, multiple directions, or animation frames, decline this turn.** Say: "v1 only generates a single idle frame. Multi-frame character generation is planned for v2 — I don't have the tools for it yet." Offer to generate the idle frame instead.

4. Confirm intent: "I'll generate 4 variants of a front-facing idle sprite of a 1974 hardware store clerk for sunny-street, ok?" Wait.

5. Shell out:

   ```
   python -m pixel_forge generate \
     --project <name> \
     --kind character \
     --prompt "<character description>, standing, facing viewer, idle pose, full body, transparent background" \
     --variants 4
   ```

6. Parse, filter, Read, describe, present, promote — same N-of-K loop as `pf-generate-tile`.

7. Canonical name should be the character's role in kebab-case: `hardware-store-clerk.png`, `village-elder.png`.

## Never do

- Never produce walk cycles in v1.
- Never generate multi-character scenes — one sprite per call.
- Never override the hero reference — it's the identity anchor across all characters in a project. If the user wants characters that don't match the hero reference's style, they need a different project.
