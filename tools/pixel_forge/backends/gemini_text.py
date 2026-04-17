"""Thin text-completion wrapper around Gemini for structured JSON responses.

The image backend in `gemini.py` uses the image-producing model. Marker
placement is a *text* task that returns JSON, so it runs through a
different model and a different completion path. Kept in a separate module
so importing markers.py doesn't pull in image-only dependencies.

Used by the map composer when `spec.markers.suggest = true`.
"""
from __future__ import annotations

import os

MODEL_NAME = "gemini-2.5-flash"


class GeminiTextBackendError(RuntimeError):
    """Raised when the Gemini text model can't produce a response."""


def gemini_text_llm(prompt: str, *, model_name: str = MODEL_NAME) -> str:
    """Send a single prompt to Gemini's text model and return the raw string.

    The returned string is whatever the model produced — callers (e.g.
    `markers.suggest_markers`) are responsible for JSON parsing and
    validation. We deliberately do NOT strip code fences or do any cleanup
    here so the validator sees exactly what the model sent and can surface
    clear errors on format drift.
    """
    import google.generativeai as genai  # local import to keep markers.py pure

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise GeminiTextBackendError("GEMINI_API_KEY is not set")
    genai.configure(api_key=api_key)

    model = genai.GenerativeModel(model_name)
    response = model.generate_content(prompt)

    for candidate in getattr(response, "candidates", []) or []:
        content = getattr(candidate, "content", None)
        if content is None:
            continue
        for part in getattr(content, "parts", []) or []:
            text = getattr(part, "text", None)
            if text:
                return text
    raise GeminiTextBackendError("No text part in Gemini response")


# ---------------------------------------------------------------------------
# Map analysis (multimodal: image + text → JSON)
# ---------------------------------------------------------------------------

_ANALYZE_MAP_PROMPT = """\
{prose}

Palette (reference only):
{palette_lines}

You are a pixel-art game map analyst.
Analyze the attached map screenshot and suggest 10-15 placeable objects that would fit naturally in this map.

Rules:
- Consider the map's theme, color palette, time period, and setting
- Exclude objects that already appear in the map
- Estimate each object's footprint in tiles (width x height) realistically
- Group by category (nature, furniture, structure, decor, etc.)
- Write a detailed generation prompt for each object suitable for an image generation model. Include view angle, style notes, and always end with 'centered, transparent background'

Return ONLY valid JSON (no markdown fences):
{{ "map_description": "...", "suggestions": [{{ "name": "...", "prompt": "...", "footprint": [w, h], "category": "..." }}] }}
"""


def _strip_code_fences(text: str) -> str:
    """Remove optional ```json ... ``` wrapping from model output."""
    stripped = text.strip()
    if stripped.startswith("```"):
        # Drop the opening fence line (```json or ```)
        stripped = stripped.split("\n", 1)[-1]
    if stripped.endswith("```"):
        stripped = stripped.rsplit("```", 1)[0]
    return stripped.strip()


def analyze_map(
    *,
    map_image_path: str,
    prose: str,
    palette_hex: list[str],
    model_name: str = MODEL_NAME,
) -> dict:
    """Send a map screenshot to Gemini and get placeable-object suggestions.

    Returns a dict with ``map_description`` (str) and ``suggestions``
    (list of dicts each containing name, prompt, footprint, category).
    """
    import json
    import google.generativeai as genai  # local import like gemini_text_llm
    from PIL import Image

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise GeminiTextBackendError("GEMINI_API_KEY is not set")
    genai.configure(api_key=api_key)

    palette_lines = "\n".join(palette_hex)
    prompt = _ANALYZE_MAP_PROMPT.format(prose=prose, palette_lines=palette_lines)

    with Image.open(map_image_path) as im:
        im.load()
        image = im.copy()

    model = genai.GenerativeModel(model_name)
    response = model.generate_content([prompt, image])

    # Extract text from response (same logic as gemini_text_llm)
    raw_text: str | None = None
    for candidate in getattr(response, "candidates", []) or []:
        content = getattr(candidate, "content", None)
        if content is None:
            continue
        for part in getattr(content, "parts", []) or []:
            text = getattr(part, "text", None)
            if text:
                raw_text = text
                break
        if raw_text:
            break

    if not raw_text:
        raise GeminiTextBackendError("No text part in Gemini response")

    cleaned = _strip_code_fences(raw_text)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise GeminiTextBackendError(
            f"Failed to parse Gemini response as JSON: {exc}"
        ) from exc

    return parsed
