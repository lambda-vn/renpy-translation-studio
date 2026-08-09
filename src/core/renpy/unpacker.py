"""Selective extraction of .rpy sources from .rpa archives.

The Ren'Py SDK's translate command only sees files that exist on disk: a
script packed inside an .rpa is invisible to it. Writing the .rpy members
of every archive in game/ back onto disk, without ever overwriting what is
already there, makes the SDK's own extraction see them.

Ren'Py's engine, unlike the file-listing translate() itself uses, loads a
script from disk and from an archive as two distinct sources with no
deduplication: with both present it fails every label they share as
"defined twice". disable_extracted_archives() renames a script-only
archive out of the way for the run, restore_disabled_archives() puts it
back; a mixed archive (script and image/audio members together) is left
in place, since renaming it would break the resources it also holds.
"""

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from core.renpy.archive import ArchiveError, RpaArchive
from core.validators import resolve_safe_path

logger = logging.getLogger(__name__)

_MANIFEST_RELATIVE_PATH = Path(".rts") / "unpacked_sources.json"
_EXTRACTABLE_SUFFIXES = {".rpy", ".rpym"}
_SCRIPT_SUFFIXES = {".rpy", ".rpym", ".rpyc", ".rpymc"}
_DISABLED_SUFFIX = ".disabled"


@dataclass
class UnpackedEntry:
    """A single source file extracted from an .rpa archive."""

    path: str
    rpyc_preexisted: bool


@dataclass
class DisabledArchive:
    """An archive temporarily renamed out of Ren'Py's search path."""

    archive: str
    temp_name: str


@dataclass
class _Manifest:
    """Parsed content of the unpacked-sources manifest."""

    entries: list[UnpackedEntry] = field(default_factory=list)
    disabled_archives: list[DisabledArchive] = field(default_factory=list)


def unpack_archived_sources(project_path: Path) -> list[UnpackedEntry]:
    """Extract .rpy/.rpym members of every .rpa archive in game/ to disk.

    Restores any archive a previous, interrupted run left disabled before
    scanning: a renamed archive does not match the game/*.rpa glob, so
    without this the game would stay broken by a crash this application
    caused, and this run would not see that archive's members either.

    Members under tl/ are skipped, since they carry translations bundled
    by the game's own build and not sources to translate. A member is
    also skipped whenever a file already sits at its target path: the
    manifest only ever records files this function itself created, so a
    second run is safe to repeat.

    Args:
        project_path: Path to the Ren'Py project root.

    Returns:
        Every UnpackedEntry known after this run, including ones created
        by a previous run.

    Raises:
        ArchiveError: If an archive is malformed, or a member name would
            resolve outside of game/.
    """
    restore_disabled_archives(project_path)

    game_dir = project_path / "game"
    manifest_path = project_path / _MANIFEST_RELATIVE_PATH
    manifest = _read_manifest(manifest_path)
    entries_by_path = {entry.path: entry for entry in manifest.entries}

    for archive_path in sorted(game_dir.glob("*.rpa")):
        with RpaArchive.open(archive_path) as archive:
            for name in archive.names():
                if not _is_extractable(name):
                    continue
                target = _resolve_target(game_dir, name)
                if target.exists():
                    continue
                rpyc_target = target.with_suffix(".rpyc")
                rpyc_preexisted = rpyc_target.exists()
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(name))
                entries_by_path[name] = UnpackedEntry(
                    path=name, rpyc_preexisted=rpyc_preexisted
                )

    entries = sorted(entries_by_path.values(), key=_entry_path)
    if entries or manifest.disabled_archives:
        _write_manifest(
            manifest_path,
            _Manifest(entries=entries, disabled_archives=manifest.disabled_archives),
        )
    return entries


