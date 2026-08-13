"""Central theme list: the single place to add a selectable UI theme.

Each Theme entry drives everything at once: the settings dropdown, the
palette the interface draws with, and the folder its logo is read from. To
support a new theme, append one entry to THEMES, declare a themes.<code>
key in both locale files, and drop a logo folder in src/assets. Nothing
else to change.

The `code` is what lands in the settings file, so it must stay stable once
released. It is also the locale key suffix, which is why it is a lowercase
identifier.

Palette is deliberately flat and exhaustive: every colour the interface
draws with is declared here, and a theme that forgot one would not build.
That is the property the whole design rests on, since a colour written
anywhere else is a colour that cannot follow the theme.
"""

from dataclasses import dataclass

import flet as ft

from core.i18n import i18n


@dataclass(frozen=True)
class Palette:
    """Every colour the interface draws with, for one theme.

    Field names double as the module-level names exported by app.theme, so
    renaming one here renames it for the whole application.

    Attributes:
        ACCENT: The brand colour. Fills the primary buttons, but also
            serves as a text and cursor colour, so it has to stay readable
            against BG as well as carry ACCENT_ON on top of itself.
        ACCENT_ON: What is drawn over an ACCENT fill.
        BG: The page background.
        BG_INPUT: Fill of a text field or dropdown.
        BG_METHOD_SEL: Fill of a selected extraction method.
        BG_FILE_SEL: Fill of the selected row in the file list.
        BG_MENU: Fill of anything floating above the page: dialogs, menus.
        BORDER: Hairline separator, barely distinct from the surface it
            sits on.
        BORDER_COLOR: Ordinary control outline.
        BORDER_STRONG: Outline of a control asking to be noticed.
        TEXT_H: Headings.
        TEXT: Body text.
        TEXT_MUTED: Secondary text, still meant to be read.
        TEXT_HINT: Placeholder text and inactive icons.
        TEXT_DIM: Text stepped back from TEXT_MUTED.
        TEXT_PATH: Filesystem paths.
        SUCCESS: Positive outcome, as text and as icon.
        ERROR: Failure, as text and as icon.
        WARNING: Caution, as text and as icon.
        DOT_NONE: Status dot of an untranslated unit.
        DOT_DRAFT: Status dot of a draft.
        DOT_IMPORTED: Status dot of an imported translation.
        DOT_AI: Status dot of a machine suggestion.
        DOT_HUMAN: Status dot of a validated translation.
        FOCUS_RING: The keyboard focus ring, drawn by focusable(). Needs
            real contrast against BG: it is the only thing telling a
            keyboard user where they are.
        HOVER_TINT: Overlay tinting a control under the pointer.
        HOVER_RING: Ring drawn around a control under the pointer.
        SURFACE_DISABLED: Fill of a primary button that cannot be clicked.
        BANNER_BG: Fill of the running-job banner.
        TOOLBAR_BG: Fill of the review toolbar.
        TABLE_HEADER_BG: Fill of the review table header.
        PANEL_BG: Fill of a raised card.
        TILE_BG: Fill of the square holding an icon.
        BORDER_SUBTLE: Outline of a card, and the stepper's connector.
        BORDER_ROW: Separator between rows of a list.
        DANGER_BORDER: Outline of a destructive action.
        TOAST_SUCCESS_BG: Fill of a toast reporting a success.
        TOAST_WARNING_BG: Fill of a toast reporting a warning.
        TOAST_ERROR_BG: Fill of a toast reporting a failure.
        SUCCESS_PANEL_BG: Fill of the export success panel.
        SUCCESS_PANEL_BORDER: Outline of that panel.
        SUCCESS_TITLE: Its heading.
        SUCCESS_PATH: The path it prints.
        ON_SUCCESS: What is drawn over a SUCCESS fill.
        STEP_DONE_BG: Fill of a completed step in the stepper.
        STEP_TODO_BORDER: Outline of a step not reached yet.
    """

    ACCENT: str
    ACCENT_ON: str

    BG: str
    BG_INPUT: str
    BG_METHOD_SEL: str
    BG_FILE_SEL: str
    BG_MENU: str

    BORDER: str
    BORDER_COLOR: str
    BORDER_STRONG: str

    TEXT_H: str
    TEXT: str
    TEXT_MUTED: str
    TEXT_HINT: str
    TEXT_DIM: str
    TEXT_PATH: str

    SUCCESS: str
    ERROR: str
    WARNING: str

    DOT_NONE: str
    DOT_DRAFT: str
    DOT_IMPORTED: str
    DOT_AI: str
    DOT_HUMAN: str

    FOCUS_RING: str
    HOVER_TINT: str
    HOVER_RING: str

    SURFACE_DISABLED: str
    BANNER_BG: str
    TOOLBAR_BG: str
    TABLE_HEADER_BG: str
    PANEL_BG: str
    TILE_BG: str

    BORDER_SUBTLE: str
    BORDER_ROW: str
    DANGER_BORDER: str

    TOAST_SUCCESS_BG: str
    TOAST_WARNING_BG: str
    TOAST_ERROR_BG: str

    SUCCESS_PANEL_BG: str
    SUCCESS_PANEL_BORDER: str
    SUCCESS_TITLE: str
    SUCCESS_PATH: str
    ON_SUCCESS: str

    STEP_DONE_BG: str
    STEP_TODO_BORDER: str


