---
name: digital-being-runbook
description: Maintain Digital Being run memory artifacts for pixel-forge. Use when Codex needs to inspect, repair, or update plan.md, prompts.md, learnings.md, capability-matrix.json, and run-summary.json so future agents can resume a Sunny Street Digital Being run.
---

# Digital Being Runbook

Use this skill to keep a Digital Being run resumable.

## Required Runbook Artifacts

- `plan.md`
- `prompts.md`
- `learnings.md`
- `capability-matrix.json`
- `run-summary.json`

## Rules

- Keep markdown human-readable and JSON machine-readable.
- Do not use runbook files as substitutes for canonical schemas.
- Do not mark live providers as active in v1.
- If a run fails, preserve the failed stage and available artifacts.

## Workflow

1. Read `run-summary.json` first when present.
2. Check `pipeline-run.json` for stage status and artifact ids.
3. Check `capability-matrix.json` for active/deferred providers.
4. Update `learnings.md` with facts that would help the next agent.
5. Run `digital-being-validation` after editing runbook artifacts.