def archives_contain_compiled_scripts(project_path: Path) -> bool:
    """Check whether game/'s archives hold a compiled script (.rpyc).

    Tells apart a game with no archived scripts at all, the common case
    where extraction has nothing to do, from one shipping only bytecode:
    no amount of extraction recovers a source from a .rpyc, a decompiler
    would be needed instead.

    Args:
        project_path: Path to the Ren'Py project root.

    Returns:
        True if any archive in game/ contains a .rpyc member outside tl/.
    """
    game_dir = project_path / "game"
    for archive_path in sorted(game_dir.glob("*.rpa")):
        with RpaArchive.open(archive_path) as archive:
            for name in archive.names():
                if name.split("/", 1)[0] == "tl":
                    continue
                if Path(name).suffix == ".rpyc":
                    return True
    return False


def disable_extracted_archives(project_path: Path) -> list[str]:
    """Rename each script-only archive whose sources were unpacked.

    Must only run once every archive has been fully unpacked: renaming
    makes the whole archive unreadable for the duration, not just the
    members that were extracted from it, so a partially-unpacked archive
    renamed early would lose the rest of its own content.

    Only an archive holding nothing but script files (.rpy, .rpym, and
    their compiled forms) is renamed. A mixed archive keeps its images or
    audio reachable by staying in place; a source it produced that Ren'Py
    then reports as defined twice falls back to the ordinary
    discard-and-retry an unparseable source already goes through.

    Args:
        project_path: Path to the Ren'Py project root.

    Returns:
        The archive names (relative to game/) that were renamed.

    Raises:
        ArchiveError: If an archive is malformed.
    """
    game_dir = project_path / "game"
    manifest_path = project_path / _MANIFEST_RELATIVE_PATH
    manifest = _read_manifest(manifest_path)
    unpacked_names = {entry.path for entry in manifest.entries}

    renamed: list[str] = []
    for archive_path in sorted(game_dir.glob("*.rpa")):
        with RpaArchive.open(archive_path) as archive:
            names = archive.names()
        if not any(name in unpacked_names for name in names):
            continue
        if not all(Path(name).suffix in _SCRIPT_SUFFIXES for name in names):
            continue

        temp_path = _disabled_path(archive_path)
        archive_path.rename(temp_path)
        manifest.disabled_archives.append(
            DisabledArchive(archive=archive_path.name, temp_name=temp_path.name)
        )
        renamed.append(archive_path.name)

    if renamed:
        _write_manifest(manifest_path, manifest)
    return renamed


def restore_disabled_archives(project_path: Path) -> None:
    """Rename every archive disable_extracted_archives() renamed, back.

    Must run whether the SDK run that followed succeeded or failed: the
    game itself reads these archives too, and nothing outside this
    application knows to look for the temporary name. Safe to call when
    nothing is disabled.

    Args:
        project_path: Path to the Ren'Py project root.
    """
    game_dir = project_path / "game"
    manifest_path = project_path / _MANIFEST_RELATIVE_PATH
    manifest = _read_manifest(manifest_path)
    if not manifest.disabled_archives:
        return

    still_disabled: list[DisabledArchive] = []
    for disabled in manifest.disabled_archives:
        temp_path = game_dir / disabled.temp_name
        original_path = game_dir / disabled.archive
        if temp_path.is_file():
            temp_path.rename(original_path)
        elif not original_path.is_file():
            logger.warning(
                "Archive %s is missing under both its own and its disabled name",
                disabled.archive,
            )
            still_disabled.append(disabled)

    manifest.disabled_archives = still_disabled
    _write_manifest(manifest_path, manifest)


