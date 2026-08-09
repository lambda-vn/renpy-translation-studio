"""Global registry of recently parsed projects.

Stores only the absolute paths of projects that have been extracted or
resumed, as a JSON list in the application config directory (next to
settings.json). All display data (game name, language, counts) is read live
from each project's own database and is never duplicated here.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from core.app_dirs import config_dir

_logger = logging.getLogger(__name__)


class RecentProjects:
    """Read/write the list of recently parsed project paths."""

    def __init__(self, path: Path | None = None) -> None:
        """Initialize the registry.

        Args:
            path: Location of the JSON file. Defaults to
                <config_dir>/projects.json.
        """
        self._path = path or config_dir() / "projects.json"

    def all(self) -> list[Path]:
        """Return the stored project paths, most recently added first.

        A missing or unreadable file yields an empty list rather than raising.

        Returns:
            The stored project paths.
        """
        if not self._path.is_file():
            return []
        try:
            with self._path.open(encoding="utf-8") as f:
                raw = json.load(f)
        except (json.JSONDecodeError, OSError):
            _logger.warning("Could not read recent projects file: %s", self._path)
            return []
        if not isinstance(raw, list):
            return []
        return [Path(entry) for entry in raw if isinstance(entry, str)]

    def add(self, project: Path) -> None:
        """Register a project path, moving it to the front if already present.

        Args:
            project: The Ren'Py project root path to remember.
        """
        resolved = str(project.resolve())
        entries = [str(p) for p in self.all() if str(p) != resolved]
        entries.insert(0, resolved)
        self._save(entries)

    def remove(self, project: Path) -> None:
        """Drop a project path from the registry.

        Args:
            project: The Ren'Py project root path to forget.
        """
        resolved = str(project.resolve())
        entries = [str(p) for p in self.all() if str(p) != resolved]
        self._save(entries)

    def _save(self, entries: list[str]) -> None:
        """Persist the given path list to disk.

        Args:
            entries: Absolute project paths, ordered most recent first.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2, ensure_ascii=False)


recent_projects = RecentProjects()
