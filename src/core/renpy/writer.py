"""Writes validated translations back into Ren'Py .rpy files."""

import re
import shutil
from pathlib import Path

from core.renpy.say_line import split_say_line

_UNESCAPED_QUOTE_RE = re.compile(r'(\\*)"')
_TRAILING_BACKSLASHES_RE = re.compile(r"\\+$")

_HEADER_RE = re.compile(r"^translate \w+ (\w+):\s*$")
_STRINGS_HEADER_RE = re.compile(r"^translate \w+ strings:\s*$")
_OLD_LINE_RE = re.compile(r'^    old "((?:[^"\\]|\\.)*)"')
_NEW_LINE_RE = re.compile(r'^    new "((?:[^"\\]|\\.)*)"')


class TranslateBlockWriter:
    """Rewrites editable lines in tl/<lang>/*.rpy with validated translations.

    Always creates a backup in backup_dir before modifying any file.
    """

    def __init__(self, tl_dir: Path, backup_dir: Path) -> None:
        """Initialize with explicit tl directory and backup directory.

        Args:
            tl_dir: Directory containing .rpy files to update.
            backup_dir: Directory where original files are copied before modification.
        """
        self._tl_dir = tl_dir
        self._backup_dir = backup_dir

    def write_all(
        self,
        translations: dict[str, str],
        old_to_new: dict[str, str] | None = None,
    ) -> None:
        """Write all provided translations into their respective .rpy files.

        Args:
            translations: Mapping of block_id to validated translated text
                for dialogue blocks.
            old_to_new: Optional mapping of old_text to new_text for strings
                blocks (translate ... strings: format).
        """
        for rpy_file in self._tl_dir.rglob("*.rpy"):
            self._write_file(rpy_file, translations, old_to_new)

    def _write_file(
        self,
        path: Path,
        translations: dict[str, str],
        old_to_new: dict[str, str] | None = None,
    ) -> None:
        """Backup a file if changed, then rewrite its editable lines.

        Args:
            path: Path to a single .rpy translation file.
            translations: Full block_id -> translated_text mapping.
            old_to_new: Optional old_text -> new_text mapping for strings blocks.
        """
        content = path.read_text(encoding="utf-8")
        modified = self._apply_translations(content, translations, old_to_new)
        if modified == content:
            return
        self._backup(path)
        path.write_text(modified, encoding="utf-8")

    def _backup(self, path: Path) -> None:
        """Copy the original file to backup_dir before modification.

        Args:
            path: Absolute path of the file to backup.
        """
        self._backup_dir.mkdir(parents=True, exist_ok=True)
        relative = path.relative_to(self._tl_dir)
        backup_path = self._backup_dir / relative
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup_path)

    @staticmethod
    def _copy_block_preamble(lines: list[str], start: int, result: list[str]) -> int:
        """Copy what stands between a block header and its editable line.

        Ren'Py writes a blank line after every header, then the commented
        source statement. Only the comments used to be skipped here, so
        the editable line was never reached on a real generated file and
        nothing was ever written back to it. The parser has always
        skipped both, which is why the two disagreed in silence: the
        review showed lines the save button could not write.

        Args:
            lines: All lines of the file.
            start: Index of the first line after the header.
            result: The output the copied lines are appended to.

        Returns:
            The index of the first line that is neither blank nor a
            comment.
        """
        index = start
        while index < len(lines) and not lines[index].strip():
            result.append(lines[index])
            index += 1
        while index < len(lines) and lines[index].lstrip().startswith("#"):
            result.append(lines[index])
            index += 1
        return index

    def _apply_translations(
        self,
        content: str,
        translations: dict[str, str],
        old_to_new: dict[str, str] | None = None,
    ) -> str:
        """Replace editable lines for matching blocks.

        Handles two block formats:
        - Dialogue blocks: translate lang block_id: / # comment / editable line
        - Strings blocks: translate lang strings: / old "..." / new "..."

        A dialogue block header also exits strings mode, since a strings
        block only ends at the next block header or a non-indented line.

        Args:
            content: Full text of a .rpy file.
            translations: Mapping of block_id to translated text (dialogue).
            old_to_new: Optional mapping of old_text to new_text (strings).

        Returns:
            Modified file content (identical to input if no replacements made).
        """
        lines = content.splitlines(keepends=True)
        result: list[str] = []
        i = 0
        in_strings = False
        pending_old: str | None = None

        while i < len(lines):
            line = lines[i]

            if _STRINGS_HEADER_RE.match(line):
                in_strings = True
                pending_old = None
                result.append(line)
                i += 1
                continue

            m = _HEADER_RE.match(line)
            if m:
                in_strings = False
                pending_old = None
                block_id = m.group(1)
                result.append(line)
                i += 1
                if block_id in translations:
                    i = self._copy_block_preamble(lines, i, result)
                    if i < len(lines) and lines[i][:1] in (" ", "\t"):
                        result.append(_replace_quoted(lines[i], translations[block_id]))
                        i += 1
                continue

            if in_strings:
                if line.strip() and line[:1] not in (" ", "\t"):
                    in_strings = False
                    pending_old = None
                    result.append(line)
                    i += 1
                    continue

                m_old = _OLD_LINE_RE.match(line)
                if m_old:
                    pending_old = m_old.group(1)
                    result.append(line)
                    i += 1
                    continue

                m_new = _NEW_LINE_RE.match(line)
                if m_new and pending_old is not None and old_to_new:
                    if pending_old in old_to_new:
                        line = _replace_quoted(line, old_to_new[pending_old])
                    pending_old = None
                    result.append(line)
                    i += 1
                    continue

            result.append(line)
            i += 1

        return "".join(result)


