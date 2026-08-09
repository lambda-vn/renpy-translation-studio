"""Wrapper for the Ren'Py SDK CLI."""

import re
import subprocess
from pathlib import Path

from core.i18n import i18n

_ERROR_FILE = re.compile(r'File "([^"]+)", line \d+')


class RenpyCliError(Exception):
    """Raised when the Ren'Py SDK CLI command fails."""


def parse_failed_files(output: str) -> list[str]:
    """Return the script paths Ren'Py blamed in a failed run.

    Ren'Py reports a parse error as 'File "game/x.rpy", line 12: ...',
    naming the same file once per error. The paths are relative to the
    project root and use forward slashes.

    Args:
        output: Combined stdout and stderr of the failed SDK run.

    Returns:
        Each blamed path once, in the order Ren'Py first reported it.
    """
    seen: dict[str, None] = {}
    for match in _ERROR_FILE.finditer(output):
        seen.setdefault(match.group(1), None)
    return list(seen)


class RenpyCli:
    """Wrapper around the Ren'Py SDK subprocess."""

    def translate(self, sdk_path: Path, project_path: Path, language: str) -> None:
        """Run the Ren'Py SDK translation command.

        Args:
            sdk_path: Path to the Ren'Py SDK executable.
            project_path: Path to the Ren'Py project root.
            language: Target language code (e.g. "french").

        Raises:
            RenpyCliError: If the SDK command exits with a non-zero code.
        """
        result = subprocess.run(
            [str(sdk_path), str(project_path), "translate", language],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            prefix = i18n.t("renpy.sdk_failed").format(code=result.returncode)
            output = "\n".join(
                part for part in (result.stdout, result.stderr) if part.strip()
            )
            raise RenpyCliError(f"{prefix}\n{output}" if output else prefix)
