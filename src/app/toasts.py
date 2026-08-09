"""The one way a screen reports what just happened."""

from collections.abc import Callable

import flet as ft

from app.theme import ACCENT, SUCCESS, TEXT_HINT, WARNING

_BACKGROUNDS = {
    SUCCESS: "#16281c",
    WARNING: "#2b2210",
}
_ERROR_BACKGROUND = "#2b1c1c"


def build_toast(
    message: str,
    color: str,
    *,
    action: str | None = None,
    on_action: Callable[[], None] | None = None,
) -> ft.SnackBar:
    """Build the floating notice reporting the outcome of an action.

    A fresh SnackBar per message, as Flet's own documentation does. A
    single reused instance only ever shows its first message: once the
    client reports the toast dismissed, Flet drops it from the page's
    dialog stack without flipping its `open` flag back to False, so
    setting `open = True` again produces no diff and page.update() sends
    nothing.

    A toast carrying an action stays up longer: five seconds is enough to
    read a message, not to notice a button, aim and click it.

    Args:
        message: What happened, already localized.
        color: The outcome, as one of the theme's SUCCESS, WARNING or
            ERROR colors. Anything else is treated as an error.
        action: Label of an optional button shown next to the message.
        on_action: Called when that button is clicked.

    Returns:
        The toast, ready to be handed to Page.show_dialog().
    """
    return ft.SnackBar(
        content=ft.Text(message, size=13, color=color),
        bgcolor=_BACKGROUNDS.get(color, _ERROR_BACKGROUND),
        behavior=ft.SnackBarBehavior.FLOATING,
        show_close_icon=True,
        close_icon_color=TEXT_HINT,
        duration=ft.Duration(seconds=10 if action else 5),
        margin=ft.Margin(left=20, right=20, bottom=20),
        action=(
            ft.SnackBarAction(
                label=action,
                text_color=ACCENT,
                on_click=lambda _e: on_action() if on_action else None,
            )
            if action
            else None
        ),
    )


def show_toast(page: ft.Page, message: str, color: str) -> ft.SnackBar:
    """Report an outcome on a screen with nothing to schedule.

    Views driving background threads have to hand the toast to the event
    loop themselves; this is for the screens whose actions all run on
    that loop already.

    Args:
        page: The page the toast is shown over.
        message: What happened, already localized.
        color: SUCCESS, WARNING or ERROR.

    Returns:
        The toast that was shown, so the caller can dismiss it early.
    """
    toast = build_toast(message, color)
    page.show_dialog(toast)
    return toast
