"""Tests for core/renpy/archive.py."""

import pickle
import zlib
from pathlib import Path

import pytest

from core.renpy.archive import ArchiveError, RpaArchive, validate_member_name


def _header(magic: str, offset: int, *fields: int) -> bytes:
    """Build a raw .rpa header line for the given magic and offset."""
    tail = "".join(f" {field:08x}" for field in fields)
    return f"{magic} {offset:016x}{tail}\n".encode()


def _build_rpa(path: Path, magic: str, members: dict[str, bytes], key: int = 0) -> None:
    """Write a minimal but valid .rpa archive with the given members."""

    def make_header(offset: int) -> bytes:
        if magic == "RPA-2.0":
            return _header(magic, offset)
        if magic == "RPA-3.2":
            return _header(magic, offset, 0, key)
        return _header(magic, offset, key)

    header_len = len(make_header(0))
    body = b""
    index: dict[str, list[tuple[int, int]]] = {}
    for name, data in members.items():
        member_offset = header_len + len(body)
        length = len(data)
        body += data
        if magic == "RPA-2.0":
            index[name] = [(member_offset, length)]
        else:
            index[name] = [(member_offset ^ key, length ^ key)]

    offset = header_len + len(body)
    header = make_header(offset)
    index_bytes = zlib.compress(pickle.dumps(index, protocol=2))
    path.write_bytes(header + body + index_bytes)


class TestRpaArchiveReading:
    """Round-trip reads across the supported archive versions."""

    def test_reads_v2_archive(self, tmp_path: Path) -> None:
        """RPA-2.0 members (no XOR obfuscation) are read back correctly."""
        path = tmp_path / "test.rpa"
        _build_rpa(path, "RPA-2.0", {"Script.rpy": b"label start:\n"})
        with RpaArchive.open(path) as archive:
            assert archive.read("Script.rpy") == b"label start:\n"

    def test_reads_v3_archive(self, tmp_path: Path) -> None:
        """RPA-3.0 members are correctly de-obfuscated with the XOR key."""
        path = tmp_path / "test.rpa"
        _build_rpa(path, "RPA-3.0", {"Script.rpy": b"label start:\n"}, key=0x42424242)
        with RpaArchive.open(path) as archive:
            assert archive.read("Script.rpy") == b"label start:\n"

    def test_reads_v3_2_archive(self, tmp_path: Path) -> None:
        """RPA-3.2 members are correctly de-obfuscated with the XOR key."""
        path = tmp_path / "test.rpa"
        _build_rpa(path, "RPA-3.2", {"Script.rpy": b"label start:\n"}, key=0x1337)
        with RpaArchive.open(path) as archive:
            assert archive.read("Script.rpy") == b"label start:\n"

    def test_names_lists_all_members(self, tmp_path: Path) -> None:
        """names() returns every member of a multi-file archive."""
        path = tmp_path / "test.rpa"
        _build_rpa(
            path,
            "RPA-3.0",
            {"Script.rpy": b"a", "Events/scene.rpy": b"b"},
            key=1,
        )
        with RpaArchive.open(path) as archive:
            assert sorted(archive.names()) == ["Events/scene.rpy", "Script.rpy"]

    def test_three_element_entry_with_prefix(self, tmp_path: Path) -> None:
        """A (offset, length, prefix) index entry is prepended on read."""
        path = tmp_path / "test.rpa"
        header_len = len(_header("RPA-2.0", 0))
        stored = b"world"
        member_offset = header_len
        length = len(b"hello") + len(stored)
        index = {"Script.rpy": [(member_offset, length, "hello")]}
        header = _header("RPA-2.0", header_len + len(stored))
        index_bytes = zlib.compress(pickle.dumps(index, protocol=2))
        path.write_bytes(header + stored + index_bytes)

        with RpaArchive.open(path) as archive:
            assert archive.read("Script.rpy") == b"helloworld"

    def test_context_manager_closes_file(self, tmp_path: Path) -> None:
        """The underlying file handle is released on exit."""
        path = tmp_path / "test.rpa"
        _build_rpa(path, "RPA-2.0", {"Script.rpy": b"x"})
        with RpaArchive.open(path) as archive:
            handle = archive._file
        assert handle.closed


class TestRpaArchiveMalformedInput:
    """Archives that must be refused rather than trusted."""

    def test_unknown_magic_raises(self, tmp_path: Path) -> None:
        """An unsupported header magic (e.g. RPA-1.0) is refused."""
        path = tmp_path / "test.rpa"
        path.write_bytes(b"RPA-1.0 0000000000000000\n")
        with pytest.raises(ArchiveError):
            RpaArchive.open(path)

    def test_non_utf8_header_raises(self, tmp_path: Path) -> None:
        """A header that is not valid UTF-8 is refused explicitly."""
        path = tmp_path / "test.rpa"
        path.write_bytes(b"\x80\x81\x82\n")
        with pytest.raises(ArchiveError):
            RpaArchive.open(path)

    def test_corrupt_index_raises(self, tmp_path: Path) -> None:
        """Non-zlib garbage at the index offset is refused."""
        path = tmp_path / "test.rpa"
        header = _header("RPA-2.0", 0)
        header = _header("RPA-2.0", len(header))
        path.write_bytes(header + b"not a valid zlib stream")
        with pytest.raises(ArchiveError):
            RpaArchive.open(path)

    def test_malicious_pickle_payload_is_refused_and_not_executed(
        self, tmp_path: Path
    ) -> None:
        """A pickled class/function reference in the index is refused.

        Regression guard for the security requirement that no GLOBAL
        opcode in an archive's index may ever resolve, since the index
        comes from a third-party file, not from us.
        """
        path = tmp_path / "test.rpa"
        header = _header("RPA-2.0", 0)
        header = _header("RPA-2.0", len(header))
        malicious = zlib.compress(pickle.dumps(len, protocol=2))
        path.write_bytes(header + malicious)
        with pytest.raises(ArchiveError):
            RpaArchive.open(path)

    @pytest.mark.parametrize(
        "unsafe_name",
        ["../evil.rpy", "/etc/passwd", "C:\\evil.rpy", "Events/../../evil.rpy"],
    )
    def test_unsafe_member_names_are_refused(
        self, tmp_path: Path, unsafe_name: str
    ) -> None:
        """Archive indexes naming an unsafe path are refused on open."""
        path = tmp_path / "test.rpa"
        _build_rpa(path, "RPA-2.0", {unsafe_name: b"x"})
        with pytest.raises(ArchiveError):
            RpaArchive.open(path)


class TestValidateMemberName:
    """Direct tests for the member name guard."""

    def test_accepts_normal_relative_name(self) -> None:
        """A plain relative path is accepted unchanged."""
        assert validate_member_name("Events/scene.rpy") == "Events/scene.rpy"

    def test_normalizes_backslashes(self) -> None:
        """Backslash separators are normalized to forward slashes."""
        assert validate_member_name("Events\\scene.rpy") == "Events/scene.rpy"

    def test_rejects_parent_traversal(self) -> None:
        """A '..' path segment is refused."""
        with pytest.raises(ArchiveError):
            validate_member_name("../evil.rpy")

    def test_rejects_absolute_path(self) -> None:
        """A leading slash is refused."""
        with pytest.raises(ArchiveError):
            validate_member_name("/etc/passwd")

    def test_rejects_drive_letter(self) -> None:
        """A Windows drive letter is refused."""
        with pytest.raises(ArchiveError):
            validate_member_name("C:\\evil.rpy")
