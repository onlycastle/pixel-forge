# Placeable Forge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Placeables" tab to the web UI that lets users upload a map screenshot, get AI-suggested objects, select which to generate, and save results.

**Architecture:** Two-phase API (analyze → generate) with a 3-step React UI. The analyze endpoint uses Gemini text model for map analysis; the generate endpoint loops over existing `generate.run(kind="placeable")` pipeline. Frontend adds tab navigation and a new `PlaceableForge` component tree.

**Tech Stack:** Python/FastAPI (backend), React/TypeScript/Vite (frontend), Gemini 2.5 Flash (text analysis)

---

### Task 1: Map Analysis Function in gemini_text.py

**Files:**
- Modify: `tools/pixel_forge/backends/gemini_text.py`
- Test: `tests/test_analyze_map.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_analyze_map.py`:

```python
"""Tests for the map analysis function."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from pixel_forge.backends.gemini_text import analyze_map


def _fake_gemini_response(text: str) -> MagicMock:
    """Build a mock Gemini response with a single text part."""
    part = MagicMock()
    part.text = text
    content = MagicMock()
    content.parts = [part]
    candidate = MagicMock()
    candidate.content = content
    resp = MagicMock()
    resp.candidates = [candidate]
    return resp


GOOD_JSON = json.dumps({
    "map_description": "a sunny coastal village",
    "suggestions": [
        {
            "name": "oak tree",
            "prompt": "large oak tree with full canopy, side view, centered, transparent background",
            "footprint": [2, 3],
            "category": "nature",
        },
        {
            "name": "wooden bench",
            "prompt": "weathered wooden park bench, front view, centered, transparent background",
            "footprint": [2, 1],
            "category": "furniture",
        },
    ],
})


@patch("pixel_forge.backends.gemini_text.genai")
def test_analyze_map_returns_suggestions(mock_genai, tmp_path):
    # Create a dummy map image
    from PIL import Image
    img = Image.new("RGBA", (256, 256), (100, 200, 100, 255))
    map_path = tmp_path / "map.png"
    img.save(map_path)

    mock_model = MagicMock()
    mock_model.generate_content.return_value = _fake_gemini_response(GOOD_JSON)
    mock_genai.GenerativeModel.return_value = mock_model

    result = analyze_map(
        map_image_path=str(map_path),
        prose="Sunny coastal village pixel art",
        palette_hex=["#7ec850", "#5a9e3e", "#3b6e28"],
    )

    assert result["map_description"] == "a sunny coastal village"
    assert len(result["suggestions"]) == 2
    assert result["suggestions"][0]["name"] == "oak tree"
    assert result["suggestions"][0]["footprint"] == [2, 3]


@patch("pixel_forge.backends.gemini_text.genai")
def test_analyze_map_strips_code_fences(mock_genai, tmp_path):
    from PIL import Image
    img = Image.new("RGBA", (256, 256), (100, 200, 100, 255))
    map_path = tmp_path / "map.png"
    img.save(map_path)

    fenced = f"```json\n{GOOD_JSON}\n```"
    mock_model = MagicMock()
    mock_model.generate_content.return_value = _fake_gemini_response(fenced)
    mock_genai.GenerativeModel.return_value = mock_model

    result = analyze_map(
        map_image_path=str(map_path),
        prose="test prose",
        palette_hex=["#ffffff"],
    )
    assert len(result["suggestions"]) == 2


@patch("pixel_forge.backends.gemini_text.genai")
def test_analyze_map_raises_on_bad_json(mock_genai, tmp_path):
    from PIL import Image
    img = Image.new("RGBA", (256, 256), (100, 200, 100, 255))
    map_path = tmp_path / "map.png"
    img.save(map_path)

    mock_model = MagicMock()
    mock_model.generate_content.return_value = _fake_gemini_response("not json")
    mock_genai.GenerativeModel.return_value = mock_model

    with pytest.raises(Exception, match="Failed to parse"):
        analyze_map(
            map_image_path=str(map_path),
            prose="test",
            palette_hex=[],
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_analyze_map.py -v`
Expected: FAIL — `analyze_map` doesn't exist yet

- [ ] **Step 3: Implement analyze_map**

Add to `tools/pixel_forge/backends/gemini_text.py` (append after existing code):

