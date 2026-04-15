# Asset-forge Redesign: Person Bundle + Live Action Grid

**Date:** 2026-04-15
**Scope:** sunny-street `dev/asset-forge` page, pixel-forge `pf bundle` backend, API bridge
**Status:** Draft — pending user review

## Problem

The current `dev/asset-forge` page is a single 1549-line client component that serves three asset types (person, animal, decoration) and three output modes (single, sheet, bundle) via intertwined conditional rendering. The person-bundle flow — which is the most-used path — requires a user to toggle output-mode to "bundle", enter a slug, pick from a "Farmer preset" button or manually check action boxes, and optionally tick "refine walk". Results render as static thumbnails plus a keyboard-driven `BundlePlayer` that only previews one variant at a time.

The user wants a focused person-character flow where:

1. Selecting **person** skips output-mode selection entirely — full character bundle is implicit.
2. The form asks only for the essentials: actions, prompt, optional reference, variants, backend.
3. Backend is selectable between `gemini-3.1-flash` (default) and `pixellab`.
4. The result grid shows **all variants at once**, each row containing portrait + walk + each selected action, with the action sprites actually animating so the user sees what the character does without pressing any key.

Separately, a supporting investigation (R1) confirmed that 3.1 Flash single-call 8:1 sheet generation produces style the user loves but layout the user hates — the four "direction" cells come out as random 3/4-iso poses, not cardinal right/up/left/down. The redesign therefore assumes the production Gemini backend will switch to a per-direction strip implementation internally, independent of the UI shape.

## Goals

- Replace the person flow in `dev/asset-forge` with a purpose-built component that surfaces only the fields a person character needs.
- Render all variants as an auto-animating grid (variant per row, columns: portrait, walk, actions…) with a small direction toggle beneath each cell.
- Expose a backend selector whose choices (`gemini-3.1-flash`, `pixellab`) propagate through the API route to `pf bundle --backend`.
- Delete outdated/orphaned/duplicated code left over from the multi-mode era: the current `BundlePlayer`, the `--refine-walk` pipeline, the "Farmer preset" button, failed spike scripts in `tools/pixel_forge/experiments/`.

## Non-goals

- Reworking the animal or decoration flows. These keep their current behavior, moved into a separate legacy client component without feature change.
- Full production wiring of PixelLab as a sprite source. The UI exposes it as an option; the backend ships a working implementation (`try_pixellab_full_pipeline.py` promoted), but we do not commit to making its output match LimeZu style — the user has judged PixelLab's native style unsuitable and may rarely select it.
- Changes to the on-disk sprite format or to sunny-street's Phaser loader (`character-anims.ts`). The pf bundle output shape is unchanged.
- Imagen 4 backend, nano-banana backend, Gemini 3 Pro backend. These stay as experimentation scripts and are not user-visible.

## Architecture

### Frontend (sunny-street)

```
app/dev/asset-forge/
├── page.tsx                          unchanged server wrapper
├── asset-forge-client.tsx            slimmed to ~30 lines — dispatcher only
│                                     reads asset-type radio, mounts child
├── person-forge-client.tsx           NEW — person full-bundle form + grid
├── legacy-asset-forge-client.tsx     NEW — animal/decoration single/sheet flows
│                                     lifted out of the old file verbatim
├── result-grid/
│   ├── character-result-grid.tsx     NEW — variant-per-row layout
│   ├── sprite-cell.tsx               NEW — one animated cell + dir toggle
│   └── use-sprite-animation.ts       NEW — rAF frame ticker + bg-position
└── bundle-player.tsx                 DELETED (result grid replaces it)
```

**Dispatcher (`asset-forge-client.tsx`).** Keeps the three-way asset-type radio as the only shared top-level control. On change, unmounts/mounts either `PersonForgeClient` or `LegacyAssetForgeClient`. No shared state between the two — the dispatcher owns only `assetType`.

**`PersonForgeClient`** owns:
- Form state: `prompt`, `referenceFile`, `variants` (1–6), `backend` (`"gemini-3.1-flash" | "pixellab"`), `actions` (subset of `{chop, dig, water, fishing, harvest}`).
- Generation state: `isGenerating`, `events[]` (SSE), `variants: VariantResult[]` where each VariantResult contains portrait URL, walk sheet URL + dims, action sheets `{[actionType]: {url, dims}}`, and per-pipe status.
- `handleGenerate()` posts to `/api/asset-forge/generate-stream` and subscribes to SSE. Variants populate as events arrive.
- Renders the form on top and `<CharacterResultGrid variants={variants} />` below.

