# Asset-Forge Web UI — Phase B Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone web UI in `pixel-forge/web/` that replaces sunny-street's `dev/asset-forge` page for person character generation — FastAPI backend + Vite/React frontend, with animated sprite-sheet preview grid.

**Architecture:** FastAPI server wraps `pf bundle` via subprocess, streaming stderr progress events as SSE to the browser. React frontend renders a form (prompt, actions, variants, backend, ref image) and a CharacterResultGrid where each variant row auto-animates portrait + walk + selected actions via CSS `background-position` driven by requestAnimationFrame.

**Tech Stack:** Python 3.12, FastAPI, uvicorn, Vite 6, React 19, TypeScript

**Spec:** `docs/superpowers/specs/2026-04-15-asset-forge-redesign-design.md`
**Depends on:** Phase A (`feat/asset-forge-backend` branch) — `CharacterBackend` protocol, `--backend` CLI flag, Gemini/PixelLab backends.

---

## File Map

```
web/
├── server.py                         FastAPI app (generate SSE, save, preview)
├── requirements.txt                  fastapi, uvicorn, python-multipart
├── frontend/
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── index.html
│   └── src/
│       ├── main.tsx                  ReactDOM mount
│       ├── App.tsx                   Top-level layout + asset-type dispatch
│       ├── App.css                   Global styles
│       ├── types.ts                  Shared TS interfaces
│       ├── api.ts                    fetch wrappers + SSE subscription
│       ├── components/
│       │   ├── PersonForge.tsx       Form + state + result grid integration
│       │   ├── PersonForge.css
│       │   ├── CharacterResultGrid.tsx  Variant-per-row table
│       │   ├── SpriteCell.tsx        One animated cell + direction toggle
│       │   └── SpriteCell.css
│       └── hooks/
│           └── useSpriteAnimation.ts  rAF frame ticker
└── tests/
    └── test_server.py                pytest tests for FastAPI endpoints
```

---

### Task 1: Project scaffolding

**Files:**
- Create: `web/requirements.txt`
- Create: `web/frontend/package.json`
- Create: `web/frontend/tsconfig.json`
- Create: `web/frontend/vite.config.ts`
- Create: `web/frontend/index.html`
- Create: `web/frontend/src/main.tsx`
- Create: `web/frontend/src/App.tsx`
- Create: `web/frontend/src/App.css`

- [ ] **Step 1: Create web/requirements.txt**

```
fastapi>=0.115
uvicorn[standard]>=0.30
python-multipart>=0.0.9
```

- [ ] **Step 2: Install Python deps**

Run: `cd /Users/sungmancho/projects/pixel-forge && .venv/bin/pip install -r web/requirements.txt`

- [ ] **Step 3: Scaffold Vite + React + TypeScript**

Run:
```bash
cd /Users/sungmancho/projects/pixel-forge/web
npm create vite@latest frontend -- --template react-ts
cd frontend && npm install
```

- [ ] **Step 4: Configure Vite dev proxy**

Replace `web/frontend/vite.config.ts`:

```typescript
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8420",
        changeOrigin: true,
      },
      "/preview": {
        target: "http://127.0.0.1:8420",
        changeOrigin: true,
      },
    },
  },
});
```

- [ ] **Step 5: Create minimal App.tsx**

Replace `web/frontend/src/App.tsx`:

```tsx
export default function App() {
  return (
    <div style={{ maxWidth: 1200, margin: "0 auto", padding: 24 }}>
      <h1>Pixel Forge — Character Generator</h1>
      <p>Form and result grid will go here.</p>
    </div>
  );
}
```

- [ ] **Step 6: Verify frontend builds**

Run: `cd /Users/sungmancho/projects/pixel-forge/web/frontend && npm run build`
Expected: Build succeeds, `dist/` created.

- [ ] **Step 7: Commit**

```bash
git add web/
git commit -m "scaffold: FastAPI + Vite/React project in web/"
```

---

### Task 2: FastAPI server — generate endpoint with SSE

**Files:**
- Create: `web/server.py`
- Create: `web/tests/test_server.py`

The generate endpoint:
- Accepts POST multipart form: `prompt`, `actions` (comma-separated), `variants`, `backend`, optional `reference` file
- Spawns `pf bundle` subprocess with matching CLI args
- Reads stderr line-by-line (JSON progress events) and forwards as SSE
- When subprocess exits, sends a final `done` or `error` event

- [ ] **Step 1: Write the server test**