def discard_unpacked_files(project_path: Path, names: Iterable[str]) -> list[str]:
    """Remove named sources this module unpacked, forgetting them.

    Meant for the .rpy the Ren'Py SDK refuses to parse. A game shipping
    a source its own engine cannot compile blocks the whole run, since
    Ren'Py loads every script before generating anything; dropping the
    file lets the archived .rpyc take over, which is what ran before any
    of this and still runs the game.

    A name absent from the manifest is ignored rather than deleted, so
    an error blaming one of the game's own files never removes it. That
    check is what makes the caller free to pass paths read out of SDK
    output.

    Args:
        project_path: Path to the Ren'Py project root.
        names: Paths as Ren'Py reports them, relative to the project
            root ('game/x.rpy') or to game/ ('x.rpy').

    Returns:
        The manifest-relative paths actually removed.
    """
    game_dir = project_path / "game"
    manifest_path = project_path / _MANIFEST_RELATIVE_PATH
    manifest = _read_manifest(manifest_path)
    by_path = {entry.path: entry for entry in manifest.entries}

    discarded: list[str] = []
    for name in names:
        normalized = name.replace("\\", "/").removeprefix("game/")
        entry = by_path.get(normalized)
        if entry is None:
            continue
        target = _resolve_target(game_dir, entry.path)
        if not entry.rpyc_preexisted:
            _try_unlink(target.with_suffix(".rpyc"))
        if not _try_unlink(target):
            continue
        del by_path[normalized]
        discarded.append(normalized)

    if discarded:
        manifest.entries = sorted(by_path.values(), key=_entry_path)
        _write_manifest(manifest_path, manifest)
    return discarded


def remove_unpacked_sources(project_path: Path) -> None:
    """Remove every source file created by unpack_archived_sources().

    Restores any archive still disabled first: this is meant to run once
    a translation has been exported and nothing is expected to still be
    mid-run, but an archive left renamed would otherwise break the game
    permanently, which outweighs leaving it be on the chance something
    else is still using it.

    A .rpyc compiled from a freshly extracted .rpy is removed alongside
    it, but only when the manifest recorded that no .rpyc sat there
    before extraction: one that already existed belongs to the project,
    not to us. Directories left empty by the removal are pruned, but
    game/ itself is never removed.

    A file that cannot be deleted (open elsewhere) stays in the manifest
    instead of being silently forgotten, so a later call can still find
    and remove it.

    Args:
        project_path: Path to the Ren'Py project root.
    """
    restore_disabled_archives(project_path)

    game_dir = project_path / "game"
    manifest_path = project_path / _MANIFEST_RELATIVE_PATH
    manifest = _read_manifest(manifest_path)

    remaining: list[UnpackedEntry] = []
    parent_dirs: set[Path] = set()
    for entry in manifest.entries:
        target = _resolve_target(game_dir, entry.path)
        if not entry.rpyc_preexisted:
            _try_unlink(target.with_suffix(".rpyc"))
        if _try_unlink(target):
            parent_dirs.add(target.parent)
        else:
            remaining.append(entry)

    for directory in sorted(
        parent_dirs, key=lambda path: len(path.parts), reverse=True
    ):
        _prune_empty_directories(directory, game_dir)

    if remaining:
        _write_manifest(manifest_path, _Manifest(entries=remaining))
    elif manifest_path.exists():
        manifest_path.unlink()


def _entry_path(entry: UnpackedEntry) -> str:
    """Return an entry's path, for sorting a manifest."""
    return entry.path


def _is_extractable(name: str) -> bool:
    """Return True for a .rpy/.rpym member that is not under tl/.

    Args:
        name: A member name already validated by RpaArchive.

    Returns:
        True if the member should be extracted.
    """
    if name.split("/", 1)[0] == "tl":
        return False
    return Path(name).suffix in _EXTRACTABLE_SUFFIXES


def _resolve_target(game_dir: Path, name: str) -> Path:
    """Resolve an archive member name to a path inside game/.

    Member names are already validated by RpaArchive against traversal,
    but writing to disk is the point of no return, so it is checked
    again here, the same way exporter.py double-checks zip entries.

    Args:
        game_dir: The project's game/ directory.
        name: A member name already validated by RpaArchive.

    Returns:
        The absolute target path.

    Raises:
        ArchiveError: If the resolved path would escape game/.
    """
    try:
        return resolve_safe_path(str(game_dir / name), base=game_dir)
    except ValueError as exc:
        raise ArchiveError(f"Unsafe member path: {name}") from exc


