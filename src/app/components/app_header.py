"""Persistent top header shown above the stepper nav on every page."""

from collections.abc import Callable

import flet as ft
from flet.controls.control_event import Event

from app.theme import BG, BORDER, TEXT_H, TEXT_HINT, focusable
from core.i18n import i18n
from core.languages import localized_label

APP_NAME = "Ren'Py Translation Studio"


def _build_project_label(game_name: str, target_language: str) -> ft.Control:
    """Name the project being worked on, next to the application's own name.

    No screen said which game was open. One machine can hold several, the
    recent-projects list exists to switch between them, and the review
    screen shows a file name that is the same in every game. The header
    is where it belongs, being the one strip present on every screen.

    Args:
        game_name: Resolved name of the game, empty before a project is
            opened.
        target_language: Language folder being translated into, empty
            before a project is opened.

    Returns:
        The label, taking the slack of the row so a long game name is cut
        rather than pushing the buttons off the window, or an empty
        spacer when no project is open.
    """
    if not game_name:
        return ft.Container(expand=True)

    parts = [game_name]
    if target_language:
        parts.append(localized_label(target_language))
    return ft.Container(
        content=ft.Text(
            " · ".join(parts),
            size=13,
            color=TEXT_HINT,
            no_wrap=True,
            overflow=ft.TextOverflow.ELLIPSIS,
            tooltip=" · ".join(parts),
        ),
        padding=ft.Padding(left=14, right=14, top=0, bottom=0),
        expand=True,
    )


def build_app_header(
    on_settings_click: Callable[[Event[ft.TextButton]], None],
    on_help_click: Callable[[Event[ft.TextButton]], None],
    game_name: str = "",
    target_language: str = "",
) -> ft.Container:
    """Build the header row: app name on the left, help and settings on the right.

    Args:
        on_settings_click: Callback invoked when the settings button is clicked.
        on_help_click: Callback invoked when the help button is clicked.
        game_name: Name of the open game, shown next to the application's
            own name. Omitted before a project is opened.
        target_language: Language folder being translated into, named in
            the language of the interface.

    Returns:
        A Container spanning the page width with the header row.
    """
    return ft.Container(
        content=ft.Row(
            [
                ft.Text(
                    APP_NAME,
                    size=15,
                    weight=ft.FontWeight.W_700,
                    color=TEXT_H,
                ),
                _build_project_label(game_name, target_language),
                focusable(
                    ft.Container(
                        content=ft.Icon(
                            ft.Icons.HELP_OUTLINE, size=18, color=TEXT_HINT
                        ),
                        width=32,
                        height=32,
                        alignment=ft.Alignment(0, 0),
                        ink=True,
                        border_radius=8,
                    ),
                    on_click=on_help_click,
                    tooltip=i18n.t("help.title"),
                    width=32,
                    height=32,
                ),
                focusable(
                    ft.Container(
                        content=ft.Icon(
                            ft.Icons.SETTINGS_OUTLINED, size=18, color=TEXT_HINT
                        ),
                        width=32,
                        height=32,
                        alignment=ft.Alignment(0, 0),
                        ink=True,
                        border_radius=8,
                    ),
                    on_click=on_settings_click,
                    tooltip=i18n.t("settings.title"),
                    width=32,
                    height=32,
                ),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=ft.Padding(left=40, right=40, top=14, bottom=14),
        border=ft.Border(bottom=ft.BorderSide(1, BORDER)),
        bgcolor=BG,
    )
