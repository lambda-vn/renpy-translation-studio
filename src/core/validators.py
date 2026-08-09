"""Input validation utilities."""

import re
from pathlib import Path

from core.languages import get_language

LANGUAGE_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,31}$")


class ValidationError(ValueError):
    """Raised when user input fails validation."""


def validate_language_code(code: str) -> bool:
    """Validate a Ren'Py language code against the allowed pattern.

    Args:
        code: The language identifier to validate (e.g. "french").

    Returns:
        True if the code is valid, False otherwise.
    """
    return bool(LANGUAGE_CODE_PATTERN.match(code))


def is_recognized_language(code: str) -> bool:
    """Check whether code is a language providers know how to translate.

    The target language field doubles as the Ren'Py tl/<language>/ folder
    name, so it accepts any filename-safe string (see
    validate_language_code()) — not necessarily a real language. Machine
    translation and LLM providers only know the fixed set of languages
    declared in core.languages, so this catches the mismatch before a job
    silently fails (DeepL) or quietly degrades (an LLM guessing at an
    unrecognized name).

    Args:
        code: The language identifier to check (e.g. "french").

    Returns:
        True if code is a language providers can translate to/from.
    """
    return get_language(code) is not None


def resolve_safe_path(user_path: str, base: Path | None = None) -> Path:
    """Resolve and validate a path, raising if it escapes the base directory.

    Args:
        user_path: The user-provided path string.
        base: If provided, the resolved path must reside within this base.

    Returns:
        The resolved absolute Path.

    Raises:
        ValueError: If the resolved path escapes the base directory.
    """
    resolved = Path(user_path).resolve()
    if base is not None:
        base_resolved = base.resolve()
        if not resolved.is_relative_to(base_resolved):
            raise ValueError(f"Path traversal detected: {user_path}")
    return resolved


def validate_project_dir(path: Path) -> bool:
    """Check whether a directory looks like a valid Ren'Py project.

    A Ren'Py project root contains a 'game/' subdirectory.

    Args:
        path: The candidate project directory.

    Returns:
        True if the directory appears to be a Ren'Py project.
    """
    return path.is_dir() and (path / "game").is_dir()
