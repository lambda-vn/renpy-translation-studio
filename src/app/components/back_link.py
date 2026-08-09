"""The one way back out of a screen, shared so every screen offers it alike."""

from collections.abc import Callable

import flet as ft

from app.theme import TEXT_MUTED, focusable


def build_back_link(label: str, on_click: Callable[[], None]) -> ft.Control:
    """Build the arrow link that leaves a screen, placed at its top left.

    Screens reached from the review used to end on their way back: a bare
    label in a footer, below content long enough to scroll, in a spot that
    differed from one screen to the next. Leaving is the first thing
    somebody looks for when they open a screen by mistake, so it belongs
    where reading starts rather than where it ends, and it looks the same
    everywhere because it is now built in one place.

    Args:
        label: Where the link goes, named as the destination.
        on_click: Called when the link is activated.

    Returns:
        A focusable arrow link, ready to head a view's column.
    """
    return focusable(
        ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.ARROW_BACK, size=15, color=TEXT_MUTED),
                    ft.Text(
                        label,
                        size=13,
                        weight=ft.FontWeight.W_500,
                        color=TEXT_MUTED,
                    ),
                ],
                tight=True,
                spacing=7,
            ),
            ink=True,
            border_radius=8,
            padding=ft.Padding(left=4, right=8, top=4, bottom=4),
        ),
        on_click=lambda _e: on_click(),
    )
