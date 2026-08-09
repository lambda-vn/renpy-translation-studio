"""What every modal of the application shares: its way out and its buttons."""

from collections.abc import Callable
from typing import Any, Literal

import flet as ft

from app.theme import ACCENT, ACCENT_ON, ERROR, TEXT_MUTED, focusable

DialogTone = Literal["neutral", "accent", "primary", "danger"]

_TONE_COLORS: dict[DialogTone, tuple[str, str | None, ft.FontWeight]] = {
    "neutral": (TEXT_MUTED, None, ft.FontWeight.W_500),
    "accent": (ACCENT, None, ft.FontWeight.W_600),
    "primary": (ACCENT_ON, ACCENT, ft.FontWeight.W_600),
    "danger": (ERROR, None, ft.FontWeight.W_600),
}


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
    color, bgcolor, weight = _TONE_COLORS[tone]
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
