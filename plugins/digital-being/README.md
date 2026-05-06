# Digital Being Assetgen Guide

`digital-being-assetgen` is the Codex skill for generating Sunny Street Digital
Being assets.

In this repository, `plugins/digital-being/` is the Codex plugin. The specific
skill used for asset generation is:

```text
plugins/digital-being/skills/digital-being-assetgen/SKILL.md
```

## What Teammates Need

Teammates should pull the latest `pixel-forge` repository and use Codex from
the repository root. They should not copy only `plugins/digital-being/` into an
unrelated folder, because the skill expects the local `pixel-forge` tools,
contracts, and references to be available from this repo.

For normal use, a teammate only needs to read this file and use the
`plugins/digital-being/` plugin that is already committed in the repo.

## 1. Pull The Latest Code

```bash
git pull origin main
```

Open Codex with the `pixel-forge` repository root as the working directory.

## 2. Use The Skill Directly

Ask Codex:

```text
Read plugins/digital-being/skills/digital-being-assetgen/SKILL.md and use the digital-being-assetgen workflow to create one Sunny Street placeable tree asset.
```

For a more explicit request, include the target, slug, and prompt:

```text
digital-being-assetgen --sunny-type placeable --slug sunny-farm-tree --prompt "A small tree placeable for a Sunny Street farm map"
```

## 3. Optional Shortcut: `$digital-being-assetgen`

If a teammate wants to invoke the skill from any Codex thread with
`$digital-being-assetgen`, they can create this local alias skill:

```text
~/.codex/skills/digital-being-assetgen/SKILL.md
```

Use this content:

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

After adding the alias, they can ask Codex:

```text
$digital-being-assetgen --sunny-type placeable --slug sunny-farm-tree --prompt "A small tree placeable for a Sunny Street farm map"
```

The alias is optional. It is only a personal shortcut. The canonical skill stays
versioned in this repository.

## 4. Common Targets

- `placeable`: static world objects such as trees, shrines, furniture, and decor
- `npc-premade`: a character that moves like a Sunny Street NPC
- `ground-tileset`: ground terrain tiles
- `object-tileset`: object-layer tile sheets
- `map`: a Sunny Street-compatible Tiled `.tmj` map
- `concept-only`: visual exploration that is not runtime-ready

For trees and decorative objects, use `placeable`.

## 5. Output Location

Generated runs are saved under:

```text
out/digital-beings/<slug>/
```

A generated run should include:

- `prompts.md`
- `learnings.md`
- `capability-matrix.json`
- `run-summary.json`
- generated PNG files and `.meta.json` sidecars

A `placeable` is `adapter-ready` when the PNG and sidecar match the Pixel Forge
placeable contract. It is not `runtime-ready` until it has been exported and
registered in Sunny Street.

## 6. Export To Sunny Street Runtime

To export a completed placeable into a Sunny Street repo, ask for
`--export-ready` and provide the Sunny Street repository path:

```text
$digital-being-assetgen --sunny-type placeable --slug sunny-farm-tree --export-ready --prompt "A small tree placeable for a Sunny Street farm map" --to /path/to/sunny-street
```

The export path uses:

```bash
pf being export-sunny --run-dir out/digital-beings/<slug> --to /path/to/sunny-street
```

Only call the asset `runtime-ready` after the Sunny Street placeables manifest
and Tiled collection have both been updated.
