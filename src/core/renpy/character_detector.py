"""Heuristic scanner for Ren'Py Character() definitions."""

import re
from dataclasses import dataclass
from pathlib import Path

CHARACTER_PATTERNS = [
    re.compile(r'define\s+(\w+)\s*=\s*Character\(\s*[_(]*["\']([^"\']+)["\']'),
    re.compile(r'^(\w+)\s*=\s*Character\(\s*[_(]*["\']([^"\']+)["\']', re.MULTILINE),
]


@dataclass
class DetectedCharacter:
    """A character definition found while scanning source files."""

    variable: str
    display_name: str
    source_file: str


class CharacterDetector:
    """Scans .rpy source files for Character() definitions.

    Results are heuristic — the user must confirm them before they are saved.
    Does not scan tl/ directories.
    """

    def detect(self, game_path: Path) -> list[DetectedCharacter]:
        """Return all detected characters across all .rpy source files.

        Args:
            game_path: Path to the Ren'Py project root.

        Returns:
            One DetectedCharacter per unique variable found, first match wins.
        """
        results: dict[str, DetectedCharacter] = {}
        source_dir = game_path / "game"
        tl_dir = source_dir / "tl"

        for rpy_file in source_dir.rglob("*.rpy"):
            if tl_dir in rpy_file.parents:
                continue
            content = rpy_file.read_text(encoding="utf-8", errors="ignore")
            for pattern in CHARACTER_PATTERNS:
                for match in pattern.finditer(content):
                    variable, display_name = match.group(1), match.group(2)
                    if variable not in results:
                        results[variable] = DetectedCharacter(
                            variable=variable,
                            display_name=display_name,
                            source_file=str(rpy_file.relative_to(game_path)),
                        )
        return list(results.values())
