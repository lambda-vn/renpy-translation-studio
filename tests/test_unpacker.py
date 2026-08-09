"""Tests for core/renpy/unpacker.py."""

import json
import pickle
import zlib
from pathlib import Path

import pytest

from core.renpy.unpacker import (
    UnpackedEntry,
    archives_contain_compiled_scripts,
    disable_extracted_archives,
    discard_unpacked_files,
    remove_unpacked_sources,
    restore_disabled_archives,
    unpack_archived_sources,
)


def _write_rpa(path: Path, members: dict[str, bytes]) -> None:
    """Write a minimal RPA-2.0 archive (no XOR obfuscation) for tests."""
    header_len = len(f"RPA-2.0 {0:016x}\n".encode())
    body = b""
    index: dict[str, list[tuple[int, int]]] = {}
    for name, data in members.items():
        offset = header_len + len(body)
        index[name] = [(offset, len(data))]
        body += data
    index_offset = header_len + len(body)
    header = f"RPA-2.0 {index_offset:016x}\n".encode()
    index_bytes = zlib.compress(pickle.dumps(index, protocol=2))
    path.write_bytes(header + body + index_bytes)


def _make_project(tmp_path: Path) -> Path:
    """Create a bare Ren'Py project skeleton with an empty game/ dir."""
    project = tmp_path / "my_game"
    (project / "game").mkdir(parents=True)
    return project


class TestUnpackArchivedSources:
    """Tests for unpack_archived_sources."""

    def test_extracts_rpy_and_rpym_only(self, tmp_path: Path) -> None:
        """Only .rpy and .rpym members are written to disk."""
        project = _make_project(tmp_path)
        _write_rpa(
            project / "game" / "scripts.rpa",
            {
                "Script.rpy": b"label start:\n",
                "gui.rpym": b"init python:\n",
                "image.png": b"\x89PNG",
            },
        )
        unpack_archived_sources(project)
        assert (project / "game" / "Script.rpy").read_bytes() == b"label start:\n"
        assert (project / "game" / "gui.rpym").read_bytes() == b"init python:\n"
        assert not (project / "game" / "image.png").exists()

    def test_ignores_tl_members(self, tmp_path: Path) -> None:
        """Members under tl/ are never extracted."""
        project = _make_project(tmp_path)
        _write_rpa(
            project / "game" / "scripts.rpa",
            {"tl/french/common.rpy": b"translate french strings:\n"},
        )
        unpack_archived_sources(project)
        assert not (project / "game" / "tl").exists()

    def test_never_overwrites_existing_file(self, tmp_path: Path) -> None:
        """A file already on disk is left untouched and not tracked."""
        project = _make_project(tmp_path)
        (project / "game" / "Script.rpy").write_bytes(b"already here")
        _write_rpa(project / "game" / "scripts.rpa", {"Script.rpy": b"from archive"})
        entries = unpack_archived_sources(project)
        assert (project / "game" / "Script.rpy").read_bytes() == b"already here"
        assert entries == []

    def test_creates_nested_directories(self, tmp_path: Path) -> None:
        """A member in a subdirectory creates that subdirectory."""
        project = _make_project(tmp_path)
        _write_rpa(
            project / "game" / "scripts.rpa",
            {"Events/scene.rpy": b"label scene:\n"},
        )
        unpack_archived_sources(project)
        assert (
            project / "game" / "Events" / "scene.rpy"
        ).read_bytes() == b"label scene:\n"

    def test_records_rpyc_preexisted_flag(self, tmp_path: Path) -> None:
        """The manifest tracks whether a sibling .rpyc predates extraction."""
        project = _make_project(tmp_path)
        (project / "game" / "Script.rpyc").write_bytes(b"compiled")
        _write_rpa(
            project / "game" / "scripts.rpa",
            {"Script.rpy": b"a", "Menu.rpy": b"b"},
        )
        entries = unpack_archived_sources(project)
        by_path = {entry.path: entry for entry in entries}
        assert by_path["Script.rpy"].rpyc_preexisted is True
        assert by_path["Menu.rpy"].rpyc_preexisted is False

    def test_no_manifest_written_when_nothing_extracted(self, tmp_path: Path) -> None:
        """No manifest file is created when there is nothing to extract."""
        project = _make_project(tmp_path)
        entries = unpack_archived_sources(project)
        assert entries == []
        assert not (project / ".rts" / "unpacked_sources.json").exists()

    def test_manifest_content(self, tmp_path: Path) -> None:
        """The manifest on disk matches the returned entries."""
        project = _make_project(tmp_path)
        _write_rpa(project / "game" / "scripts.rpa", {"Script.rpy": b"a"})
        unpack_archived_sources(project)
        manifest_path = project / ".rts" / "unpacked_sources.json"
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert raw == {
            "entries": [{"path": "Script.rpy", "rpyc_preexisted": False}],
            "disabled_archives": [],
        }

    def test_second_run_does_not_duplicate_entries(self, tmp_path: Path) -> None:
        """Running extraction twice keeps a single entry per file."""
        project = _make_project(tmp_path)
        _write_rpa(project / "game" / "scripts.rpa", {"Script.rpy": b"a"})
        unpack_archived_sources(project)
        entries = unpack_archived_sources(project)
        assert [entry.path for entry in entries] == ["Script.rpy"]

    def test_restores_an_archive_left_disabled_by_a_crash(self, tmp_path: Path) -> None:
        """A leftover .disabled archive is put back before scanning."""
        project = _make_project(tmp_path)
        _write_rpa(project / "game" / "scripts.rpa", {"Script.rpy": b"a"})
        unpack_archived_sources(project)
        disable_extracted_archives(project)
        assert not (project / "game" / "scripts.rpa").exists()

        unpack_archived_sources(project)
        assert (project / "game" / "scripts.rpa").exists()


