---
name: digital-being-init
description: Start a pixel-forge Digital Being task using the local offline/stub-safe workflow. Use when Codex needs to initialize a Sunny Street Digital Being run, confirm canonical schema locations, avoid live providers, and prepare the runbook artifacts before generation.
---

# Digital Being Init

Use this skill to start a Digital Being task inside `pixel-forge`.

## Rules

- Use the local `pixel-forge` engine as the source of truth.
- Do not create new schema definitions.
- Do not call live APIs or providers in v1.
- Prefer `pf being generate --backend stub` or the equivalent module command
  for a deterministic first run.

## Canonical Touchpoints

- `tools/pixel_forge/schemas/being.py`
- `tools/pixel_forge/digital_being.py`
- `tools/pixel_forge/sprite_pipeline.py`
- `tools/pixel_forge/cli.py`

## Workflow

1. Clarify slug and prompt.
2. Confirm the offline/stub path unless the user explicitly asks for a later
   live-provider phase.
3. Create or inspect the runbook artifacts:
   - `plan.md`
   - `prompts.md`
   - `learnings.md`
   - `capability-matrix.json`
   - `run-summary.json`
4. Generate or validate the run using local tools.
5. Hand off to `digital-being-validation` before claiming the run is usable.