```python
def analyze_map(
    *,
    map_image_path: str,
    prose: str,
    palette_hex: list[str],
    model_name: str = MODEL_NAME,
) -> dict:
    """Analyze a map screenshot and return suggested placeable objects.

    Returns a dict with keys 'map_description' (str) and
    'suggestions' (list of dicts with name, prompt, footprint, category).
    """
    import google.generativeai as genai  # local import

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise GeminiTextBackendError("GEMINI_API_KEY is not set")
    genai.configure(api_key=api_key)

    from PIL import Image
    img = Image.open(map_image_path)
    img.load()

    palette_block = "\n".join(palette_hex) if palette_hex else "(no palette constraint)"

    prompt = (
        f"{prose}\n\n"
        f"Palette (reference only):\n{palette_block}\n\n"
        "You are a pixel-art game map analyst.\n"
        "Analyze the attached map screenshot and suggest 10-15 placeable objects "
        "that would fit naturally in this map.\n\n"
        "Rules:\n"
        "- Consider the map's theme, color palette, time period, and setting\n"
        "- Exclude objects that already appear in the map\n"
        "- Estimate each object's footprint in tiles (width x height) realistically\n"
        "- Group by category (nature, furniture, structure, decor, etc.)\n"
        "- Write a detailed generation prompt for each object suitable for an "
        "image generation model. Include view angle, style notes, and always end "
        "with 'centered, transparent background'\n\n"
        "Return ONLY valid JSON (no markdown fences):\n"
        '{ "map_description": "brief description of the map",\n'
        '  "suggestions": [\n'
        '    { "name": "human-readable name",\n'
        '      "prompt": "detailed generation prompt",\n'
        '      "footprint": [width_tiles, height_tiles],\n'
        '      "category": "nature | furniture | structure | decor | ..." }\n'
        "  ] }\n"
    )

    model = genai.GenerativeModel(model_name)
    response = model.generate_content([prompt, img])

    raw_text = _extract_text(response)
    return _parse_analysis(raw_text)


def _extract_text(response) -> str:
    """Pull the first text part from a Gemini response."""
    for candidate in getattr(response, "candidates", []) or []:
        content = getattr(candidate, "content", None)
        if content is None:
            continue
        for part in getattr(content, "parts", []) or []:
            text = getattr(part, "text", None)
            if text:
                return text
    raise GeminiTextBackendError("No text part in Gemini response")


def _parse_analysis(raw: str) -> dict:
    """Parse the raw Gemini text into structured analysis result."""
    import json
    import re

    # Strip markdown code fences if present
    cleaned = re.sub(r"^```(?:json)?\s*\n?", "", raw.strip())
    cleaned = re.sub(r"\n?```\s*$", "", cleaned)

    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError as err:
        raise GeminiTextBackendError(
            f"Failed to parse map analysis JSON: {err}\nRaw response:\n{raw[:500]}"
        ) from err

    if "suggestions" not in result:
        raise GeminiTextBackendError(
            f"Missing 'suggestions' key in analysis response: {list(result.keys())}"
        )
    return result
```

Also add the `PIL` import at the top — no, it's a local import inside the function. But we need to move the `import os` to the top of the file if not already there. Check: it's already there at line 5.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_analyze_map.py -v`
Expected: 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_analyze_map.py tools/pixel_forge/backends/gemini_text.py
git commit -m "feat: add analyze_map function for map-driven placeable suggestions"
```

---

### Task 2: Backend API Endpoints

**Files:**
- Modify: `web/server.py`
- Test: `web/tests/test_server_placeables.py`

- [ ] **Step 1: Write the failing test**

Create `web/tests/test_server_placeables.py`:

```python
"""Tests for the placeable forge API endpoints."""
from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import patch

import pytest
from PIL import Image

# Import the FastAPI app for testing
from fastapi.testclient import TestClient
from web.server import app

client = TestClient(app)


def _make_png_bytes(w: int = 64, h: int = 64) -> bytes:
    img = Image.new("RGBA", (w, h), (100, 200, 100, 255))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


MOCK_ANALYSIS = {
    "map_description": "sunny village",
    "suggestions": [
        {
            "name": "oak tree",
            "prompt": "large oak tree, side view, centered, transparent background",
            "footprint": [2, 3],
            "category": "nature",
        },
    ],
}


