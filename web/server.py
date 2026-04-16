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
        stdout, _ = await proc.communicate()
        if proc.returncode == 0 and stdout:
            try:
                result = json.loads(stdout)
                yield f"data: {json.dumps({'event': 'done', 'result': result})}\n\n"
            except json.JSONDecodeError:
                yield f"data: {json.dumps({'event': 'done', 'raw': stdout.decode()})}\n\n"
        elif proc.returncode != 0:
            yield f"data: {json.dumps({'event': 'error', 'code': proc.returncode})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/preview/{path:path}")
async def preview(path: str):
    full = OUTPUT_DIR / path
    if not full.is_file():
        raise HTTPException(404, f"file not found: {path}")
    return FileResponse(full, media_type="image/png")


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


# Serve frontend static files in production
FRONTEND_DIST = Path(__file__).parent / "frontend" / "dist"
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True))
