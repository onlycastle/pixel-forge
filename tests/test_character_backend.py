"""Tests for the CharacterBackend protocol and its implementations."""
from __future__ import annotations

from pathlib import Path

from pixel_forge.backends.character import (
    ActionSheetsRequest,
    ActionSheetsResult,
    CharacterBackend,
    PortraitRequest,
    PortraitResult,
    WalkingSheetRequest,
    WalkingSheetResult,
)


class _FakeBackend:
    """Minimal struct-subtype of CharacterBackend for type checking."""

    def generate_portrait(self, req: PortraitRequest) -> PortraitResult:
        return PortraitResult(path=Path("/fake/portrait.png"))

    def generate_walking_sheet(self, req: WalkingSheetRequest) -> WalkingSheetResult:
        return WalkingSheetResult(sheet_path=Path("/fake/walk.png"), dims={})

    def generate_action_sheets(self, req: ActionSheetsRequest) -> ActionSheetsResult:
        return ActionSheetsResult(sheets={})


def test_fake_backend_satisfies_protocol():
    """A class implementing the three methods structurally satisfies CharacterBackend."""
    backend: CharacterBackend = _FakeBackend()
    result = backend.generate_portrait(
        PortraitRequest(prompt="test", reference=None, output_dir=Path("/tmp"))
    )
    assert result.path == Path("/fake/portrait.png")
