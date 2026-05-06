---
name: digital-being-validation
description: Validate an existing pixel-forge Digital Being run directory. Use when Codex needs to check required artifacts, being-manifest.json, pipeline-run.json, run-summary.json, capability-matrix.json, path safety, and offline V1 provider constraints without generating assets or calling network services.
---

# Digital Being Validation

Use this skill to validate an existing Digital Being run directory.

## Rules

- Do not generate assets.
- Do not call network services.
- Do not call live image or background-removal providers.
- Use the Python validators in `plugins/digital-being/scripts/`.

## Commands

```bash
.venv/bin/python plugins/digital-being/scripts/check_artifacts.py <run-dir>
.venv/bin/python plugins/digital-being/scripts/validate_manifest.py <run-dir>/being-manifest.json <run-dir>
.venv/bin/python plugins/digital-being/scripts/summarize_run.py <run-dir>
```

## Quality Gate

A run is not usable until:

- required artifacts exist
- manifest frame counts are internally consistent
- referenced artifact paths stay inside the run directory
- `pipeline-run.json` and `run-summary.json` references resolve
- `capability-matrix.json` does not claim live providers are active in v1
