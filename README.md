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

## Quick start

1. `python3.12 -m venv .venv && source .venv/bin/activate`
2. `pip install -e ".[dev]"`
3. `cd web/frontend && npm install && cd ../..`
4. `cp .env.example .env` and fill in `GEMINI_API_KEY`
5. `cd` into this repo and run `claude` — the skills in `.claude/skills/` take over from there.

## Web UI (local dev)

```bash
./dev.sh
```

Starts both servers in one terminal — backend on `:8000`, frontend on `:5173`. Open `http://localhost:5173`.

| Tab | What it does |
|-----|-------------|
| **Character** | Generate character bundles (portrait + walk + actions) |
| **Placeables** | Upload a map screenshot → AI suggests fitting objects → generate & save |

## Layout

- `tools/pixel_forge/` — deterministic Python package (postprocess, validate, backends, CLI)
- `.claude/skills/` — markdown skills Claude loads to drive the tool
- `projects/<name>/` — one folder per project with its own style anchor and `out/`
- `tests/` — pytest unit and integration tests (no real API calls)

## Running tests

```
source .venv/bin/activate
pytest -v
```

Unit and integration tests do not call the Gemini API. They use a stub backend that copies fixture PNGs. To exercise the real Gemini path, set `GEMINI_API_KEY` in `.env` and run `make smoke`.
