# Placeable Forge — Map-Driven Object Generation

**Date**: 2026-04-17
**Status**: Approved

## Summary

Add a "Placeables" tab to the Pixel Forge web UI that lets users upload a map screenshot, receive AI-suggested objects that fit the map's theme/style, select which ones to generate, and save the results to the sunny-street project for use in Tiled maps.

## Motivation

Currently, placeable generation is CLI-only (`pf generate --kind placeable`). Users must manually decide what objects to create and craft prompts individually. This feature automates the ideation step — the AI analyzes a map image and suggests 10–15 fitting objects with appropriate footprints, then generates them using the existing pipeline.

## Data Flow

```
User uploads map screenshot
        │
        ▼
  POST /api/analyze-map
  (map image → Gemini text model → structured JSON)
        │
        ▼
  JSON response: 10–15 suggested objects
  [{ name, prompt, footprint, category }, ...]
        │
        ▼
  User selects/deselects items via checkboxes
        │
        ▼
  POST /api/generate-placeables
  (selected items → pf generate --kind placeable × N)
        │
        ▼
  SSE streaming: per-item progress
        │
        ▼
  Result grid: generated PNGs with preview
        │
        ▼
  Save → ~/projects/sunny-street/public/placeables/generated/
```

## Backend: API Endpoints

### `POST /api/analyze-map`

**Input** (FormData):
- `map_image`: PNG/JPG map screenshot

**Processing**:
- Send map image + project prose + palette to Gemini text model
- Request structured JSON response (response_mime_type: "application/json")
- Parse into `PlaceableSuggestion` list

**Analysis prompt** (English):
```
{project prose}

You are a pixel-art game map analyst.

Analyze the attached map screenshot and suggest 10–15 placeable objects that would fit naturally in this map.

Rules:
- Consider the map's theme, color palette, time period, and setting
- Exclude objects that already appear in the map
- Estimate each object's footprint in tiles (width × height) realistically
- Group by category (nature, furniture, structure, decor, etc.)
- Write a detailed generation prompt for each object suitable for an image generation model

Return JSON:
{
  "map_description": "brief description of the map",
  "suggestions": [
    {
      "name": "human-readable name",
      "prompt": "detailed generation prompt — describe appearance, view angle, style",
      "footprint": [width_tiles, height_tiles],
      "category": "nature | furniture | structure | decor | ..."
    }
  ]
}
```

**Output**:
```json
{
  "map_description": "coastal village with grass paths and small houses",
  "suggestions": [
    {
      "name": "oak tree",
      "prompt": "large oak tree with thick trunk and full green canopy, side view, centered, transparent background",
      "footprint": [2, 3],
      "category": "nature"
    },
    ...
  ]
}
```

### `POST /api/generate-placeables`

**Input** (FormData):
- `items`: JSON string — array of selected suggestion objects (name, prompt, footprint)
- `map_image`: original map image (reused as style reference)
- `variants`: variants per item (default 1)

**Processing**:
- Items are generated sequentially (one at a time) to avoid Gemini rate limits
- For each item, invoke `pf generate --kind placeable --footprint WxH --prompt "..." --ref-image map.png`
- Stream progress via SSE: `{ event: "progress", item: "oak tree", status: "generating" }`
- Map image is passed as `--ref-image` so generated objects match the map's color/texture

**Output** (final SSE event):
```json
{
  "event": "done",
  "results": [
    {
      "name": "oak tree",
      "path": "/tmp/pixel-forge-output/oak-tree-xxx.png",
      "meta_path": "/tmp/pixel-forge-output/oak-tree-xxx.meta.json",
      "footprint": [2, 3],
      "ok": true
    },
    ...
  ]
}
```

## Backend: Map Analysis Engine

**Location**: `tools/pixel_forge/backends/gemini_text.py`

This file already exists (empty). Add a single function:

```python
async def analyze_map(
    map_image_path: str,
    project: ProjectConfig,
) -> dict:
    """Send map image to Gemini text model, return structured suggestions."""
```