def _disabled_path(archive_path: Path) -> Path:
    """Return an unused name for temporarily disabling an archive.

    Args:
        archive_path: The archive's current path.

    Returns:
        A sibling path that does not currently exist.
    """
    candidate = archive_path.with_name(archive_path.name + _DISABLED_SUFFIX)
    attempt = 1
    while candidate.exists():
        candidate = archive_path.with_name(
            f"{archive_path.name}{_DISABLED_SUFFIX}.{attempt}"
        )
        attempt += 1
    return candidate


def _try_unlink(path: Path) -> bool:
    """Delete a file if present, logging rather than raising on failure.

    A locked file (the game running, an editor open on it) must not abort
    a whole cleanup pass and leave the manifest out of step with what is
    actually still on disk.

    Args:
        path: File to delete.

    Returns:
        True if the file is gone afterward, False if it is still there
        because deletion failed.
    """
    if not path.exists():
        return True
    try:
        path.unlink()
    except OSError:
        logger.warning("Could not remove %s", path, exc_info=True)
        return False
    return True


def _prune_empty_directories(directory: Path, boundary: Path) -> None:
    """Remove directory and its now-empty ancestors, stopping at boundary.

    Args:
        directory: Directory to remove if empty.
        boundary: Directory that is never removed, even if empty.
    """
    current = directory
    while current != boundary and boundary in current.parents:
        if not current.is_dir() or any(current.iterdir()):
            return
        current.rmdir()
        current = current.parent


def _read_manifest(manifest_path: Path) -> _Manifest:
    """Read a previously written unpacked-sources manifest, if any.

    Args:
        manifest_path: Path to the manifest file.

    Returns:
        The manifest's content, or an empty one if absent or unreadable.
    """
    if not manifest_path.is_file():
        return _Manifest()
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        logger.warning("Could not read manifest %s", manifest_path, exc_info=True)
        return _Manifest()
    if not isinstance(raw, dict):
        logger.warning("Manifest %s is not a JSON object, ignoring it", manifest_path)
        return _Manifest()

    raw_entries = raw.get("entries", [])
    entries: list[UnpackedEntry] = []
    for item in raw_entries:
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        rpyc_preexisted = item.get("rpyc_preexisted")
        if isinstance(path, str) and isinstance(rpyc_preexisted, bool):
            entries.append(UnpackedEntry(path=path, rpyc_preexisted=rpyc_preexisted))
    if len(entries) != len(raw_entries):
        logger.warning(
            "Manifest %s: %d of %d entries had an unexpected shape and were dropped",
            manifest_path,
            len(raw_entries) - len(entries),
            len(raw_entries),
        )

    disabled_archives: list[DisabledArchive] = []
    for item in raw.get("disabled_archives", []):
        if not isinstance(item, dict):
            continue
        archive = item.get("archive")
        temp_name = item.get("temp_name")
        if isinstance(archive, str) and isinstance(temp_name, str):
            disabled_archives.append(
                DisabledArchive(archive=archive, temp_name=temp_name)
            )

    logger.debug(
        "Read manifest %s: %d entries, %d disabled archives",
        manifest_path,
        len(entries),
        len(disabled_archives),
    )
    return _Manifest(entries=entries, disabled_archives=disabled_archives)


def _write_manifest(manifest_path: Path, manifest: _Manifest) -> None:
    """Write the unpacked-sources manifest.

    Args:
        manifest_path: Path to the manifest file.
        manifest: Content to persist.
    """
    logger.debug(
        "Writing manifest %s: %d entries, %d disabled archives",
        manifest_path,
        len(manifest.entries),
        len(manifest.disabled_archives),
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "entries": [
            {"path": entry.path, "rpyc_preexisted": entry.rpyc_preexisted}
            for entry in manifest.entries
        ],
        "disabled_archives": [
            {"archive": disabled.archive, "temp_name": disabled.temp_name}
            for disabled in manifest.disabled_archives
        ],
    }
    manifest_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