@dataclass(frozen=True)
class Theme:
    """One selectable theme.

    Read as palettes.Theme and never imported bare, so it is not mistaken
    for ft.Theme, which is Flet's own and a different thing entirely.

    Attributes:
        code: Internal identifier, stored in the settings file and used as
            the themes.<code> locale key.
        label: English name, shown when the locales do not translate the
            code.
        dark: Whether the palette is a dark one. Drives Flet's own
            ThemeMode, so the Material defaults agree with the palette.
        icons: Name of the folder under src/assets holding this theme's
            logo. Naming it here is what keeps the rest of the code from
            testing for light or dark to pick an image.
        colors: The palette itself.
    """

    code: str
    label: str
    dark: bool
    icons: str
    colors: Palette


_DARK_COLORS = Palette(
    ACCENT="#cbbdff",
    ACCENT_ON="#241a52",
    BG="#141318",
    BG_INPUT="#1d1c24",
    BG_METHOD_SEL="#201c2e",
    BG_FILE_SEL="#252336",
    BG_MENU="#1a1822",
    BORDER="#1a1820",
    BORDER_COLOR="#3a3744",
    BORDER_STRONG="#4b4856",
    TEXT_H="#ece7f2",
    TEXT="#e4dfee",
    TEXT_MUTED="#9b96a6",
    TEXT_HINT="#6f6b79",
    TEXT_DIM="#8e8a98",
    TEXT_PATH="#cdc8d8",
    SUCCESS="#7ddf9b",
    ERROR="#ff8a80",
    WARNING="#ffc947",
    DOT_NONE="#4a4759",
    DOT_DRAFT="#7fbfff",
    DOT_IMPORTED="#c9a5ff",
    DOT_AI="#ffc947",
    DOT_HUMAN="#7ddf9b",
    FOCUS_RING="#4fd1ff",
    HOVER_TINT=ft.Colors.with_opacity(0.09, ft.Colors.WHITE),
    HOVER_RING=ft.Colors.with_opacity(0.28, ft.Colors.WHITE),
    SURFACE_DISABLED="#26242f",
    BANNER_BG="#1b1a26",
    TOOLBAR_BG="#17161f",
    TABLE_HEADER_BG="#15141d",
    PANEL_BG="#201d2b",
    TILE_BG="#1f1b2b",
    BORDER_SUBTLE="#322f3d",
    BORDER_ROW="#1e1d27",
    DANGER_BORDER="#4a2828",
    TOAST_SUCCESS_BG="#16281c",
    TOAST_WARNING_BG="#2b2210",
    TOAST_ERROR_BG="#2b1c1c",
    SUCCESS_PANEL_BG="#0f2316",
    SUCCESS_PANEL_BORDER="#2a6640",
    SUCCESS_TITLE="#bdeccb",
    SUCCESS_PATH="#8aa792",
    ON_SUCCESS="#10261a",
    STEP_DONE_BG="#2a2638",
    STEP_TODO_BORDER="#423f4d",
)

