"""Checks keeping the theme registry, the palettes and the views in step.

Written against palettes.THEMES rather than against the two themes that
exist today: adding a third one is meant to take a single entry, so these
must cover it without being touched.

The last one is the one that matters most. A colour written straight into
a view is invisible to every other guard -- ruff, mypy and the rest of the
suite all stay green while that view quietly keeps its dark background on
a light theme.
"""

import json
import re
from dataclasses import fields
from pathlib import Path

import pytest

from app import palettes, theme
from core.i18n import LOCALES_DIR, SUPPORTED_LOCALES

_ASSETS_DIR = Path(__file__).resolve().parent.parent / "src" / "assets"

_APP_DIR = Path(__file__).resolve().parent.parent / "src" / "app"

_HEX_PATTERN = re.compile(r"^#[0-9a-f]{6}$")

_HEX_LITERAL = re.compile(r"#[0-9a-fA-F]{6,8}")

# The two hover veils are an opacity over black or white, which Flet spells
# as an eight-digit colour rather than the six-digit hex every other entry
# uses.
_VEILS = {"HOVER_TINT", "HOVER_RING"}

# Fully transparent belongs to no palette: it is what focusable() draws
# when there is no ring to show.
_NEUTRAL_LITERALS = {"#00000000"}


def test_every_theme_has_a_distinct_code() -> None:
    """Two themes sharing a code would make one unreachable."""
    codes = [entry.code for entry in palettes.THEMES]
    assert sorted(codes) == sorted(set(codes))


def test_no_theme_takes_the_system_value_as_a_code() -> None:
    """A theme named "system" could never be told from following the OS."""
    assert palettes.SYSTEM not in {entry.code for entry in palettes.THEMES}


@pytest.mark.parametrize("entry", palettes.THEMES, ids=lambda e: e.code)
def test_every_colour_is_a_hex_value(entry: palettes.Theme) -> None:
    """A palette holding an empty or malformed colour draws nothing."""
    for field in fields(entry.colors):
        value = getattr(entry.colors, field.name)
        assert value, f"{entry.code}.{field.name} is empty"
        if field.name in _VEILS:
            continue
        assert _HEX_PATTERN.match(value), f"{entry.code}.{field.name} = {value!r}"


@pytest.mark.parametrize("entry", palettes.THEMES, ids=lambda e: e.code)
def test_every_theme_ships_its_logo(entry: palettes.Theme) -> None:
    """The folder a theme names has to hold the size onboarding asks for."""
    logo = _ASSETS_DIR / entry.icons / "icon-256x256.png"
    assert logo.is_file(), f"{entry.code}: {logo} is missing"


def test_the_packaged_icon_exists() -> None:
    """flet build reads this exact name to make every platform's icon."""
    assert (_ASSETS_DIR / "icon.png").is_file()


def test_the_window_icon_exists() -> None:
    """main.py points page.window.icon at this file by name.

    Its name must stay outside the icon.* glob flet build reads, or a
    Windows build would take this 256-pixel icon over the 1024 one.
    """
    assert (_ASSETS_DIR / "window.ico").is_file()
    assert not (_ASSETS_DIR / "icon.ico").exists()


def test_following_the_system_lands_on_declared_themes() -> None:
    """Both ends of the system setting must name a theme that exists."""
    dark = palettes.get_theme(palettes.SYSTEM_DARK)
    light = palettes.get_theme(palettes.SYSTEM_LIGHT)
    assert dark is not None and dark.dark
    assert light is not None and not light.dark


@pytest.mark.parametrize("locale", SUPPORTED_LOCALES)
def test_every_theme_is_named_in_every_locale(locale: str) -> None:
    """A theme with no themes.<code> key shows its English label instead."""
    with (LOCALES_DIR / f"{locale}.json").open(encoding="utf-8") as handle:
        strings = json.load(handle)
    declared = strings.get("themes", {})
    for entry in palettes.THEMES:
        assert entry.code in declared, f"themes.{entry.code} missing from {locale}"


@pytest.mark.parametrize("entry", palettes.THEMES, ids=lambda e: e.code)
def test_applying_a_theme_rebinds_every_colour(entry: palettes.Theme) -> None:
    """Switching has to move the names the views read, not just a record."""
    try:
        theme.set_theme(entry.code)
        assert theme.active_theme() is entry
        for field in fields(entry.colors):
            expected = getattr(entry.colors, field.name)
            assert getattr(theme, field.name) == expected
    finally:
        theme.set_theme(palettes.SYSTEM_DARK)


def test_an_unknown_theme_is_refused() -> None:
    """A typo must fail loudly rather than leave the palette half applied."""
    with pytest.raises(ValueError):
        theme.set_theme("solarized")


def test_no_view_writes_a_colour_of_its_own() -> None:
    """Every colour lives in palettes.py, or it cannot follow the theme.

    This is the guard against the drift the light theme was added to
    undo: forty-nine colours had been written straight into the views,
    where no theme switch could ever reach them.
    """
    written: dict[str, str] = {}
    for path in sorted(_APP_DIR.rglob("*.py")):
        if path.name == "palettes.py":
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for found in _HEX_LITERAL.findall(line):
                if found not in _NEUTRAL_LITERALS:
                    written[f"{path.name}:{number}"] = found
    assert written == {}