**`CharacterResultGrid`** receives `variants: VariantResult[]` and the user's `selectedActions` list, and renders a table where each row is one variant:

```
┌─────────────┬──────────┬──────┬───────┬─────┬─────────┬─────────┐
│ Variant 1   │ Portrait │ Walk │ Chop  │ Dig │ Save as │ [Save]  │
├─────────────┼──────────┼──────┼───────┼─────┼─────────┼─────────┤
│ Variant 2   │ Portrait │ Walk │ Chop  │ Dig │ Save as │ [Save]  │
└─────────────┴──────────┴──────┴───────┴─────┴─────────┴─────────┘
```

**Columns are determined by `selectedActions.length` at render time, not by a fixed-width grid.** If the user selects zero actions, the grid has only portrait + walk + save columns. If the user selects five actions, the grid has 5 action columns. Unselected actions never produce an empty column — the column is **omitted entirely**, not rendered blank. This supersedes any earlier wording about "empty columns render blank".

**`SpriteCell`** is the animated unit. Props: `sheetUrl`, `dims` (the object shape already emitted by `pf bundle` into `bundle.json` per variant — see `cli.py:760-808` `_walking_dims_from_sidecar()` which produces `{cell: [w, h], cols, rows, direction_order, locomotion_rows, frames_per_dir}`), `mode: "idle" | "walk" | "action"`, and for action cells `actionType` (used only to read rows / fps, not dims). Internal state: `direction` (default `"down"`). The component:
- Reads cellW/cellH from `dims.cell`, framesPerDir from `dims.frames_per_dir`, row index from `dims.locomotion_rows[mode]`, column offset from `dims.direction_order.indexOf(direction) * framesPerDir`.
- **Walk sheets always read dims from bundle.json.** The grid never hardcodes dimensions. If the backend ever returns a non-standard cell size, SpriteCell renders correctly without code changes.
- Action sheets use `ACTION_SHEETS[actionType]` from `src/lib/sprites.ts` for `frameWidth / frameHeight / framesPerDir / frameRate` — these are fixed per action type by LimeZu convention, not per variant.
- Sets `background-image: url(sheetUrl)`, `background-repeat: no-repeat`, width/height = cellW/cellH scaled up 2× for readability.
- Uses `useSpriteAnimation` to compute the current `background-position` each rAF tick.
- Renders four direction buttons beneath the cell in the **canonical order `[↑, ←, ↓, →]`** (up, left, down, right) — this is the same order Phaser's `DIRECTIONS` array uses in `character-anims.ts:50` and is the order the rest of this spec assumes. Any mention of another ordering in an earlier draft is superseded by this paragraph.
- For the Portrait cell there is no animation and no direction toggle — it renders as a static `<img>`. Treating it as a degenerate SpriteCell variant (via `mode="static"`) keeps the grid layout consistent.

**`useSpriteAnimation(sheet, dims, direction, mode)`** is a small rAF loop that advances a `frameIndex` based on `frameRate`, clamps to `framesPerDir`, and returns `{backgroundPositionX, backgroundPositionY}`. Walking and action sheets index into the same locomotion-row / direction-column scheme already encoded by `ACTION_SHEETS` in `src/lib/sprites.ts`.

### Backend (pixel-forge)

**`backends/gemini.py`** is rewritten. This is materially bigger than a model swap — the current file imports the **legacy `google.generativeai` SDK** (see line 6), while the validated 3.1 Flash experiment scripts use the **new `google-genai` SDK**. The rewrite therefore is an SDK migration:

- Replace `import google.generativeai as genai` with `from google import genai; from google.genai import types as gtypes`.
- Replace `genai.configure(api_key=…)` + `GenerativeModel(...)` pattern with `genai.Client(api_key=…)` + `client.models.generate_content(...)`.
- Replace response-parsing (old SDK exposes `response.parts` iteration differently) with the `candidates[].content.parts[].inline_data` walk used in `try_gemini_31_flash_batch.py`.
- Port the 90-second `HttpOptions(timeout=…)` guard from the experiment scripts — the new SDK also has no default timeout.
- Replace `UsageRecord` integration with the new SDK's `usage_metadata` shape (`prompt_token_count`, `candidates_token_count`, `total_token_count`).
- Model id becomes `gemini-3.1-flash-image-preview`.

