# pixel-forge

Conversational pixel-art asset generator. Drives Gemini 2.5 Flash Image from a Claude Code session via markdown skills. Produces tiles, props, and single-frame character sprites that respect a per-project style anchor (palette + reference images + prose).

See `docs/2026-04-12-pixel-forge-design.md` in the sunny-street repo for the full spec.

## Quick start

1. `python3.12 -m venv .venv && source .venv/bin/activate`
2. `pip install -e ".[dev]"`
3. `cp .env.example .env` and fill in `GEMINI_API_KEY`
4. `cd` into this repo and run `claude` — the skills in `.claude/skills/` take over from there.

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