class TestDisableExtractedArchives:
    """Tests for disable_extracted_archives."""

    def test_renames_a_script_only_archive(self, tmp_path: Path) -> None:
        """An archive holding only scripts is renamed out of the way."""
        project = _make_project(tmp_path)
        _write_rpa(project / "game" / "scripts.rpa", {"Script.rpy": b"a"})
        unpack_archived_sources(project)
        renamed = disable_extracted_archives(project)
        assert renamed == ["scripts.rpa"]
        assert not (project / "game" / "scripts.rpa").exists()
        assert (project / "game" / "scripts.rpa.disabled").is_file()

    def test_leaves_a_mixed_archive_in_place(self, tmp_path: Path) -> None:
        """An archive holding a non-script member is never renamed."""
        project = _make_project(tmp_path)
        _write_rpa(
            project / "game" / "scripts.rpa",
            {"Script.rpy": b"a", "image.png": b"\x89PNG"},
        )
        unpack_archived_sources(project)
        renamed = disable_extracted_archives(project)
        assert renamed == []
        assert (project / "game" / "scripts.rpa").is_file()

    def test_ignores_an_archive_nothing_was_unpacked_from(self, tmp_path: Path) -> None:
        """An archive irrelevant to this run is left alone."""
        project = _make_project(tmp_path)
        _write_rpa(project / "game" / "fonts.rpa", {"font.ttf": b"x"})
        assert disable_extracted_archives(project) == []
        assert (project / "game" / "fonts.rpa").is_file()

    def test_records_the_rename_in_the_manifest(self, tmp_path: Path) -> None:
        """The temporary name is persisted for crash recovery."""
        project = _make_project(tmp_path)
        _write_rpa(project / "game" / "scripts.rpa", {"Script.rpy": b"a"})
        unpack_archived_sources(project)
        disable_extracted_archives(project)
        raw = json.loads(
            (project / ".rts" / "unpacked_sources.json").read_text(encoding="utf-8")
        )
        assert raw["disabled_archives"] == [
            {"archive": "scripts.rpa", "temp_name": "scripts.rpa.disabled"}
        ]


