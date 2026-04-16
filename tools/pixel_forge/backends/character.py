"""CharacterBackend protocol for the person-bundle pipeline.

Defines three pipe-specific methods matching the bundle's portrait,
walking-sheet, and action-sheets stages. Each backend (Gemini, PixelLab)
implements all three. The legacy ImageBackend (in base.py) continues to
serve animal/decoration flows unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class PortraitRequest:
    prompt: str
    reference: Path | None
    output_dir: Path


@dataclass(frozen=True)
class PortraitResult:
    path: Path


@dataclass(frozen=True)
class WalkingSheetRequest:
    prompt: str
    reference: Path | None
    output_dir: Path
    profile_id: str = "person-premade"


@dataclass(frozen=True)
class WalkingSheetResult:
    sheet_path: Path
    dims: dict


@dataclass(frozen=True)
class ActionSheetsRequest:
    prompt: str
    reference: Path | None
    output_dir: Path
    actions: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ActionSheetsResult:
    sheets: dict[str, Path]


class CharacterBackend(Protocol):
    def generate_portrait(self, req: PortraitRequest) -> PortraitResult: ...
    def generate_walking_sheet(self, req: WalkingSheetRequest) -> WalkingSheetResult: ...
    def generate_action_sheets(self, req: ActionSheetsRequest) -> ActionSheetsResult: ...
