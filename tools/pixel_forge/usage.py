"""Token usage tracking for AI backends.

Backends that hit external APIs (Gemini today, others later) populate
this record on their last `generate()` call so upstream callers can
surface per-pipe token counts + USD cost without threading the whole
request/response protocol.

The record is mutated in place by the backend; callers read it AFTER
the generate call. For backends that don't incur cost (stub), the
record is zero-initialized and `model` is set to "stub" so UIs can
render "$0.00" without special-casing.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class UsageRecord:
    model: str
    prompt_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    call_count: int = 0

    def as_dict(self) -> dict:
        return {
            "model": self.model,
            "prompt_tokens": self.prompt_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "call_count": self.call_count,
        }

    def merge(self, other: "UsageRecord | None") -> None:
        """Add another record's counters into this one in place.

        Model field is kept from whichever record is non-empty. For two
        different models, the merged record keeps the first one and the
        caller is expected to bucket by model upstream.
        """
        if other is None:
            return
        self.prompt_tokens += other.prompt_tokens
        self.output_tokens += other.output_tokens
        self.total_tokens += other.total_tokens
        self.call_count += other.call_count
        if not self.model and other.model:
            self.model = other.model


def empty_usage(model: str = "") -> UsageRecord:
    return UsageRecord(model=model)
