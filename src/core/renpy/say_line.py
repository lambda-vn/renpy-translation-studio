"""Locating the spoken string inside a Ren'Py say statement.

A say statement is not just a quoted string on a line. It can carry a
speaker, image attributes, a transition, an id or keyword arguments:

    e "Hello"
    MC happy "Hello"
    "Store clerk" "Not so fast!" with hpunch
    e "Hello" (what_color="#fff")

Both the parser, which reads the statement, and the writer, which puts a
translation back into it, have to agree on which of those quoted strings
is the one a translator sees. They used to disagree, each with its own
regular expressions: the parser refused anything it could not match to
the end of the line and stored the whole statement as the source text,
while the writer replaced everything between the first and the last
quote of the line, which on a statement with a quoted speaker overwrote
the speaker along with the text. This module is the single answer both
of them ask.
"""

from dataclasses import dataclass

_HEAD_TOKEN_EXTRA = frozenset("@.")
_SPACES = " \t"


@dataclass(frozen=True)
class SayLine:
    """A say statement split around the string a translation replaces.

    Attributes:
        prefix: Everything before the opening quote, verbatim: indentation,
            the speaker and its image attributes.
        text: The spoken string, still escaped as it appears in the file.
        suffix: Everything after the closing quote, verbatim: a `with`
            clause, an id, keyword arguments, the line break.
        who: The character variable the line is attributed to, None for
            narration.
    """

    prefix: str
    text: str
    suffix: str
    who: str | None


def _skip_spaces(line: str, start: int) -> int:
    """Return the index of the first character that is not a space or tab.

    Line breaks are not skipped: a statement read with its newline kept
    must leave that newline in the suffix rather than have it absorbed
    into the statement head.

    Args:
        line: The line being scanned.
        start: Index to start from.

    Returns:
        The index of the first non-space character, or len(line).
    """
    index = start
    while index < len(line) and line[index] in _SPACES:
        index += 1
    return index


def _end_of_token(line: str, start: int) -> int:
    """Return the index just past an unquoted head token.

    A head token is a speaker name, one of its image attributes, or the
    `@` introducing temporary ones.

    Args:
        line: The line being scanned.
        start: Index of the token's first character.

    Returns:
        The index just past the token, equal to start when there is no
        token at that position.
    """
    index = start
    while index < len(line) and (
        line[index].isalnum() or line[index] == "_" or line[index] in _HEAD_TOKEN_EXTRA
    ):
        index += 1
    return index


def _end_of_literal(line: str, start: int) -> int | None:
    """Return the index just past a double-quoted string literal.

    A backslash escapes the character following it, so an escaped quote
    does not close the literal.

    Args:
        line: The line being scanned.
        start: Index of the opening quote.

    Returns:
        The index just past the closing quote, or None when the literal
        runs to the end of the line without being closed.
    """
    index = start + 1
    while index < len(line):
        char = line[index]
        if char == "\\":
            index += 2
            continue
        if char == '"':
            return index + 1
        if char in "\r\n":
            return None
        index += 1
    return None


def _resolve_who(prefix: str, quoted_speaker: str | None) -> str | None:
    """Return the character variable a statement is attributed to.

    Args:
        prefix: Everything before the spoken string's opening quote.
        quoted_speaker: Content of the leading string literal when the
            speaker is written as one, None otherwise.

    Returns:
        The speaker, or None when the line is narration or names its
        speaker in a shape no glossary entry could match.
    """
    if quoted_speaker is not None:
        return quoted_speaker
    tokens = prefix.split()
    if not tokens:
        return None
    name = tokens[0]
    return name if name.replace("_", "").isalnum() else None


def split_say_line(line: str) -> SayLine | None:
    """Split a say statement around the string a translation replaces.

    The spoken string is the last quoted literal of the statement head,
    the head being what stands before the first thing that is neither a
    speaker token nor a literal. A quoted speaker is only recognized when
    nothing precedes it, so a malformed line naming a speaker twice keeps
    its first literal as the text rather than silently promoting the
    second one.

    Args:
        line: One line of a .rpy file, with or without its indentation
            and its trailing line break.

    Returns:
        The split statement, or None when the line holds no usable
        string: a blank line, a statement that is not a say, an
        unterminated literal, or the `\"\"\"` opening a multiline block,
        whose spoken text is not on this line at all.
    """
    literals: list[tuple[int, int]] = []
    named_speaker = False
    index = _skip_spaces(line, 0)

    while index < len(line):
        if line[index] == '"':
            end = _end_of_literal(line, index)
            if end is None:
                return None
            literals.append((index, end))
            if named_speaker or len(literals) == 2:
                break
            index = _skip_spaces(line, end)
            continue
        if literals:
            break
        token_end = _end_of_token(line, index)
        if token_end == index:
            return None
        named_speaker = True
        index = _skip_spaces(line, token_end)

    if not literals:
        return None

    start, end = literals[-1]
    if line[end : end + 1] == '"':
        return None
    quoted_speaker = (
        line[literals[0][0] + 1 : literals[0][1] - 1] if len(literals) == 2 else None
    )
    return SayLine(
        prefix=line[:start],
        text=line[start + 1 : end - 1],
        suffix=line[end:],
        who=_resolve_who(line[:start], quoted_speaker),
    )