Pipe-level behavior of the new backend:

- The walking-sheet pipe (pipe 2 of bundle) switches from one 8:1 single-call to **four per-direction strip calls** (one per `right/up/left/down`), each at `4:1` aspect asking for `preview + 6 idle + 6 walk` of that one direction. This is the core fix for the diagonal-facing bug surfaced during R1 validation.
- After the 4 strips return, a stitcher composes them into the familiar PERSON_PREMADE 1792×192 sheet shape (cell row 0 = 4 previews, row 1 = 24 idles, row 2 = 24 walks).
- Each strip is chroma-keyed to alpha before stitching. The key color is the per-strip dominant 5-bit-quantized color (same algorithm the analysis Python used during the investigation), tolerance = Manhattan RGB distance ≤ 24 (the same tolerance that correctly isolated the LimeZu character vs background in the pairwise-XOR code). If the dominant bg color collides with a sprite color (a bg pixel < tol from any sprite pixel), the stitcher logs a warning and falls back to alpha=255 (no key), letting downstream Phaser render the gray background — ugly but non-fatal.
- The portrait (pipe 1) and action-sheet (pipe 3) pipes use the same model with single-call prompts — those have not exhibited the layout bug.
- Prompts are written in the simplified natural-language style established during the nano-banana investigation: no "3/4 view", no "16-bit-era", no cell-count numerics; rely on the attached reference image to carry layout.

**Rollback note.** 3.1 Flash Image is a preview model. If Google withdraws it during implementation, the fallback is to hold the GeminiBackend rewrite behind a feature flag and keep the current 2.5-flash-based `gemini.py` as `gemini_legacy.py` until either a stable 3.x image model ships or we commit fully to PixelLab. Revert target: the commit that lands the SDK migration.

**`backends/pixellab.py`** is new:
- Wraps the logic currently in `experiments/try_pixellab_full_pipeline.py`: `generate_image_pixflux` for the base east-facing pose, three `rotate` calls to produce north/west/south, four `animate_with_text` calls for per-direction walk cycles.
- Emits a PixelLab asset pack on disk and runs it through the existing `pixellab_to_sheet.py` adapter to produce the PERSON_PREMADE-shaped sheet.
- Does not do palette quantization or style post-processing — the user selects this backend knowing the style is different.

**`backends/base.py`** — the current `ImageBackend` protocol exposes a single method `generate(prompt, refs, n) -> list[Path]`. That shape is wrong for the new pipe-per-method world because the three bundle pipes have different inputs and outputs. The protocol expands to **three pipe-specific methods**:

```python
class CharacterBackend(Protocol):
    def generate_portrait(self, req: PortraitRequest) -> PortraitResult: ...
    def generate_walking_sheet(self, req: WalkingSheetRequest) -> WalkingSheetResult: ...
    def generate_action_sheets(self, req: ActionSheetsRequest) -> ActionSheetsResult: ...
```

`ImageBackend` (the old one) is kept under the same name for the animal/decoration flows (`pf sheet`, `pf generate`) that still shell out to a single generic call. The new `CharacterBackend` lives alongside it and is only consumed by the person bundle pipeline.

**`sheet.py` / `cli._cmd_bundle` dispatch.** The current `_cmd_bundle` runs the three pipes as inline calls through `sheet.run()` / `actions.run()`, both of which take a backend instance. Today both paths use the same `GeminiBackend`; that is the coupling we're breaking. After the rewrite:

1. `_cmd_bundle` resolves the backend class from `--backend` at the top: `backend_cls = {"gemini": GeminiCharacterBackend, "pixellab": PixelLabCharacterBackend}[args.backend]`.
2. Instantiates one backend and passes it (typed `CharacterBackend`) to each pipe helper.
3. Each pipe helper calls the matching method on the backend rather than the generic `generate()`. The helper is responsible for request shaping; the backend is responsible for the actual API calls.

This keeps `_cmd_bundle` readable as a linear three-pipe recipe and pushes all per-backend choice into the backend class itself.

**`cli.py`** adds `--backend {gemini,pixellab}` to `pf bundle`, default `gemini`. The existing `--refine-walk` flag and its handler are **removed**; per-direction generation is now the default implementation of the Gemini backend.

