# Multi-View Sprite API Spike — Design

**Date**: 2026-04-15
**Author**: brainstorming session
**Status**: proposed — awaiting approval

## Motivation

Current production path generates character sprite sheets via `gemini-2.5-flash-image` through `tools/pixel_forge/sheet.py`. This path has two recurring failure modes observed during the 2026-04-14/15 work on `pf sheet-refine-walk`:

1. **Square-canvas bias** — Gemini 2.5 Flash Image regularly ignores the 1792×192 (9.33:1) reference aspect ratio and returns a ~1024×1024 canvas. `sheet_extract` then picks a heuristic grid (e.g. 8×4) that doesn't match the `PERSON_PREMADE` contract (56×3), yielding a 256×256 "clean" sheet that is geometrically wrong for downstream sunny-street loaders which index by `SHEET_COLS[spriteKey] = 56`.
2. **Transient 504s** — in the 2026-04-14 session, ~30% of direction-level calls to `gemini-2.5-flash-image` returned `DeadlineExceeded: 504`. Retry logic was added for the walk-refine path but the broader pipe-2 path still fails outright on these.

Before investing in a large rewrite of the Gemini 2.5 Flash pipeline (e.g. porting `actions._extract_action_row` band-detection to full sheets), we want to confirm whether **newer APIs released since May 2025 obsolete the workaround entirely**. Two candidates surfaced during the research phase of this brainstorming session:

- **Gemini 3 Pro Image (Nano Banana Pro)** — Google's flagship image model as of late 2025. Adds explicit `aspect_ratio` parameter support including 8:1, 1:8, 4:1, 1:4, directly targeting the square-bias problem. Requires migration from the deprecated `google-generativeai` SDK to the new `google-genai` SDK.
- **PixelLab.ai** — a pixel-art-specific generation service whose core product is "take one character, output a 4/8-direction sprite sheet with walk/idle cycles". Has a Python SDK, typical prices 1/5 to 1/40 of Gemini Flash per image.

## Scope

A single **spike**, not a production migration. Two standalone Python scripts that each invoke one candidate API with the minimum-viable input to let us judge output quality, cost, and style fit.

## Non-Goals

- No refactoring of `tools/pixel_forge/backends/gemini.py`, `sheet.py`, or any production CLI path
- No new CLI subcommands
- No new backend classes in `backends/`
- No multi-variant generation; each script generates **exactly 1 image** per run
- No UI wiring (asset-forge GUI unchanged)
- No adoption decision encoded in code — the spike produces observations, not merges

## Deliverables

```
tools/pixel_forge/experiments/
├── try_gemini_3_pro.py      # standalone, uses google-genai
├── try_pixellab.py          # standalone, uses pixellab SDK
└── out/
    └── <YYYYMMDD-HHMMSS>/
        ├── gemini3pro_raw.png
        ├── gemini3pro_meta.json
        ├── pixellab_raw.png
        └── pixellab_meta.json

docs/superpowers/specs/
└── 2026-04-15-multi-view-api-spike-design.md   # this doc

docs/superpowers/findings/
└── 2026-04-15-multi-view-api-spike-findings.md  # written after the runs
```

## Script Contract (shared)

Both scripts follow the same shape so the comparison is apples-to-apples:

| Aspect | Value |
|---|---|
| Subject prompt | `"a weathered 1974 California farmhand with sun-bleached denim and a wide-brim hat"` (same as the 2026-04-14 refine test, for continuity) |
| Reference image | `/Users/sungmancho/projects/sunny-street/public/sprites/premade-01.png` (shared layout anchor) |
| Target output shape | 1792×192 RGBA (PERSON_PREMADE target) OR whatever the API's native sprite-sheet format is |
| Variants per run | 1 |
| Output PNG | `{api}_raw.png` in the timestamped output dir |
| Output meta | `{api}_meta.json` with `{model, prompt, elapsed_ms, usage_tokens_or_equivalent, cost_usd_estimate, raw_size}` |
| Stdout | Single-line summary: `{api}: {status} {raw_size} {elapsed_ms}ms ~${cost}` |
| Env vars | `GEMINI_API_KEY` (existing), `PIXELLAB_API_KEY` (new, already added) |

## API-Specific Notes

### `try_gemini_3_pro.py`

- **SDK**: `google-genai` (new, must be installed alongside the legacy `google-generativeai` that production still depends on)
- **Model**: `gemini-3-pro-image-preview`
- **Critical parameter**: `aspect_ratio="8:1"` (closest supported ratio to our 9.33:1 target). This is the hypothesis-under-test — if this one parameter fixes the square-bias, the whole production path becomes dramatically simpler.
- **Reference passing**: pass masked `premade-01.png` cropped to 1792×192 as a reference image alongside the prompt, identical to how `sheet.run` does it today.
- **Expected cost**: $0.134 at 2K resolution.

### `try_pixellab.py`

- **SDK**: `pixellab` Python package
- **Approach**: first call SDK's simplest "generate character" endpoint to see raw output style. If the SDK has a native "generate 4-direction sprite sheet" endpoint, use that instead (it's the closest match to our goal).
- **Reference passing**: if the SDK accepts a style reference, pass the same `premade-01.png`. If not, prompt-only generation is acceptable for the spike.
- **Expected cost**: $0.007–$0.02 depending on size.

## Success Criteria

The spike answers these four questions:

1. **Aspect ratio**: does Gemini 3 Pro's explicit `aspect_ratio` actually produce a 8:1 canvas? (Yes = fix confirmed; No = Gemini 3 Pro doesn't help us structurally either.)
2. **Character quality**: does each API's single output look like a recognizable version of the described character?
3. **Style fit**: does each API's pixel-art style match sunny-street's existing LimeZu-premade art well enough to drop in without jarring visual break?
4. **Unit economics**: for a realistic full bundle (~3-7 API calls), what's the total cost and total latency in each candidate vs current baseline?

## What the Spike Does NOT Answer

- Multi-frame character consistency across a full sprite sheet (single image doesn't exercise this)
- Robustness under transient network failures (too few samples to measure 504 rate)
- Long-term pricing stability
- Whether the APIs can honor 56×3 grid with 6-frames-per-direction layout specifically

Those are questions for a Phase 2 if the spike's result says "this candidate is worth pursuing".

## Risk + Mitigations

| Risk | Mitigation |
|---|---|
| SDK install conflicts with existing `google-generativeai` | `google-genai` and `google-generativeai` are independently importable packages per Google's SDK docs — additive install, no uninstall |
| PixelLab's style diverges too far from LimeZu premade | Spike surfaces this visually; no code commitment made from spike alone |
| Accidental over-spend from a bug in script | Each script generates exactly 1 image; hard-coded `n=1`; total budget cap $0.20 |
| Script leaks credentials into git | Output dir under `experiments/out/` added to `.gitignore` before first run |

## Approval Required Before Implementation

This design doc is the brainstorming deliverable. Implementation begins **after** the user signs off on it.

Expected sign-off shape: "proceed" or targeted changes to scope/prompt/output format.
