"""Shared settings dialog: locale switch, SDK path, and provider config link."""

from collections.abc import Callable

import flet as ft
from flet.controls.control_event import Event

from app.theme import (
    ACCENT,
    BG_INPUT,
    BORDER_STRONG,
    ERROR,
    FOCUS_RING,
    FOCUS_RING_WIDTH,
    TEXT_H,
    TEXT_HINT,
    TEXT_MUTED,
    TEXT_PATH,
    border_all,
    focusable,
)
from core.i18n import SUPPORTED_LOCALES, i18n
from core.languages import localized_label
from core.settings import settings
from core.storage.translation_memory import translation_memory

_LOCALE_OPTIONS = [
    ft.dropdown.Option(key="en", text="English"),
    ft.dropdown.Option(key="fr", text="Français"),
]


def build_settings_dialog(
    page: ft.Page,
    on_configure_provider: Callable[[], None],
    on_close: Callable[[], None],
) -> ft.AlertDialog:
    """Build the app-wide settings dialog.

    Args:
        page: The Flet page instance, used to dismiss the dialog.
        on_configure_provider: Navigate to the provider settings view.
        on_close: Called after the dialog is dismissed, so the caller can
            refresh the current page with any changed locale or SDK path.

    Returns:
        An AlertDialog with language, SDK path, and provider config controls.
    """
    saved_sdk = settings.get("sdk_path")
    sdk_path_label = ft.Text(saved_sdk or "", size=13, color=TEXT_PATH)

    def on_locale_changed(e: Event[ft.Dropdown]) -> None:
        locale = e.control.value or "en"
        if locale not in SUPPORTED_LOCALES:
            return
        i18n.set_locale(locale)
        settings.set("locale", locale)
        page.pop_dialog()
        page.show_dialog(
            build_settings_dialog(
                page,
                on_configure_provider=on_configure_provider,
                on_close=on_close,
            )
        )

    def on_sdk_cleared(_: Event[ft.TextButton]) -> None:
        sdk_path_label.value = ""
        sdk_clear_btn.visible = False
        settings.set("sdk_path", None)
        page.update()

    sdk_clear_btn = focusable(
        ft.Container(
            content=ft.Icon(ft.Icons.CLOSE, size=14, color=TEXT_HINT),
            width=24,
            height=24,
            alignment=ft.Alignment(0, 0),
            border_radius=12,
            ink=True,
        ),
        on_click=on_sdk_cleared,
        tooltip=i18n.t("settings.clear"),
        visible=bool(saved_sdk),
        width=24,
        height=24,
    )

    async def on_sdk_clicked(_: Event[ft.TextButton]) -> None:
        results = await ft.FilePicker().pick_files(allow_multiple=False)
        if results and results[0].path:
            sdk_path_label.value = results[0].path
            sdk_clear_btn.visible = True
            settings.set("sdk_path", results[0].path)
            page.update()

    memory_rows = ft.Column(spacing=7, tight=True)
    disarm_armed_row: Callable[[], None] | None = None

    def memory_controls() -> list[ft.Control]:
        """List the stored language pairs, or say the memory is empty.

        Returns:
            One row per language pair, most entries first.
        """
        stats = translation_memory.stats()
        if not stats:
            return [ft.Text(i18n.t("settings.memory_empty"), size=12, color=TEXT_HINT)]
        return [
            build_memory_row(source, target, count) for source, target, count in stats
        ]

    def refresh_memory() -> None:
        """Rebuild the list of stored language pairs and push it to the client."""
        nonlocal disarm_armed_row
        disarm_armed_row = None
        memory_rows.controls = memory_controls()
        page.update()

    def build_memory_row(source: str, target: str, count: int) -> ft.Row:
        """Build one language pair, with a two-step delete.

        Forgetting a pair throws away months of validated work and cannot
        be undone, so the trash icon only arms the row; a second, explicit
        click on "confirm" is what deletes. Nesting a confirmation dialog
        inside this one would leave two modals stacked over each other.

        Arming turns the trash icon into a cancel, so the spot the user
        just clicked backs out instead of deleting, and the confirmation
        is somewhere the cursor is not already resting. Only one row can
        be armed at a time: an armed row left behind in a corner of the
        dialog is a delete waiting for a stray click.

        Args:
            source: Language the stored source texts are written in.
            target: Language the stored translations are written in.
            count: How many entries the pair holds.

        Returns:
            The row, ready to be dropped into the memory section.
        """

        def disarm() -> None:
            forget_btn.visible = True
            confirm_btn.visible = False
            cancel_btn.visible = False

        def on_arm(_: Event[ft.TextButton]) -> None:
            nonlocal disarm_armed_row
            if disarm_armed_row is not None:
                disarm_armed_row()
            disarm_armed_row = disarm
            forget_btn.visible = False
            confirm_btn.visible = True
            cancel_btn.visible = True
            page.update()

        def on_cancel(_: Event[ft.TextButton]) -> None:
            nonlocal disarm_armed_row
            disarm_armed_row = None
            disarm()
            page.update()

        def on_confirm(_: Event[ft.TextButton]) -> None:
            translation_memory.forget(source, target)
            refresh_memory()

        forget_btn = focusable(
            ft.Container(
                content=ft.Icon(ft.Icons.DELETE_OUTLINE, size=15, color=TEXT_HINT),
                width=26,
                height=26,
                alignment=ft.Alignment(0, 0),
                border_radius=6,
                ink=True,
            ),
            on_click=on_arm,
            tooltip=i18n.t("settings.memory_forget"),
            radius=6,
            width=26,
            height=26,
        )
        cancel_btn = focusable(
            ft.Container(
                content=ft.Icon(ft.Icons.CLOSE, size=15, color=TEXT_HINT),
                width=26,
                height=26,
                alignment=ft.Alignment(0, 0),
                border_radius=6,
                ink=True,
            ),
            on_click=on_cancel,
            tooltip=i18n.t("settings.memory_cancel"),
            radius=6,
            width=26,
            height=26,
            visible=False,
        )
        confirm_btn = focusable(
            ft.Container(
                content=ft.Text(
                    i18n.t("settings.memory_confirm"),
                    size=12,
                    weight=ft.FontWeight.W_600,
                    color=ERROR,
                ),
                padding=ft.Padding(left=8, right=8, top=4, bottom=4),
                border_radius=6,
                ink=True,
            ),
            on_click=on_confirm,
            radius=6,
            visible=False,
        )

        return ft.Row(
            [
                ft.Text(
                    i18n.t("settings.memory_pair").format(
                        source=localized_label(source), target=localized_label(target)
                    ),
                    size=13,
                    color=TEXT_H,
                    expand=True,
                ),
                ft.Text(
                    i18n.t("settings.memory_entries").format(n=count),
                    size=12,
                    color=TEXT_MUTED,
                ),
                confirm_btn,
                forget_btn,
                cancel_btn,
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    memory_rows.controls = memory_controls()

    def on_close_clicked(_: Event[ft.TextButton]) -> None:
        page.pop_dialog()
        on_close()

    def on_provider_link_clicked(_: Event[ft.TextButton]) -> None:
        page.pop_dialog()
        on_configure_provider()

    return ft.AlertDialog(
        modal=True,
        title=ft.Text(
            i18n.t("settings.title"),
            size=18,
            weight=ft.FontWeight.W_600,
            color=TEXT_H,
        ),
        bgcolor="#1a1822",
        content=ft.Column(
            [
                ft.Column(
                    [
                        ft.Text(
                            i18n.t("settings.language_label"),
                            size=12,
                            weight=ft.FontWeight.W_600,
                            color=TEXT_MUTED,
                        ),
                        ft.Dropdown(
                            options=_LOCALE_OPTIONS,
                            value=i18n.locale,
                            bgcolor=BG_INPUT,
                            border_color=BORDER_STRONG,
                            focused_border_color=FOCUS_RING,
                            focused_border_width=FOCUS_RING_WIDTH,
                            color=TEXT_H,
                            border_radius=11,
                            height=48,
                            dense=True,
                            width=220,
                            on_select=on_locale_changed,
                        ),
                    ],
                    spacing=9,
                ),
                ft.Column(
                    [
                        ft.Text(
                            i18n.t("settings.sdk_label"),
                            size=12,
                            weight=ft.FontWeight.W_600,
                            color=TEXT_MUTED,
                        ),
                        ft.Text(
                            i18n.t("settings.sdk_hint"),
                            size=11.5,
                            color=TEXT_HINT,
                        ),
                        ft.Row(
                            [
                                focusable(
                                    ft.Container(
                                        content=ft.Row(
                                            [
                                                ft.Icon(
                                                    ft.Icons.FOLDER_OPEN,
                                                    size=15,
                                                    color=TEXT_H,
                                                ),
                                                ft.Text(
                                                    i18n.t("settings.sdk_browse"),
                                                    size=13,
                                                    weight=ft.FontWeight.W_500,
                                                    color=TEXT_H,
                                                ),
                                            ],
                                            spacing=7,
                                            tight=True,
                                        ),
                                        bgcolor=BG_INPUT,
                                        border=border_all(1, BORDER_STRONG),
                                        border_radius=8,
                                        padding=ft.Padding(
                                            left=14, right=14, top=9, bottom=9
                                        ),
                                        ink=True,
                                    ),
                                    on_click=on_sdk_clicked,
                                ),
                                sdk_path_label,
                                sdk_clear_btn,
                            ],
                            spacing=8,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                    ],
                    spacing=8,
                ),
                ft.Column(
                    [
                        ft.Text(
                            i18n.t("settings.memory_label"),
                            size=12,
                            weight=ft.FontWeight.W_600,
                            color=TEXT_MUTED,
                        ),
                        ft.Text(
                            i18n.t("settings.memory_hint"),
                            size=11.5,
                            color=TEXT_HINT,
                        ),
                        memory_rows,
                    ],
                    spacing=8,
                ),
                ft.Column(
                    [
                        ft.Text(
                            i18n.t("provider_config.title"),
                            size=12,
                            weight=ft.FontWeight.W_600,
                            color=TEXT_MUTED,
                        ),
                        focusable(
                            ft.Container(
                                content=ft.Row(
                                    [
                                        ft.Icon(
                                            ft.Icons.TRANSLATE, size=15, color=TEXT_H
                                        ),
                                        ft.Text(
                                            i18n.t("provider_config.open_settings"),
                                            size=13,
                                            weight=ft.FontWeight.W_500,
                                            color=TEXT_H,
                                        ),
                                    ],
                                    spacing=7,
                                    tight=True,
                                ),
                                bgcolor=BG_INPUT,
                                border=border_all(1, BORDER_STRONG),
                                border_radius=8,
                                padding=ft.Padding(left=14, right=14, top=9, bottom=9),
                                ink=True,
                            ),
                            on_click=on_provider_link_clicked,
                        ),
                    ],
                    spacing=9,
                ),
            ],
            spacing=24,
            width=380,
            tight=True,
        ),
        actions=[
            focusable(
                ft.Container(
                    content=ft.Text(
                        i18n.t("settings.close"),
                        size=13.5,
                        weight=ft.FontWeight.W_500,
                        color=ACCENT,
                    ),
                    padding=ft.Padding(left=12, right=12, top=8, bottom=8),
                    ink=True,
                    border_radius=8,
                ),
                on_click=on_close_clicked,
            ),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
