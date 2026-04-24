"""Gemini token pricing and USD cost estimation.

Rates are PER MILLION TOKENS and must be kept in sync with
https://ai.google.dev/pricing manually. They WILL drift — update the
`Last updated` comment alongside every value bump so future readers
know how stale the table is.

Image generation billing is a moving target: Google has priced it
per-token AND per-image in different model families. The table below
uses per-token approximations that are intentionally conservative
(erring on the expensive side) so the displayed cost is an UPPER
bound rather than a pleasant surprise. For exact invoicing, use
Google Cloud Console.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPricing:
    input_per_million_usd: float
    output_per_million_usd: float


# Last updated: 2026-04-14. Rates approximate Gemini 2.5 Flash Image
# generation. Update both the rate AND this comment when Google
# announces new pricing.
MODEL_PRICING: dict[str, ModelPricing] = {
    "gemini-2.5-flash-image": ModelPricing(
        input_per_million_usd=0.30,
        output_per_million_usd=30.00,  # image output tokens are priced higher than text
    ),
    "gemini-2.5-flash": ModelPricing(
        input_per_million_usd=0.30,
        output_per_million_usd=2.50,
    ),
    "gemini-2.0-flash": ModelPricing(
        input_per_million_usd=0.10,
        output_per_million_usd=0.40,
    ),
    # "stub" backend — used in tests, zero cost.
    "stub": ModelPricing(
        input_per_million_usd=0.0,
        output_per_million_usd=0.0,
    ),
}

UNKNOWN_MODEL_FALLBACK = ModelPricing(
    input_per_million_usd=0.30,
    output_per_million_usd=30.00,
)


def estimate_usd(model: str, prompt_tokens: int, output_tokens: int) -> float:
    """Return an approximate USD cost for a given model + token split.

    Unknown models fall back to the conservative upper-bound rate. The
    result is a FLOAT and should be displayed to 4 decimal places at
    most (e.g. "$0.1234"); more precision is meaningless at these
    rate scales.
    """
    pricing = MODEL_PRICING.get(model, UNKNOWN_MODEL_FALLBACK)
    return (
        prompt_tokens * pricing.input_per_million_usd / 1_000_000
        + output_tokens * pricing.output_per_million_usd / 1_000_000
    )
