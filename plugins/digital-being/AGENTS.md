# Digital Being Plugin Instructions

This directory is a Codex plugin/skill pack for `pixel-forge`.

The plugin consumes the local `pixel-forge` Digital Being engine. Do not treat
this plugin as a second implementation.

Canonical code lives outside this plugin:

- `tools/pixel_forge/schemas/being.py`
- `tools/pixel_forge/sprite_pipeline.py`
- `tools/pixel_forge/digital_being.py`
- `tools/pixel_forge/cli.py`

Rules:

- Do not redefine `BeingSpec`, `PipelineRun`, `ArtifactRef`,
  `ValidationReport`, or `BeingManifest` here.
- Do not reimplement sprite component extraction, background removal,
  normalization, sheet assembly, or validation algorithms here.
- Plugin scripts and CI validators must stay offline and use only the Python
  standard library.
- When the user explicitly asks to create visual assets, skill instructions may
  invoke Codex's built-in `imagegen` skill/tool and the existing
  `pixel-sprite-pipeline` skill. Save project-bound generated images into the
  workspace before reporting completion.
- Do not add a live provider backend to `pixel_forge being generate` until the
  canonical engine implements it. The CLI backend remains `stub` for Phase 0/1.
- Do not call provider APIs from plugin scripts.
- Fixture assets must be deterministic and must not include proprietary Sunny
  Street assets.
