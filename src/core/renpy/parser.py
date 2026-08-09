"""Parser for Ren'Py translation (.rpy) files."""

import binascii
import re
from dataclasses import dataclass
from pathlib import Path

_TRANSLATE_HEADER = re.compile(r"^translate\s+\S+\s+(\w+)\s*:")
_STRINGS_HEADER = re.compile(r"^translate\s+\S+\s+strings\s*:")
_OLD_LINE = re.compile(r'^    old "((?:[^"\\]|\\.)*)"$')
_NEW_LINE = re.compile(r'^    new "((?:[^"\\]|\\.)*)"')
_COMMENT_LINE = re.compile(r"^    #(?: (.*))?$")
_TRANS_CHAR = re.compile(r'^    (\w+) "(.*)"$')
_TRANS_STR_CHAR = re.compile(r'^    "((?:[^"\\]|\\.)*)" "((?:[^"\\]|\\.)*)"$')
_TRANS_NARRATOR = re.compile(r'^    "(.*)"$')
_SRC_CHAR_SINGLE = re.compile(r'^(\w+) "(.*)"$')
_SRC_STR_CHAR = re.compile(r'^"((?:[^"\\]|\\.)*)" "((?:[^"\\]|\\.)*)"$')
_SRC_NARRATOR_SINGLE = re.compile(r'^"(.*)"$')
_SRC_MULTILINE_START = re.compile(r'^(?:(\w+) )?"""$')
_FILE_REF = re.compile(r"^[\w./\-]+\.rpy:\d+$")


class ParseError(Exception):
    """Raised when a .rpy file cannot be parsed."""


@dataclass
class TranslationBlock:
    """A single translation unit extracted from a Ren'Py .rpy file."""

    block_id: str
    source_file: str
    source_line: int
    character_variable: str | None
    source_text: str
    translated_text: str


def is_translated(block: TranslationBlock) -> bool:
    """Return True when a parsed block already carries a real translation.

    The Ren'Py SDK seeds every freshly generated block with a copy of the
    source text, so a translation equal to its source means "not translated
    yet" rather than "translated to an identical string".

    Multiline blocks always count as untranslated: their translation line
    cannot be read back reliably, so adopting it would store garbage.

    Args:
        block: A block returned by TranslateBlockParser.

    Returns:
        True when the block holds a translation differing from its source.
    """
    if "\n" in block.source_text:
        return False
    return bool(block.translated_text) and block.translated_text != block.source_text