def _escape_translation(text: str) -> str:
    """Neutralize characters that would break out of a .rpy string literal.

    Translations come from external providers (or human edits) and are
    inserted verbatim between double quotes by _replace_quoted(). A raw
    double quote would terminate the string literal early and a raw line
    break would inject new script lines — both would let a hostile
    "translation" plant arbitrary Ren'Py statements in the generated
    file. A quote preceded by an odd number of backslashes is already
    escaped and left untouched, since providers commonly echo the \\"
    sequences present in the source text.

    A text ending on an odd number of backslashes gets one more, because
    _replace_quoted() appends the closing quote right after it: the last
    backslash would escape that quote and let the literal run to the end
    of the line, which Ren'Py refuses to load.

    Args:
        text: The replacement text to sanitize.

    Returns:
        The text with unescaped double quotes escaped, trailing
        backslashes balanced, and line breaks replaced by the literal
        \\n escape sequence.
    """
    escaped = _UNESCAPED_QUOTE_RE.sub(
        lambda m: m.group(1) + ('"' if len(m.group(1)) % 2 else '\\"'),
        text,
    )
    escaped = _TRAILING_BACKSLASHES_RE.sub(
        lambda m: m.group(0) + "\\" if len(m.group(0)) % 2 else m.group(0),
        escaped,
    )
    return escaped.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")


def _replace_quoted(line: str, new_text: str) -> str:
    """Replace the spoken string of an editable line with a translation.

    The string is located by split_say_line(), the same way the parser
    located the source text this translation answers, so the two cannot
    disagree about which of a line's quoted strings belongs to the
    translator. Everything else is kept verbatim: indentation, the
    speaker, a `with` clause, keyword arguments, the line break. Taking
    everything between the first and the last quote of the line instead
    would overwrite the speaker of `"Store clerk" "Not so fast!"` and
    swallow the arguments of `e "Hi" (what_color="#fff")`.

    The replacement text is sanitized with _escape_translation() first.

    Args:
        line: A .rpy editable line such as '    e "Hello"\\n'.
        new_text: The replacement text (without surrounding quotes).

    Returns:
        The line with the spoken string replaced by new_text, unchanged
        when the line holds none.
    """
    say = split_say_line(line)
    if say is None:
        return line
    return f'{say.prefix}"{_escape_translation(new_text)}"{say.suffix}'
