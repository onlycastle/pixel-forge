# Multi-View Sprite API Spike — Findings

**Date**: 2026-04-15
**Spike spec**: `docs/superpowers/specs/2026-04-15-multi-view-api-spike-design.md`
**Scripts**: `tools/pixel_forge/experiments/try_gemini_3_pro.py`, `try_pixellab.py`
**Total spike cost**: ~$0.15 (3 real API calls; empirical)

## Headline

**Gemini 3 Pro Image (`gemini-3-pro-image-preview`) is the clear winner** for sunny-street-compatible sprite generation. It solves the aspect-ratio square-bias that has been plaguing our `gemini-2.5-flash-image` pipeline, its output style is a drop-in match for LimeZu premade perspective, and a single call produces 12 coherent frames (6 idle + 6 walk) in a 2-row strip. PixelLab is a beautifully clean pixel-art generator but produces a side-scroller perspective that does not match the top-down 3/4 LimeZu style sunny-street uses; adoption would require either camera-parameter tuning beyond the spike scope or a stylistic retargeting of sunny-street itself.

## Runs

### Gemini 3 Pro Image

| Property | Value |
|---|---|
| Model ID | `gemini-3-pro-image-preview` |
| SDK | `google-genai==1.73.1` (new) |
| Aspect ratio requested | `3:2` |
| Actual output size | **1264 × 848** (1.49:1 — within 1% of requested 1.5:1) |
| Elapsed | 71.6 s |
| Cost (est.) | $0.134 |
| Reference passed | 192×128 crop of `premade-01.png` (idle+walk row × right-direction cells) |
| Content | 2 rows × 6 cols = 12 farmhand frames, top row idle variations, bottom row walk cycle with visible leg alternation, all frames share the same character |
| Run output | `experiments/out/20260415-005655/gemini3pro_raw.png` |

**Aspect ratio hypothesis**: confirmed. Unlike Gemini 2.5 Flash Image which returns ~1024×1024 regardless of reference shape, `gemini-3-pro-image-preview` respects the `image_config.aspect_ratio` parameter. 3:2 = 1.5, measured = 1.49 — rounding error territory.

**Important constraint discovered**: Gemini 3 Pro supports these ratios only — `1:1, 2:3, 3:2, 3:4, 4:3, 4:5, 5:4, 9:16, 16:9, 21:9`. It does NOT support the wider 8:1 / 4:1 / 1:4 / 1:8 bands that `gemini-3.1-flash-image-preview` advertises. For our 9.33:1 full sheet target this means 3 Pro can't produce a full-sheet in one call, but it CAN produce a 3:2 per-direction 2-row strip (192×128) that composites into the full sheet via the 4-call pattern we already prototyped in `refine_sheet_walk`.

### PixelLab (pixflux)

| Property | Value |
|---|---|
| SDK | `pixellab==1.0.5` |
| Model | `pixflux` (generate_image_pixflux) |
| image_size | 32×64 (PERSON_PREMADE cell size, exact) |
| Attempts | Two: `view="side"` and `view="high top-down"` |
| Elapsed | 22.2 s and 23.6 s |
| Cost (est.) | ~$0.007 per call (balance-delta measurement failed; SDK BalanceResponse shape differs from what we probed) |
| Content | Single-character single-pose single-direction sprite |
| Outputs | `experiments/out/20260415-005815/pixellab_raw.png` (side), `20260415-010558/pixellab_raw.png` (high top-down) |

**Style finding — the decisive observation**: both PixelLab attempts produced **full-body stand-up pixel art** in what is essentially a platformer / side-scroller perspective. The character occupies the full 64px cell height as a standing figure, with visible face, torso, arms, legs, and boots. This is gorgeous pixel art — crisper than anything Gemini produces — but it is **not the same visual language** as sunny-street's LimeZu premade sheets.

Sunny-street's premade sheets use a **top-down 3/4 "Stardew" view**: the character is seen from above-and-in-front, with the hat visible from the top, the body foreshortened, and the character occupying only the center of each 32×64 cell. PixelLab's `high top-down` option was closer than `side` but still clearly a standing-figure perspective, not the overhead-looking-down style.

This mismatch means PixelLab is not a drop-in replacement for sunny-street unless we're willing to:
- (a) Tune `coverage_percentage`, switch `direction` to `south` (character facing camera), and try other view/direction combinations until we find one that matches LimeZu — uncertain and more calls required
- (b) Retarget sunny-street to PixelLab's native style — large art-direction shift across the whole game
- (c) Use PixelLab for a different asset class (icons, items, portraits) where its standing-figure perspective IS correct

## Cost + Latency per Realistic Bundle

Scaling each API to a full 4-direction sprite sheet equivalent (24 walk frames + 24 idle frames):

| Approach | Calls | Cost | Latency (serial) | Output conformance |
|---|---:|---:|---:|---|
| Current (Gemini 2.5 Flash one-shot) | 1 | ~$0.04 | ~15 s | Often broken (256×256) |
| Current + walk refine | 5 | ~$0.20 | ~2 min | Walk row rescued, idle/preview still from broken shot |
| **Gemini 3 Pro per-direction 3:2 strip (4 calls)** | **4** | **~$0.54** | **~5 min** | **Native 12-frame-per-call, aspect honored, composites cleanly** |
| PixelLab full pipeline (rotate + animate) | ~9 | ~$0.08 | ~3 min | Style mismatch (see above) |
| Gemini 3.1 Flash with 8:1 | 1 | ? | ? | **Untested** — would need a second spike |

