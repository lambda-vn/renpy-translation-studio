"""Tests for the Windows path length guard."""

import sys
from pathlib import Path

import pytest

from core.path_budget import (
    LONGEST_SHIPPED_RELATIVE_PATH,
    USABLE_PATH_LENGTH,
    characters_over_budget,
    long_path_message,
    refuse_to_start_on_long_path,
)


def _installed_longest_relative_path() -> int:
    """Return the deepest path under the site-packages tests run from."""
    root = Path(sys.prefix) / "Lib" / "site-packages"
    if not root.is_dir():
        root = next(Path(sys.prefix).glob("lib/python*/site-packages"))
    return max(len(str(p.relative_to(root))) for p in root.rglob("*"))


def test_constant_covers_what_is_actually_installed() -> None:
    """The measured constant must not fall behind the dependencies.

    A build ships the compiled twin of a module, one character longer
    than the source this walks, so the constant has to clear the
    measurement by that much. When a dependency lands a longer name than
    mistralai's, this fails and the constant is re-measured rather than
    the guard quietly checking the wrong number.
    """
    assert _installed_longest_relative_path() + 1 <= LONGEST_SHIPPED_RELATIVE_PATH


def test_no_budget_problem_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    assert characters_over_budget() is None


def test_short_install_is_within_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "path", ["C:\\rts\\site-packages"])
    assert characters_over_budget() is None


def _root_of_length(length: int) -> str:
    """Build a site-packages path of exactly the requested length."""
    suffix = "\\site-packages"
    return "C:\\" + "a" * (length - len("C:\\") - len(suffix)) + suffix


def test_longest_install_that_still_fits(monkeypatch: pytest.MonkeyPatch) -> None:
    """The last root that fits reports nothing, the next one reports one."""
    monkeypatch.setattr(sys, "platform", "win32")
    fits = USABLE_PATH_LENGTH - LONGEST_SHIPPED_RELATIVE_PATH - 1

    monkeypatch.setattr(sys, "path", [_root_of_length(fits)])
    assert characters_over_budget() is None

    monkeypatch.setattr(sys, "path", [_root_of_length(fits + 1)])
    assert characters_over_budget() == 1


def test_long_install_reports_what_has_to_go(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    fits = USABLE_PATH_LENGTH - LONGEST_SHIPPED_RELATIVE_PATH - 1
    monkeypatch.setattr(sys, "path", [_root_of_length(fits + 7)])
    assert characters_over_budget() == 7


def test_no_site_packages_on_the_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "path", ["C:\\somewhere\\else", ""])
    assert characters_over_budget() is None


def test_message_names_the_directory_and_the_overshoot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = "C:\\deep\\site-packages"
    monkeypatch.setattr(sys, "path", [root])
    message = long_path_message(12)
    assert root in message
    assert "12" in message


def test_start_is_refused_when_over_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """A path over budget stops the process instead of letting it import.

    The locale switch is stubbed rather than allowed to run: it reads the
    settings of whoever runs the suite and moves a module-level
    singleton, which every test asserting on an English message would
    then inherit.
    """
    monkeypatch.setattr("core.path_budget.characters_over_budget", lambda: 12)
    monkeypatch.setattr("core.path_budget.i18n.set_locale", lambda locale: None)
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(SystemExit):
        refuse_to_start_on_long_path()


def test_start_proceeds_when_within_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("core.path_budget.characters_over_budget", lambda: None)
    refuse_to_start_on_long_path()
