# Digital Being Plugin

Project-local Codex skills for Sunny Street Digital Being asset authoring,
runbooks, and offline validation in `pixel-forge`.

This plugin is intentionally not a second asset engine. The canonical Digital
Being contracts and sprite processing live in the main `pixel-forge` package.
This plugin provides:

- image-generation runbooks
- sprite-generation runbooks
- world/map/prop generation runbooks
- workflow skills
- contract notes
- a minimal fixture
- offline validation scripts
- pytest coverage for the plugin pack

## Skills

- `digital-being-init`: start a local, stub-safe Digital Being task.
- `digital-being-assetgen`: turn a user prompt into a generated Digital Being
  asset run using `imagegen`, then package the outputs. Use
  `--sunny-type <target>` for Sunny Street runtime targets.
- `digital-being-spritegen`: generate character identity and animation assets
  using `imagegen` plus `pixel-sprite-pipeline`.
- `digital-being-worldgen`: generate Sunny Street maps, props, tiles, and scene
  concepts as game-ready asset packs.
- `digital-being-runbook`: maintain `plan.md`, `prompts.md`, `learnings.md`,
  `capability-matrix.json`, and `run-summary.json`.
- `digital-being-validation`: validate and summarize an existing run directory.

## Sunny Street Targets

Use `digital-being-assetgen --sunny-type <target>` when an asset should be
usable in Sunny Street:

- `npc-premade`
- `player-farmer`
- `animal-livestock24`
- `placeable`
- `ground-tileset`
- `object-tileset`
- `map`
- `concept-only`

Details live in `references/sunny-street-targets.md`.

## Sharing And Registration

This folder is the plugin. Each workflow is a skill markdown file under
`skills/<skill-name>/SKILL.md`, and `.codex-plugin/plugin.json` tells Codex
where to find those skills.

Recommended team setup:

1. Commit `plugins/digital-being/` with the `pixel-forge` repo.
2. Ask teammates to pull the latest repo.
3. In Codex, use the project from the `pixel-forge` repo root so the plugin can
   read the local `tools/pixel_forge` package and the Sunny Street reference
   files.

For a personal shortcut, create this alias skill outside the repo:

```text
~/.codex/skills/digital-being-assetgen/SKILL.md
```

Use this file content:

````markdown
---
name: digital-being-assetgen
description: Explicit alias for the Sunny Street Digital Being asset authoring workflow.
---

# Digital Being Assetgen Alias

When used inside `pixel-forge`, the canonical project skill body lives at:

```text
plugins/digital-being/skills/digital-being-assetgen/SKILL.md
```

Before executing in `pixel-forge`, read that file and:

```text
plugins/digital-being/references/sunny-street-targets.md
```
````

The alias is optional. It is useful when a teammate wants to type
`$digital-being-assetgen` from any Codex thread, while still keeping the
canonical instructions versioned in this repo.

Do not copy only the alias if the teammate does not also have this repo. The
alias delegates to the canonical plugin files, so the portable unit is the full
`plugins/digital-being/` directory.

## V1 Boundary

The canonical `pixel_forge being generate` backend is still deterministic
`stub` only. The creative authoring skills may use Codex's built-in `imagegen`
tool when the user asks to create assets, but plugin scripts and CI remain
offline.

V1 does not add these as engine backends:

- no GPT-5.5 orchestration
- no remove.bg provider
- no image2video provider
- no web curation UI
- no sprite algorithm wrapper

## Validate The Fixture

```bash
.venv/bin/python plugins/digital-being/scripts/check_artifacts.py plugins/digital-being/examples/minimal-being
.venv/bin/python plugins/digital-being/scripts/validate_manifest.py plugins/digital-being/examples/minimal-being/being-manifest.json plugins/digital-being/examples/minimal-being
.venv/bin/python plugins/digital-being/scripts/summarize_run.py plugins/digital-being/examples/minimal-being
```

## Regenerate The Fixture

The fixture is small and stub-generated. To regenerate it:

```bash
rm -rf plugins/digital-being/examples/minimal-being
.venv/bin/python -m pixel_forge being generate \
  --slug minimal-being \
  --prompt "minimal sunny street digital being" \
  --out plugins/digital-being/examples \
  --backend stub
```

After regenerating, run the validators and pytest.