class TranslateBlockParser:
    """Parser for Ren'Py translation (.rpy) files."""

    def parse_file(self, path: Path) -> list[TranslationBlock]:
        """Parse all translation blocks in a single .rpy file.

        Args:
            path: Path to the translation .rpy file.

        Returns:
            A list of TranslationBlock instances found in the file.

        Raises:
            ParseError: If the file cannot be read.
        """
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ParseError(f"Cannot read {path}: {exc}") from exc

        lines = text.splitlines()
        blocks: list[TranslationBlock] = []
        i = 0
        while i < len(lines):
            if _STRINGS_HEADER.match(lines[i]):
                str_blocks, i = self._parse_strings_body(lines, i + 1, str(path))
                blocks.extend(str_blocks)
            else:
                m = _TRANSLATE_HEADER.match(lines[i])
                if m:
                    block_id = m.group(1)
                    source_line = i + 1
                    block, i = self._parse_block_body(
                        lines, i + 1, block_id, str(path), source_line
                    )
                    if block is not None:
                        blocks.append(block)
                else:
                    i += 1
        return blocks

    def parse_directory(self, tl_dir: Path) -> list[TranslationBlock]:
        """Parse all translation blocks in a directory of .rpy files.

        Args:
            tl_dir: Path to the translation directory (e.g. tl/french/).

        Returns:
            A list of TranslationBlock instances from all files, sorted by
            file path then line number.
        """
        blocks: list[TranslationBlock] = []
        for rpy_file in sorted(tl_dir.rglob("*.rpy")):
            blocks.extend(self.parse_file(rpy_file))
        return blocks

    def _parse_block_body(
        self,
        lines: list[str],
        start: int,
        block_id: str,
        source_file: str,
        source_line: int,
    ) -> tuple[TranslationBlock | None, int]:
        """Parse the indented body of a translate block.

        Args:
            lines: All lines of the file.
            start: Index of the first body line (after the header).
            block_id: The block identifier extracted from the header.
            source_file: The file path string for the resulting block record.
            source_line: The 1-based line number of the translate header.

        Returns:
            A tuple of (TranslationBlock or None, next line index).
        """
        i = start
        comment_contents: list[str] = []

        while i < len(lines) and lines[i].strip() == "":
            i += 1

        while i < len(lines):
            m = _COMMENT_LINE.match(lines[i])
            if m:
                comment_contents.append(m.group(1) or "")
                i += 1
            else:
                break

        if not comment_contents:
            return None, i

        char_var, source_text = self._parse_comment_source(comment_contents)

        translated_text = ""
        if i < len(lines):
            line = lines[i]
            m_char = _TRANS_CHAR.match(line)
            m_str_char = _TRANS_STR_CHAR.match(line)
            m_narr = _TRANS_NARRATOR.match(line)
            if m_char:
                translated_text = m_char.group(2)
                i += 1
            elif m_str_char:
                translated_text = m_str_char.group(2)
                i += 1
            elif m_narr:
                translated_text = m_narr.group(1)
                i += 1

        return (
            TranslationBlock(
                block_id=block_id,
                source_file=source_file,
                source_line=source_line,
                character_variable=char_var,
                source_text=source_text,
                translated_text=translated_text,
            ),
            i,
        )

    def _parse_comment_source(
        self, comment_contents: list[str]
    ) -> tuple[str | None, str]:
        """Extract character variable and source text from comment lines.

        Leading SDK file-reference lines (e.g. "renpy/common/x.rpy:28") are
        skipped before looking for the actual source line.

        Args:
            comment_contents: Lines after stripping the leading '# ' prefix.

        Returns:
            A tuple of (character_variable or None, source_text).
        """
        if not comment_contents:
            return None, ""

        contents = comment_contents
        while contents and _FILE_REF.match(contents[0]):
            contents = contents[1:]

        if not contents:
            return None, ""

        first = contents[0]

        m_multi = _SRC_MULTILINE_START.match(first)
        if m_multi:
            char_var: str | None = m_multi.group(1) or None
            inner = comment_contents[1:]
            if inner and inner[-1] == '"""':
                inner = inner[:-1]
            return char_var, "\n".join(inner)

        m_char = _SRC_CHAR_SINGLE.match(first)
        if m_char:
            return m_char.group(1), m_char.group(2)

        m_str_char = _SRC_STR_CHAR.match(first)
        if m_str_char:
            return m_str_char.group(1), m_str_char.group(2)

        m_narr = _SRC_NARRATOR_SINGLE.match(first)
        if m_narr:
            return None, m_narr.group(1)

        return None, first

    def _parse_strings_body(
        self, lines: list[str], start: int, source_file: str
    ) -> tuple[list[TranslationBlock], int]:
        """Parse old/new string pairs from a translate strings block.

        The block ends at the first non-indented, non-empty line. Each
        block_id is a hash of (source_file + old_text), since strings blocks
        have no header identifier to key on.

        Args:
            lines: All lines of the file.
            start: Index of the first body line (after the header).
            source_file: File path string for the resulting block records.

        Returns:
            Tuple of (list of TranslationBlock, next line index after block).
        """
        blocks: list[TranslationBlock] = []
        i = start

        while i < len(lines):
            line = lines[i]
            if line.strip() and line[:1] not in (" ", "\t"):
                break

            m_old = _OLD_LINE.match(line)
            if not m_old:
                i += 1
                continue

            old_text = m_old.group(1)
            old_line_no = i + 1
            i += 1

            while i < len(lines) and not lines[i].strip():
                i += 1

            new_text = ""
            if i < len(lines):
                m_new = _NEW_LINE.match(lines[i])
                if m_new:
                    new_text = m_new.group(1)
                    i += 1

            data = (source_file + "\x00" + old_text).encode()
            crc = binascii.crc32(data) & 0xFFFFFFFF
            block_id = f"strings_{crc:08x}"

            blocks.append(
                TranslationBlock(
                    block_id=block_id,
                    source_file=source_file,
                    source_line=old_line_no,
                    character_variable=None,
                    source_text=old_text,
                    translated_text=new_text,
                )
            )

        return blocks, i