**`sheet.py`** drops `WalkRefineRequest`, `refine_sheet_walk()`, the retryable-backend helper's refine path, and the `pf sheet-refine-walk` CLI subcommand. The `--refine-walk` threading in `_cmd_bundle` is removed.

### API bridge (sunny-street)

**`api/asset-forge/generate/route.ts`** and **`generate-stream/route.ts`** get parallel edits:

Input payload for person:
```ts
{
  assetType: "person",
  prompt: string,
  referenceImage?: File,
  variants: 1..6,
  actions: Array<"chop"|"dig"|"water"|"fishing"|"harvest">,
  backend: "gemini-3.1-flash" | "pixellab",
}
```
Removed fields: `outputMode`, `slug`, `refineWalk`.

Slug auto-generation: `${slugify(prompt).slice(0, 32)}-${Date.now().toString(36)}`. Lives inline at the top of the handler — no separate helper because it's 2 lines.

CLI dispatch: the existing `pf bundle` spawn keeps its argument shape, with three deltas:
- add `--backend <gemini|pixellab>`. The CLI uses the **unversioned short name** `gemini` rather than `gemini-3.1-flash` because the CLI flag is bound to a **backend class**, not to a specific model version. The UI picker displays `gemini-3.1-flash` as the human-readable label for that class. If a future Gemini version replaces 3.1 Flash, the class is swapped out and the UI label updated; the `--backend gemini` flag stays stable, which is the desired decoupling. If we ever need to run two Gemini variants side-by-side, a `--model` sub-flag gets added; this is not currently a requirement.
- drop `--refine-walk`
- drop explicit slug injection; rely on auto-generated slug

Per-variant timeout stays at 6 minutes (10-minute refine variant removed with refineWalk).

## Data flow

```
user clicks Generate
      ↓
PersonForgeClient.handleGenerate
      ↓ FormData POST
/api/asset-forge/generate-stream
      ↓ zod validate, auto-slug
spawn(`pf bundle --project sunny-street --kind person
      --prompt <PROMPT> --backend <BACKEND_NAME>
      --variants <N> --actions <CSV>
      [--ref-image <PATH>]`)
      ↓
pf.cli._cmd_bundle
      ├── pipe 1: backend.generate_portrait(prompt, ref)
      ├── pipe 2: backend.generate_walking_sheet(prompt, ref)
      │           ├── gemini: 4 per-direction strips → stitch
      │           └── pixellab: pixflux + 3 rotate + 4 animate → adapter
      └── pipe 3: backend.generate_action_sheets(prompt, actions, ref)
      ↓
bundle_dir/{portrait.png, walk.png, <action>.png, bundle.json}
      ↓ SSE events: variant-started / pipe-finished / variant-ready / error
PersonForgeClient variants state
      ↓
CharacterResultGrid renders
      ↓ per-variant row, per-cell SpriteCell
SpriteCell reads sheet + dims, rAF loop ticks frame index, CSS bg-position updates
```

## Cleanup scope

The user asked for outdated / orphaned / duplicated code removal. Audit and remove:

**Frontend deletions:**
- `app/dev/asset-forge/bundle-player.tsx` — the old keyboard-driven preview. Replaced by `CharacterResultGrid`.
- From `asset-forge-client.tsx` once the split is done: all `outputMode` state, the bundle-only fields (`slug`, `refineWalk`, `bundleActions` if a dup exists), the "Farmer preset" button, per-mode conditional render branches. Everything that can reach the file via text-search for `outputMode` goes.
- From `/api/asset-forge/generate*/route.ts`: the `"single"` and `"sheet"` validation branches that served person. Those exact code paths still exist for animal and decoration so they move with the legacy component; for person they're dead.

**Backend deletions:**
- `tools/pixel_forge/sheet.py`: `WalkRefineRequest` dataclass, `refine_sheet_walk()` function, the retry-path-for-refine logic. **`contract_drift` stays** — audit during spec revision confirmed it is referenced at `sheet.py:416-480` inside the generic `run()` function, independent of refine, and is still used by the animal/decoration sheet path.
- `tools/pixel_forge/cli.py`: `pf sheet-refine-walk` subcommand, `--refine-walk` flag on `pf bundle`, the `_cmd_sheet_refine_walk` handler, any arg wiring.
- `tools/pixel_forge/backends/gemini.py`: the current 2.5-flash / legacy-SDK implementation gets rewritten in place per the SDK-migration notes above — not deleted, but the file is effectively replaced.

