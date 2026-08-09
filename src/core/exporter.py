"""Translation zip exporter."""

import re
import zipfile
from pathlib import Path

_GAME_NAME_SANITIZE = re.compile(r"[^a-zA-Z0-9_\-]")
_BUILD_NAME = re.compile(r'build\.name\s*=\s*["\']([^"\']+)["\']')


class GameNameResolver:
    """Resolves the game name from a Ren'Py project directory."""

    def resolve(self, project_path: Path) -> str:
        """Determine and sanitize the game name.

        Reads 'build.name' from options.rpy if available; falls back to the
        directory name.

        Args:
            project_path: Path to the Ren'Py project root.

        Returns:
            A sanitized game name safe for use in file and zip paths.
        """
        name = self._read_build_name(project_path) or project_path.name
        return _GAME_NAME_SANITIZE.sub("-", name)

    def _read_build_name(self, project_path: Path) -> str | None:
        """Attempt to read build.name from game/options.rpy.

        Args:
            project_path: Path to the Ren'Py project root.

        Returns:
            The build name string, or None if not found or unreadable.
        """
        options = project_path / "game" / "options.rpy"
        if not options.is_file():
            return None
        try:
            content = options.read_text(encoding="utf-8")
        except OSError:
            return None
        m = _BUILD_NAME.search(content)
        return m.group(1) if m else None


class TranslationZipExporter:
    """Exports a translation directory as a structured zip archive."""

    def export(
        self,
        tl_dir: Path,
        game_name: str,
        language: str,
        output_path: Path,
    ) -> None:
        """Build a zip archive from a translation language directory.

        The zip structure follows: <game_name>/game/tl/<language>/<file>.

        Args:
            tl_dir: Path to the tl/<language>/ directory to archive.
            game_name: Sanitized game name used as the zip root prefix.
            language: Target language code (e.g. "french").
            output_path: Destination .zip file path.

        Raises:
            ValueError: If a path traversal is detected in zip entries.
        """
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for src in sorted(tl_dir.rglob("*")):
                if not src.is_file():
                    continue
                if src.suffix == ".rpyc":
                    continue
                rel = src.relative_to(tl_dir)
                if ".." in rel.parts:
                    raise ValueError(f"Path traversal detected: {rel}")
                arc_name = f"{game_name}/game/tl/{language}/{rel.as_posix()}"
                zf.write(src, arc_name)