- Uses `gemini-2.5-flash` (text model, not image generation)
- Injects project prose and palette as context
- Requests JSON response format
- Returns parsed dict with `map_description` and `suggestions`

**Generation reuses existing pipeline entirely** — no changes to `generate.py`, `postprocess.py`, or `backends/gemini.py`.

## Frontend: UI Components

### Tab Structure

Top-level tabs in `App.tsx`:
```
┌─────────────┬──────────────┐
│  Character  │  Placeables  │
└─────────────┴──────────────┘
```

Tab state in App.tsx determines which forge component renders.

### New Components

| Component | File | Purpose |
|-----------|------|---------|
| `PlaceableForge` | `PlaceableForge.tsx` | 3-step flow container (upload → select → results) |
| `MapUploader` | `MapUploader.tsx` | Drag-and-drop image upload area |
| `SuggestionList` | `SuggestionList.tsx` | Checkbox list of AI-suggested objects |
| `PlaceableResultGrid` | `PlaceableResultGrid.tsx` | Generated results with preview and save |

### PlaceableForge — 3-Step Flow

**Step 1: Upload**
- Drag-and-drop zone or file picker for map screenshot
- "Analyze Map" button triggers `/api/analyze-map`
- Loading spinner during analysis

**Step 2: Select**
- Map thumbnail at top with AI's `map_description`
- Checkbox list of suggestions grouped by category
- Each row: checkbox, name, footprint (e.g., "2×3"), category badge
- "Variants per item" dropdown (1–4)
- "Generate Selected" button triggers `/api/generate-placeables`

**Step 3: Results**
- Grid showing each object with:
  - Name
  - Generated PNG preview (transparent background, pixelated rendering)
  - Footprint dimensions
  - Status indicator (pending / generating / done / error)
  - Individual "Save" button
- "Save All to sunny-street" button at bottom

### API Integration

Add to `api.ts`:
- `analyzeMap(mapImage: File): Promise<AnalysisResult>` — standard fetch, returns JSON
- `generatePlaceables(params, onEvent, onDone, onError)` — SSE streaming (same pattern as `startGenerate`)

### New Types

Add to `types.ts`:
```typescript
interface PlaceableSuggestion {
  name: string
  prompt: string
  footprint: [number, number]
  category: string
  selected: boolean  // UI state
}

interface AnalysisResult {
  map_description: string
  suggestions: PlaceableSuggestion[]
}

interface PlaceableResult {
  name: string
  path: string
  metaPath: string
  footprint: [number, number]
  ok: boolean
  previewUrl: string  // constructed from /api/preview?path=...
}
```

## Save / Export

- Reuses existing `POST /api/save` endpoint
- **Save All**: iterates results, copies each PNG + `.meta.json` to destination
- **Individual Save**: single item save via same endpoint
- **Destination**: `~/projects/sunny-street/public/placeables/generated/<slug>.png`
- Overwrites on duplicate slug (existing behavior)

## Scope Boundaries

**In scope**:
- Map image upload and AI analysis
- Suggestion list with select/deselect
- Batch placeable generation via existing pipeline
- Result preview and save

**Out of scope**:
- Editing suggestion prompts in the UI (name selection only)
- Automatic Tiled map integration (user places objects manually in Tiled)
- Placeable animation support
- Multi-project support (hardcoded to sunny-street for now)

## Files Changed

| File | Change |
|------|--------|
| `tools/pixel_forge/backends/gemini_text.py` | Add `analyze_map()` function |
| `web/server.py` | Add `/api/analyze-map` and `/api/generate-placeables` endpoints |
| `web/frontend/src/App.tsx` | Add tab navigation |
| `web/frontend/src/api.ts` | Add `analyzeMap()` and `generatePlaceables()` |
| `web/frontend/src/types.ts` | Add placeable-related types |
| `web/frontend/src/components/PlaceableForge.tsx` | New — 3-step flow container |
| `web/frontend/src/components/MapUploader.tsx` | New — drag-and-drop upload |
| `web/frontend/src/components/SuggestionList.tsx` | New — checkbox suggestion list |
| `web/frontend/src/components/PlaceableResultGrid.tsx` | New — result grid with preview |