**Experiment script archival** (full filename audit of `tools/pixel_forge/experiments/`):

Keep:
- `try_gemini_31_flash_batch.py` — source of the user-approved style run 20260415-110345-batch, seeds the new gemini backend prompt template
- `try_gemini_31_flash_singledir.py` — Path A validation for 3.1 Flash (documents why single-direction alone is not enough with 3.1 Flash)
- `try_nano_banana_4dir.py` — final working 4-direction prompt template, seeds the per-direction strip prompts
- `try_pixellab_full_pipeline.py` — source for `backends/pixellab.py`
- `pixellab_to_sheet.py` — adapter, used by the new pixellab backend

Delete:
- `try_gemini_31_flash.py` — the earliest 8:1 single-subject spike, fully superseded by `try_gemini_31_flash_batch.py`
- `try_gemini_31_flash_v2.py` — mid-iteration spike with verbose prompt that induced grid lines; superseded by batch + nano-banana
- `try_nano_banana_singledir.py` — superseded by `try_nano_banana_4dir.py`
- `try_pixellab_bitforge.py` — style_image approach proven unworkable (recorded in memory)
- `try_pixellab.py` — single-call PixelLab test, superseded by full_pipeline
- `try_gemini_3_pro.py` — Pro family shares 3.1 flash's iso bias (confirmed during 2026-04-15 triage); if anyone wants to re-evaluate Gemini 3 Pro later the git history still has it

**Duplication audit:**
- `asset-forge-client.tsx` currently has a hardcoded action list that mirrors `ACTION_SHEETS` in `src/lib/sprites.ts`. After the split, `PersonForgeClient` imports from `src/lib/sprites.ts` directly so the list only lives in one place. `LegacyAssetForgeClient` does the same if it needs the list.
- The `refineWalk` branch in `api/asset-forge/generate*/route.ts` duplicates the bundle branch with a different timeout. Both branches fold into one.

## Cell playback mechanics

SpriteCell uses CSS backgrounds rather than Phaser for three reasons:
- Result grid renders up to `6 variants × (1 portrait + 1 walk + 5 actions) = 42 cells`. Spinning up 42 Phaser game instances per generation would be absurd.
- The existing `BundlePlayer` already proves CSS-background animation is fast enough for a single cell at 10 FPS.
- The sheet dims contract (cellW/cellH/framesPerDir/frameRate) is already well-defined by `ACTION_SHEETS`, so the rAF loop is ~20 lines.

Animation parameter sources per cell (authoritative, no hardcoding in SpriteCell):
- Portrait: no animation, single `<img>` pointing at `portrait.png`.
- Walk: all dims (`cell`, `frames_per_dir`, `direction_order`, `locomotion_rows`) come from the variant's `bundle.json` `dims` object, emitted by `_walking_dims_from_sidecar` in `cli.py:760-808`. Frame rate is a component-level constant (10 FPS) since it is a playback choice, not a sprite property.
- Action cells: dims come from `ACTION_SHEETS[actionType]` in `src/lib/sprites.ts`. Example: harvest is 32×64 @ 6 FPS with 9 frames/dir; chop is 64×64 @ 4 FPS with 10 frames/dir.

