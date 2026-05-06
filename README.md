# pixel-forge

Conversational pixel-art asset generator. Drives Gemini 2.5 Flash Image from a Claude Code session via markdown skills. Produces layer-typed assets — ground/object tilesets, placeables, character sprites, and full composed maps — that respect a per-project style anchor (palette + reference images + prose) and land in the consumer game's expected layout via a pluggable adapter.

## Asset kinds

Every generated asset carries a sidecar `<slug>.meta.json` that declares its kind, layer target, footprint or sheet shape, and anchor. Downstream tools (editors, consumer adapters) read the sidecar instead of guessing from pixel dimensions.

| Kind              | What it is                                                      | Target layer    |
|-------------------|------------------------------------------------------------------|-----------------|
| `ground-tileset`  | Grid-aligned seamless terrain sheet (`cols × rows` cells)        | `ground`        |
| `object-tileset`  | Grid-aligned object/prop sheet with transparency                 | `object`        |
| `placeable`       | Single multi-tile stamp (building, prop, vehicle)                | `placeables`    |
| `character`       | NPC/actor sprite (single frame in v1)                            | —               |
| `map`             | Composer kind: full Tiled `.tmj` built from the above            | —               |

## CLI

```
pf new-project     --name <n> --tile-size 32
pf generate        --project <n> --kind ground-tileset --sheet 4x4 --prompt "..."
pf generate        --project <n> --kind placeable --footprint 2x1 --prompt "..."
pf compose         --project <n> --spec projects/<n>/maps/<m>.toml
pf export          --project <n> --adapter sunny-street --to /path/to/sunny-street
pf migrate-legacy-kinds --project <n>   # one-shot: old tiles/ + props/ → placeables/
```

`pf compose` reads a map spec TOML and produces a real Tiled-compatible `.tmj` skeleton: ground/object tilesets, placeables (with deterministic grid placement), plus optional LLM-suggested markers (transitions, NPCs, spawns). `pf export` copies the composed map's assets into the consumer repo's layout, remapping firstgids and preserving flip flags.

See `docs/2026-04-12-pixel-forge-design.md` in the sunny-street repo for the original design spec.

## How to run

### Prerequisites

- Python 3.12
- Node.js + npm
- A Gemini API key from <https://aistudio.google.com/app/apikey>

### 1. Install the Python package and backend dependencies

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pip install -r web/requirements.txt
```

### 2. Install the frontend dependencies

```bash
cd web/frontend
npm install
cd ../..
```

### 3. Configure environment variables

```bash
cp .env.example .env
```

Then edit `.env` and set:

```bash
GEMINI_API_KEY=your_api_key_here
```

### 4. Start the local web UI

```bash
./dev.sh
```

The script starts both development servers:

- Backend API: <http://localhost:8000>
- Frontend UI: <http://localhost:5173>

Open <http://localhost:5173> in your browser. Press `Ctrl+C` in the terminal to stop both servers.

### 5. Run the CLI directly

After activating the virtual environment, you can run `pf` commands from the repository root:

```bash
source .venv/bin/activate
pf new-project --name demo --tile-size 32
pf generate --project demo --kind placeable --footprint 2x1 --prompt "small wooden market stall"
```

### 6. Use Claude Code skills

From this repository, run `claude`. The markdown skills in `.claude/skills/` provide guided workflows for generating tilesets, placeables, characters, and maps.

### 7. Use the Digital Being Codex plugin

The Sunny Street Digital Being workflow lives in `plugins/digital-being/`. It is a Codex plugin that exposes project-local skills such as `digital-being-assetgen`, `digital-being-spritegen`, `digital-being-worldgen`, and `digital-being-validation`.

For teammate setup and sharing instructions, see `plugins/digital-being/README.md`.

## Web UI (local dev)

| Tab | What it does |
|-----|-------------|
| **Character** | Generate character bundles (portrait + walk + actions) |
| **Placeables** | Upload a map screenshot → AI suggests fitting objects → generate & save |

## Layout

- `tools/pixel_forge/` — deterministic Python package (postprocess, validate, backends, CLI)
- `.claude/skills/` — markdown skills Claude loads to drive the tool
- `plugins/digital-being/` — Codex plugin with Digital Being skills, references, examples, and offline validators
- `projects/<name>/` — one folder per project with its own style anchor and `out/`
- `tests/` — pytest unit and integration tests (no real API calls)

## Running tests

```
source .venv/bin/activate
pytest -v
```

Unit and integration tests do not call the Gemini API. They use a stub backend that copies fixture PNGs. To exercise the real Gemini path, set `GEMINI_API_KEY` in `.env` and run `make smoke`.
