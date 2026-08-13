"""What every modal of the application shares: its way out and its buttons."""

from collections.abc import Callable
from typing import Any, Literal

import flet as ft

from app import theme
from app.theme import focusable

DialogTone = Literal["neutral", "accent", "primary", "danger"]


def _tone_style(tone: DialogTone) -> tuple[str, str | None, ft.FontWeight]:
    """Return the text color, fill and weight carrying a tone.

    Resolved on each call rather than held in a module-level table: the
    colours move with the theme, and a table filled at import would keep
    the palette the application started with.

    Args:
        tone: What the action is.

    Returns:
        The text color, the fill behind it if any, and the font weight.
    """
    styles: dict[DialogTone, tuple[str, str | None, ft.FontWeight]] = {
        "neutral": (theme.TEXT_MUTED, None, ft.FontWeight.W_500),
        "accent": (theme.ACCENT, None, ft.FontWeight.W_600),
        "primary": (theme.ACCENT_ON, theme.ACCENT, ft.FontWeight.W_600),
        "danger": (theme.ERROR, None, ft.FontWeight.W_600),
    }
    return styles[tone]


def dialog_action(
    label: str,
    on_click: Callable[[Any], Any],
    *,
    tone: DialogTone = "neutral",
) -> ft.Control:
    """Build one button of a dialog's action row.

    Every dialog used to spell its own buttons out, and they drifted:
    the same "Cancel" came in two weights and two paddings depending on
    which screen opened it. What a button does is carried by its tone
    here, so a destructive confirmation looks destructive everywhere and
    nowhere else.

    Args:
        label: The button's text.
        on_click: Called on click, on Enter and on Space.
        tone: What the action is. "neutral" backs out, "accent" and
            "primary" confirm, "danger" is the one that cannot be undone.

    Returns:
        The focusable action, ready to sit in an AlertDialog's actions.
    """
    color, bgcolor, weight = _tone_style(tone)
    horizontal = 18 if tone == "primary" else 12
    return focusable(
        ft.Container(
            content=ft.Text(label, size=13.5, weight=weight, color=color),
            bgcolor=bgcolor,
            padding=ft.Padding(left=horizontal, right=horizontal, top=8, bottom=8),
            ink=True,
            border_radius=8,
        ),
        on_click=on_click,
    )


def top_alert_dialog(page: ft.Page) -> ft.AlertDialog | None:
    """Return the AlertDialog standing in front of the view, if any.

    Only AlertDialogs count: status toasts ride the same stack and must
    not pass for something the user has to answer.

    Args:
        page: The Flet page whose dialog stack is inspected.

    Returns:
        The topmost open dialog, or None when the view is unobstructed.
    """
    dialogs = getattr(page, "_dialogs", None)
    if dialogs is None:
        return None
    return next(
        (
            dialog
            for dialog in reversed(dialogs.controls)
            if isinstance(dialog, ft.AlertDialog) and dialog.open
        ),
        None,
    )


def close_top_alert_dialog(page: ft.Page) -> bool:
    """Close the AlertDialog on top of the stack, if there is one.

    A modal that only a mouse can leave is a keyboard trap, and every
    dialog here is modal so a stray click never dismisses a confirmation.
    Escape is the way out, which nothing in Flet wires for us.

    Args:
        page: The Flet page whose dialog stack is inspected.

    Returns:
        True when a dialog was closed, False when none was open.
    """
    top = top_alert_dialog(page)
    if top is None:
        return False
    top.open = False
    top.update()
    return True