Direction toggle sits directly beneath each cell as four small square buttons ordered `[↑, ←, ↓, →]` (matching `character-anims.ts:50`'s `DIRECTIONS` tuple). Default `direction="down"`. Clicking a button only sets state on that cell; variant rows are independent of each other.

## Error handling

Per-variant failures surface inline: a failed variant row renders an "error" state in its cells (red border, error message in place of the sprite) rather than dropping the row. This matches the existing per-variant behavior in `BundlePlayer`'s ancestors.

Backend API failures (e.g. Gemini 504, PixelLab balance exhausted) propagate as SSE `error` events with a human-readable message. The UI shows the message in a toast and marks the variant as failed, letting the user click Generate again for just that variant (a re-generation button on the failed row).

SSE disconnection: existing reconnect logic in `asset-forge-client.tsx` is lifted to `PersonForgeClient` as-is. If SSE fails entirely, the button falls back to a POST to the non-streaming `generate/route.ts`.

Form validation: Generate button is disabled until `prompt.length >= 3`. `actions.length` may be 0 — the grid just omits action columns in that case. `backend` has a default so never null. Reference image is optional; when omitted the project's default walking reference is used (same as current).

## Testing

**Frontend (Jest + React Testing Library):**
- `use-sprite-animation.spec.ts` — mock rAF, verify frame index advances at correct rate and wraps at framesPerDir.
- `sprite-cell.spec.tsx` — direction toggle click updates background-position-Y to the correct row.
- `character-result-grid.spec.tsx` — renders N rows for N variants, column count matches portrait + walk + actions.length.
- `person-forge-client.spec.tsx` — form disables Generate when prompt too short, emits correct FormData on submit, SSE event handler appends variants.

**Backend (pytest):**
- `test_gemini_backend_per_direction.py` — monkeypatch the `google-genai` client, feed four fake per-direction strip responses where each strip is tagged with a unique solid-color marker band (e.g. pure red in the right-strip's top-left pixel, pure green in the up-strip's, etc.), assert:
  1. the stitched sheet is exactly 1792×192 RGBA
  2. cell (0, 0) (preview row, direction-order index 0) matches the marker color of the direction the backend claims goes there — this detects row→direction mapping bugs like swapping up/down, not just per-cell content
  3. the chroma-key removed the per-strip background in every stitched region (no bg color survives in the final sheet above alpha=0)
- `test_pixellab_backend.py` — monkeypatch `pixellab.Client`, verify the full 8-call chain (1 generate + 3 rotate + 4 animate) runs in order and the adapter output matches PERSON_PREMADE dims.
- `test_cli_bundle_backend_flag.py` — `pf bundle --backend gemini` and `--backend pixellab` route to the right backend class; unknown backends produce a clean error.

**Integration:**
- Existing `test_end_to_end.py` extends with a person-flow case that uses the stub backend end-to-end and verifies bundle.json shape.

**Manual smoke:**
- Start `next dev`, open `/dev/asset-forge`, select person, fill prompt "a short woman in a green apron", check harvest + chop, variants=2, backend=gemini-3.1-flash, hit Generate. Verify: SSE progress events appear, two rows appear in the grid as variants complete, each row has 4 cells (portrait, walk, harvest, chop) and the walk + action cells actually animate on their own. Click the left-arrow button under the walk cell of variant 1, verify it switches to the left-facing strip.

## Open questions

None blocking this design — the investigation resolved the biggest one (per-direction strips are the layout fix) and the remaining decisions are implementation-local.

## Risks and mitigations

- **Full bundle cost per variant under the new design**: pipe 1 (portrait) = 1 call × ~$0.04 = ~$0.04; pipe 2 (walking sheet) = 4 per-direction calls × ~$0.04 = ~$0.16; pipe 3 (action sheets) = 1 call per selected action × ~$0.04 = up to $0.20 for all 5 actions. **Total per variant: ~$0.40 in the worst case (5 actions), ~$0.20 typical (2 actions)**. A 6-variant generation therefore caps at ~$2.40. For dev-page usage this is negligible; the cost data is recorded so production usage (if any) can budget accurately. All figures are the nominal 3.1 Flash Image Preview tier rate and should be re-measured from usage_metadata on first integration run.
- **3.1 Flash preview latency variance is high (18s–77s measured during validation).** The 90s timeout + 2-attempt retry logic already exists in the experiment scripts and ports into `backends/gemini.py`.
- **PixelLab backend failure mode isn't well-understood yet.** Ship it as the non-default, the user has explicitly said they'll rarely pick it, and add a FAIL-LOUDLY error when it raises so debugging is easier next time.
- **Deleting `BundlePlayer` removes the only keyboard-arrow preview interaction.** The user never mentioned this in the new design, so I'm assuming it's not missed. If it turns out to be a regression we can restore it as a "detail view" modal on top of the grid later.
- **Spec scope is at the edge of "one implementable unit".** The backend rewrite (SDK migration + protocol expansion + per-direction stitcher + new PixelLab backend) and the frontend redesign (5 new files + SSE lift) are roughly equal in effort. Implementation plan should split into a **backend phase** (ships `pf bundle --backend X` green, no frontend changes) and a **frontend phase** (consumes the new CLI), with a handoff checkpoint in between. This lets the frontend development proceed against a stable CLI contract rather than a moving one.