_LIGHT_COLORS = Palette(
    ACCENT="#6246d9",
    ACCENT_ON="#ffffff",
    BG="#f7f5fb",
    BG_INPUT="#ffffff",
    BG_METHOD_SEL="#efeafd",
    BG_FILE_SEL="#ebe6f8",
    BG_MENU="#ffffff",
    BORDER="#e3dfec",
    BORDER_COLOR="#cbc5da",
    BORDER_STRONG="#a9a2bd",
    TEXT_H="#17151f",
    TEXT="#2a2735",
    TEXT_MUTED="#5f5a6e",
    TEXT_HINT="#807a90",
    TEXT_DIM="#6b6579",
    TEXT_PATH="#3d3950",
    SUCCESS="#1c7a43",
    ERROR="#c02a25",
    WARNING="#9a6400",
    DOT_NONE="#c3bed1",
    DOT_DRAFT="#2f7fd1",
    DOT_IMPORTED="#7a4fd0",
    DOT_AI="#b5790a",
    DOT_HUMAN="#1c7a43",
    FOCUS_RING="#0b6fb8",
    HOVER_TINT=ft.Colors.with_opacity(0.06, ft.Colors.BLACK),
    HOVER_RING=ft.Colors.with_opacity(0.22, ft.Colors.BLACK),
    SURFACE_DISABLED="#e7e3ef",
    BANNER_BG="#f1eef9",
    TOOLBAR_BG="#f2eff8",
    TABLE_HEADER_BG="#eeebf5",
    PANEL_BG="#ffffff",
    TILE_BG="#f0ecfa",
    BORDER_SUBTLE="#ddd8e8",
    BORDER_ROW="#e6e2f0",
    DANGER_BORDER="#e8bdbb",
    TOAST_SUCCESS_BG="#e3f5e9",
    TOAST_WARNING_BG="#fdf1d8",
    TOAST_ERROR_BG="#fbe4e3",
    SUCCESS_PANEL_BG="#e8f6ed",
    SUCCESS_PANEL_BORDER="#9dd3b2",
    SUCCESS_TITLE="#12572f",
    SUCCESS_PATH="#3f6b52",
    ON_SUCCESS="#ffffff",
    STEP_DONE_BG="#e6e0f6",
    STEP_TODO_BORDER="#c6c0d4",
)

THEMES: list[Theme] = [
    Theme("dark", "Dark", dark=True, icons="icons-dark", colors=_DARK_COLORS),
    Theme("light", "Light", dark=False, icons="icons-light", colors=_LIGHT_COLORS),
]

THEME_BY_CODE: dict[str, Theme] = {theme.code: theme for theme in THEMES}

# The settings value asking for the operating system's own choice. Not a
# theme: it is stored in its place, and resolves to one of the two below.
SYSTEM = "system"

# What following the operating system resolves to. Named rather than picked
# from THEMES by their `dark` flag: a second dark theme added at the top of
# the list would otherwise silently change what "system" means.
SYSTEM_DARK = "dark"
SYSTEM_LIGHT = "light"


def get_theme(code: str) -> Theme | None:
    """Return the Theme entry for an identifier, if known.

    Args:
        code: The theme identifier to look up (case-insensitive).

    Returns:
        The matching Theme, or None for unknown identifiers.
    """
    return THEME_BY_CODE.get(code.lower())


def localized_label(code: str) -> str:
    """Return a theme's name in the language of the interface.

    Adding a theme still takes a single entry in THEMES: without a
    themes.<code> key in the locale files, the name simply stays the
    English label declared there.

    Args:
        code: The theme identifier to name (case-insensitive).

    Returns:
        The translated name, the English label, or the code itself for a
        theme nobody declared.
    """
    key = f"themes.{code.lower()}"
    translated = i18n.t(key)
    if translated != key:
        return translated
    theme = get_theme(code)
    return theme.label if theme else code
