"""Tests for app/shortcuts.py, the single review shortcut table."""

import json
from collections.abc import Iterator

import pytest

from app.shortcuts import (
    GLOBAL_SHORTCUTS,
    REVIEW_SHORTCUTS,
    combination,
    match,
)
from core.i18n import LOCALES_DIR, i18n

_LOCALES = LOCALES_DIR
_ALL = GLOBAL_SHORTCUTS + REVIEW_SHORTCUTS


def _labels(locale: str) -> dict[str, str]:
    """Return the help section of a locale file.

    Args:
        locale: Locale code, 'en' or 'fr'.

    Returns:
        The keys declared under "help" in that locale.
    """
    data = json.loads((_LOCALES / f"{locale}.json").read_text(encoding="utf-8"))
    return dict(data["help"])


def test_every_shortcut_is_named_in_both_locales() -> None:
    """The help dialog is built from these tables, so a missing label shows."""
    for locale in ("en", "fr"):
        labels = _labels(locale)
        for shortcut in _ALL:
            key = shortcut.label_key.removeprefix("help.")
            assert key in labels, f"{shortcut.label_key} missing from {locale}.json"


def test_no_two_shortcuts_share_a_combination() -> None:
    """A global entry shadows a review one, so the tables cannot overlap."""
    combinations = [(s.key, s.ctrl, s.shift, s.alt) for s in _ALL]
    assert len(set(combinations)) == len(combinations)


def test_every_shortcut_runs_a_distinct_action() -> None:
    actions = [s.action for s in _ALL]
    assert len(set(actions)) == len(actions)


def test_shift_is_matched_exactly() -> None:
    """Ctrl+Shift+Enter and Ctrl+Enter must not be confused for each other."""
    with_shift = match(
        "ENTER", ctrl=True, shift=True, alt=False, table=REVIEW_SHORTCUTS
    )
    without = match("ENTER", ctrl=True, shift=False, alt=False, table=REVIEW_SHORTCUTS)

    assert with_shift is not None
    assert without is not None
    assert with_shift.action != without.action


def test_an_unbound_combination_matches_nothing() -> None:
    assert match("A", ctrl=False, shift=False, alt=False, table=_ALL) is None
    assert match("F", ctrl=False, shift=False, alt=False, table=_ALL) is None


def test_a_table_only_answers_for_its_own_shortcuts() -> None:
    """The review handler consults both tables, and must not mix them up."""
    assert (
        match("F1", ctrl=False, shift=False, alt=False, table=REVIEW_SHORTCUTS) is None
    )
    assert match("S", ctrl=True, shift=False, alt=False, table=GLOBAL_SHORTCUTS) is None


@pytest.fixture()
def restore_locale() -> Iterator[None]:
    """Put the interface language back, the i18n singleton being shared."""
    previous = i18n.locale
    yield
    i18n.set_locale(previous)


def test_combination_follows_the_interface_language(restore_locale: None) -> None:
    enter = next(s for s in REVIEW_SHORTCUTS if s.action == "validate_row")

    i18n.set_locale("en")
    assert combination(enter) == "Ctrl+Enter"
    i18n.set_locale("fr")
    assert combination(enter) == "Ctrl+Entrée"
