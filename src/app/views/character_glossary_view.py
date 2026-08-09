"""Character glossary view: detect, add, edit, and delete characters."""

from collections.abc import Callable
from pathlib import Path

import flet as ft
from flet.controls.control_event import Event

from app.components.back_link import build_back_link
from app.dialogs import dialog_action
from app.state import AppState
from app.theme import (
    ACCENT,
    ACCENT_ON,
    BG_INPUT,
    BORDER_COLOR,
    BORDER_STRONG,
    ERROR,
    FOCUS_RING,
    FOCUS_RING_WIDTH,
    SUCCESS,
    TEXT,
    TEXT_DIM,
    TEXT_H,
    TEXT_HINT,
    TEXT_MUTED,
    WARNING,
    border_all,
    focusable,
)
from app.toasts import show_toast
from core.i18n import i18n
from core.project_actions import detect_and_store_characters
from core.storage.repositories import Character, CharacterRepository


class CharacterGlossaryView:
    """Manage the character glossary used to give the LLM speaker context."""

    def __init__(
        self,
        page: ft.Page,
        state: AppState,
        on_back: Callable[[], None],
    ) -> None:
        """Initialize the character glossary view.

        Args:
            page: The Flet page instance.
            state: Shared application state (db and project_path must be set).
            on_back: Callback invoked when the user returns to review.

        Raises:
            RuntimeError: If the database is not connected or no project
                is selected.
        """
        if state.db is None or state.project_path is None:
            raise RuntimeError("Database not connected or project not set.")

        self._page = page
        self._project_path: Path = state.project_path
        self._on_back = on_back
        self._repo = CharacterRepository(state.db.conn, state.db.lock)

        self._title = ft.Text(
            i18n.t("characters.title"),
            size=26,
            weight=ft.FontWeight.W_700,
            color=TEXT_H,
        )
        self._subtitle = ft.Text(i18n.t("characters.subtitle"), size=13, color=TEXT_DIM)

        self._variable_field = ft.TextField(
            hint_text=i18n.t("characters.variable"),
            hint_style=ft.TextStyle(color=TEXT_HINT),
            bgcolor=BG_INPUT,
            border_color=BORDER_COLOR,
            focused_border_color=FOCUS_RING,
            focused_border_width=FOCUS_RING_WIDTH,
            color=TEXT,
            cursor_color=ACCENT,
            border_radius=8,
            height=44,
            width=160,
            content_padding=ft.Padding(left=12, right=12, top=0, bottom=0),
        )
        self._display_name_field = ft.TextField(
            hint_text=i18n.t("characters.display_name"),
            hint_style=ft.TextStyle(color=TEXT_HINT),
            bgcolor=BG_INPUT,
            border_color=BORDER_COLOR,
            focused_border_color=FOCUS_RING,
            focused_border_width=FOCUS_RING_WIDTH,
            color=TEXT,
            cursor_color=ACCENT,
            border_radius=8,
            height=44,
            width=200,
            content_padding=ft.Padding(left=12, right=12, top=0, bottom=0),
        )
        self._add_text = ft.Text(
            i18n.t("characters.add"),
            size=13,
            weight=ft.FontWeight.W_600,
            color=ACCENT_ON,
        )
        self._add_btn = focusable(
            ft.Container(
                content=self._add_text,
                bgcolor=ACCENT,
                border_radius=8,
                padding=ft.Padding(left=16, right=16, top=12, bottom=12),
                ink=True,
            ),
            on_click=self._on_add_clicked,
        )
        self._detect_text = ft.Text(
            i18n.t("characters.detect"),
            size=13,
            weight=ft.FontWeight.W_500,
            color=TEXT,
        )
        self._detect_btn = focusable(
            ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.SEARCH, size=15, color=TEXT),
                        self._detect_text,
                    ],
                    spacing=7,
                    tight=True,
                ),
                bgcolor=BG_INPUT,
                border=border_all(1, BORDER_STRONG),
                border_radius=8,
                padding=ft.Padding(left=14, right=14, top=11, bottom=11),
                ink=True,
            ),
            on_click=self._on_detect_clicked,
        )
        self._clear_all_btn = focusable(
            ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.DELETE_SWEEP_OUTLINED, size=15, color=ERROR),
                        ft.Text(
                            i18n.t("characters.clear_all"),
                            size=13,
                            weight=ft.FontWeight.W_500,
                            color=ERROR,
                        ),
                    ],
                    spacing=7,
                    tight=True,
                ),
                border=border_all(1, BORDER_STRONG),
                border_radius=8,
                padding=ft.Padding(left=14, right=14, top=11, bottom=11),
                ink=True,
            ),
            on_click=self._on_clear_all_clicked,
            visible=False,
        )
        self._list_col = ft.Column(spacing=8, scroll=ft.ScrollMode.AUTO, expand=True)

        self._refresh_list()

    def build(self) -> ft.Control:
        """Build and return the view control tree.

        Returns:
            A Flet Control representing the character glossary view.
        """
        return ft.Column(
            controls=[
                ft.Container(
                    expand=True,
                    content=ft.Column(
                        controls=[
                            build_back_link(i18n.t("characters.back"), self._on_back),
                            ft.Column([self._title, self._subtitle], spacing=6),
                            self._build_purpose_card(),
                            ft.Row(
                                [
                                    self._variable_field,
                                    self._display_name_field,
                                    self._add_btn,
                                    self._detect_btn,
                                    ft.Container(expand=True),
                                    self._clear_all_btn,
                                ],
                                spacing=10,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                            self._list_col,
                        ],
                        spacing=20,
                        expand=True,
                    ),
                    padding=ft.Padding(left=60, right=60, top=30, bottom=30),
                ),
            ],
            expand=True,
            spacing=0,
        )

    @staticmethod
    def _build_purpose_card() -> ft.Control:
        """Build the panel saying what the glossary actually changes.

        Same panel as the universe summary carries, for the same reason:
        the screen shows a list of variables and a notes field without
        ever saying what any of it buys, and a glossary nobody fills is a
        glossary that changes nothing about the translation.

        Returns:
            A bordered panel listing what the characters are used for.
        """
        rows = [
            ("characters.purpose_speaker", ft.Icons.RECORD_VOICE_OVER_OUTLINED),
            ("characters.purpose_names", ft.Icons.BADGE_OUTLINED),
            ("characters.purpose_notes", ft.Icons.EDIT_NOTE_OUTLINED),
        ]
        return ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        i18n.t("characters.purpose_title"),
                        size=13,
                        weight=ft.FontWeight.W_600,
                        color=TEXT_H,
                    ),
                    *(
                        ft.Row(
                            [
                                ft.Icon(icon, size=15, color=ACCENT),
                                ft.Text(
                                    i18n.t(key),
                                    size=12.5,
                                    color=TEXT_MUTED,
                                    expand=True,
                                ),
                            ],
                            spacing=10,
                            vertical_alignment=ft.CrossAxisAlignment.START,
                        )
                        for key, icon in rows
                    ),
                ],
                spacing=9,
                tight=True,
            ),
            bgcolor=BG_INPUT,
            border=border_all(1, BORDER_COLOR),
            border_radius=12,
            padding=ft.Padding(left=18, right=18, top=15, bottom=15),
        )

    def _refresh_list(self) -> None:
        """Reload the character list from the database."""
        characters = self._repo.get_all()
        self._clear_all_btn.visible = bool(characters)
        if not characters:
            self._list_col.controls = [
                ft.Text(i18n.t("characters.no_characters"), size=13, color=TEXT_HINT)
            ]
        else:
            self._list_col.controls = [self._build_row(c) for c in characters]

    def _build_row(self, character: Character) -> ft.Control:
        """Build one editable row for a single character.

        Args:
            character: The character to render.

        Returns:
            A styled Container with the character's fields and delete button.
        """
        notes_field = ft.TextField(
            value=character.notes or "",
            hint_text=i18n.t("characters.notes"),
            hint_style=ft.TextStyle(color=TEXT_HINT),
            bgcolor=BG_INPUT,
            border_color=BORDER_COLOR,
            focused_border_color=FOCUS_RING,
            focused_border_width=FOCUS_RING_WIDTH,
            color=TEXT,
            cursor_color=ACCENT,
            border_radius=8,
            expand=True,
            content_padding=ft.Padding(left=10, right=10, top=8, bottom=8),
        )

        def _on_notes_blur(_e: Event[ft.TextField]) -> None:
            """Write the notes when they changed, and say so.

            Leaving a field wrote to the database and reported nothing,
            so the one thing worth typing on this screen was also the
            one nobody could tell had been kept.

            Only a real change is written and announced. Tabbing across
            the glossary crosses every field, and a screen that
            congratulates itself on each of them teaches its user to
            stop reading it.
            """
            value = notes_field.value or ""
            if value == (character.notes or ""):
                return
            self._repo.update_notes(character.variable, value)
            character.notes = value
            show_toast(self._page, i18n.t("characters.notes_saved"), SUCCESS)

        notes_field.on_blur = _on_notes_blur

        def _on_delete(_e: Event[ft.TextButton]) -> None:
            self._page.show_dialog(self._build_delete_dialog(character.variable))

        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text(
                                character.variable,
                                size=13.5,
                                weight=ft.FontWeight.W_600,
                                color=TEXT,
                            ),
                            ft.Text(character.display_name, size=13, color=TEXT_MUTED),
                            ft.Container(expand=True),
                            focusable(
                                ft.Container(
                                    content=ft.Icon(
                                        ft.Icons.DELETE_OUTLINE,
                                        size=16,
                                        color=ERROR,
                                    ),
                                    ink=True,
                                    border_radius=8,
                                    padding=6,
                                ),
                                on_click=_on_delete,
                                tooltip=i18n.t("characters.delete"),
                            ),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    notes_field,
                ],
                spacing=8,
            ),
            padding=ft.Padding(left=14, right=14, top=10, bottom=10),
            border=border_all(1, BORDER_COLOR),
            border_radius=10,
        )

    def _build_delete_dialog(self, variable: str) -> ft.AlertDialog:
        """Build the confirmation dialog shown before deleting a character.

        Args:
            variable: The Ren'Py variable of the character to delete.

        Returns:
            An AlertDialog asking the user to confirm the deletion.
        """

        def _confirm(_e: Event[ft.TextButton]) -> None:
            self._repo.delete(variable)
            self._page.pop_dialog()
            self._refresh_list()
            self._page.update()
            show_toast(
                self._page,
                i18n.t("characters.deleted_one").format(name=variable),
                SUCCESS,
            )

        return ft.AlertDialog(
            modal=True,
            title=ft.Text(
                i18n.t("characters.confirm_delete"),
                size=16,
                weight=ft.FontWeight.W_600,
                color=TEXT_H,
            ),
            bgcolor="#1a1822",
            actions=[
                dialog_action(
                    i18n.t("common.cancel"),
                    lambda _e: self._page.pop_dialog(),
                ),
                dialog_action(
                    i18n.t("characters.delete"),
                    _confirm,
                    tone="danger",
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

    def _on_clear_all_clicked(self, _e: Event[ft.TextButton]) -> None:
        """Ask for confirmation before emptying the whole glossary.

        Args:
            _e: Unused click event.
        """
        self._page.show_dialog(self._build_clear_all_dialog(len(self._repo.get_all())))

    def _build_clear_all_dialog(self, count: int) -> ft.AlertDialog:
        """Build the confirmation shown before deleting every character.

        The count and what survives are both spelled out: auto-detection
        brings the characters back, never the notes, and those notes are
        what feeds the DeepL glossary and the LLM prompts.

        Args:
            count: How many characters the glossary currently holds.

        Returns:
            An AlertDialog asking the user to confirm the deletion.
        """

        def _confirm(_e: Event[ft.TextButton]) -> None:
            deleted = self._repo.delete_all()
            self._page.pop_dialog()
            self._refresh_list()
            self._page.update()
            show_toast(
                self._page,
                i18n.t("characters.cleared_count").format(n=deleted),
                SUCCESS,
            )

        return ft.AlertDialog(
            modal=True,
            bgcolor="#1a1822",
            title=ft.Text(
                i18n.t("characters.confirm_clear_all"),
                size=16,
                weight=ft.FontWeight.W_600,
                color=TEXT_H,
            ),
            content=ft.Text(
                i18n.t("characters.confirm_clear_all_message").format(n=count),
                size=13.5,
                color=TEXT_MUTED,
                width=360,
            ),
            actions=[
                dialog_action(
                    i18n.t("common.cancel"),
                    lambda _e: self._page.pop_dialog(),
                ),
                dialog_action(
                    i18n.t("characters.clear_all"),
                    _confirm,
                    tone="danger",
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

    def _on_detect_clicked(self, _e: Event[ft.TextButton]) -> None:
        """Scan the project for Character() definitions and save them.

        Args:
            _e: Unused click event.
        """
        count = detect_and_store_characters(self._repo, self._project_path)
        self._refresh_list()
        self._page.update()
        show_toast(
            self._page,
            i18n.t("characters.detected_count").format(n=count),
            SUCCESS if count else WARNING,
        )

    def _on_add_clicked(self, _e: Event[ft.TextButton]) -> None:
        """Add a character from the manual entry fields.

        Args:
            _e: Unused click event.
        """
        variable = (self._variable_field.value or "").strip()
        display_name = (self._display_name_field.value or "").strip()
        if not variable or not display_name:
            return
        self._repo.upsert(variable, display_name)
        self._variable_field.value = ""
        self._display_name_field.value = ""
        self._refresh_list()
        self._page.update()
