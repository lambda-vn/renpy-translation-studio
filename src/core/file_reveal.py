"""Opens the desktop file manager on one file, per platform."""

import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


class RevealError(Exception):
    """Raised when the desktop file manager could not be opened."""


def _reveal_command(path: Path) -> list[str]:
    """Return the argument list opening a file manager on a given file.

    Windows and macOS each have a single command that selects the file.
    Linux has no such command: file managers disagree on the flag, so
    this asks through the freedesktop.org FileManager1 D-Bus interface
    instead, implemented by Nautilus, Nemo, Dolphin and PCManFM. When no
    file manager answers on the session bus, the caller falls back to
    opening the containing folder with xdg-open.

    Args:
        path: The file to reveal, already resolved.

    Returns:
        The command as an argument list, never a shell string.
    """
    if sys.platform == "win32":
        return ["explorer", f"/select,{path}"]
    if sys.platform == "darwin":
        return ["open", "-R", str(path)]
    uri = path.resolve().as_uri()
    return [
        "dbus-send",
        "--session",
        "--dest=org.freedesktop.FileManager1",
        "--type=method_call",
        "/org/freedesktop/FileManager1",
        "org.freedesktop.FileManager1.ShowItems",
        f"array:string:{uri}",
        "string:",
    ]


def reveal_in_file_manager(path: Path) -> None:
    """Open the desktop file manager on a file, selecting it where possible.

    On Linux, the D-Bus selection call is tried first; if dbus-send is
    missing or no file manager answers, the containing folder is opened
    with xdg-open instead. On Windows and macOS, the single platform
    command runs directly.

    The return code of the command actually used to reveal the file is
    not checked. Windows Explorer answers 1 on a perfectly successful
    /select, so treating a non-zero code as a failure would report every
    reveal as broken.

    Args:
        path: The file to reveal.

    Raises:
        RevealError: If the file does not exist, or if no file manager
            could be started.
    """
    if not path.is_file():
        raise RevealError(f"No such file: {path}")
    if sys.platform in ("win32", "darwin"):
        _run(_reveal_command(path))
        return
    if not _try_dbus_show(path):
        _run(["xdg-open", str(path.parent)])


def _try_dbus_show(path: Path) -> bool:
    """Attempt to select the file via the FileManager1 D-Bus interface.

    Args:
        path: The file to reveal.

    Returns:
        True once a file manager has answered the ShowItems call, False
        if dbus-send is missing or no service answered on the session bus.
    """
    try:
        result = subprocess.run(_reveal_command(path), shell=False, check=False)
    except OSError:
        return False
    return result.returncode == 0


def _run(command: list[str]) -> None:
    """Run a reveal command, turning a launch failure into a RevealError.

    Args:
        command: The argument list to run, never a shell string.

    Raises:
        RevealError: If the command could not be started.
    """
    try:
        subprocess.run(command, shell=False, check=False)
    except OSError as exc:
        logger.warning("Cannot open the file manager: %s", exc)
        raise RevealError(str(exc)) from exc