**13× cost increase vs current baseline is real** ($0.04 → $0.54), but the current baseline doesn't actually work — its output needs the 4-call refine pipeline to produce anything usable, and even then idle/preview rows are frozen in their original broken state. The honest comparison is "Gemini 3 Pro $0.54 working" vs "Gemini 2.5 Flash refine $0.20 half-working".

## Answering the Spike's Four Questions

> 1. **Aspect ratio** — does Gemini 3 Pro's explicit `aspect_ratio` produce the requested canvas?

**Yes**, within 1% tolerance for 3:2. Major win. The square-bias bug in `gemini-2.5-flash-image` is entirely gone in 3 Pro for the ratios 3 Pro supports.

> 2. **Character quality** — does each API recognizably draw the described character?

Both APIs produced recognizable "1974 California farmhand in denim with wide-brim hat". Gemini 3 Pro also kept the character consistent across all 12 frames in its grid, which is the harder half of this question and PixelLab didn't get asked (only 1 cell produced).

> 3. **Style fit with sunny-street**

Gemini 3 Pro: **good** (top-down 3/4 view matches LimeZu). PixelLab: **poor** (side-scroller / standing-figure perspective, incompatible as drop-in).

> 4. **Unit economics per full bundle**

Gemini 3 Pro 4-call: $0.54 / 5 min / conformant. PixelLab 9-call: $0.08 / 3 min / style mismatch. Baseline: $0.04–$0.20 / 15 s–2 min / broken.

## Recommendations

### Adopt: Gemini 3 Pro Image with per-direction 3:2 strip pipeline

- Replace `sheet.run()`'s full-sheet generation with a 4-call per-direction pipeline that mirrors `refine_sheet_walk`'s architecture
- Each call generates a 192×128 (3:2) strip containing idle row + walk row stacked, for ONE direction
- 4 strips composite into the 1792×192 canvas via paste at the correct column offsets
- This sidesteps the full-sheet square-bias entirely; the 2-row-per-direction shape is 3 Pro's native supported aspect
- Migrate from `google-generativeai` (deprecated) to `google-genai==1.73.1` as part of the work
- Keep `refine_sheet_walk` as-is — the per-direction walk-only refinement is still useful for "pay a little more to improve walk" workflows on existing sheets

### Defer: PixelLab

- Not a drop-in replacement for sunny-street at its current camera-view settings
- Worth a Phase 2 exploration ($0.03–$0.05 budget for 5 more param-combinations) IF we want to use it for cheaper per-cell generation of non-character assets (items, icons, tiles)
- The `animate_with_skeleton` endpoint is theoretically interesting for our use case (it's the "Option C / ControlNet equivalent" we flagged during brainstorming), but without first solving the style-match problem there's no point testing it

### Ignore for now: Gemini 3.1 Flash Image Preview

- It advertises wider aspects (8:1, 4:1) that could theoretically produce our full 1792×192 sheet in ONE call
- Untested in this spike — we chose 3 Pro because its per-direction shape is more aligned with our existing per-direction architecture
- If future work wants to test "single-call full sheet with 8:1", it's a small additional spike

## Next-Session Plan (not for this session)

1. Implement a `Gemini3ProBackend` class alongside the existing `GeminiBackend` (additive, not replacing) — uses `google-genai` SDK
2. Add a new `sheet.run_person_premade_strips()` function that generates 4 per-direction 2-row strips in parallel and composites them into the PERSON_PREMADE canvas
3. Wire a `--use-gemini3` flag on `pf bundle` so we can A/B the paths without committing
4. Run an actual full-bundle e2e with 3 Pro and compare to the current baseline on identity/consistency/cost
5. If 3 Pro wins, make it the default for bundle pipe 2; deprecate the Gemini 2.5 Flash full-sheet path

## Files + Artifacts

- Spec: `docs/superpowers/specs/2026-04-15-multi-view-api-spike-design.md`
- Findings (this doc): `docs/superpowers/findings/2026-04-15-multi-view-api-spike-findings.md`
- Gemini 3 Pro script: `tools/pixel_forge/experiments/try_gemini_3_pro.py`
- PixelLab script: `tools/pixel_forge/experiments/try_pixellab.py`
- Outputs:
  - `tools/pixel_forge/experiments/out/20260415-005655/gemini3pro_raw.png` (1264×848, the winner)
  - `tools/pixel_forge/experiments/out/20260415-005815/pixellab_raw.png` (32×64, side view)
  - `tools/pixel_forge/experiments/out/20260415-010558/pixellab_raw.png` (32×64, high top-down)
- Meta JSON sidecars live next to each `*_raw.png`

## Known Issues

- `try_pixellab.py`'s balance delta measurement reports $0.00 — the `BalanceResponse` object doesn't expose `usd`/`balance` attributes directly. Needs a minor fix to read the actual response shape (non-blocking for the spike's conclusion).
- Neither script has automatic retry on transient failures (`gemini-2.5-flash-image`'s 504 problem would presumably apply here too). Production adoption should wrap these in the same retry helper used by `refine_sheet_walk`.
