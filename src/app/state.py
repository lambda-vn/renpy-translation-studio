"""Global application state."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from core.renpy.parser import TranslationBlock
from core.storage.database import Database


@dataclass
class AppState:
    """Shared mutable state passed between views."""

    project_path: Path | None = None
    source_language: str = "english"
    target_language: str = ""
    sdk_path: str = ""
    game_name: str = ""
    blocks: list[TranslationBlock] = field(default_factory=list)
    tl_output_dir: Path | None = None
    db: Database | None = None