class TestRestoreDisabledArchives:
    """Tests for restore_disabled_archives."""

    def test_renames_the_archive_back(self, tmp_path: Path) -> None:
        """A disabled archive is restored to its original name."""
        project = _make_project(tmp_path)
        _write_rpa(project / "game" / "scripts.rpa", {"Script.rpy": b"a"})
        unpack_archived_sources(project)
        disable_extracted_archives(project)
        restore_disabled_archives(project)
        assert (project / "game" / "scripts.rpa").is_file()
        assert not (project / "game" / "scripts.rpa.disabled").exists()

    def test_clears_the_manifest_entry(self, tmp_path: Path) -> None:
        """A restored archive is no longer tracked as disabled."""
        project = _make_project(tmp_path)
        _write_rpa(project / "game" / "scripts.rpa", {"Script.rpy": b"a"})
        unpack_archived_sources(project)
        disable_extracted_archives(project)
        restore_disabled_archives(project)
        raw = json.loads(
            (project / ".rts" / "unpacked_sources.json").read_text(encoding="utf-8")
        )
        assert raw["disabled_archives"] == []

    def test_noop_when_nothing_is_disabled(self, tmp_path: Path) -> None:
        """Restoring on a project with nothing disabled does not raise."""
        project = _make_project(tmp_path)
        restore_disabled_archives(project)

    def test_idempotent_second_call(self, tmp_path: Path) -> None:
        """Calling restore twice in a row is harmless."""
        project = _make_project(tmp_path)
        _write_rpa(project / "game" / "scripts.rpa", {"Script.rpy": b"a"})
        unpack_archived_sources(project)
        disable_extracted_archives(project)
        restore_disabled_archives(project)
        restore_disabled_archives(project)
        assert (project / "game" / "scripts.rpa").is_file()


