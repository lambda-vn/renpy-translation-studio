"""Where the machine-wide application files live.

settings.json, the recent-project registry and the translation memory all
share one directory, common to every project of the machine.

That directory used to be spelled `user_config_dir(APP_NAME)`, which on
Windows repeats the name (`<appname>/<appname>`): the second argument of
user_config_dir is the app author, and it falls back to the app name when
left out. Passing `appauthor=False` drops the repetition, but it also
moves the directory, so whatever the old one holds is carried over the
first time the new one is asked for. Without that, an existing install
would come back with no recent projects, an empty translation memory and
default settings, all three still on disk one folder away.

Linux and macOS ignore the app author entirely, so both spellings name the
same directory there and the migration is a no-op.

The move has to happen before anything reads a file, and `core.settings`
builds its singleton at import time, so it cannot wait for the
application to start: config_dir() migrates on its first call and caches
the answer.
"""

from __future__ import annotations

import contextlib
import logging
import shutil
from functools import cache
from pathlib import Path

from platformdirs import user_config_dir

APP_NAME = "renpy-translation-studio"

_logger = logging.getLogger(__name__)


@cache
def config_dir() -> Path:
    """Return the directory holding the machine-wide application files.

    The directory is not created here. Every writer already creates it on
    its way to a file, and creating it eagerly would run at import time,
    through the settings singleton: a config location that cannot be
    written would then stop the application from starting, where it used
    to only mean falling back to the defaults.

    Returns:
        The config directory, with anything the pre-migration directory
        still held moved into it.
    """
    current = Path(user_config_dir(APP_NAME, appauthor=False))
    migrate_legacy_files(Path(user_config_dir(APP_NAME)), current)
    return current


def migrate_legacy_files(legacy: Path, current: Path) -> None:
    """Move whatever the old config directory still holds into the new one.

    Every entry is moved, rather than a known list of names, so a file
    added since is carried over too. An entry whose name already exists in
    the new directory is left behind: the new one is what the application
    has been writing to, and overwriting it would trade live data for a
    stale copy.

    A failed move is logged and skipped rather than raised. The worst case
    is one setting falling back to its default, which is no reason to stop
    the application from starting.

    The listing is taken before the first move: iterdir() enumerates
    lazily, and removing entries from the directory being walked leaves
    Windows free to skip the ones that follow.

    Args:
        legacy: The directory the files used to live in. On Windows it is
            a subdirectory of `current`; elsewhere it is `current` itself,
            in which case there is nothing to do.
        current: The directory they live in now.
    """
    if legacy == current or not legacy.is_dir():
        return

    for entry in list(legacy.iterdir()):
        destination = current / entry.name
        if destination.exists():
            continue
        try:
            shutil.move(str(entry), str(destination))
        except OSError:
            _logger.warning(
                'Could not move "%s" to "%s"', entry, destination, exc_info=True
            )

    with contextlib.suppress(OSError):
        legacy.rmdir()
