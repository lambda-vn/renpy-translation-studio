"""The single declaration of the keyboard shortcuts.

Two tables, read by the places that used to hold their own copy: the views,
which run the actions, and the help dialog, which lists them. Adding a
shortcut is adding a line here plus the method it names; forgetting to
document it is no longer possible, since the dialog is built from these
lists.

The split is what a shortcut answers for, not where it is implemented.
GLOBAL_SHORTCUTS work on every screen and are installed once by the entry
point; REVIEW_SHORTCUTS only mean anything in front of a list of lines.

Modifiers are matched exactly. Ctrl+Shift+Enter and Ctrl+Enter are two
entries that cannot be confused, whatever order they sit in.
"""

from dataclasses import dataclass

from core.i18n import i18n


@dataclass(frozen=True)
class Shortcut:
    """One key combination and the action it runs.

    Attributes:
        key: Flet key name, uppercased ("F", "ENTER", "ARROW LEFT").
        action: Name of the method bound to it, without its leading
            underscore.
        label_key: i18n key naming the action in the help dialog.
        ctrl: Whether Control (or Command) must be held.
        shift: Whether Shift must be held.
        alt: Whether Alt must be held.
    """

    key: str
    action: str
    label_key: str
    ctrl: bool = False
    shift: bool = False
    alt: bool = False


GLOBAL_SHORTCUTS: tuple[Shortcut, ...] = (
    Shortcut("F1", "open_help", "help.shortcut_help"),
    Shortcut("ESCAPE", "close_dialog", "help.shortcut_escape"),
)

REVIEW_SHORTCUTS: tuple[Shortcut, ...] = (
    Shortcut("F", "focus_search", "help.shortcut_search", ctrl=True),
    Shortcut("S", "save", "help.shortcut_save", ctrl=True),
    Shortcut("ENTER", "validate_row", "help.shortcut_validate", ctrl=True),
    Shortcut(
        "ENTER",
        "spread_duplicates",
        "help.shortcut_spread_duplicates",
        ctrl=True,
        shift=True,
    ),
    Shortcut("D", "copy_source", "help.shortcut_copy_source", ctrl=True),
    Shortcut("M", "toggle_review", "help.shortcut_needs_review", ctrl=True),
    Shortcut("ARROW UP", "focus_previous_row", "help.shortcut_prev_row", alt=True),
    Shortcut("ARROW DOWN", "focus_next_row", "help.shortcut_next_row", alt=True),
    Shortcut(
        "ARROW UP",
        "focus_previous_file",
        "help.shortcut_prev_file",
        alt=True,
        shift=True,
    ),
    Shortcut(
        "ARROW DOWN",
        "focus_next_file",
        "help.shortcut_next_file",
        alt=True,
        shift=True,
    ),
    Shortcut("ARROW LEFT", "previous_page", "help.shortcut_prev_page", alt=True),
    Shortcut("ARROW RIGHT", "next_page", "help.shortcut_next_page", alt=True),
    Shortcut("CONTEXT MENU", "open_file_menu", "help.shortcut_file_menu"),
)


def match(
    key: str, *, ctrl: bool, shift: bool, alt: bool, table: tuple[Shortcut, ...]
) -> Shortcut | None:
    """Find the shortcut a key event fires in one table, if any.

    Args:
        key: Flet key name, uppercased by the caller.
        ctrl: Whether Control or Command was held.
        shift: Whether Shift was held.
        alt: Whether Alt was held.
        table: The table to look in, GLOBAL_SHORTCUTS or REVIEW_SHORTCUTS.

    Returns:
        The matching shortcut, or None when the combination is bound to
        nothing in that table.
    """
    for shortcut in table:
        if (
            shortcut.key == key
            and shortcut.ctrl == ctrl
            and shortcut.shift == shift
            and shortcut.alt == alt
        ):
            return shortcut
    return None


_KEY_NAMES = {
    "ESCAPE": "help.key_escape",
    "ENTER": "help.key_enter",
    "CONTEXT MENU": "help.key_context_menu",
}

_KEY_GLYPHS = {
    "ARROW LEFT": "←",
    "ARROW RIGHT": "→",
    "ARROW UP": "↑",
    "ARROW DOWN": "↓",
}


def combination(shortcut: Shortcut) -> str:
    """Spell a shortcut the way it is typed, for the help dialog.

    Built on each call rather than stored, so a locale change reaches the
    key names too.

    Args:
        shortcut: The shortcut to name.

    Returns:
        The combination as displayed, e.g. "Ctrl+Shift+Entree".
    """
    parts = []
    if shortcut.ctrl:
        parts.append("Ctrl")
    if shortcut.shift:
        parts.append("Shift")
    if shortcut.alt:
        parts.append("Alt")
    named = _KEY_NAMES.get(shortcut.key)
    parts.append(
        i18n.t(named)
        if named
        else _KEY_GLYPHS.get(shortcut.key, shortcut.key.capitalize())
    )
    return "+".join(parts)