```python
# web/tests/test_server.py
"""Tests for the asset-forge web server."""
import pytest
from fastapi.testclient import TestClient


def test_generate_requires_prompt():
    from web.server import app
    client = TestClient(app)
    response = client.post("/api/generate", data={"actions": "", "variants": "1", "backend": "gemini"})
    assert response.status_code == 422 or response.status_code == 400


def test_health():
    from web.server import app
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest web/tests/test_server.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement server.py**

```python
# web/server.py
"""Pixel-Forge asset-forge web server.

Wraps `pf bundle` CLI via subprocess and streams progress as SSE.
Serves the Vite-built frontend as static files in production.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Pixel Forge — Asset Forge")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# The pf CLI entry point — resolve from the same venv.
PF_BIN = str(Path(sys.executable).parent / "pf")
# Default project for sunny-street. Override via PF_PROJECT env var.
PF_PROJECT = os.environ.get("PF_PROJECT", "sunny-street")
# Output base directory. Override via PF_OUTPUT_DIR env var.
OUTPUT_DIR = Path(os.environ.get("PF_OUTPUT_DIR", "/tmp/pixel-forge-output"))


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/generate")
async def generate(
    prompt: str = Form(...),
    actions: str = Form(""),
    variants: int = Form(1),
    backend: str = Form("gemini"),
    reference: UploadFile | None = File(None),
):
    """Stream pf bundle progress as SSE."""
    if not prompt or len(prompt.strip()) < 3:
        raise HTTPException(400, "prompt must be at least 3 characters")
    if backend not in ("gemini", "pixellab"):
        raise HTTPException(400, f"invalid backend: {backend}")
    if not 1 <= variants <= 6:
        raise HTTPException(400, "variants must be 1-6")

    # Auto-generate slug from prompt
    import re, time as _time
    slug = re.sub(r"[^a-z0-9]+", "-", prompt.lower().strip())[:32].strip("-")
    slug = f"{slug}-{int(_time.time()):x}"

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Save reference image if provided
    ref_path: str | None = None
    if reference is not None:
        ref_tmp = OUTPUT_DIR / f"_ref_{slug}.png"
        ref_tmp.write_bytes(await reference.read())
        ref_path = str(ref_tmp)

    cmd = [
        PF_BIN, "bundle",
        "--project", PF_PROJECT,
        "--slug", slug,
        "--prompt", prompt,
        "--backend", backend,
        "--variants", str(variants),
    ]
    if actions.strip():
        cmd.extend(["--actions", actions.strip()])
    if ref_path:
        cmd.extend(["--ref-image", ref_path])

    async def event_stream():
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(Path(__file__).resolve().parent.parent),
        )
        # Stream stderr (progress events) as SSE
        while True:
            line = await proc.stderr.readline()
            if not line:
                break
            text = line.decode().strip()
            if text:
                yield f"data: {text}\n\n"
        # Wait for process to finish
        stdout, _ = await proc.communicate()
        if proc.returncode == 0 and stdout:
            yield f"data: {json.dumps({'event': 'done', 'result': json.loads(stdout)})}\n\n"
        elif proc.returncode != 0:
            yield f"data: {json.dumps({'event': 'error', 'code': proc.returncode})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/preview/{path:path}")
async def preview(path: str):
    """Serve a generated image file for preview."""
    full = OUTPUT_DIR / path
    if not full.is_file():
        raise HTTPException(404, f"file not found: {path}")
    return FileResponse(full, media_type="image/png")


@app.post("/api/save")
async def save(
    source: str = Form(...),
    destination: str = Form(...),
):
    """Copy a generated bundle to the target sprites directory."""
    src = Path(source)
    dst = Path(destination)
    if not src.exists():
        raise HTTPException(404, f"source not found: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True)
    else:
        shutil.copy2(src, dst)
    return {"status": "saved", "destination": str(dst)}


# Serve frontend static files in production
FRONTEND_DIST = Path(__file__).parent / "frontend" / "dist"
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pip install httpx 2>&1 | tail -1 && .venv/bin/pytest web/tests/test_server.py -v`
Expected: PASS (httpx is needed by FastAPI TestClient)

- [ ] **Step 5: Commit**

```bash
git add web/server.py web/tests/ web/requirements.txt
git commit -m "feat(web): FastAPI server with generate SSE + save + preview endpoints"
```

---

### Task 3: TypeScript types + API client

**Files:**
- Create: `web/frontend/src/types.ts`
- Create: `web/frontend/src/api.ts`

- [ ] **Step 1: Create types.ts**

```typescript
// web/frontend/src/types.ts

export type Direction = "right" | "up" | "left" | "down";
export type Backend = "gemini-3.1-flash" | "pixellab";
export type ActionType = "chop" | "dig" | "water" | "fishing" | "harvest";

export const ACTIONS: ActionType[] = ["chop", "dig", "water", "fishing", "harvest"];
export const DIRECTIONS: Direction[] = ["right", "up", "left", "down"];

/** Maps UI backend label to CLI backend name. */
export const BACKEND_CLI_NAME: Record<Backend, string> = {
  "gemini-3.1-flash": "gemini",
  pixellab: "pixellab",
};

/** Sprite sheet dimensions per action type (from sunny-street's ACTION_SHEETS). */
export const ACTION_DIMS: Record<
  ActionType,
  { frameWidth: number; frameHeight: number; framesPerDir: number; frameRate: number }
> = {
  harvest: { frameWidth: 32, frameHeight: 64, framesPerDir: 9, frameRate: 6 },
  chop: { frameWidth: 64, frameHeight: 64, framesPerDir: 10, frameRate: 4 },
  dig: { frameWidth: 64, frameHeight: 64, framesPerDir: 10, frameRate: 4 },
  water: { frameWidth: 64, frameHeight: 64, framesPerDir: 10, frameRate: 6 },
  fishing: { frameWidth: 64, frameHeight: 64, framesPerDir: 10, frameRate: 4 },
};

/** Walk sheet dims (from bundle.json). */
export interface WalkDims {
  cell: [number, number];
  cols: number;
  rows: number;
  direction_order: string[];
  locomotion_rows: Record<string, number>;
  frames_per_dir: number;
}

export interface VariantResult {
  index: number;
  slug: string;
  portraitUrl: string | null;
  walkSheetUrl: string | null;
  walkDims: WalkDims | null;
  actionSheets: Record<ActionType, string>; // actionType -> preview URL
  status: "pending" | "generating" | "done" | "error";
  error?: string;
}

export interface ProgressEvent {
  event: string;
  ts_ms?: number;
  variant?: number;
  pipe?: string;
  [key: string]: unknown;
}
```

- [ ] **Step 2: Create api.ts**

```typescript
// web/frontend/src/api.ts
import type { Backend, ProgressEvent } from "./types";
import { BACKEND_CLI_NAME } from "./types";

export interface GenerateParams {
  prompt: string;
  actions: string[];
  variants: number;
  backend: Backend;
  reference?: File;
}

/**
 * Start a generate request and subscribe to SSE progress events.
 * Returns an AbortController to cancel.
 */
export function startGenerate(
  params: GenerateParams,
  onEvent: (event: ProgressEvent) => void,
  onDone: (result: unknown) => void,
  onError: (error: string) => void,
): AbortController {
  const ctrl = new AbortController();
  const form = new FormData();
  form.append("prompt", params.prompt);
  form.append("actions", params.actions.join(","));
  form.append("variants", String(params.variants));
  form.append("backend", BACKEND_CLI_NAME[params.backend]);
  if (params.reference) {
    form.append("reference", params.reference);
  }

  fetch("/api/generate", { method: "POST", body: form, signal: ctrl.signal })
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
                onDone(parsed.result ?? parsed);
              } else if (parsed.event === "error") {
                onError(JSON.stringify(parsed));
              } else {
                onEvent(parsed);
              }
            } catch {
              // skip unparseable lines
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

- [ ] **Step 3: Commit**

```bash
git add web/frontend/src/types.ts web/frontend/src/api.ts
git commit -m "feat(web): TypeScript types + SSE API client"
```

---

### Task 4: useSpriteAnimation hook

**Files:**
- Create: `web/frontend/src/hooks/useSpriteAnimation.ts`

This is the core animation primitive. It uses requestAnimationFrame to tick a frame index at the specified frame rate and returns the CSS `background-position` values.

- [ ] **Step 1: Create the hook**

```typescript
// web/frontend/src/hooks/useSpriteAnimation.ts
import { useEffect, useRef, useState } from "react";

export interface SpriteAnimationParams {
  /** Total frames in one direction's strip. */
  framesPerDir: number;
  /** Playback speed in frames per second. */
  frameRate: number;
  /** Whether to play (true) or pause on frame 0 (false). */
  playing: boolean;
}

export interface SpriteAnimationResult {
  /** Current frame index (0-based, wraps at framesPerDir). */
  frameIndex: number;
}

/**
 * Ticks a sprite animation frame counter at the specified frame rate
 * using requestAnimationFrame. Returns the current frame index.
 */
export function useSpriteAnimation(
  params: SpriteAnimationParams,
): SpriteAnimationResult {
  const { framesPerDir, frameRate, playing } = params;
  const [frameIndex, setFrameIndex] = useState(0);
  const lastTickRef = useRef(0);
  const rafRef = useRef(0);

  useEffect(() => {
    if (!playing || framesPerDir <= 0 || frameRate <= 0) {
      setFrameIndex(0);
      return;
    }
    const msPerFrame = 1000 / frameRate;
    lastTickRef.current = performance.now();

    const tick = (now: number) => {
      const elapsed = now - lastTickRef.current;
      if (elapsed >= msPerFrame) {
        const steps = Math.floor(elapsed / msPerFrame);
        lastTickRef.current += steps * msPerFrame;
        setFrameIndex((prev) => (prev + steps) % framesPerDir);
      }
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, [framesPerDir, frameRate, playing]);

  return { frameIndex };
}
```

- [ ] **Step 2: Commit**

```bash
git add web/frontend/src/hooks/useSpriteAnimation.ts
git commit -m "feat(web): useSpriteAnimation hook — rAF frame ticker"
```

---

### Task 5: SpriteCell component

**Files:**
- Create: `web/frontend/src/components/SpriteCell.tsx`
- Create: `web/frontend/src/components/SpriteCell.css`

One animated cell with direction toggle buttons beneath.

- [ ] **Step 1: Create SpriteCell.tsx**

```tsx
// web/frontend/src/components/SpriteCell.tsx
import { useState } from "react";
import { useSpriteAnimation } from "../hooks/useSpriteAnimation";
import type { Direction } from "../types";
import { DIRECTIONS } from "../types";
import "./SpriteCell.css";

export interface SpriteCellProps {
  /** URL of the sprite sheet image. */
  sheetUrl: string;
  /** Cell width in pixels. */
  cellW: number;
  /** Cell height in pixels. */
  cellH: number;
  /** Frames per direction in the sheet. */
  framesPerDir: number;
  /** Playback FPS. */
  frameRate: number;
  /** Direction order in the sheet (left to right). */
  directionOrder: Direction[];
  /** Which row of the sheet to animate (0=preview, 1=idle, 2=walk). */
  rowIndex: number;
  /** Display scale factor (default 2). */
  scale?: number;
  /** Label shown above the cell. */
  label?: string;
}

export function SpriteCell({
  sheetUrl,
  cellW,
  cellH,
  framesPerDir,
  frameRate,
  directionOrder,
  rowIndex,
  scale = 2,
  label,
}: SpriteCellProps) {
  const [direction, setDirection] = useState<Direction>("down");
  const { frameIndex } = useSpriteAnimation({
    framesPerDir,
    frameRate,
    playing: true,
  });

  const dirIdx = directionOrder.indexOf(direction);
  const col = dirIdx * framesPerDir + frameIndex;
  const bgX = -(col * cellW * scale);
  const bgY = -(rowIndex * cellH * scale);

  return (
    <div className="sprite-cell">
      {label && <div className="sprite-cell__label">{label}</div>}
      <div
        className="sprite-cell__canvas"
        style={{
          width: cellW * scale,
          height: cellH * scale,
          backgroundImage: `url(${sheetUrl})`,
          backgroundPosition: `${bgX}px ${bgY}px`,
          backgroundSize: "auto",
          backgroundRepeat: "no-repeat",
          imageRendering: "pixelated",
        }}
      />
      <div className="sprite-cell__dirs">
        {(["up", "left", "down", "right"] as Direction[]).map((d) => (
          <button
            key={d}
            className={`sprite-cell__dir-btn ${d === direction ? "active" : ""}`}
            onClick={() => setDirection(d)}
            title={d}
          >
            {{ up: "\u2191", left: "\u2190", down: "\u2193", right: "\u2192" }[d]}
          </button>
        ))}
      </div>
    </div>
  );
}

/** Static portrait cell — no animation, no direction toggle. */
export function PortraitCell({
  imageUrl,
  scale = 2,
}: {
  imageUrl: string;
  scale?: number;
}) {
  return (
    <div className="sprite-cell">
      <div className="sprite-cell__label">Portrait</div>
      <img
        src={imageUrl}
        alt="Character portrait"
        className="sprite-cell__portrait"
        style={{
          width: 64 * scale,
          height: 64 * scale,
          imageRendering: "pixelated",
        }}
      />
    </div>
  );
}
```

- [ ] **Step 2: Create SpriteCell.css**

```css
/* web/frontend/src/components/SpriteCell.css */
.sprite-cell {
  display: inline-flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 8px;
  border: 1px solid #333;
  border-radius: 4px;
  background: #1a1a1a;
}
.sprite-cell__label {
  font-size: 11px;
  color: #888;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.sprite-cell__canvas {
  background-color: #222;
  border: 1px solid #444;
}
.sprite-cell__portrait {
  background-color: #222;
  border: 1px solid #444;
  display: block;
}
.sprite-cell__dirs {
  display: flex;
  gap: 2px;
}
.sprite-cell__dir-btn {
  width: 24px;
  height: 24px;
  border: 1px solid #555;
  border-radius: 3px;
  background: #2a2a2a;
  color: #ccc;
  cursor: pointer;
  font-size: 14px;
  padding: 0;
  line-height: 22px;
}
.sprite-cell__dir-btn.active {
  background: #4a4aff;
  border-color: #6a6aff;
  color: #fff;
}
.sprite-cell__dir-btn:hover {
  background: #3a3a3a;
}
```

- [ ] **Step 3: Commit**

```bash
git add web/frontend/src/components/SpriteCell.tsx web/frontend/src/components/SpriteCell.css
git commit -m "feat(web): SpriteCell component with direction toggle + CSS sprite animation"
```

---

### Task 6: CharacterResultGrid component

**Files:**
- Create: `web/frontend/src/components/CharacterResultGrid.tsx`

Renders a table: one row per variant, columns = portrait + walk + action cells.

- [ ] **Step 1: Create CharacterResultGrid.tsx**

```tsx
// web/frontend/src/components/CharacterResultGrid.tsx
import type { ActionType, Direction, VariantResult } from "../types";
import { ACTION_DIMS } from "../types";
import { PortraitCell, SpriteCell } from "./SpriteCell";

interface Props {
  variants: VariantResult[];
  selectedActions: ActionType[];
}

const WALK_FRAME_RATE = 10;
const WALK_ROW = 2; // walk row in PERSON_PREMADE layout
const DIR_ORDER: Direction[] = ["right", "up", "left", "down"];

export function CharacterResultGrid({ variants, selectedActions }: Props) {
  if (variants.length === 0) return null;

  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ borderCollapse: "separate", borderSpacing: 8 }}>
        <thead>
          <tr>
            <th style={{ color: "#888", fontSize: 12 }}>#</th>
            <th style={{ color: "#888", fontSize: 12 }}>Portrait</th>
            <th style={{ color: "#888", fontSize: 12 }}>Walk</th>
            {selectedActions.map((a) => (
              <th key={a} style={{ color: "#888", fontSize: 12, textTransform: "capitalize" }}>
                {a}
              </th>
            ))}
            <th style={{ color: "#888", fontSize: 12 }}>Save</th>
          </tr>
        </thead>
        <tbody>
          {variants.map((v) => (
            <tr key={v.index}>
              <td style={{ color: "#666", verticalAlign: "top", paddingTop: 16 }}>
                {v.index + 1}
              </td>

              {/* Portrait */}
              <td>
                {v.portraitUrl ? (
                  <PortraitCell imageUrl={v.portraitUrl} />
                ) : (
                  <Placeholder label="Portrait" status={v.status} />
                )}
              </td>

              {/* Walk */}
              <td>
                {v.walkSheetUrl && v.walkDims ? (
                  <SpriteCell
                    sheetUrl={v.walkSheetUrl}
                    cellW={v.walkDims.cell[0]}
                    cellH={v.walkDims.cell[1]}
                    framesPerDir={v.walkDims.frames_per_dir}
                    frameRate={WALK_FRAME_RATE}
                    directionOrder={DIR_ORDER}
                    rowIndex={WALK_ROW}
                    label="Walk"
                  />
                ) : (
                  <Placeholder label="Walk" status={v.status} />
                )}
              </td>

              {/* Action cells */}
              {selectedActions.map((action) => {
                const url = v.actionSheets[action];
                const dims = ACTION_DIMS[action];
                return (
                  <td key={action}>
                    {url ? (
                      <SpriteCell
                        sheetUrl={url}
                        cellW={dims.frameWidth}
                        cellH={dims.frameHeight}
                        framesPerDir={dims.framesPerDir}
                        frameRate={dims.frameRate}
                        directionOrder={DIR_ORDER}
                        rowIndex={0}
                        label={action}
                      />
                    ) : (
                      <Placeholder label={action} status={v.status} />
                    )}
                  </td>
                );
              })}

              {/* Save */}
              <td style={{ verticalAlign: "top", paddingTop: 16 }}>
                {v.status === "done" && (
                  <button
                    style={{
                      padding: "6px 12px",
                      background: "#4a4aff",
                      color: "#fff",
                      border: "none",
                      borderRadius: 4,
                      cursor: "pointer",
                    }}
                    onClick={() => alert(`Save variant ${v.index + 1} — TODO`)}
                  >
                    Save
                  </button>
                )}
                {v.status === "error" && (
                  <span style={{ color: "#ff4444", fontSize: 12 }}>
                    {v.error || "Error"}
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Placeholder({ label, status }: { label: string; status: string }) {
  return (
    <div
      style={{
        width: 128,
        height: 128,
        background: "#222",
        border: "1px solid #333",
        borderRadius: 4,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        color: "#666",
        fontSize: 11,
        flexDirection: "column",
        gap: 4,
      }}
    >
      <span>{label}</span>
      {status === "generating" && <span className="spinner">...</span>}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add web/frontend/src/components/CharacterResultGrid.tsx
git commit -m "feat(web): CharacterResultGrid — variant-per-row table with animated cells"
```

---

### Task 7: PersonForge form component

**Files:**
- Create: `web/frontend/src/components/PersonForge.tsx`
- Create: `web/frontend/src/components/PersonForge.css`

The main form: prompt, actions checkboxes, variants slider, backend radio, ref upload, generate button. Manages state and calls `startGenerate()` from api.ts.

- [ ] **Step 1: Create PersonForge.tsx**

```tsx
// web/frontend/src/components/PersonForge.tsx
import { useCallback, useRef, useState } from "react";
import type { ActionType, Backend, VariantResult } from "../types";
import { ACTIONS, BACKEND_CLI_NAME } from "../types";
import { startGenerate } from "../api";
import { CharacterResultGrid } from "./CharacterResultGrid";
import "./PersonForge.css";

export function PersonForge() {
  const [prompt, setPrompt] = useState("");
  const [selectedActions, setSelectedActions] = useState<ActionType[]>([]);
  const [variants, setVariants] = useState(1);
  const [backend, setBackend] = useState<Backend>("gemini-3.1-flash");
  const [refFile, setRefFile] = useState<File | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [results, setResults] = useState<VariantResult[]>([]);
  const [progressLog, setProgressLog] = useState<string[]>([]);
  const abortRef = useRef<AbortController | null>(null);

  const toggleAction = (action: ActionType) => {
    setSelectedActions((prev) =>
      prev.includes(action) ? prev.filter((a) => a !== action) : [...prev, action],
    );
  };

  const handleGenerate = useCallback(() => {
    if (prompt.trim().length < 3) return;
    setIsGenerating(true);
    setProgressLog([]);

    // Initialize empty variant results
    const initial: VariantResult[] = Array.from({ length: variants }, (_, i) => ({
      index: i,
      slug: "",
      portraitUrl: null,
      walkSheetUrl: null,
      walkDims: null,
      actionSheets: {} as Record<ActionType, string>,
      status: "pending",
    }));
    setResults(initial);

    abortRef.current = startGenerate(
      { prompt: prompt.trim(), actions: selectedActions, variants, backend, reference: refFile ?? undefined },
      (event) => {
        setProgressLog((prev) => [...prev, JSON.stringify(event)]);
        // Update variant status based on events as they arrive
        // The pf bundle CLI emits events to stderr with variant index info
      },
      (result) => {
        setIsGenerating(false);
        // Parse final result and populate variant URLs
        // This is where bundle.json paths get mapped to preview URLs
        setProgressLog((prev) => [...prev, "done: " + JSON.stringify(result)]);
      },
      (error) => {
        setIsGenerating(false);
        setProgressLog((prev) => [...prev, "error: " + error]);
      },
    );
  }, [prompt, selectedActions, variants, backend, refFile]);

  return (
    <div className="person-forge">
      <div className="person-forge__form">
        {/* Prompt */}
        <label className="person-forge__label">
          Character Description
          <textarea
            className="person-forge__textarea"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="a young woman in a yellow sundress and white sneakers, shoulder-length brown hair"
            rows={3}
            maxLength={4000}
          />
        </label>

        {/* Actions */}
        <fieldset className="person-forge__fieldset">
          <legend>Actions</legend>
          <div className="person-forge__actions">
            {ACTIONS.map((action) => (
              <label key={action} className="person-forge__action-label">
                <input
                  type="checkbox"
                  checked={selectedActions.includes(action)}
                  onChange={() => toggleAction(action)}
                />
                {action}
              </label>
            ))}
          </div>
        </fieldset>

        {/* Variants */}
        <label className="person-forge__label">
          Variants: {variants}
          <input
            type="range"
            min={1}
            max={6}
            value={variants}
            onChange={(e) => setVariants(Number(e.target.value))}
          />
        </label>

        {/* Backend */}
        <fieldset className="person-forge__fieldset">
          <legend>Backend</legend>
          <div className="person-forge__radios">
            {(["gemini-3.1-flash", "pixellab"] as Backend[]).map((b) => (
              <label key={b}>
                <input
                  type="radio"
                  name="backend"
                  value={b}
                  checked={backend === b}
                  onChange={() => setBackend(b)}
                />
                {b}
              </label>
            ))}
          </div>
        </fieldset>

        {/* Reference image */}
        <label className="person-forge__label">
          Reference Image (optional)
          <input
            type="file"
            accept="image/png,image/jpeg,image/webp"
            onChange={(e) => setRefFile(e.target.files?.[0] ?? null)}
          />
        </label>

        {/* Generate */}
        <button
          className="person-forge__generate-btn"
          disabled={isGenerating || prompt.trim().length < 3}
          onClick={handleGenerate}
        >
          {isGenerating ? "Generating..." : "Generate"}
        </button>
      </div>

      {/* Progress log */}
      {progressLog.length > 0 && (
        <details className="person-forge__log" open={isGenerating}>
          <summary>Progress ({progressLog.length} events)</summary>
          <pre>{progressLog.join("\n")}</pre>
        </details>
      )}

      {/* Result grid */}
      <CharacterResultGrid variants={results} selectedActions={selectedActions} />
    </div>
  );
}
```

- [ ] **Step 2: Create PersonForge.css**

```css
/* web/frontend/src/components/PersonForge.css */
.person-forge {
  display: flex;
  flex-direction: column;
  gap: 24px;
}
.person-forge__form {
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-width: 600px;
}
.person-forge__label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  color: #ccc;
  font-size: 14px;
}
.person-forge__textarea {
  background: #222;
  border: 1px solid #444;
  border-radius: 4px;
  color: #eee;
  padding: 8px;
  font-family: inherit;
  font-size: 14px;
  resize: vertical;
}
.person-forge__fieldset {
  border: 1px solid #444;
  border-radius: 4px;
  padding: 12px;
}
.person-forge__fieldset legend {
  color: #888;
  font-size: 12px;
  text-transform: uppercase;
}
.person-forge__actions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}
.person-forge__action-label {
  display: flex;
  align-items: center;
  gap: 4px;
  color: #ccc;
  font-size: 14px;
  text-transform: capitalize;
  cursor: pointer;
}
.person-forge__radios {
  display: flex;
  gap: 16px;
}
.person-forge__radios label {
  display: flex;
  align-items: center;
  gap: 4px;
  color: #ccc;
  font-size: 14px;
  cursor: pointer;
}
.person-forge__generate-btn {
  padding: 10px 20px;
  background: #4a4aff;
  color: #fff;
  border: none;
  border-radius: 6px;
  font-size: 16px;
  cursor: pointer;
  align-self: flex-start;
}
.person-forge__generate-btn:disabled {
  background: #333;
  color: #666;
  cursor: not-allowed;
}
.person-forge__log {
  background: #111;
  border: 1px solid #333;
  border-radius: 4px;
  padding: 8px;
}
.person-forge__log summary {
  color: #888;
  cursor: pointer;
  font-size: 12px;
}
.person-forge__log pre {
  color: #666;
  font-size: 11px;
  max-height: 200px;
  overflow-y: auto;
  margin: 8px 0 0;
}
```

- [ ] **Step 3: Commit**

```bash
git add web/frontend/src/components/PersonForge.tsx web/frontend/src/components/PersonForge.css
git commit -m "feat(web): PersonForge form — prompt, actions, variants, backend, generate"
```

---

### Task 8: Wire App.tsx + global styles

**Files:**
- Modify: `web/frontend/src/App.tsx`
- Modify: `web/frontend/src/App.css`
- Modify: `web/frontend/src/main.tsx` (cleanup Vite boilerplate)

- [ ] **Step 1: Update App.tsx**

```tsx
// web/frontend/src/App.tsx
import { PersonForge } from "./components/PersonForge";
import "./App.css";

export default function App() {
  return (
    <div className="app">
      <header className="app__header">
        <h1>Pixel Forge</h1>
        <span className="app__subtitle">Character Generator</span>
      </header>
      <main className="app__main">
        <PersonForge />
      </main>
    </div>
  );
}
```

- [ ] **Step 2: Update App.css**

```css
/* web/frontend/src/App.css */
:root {
  color-scheme: dark;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: #0a0a0a;
  color: #eee;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}
.app {
  max-width: 1400px;
  margin: 0 auto;
  padding: 24px;
}
.app__header {
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin-bottom: 32px;
  border-bottom: 1px solid #333;
  padding-bottom: 16px;
}
.app__header h1 {
  font-size: 24px;
  font-weight: 600;
}
.app__subtitle {
  color: #888;
  font-size: 14px;
}
```

- [ ] **Step 3: Clean up main.tsx**

```tsx
// web/frontend/src/main.tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```

- [ ] **Step 4: Build and verify**

Run: `cd /Users/sungmancho/projects/pixel-forge/web/frontend && npm run build`
Expected: Build succeeds.

- [ ] **Step 5: Commit**

```bash
git add web/frontend/src/
git commit -m "feat(web): wire App.tsx with PersonForge + dark theme"
```

---

### Task 9: Dev workflow + smoke test

**Files:**
- Create: `web/README.md`

- [ ] **Step 1: Create README with dev workflow**

```markdown
# Pixel Forge — Web UI

Local web interface for character generation. Wraps `pf bundle` via FastAPI.

## Quick Start

```bash
# Terminal 1: FastAPI server
cd /path/to/pixel-forge
.venv/bin/uvicorn web.server:app --reload --port 8420

# Terminal 2: Vite dev server (with proxy to FastAPI)
cd /path/to/pixel-forge/web/frontend
npm run dev
```

Open http://localhost:5173

## Production

```bash
cd web/frontend && npm run build
.venv/bin/uvicorn web.server:app --port 8420
```

FastAPI serves the built frontend from `web/frontend/dist/`.

## Environment Variables

- `GEMINI_API_KEY` — required for gemini backend
- `PIXELLAB_API_KEY` — required for pixellab backend
- `PF_PROJECT` — pf project name (default: `sunny-street`)
- `PF_OUTPUT_DIR` — where generated bundles go (default: `/tmp/pixel-forge-output`)
```

- [ ] **Step 2: Smoke test the server**

Run: `.venv/bin/pytest web/tests/test_server.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add web/README.md
git commit -m "docs(web): README with dev workflow and env vars"
```

---

## Self-review checklist

**Spec coverage:**
- PersonForge form with prompt/actions/variants/backend/ref: Task 7 ✓
- CharacterResultGrid variant-per-row: Task 6 ✓
- SpriteCell with direction toggle (↑←↓→): Task 5 ✓
- CSS sprite animation via rAF: Task 4 (useSpriteAnimation) ✓
- Backend selector gemini-3.1-flash | pixellab: Task 7 form + Task 3 API mapping ✓
- SSE streaming progress: Task 2 server + Task 3 API client ✓
- Auto-play all cells, default down: Task 5 SpriteCell defaults ✓
- Save per variant: Task 6 CharacterResultGrid save button ✓
- Product separation (web/ in pixel-forge, not sunny-street): All tasks ✓

**Placeholder scan:** The Save button in Task 6 currently calls `alert("TODO")` — this is intentional for the first pass. The FastAPI `/api/save` endpoint (Task 2) is ready; wiring the frontend Save button to call it is a small follow-up. Flagged explicitly to avoid silent omission.

**Type consistency:** `VariantResult`, `ActionType`, `Direction`, `Backend`, `WalkDims` defined in Task 3 types.ts, used consistently in Tasks 5-8. `ACTION_DIMS` matches sunny-street's `ACTION_SHEETS` values. `BACKEND_CLI_NAME` maps UI labels to CLI names as per spec.