class TestRemoveUnpackedSources:
    """Tests for remove_unpacked_sources."""

    def test_removes_extracted_files_and_manifest(self, tmp_path: Path) -> None:
        """Extracted sources and the manifest are deleted."""
        project = _make_project(tmp_path)
        _write_rpa(project / "game" / "scripts.rpa", {"Script.rpy": b"a"})
        unpack_archived_sources(project)
        remove_unpacked_sources(project)
        assert not (project / "game" / "Script.rpy").exists()
        assert not (project / ".rts" / "unpacked_sources.json").exists()

    def test_restores_an_archive_left_disabled(self, tmp_path: Path) -> None:
        """A leftover disabled archive is restored before cleanup."""
        project = _make_project(tmp_path)
        _write_rpa(project / "game" / "scripts.rpa", {"Script.rpy": b"a"})
        unpack_archived_sources(project)
        disable_extracted_archives(project)
        remove_unpacked_sources(project)
        assert (project / "game" / "scripts.rpa").is_file()

    def test_removes_rpyc_when_not_preexisting(self, tmp_path: Path) -> None:
        """A .rpyc compiled after extraction is removed alongside its .rpy."""
        project = _make_project(tmp_path)
        _write_rpa(project / "game" / "scripts.rpa", {"Events/scene.rpy": b"a"})
        unpack_archived_sources(project)
        (project / "game" / "Events" / "scene.rpyc").write_bytes(b"compiled")
        remove_unpacked_sources(project)
        assert not (project / "game" / "Events" / "scene.rpyc").exists()

    def test_keeps_rpyc_when_preexisting(self, tmp_path: Path) -> None:
        """A .rpyc that predates extraction is never removed."""
        project = _make_project(tmp_path)
        (project / "game" / "Script.rpyc").write_bytes(b"compiled")
        _write_rpa(project / "game" / "scripts.rpa", {"Script.rpy": b"a"})
        unpack_archived_sources(project)
        remove_unpacked_sources(project)
        assert (project / "game" / "Script.rpyc").exists()

    def test_prunes_empty_directories_but_keeps_game(self, tmp_path: Path) -> None:
        """Directories left empty by removal are pruned, game/ is kept."""
        project = _make_project(tmp_path)
        _write_rpa(project / "game" / "scripts.rpa", {"Events/scene.rpy": b"a"})
        unpack_archived_sources(project)
        remove_unpacked_sources(project)
        assert not (project / "game" / "Events").exists()
        assert (project / "game").exists()

    def test_does_not_prune_directory_with_other_files(self, tmp_path: Path) -> None:
        """A directory holding an unrelated file is not removed."""
        project = _make_project(tmp_path)
        (project / "game" / "Events").mkdir()
        (project / "game" / "Events" / "art.png").write_bytes(b"\x89PNG")
        _write_rpa(project / "game" / "scripts.rpa", {"Events/scene.rpy": b"a"})
        unpack_archived_sources(project)
        remove_unpacked_sources(project)
        assert (project / "game" / "Events").exists()
        assert (project / "game" / "Events" / "art.png").exists()

    def test_noop_without_manifest(self, tmp_path: Path) -> None:
        """Removal on a project that was never unpacked does not raise."""
        project = _make_project(tmp_path)
        remove_unpacked_sources(project)

    def test_keeps_tracking_a_file_that_cannot_be_deleted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A locked file stays in the manifest instead of being forgotten."""
        project = _make_project(tmp_path)
        _write_rpa(
            project / "game" / "scripts.rpa",
            {"Phone.rpy": b"locked", "Script.rpy": b"fine"},
        )
        unpack_archived_sources(project)
        real_unlink = Path.unlink

        def _selective_raise(self: Path) -> None:
            if self.name == "Phone.rpy":
                raise OSError("locked")
            real_unlink(self)

        monkeypatch.setattr(Path, "unlink", _selective_raise)
        remove_unpacked_sources(project)
        monkeypatch.undo()

        assert (project / "game" / "Phone.rpy").exists()
        assert not (project / "game" / "Script.rpy").exists()
        raw = json.loads(
            (project / ".rts" / "unpacked_sources.json").read_text(encoding="utf-8")
        )
        assert [item["path"] for item in raw["entries"]] == ["Phone.rpy"]


class TestDiscardUnpackedFiles:
    """Tests for discard_unpacked_files."""

    def test_removes_a_named_unpacked_file(self, tmp_path: Path) -> None:
        """A file the manifest recorded is deleted and reported."""
        project = _make_project(tmp_path)
        _write_rpa(
            project / "game" / "scripts.rpa",
            {"Phone.rpy": b"broken", "Script.rpy": b"fine"},
        )
        unpack_archived_sources(project)
        discarded = discard_unpacked_files(project, ["game/Phone.rpy"])
        assert discarded == ["Phone.rpy"]
        assert not (project / "game" / "Phone.rpy").exists()
        assert (project / "game" / "Script.rpy").exists()

    def test_accepts_a_path_relative_to_game(self, tmp_path: Path) -> None:
        """A name without the game/ prefix resolves to the same entry."""
        project = _make_project(tmp_path)
        _write_rpa(project / "game" / "scripts.rpa", {"Phone.rpy": b"broken"})
        unpack_archived_sources(project)
        assert discard_unpacked_files(project, ["Phone.rpy"]) == ["Phone.rpy"]

    def test_ignores_a_file_the_manifest_does_not_know(self, tmp_path: Path) -> None:
        """A game's own file is never deleted, only ours can be."""
        project = _make_project(tmp_path)
        (project / "game" / "options.rpy").write_bytes(b"theirs")
        _write_rpa(project / "game" / "scripts.rpa", {"Script.rpy": b"ours"})
        unpack_archived_sources(project)
        assert discard_unpacked_files(project, ["game/options.rpy"]) == []
        assert (project / "game" / "options.rpy").read_bytes() == b"theirs"

    def test_forgets_the_entry_in_the_manifest(self, tmp_path: Path) -> None:
        """A discarded file leaves the manifest, keeping the others."""
        project = _make_project(tmp_path)
        _write_rpa(
            project / "game" / "scripts.rpa",
            {"Phone.rpy": b"broken", "Script.rpy": b"fine"},
        )
        unpack_archived_sources(project)
        discard_unpacked_files(project, ["game/Phone.rpy"])
        raw = json.loads(
            (project / ".rts" / "unpacked_sources.json").read_text(encoding="utf-8")
        )
        assert [item["path"] for item in raw["entries"]] == ["Script.rpy"]

    def test_removes_a_rpyc_it_created(self, tmp_path: Path) -> None:
        """A .rpyc compiled after unpacking goes with the discarded source."""
        project = _make_project(tmp_path)
        _write_rpa(project / "game" / "scripts.rpa", {"Phone.rpy": b"broken"})
        unpack_archived_sources(project)
        (project / "game" / "Phone.rpyc").write_bytes(b"compiled")
        discard_unpacked_files(project, ["game/Phone.rpy"])
        assert not (project / "game" / "Phone.rpyc").exists()

    def test_keeps_a_preexisting_rpyc(self, tmp_path: Path) -> None:
        """A .rpyc that predates unpacking belongs to the game, not to us."""
        project = _make_project(tmp_path)
        (project / "game" / "Phone.rpyc").write_bytes(b"theirs")
        _write_rpa(project / "game" / "scripts.rpa", {"Phone.rpy": b"broken"})
        unpack_archived_sources(project)
        discard_unpacked_files(project, ["game/Phone.rpy"])
        assert (project / "game" / "Phone.rpyc").read_bytes() == b"theirs"

    def test_noop_without_manifest(self, tmp_path: Path) -> None:
        """Discarding on a project that was never unpacked does nothing."""
        project = _make_project(tmp_path)
        assert discard_unpacked_files(project, ["game/Phone.rpy"]) == []

    def test_keeps_tracking_a_file_that_cannot_be_deleted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A locked file is not silently forgotten by the manifest."""
        project = _make_project(tmp_path)
        _write_rpa(project / "game" / "scripts.rpa", {"Phone.rpy": b"broken"})
        unpack_archived_sources(project)

        def _raise(self: Path) -> None:
            raise OSError("locked")

        monkeypatch.setattr(Path, "unlink", _raise)
        assert discard_unpacked_files(project, ["game/Phone.rpy"]) == []
        monkeypatch.undo()
        assert (project / "game" / "Phone.rpy").exists()


class TestArchivesContainCompiledScripts:
    """Tests for archives_contain_compiled_scripts."""

    def test_false_when_no_archives(self, tmp_path: Path) -> None:
        """A game with no .rpa archives at all reports False."""
        project = _make_project(tmp_path)
        assert archives_contain_compiled_scripts(project) is False

    def test_false_when_only_sources_present(self, tmp_path: Path) -> None:
        """An archive holding only .rpy sources reports False."""
        project = _make_project(tmp_path)
        _write_rpa(project / "game" / "scripts.rpa", {"Script.rpy": b"a"})
        assert archives_contain_compiled_scripts(project) is False

    def test_true_when_rpyc_present(self, tmp_path: Path) -> None:
        """An archive holding a compiled .rpyc reports True."""
        project = _make_project(tmp_path)
        _write_rpa(project / "game" / "scripts.rpa", {"Script.rpyc": b"compiled"})
        assert archives_contain_compiled_scripts(project) is True

    def test_ignores_rpyc_under_tl(self, tmp_path: Path) -> None:
        """A compiled translation file under tl/ does not count."""
        project = _make_project(tmp_path)
        _write_rpa(
            project / "game" / "scripts.rpa",
            {"tl/french/common.rpyc": b"compiled"},
        )
        assert archives_contain_compiled_scripts(project) is False


def test_unpacked_entry_is_a_plain_record() -> None:
    """UnpackedEntry exposes its two fields directly."""
    entry = UnpackedEntry(path="Script.rpy", rpyc_preexisted=True)
    assert entry.path == "Script.rpy"
    assert entry.rpyc_preexisted is True
