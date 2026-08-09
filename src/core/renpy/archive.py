"""Reader for Ren'Py .rpa archive files."""

import pickle
import zlib
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import BinaryIO, NoReturn

_HEADER_VERSIONS = {
    "RPA-2.0": 2.0,
    "RPA-3.0": 3.0,
    "RPA-3.2": 3.2,
}


class ArchiveError(Exception):
    """Raised when an .rpa archive cannot be read or is malformed."""


class _RestrictedUnpickler(pickle.Unpickler):
    """Unpickler that refuses to resolve any class or function reference.

    A Ren'Py archive index only ever contains dicts, lists, tuples, strings
    and integers, so any GLOBAL opcode in the stream means the payload is
    not a legitimate index. Refusing every lookup, rather than allowlisting
    the expected containers, keeps a crafted payload from ever reaching
    __reduce__ on an attacker-chosen callable.
    """

    def find_class(self, module: str, name: str) -> NoReturn:
        raise ArchiveError(f"Refused to unpickle {module}.{name}")


def validate_member_name(name: str) -> str:
    """Validate an archive member name and normalize its separators.

    Member names come straight from the archive's index, an untrusted
    third party, so nothing here may be interpreted as an absolute path or
    a traversal outside the extraction target.

    Args:
        name: Raw member name as stored in the archive index.

    Returns:
        The name with backslashes normalized to forward slashes.

    Raises:
        ArchiveError: If the name is absolute, carries a drive letter, or
            contains a '..' segment.
    """
    normalized = name.replace("\\", "/")
    if normalized.startswith("/"):
        raise ArchiveError(f"Unsafe member name (absolute path): {name}")
    if len(normalized) >= 2 and normalized[1] == ":":
        raise ArchiveError(f"Unsafe member name (drive letter): {name}")
    if ".." in normalized.split("/"):
        raise ArchiveError(f"Unsafe member name (path traversal): {name}")
    return normalized


@dataclass
class ArchiveMember:
    """Location of a single file inside an .rpa archive."""

    offset: int
    length: int
    prefix: bytes


class RpaArchive:
    """Reader for a single Ren'Py .rpa archive.

    Must be used as a context manager so the underlying file handle is
    always released:

        with RpaArchive.open(path) as archive:
            data = archive.read(name)
    """

    def __init__(
        self, path: Path, file: BinaryIO, index: dict[str, ArchiveMember]
    ) -> None:
        self._path = path
        self._file = file
        self._index = index

    @classmethod
    def open(cls, path: Path) -> "RpaArchive":
        """Open an .rpa archive and read its index.

        Args:
            path: Path to the .rpa file.

        Returns:
            An RpaArchive ready for names()/read() calls.

        Raises:
            ArchiveError: If the file is not a supported .rpa archive, or
                its index is malformed.
        """
        file = path.open("rb")
        try:
            index = _read_index(file)
        except Exception:
            file.close()
            raise
        return cls(path, file, index)

    def __enter__(self) -> "RpaArchive":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        """Release the underlying file handle."""
        self._file.close()

    def names(self) -> list[str]:
        """Return the archive-relative names of every member."""
        return list(self._index.keys())

    def read(self, name: str) -> bytes:
        """Read the raw bytes of a single member.

        Args:
            name: Member name as returned by names().

        Returns:
            The member's raw content.

        Raises:
            ArchiveError: If no member has this name.
        """
        member = self._index.get(name)
        if member is None:
            raise ArchiveError(f"No such member in {self._path}: {name}")
        self._file.seek(member.offset)
        data = self._file.read(member.length - len(member.prefix))
        return member.prefix + data


def _read_index(file: BinaryIO) -> dict[str, ArchiveMember]:
    """Read and decode the member index of an open .rpa file.

    Args:
        file: The archive file, positioned at its start.

    Returns:
        A mapping of validated member name to its ArchiveMember location.

    Raises:
        ArchiveError: If the header, index or a member name is invalid.
    """
    header_line = file.readline().rstrip(b"\r\n")
    try:
        header = header_line.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ArchiveError(f"Unsupported archive header: {header_line!r}") from exc

    parts = header.split()
    magic = parts[0] if parts else ""
    version = _HEADER_VERSIONS.get(magic)
    if version is None or len(parts) < 2:
        raise ArchiveError(f"Unsupported archive header: {header!r}")

    offset = int(parts[1], 16)
    key = 0
    if version in (3.0, 3.2):
        key_start = 3 if version == 3.2 else 2
        for subkey in parts[key_start:]:
            key ^= int(subkey, 16)

    file.seek(offset)
    raw_index = file.read()
    try:
        decompressed = zlib.decompress(raw_index)
        payload = _RestrictedUnpickler(BytesIO(decompressed), encoding="latin1").load()
    except ArchiveError:
        raise
    except (zlib.error, pickle.UnpicklingError, EOFError, ValueError) as exc:
        raise ArchiveError(f"Corrupt archive index: {exc}") from exc

    return _normalize_index(payload, key)


def _normalize_index(payload: object, key: int) -> dict[str, ArchiveMember]:
    """Validate and decode a raw unpickled archive index.

    Args:
        payload: The object produced by unpickling the index.
        key: XOR key to apply to offset/length (0 for unobfuscated indexes).

    Returns:
        A mapping of validated member name to its ArchiveMember location.

    Raises:
        ArchiveError: If the index does not have the expected shape.
    """
    if not isinstance(payload, dict):
        raise ArchiveError("Archive index is not a dict")

    normalized: dict[str, ArchiveMember] = {}
    for name, entries in payload.items():
        if not isinstance(name, str) or not isinstance(entries, list) or not entries:
            raise ArchiveError(f"Malformed archive index entry: {name!r}")
        entry = entries[0]
        if not isinstance(entry, tuple) or len(entry) not in (2, 3):
            raise ArchiveError(f"Malformed archive index entry: {name!r}")

        offset, length = entry[0], entry[1]
        if not isinstance(offset, int) or not isinstance(length, int):
            raise ArchiveError(f"Malformed archive index entry: {name!r}")

        prefix: bytes
        if len(entry) == 3:
            raw_prefix = entry[2]
            if isinstance(raw_prefix, str):
                prefix = raw_prefix.encode("latin1")
            elif isinstance(raw_prefix, bytes):
                prefix = raw_prefix
            else:
                raise ArchiveError(f"Malformed archive index prefix: {name!r}")
        else:
            prefix = b""

        if key:
            offset ^= key
            length ^= key

        normalized[validate_member_name(name)] = ArchiveMember(
            offset=offset, length=length, prefix=prefix
        )
    return normalized
