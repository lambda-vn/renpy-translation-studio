"""Checks keeping the locale files and the code that reads them in step.

A key the code reads but no locale declares is invisible to every other
guard: i18n.t() returns the key itself rather than raising, so the screen
simply shows "onboarding.sdk_valid" where a sentence belongs, and ruff,
mypy and the rest of the suite all stay green.
"""

import ast
import json
import re
from collections.abc import Iterator
from pathlib import Path

import pytest

from core.i18n import DEFAULT_LOCALE, LOCALES_DIR, SUPPORTED_LOCALES

_SOURCE_DIR = Path(__file__).resolve().parent.parent / "src"

_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+$")

_FILE_SUFFIXES = (".py", ".sh", ".exe", ".json", ".rpy")


def _flatten(strings: dict[str, object], prefix: str = "") -> set[str]:
    """Return the dot-separated path of every leaf of a locale file.

    Args:
        strings: A locale file, or one of its sections.
        prefix: Path of the section being walked, empty at the root.

    Returns:
        Every key i18n.t() can resolve to a string.
    """
    keys: set[str] = set()
    for name, value in strings.items():
        path = f"{prefix}{name}"
        if isinstance(value, dict):
            keys |= _flatten(value, f"{path}.")
        else:
            keys.add(path)
    return keys


def _load_locale(locale: str) -> dict[str, object]:
    """Return the parsed content of one locale file.

    Args:
        locale: Locale code, as listed in SUPPORTED_LOCALES.

    Returns:
        The locale file, sections included.
    """
    with (LOCALES_DIR / f"{locale}.json").open(encoding="utf-8") as handle:
        content: dict[str, object] = json.load(handle)
    return content


def _locale_keys(locale: str) -> set[str]:
    """Return every key declared by one locale file.

    Args:
        locale: Locale code, as listed in SUPPORTED_LOCALES.

    Returns:
        The flattened key set of that locale.
    """
    return _flatten(_load_locale(locale))


def _walk_outside_formatting(node: ast.AST) -> Iterator[ast.AST]:
    """Yield every node below the given one, f-strings excepted.

    An f-string holds its fixed parts as plain string constants, so
    walking into one hands out the prefix of a key rather than a key.

    Args:
        node: The node to walk, itself excluded.

    Yields:
        Each descendant that no f-string encloses.
    """
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.JoinedStr):
            continue
        yield child
        yield from _walk_outside_formatting(child)


def _key_literals(sections: set[str]) -> dict[str, str]:
    """Return every translation key written literally in the source.

    Collects the string constants that look like a key rather than the
    arguments of i18n.t(), because a good half of them never appear
    there: they travel as a label_key parameter or sit in a lookup table
    the call site indexes.

    A string only counts as a key when its first part names a section of
    the locale files, which leaves out logger names and module paths.
    Filenames are then dropped by hand: sections named after the SDK, the
    settings and the "common" strings make "renpy.sh", "settings.json"
    and "common.rpy" pass that test.

    Args:
        sections: Top-level section names of the reference locale.

    Returns:
        Each key mapped to the "file:line" that writes it.
    """
    found: dict[str, str] = {}
    for path in sorted(_SOURCE_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in _walk_outside_formatting(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            key = node.value
            if not _KEY_PATTERN.match(key) or key.endswith(_FILE_SUFFIXES):
                continue
            if key.split(".")[0] in sections:
                found.setdefault(key, f"{path.name}:{node.lineno}")
    return found


_TRANSLATED_LOCALES = [code for code in SUPPORTED_LOCALES if code != DEFAULT_LOCALE]


@pytest.mark.parametrize("locale", _TRANSLATED_LOCALES)
def test_every_locale_declares_the_same_keys(locale: str) -> None:
    """No locale may declare a key another one lacks."""
    reference = _locale_keys(DEFAULT_LOCALE)
    keys = _locale_keys(locale)
    assert sorted(reference - keys) == [], f"missing from {locale}.json"
    assert sorted(keys - reference) == [], f"absent from {DEFAULT_LOCALE}.json"


def test_every_key_the_code_reads_is_declared() -> None:
    """No screen may read a key the locale files do not declare."""
    reference = _load_locale(DEFAULT_LOCALE)
    declared = _flatten(reference)
    literals = _key_literals(set(reference))
    unknown = {key: where for key, where in literals.items() if key not in declared}
    assert unknown == {}


def test_the_scan_still_finds_the_keys_in_use() -> None:
    """Guard the scan itself, which passes silently once it finds nothing."""
    reference = _load_locale(DEFAULT_LOCALE)
    assert len(_key_literals(set(reference))) > 250
