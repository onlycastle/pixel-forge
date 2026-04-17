"""Pixel-Forge asset-forge web server.

Wraps `pf bundle` CLI via subprocess and streams progress as SSE.
Serves the Vite-built frontend as static files in production.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sys
import time as _time
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root (one level up from web/)
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from pixel_forge.backends.gemini_text import analyze_map
from pixel_forge.project import load_project

app = FastAPI(title="Pixel Forge — Asset Forge")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

PF_BIN = str(Path(sys.executable).parent / "pf")
PF_PROJECT = os.environ.get("PF_PROJECT", "sunny-street")
OUTPUT_DIR = Path(os.environ.get("PF_OUTPUT_DIR", "/tmp/pixel-forge-output"))
# Walking reference: the premade-01.png sprite sheet used as a layout reference
# for the walking-sheet pipe. Override via WALKING_REFERENCE env var.
WALKING_REFERENCE = os.environ.get(
    "WALKING_REFERENCE",
    str(Path.home() / "projects" / "sunny-street" / "public" / "sprites" / "premade-01.png"),
)


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
    if not prompt or len(prompt.strip()) < 3:
        raise HTTPException(400, "prompt must be at least 3 characters")
    if backend not in ("gemini", "pixellab"):
        raise HTTPException(400, f"invalid backend: {backend}")
    if not 1 <= variants <= 6:
        raise HTTPException(400, "variants must be 1-6")

    slug = re.sub(r"[^a-z0-9]+", "-", prompt.lower().strip())[:32].strip("-")
    slug = f"{slug}-{int(_time.time()):x}"

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

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
        "--walking-reference", WALKING_REFERENCE,
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
        while True:
            line = await proc.stderr.readline()
            if not line:
                break
            text = line.decode().strip()
            if text:
                yield f"data: {text}\n\n"
        # Read remaining stdout after stderr is exhausted.
        stdout_bytes = await proc.stdout.read()
        await proc.wait()
        # Always try to parse stdout — pf bundle writes the result JSON
        # even on exit code 3 (partial errors). Only skip if truly empty.
        if stdout_bytes:
            try:
                result = json.loads(stdout_bytes)
                yield f"data: {json.dumps({'event': 'done', 'result': result})}\n\n"
            except json.JSONDecodeError:
                yield f"data: {json.dumps({'event': 'done', 'raw': stdout_bytes.decode()})}\n\n"
        if proc.returncode and proc.returncode != 0 and not stdout_bytes:
            yield f"data: {json.dumps({'event': 'error', 'code': proc.returncode})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/preview")
async def preview(path: str = ""):
    """Serve a generated image by absolute path (query param)."""
    if not path:
        raise HTTPException(400, "path required")
    full = Path(path)
    if not full.is_file():
        raise HTTPException(404, f"not found: {path}")
    mime = "image/png" if full.suffix == ".png" else "application/octet-stream"
    return FileResponse(full, media_type=mime)


@app.post("/api/save")
async def save(
    source: str = Form(...),
    destination: str = Form(...),
):
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


@app.post("/api/analyze-map")
async def analyze_map_endpoint(
    map_image: UploadFile = File(...),
):
    """Send a map screenshot to Gemini for placeable-object suggestions."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    map_path = OUTPUT_DIR / f"_map_{int(_time.time()):x}.png"
    map_path.write_bytes(await map_image.read())

    try:
        project_root = Path(__file__).resolve().parent.parent / "projects" / PF_PROJECT
        project = load_project(project_root)
        palette_hex = [f"#{r:02x}{g:02x}{b:02x}" for r, g, b in project.palette]
        result = analyze_map(
            map_image_path=str(map_path),
            prose=project.prose,
            palette_hex=palette_hex,
        )
        return result
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@app.post("/api/generate-placeables")
async def generate_placeables(
    items: str = Form(...),
    map_image: UploadFile | None = File(None),
    variants: int = Form(1),
):
    """Generate placeable assets for a list of items, streaming progress via SSE."""
    if not 1 <= variants <= 4:
        raise HTTPException(400, "variants must be 1-4")

    try:
        item_list = json.loads(items)
    except json.JSONDecodeError as exc:
        raise HTTPException(400, f"invalid items JSON: {exc}") from exc

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    ref_path: str | None = None
    if map_image is not None:
        ref_tmp = OUTPUT_DIR / f"_map_ref_{int(_time.time()):x}.png"
        ref_tmp.write_bytes(await map_image.read())
        ref_path = str(ref_tmp)

    total = len(item_list)

    async def event_stream():
        for idx, item in enumerate(item_list):
            name = item.get("name", f"item-{idx}")
            prompt = item.get("prompt", name)
            footprint = item.get("footprint", "1x1")

            yield (
                f"data: {json.dumps({'event': 'progress', 'item': name, 'index': idx, 'total': total, 'status': 'generating'})}\n\n"
            )

            cmd = [
                PF_BIN, "generate",
                "--project", PF_PROJECT,
                "--kind", "placeable",
                "--footprint", footprint,
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
            stdout_bytes = await proc.stdout.read()
            await proc.wait()

            result: dict = {}
            if stdout_bytes:
                try:
                    result = json.loads(stdout_bytes)
                except json.JSONDecodeError:
                    result = {"raw": stdout_bytes.decode()}
            if proc.returncode and proc.returncode != 0 and not result:
                result = {"error": f"pf generate exited with code {proc.returncode}"}

            yield (
                f"data: {json.dumps({'event': 'item_done', 'item': name, 'index': idx, 'result': result})}\n\n"
            )

        yield f"data: {json.dumps({'event': 'done'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# Serve frontend static files in production
FRONTEND_DIST = Path(__file__).parent / "frontend" / "dist"
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True))
