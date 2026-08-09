"""Tests for core/app_dirs.py."""

from pathlib import Path

from core.app_dirs import migrate_legacy_files


def _legacy_install(root: Path) -> tuple[Path, Path]:
    """Lay out a pre-migration Windows install under root.

    Returns:
        Tuple of (legacy directory, current directory), the legacy one
        being a subdirectory of the current one as platformdirs spells it.
    """
    current = root / "renpy-translation-studio"
    legacy = current / "renpy-translation-studio"
    legacy.mkdir(parents=True)
    return legacy, current


def test_files_are_carried_over(tmp_path: Path) -> None:
    legacy, current = _legacy_install(tmp_path)
    (legacy / "settings.json").write_text('{"locale": "fr"}', encoding="utf-8")
    (legacy / "memory.db").write_bytes(b"sqlite")

    migrate_legacy_files(legacy, current)

    assert (current / "settings.json").read_text(encoding="utf-8") == '{"locale": "fr"}'
    assert (current / "memory.db").read_bytes() == b"sqlite"
    assert not legacy.exists()


def test_no_entry_is_left_behind(tmp_path: Path) -> None:
    """Moving entries must not make the walk skip the ones that follow."""
    legacy, current = _legacy_install(tmp_path)
    names = [f"file_{index}.json" for index in range(20)]
    for name in names:
        (legacy / name).write_text("{}", encoding="utf-8")

    migrate_legacy_files(legacy, current)

    assert sorted(entry.name for entry in current.iterdir()) == sorted(names)


def test_unknown_files_are_carried_over_too(tmp_path: Path) -> None:
    legacy, current = _legacy_install(tmp_path)
    (legacy / "something_added_later.json").write_text("[]", encoding="utf-8")

    migrate_legacy_files(legacy, current)

    assert (current / "something_added_later.json").is_file()


def test_existing_files_are_never_overwritten(tmp_path: Path) -> None:
    legacy, current = _legacy_install(tmp_path)
    (legacy / "settings.json").write_text("stale", encoding="utf-8")
    (current / "settings.json").write_text("live", encoding="utf-8")

    migrate_legacy_files(legacy, current)

    assert (current / "settings.json").read_text(encoding="utf-8") == "live"
    assert (legacy / "settings.json").read_text(encoding="utf-8") == "stale"


def test_legacy_directory_is_kept_when_something_stayed(tmp_path: Path) -> None:
    legacy, current = _legacy_install(tmp_path)
    (legacy / "settings.json").write_text("stale", encoding="utf-8")
    (current / "settings.json").write_text("live", encoding="utf-8")

    migrate_legacy_files(legacy, current)

    assert legacy.is_dir()


def test_nothing_happens_without_a_legacy_directory(tmp_path: Path) -> None:
    current = tmp_path / "renpy-translation-studio"
    current.mkdir()

    migrate_legacy_files(current / "renpy-translation-studio", current)

    assert list(current.iterdir()) == []


def test_same_directory_is_left_alone(tmp_path: Path) -> None:
    """On Linux and macOS both spellings name the same directory."""
    current = tmp_path / "renpy-translation-studio"
    current.mkdir()
    (current / "settings.json").write_text("live", encoding="utf-8")

    migrate_legacy_files(current, current)

    assert (current / "settings.json").read_text(encoding="utf-8") == "live"
    assert current.is_dir()
