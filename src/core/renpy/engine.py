"""Detection of the Ren'Py engine a game ships with.

A packaged Ren'Py game carries its own engine, and that engine answers
the same `translate` command as the SDK. It is also the *right* engine
by construction: it is the version the game's sources were written for.
The SDK installed on the machine is some other version, and Ren'Py 8
refuses screen syntax Ren'Py 7 accepted (a property without a value),
so extracting a Ren'Py 7 game with the SDK 8 loses every line of the
sources it rejects.

Measured on Stormside v0.23.1.4, a Ren'Py 7.5.3 game: the SDK 8.5.3
rejects three sources and parses 40 739 units, the game's own engine
rejects none and parses 40 820.

Finding the launcher is not enough to know it will run: a `-win` build
ships Windows runtimes only. The proof lives in `lib/`, one directory
per platform the build was made for, so that is what gets tested rather
than the mere presence of the executable.
"""

import logging
import sys
from pathlib import Path

from core.i18n import i18n

logger = logging.getLogger(__name__)

_PLATFORM_LABELS = {
    "windows": "Windows",
    "linux": "Linux",
    "mac": "macOS",
}

_LAUNCHER_SUFFIXES = {
    "windows": (".exe", ".sh"),
    "linux": (".sh", ".exe"),
    "mac": (".sh", ".exe"),
}

_FALLBACK_SUFFIXES = (".exe", ".sh")


class EngineNotFoundError(Exception):
    """Raised when no engine can run the extraction on this machine."""


def current_platform() -> str | None:
    """Return the platform token of the running system.

    Returns:
        "windows", "linux" or "mac", or None on anything else, which no
        Ren'Py build ships a runtime for.
    """
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "mac"
    return None


def find_game_launcher(project: Path) -> Path | None:
    """Return the launcher of the game's own engine, if the folder has one.

    The search is ordered by the running platform but never restricted
    to it: a launcher found for another platform is what lets the caller
    say "this is a Windows build" rather than "nothing found here".

    A file only counts as a launcher when a `<stem>.py` sits beside it,
    the entry point every Ren'Py build ships next to its per-platform
    launchers. Without that pairing the choice would come down to
    alphabetical order, so an unrelated executable left in the folder,
    an installer or an unpacking tool, could win it and then be run.

    That `.py` marks the game but is never returned as the launcher: it
    needs the interpreter the wrappers bring along, so handing it to a
    subprocess would rely on a file association on Windows and on an
    execute bit elsewhere.

    A `-32.exe` is skipped: it is the 32-bit twin of the launcher next
    to it, never the only one.

    Args:
        project: The Ren'Py project root path.

    Returns:
        The launcher path, or None when the folder ships no engine.
    """
    if not (project / "renpy").is_dir() or not (project / "lib").is_dir():
        return None
    platform = current_platform()
    suffixes = _LAUNCHER_SUFFIXES.get(platform or "", _FALLBACK_SUFFIXES)
    for suffix in suffixes:
        candidates = sorted(
            path
            for path in project.glob(f"*{suffix}")
            if path.is_file()
            and not path.stem.endswith("-32")
            and path.with_suffix(".py").is_file()
        )
        if candidates:
            return candidates[0]
    return None


def game_platforms(project: Path) -> set[str]:
    """Return the platforms the game's bundled engine can run on.

    Read from the names of the `lib/` subdirectories, which a build
    carries one of per platform it targets: a `-win` build holds
    `py2-windows-i686` and `py2-windows-x86_64`, a `-pc` build adds
    `py3-linux-x86_64`.

    Args:
        project: The Ren'Py project root path.

    Returns:
        The platform tokens found, empty when `lib/` is absent or names
        nothing recognizable.
    """
    lib = project / "lib"
    if not lib.is_dir():
        return set()
    found: set[str] = set()
    for entry in lib.iterdir():
        if not entry.is_dir():
            continue
        name = entry.name.lower()
        found |= {token for token in _PLATFORM_LABELS if token in name}
    return found


def can_use_game_engine(project: Path) -> bool:
    """Check whether the game's own engine is usable for the extraction.

    Args:
        project: The Ren'Py project root path.

    Returns:
        True when the folder ships a launcher and a runtime for the
        running platform.
    """
    if find_game_launcher(project) is None:
        return False
    return current_platform() in game_platforms(project)


def resolve_engine(project: Path, sdk_path: Path | None) -> Path:
    """Return the executable that will run the translate command.

    The game's own engine comes first, the configured SDK is the
    fallback, and the failure names which of the two situations was hit
    so the user knows whether selecting an SDK is what is missing.

    Args:
        project: Validated Ren'Py project root path.
        sdk_path: The SDK executable configured in the settings, if any.

    Returns:
        The launcher of the game's engine, or the SDK executable.

    Raises:
        EngineNotFoundError: If neither is usable on this machine.
    """
    launcher = find_game_launcher(project)
    platforms = game_platforms(project)
    if launcher is not None and current_platform() in platforms:
        logger.info("Using the engine bundled with the game: %s", launcher)
        return launcher
    if sdk_path is not None and sdk_path.is_file():
        logger.info("Using the configured Ren'Py SDK: %s", sdk_path)
        return sdk_path
    if launcher is not None and platforms:
        labels = ", ".join(sorted(_PLATFORM_LABELS[token] for token in platforms))
        raise EngineNotFoundError(
            i18n.t("renpy.engine_wrong_platform").format(platforms=labels)
        )
    raise EngineNotFoundError(i18n.t("renpy.no_engine"))
