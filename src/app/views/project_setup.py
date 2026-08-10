"""Project setup view: folder selection, language and text extraction."""

import asyncio
import logging
import shutil
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

import flet as ft
from flet.controls.control_event import Event

from app.components.back_link import build_back_link
from app.components.stepper import build_stepper
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
    TEXT,
    TEXT_DIM,
    TEXT_H,
    TEXT_HINT,
    TEXT_MUTED,
    TEXT_PATH,
    WARNING,
    border_all,
    focusable,
)
from app.ui_thread import safe_update
from core.exporter import GameNameResolver
from core.i18n import i18n
from core.languages import LANGUAGES, localized_label
from core.renpy.cli import RenpyCli, RenpyCliError, parse_failed_files
from core.renpy.engine import can_use_game_engine, resolve_engine
from core.renpy.parser import (
    ParseError,
    TranslateBlockParser,
    TranslationBlock,
    is_translated,
)
from core.renpy.unpacker import (
    archives_contain_compiled_scripts,
    disable_extracted_archives,
    discard_unpacked_files,
    restore_disabled_archives,
    unpack_archived_sources,
)
from core.settings import settings
from core.storage.database import Database
from core.storage.recent_projects import recent_projects
from core.storage.repositories import (
    ProjectMetaRepository,
    TranslationUnitRepository,
)
from core.translation.job import needs_translation
from core.validators import (
    is_recognized_language,
    validate_language_code,
    validate_project_dir,
)

logger = logging.getLogger(__name__)

_CONTENT_MAX_WIDTH = 640
_CARD_HEIGHT = 66
_MODE_DIALOG_WIDTH = 420
_MAX_DISCARD_ROUNDS = 200

_ExtractMode = Literal["keep", "update", "reset"]


class ArchiveError(OSError):
    """Raised when an existing tl/ folder cannot be backed up."""


class CompiledScriptsOnlyError(Exception):
    """Raised when a game's archives hold only compiled .rpyc scripts."""


@dataclass
class _ResumeInfo:
    """Metadata describing a resumable project database.

    Attributes:
        target_language: Persisted target language of the previous session.
        source_language: Persisted source language of the previous session.
        total: Total number of translation units stored in the database.
        validated: Number of human_validated units.
        ai_suggested: Number of ai_suggested units.
        imported: Number of units adopted from the tl/ files.
    """

    target_language: str
    source_language: str
    total: int
    validated: int
    ai_suggested: int
    imported: int


def _language_options() -> list[ft.dropdown.Option]:
    """Build dropdown options from the central language list.

    Returns:
        One option per supported language, named in the language of the
        interface, the tl/ folder name stored behind it.
    """
    return [
        ft.dropdown.Option(key=lang.code, text=localized_label(lang.code))
        for lang in LANGUAGES
    ]


