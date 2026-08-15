"""Refusal to start rather than fail on a Windows path length limit.

Windows refuses a path longer than 260 characters. The deepest file a
packaged build ships spends 141 of them on its own name, a generated
mistralai model, and the rest is whatever folder the user unpacked into.
Over budget, Python does not report a path it could not open: it reports
a missing module, naming a dependency nobody touched and saying nothing
about the length of anything.

The check therefore has to run before the import that would fail, which
is why main.py calls it above its own imports rather than from main().
Nothing here imports the packages at risk.
"""

import sys
from pathlib import PureWindowsPath

from core.i18n import i18n
from core.settings import settings

USABLE_PATH_LENGTH = 259
"""Longest path Windows accepts, the documented 260 counting the null."""

LONGEST_SHIPPED_RELATIVE_PATH = 141
"""Length of the deepest path shipped, relative to site-packages.

Measured on the v0.1.0 Windows archive. A build ships the compiled twin
of a module rather than its source, so the shipped name is one character
longer than the same path in a development environment, which is what
tests/test_path_budget.py accounts for when it checks this value against
the packages actually installed.
"""

_MESSAGE_BOX_ERROR_ICON = 0x10


def _site_packages() -> PureWindowsPath | None:
    """Return the site-packages directory this process imports from.

    Read as a Windows path whatever system is running, since a Windows
    path is the only thing this module has an opinion about. Read as the
    local flavour instead, a backslash would stop being a separator off
    Windows and the tests could no longer state the case they cover.

    Returns:
        The directory, or None when no import path looks like one, which
        is the case for an interpreter running from a source checkout
        without a virtual environment.
    """
    for entry in sys.path:
        if entry and PureWindowsPath(entry).name == "site-packages":
            return PureWindowsPath(entry)
    return None


def characters_over_budget() -> int | None:
    """Return how far the deepest shipped file overshoots the limit.

    Returns:
        The number of characters to cut from the install location, or
        None when the system is not Windows, when the import root cannot
        be found, or when the deepest shipped file fits.
    """
    if sys.platform != "win32":
        return None

    root = _site_packages()
    if root is None:
        return None

    needed = len(str(root)) + 1 + LONGEST_SHIPPED_RELATIVE_PATH
    if needed <= USABLE_PATH_LENGTH:
        return None
    return needed - USABLE_PATH_LENGTH


def long_path_message(over: int) -> str:
    """Build the message shown when the install cannot be imported.

    Args:
        over: Characters by which the deepest shipped path overshoots.

    Returns:
        The message, naming the offending directory and how much has to
        go, in the interface language currently loaded.
    """
    root = _site_packages()
    return (
        f"{i18n.t('startup.long_path_body')}\n\n"
        f"{root}\n\n"
        f"{i18n.t('startup.long_path_fix')} {over}"
    )


def refuse_to_start_on_long_path() -> None:
    """Show the problem and stop, when the install cannot be imported.

    A native message box rather than a Flet window: this runs before the
    application exists, and the failure it replaces is one the user would
    otherwise meet as a traceback about a module they have never heard
    of.

    Raises:
        SystemExit: When the path is too long, once the user has
            dismissed the message.
    """
    over = characters_over_budget()
    if over is None:
        return

    i18n.set_locale(settings.get("locale") or "en")

    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            0,
            long_path_message(over),
            i18n.t("startup.long_path_title"),
            _MESSAGE_BOX_ERROR_ICON,
        )
    raise SystemExit(1)
