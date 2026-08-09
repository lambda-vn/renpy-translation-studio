"""Shared help dialog: what the keyboard can do in the review screen."""

import flet as ft

from app.shortcuts import GLOBAL_SHORTCUTS, REVIEW_SHORTCUTS, Shortcut, combination
from app.theme import (
    ACCENT,
    BORDER_COLOR,
    TEXT_H,
    TEXT_HINT,
    TEXT_MUTED,
    border_all,
    focusable,
)
from core.i18n import i18n


def _build_shortcut_row(keys: str, label_key: str) -> ft.Row:
    """Build one line of the shortcut table.

    Args:
        keys: The key combination, shown as typed and left untranslated.
        label_key: i18n key of what the combination does.

    Returns:
        A Row pairing the keys with their action.
    """
    return ft.Row(
        [
            ft.Container(
                content=ft.Text(keys, size=12, color=TEXT_H),
                width=104,
                border=border_all(1, BORDER_COLOR),
                border_radius=6,
                padding=ft.Padding(left=8, right=8, top=4, bottom=4),
            ),
            ft.Text(i18n.t(label_key), size=13, color=TEXT_MUTED, expand=True),
        ],
        spacing=12,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )


def _build_group(title_key: str, table: tuple[Shortcut, ...]) -> ft.Control:
    """Build one titled block of the shortcut table.

    Args:
        title_key: i18n key naming what the block's shortcuts apply to.
        table: The shortcuts to list, in declaration order.

    Returns:
        A Column pairing a section title with its shortcut rows.
    """
    return ft.Column(
        [
            ft.Text(
                i18n.t(title_key),
                size=11,
                weight=ft.FontWeight.W_700,
                color=TEXT_HINT,
            ),
            *(_build_shortcut_row(combination(s), s.label_key) for s in table),
        ],
        spacing=7,
        tight=True,
    )


def build_help_dialog(page: ft.Page) -> ft.AlertDialog:
    """Build the app-wide help dialog.

    Args:
        page: The Flet page instance, used to dismiss the dialog.

    Returns:
        An AlertDialog listing the keyboard shortcuts of the review screen.
    """
    return ft.AlertDialog(
        modal=True,
        title=ft.Text(
            i18n.t("help.title"),
            size=18,
            weight=ft.FontWeight.W_600,
            color=TEXT_H,
        ),
        bgcolor="#1a1822",
        content=ft.Column(
            [
                _build_group("help.scope_global", GLOBAL_SHORTCUTS),
                _build_group("help.scope_review", REVIEW_SHORTCUTS),
            ],
            spacing=18,
            width=420,
            tight=True,
        ),
        actions=[
            focusable(
                ft.Container(
                    content=ft.Text(
                        i18n.t("common.close"),
                        size=13.5,
                        weight=ft.FontWeight.W_500,
                        color=ACCENT,
                    ),
                    padding=ft.Padding(left=12, right=12, top=8, bottom=8),
                    ink=True,
                    border_radius=8,
                ),
                on_click=lambda _e: page.pop_dialog(),
            )
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