class ProjectSetupView:
    """View for configuring a Ren'Py project and running extraction."""

    def __init__(
        self,
        page: ft.Page,
        state: AppState,
        on_done: Callable[[], None],
    ) -> None:
        """Initialize the project setup view.

        Args:
            page: The Flet page instance.
            state: Shared application state to read and update.
            on_done: Callback invoked after successful extraction.
        """
        self._page = page
        self._state = state
        self._on_done = on_done
        saved_sdk = settings.get("sdk_path")
        self._sdk_path: Path | None = Path(saved_sdk) if saved_sdk else None
        self._extracting = False
        self._mode_dialog_open = False
        self._disk_blocks: list[TranslationBlock] = []
        self._discarded_sources: list[str] = []

        # --- header texts ---
        self._t_header_title = ft.Text(
            i18n.t("project_setup.title"),
            size=24,
            weight=ft.FontWeight.W_600,
            color=TEXT_H,
        )
        self._t_header_subtitle = ft.Text(
            i18n.t("project_setup.subtitle"),
            size=13,
            color=TEXT_DIM,
        )

        # --- folder section ---
        self._t_folder_section = ft.Text(
            i18n.t("project_setup.game_folder"),
            size=12,
            weight=ft.FontWeight.W_600,
            color=TEXT_MUTED,
        )
        self._t_browse = ft.Text(
            i18n.t("common.browse"),
            size=13.5,
            weight=ft.FontWeight.W_500,
            color=TEXT,
        )
        self._folder_label = ft.Text(
            i18n.t("project_setup.no_folder"),
            color=TEXT_HINT,
            italic=True,
            size=13,
        )
        # --- language section ---
        self._t_source_lang = ft.Text(
            i18n.t("project_setup.source_lang"),
            size=12,
            weight=ft.FontWeight.W_600,
            color=TEXT_MUTED,
        )
        self._t_target_lang = ft.Text(
            i18n.t("project_setup.target_lang"),
            size=12,
            weight=ft.FontWeight.W_600,
            color=TEXT_MUTED,
        )

        self._target_dropdown = ft.Dropdown(
            options=_language_options(),
            value=state.target_language or None,
            hint_text=i18n.t("project_setup.target_placeholder"),
            bgcolor=BG_INPUT,
            border_color=BORDER_COLOR,
            focused_border_color=FOCUS_RING,
            focused_border_width=FOCUS_RING_WIDTH,
            color=TEXT,
            border_radius=11,
            height=48,
            dense=True,
            on_select=self._on_target_changed,
            expand=True,
        )
        self._target_help = ft.Text(
            i18n.t("project_setup.target_hint"),
            color=TEXT_HINT,
            size=11.5,
        )

        # --- folder browse button (stored for disabling during extraction) ---
        self._browse_btn = focusable(
            ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.FOLDER_OPEN, size=17, color=TEXT),
                        self._t_browse,
                    ],
                    spacing=9,
                    tight=True,
                ),
                bgcolor=BG_INPUT,
                border=border_all(1, BORDER_STRONG),
                border_radius=10,
                padding=ft.Padding(left=18, right=18, top=11, bottom=11),
                ink=True,
            ),
            on_click=self._on_folder_clicked,
            radius=10,
        )

        # --- source language dropdown (stored for disabling during extraction) ---
        self._source_dropdown = ft.Dropdown(
            options=_language_options(),
            value=self._state.source_language,
            bgcolor=BG_INPUT,
            border_color=BORDER_COLOR,
            focused_border_color=FOCUS_RING,
            focused_border_width=FOCUS_RING_WIDTH,
            color=TEXT,
            border_radius=11,
            height=48,
            dense=True,
            on_select=self._on_source_changed,
            expand=True,
        )

        # --- SDK section ---
        self._t_sdk_notice = ft.Text(
            i18n.t("project_setup.code_execution_notice"),
            size=12,
            color=TEXT_DIM,
            expand=True,
        )
        self._sdk_notice_row = ft.Row(
            [
                ft.Icon(ft.Icons.INFO_OUTLINE, size=16, color=TEXT_DIM),
                self._t_sdk_notice,
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )

        self._t_sdk_title = ft.Text(
            i18n.t("project_setup.sdk_title"),
            size=14,
            weight=ft.FontWeight.W_600,
            color=TEXT,
        )
        self._t_sdk_desc = ft.Text(
            i18n.t("project_setup.sdk_desc"),
            size=12,
            color=TEXT_DIM,
        )

        self._t_sdk_file_hint = ft.Text(
            i18n.t("project_setup.sdk_file_hint"),
            size=12,
            color=TEXT_DIM,
        )
        self._t_sdk_select = ft.Text(
            i18n.t("project_setup.sdk_select"),
            size=13,
            weight=ft.FontWeight.W_500,
            color=TEXT,
        )
        self._sdk_path_label = ft.Text(
            saved_sdk or "",
            color=TEXT_HINT if not saved_sdk else TEXT_PATH,
            italic=not bool(saved_sdk),
            size=13,
        )
        self._sdk_section = ft.Container(
            content=ft.Column(
                [
                    self._t_sdk_file_hint,
                    ft.Row(
                        [
                            focusable(
                                ft.Container(
                                    content=ft.Row(
                                        [
                                            ft.Icon(
                                                ft.Icons.FOLDER_OPEN,
                                                size=15,
                                                color=TEXT,
                                            ),
                                            self._t_sdk_select,
                                        ],
                                        spacing=7,
                                        tight=True,
                                    ),
                                    bgcolor=BG_INPUT,
                                    border=border_all(1, BORDER_STRONG),
                                    border_radius=8,
                                    padding=ft.Padding(
                                        left=14,
                                        right=14,
                                        top=9,
                                        bottom=9,
                                    ),
                                    ink=True,
                                ),
                                on_click=self._on_sdk_clicked,
                            ),
                            self._sdk_path_label,
                        ],
                        spacing=12,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                spacing=8,
            ),
        )

        # --- extract button ---
        self._extract_btn_icon = ft.Icon(ft.Icons.DOWNLOAD, size=17, color=TEXT_HINT)
        self._extract_btn_text = ft.Text(
            i18n.t("project_setup.extract"),
            size=14.5,
            weight=ft.FontWeight.W_600,
            color=TEXT_HINT,
        )
        self._extract_btn_box = ft.Container(
            content=ft.Row(
                [self._extract_btn_icon, self._extract_btn_text],
                tight=True,
                spacing=10,
            ),
            bgcolor="#26242f",
            border_radius=12,
            padding=ft.Padding(left=26, right=26, top=14, bottom=14),
            ink=True,
        )
        self._extract_btn = focusable(
            self._extract_btn_box,
            on_click=self._on_extract_clicked,
            radius=12,
        )
        self._extract_hint = ft.Text("", size=12.5, color=TEXT_DIM)
        self._t_extracting = ft.Text(
            i18n.t("project_setup.extracting"),
            size=14,
            color=TEXT_MUTED,
        )
        self._extracting_row = ft.Row(
            [
                ft.ProgressRing(width=16, height=16, color=ACCENT, stroke_width=2),
                self._t_extracting,
            ],
            spacing=10,
            visible=False,
        )
        self._status = ft.Text("", color=ERROR, size=13)

        # --- projects list (landing) ---
        self._recent_col = ft.Column(spacing=8)
        self._recent_empty = ft.Text(
            i18n.t("project_setup.list_empty"),
            size=13,
            color=TEXT_HINT,
            italic=True,
        )
        self._error_snack = ft.SnackBar(
            content=ft.Text("", size=13),
            behavior=ft.SnackBarBehavior.FLOATING,
            show_close_icon=True,
            close_icon_color=TEXT_HINT,
            duration=ft.Duration(seconds=6),
            margin=ft.Margin(left=20, right=20, bottom=20),
        )
        self._error_snack_shown = False
        self._content_holder = ft.Container(
            width=_CONTENT_MAX_WIDTH,
            padding=ft.Padding(left=40, right=40, top=30, bottom=36),
        )
        self._refresh_recent(do_update=False)

        if state.project_path is not None:
            self._folder_label.value = str(state.project_path)
            self._folder_label.italic = False
            self._folder_label.color = TEXT_PATH
        self._mode = "list" if self._recent_col.controls else "form"
        self._update_extract_btn()

    def build(self) -> ft.Control:
        """Build and return the view control tree.

        Returns:
            A Flet Control representing the complete setup view.
        """
        self._content_holder.content = (
            self._build_list_content()
            if self._mode == "list"
            else self._build_form_content()
        )
        return ft.Column(
            controls=[
                build_stepper(1),
                ft.Container(
                    expand=True,
                    alignment=ft.Alignment(0, 0),
                    content=self._content_holder,
                ),
            ],
            expand=True,
            spacing=0,
        )

    def _build_list_content(self) -> ft.Control:
        """Build the landing content: the project list and a new-project button.

        Returns:
            A scrollable Column listing resumable projects.
        """
        return ft.Column(
            controls=[
                ft.Column(
                    [
                        ft.Text(
                            i18n.t("project_setup.list_title"),
                            size=24,
                            weight=ft.FontWeight.W_600,
                            color=TEXT_H,
                        ),
                        ft.Text(
                            i18n.t("project_setup.list_subtitle"),
                            size=13,
                            color=TEXT_DIM,
                        ),
                    ],
                    spacing=4,
                ),
                self._recent_empty,
                self._recent_col,
                focusable(
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Icon(ft.Icons.ADD, size=17, color=ACCENT_ON),
                                ft.Text(
                                    i18n.t("project_setup.new_project"),
                                    size=14.5,
                                    weight=ft.FontWeight.W_600,
                                    color=ACCENT_ON,
                                ),
                            ],
                            tight=True,
                            spacing=10,
                        ),
                        bgcolor=ACCENT,
                        border_radius=12,
                        padding=ft.Padding(left=22, right=22, top=13, bottom=13),
                        ink=True,
                    ),
                    on_click=self._show_form,
                    radius=12,
                ),
            ],
            scroll=ft.ScrollMode.AUTO,
            spacing=20,
        )

    def _build_form_content(self) -> ft.Control:
        """Build the new-project configuration form.

        Returns:
            A scrollable Column with the folder, language, method and extract
            controls, preceded by a back link only when recent projects exist.
        """
        controls: list[ft.Control] = []
        if self._recent_col.controls:
            controls.append(
                build_back_link(
                    i18n.t("project_setup.back_to_list"),
                    lambda: self._show_list(),
                )
            )
        controls.extend(
            [
                self._build_header(),
                self._build_folder_section(),
                ft.Row(
                    [self._build_source_lang(), self._build_target_lang()],
                    spacing=18,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                ),
                self._build_sdk_section(),
                self._sdk_section,
                ft.Column(
                    [
                        ft.Row(
                            [self._extract_btn, self._extracting_row],
                            spacing=12,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        self._extract_hint,
                        self._status,
                    ],
                    spacing=8,
                ),
            ]
        )
        return ft.Column(controls, scroll=ft.ScrollMode.AUTO, spacing=24)

    def _show_form(self, _: Event[ft.Container] | None = None) -> None:
        """Switch to a blank configuration form for a new project.

        Args:
            _: Unused click event.
        """
        self._reset_form()
        self._mode = "form"
        self._content_holder.content = self._build_form_content()
        self._page.update()

    def _reset_form(self) -> None:
        """Clear per-project state and form fields for a fresh project."""
        if self._state.db is not None:
            self._state.db.close()
            self._state.db = None
        self._state.project_path = None
        self._state.tl_output_dir = None
        self._state.blocks = []
        self._state.game_name = ""
        self._folder_label.value = i18n.t("project_setup.no_folder")
        self._folder_label.italic = True
        self._folder_label.color = TEXT_HINT
        self._state.target_language = ""
        self._target_dropdown.value = None
        self._status.value = ""
        self._update_extract_btn()

    def _show_list(self, _: Event[ft.Container] | None = None) -> None:
        """Switch to the project list, refreshing it first.

        Args:
            _: Unused click event.
        """
        self._mode = "list"
        self._refresh_recent(do_update=False)
        self._content_holder.content = self._build_list_content()
        self._page.update()

    def _build_header(self) -> ft.Column:
        """Build the section title and subtitle.

        Returns:
            A Column with title Text and subtitle Text.
        """
        return ft.Column(
            [self._t_header_title, self._t_header_subtitle],
            spacing=4,
        )

    def _build_folder_section(self) -> ft.Column:
        """Build the game folder picker row.

        Returns:
            A Column with a label, browse button, and path display.
        """
        return ft.Column(
            [
                self._t_folder_section,
                ft.Row(
                    [self._browse_btn, self._folder_label],
                    spacing=14,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            ],
            spacing=9,
        )

    def _build_source_lang(self) -> ft.Container:
        """Build the source language dropdown field.

        Returns:
            An expanding Container wrapping a labeled Dropdown.
        """
        return ft.Container(
            expand=True,
            content=ft.Column(
                [self._t_source_lang, self._source_dropdown],
                spacing=9,
            ),
        )

    def _build_target_lang(self) -> ft.Container:
        """Build the target language dropdown field.

        Returns:
            An expanding Container with a labeled Dropdown and its hint.
        """
        return ft.Container(
            expand=True,
            content=ft.Column(
                [
                    self._t_target_lang,
                    self._target_dropdown,
                    self._target_help,
                ],
                spacing=7,
            ),
        )

    def _build_sdk_section(self) -> ft.Column:
        """Build the SDK extraction header and code-execution warning.

        Returns:
            A Column with the SDK title, description and notice row.
        """
        return ft.Column(
            [
                self._t_sdk_title,
                self._t_sdk_desc,
                self._sdk_notice_row,
            ],
            spacing=11,
        )

    async def _on_folder_clicked(self, _: Event[ft.Container]) -> None:
        """Open a directory picker dialog and update state with the result.

        Args:
            _: Unused click event.
        """
        if self._extracting:
            return
        path = await ft.FilePicker().get_directory_path()
        if path:
            self._state.project_path = Path(path)
            self._folder_label.value = path
            self._folder_label.italic = False
            self._folder_label.color = TEXT_PATH
            self._update_extract_btn()
            self._page.update()

    async def _on_sdk_clicked(self, _: Event[ft.Container]) -> None:
        """Open a file picker to select the Ren'Py SDK executable.

        Args:
            _: Unused click event.
        """
        if self._extracting:
            return
        results = await ft.FilePicker().pick_files(allow_multiple=False)
        if results and results[0].path:
            self._sdk_path = Path(results[0].path)
            self._sdk_path_label.value = results[0].path
            self._sdk_path_label.italic = False
            self._sdk_path_label.color = TEXT_PATH
            settings.set("sdk_path", results[0].path)
            self._update_extract_btn()
            self._page.update()

    def _on_source_changed(self, e: Event[ft.Dropdown]) -> None:
        """Update source language in state.

        Args:
            e: The dropdown select event.
        """
        self._state.source_language = e.control.value or "english"

    def _on_target_changed(self, e: Event[ft.Dropdown]) -> None:
        """Update target language in state.

        Args:
            e: The dropdown select event.
        """
        self._state.target_language = e.control.value or ""
        self._update_extract_btn()
        self._page.update()

    def _missing_requirements(self) -> list[str]:
        """List what extraction is still waiting for.

        The SDK is only missing for a game that ships no engine this
        system can run: asking for it before a folder is picked would
        claim a requirement most games do not have.

        Returns:
            Localized names of the missing inputs, empty when extraction
            can proceed.
        """
        missing: list[str] = []
        project = self._state.project_path
        if project is None:
            missing.append(i18n.t("project_setup.need_folder"))
        if not validate_language_code(self._state.target_language):
            missing.append(i18n.t("project_setup.need_language"))
        if (
            project is not None
            and not can_use_game_engine(project)
            and (self._sdk_path is None or not self._sdk_path.is_file())
        ):
            missing.append(i18n.t("project_setup.need_sdk"))
        return missing

    def _can_extract(self) -> bool:
        """Return True when folder is set and target language code is valid.

        Returns:
            True if extraction can proceed.
        """
        return not self._missing_requirements()

    def _update_extract_btn(self) -> None:
        """Toggle the extract button styling and say what it is waiting for."""
        missing = self._missing_requirements()
        can = not missing
        self._extract_btn_box.bgcolor = ACCENT if can else "#26242f"
        self._extract_btn_icon.color = ACCENT_ON if can else TEXT_HINT
        self._extract_btn_text.color = ACCENT_ON if can else TEXT_HINT
        self._extract_hint.value = (
            ""
            if can
            else i18n.t("project_setup.extract_missing").format(
                items=", ".join(missing)
            )
        )
        self._extract_hint.visible = not can

    def _set_extracting(self, extracting: bool) -> None:
        """Toggle the loading state: show/hide loader and disable/enable fields.

        The browse button is disabled rather than stripped of its handler,
        so it also leaves the focus order: an action refusing to run must
        not still be reachable by the keyboard.

        Args:
            extracting: True to enter loading state, False to leave it.
        """
        self._extracting = extracting
        self._extract_btn.visible = not extracting
        self._extracting_row.visible = extracting
        self._source_dropdown.disabled = extracting
        self._target_dropdown.disabled = extracting
        self._browse_btn.disabled = extracting

    async def _on_extract_clicked(self, _: Event[ft.Container]) -> None:
        """Validate inputs, then extract or ask what to do with existing files.

        Args:
            _: Unused click event.
        """
        if not self._can_extract() or self._extracting or self._mode_dialog_open:
            return
        project = self._state.project_path
        if project is None:
            return
        if not validate_project_dir(project):
            self._set_error(i18n.t("project_setup.invalid_project_dir"))
            return
        if self._has_existing_tl(project, self._state.target_language):
            self._mode_dialog_open = True
            self._page.show_dialog(self._build_existing_tl_dialog(project))
            return
        await self._start_extraction(project, "update")

    @staticmethod
    def _has_existing_tl(project: Path, language: str) -> bool:
        """Return True when the target language folder already holds .rpy files.

        Args:
            project: The Ren'Py project root path.
            language: The target language, used as the tl/ folder name.

        Returns:
            True when a previous translation is present on disk.
        """
        tl_dir = project / "game" / "tl" / language
        return tl_dir.is_dir() and any(tl_dir.rglob("*.rpy"))

    def _build_existing_tl_dialog(self, project: Path) -> ft.AlertDialog:
        """Build the dialog offering the three ways to handle existing files.

        Args:
            project: The Ren'Py project root path being set up.

        Returns:
            An AlertDialog with one clickable card per extraction mode.
        """
        return ft.AlertDialog(
            modal=True,
            title=ft.Text(
                i18n.t("project_setup.existing_tl_title"),
                size=18,
                weight=ft.FontWeight.W_600,
                color=TEXT_H,
            ),
            bgcolor="#1a1822",
            content=ft.Column(
                [
                    ft.Text(
                        i18n.t("project_setup.existing_tl_desc").format(
                            language=localized_label(self._state.target_language)
                        ),
                        size=13.5,
                        color=TEXT_MUTED,
                    ),
                    self._build_mode_card(
                        project,
                        "keep",
                        ft.Icons.PLAY_ARROW,
                        ACCENT,
                    ),
                    self._build_mode_card(
                        project,
                        "update",
                        ft.Icons.SYNC,
                        ACCENT,
                    ),
                    self._build_mode_card(
                        project,
                        "reset",
                        ft.Icons.RESTART_ALT,
                        ERROR,
                    ),
                ],
                spacing=12,
                tight=True,
                width=_MODE_DIALOG_WIDTH,
            ),
            actions=[
                focusable(
                    ft.Container(
                        content=ft.Text(
                            i18n.t("common.cancel"),
                            size=13.5,
                            weight=ft.FontWeight.W_500,
                            color=TEXT_MUTED,
                        ),
                        padding=ft.Padding(left=12, right=12, top=8, bottom=8),
                        ink=True,
                        border_radius=8,
                    ),
                    on_click=lambda _e: self._close_mode_dialog(),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

    def _close_mode_dialog(self) -> None:
        """Dismiss the existing-files dialog and allow it to be reopened."""
        self._mode_dialog_open = False
        self._page.pop_dialog()

    def _build_mode_card(
        self,
        project: Path,
        mode: _ExtractMode,
        icon: ft.IconData,
        accent: str,
    ) -> ft.Control:
        """Build one clickable extraction-mode card for the existing-files dialog.

        Args:
            project: The Ren'Py project root path being set up.
            mode: The extraction mode this card selects.
            icon: Flet icon name shown on the left.
            accent: Icon and title color, ERROR for the destructive mode.

        Returns:
            A focusable card starting that extraction mode when activated.

        The width is fixed rather than expanded. focusable() returns a
        button, and a button given expand=True inside a Column takes the
        main axis, which is the vertical one: the three cards then each
        claimed the remaining height and the dialog filled the window. A
        Container behaved differently, which is why the card only grew
        once it became keyboard-operable. The ring is drawn outside the
        width asked for, so it is subtracted here to land on the width
        the surrounding Column has.
        """
        return focusable(
            ft.Container(
                bgcolor=BG_INPUT,
                border=border_all(1, BORDER_COLOR),
                border_radius=10,
                padding=ft.Padding(left=14, right=14, top=12, bottom=12),
                ink=True,
                content=ft.Row(
                    [
                        ft.Icon(icon, size=18, color=accent),
                        ft.Column(
                            [
                                ft.Text(
                                    i18n.t(f"project_setup.existing_{mode}_title"),
                                    size=13.5,
                                    weight=ft.FontWeight.W_600,
                                    color=TEXT_H,
                                ),
                                ft.Text(
                                    i18n.t(f"project_setup.existing_{mode}_desc"),
                                    size=12.5,
                                    color=TEXT_MUTED,
                                ),
                            ],
                            spacing=3,
                            expand=True,
                        ),
                    ],
                    spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                ),
            ),
            on_click=lambda _e: self._on_mode_chosen(project, mode),
            radius=10,
            width=_MODE_DIALOG_WIDTH - 2 * FOCUS_RING_WIDTH,
        )

    def _on_mode_chosen(self, project: Path, mode: _ExtractMode) -> None:
        """Close the existing-files dialog and start the chosen extraction.

        Args:
            project: The Ren'Py project root path being set up.
            mode: The extraction mode picked by the user.
        """
        self._close_mode_dialog()
        self._page.run_task(self._start_extraction, project, mode)

    async def _start_extraction(self, project: Path, mode: _ExtractMode) -> None:
        """Run extraction in a background thread and open the review view.

        Archiving the existing tl/ folder raises its own ArchiveError, told
        apart from every other filesystem failure the run can hit. It gets a
        message naming the likely culprit, because the raw "file used by
        another process" tells the user nothing about what to close.

        Args:
            project: Validated Ren'Py project root path.
            mode: How the tl/ folder already on disk must be treated.
        """
        if self._extracting:
            return
        self._set_extracting(True)
        self._status.value = ""
        self._page.update()

        try:
            await asyncio.to_thread(self._run_extraction, project, mode)
        except ArchiveError as exc:
            self._set_error(i18n.t("project_setup.archive_failed").format(error=exc))
            self._set_extracting(False)
            self._update_extract_btn()
            self._page.update()
            return
        except Exception as exc:
            self._set_error(str(exc))
            self._set_extracting(False)
            self._update_extract_btn()
            self._page.update()
            return

        if len(self._state.blocks) == 0:
            self._set_error(
                i18n.t("project_setup.no_blocks")
                + i18n.t("project_setup.no_blocks_sdk")
            )
            self._set_extracting(False)
            self._update_extract_btn()
            self._page.update()
            return

        if self._only_common_rpy(self._state.blocks):
            self._set_error(i18n.t("project_setup.only_common_rpy"))
            self._set_extracting(False)
            self._update_extract_btn()
            self._page.update()
            return

        self._init_db(project, mode)
        if self._discarded_sources:
            self._set_extracting(False)
            self._update_extract_btn()
            self._page.show_dialog(self._build_discarded_dialog())
            return
        self._on_done()

    def _build_discarded_dialog(self) -> ft.AlertDialog:
        """Build the dialog naming the sources Ren'Py could not parse.

        Their lines never reach the review screen, so staying silent
        would leave the user to discover a whole file missing without a
        way to learn why.

        Returns:
            A dialog listing the dropped files, opening the review
            screen once acknowledged.
        """
        return ft.AlertDialog(
            modal=True,
            bgcolor="#1a1822",
            title=ft.Text(
                i18n.t("project_setup.discarded_title"),
                size=18,
                weight=ft.FontWeight.W_600,
                color=WARNING,
            ),
            content=ft.Column(
                [
                    ft.Text(
                        i18n.t("project_setup.discarded_message"),
                        size=13.5,
                        color=TEXT_MUTED,
                    ),
                    *[
                        ft.Text(name, size=12.5, color=TEXT_PATH)
                        for name in self._discarded_sources
                    ],
                ],
                spacing=8,
                tight=True,
                width=380,
            ),
            actions=[
                focusable(
                    ft.Container(
                        content=ft.Text(
                            i18n.t("project_setup.discarded_continue"),
                            size=13.5,
                            weight=ft.FontWeight.W_600,
                            color=ACCENT_ON,
                        ),
                        bgcolor=ACCENT,
                        padding=ft.Padding(left=18, right=18, top=10, bottom=10),
                        ink=True,
                        border_radius=8,
                    ),
                    on_click=lambda _e: self._on_discarded_acknowledged(),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

    def _on_discarded_acknowledged(self) -> None:
        """Close the dropped-sources dialog and open the review screen."""
        self._page.pop_dialog()
        self._on_done()

    @classmethod
    def _read_resume_info(cls, project: Path) -> _ResumeInfo | None:
        """Read or infer metadata to decide whether a project is resumable.

        A project is resumable when its database exists and holds at least one
        unit. The target language comes from persisted metadata when available;
        for databases created before metadata was stored it is inferred from the
        on-disk tl/ folder. The tl/ folder must still be present, since it is
        needed to save and export without re-running the SDK.

        Args:
            project: The selected Ren'Py project root path.

        Returns:
            Resume metadata, or None when the project cannot be resumed.
        """
        db_path = project / ".rts" / "translations.db"
        if not db_path.is_file():
            return None
        db = Database(db_path)
        try:
            db.connect_readonly()
            counts = TranslationUnitRepository(db.conn, db.lock).count_by_status()
            total = sum(counts.values())
            if total == 0:
                return None

            meta = ProjectMetaRepository(db.conn, db.lock)
            lang, source = cls._read_meta(meta)

            if not lang:
                lang = cls._infer_target_language(project)
                if lang is None:
                    return None
                units = TranslationUnitRepository(db.conn, db.lock)
                if not cls._tl_matches_db(project, lang, units):
                    return None

            if not (project / "game" / "tl" / lang).is_dir():
                return None

            return _ResumeInfo(
                target_language=lang,
                source_language=source,
                total=total,
                validated=counts.get("human_validated", 0),
                ai_suggested=counts.get("ai_suggested", 0),
                imported=counts.get("imported", 0),
            )
        except (sqlite3.Error, OSError, ParseError, UnicodeDecodeError):
            logger.warning("Skipping unreadable project database at %s", db_path)
            return None
        finally:
            db.close()

    @staticmethod
    def _read_meta(
        meta: ProjectMetaRepository,
    ) -> tuple[str | None, str]:
        """Read stored project metadata, tolerating a legacy schema.

        Databases predating metadata storage have no project_meta table; a
        read-only connection cannot create it, so a missing table degrades to
        "no metadata" (the inference path) instead of raising.

        Args:
            meta: Repository bound to the read-only connection.

        Returns:
            Tuple of (target_language, source_language), where the first is
            None when unavailable.
        """
        try:
            lang = meta.get("target_language")
            source = meta.get("source_language") or "english"
        except sqlite3.OperationalError:
            return None, "english"
        return lang, source

    @staticmethod
    def _tl_matches_db(
        project: Path, lang: str, units: TranslationUnitRepository
    ) -> bool:
        """Check that an on-disk tl/<lang> folder belongs to this database.

        Legacy databases store no extraction method, so the folder is assumed
        to be SDK output. It might instead be a translation shipped with the
        game, whose block ids would not match the database; resuming would
        then parse the wrong source. Requiring a non-empty block-id
        intersection rejects that case.

        Args:
            project: The Ren'Py project root path.
            lang: The inferred target language folder name.
            units: Repository bound to the project database.

        Returns:
            True when the folder and the database share at least one block id.
        """
        tl_dir = project / "game" / "tl" / lang
        blocks = TranslateBlockParser().parse_directory(tl_dir)
        disk_ids = {block.block_id for block in blocks}
        if not disk_ids:
            return False
        return not disk_ids.isdisjoint(units.all_block_ids())

    @staticmethod
    def _infer_target_language(project: Path) -> str | None:
        """Guess the target language from the tl/ folders present on disk.

        Used only for databases predating metadata storage. Succeeds when
        exactly one recognized language folder containing .rpy files exists.

        Args:
            project: The selected Ren'Py project root path.

        Returns:
            The inferred language folder name, or None when it is absent or
            ambiguous.
        """
        tl_root = project / "game" / "tl"
        if not tl_root.is_dir():
            return None
        candidates = [
            child.name
            for child in tl_root.iterdir()
            if child.is_dir()
            and is_recognized_language(child.name)
            and any(child.rglob("*.rpy"))
        ]
        return candidates[0] if len(candidates) == 1 else None

    async def _resume_project(self, project: Path, info: _ResumeInfo) -> None:
        """Restore a project's session and jump straight to the review view.

        Args:
            project: The Ren'Py project root path to resume.
            info: Resume metadata previously read from that project.
        """
        if self._extracting:
            return
        from_list = self._mode == "list"
        self._state.project_path = project
        self._state.target_language = info.target_language
        self._state.source_language = info.source_language
        self._set_extracting(True)
        self._status.value = ""
        if from_list:
            self._content_holder.content = self._build_loading_content()
        self._page.update()

        try:
            await asyncio.to_thread(self._run_resume, project)
        except Exception as exc:
            self._set_extracting(False)
            self._update_extract_btn()
            if from_list:
                self._refresh_recent(do_update=False)
                self._content_holder.content = self._build_list_content()
                self._page.update()
                self._show_error(
                    i18n.t("project_setup.resume_failed").format(error=str(exc))
                )
            else:
                self._status.value = str(exc)
                self._status.color = ERROR
                self._content_holder.content = self._build_form_content()
                self._page.update()
            return

        self._open_existing_db(project)
        self._on_done()

    def _show_error(self, message: str) -> None:
        """Show a floating error toast, reusing a single SnackBar instance.

        Page.show_dialog() only attaches a control once, so later calls just
        toggle the existing snackbar and push a page update.

        Args:
            message: The error text to display.
        """
        self._error_snack.content = ft.Text(message, size=13, color=ERROR)
        self._error_snack.bgcolor = "#2b1c1c"
        self._error_snack.open = True
        if self._error_snack_shown:
            self._page.update()
        else:
            self._page.show_dialog(self._error_snack)
            self._error_snack_shown = True

    def _build_loading_content(self) -> ft.Control:
        """Build a centered spinner shown while a project is being resumed.

        Returns:
            A Control with a progress ring and a status label.
        """
        return ft.Container(
            expand=True,
            alignment=ft.Alignment(0, 0),
            content=ft.Row(
                [
                    ft.ProgressRing(width=18, height=18, color=ACCENT, stroke_width=2),
                    ft.Text(
                        i18n.t("project_setup.resuming"),
                        size=14,
                        color=TEXT_MUTED,
                    ),
                ],
                spacing=12,
                tight=True,
                alignment=ft.MainAxisAlignment.CENTER,
            ),
        )

    def _refresh_recent(self, do_update: bool = True) -> None:
        """Rebuild the recent-projects list from the global registry.

        Entries whose database has disappeared are pruned; entries that are
        no longer resumable are hidden but kept.

        Args:
            do_update: Whether to push a page update after rebuilding.
        """
        cards: list[ft.Control] = []
        for project in recent_projects.all():
            if not (project / ".rts" / "translations.db").is_file():
                recent_projects.remove(project)
                continue
            info = self._read_resume_info(project)
            if info is None:
                continue
            cards.append(self._build_recent_card(project, info))
        self._recent_col.controls = cards
        self._recent_empty.visible = not cards
        if do_update:
            self._page.update()

    def _build_recent_card(self, project: Path, info: _ResumeInfo) -> ft.Control:
        """Build one clickable card for a resumable project.

        Args:
            project: The Ren'Py project root path.
            info: Resume metadata read from that project.

        Returns:
            A Container with a resume area and a delete button.
        """
        meta_line = "{lang} · {counts}".format(
            lang=localized_label(info.target_language),
            counts=i18n.t("project_setup.recent_lines").format(
                total=info.total,
                validated=info.validated,
            ),
        )
        info_area = focusable(
            ft.Container(
                height=_CARD_HEIGHT,
                alignment=ft.Alignment(x=-1, y=0),
                ink=True,
                border_radius=8,
                padding=ft.Padding(left=14, right=10, top=0, bottom=0),
                content=ft.Column(
                    [
                        ft.Text(
                            project.name,
                            size=14,
                            weight=ft.FontWeight.W_600,
                            color=TEXT_H,
                            max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS,
                        ),
                        ft.Text(
                            str(project),
                            size=11,
                            color=TEXT_HINT,
                            max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS,
                        ),
                        ft.Text(meta_line, size=12, color=TEXT_MUTED),
                    ],
                    spacing=2,
                    tight=True,
                ),
            ),
            on_click=lambda _e: self._page.run_task(
                self._resume_project, project, info
            ),
            tooltip=i18n.t("project_setup.resume_tooltip").format(name=project.name),
            expand=True,
            height=_CARD_HEIGHT,
        )
        delete_btn = focusable(
            ft.Container(
                content=ft.Icon(ft.Icons.CLOSE, size=18, color=TEXT_HINT),
                height=_CARD_HEIGHT,
                alignment=ft.Alignment(x=0, y=0),
                ink=True,
                border_radius=8,
                padding=ft.Padding(left=14, right=14, top=0, bottom=0),
            ),
            on_click=lambda _e: self._on_recent_delete_clicked(project),
            tooltip=i18n.t("project_setup.delete_tooltip"),
            height=_CARD_HEIGHT,
        )
        return ft.Container(
            bgcolor=BG_INPUT,
            border=border_all(1, BORDER_COLOR),
            border_radius=11,
            content=ft.Row(
                [info_area, delete_btn],
                spacing=0,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

    def _on_recent_delete_clicked(self, project: Path) -> None:
        """Show a confirmation dialog before deleting a project's data.

        Args:
            project: The Ren'Py project root path to delete.
        """
        if self._extracting:
            return
        self._page.show_dialog(self._build_delete_dialog(project))

    def _build_delete_dialog(self, project: Path) -> ft.AlertDialog:
        """Build the destructive-delete confirmation dialog.

        Args:
            project: The Ren'Py project root path to delete.

        Returns:
            An AlertDialog asking the user to confirm the deletion.
        """
        return ft.AlertDialog(
            modal=True,
            title=ft.Text(
                i18n.t("project_setup.delete_title"),
                size=18,
                weight=ft.FontWeight.W_600,
                color=TEXT_H,
            ),
            bgcolor="#1a1822",
            content=ft.Text(
                i18n.t("project_setup.delete_message").format(name=project.name),
                size=13.5,
                color=TEXT_MUTED,
                width=340,
            ),
            actions=[
                focusable(
                    ft.Container(
                        content=ft.Text(
                            i18n.t("common.cancel"),
                            size=13.5,
                            weight=ft.FontWeight.W_500,
                            color=TEXT_MUTED,
                        ),
                        padding=ft.Padding(left=12, right=12, top=8, bottom=8),
                        ink=True,
                        border_radius=8,
                    ),
                    on_click=lambda _e: self._page.pop_dialog(),
                ),
                focusable(
                    ft.Container(
                        content=ft.Text(
                            i18n.t("project_setup.delete_btn"),
                            size=13.5,
                            weight=ft.FontWeight.W_600,
                            color=ERROR,
                        ),
                        padding=ft.Padding(left=12, right=12, top=8, bottom=8),
                        ink=True,
                        border_radius=8,
                    ),
                    on_click=lambda _e: self._on_delete_confirmed(project),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

    def _on_delete_confirmed(self, project: Path) -> None:
        """Delete the project's .rts/ data and drop it from the registry.

        Args:
            project: The Ren'Py project root path to delete.
        """
        self._page.pop_dialog()
        if (
            self._state.db is not None
            and self._state.project_path is not None
            and self._state.project_path.resolve() == project.resolve()
        ):
            self._state.db.close()
            self._state.db = None
        rts_dir = project / ".rts"
        try:
            shutil.rmtree(rts_dir)
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.warning("Failed to delete %s: %s", rts_dir, exc)
            self._show_error(
                i18n.t("project_setup.delete_failed").format(name=project.name)
            )
            return
        recent_projects.remove(project)
        self._refresh_recent(do_update=True)

    def _run_resume(self, project: Path) -> None:
        """Rebuild the tl/ scaffolding and parsed blocks without touching the DB.

        Reuses the tl/ folder already generated on disk by the SDK.

        Args:
            project: Validated Ren'Py project root path.
        """
        lang = self._state.target_language
        game_dir = project / "game"

        tl_dir = game_dir / "tl" / lang
        self._state.tl_output_dir = tl_dir

        self._state.blocks = (
            TranslateBlockParser().parse_directory(tl_dir) if tl_dir.is_dir() else []
        )
        self._state.game_name = GameNameResolver().resolve(project)

    def _open_existing_db(self, project: Path) -> None:
        """Reopen the project's database without re-inserting or pruning units.

        Args:
            project: Validated Ren'Py project root path.
        """
        db_path = project / ".rts" / "translations.db"
        if self._state.db is not None:
            self._state.db.close()
        db = Database(db_path)
        db.connect()
        self._state.db = db
        recent_projects.add(project)

    @staticmethod
    def _only_common_rpy(blocks: list[TranslationBlock]) -> bool:
        """Check whether every block comes from a bare common.rpy file.

        The Ren'Py SDK's translate command skips any script packed inside
        an .rpa archive, but still generates common.rpy from the engine's
        own bundled strings. A result made up of nothing else looks like
        a successful extraction while carrying no dialogue from the game.

        Args:
            blocks: Parsed translation blocks from a completed extraction.

        Returns:
            True if there is at least one block and every one of them
            comes from a file named common.rpy.
        """
        return bool(blocks) and all(
            Path(block.source_file).name == "common.rpy" for block in blocks
        )

    def _run_extraction(self, project: Path, mode: _ExtractMode) -> None:
        """Prepare the tl/ folder, run Ren'Py when needed and parse the result.

        "update" and "reset" both archive the folder already on disk and let
        Ren'Py rebuild it. Ren'Py only ever appends to an existing folder,
        never prunes it, so rebuilding is the only way to learn what the game
        dropped between two versions: the regenerated folder describes the
        current script and nothing else.

        "update" reads the old folder before archiving it, so the translations
        it held can still be adopted; "reset" throws them away on purpose.
        Nothing is lost either way, since the database keeps every translation
        and saving mirrors all of them back into the files.

        Args:
            project: Validated Ren'Py project root path.
            mode: "keep" reuses the files on disk untouched, "update" rebuilds
                them while adopting their translations, "reset" rebuilds them
                and drops those translations.

        Raises:
            EngineNotFoundError: If no Ren'Py engine can run here.
            RenpyCliError: If the extraction command fails.
            ParseError: If a file of the existing folder cannot be read.
            ArchiveError: If the existing tl/ folder cannot be archived.
            CompiledScriptsOnlyError: If game/'s archives hold only
                compiled .rpyc scripts, with no .rpy source to extract.
        """
        lang = self._state.target_language
        tl_dir = project / "game" / "tl" / lang
        parser = TranslateBlockParser()
        self._discarded_sources = []

        self._disk_blocks = (
            parser.parse_directory(tl_dir)
            if mode == "update" and tl_dir.is_dir()
            else []
        )

        if mode != "keep":
            engine = resolve_engine(project, self._sdk_path)
            self._archive_tl_dir(project, tl_dir)
            self._t_extracting.value = i18n.t("project_setup.unpacking_sources")
            safe_update(self._page)
            try:
                unpacked = unpack_archived_sources(project)
            finally:
                self._t_extracting.value = i18n.t("project_setup.extracting")
                safe_update(self._page)
            if not unpacked and archives_contain_compiled_scripts(project):
                raise CompiledScriptsOnlyError(
                    i18n.t("project_setup.compiled_scripts_only")
                )
            disable_extracted_archives(project)
            try:
                self._translate_discarding_broken_sources(engine, project, lang)
            finally:
                restore_disabled_archives(project)

        self._state.tl_output_dir = tl_dir
        self._state.blocks = parser.parse_directory(tl_dir) if tl_dir.is_dir() else []
        if mode == "keep":
            self._disk_blocks = self._state.blocks
        self._state.game_name = GameNameResolver().resolve(project)

    def _translate_discarding_broken_sources(
        self,
        engine: Path,
        project: Path,
        lang: str,
    ) -> None:
        """Run the engine, dropping the unpacked sources it cannot parse.

        Ren'Py loads every script before generating anything, so a single
        unparseable one fails the whole run. An archive can hold such a
        source and still ship a game that runs, because the engine reads
        the .rpyc next to it and never looks at the .rpy; unpacking that
        .rpy is what puts it in front of the parser for the first time.
        Dropping it hands that file back to its .rpyc, at the price of
        its lines staying untranslated.

        Ren'Py stops at the first file it cannot parse and only reveals
        the next one on the following run, so this retries as long as it
        keeps blaming a file the manifest recorded. A round that drops
        nothing of ours re-raises.

        The same loop absorbs a different failure: a source Ren'Py
        reports as defined twice, because disable_extracted_archives()
        could not take its archive out of the way (a mixed archive, kept
        in place so its images or audio stay reachable). Ren'Py names
        that source with the same "File ..., line N" shape a parse error
        uses, so it is discarded the same way. A mixed archive can make
        every one of its extracted sources conflict this way, one
        revealed per round, which is why _MAX_DISCARD_ROUNDS is generous
        rather than tuned to the rare parse error alone.

        Args:
            engine: The Ren'Py executable resolved for this project.
            project: Validated Ren'Py project root path.
            lang: Target language code.

        Raises:
            RenpyCliError: If the engine fails for any other reason, or
                still fails once no unpacked source is left to drop.
        """
        for _ in range(_MAX_DISCARD_ROUNDS):
            try:
                RenpyCli().translate(engine, project, lang)
            except RenpyCliError as exc:
                dropped = discard_unpacked_files(project, parse_failed_files(str(exc)))
                if not dropped:
                    raise
                self._discarded_sources.extend(dropped)
                logger.warning(
                    "Ren'Py could not parse unpacked source(s), dropped: %s",
                    ", ".join(dropped),
                )
            else:
                return
        RenpyCli().translate(engine, project, lang)

    @staticmethod
    def _archive_tl_dir(project: Path, tl_dir: Path) -> None:
        """Copy an existing translation folder into the backups, then empty it.

        The folder is copied and emptied rather than moved. Renaming a
        directory fails on Windows as soon as any process sits inside it, and
        a translation folder is exactly the kind of place a file manager, an
        editor or the game itself is left open on. Copying needs no exclusive
        access, and deleting the files it holds leaves the directory in place
        for the SDK to fill again.

        The archive lives under .rts/, outside game/, so Ren'Py never picks it
        up as a second translation of the same language.

        Args:
            project: The Ren'Py project root path.
            tl_dir: The tl/<language> folder to archive.

        Raises:
            ArchiveError: If the folder cannot be copied or emptied.
        """
        if not tl_dir.is_dir():
            return
        try:
            backups = project / ".rts" / "backups"
            backups.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            archive = backups / f"{tl_dir.name}-{stamp}"
            attempt = 1
            while archive.exists():
                archive = backups / f"{tl_dir.name}-{stamp}-{attempt}"
                attempt += 1
            shutil.copytree(tl_dir, archive)
            for path in list(tl_dir.rglob("*")):
                if path.is_file():
                    path.unlink()
        except OSError as exc:
            raise ArchiveError(str(exc)) from exc
        logger.info("Archived %s to %s", tl_dir, archive)

    def _init_db(self, project: Path, mode: _ExtractMode) -> None:
        """Create or reopen the SQLite DB and sync it with the parsed blocks.

        Must be called from the main thread (SQLite thread restriction).

        Callers must ensure the parse produced at least one block: an empty
        extraction would make delete_stale() wipe the whole project.

        Args:
            project: Validated Ren'Py project root path.
            mode: Extraction mode; "reset" drops every stored translation
                before the parsed blocks are inserted.
        """
        db_path = project / ".rts" / "translations.db"
        db_path.parent.mkdir(exist_ok=True)
        if self._state.db is not None:
            self._state.db.close()
        db = Database(db_path)
        db.connect()
        self._state.db = db
        repo = TranslationUnitRepository(db.conn, db.lock)
        if mode == "reset":
            repo.clear_translations()
        units: list[dict[str, object]] = [
            {
                "block_id": b.block_id,
                "source_file": b.source_file,
                "source_line": b.source_line,
                "character_variable": b.character_variable,
                "source_text": b.source_text,
            }
            for b in self._state.blocks
        ]
        repo.bulk_insert(units)
        current_ids = {b.block_id for b in self._state.blocks}
        moved = repo.transfer_orphan_translations(current_ids)
        obsolete = repo.delete_stale(current_ids)
        if moved or obsolete:
            logger.info(
                "Re-keyed %d translation(s), dropped %d obsolete unit(s)",
                moved,
                obsolete,
            )
        self._import_disk_translations(repo, self._disk_blocks)
        self._validate_symbol_only_units(repo)

        meta = ProjectMetaRepository(db.conn, db.lock)
        meta.set("target_language", self._state.target_language)
        meta.set("source_language", self._state.source_language)
        recent_projects.add(project)

    @staticmethod
    def _import_disk_translations(
        repo: TranslationUnitRepository, blocks: list[TranslationBlock]
    ) -> None:
        """Adopt the translations already written in the tl/ files.

        Only units still not_translated are filled, so the database stays
        authoritative for anything already drafted, suggested or validated.
        Imported lines get their own status rather than borrowing
        ai_suggested: nothing is known about who wrote them, so they must
        neither be counted as model output nor pass for reviewed work. Like
        any translated state they are skipped by automatic jobs.

        A block whose translation equals its source text is an untouched SDK
        stub, not a translation, and is skipped (see parser.is_translated).

        Args:
            repo: Repository for the project's current database.
            blocks: Blocks parsed from the tl/ folder before it was rebuilt.
        """
        pending = {
            unit.block_id for unit in repo.get_all(status_filter="not_translated")
        }
        repo.update_translations(
            [
                (block.block_id, block.translated_text, "imported")
                for block in blocks
                if block.block_id in pending and is_translated(block)
            ]
        )

    @staticmethod
    def _validate_symbol_only_units(repo: TranslationUnitRepository) -> None:
        """Auto-validate units whose source text has nothing to translate.

        Their text is copied verbatim from the source, no model is ever
        involved, so there is nothing for a human to review: they are
        marked human_validated rather than ai_suggested, which keeps the
        "AI suggested" filter to actual model output.

        Runs on every extraction, not just for newly-inserted units, so it
        also catches units reset to not_translated by "Clear translations"
        and upgrades the ai_suggested copies left by earlier versions.
        A unit whose text was edited by hand is left alone.

        Args:
            repo: Repository for the project's current database.
        """
        for status in ("not_translated", "ai_suggested"):
            for unit in repo.get_all(status_filter=status):
                if needs_translation(unit.source_text):
                    continue
                if unit.translated_text and unit.translated_text != unit.source_text:
                    continue
                repo.update_translation(
                    unit.block_id, unit.source_text, "human_validated"
                )

    def _set_error(self, message: str) -> None:
        """Display an error message in the status area.

        Args:
            message: The error text to display.
        """
        self._status.value = message
        self._status.color = ERROR
        self._page.update()