@patch("web.server.analyze_map", return_value=MOCK_ANALYSIS)
def test_analyze_map_endpoint(mock_analyze):
    png = _make_png_bytes()
    response = client.post(
        "/api/analyze-map",
        files={"map_image": ("map.png", png, "image/png")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["map_description"] == "sunny village"
    assert len(data["suggestions"]) == 1
    mock_analyze.assert_called_once()


def test_analyze_map_no_image():
    response = client.post("/api/analyze-map")
    assert response.status_code == 422  # missing required field
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest web/tests/test_server_placeables.py -v`
Expected: FAIL — `/api/analyze-map` endpoint doesn't exist

- [ ] **Step 3: Add the /api/analyze-map endpoint**

Add these imports at the top of `web/server.py` (after existing imports):

```python
from pixel_forge.backends.gemini_text import analyze_map
from pixel_forge.project import load_project
```

Add the endpoint before the `# Serve frontend static files` section:

```python
@app.post("/api/analyze-map")
async def analyze_map_endpoint(
    map_image: UploadFile = File(...),
):
    """Analyze a map screenshot and return suggested placeable objects."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    map_tmp = OUTPUT_DIR / f"_map_{int(_time.time()):x}.png"
    map_tmp.write_bytes(await map_image.read())

    project_root = Path(__file__).resolve().parent.parent / "projects" / PF_PROJECT
    project = load_project(project_root)
    palette_hex = [f"#{r:02x}{g:02x}{b:02x}" for r, g, b in project.palette]

    try:
        result = analyze_map(
            map_image_path=str(map_tmp),
            prose=project.prose,
            palette_hex=palette_hex,
        )
    except Exception as exc:
        raise HTTPException(500, f"Map analysis failed: {exc}")

    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest web/tests/test_server_placeables.py::test_analyze_map_endpoint -v`
Expected: PASS

- [ ] **Step 5: Add the /api/generate-placeables endpoint**

Add to `web/server.py` after the analyze endpoint:

```python
@app.post("/api/generate-placeables")
async def generate_placeables(
    items: str = Form(...),
    map_image: UploadFile | None = File(None),
    variants: int = Form(1),
):
    """Generate placeable objects from a list of suggestions."""
    if not 1 <= variants <= 4:
        raise HTTPException(400, "variants must be 1-4")

    try:
        item_list = json.loads(items)
    except json.JSONDecodeError:
        raise HTTPException(400, "items must be valid JSON")

    if not item_list:
        raise HTTPException(400, "items list is empty")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    ref_path: str | None = None
    if map_image is not None:
        ref_tmp = OUTPUT_DIR / f"_mapref_{int(_time.time()):x}.png"
        ref_tmp.write_bytes(await map_image.read())
        ref_path = str(ref_tmp)

    async def event_stream():
        for idx, item in enumerate(item_list):
            name = item.get("name", f"item-{idx}")
            prompt = item.get("prompt", name)
            fp = item.get("footprint", [1, 1])
            fp_str = f"{fp[0]}x{fp[1]}"

            yield f"data: {json.dumps({'event': 'progress', 'item': name, 'index': idx, 'total': len(item_list), 'status': 'generating'})}\n\n"

            cmd = [
                PF_BIN, "generate",
                "--project", PF_PROJECT,
                "--kind", "placeable",
                "--footprint", fp_str,
                "--prompt", prompt,
                "--variants", str(variants),
            ]
            if ref_path:
                cmd.extend(["--ref-image", ref_path])

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(Path(__file__).resolve().parent.parent),
            )

            stderr_bytes = await proc.stderr.read()
            stdout_bytes = await proc.stdout.read()
            await proc.wait()

            if stderr_bytes:
                for line in stderr_bytes.decode().strip().splitlines():
                    if line.strip():
                        yield f"data: {json.dumps({'event': 'log', 'item': name, 'message': line.strip()})}\n\n"

            result_data: dict = {"name": name, "footprint": fp, "ok": False, "variants": []}
            if stdout_bytes:
                try:
                    parsed = json.loads(stdout_bytes)
                    result_variants = parsed.get("variants", [])
                    result_data["ok"] = len(result_variants) > 0
                    result_data["variants"] = [
                        {"path": v.get("path", ""), "sidecar_path": v.get("sidecar_path", "")}
                        for v in result_variants
                    ]
                except json.JSONDecodeError:
                    result_data["error"] = "failed to parse output"

            if proc.returncode and proc.returncode != 0 and not result_data["ok"]:
                result_data["error"] = f"exit code {proc.returncode}"

            yield f"data: {json.dumps({'event': 'item_done', 'item': name, 'index': idx, 'result': result_data})}\n\n"

        yield f"data: {json.dumps({'event': 'done'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

- [ ] **Step 6: Run all server tests**

Run: `pytest web/tests/test_server_placeables.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add web/server.py web/tests/test_server_placeables.py
git commit -m "feat: add /api/analyze-map and /api/generate-placeables endpoints"
```

---

### Task 3: Frontend Types and API Functions

**Files:**
- Modify: `web/frontend/src/types.ts`
- Modify: `web/frontend/src/api.ts`

- [ ] **Step 1: Add placeable types to types.ts**

Append to `web/frontend/src/types.ts`:

```typescript
// ── Placeable Forge types ────────────────────────

export interface PlaceableSuggestion {
  name: string;
  prompt: string;
  footprint: [number, number];
  category: string;
}

export interface AnalysisResult {
  map_description: string;
  suggestions: PlaceableSuggestion[];
}

export interface PlaceableVariantResult {
  path: string;
  sidecar_path: string;
}

export interface PlaceableItemResult {
  name: string;
  footprint: [number, number];
  ok: boolean;
  variants: PlaceableVariantResult[];
  error?: string;
}
```

- [ ] **Step 2: Add API functions to api.ts**

Append to `web/frontend/src/api.ts`:

```typescript
import type { AnalysisResult, ProgressEvent, PlaceableSuggestion } from "./types";

export async function analyzeMap(mapImage: File): Promise<AnalysisResult> {
  const form = new FormData();
  form.append("map_image", mapImage);

  const res = await fetch("/api/analyze-map", { method: "POST", body: form });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Analysis failed: HTTP ${res.status} — ${text}`);
  }
  return res.json();
}

export interface GeneratePlaceablesParams {
  items: PlaceableSuggestion[];
  mapImage?: File;
  variants: number;
}

export function startGeneratePlaceables(
  params: GeneratePlaceablesParams,
  onEvent: (event: ProgressEvent) => void,
  onDone: () => void,
  onError: (error: string) => void,
): AbortController {
  const ctrl = new AbortController();
  const form = new FormData();
  form.append("items", JSON.stringify(params.items));
  form.append("variants", String(params.variants));
  if (params.mapImage) {
    form.append("map_image", params.mapImage);
  }

  fetch("/api/generate-placeables", { method: "POST", body: form, signal: ctrl.signal })
    .then(async (res) => {
      if (!res.ok) {
        onError(`HTTP ${res.status}`);
        return;
      }
      const reader = res.body?.getReader();
      if (!reader) return;
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";
        for (const line of lines) {
          if (line.startsWith("data: ")) {
            try {
              const parsed = JSON.parse(line.slice(6)) as ProgressEvent;
              if (parsed.event === "done") {
                onDone();
              } else {
                onEvent(parsed);
              }
            } catch {
              // skip unparseable
            }
          }
        }
      }
    })
    .catch((err) => {
      if (err.name !== "AbortError") onError(String(err));
    });

  return ctrl;
}
```

Note: Update the existing import line at the top of `api.ts` from:
```typescript
import type { Backend, ProgressEvent } from "./types";
```
to:
```typescript
import type { AnalysisResult, Backend, PlaceableSuggestion, ProgressEvent } from "./types";
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd web/frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add web/frontend/src/types.ts web/frontend/src/api.ts
git commit -m "feat: add placeable forge types and API functions"
```

---

### Task 4: Tab Navigation in App.tsx

**Files:**
- Modify: `web/frontend/src/App.tsx`
- Modify: `web/frontend/src/App.css`

- [ ] **Step 1: Add tab state and navigation to App.tsx**

Replace `web/frontend/src/App.tsx` with:

```tsx
import { useState } from "react";
import { PersonForge } from "./components/PersonForge";
import { PlaceableForge } from "./components/PlaceableForge";
import "./App.css";

type Tab = "character" | "placeables";

export default function App() {
  const [tab, setTab] = useState<Tab>("character");

  return (
    <div className="app">
      <header className="app__header">
        <h1>Pixel Forge</h1>
        <nav className="app__tabs">
          <button
            className={`app__tab ${tab === "character" ? "app__tab--active" : ""}`}
            onClick={() => setTab("character")}
          >
            Character
          </button>
          <button
            className={`app__tab ${tab === "placeables" ? "app__tab--active" : ""}`}
            onClick={() => setTab("placeables")}
          >
            Placeables
          </button>
        </nav>
      </header>
      <main className="app__main">
        {tab === "character" ? <PersonForge /> : <PlaceableForge />}
      </main>
    </div>
  );
}
```

- [ ] **Step 2: Add tab styles to App.css**

Append to `web/frontend/src/App.css`:

```css
.app__tabs {
  display: flex;
  gap: 0;
  margin-left: auto;
}
.app__tab {
  padding: 8px 20px;
  background: transparent;
  color: #888;
  border: 1px solid #333;
  border-bottom: none;
  font-size: 14px;
  cursor: pointer;
  transition: color 0.15s, background 0.15s;
}
.app__tab:first-child {
  border-radius: 6px 0 0 0;
}
.app__tab:last-child {
  border-radius: 0 6px 0 0;
}
.app__tab--active {
  color: #eee;
  background: #1a1a1a;
  border-color: #555;
}
.app__tab:hover:not(.app__tab--active) {
  color: #ccc;
}
```

- [ ] **Step 3: Create a placeholder PlaceableForge component**

Create `web/frontend/src/components/PlaceableForge.tsx`:

```tsx
import "./PlaceableForge.css";

export function PlaceableForge() {
  return (
    <div className="placeable-forge">
      <p style={{ color: "#888" }}>Placeable Forge — coming soon</p>
    </div>
  );
}
```

Create `web/frontend/src/components/PlaceableForge.css`:

```css
.placeable-forge {
  display: flex;
  flex-direction: column;
  gap: 24px;
}
```

- [ ] **Step 4: Verify dev server shows tabs**

Run: `cd web/frontend && npm run dev`
Open `http://localhost:5173` — verify two tabs appear, switching works, Character tab shows PersonForge, Placeables tab shows placeholder.

- [ ] **Step 5: Commit**

```bash
git add web/frontend/src/App.tsx web/frontend/src/App.css \
  web/frontend/src/components/PlaceableForge.tsx \
  web/frontend/src/components/PlaceableForge.css
git commit -m "feat: add tab navigation for Character and Placeables"
```

---

### Task 5: MapUploader Component

**Files:**
- Create: `web/frontend/src/components/MapUploader.tsx`

- [ ] **Step 1: Create MapUploader component**

Create `web/frontend/src/components/MapUploader.tsx`:

```tsx
import { useCallback, useRef, useState } from "react";

interface MapUploaderProps {
  onUpload: (file: File) => void;
  disabled?: boolean;
}

export function MapUploader({ onUpload, disabled }: MapUploaderProps) {
  const [dragOver, setDragOver] = useState(false);
  const [preview, setPreview] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFile = useCallback(
    (file: File) => {
      if (!file.type.startsWith("image/")) return;
      setPreview(URL.createObjectURL(file));
      onUpload(file);
    },
    [onUpload],
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const file = e.dataTransfer.files[0];
      if (file) handleFile(file);
    },
    [handleFile],
  );

  return (
    <div
      className={`map-uploader ${dragOver ? "map-uploader--drag" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
      onClick={() => inputRef.current?.click()}
      style={{ opacity: disabled ? 0.5 : 1, pointerEvents: disabled ? "none" : "auto" }}
    >
      <input
        ref={inputRef}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        style={{ display: "none" }}
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) handleFile(file);
        }}
      />
      {preview ? (
        <img
          src={preview}
          alt="Map preview"
          className="map-uploader__preview"
        />
      ) : (
        <div className="map-uploader__placeholder">
          <span className="map-uploader__icon">&#x1F5BC;</span>
          <span>Drop a map screenshot here or click to browse</span>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Add MapUploader styles to PlaceableForge.css**

Append to `web/frontend/src/components/PlaceableForge.css`:

```css
.map-uploader {
  border: 2px dashed #444;
  border-radius: 8px;
  padding: 32px;
  text-align: center;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}
.map-uploader:hover,
.map-uploader--drag {
  border-color: #4a4aff;
  background: rgba(74, 74, 255, 0.05);
}
.map-uploader__placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  color: #888;
  font-size: 14px;
}
.map-uploader__icon {
  font-size: 32px;
}
.map-uploader__preview {
  max-width: 100%;
  max-height: 300px;
  border-radius: 4px;
  image-rendering: pixelated;
}
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd web/frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add web/frontend/src/components/MapUploader.tsx \
  web/frontend/src/components/PlaceableForge.css
git commit -m "feat: add MapUploader drag-and-drop component"
```

---

### Task 6: SuggestionList Component

**Files:**
- Create: `web/frontend/src/components/SuggestionList.tsx`

- [ ] **Step 1: Create SuggestionList component**

Create `web/frontend/src/components/SuggestionList.tsx`:

```tsx
import type { PlaceableSuggestion } from "../types";

interface SuggestionListProps {
  suggestions: PlaceableSuggestion[];
  selected: Set<number>;
  onToggle: (index: number) => void;
  mapDescription: string;
}

const CATEGORY_COLORS: Record<string, string> = {
  nature: "#5a9e3e",
  furniture: "#b08050",
  structure: "#888",
  decor: "#c06080",
};

export function SuggestionList({
  suggestions,
  selected,
  onToggle,
  mapDescription,
}: SuggestionListProps) {
  return (
    <div className="suggestion-list">
      <p className="suggestion-list__description">{mapDescription}</p>
      <div className="suggestion-list__items">
        {suggestions.map((s, i) => (
          <label key={i} className="suggestion-list__item">
            <input
              type="checkbox"
              checked={selected.has(i)}
              onChange={() => onToggle(i)}
            />
            <span className="suggestion-list__name">{s.name}</span>
            <span className="suggestion-list__footprint">
              {s.footprint[0]}x{s.footprint[1]}
            </span>
            <span
              className="suggestion-list__category"
              style={{
                background: CATEGORY_COLORS[s.category] ?? "#555",
              }}
            >
              {s.category}
            </span>
          </label>
        ))}
      </div>
      <p className="suggestion-list__count">
        {selected.size} of {suggestions.length} selected
      </p>
    </div>
  );
}
```

- [ ] **Step 2: Add SuggestionList styles to PlaceableForge.css**

Append to `web/frontend/src/components/PlaceableForge.css`:

```css
.suggestion-list__description {
  color: #aaa;
  font-size: 14px;
  font-style: italic;
  margin-bottom: 12px;
}
.suggestion-list__items {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.suggestion-list__item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  background: #1a1a1a;
  border: 1px solid #333;
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
  color: #ddd;
}
.suggestion-list__item:hover {
  border-color: #555;
}
.suggestion-list__name {
  flex: 1;
  text-transform: capitalize;
}
.suggestion-list__footprint {
  color: #888;
  font-size: 12px;
  font-family: monospace;
}
.suggestion-list__category {
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 11px;
  color: #fff;
  text-transform: uppercase;
}
.suggestion-list__count {
  color: #888;
  font-size: 12px;
  margin-top: 8px;
}
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd web/frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add web/frontend/src/components/SuggestionList.tsx \
  web/frontend/src/components/PlaceableForge.css
git commit -m "feat: add SuggestionList checkbox component"
```

---

### Task 7: PlaceableResultGrid Component

**Files:**
- Create: `web/frontend/src/components/PlaceableResultGrid.tsx`

- [ ] **Step 1: Create PlaceableResultGrid component**

Create `web/frontend/src/components/PlaceableResultGrid.tsx`:

```tsx
import type { PlaceableItemResult } from "../types";

interface PlaceableResultGridProps {
  results: PlaceableItemResult[];
  onSave: (index: number) => void;
  onSaveAll: () => void;
}

export function PlaceableResultGrid({
  results,
  onSave,
  onSaveAll,
}: PlaceableResultGridProps) {
  if (results.length === 0) return null;

  const allDone = results.every((r) => r.ok || r.error);

  return (
    <div className="placeable-results">
      <div className="placeable-results__grid">
        {results.map((r, i) => (
          <div key={i} className="placeable-results__card">
            <div className="placeable-results__header">
              <span className="placeable-results__name">{r.name}</span>
              <span className="placeable-results__fp">
                {r.footprint[0]}x{r.footprint[1]}
              </span>
            </div>
            <div className="placeable-results__preview">
              {r.ok && r.variants.length > 0 ? (
                r.variants.map((v, vi) => (
                  <img
                    key={vi}
                    src={`/api/preview?path=${encodeURIComponent(v.path)}`}
                    alt={`${r.name} v${vi + 1}`}
                    className="placeable-results__img"
                  />
                ))
              ) : r.error ? (
                <span className="placeable-results__error">{r.error}</span>
              ) : (
                <span className="placeable-results__pending">Generating...</span>
              )}
            </div>
            {r.ok && (
              <button
                className="placeable-results__save-btn"
                onClick={() => onSave(i)}
              >
                Save
              </button>
            )}
          </div>
        ))}
      </div>
      {allDone && (
        <button className="placeable-results__save-all" onClick={onSaveAll}>
          Save All to sunny-street
        </button>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Add PlaceableResultGrid styles to PlaceableForge.css**

Append to `web/frontend/src/components/PlaceableForge.css`:

```css
.placeable-results__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 16px;
}
.placeable-results__card {
  background: #1a1a1a;
  border: 1px solid #333;
  border-radius: 6px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.placeable-results__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.placeable-results__name {
  color: #ddd;
  font-size: 13px;
  font-weight: 500;
  text-transform: capitalize;
}
.placeable-results__fp {
  color: #888;
  font-size: 11px;
  font-family: monospace;
}
.placeable-results__preview {
  min-height: 80px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  flex-wrap: wrap;
}
.placeable-results__img {
  max-width: 96px;
  max-height: 96px;
  image-rendering: pixelated;
  background: repeating-conic-gradient(#222 0% 25%, #1a1a1a 0% 50%) 0 0 / 8px 8px;
  border-radius: 2px;
}
.placeable-results__error {
  color: #e55;
  font-size: 12px;
}
.placeable-results__pending {
  color: #888;
  font-size: 12px;
}
.placeable-results__save-btn {
  padding: 4px 12px;
  background: #333;
  color: #ccc;
  border: 1px solid #555;
  border-radius: 4px;
  font-size: 12px;
  cursor: pointer;
  align-self: flex-end;
}
.placeable-results__save-btn:hover {
  background: #444;
}
.placeable-results__save-all {
  margin-top: 16px;
  padding: 10px 20px;
  background: #4a4aff;
  color: #fff;
  border: none;
  border-radius: 6px;
  font-size: 14px;
  cursor: pointer;
  align-self: flex-start;
}
.placeable-results__save-all:hover {
  background: #5b5bff;
}
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd web/frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add web/frontend/src/components/PlaceableResultGrid.tsx \
  web/frontend/src/components/PlaceableForge.css
git commit -m "feat: add PlaceableResultGrid component"
```

---

### Task 8: Wire Up PlaceableForge (3-Step Flow)

**Files:**
- Modify: `web/frontend/src/components/PlaceableForge.tsx`

- [ ] **Step 1: Implement the full PlaceableForge component**

Replace `web/frontend/src/components/PlaceableForge.tsx` with:

```tsx
import { useCallback, useRef, useState } from "react";
import type { PlaceableItemResult, PlaceableSuggestion, ProgressEvent } from "../types";
import { analyzeMap, startGeneratePlaceables } from "../api";
import { MapUploader } from "./MapUploader";
import { SuggestionList } from "./SuggestionList";
import { PlaceableResultGrid } from "./PlaceableResultGrid";
import "./PlaceableForge.css";

type Step = "upload" | "select" | "results";

export function PlaceableForge() {
  const [step, setStep] = useState<Step>("upload");
  const [mapFile, setMapFile] = useState<File | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [suggestions, setSuggestions] = useState<PlaceableSuggestion[]>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [mapDescription, setMapDescription] = useState("");
  const [variants, setVariants] = useState(1);
  const [isGenerating, setIsGenerating] = useState(false);
  const [results, setResults] = useState<PlaceableItemResult[]>([]);
  const [progressLog, setProgressLog] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const handleUpload = useCallback((file: File) => {
    setMapFile(file);
    setError(null);
  }, []);

  const handleAnalyze = useCallback(async () => {
    if (!mapFile) return;
    setIsAnalyzing(true);
    setError(null);
    try {
      const result = await analyzeMap(mapFile);
      setSuggestions(result.suggestions);
      setMapDescription(result.map_description);
      setSelected(new Set(result.suggestions.map((_, i) => i)));
      setStep("select");
    } catch (err) {
      setError(String(err));
    } finally {
      setIsAnalyzing(false);
    }
  }, [mapFile]);

  const handleToggle = useCallback((index: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  }, []);

  const handleGenerate = useCallback(() => {
    const items = suggestions.filter((_, i) => selected.has(i));
    if (items.length === 0) return;

    setIsGenerating(true);
    setProgressLog([]);
    setResults(
      items.map((s) => ({
        name: s.name,
        footprint: s.footprint,
        ok: false,
        variants: [],
      })),
    );
    setStep("results");

    abortRef.current = startGeneratePlaceables(
      { items, mapImage: mapFile ?? undefined, variants },
      (event: ProgressEvent) => {
        setProgressLog((prev) => [...prev, JSON.stringify(event)]);
        if (event.event === "item_done") {
          const itemResult = (event as Record<string, unknown>).result as PlaceableItemResult;
          const idx = (event as Record<string, unknown>).index as number;
          setResults((prev) =>
            prev.map((r, i) => (i === idx ? { ...r, ...itemResult } : r)),
          );
        }
      },
      () => {
        setIsGenerating(false);
        setProgressLog((prev) => [...prev, "All items generated."]);
      },
      (err) => {
        setIsGenerating(false);
        setError(err);
      },
    );
  }, [suggestions, selected, mapFile, variants]);

  const handleSave = useCallback(
    async (index: number) => {
      const r = results[index];
      if (!r?.ok) return;
      for (const v of r.variants) {
        const form = new FormData();
        form.append("source", v.path);
        const slug = v.path.split("/").pop()?.replace(".png", "") ?? r.name;
        form.append(
          "destination",
          `/Users/sungmancho/projects/sunny-street/public/placeables/generated/${slug}.png`,
        );
        await fetch("/api/save", { method: "POST", body: form });
      }
    },
    [results],
  );

  const handleSaveAll = useCallback(async () => {
    for (let i = 0; i < results.length; i++) {
      if (results[i].ok) await handleSave(i);
    }
  }, [results, handleSave]);

  const handleBack = useCallback(() => {
    if (step === "select") setStep("upload");
    else if (step === "results") {
      setStep("select");
      setResults([]);
      setProgressLog([]);
    }
  }, [step]);

  return (
    <div className="placeable-forge">
      {step !== "upload" && (
        <button className="placeable-forge__back" onClick={handleBack} disabled={isGenerating}>
          &larr; Back
        </button>
      )}

      {error && <div className="placeable-forge__error">{error}</div>}

      {step === "upload" && (
        <div className="placeable-forge__upload">
          <MapUploader onUpload={handleUpload} disabled={isAnalyzing} />
          <button
            className="placeable-forge__analyze-btn"
            disabled={!mapFile || isAnalyzing}
            onClick={handleAnalyze}
          >
            {isAnalyzing ? "Analyzing..." : "Analyze Map"}
          </button>
        </div>
      )}

      {step === "select" && (
        <div className="placeable-forge__select">
          <SuggestionList
            suggestions={suggestions}
            selected={selected}
            onToggle={handleToggle}
            mapDescription={mapDescription}
          />
          <div className="placeable-forge__gen-controls">
            <label className="placeable-forge__label">
              Variants per item: {variants}
              <input
                type="range"
                min={1}
                max={4}
                value={variants}
                onChange={(e) => setVariants(Number(e.target.value))}
              />
            </label>
            <button
              className="placeable-forge__generate-btn"
              disabled={selected.size === 0}
              onClick={handleGenerate}
            >
              Generate {selected.size} Items
            </button>
          </div>
        </div>
      )}

      {step === "results" && (
        <>
          <PlaceableResultGrid
            results={results}
            onSave={handleSave}
            onSaveAll={handleSaveAll}
          />
          {progressLog.length > 0 && (
            <details className="placeable-forge__log" open={isGenerating}>
              <summary>Progress ({progressLog.length} events)</summary>
              <pre>{progressLog.join("\n")}</pre>
            </details>
          )}
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Add remaining PlaceableForge styles**

Append to `web/frontend/src/components/PlaceableForge.css`:

```css
.placeable-forge__back {
  padding: 6px 14px;
  background: transparent;
  color: #888;
  border: 1px solid #444;
  border-radius: 4px;
  font-size: 13px;
  cursor: pointer;
  align-self: flex-start;
}
.placeable-forge__back:hover {
  color: #ccc;
  border-color: #666;
}
.placeable-forge__error {
  background: #3a1111;
  border: 1px solid #e55;
  border-radius: 4px;
  padding: 8px 12px;
  color: #e88;
  font-size: 13px;
}
.placeable-forge__upload {
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-width: 600px;
}
.placeable-forge__analyze-btn,
.placeable-forge__generate-btn {
  padding: 10px 20px;
  background: #4a4aff;
  color: #fff;
  border: none;
  border-radius: 6px;
  font-size: 16px;
  cursor: pointer;
  align-self: flex-start;
}
.placeable-forge__analyze-btn:disabled,
.placeable-forge__generate-btn:disabled {
  background: #333;
  color: #666;
  cursor: not-allowed;
}
.placeable-forge__select {
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-width: 600px;
}
.placeable-forge__gen-controls {
  display: flex;
  align-items: flex-end;
  gap: 16px;
}
.placeable-forge__label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  color: #ccc;
  font-size: 14px;
}
.placeable-forge__log {
  background: #111;
  border: 1px solid #333;
  border-radius: 4px;
  padding: 8px;
  margin-top: 16px;
}
.placeable-forge__log summary {
  color: #888;
  cursor: pointer;
  font-size: 12px;
}
.placeable-forge__log pre {
  color: #666;
  font-size: 11px;
  max-height: 200px;
  overflow-y: auto;
  margin: 8px 0 0;
}
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd web/frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add web/frontend/src/components/PlaceableForge.tsx \
  web/frontend/src/components/PlaceableForge.css
git commit -m "feat: wire up PlaceableForge 3-step flow"
```

---

### Task 9: Integration Test — Full Flow

**Files:**
- Test: manual browser test

- [ ] **Step 1: Start backend**

Run: `cd /Users/sungmancho/projects/pixel-forge && source .venv/bin/activate && uvicorn web.server:app --reload`

- [ ] **Step 2: Start frontend**

Run (separate terminal): `cd /Users/sungmancho/projects/pixel-forge/web/frontend && npm run dev`

- [ ] **Step 3: Verify the full flow in browser**

Open `http://localhost:5173`:

1. Verify tab navigation works (Character / Placeables)
2. Switch to Placeables tab
3. Upload a map screenshot
4. Click "Analyze Map" — verify suggestion list appears
5. Select/deselect items via checkboxes
6. Click "Generate Selected" — verify SSE progress updates
7. Verify generated images appear in result grid
8. Click "Save" on individual items or "Save All"

- [ ] **Step 4: Run all existing tests to check for regressions**

Run: `pytest -v`
Expected: All existing tests still pass

- [ ] **Step 5: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: integration fixes for placeable forge"
```
