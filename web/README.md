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
