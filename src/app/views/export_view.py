"""Export view: zip generation from extracted translation blocks."""

import logging
import re
from collections.abc import Callable
from pathlib import Path

import flet as ft
from flet.controls.control_event import Event

from app.components.stepper import build_stepper
from app.state import AppState
from app.theme import (
    ACCENT,
    ACCENT_ON,
    BG_INPUT,
    BORDER_COLOR,
    ERROR,
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
from core.export_sync import ExportSyncState, check_sync
from core.exporter import TranslationZipExporter
from core.i18n import i18n
from core.renpy.unpacker import remove_unpacked_sources
from core.storage.repositories import ProjectMetaRepository, TranslationUnitRepository

logger = logging.getLogger(__name__)

_CONTENT_MAX_WIDTH = 640


class ExportView:
    """View for exporting the extracted translation as a zip archive."""

    def __init__(
        self,
        page: ft.Page,
        state: AppState,
        on_back: Callable[[], None],
        on_setup: Callable[[], None],
    ) -> None:
        """Initialize the export view.

        Args:
            page: The Flet page instance.
            state: Shared application state to read.
            on_back: Callback invoked when the user returns to review.
            on_setup: Callback invoked when the user jumps back to setup.
        """
        self._page = page
        self._state = state
        self._on_back = on_back
        self._on_setup = on_setup
        self._exporting = False

        count = len(state.blocks)
        formatted = f"{count:,}".replace(",", " ")
        self._block_count_text = ft.Text(
            formatted,
            size=30,
            weight=ft.FontWeight.W_700,
            color=TEXT_H,
        )

        self._game_name_inner = ft.TextField(
            value=state.game_name,
            border=ft.InputBorder.NONE,
            bgcolor="transparent",
            color=TEXT,
            cursor_color=ACCENT,
            expand=True,
            content_padding=ft.Padding(left=14, right=14, top=0, bottom=0),
            on_change=self._on_game_name_changed,
        )
        self._game_name_container = ft.Container(
            content=ft.Row(
                [self._game_name_inner],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=BG_INPUT,
            border=border_all(1.5, BORDER_COLOR),
            border_radius=11,
            height=48,
        )

        self._zip_label = ft.Text(
            self._make_zip_name(),
            size=11.5,
            color=TEXT_HINT,
        )

        has_blocks = count > 0
        self._export_btn_icon = ft.Icon(
            ft.Icons.DOWNLOAD,
            size=17,
            color=ACCENT_ON if has_blocks else TEXT_HINT,
        )
        self._export_btn_text = ft.Text(
            i18n.t("export.export_btn"),
            size=14.5,
            weight=ft.FontWeight.W_600,
            color=ACCENT_ON if has_blocks else TEXT_HINT,
        )
        self._export_btn = focusable(
            ft.Container(
                content=ft.Row(
                    [self._export_btn_icon, self._export_btn_text],
                    tight=True,
                    spacing=10,
                ),
                bgcolor=ACCENT if has_blocks else "#26242f",
                border_radius=12,
                padding=ft.Padding(left=26, right=26, top=14, bottom=14),
                ink=has_blocks,
            ),
            on_click=self._on_export_clicked,
            radius=12,
            disabled=not has_blocks,
        )
        self._exporting_row = ft.Row(
            [
                ft.ProgressRing(width=16, height=16, color=ACCENT, stroke_width=2),
                ft.Text(i18n.t("export.generating"), size=14, color=TEXT_MUTED),
            ],
            spacing=10,
            visible=False,
        )

        self._success_path_text = ft.Text("", size=12, color="#8aa792")
        self._success_panel = ft.Container(
            content=ft.Row(
                [
                    ft.Container(
                        content=ft.Icon(ft.Icons.CHECK, color="#10261a", size=15),
                        width=26,
                        height=26,
                        border_radius=13,
                        bgcolor=SUCCESS,
                        alignment=ft.Alignment(x=0, y=0),
                    ),
                    ft.Column(
                        [
                            ft.Text(
                                i18n.t("export.success_title"),
                                size=13.5,
                                weight=ft.FontWeight.W_600,
                                color="#bdeccb",
                            ),
                            self._success_path_text,
                        ],
                        spacing=2,
                        tight=True,
                    ),
                ],
                spacing=13,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor="#0f2316",
            border=border_all(1, "#2a6640"),
            border_radius=12,
            padding=ft.Padding(left=18, right=18, top=15, bottom=15),
            visible=False,
        )
        self._error_text = ft.Text("", color=ERROR, size=13)

    def build(self) -> ft.Control:
        """Build and return the export view control tree.

        Returns:
            A Flet Control representing the complete export view.
        """
        return ft.Column(
            controls=[
                build_stepper(3, on_setup=self._on_setup, on_review=self._on_back),
                ft.Container(
                    expand=True,
                    alignment=ft.Alignment(0, 0),
                    content=ft.Container(
                        width=_CONTENT_MAX_WIDTH,
                        content=ft.Column(
                            controls=[
                                self._build_header(),
                                self._build_counter(),
                                self._build_game_name_section(),
                                ft.Column(
                                    [
                                        ft.Row(
                                            [
                                                self._export_btn,
                                                self._exporting_row,
                                                focusable(
                                                    ft.Container(
                                                        content=ft.Text(
                                                            i18n.t(
                                                                "export.back_to_review"
                                                            ),
                                                            size=13.5,
                                                            weight=ft.FontWeight.W_500,
                                                            color=TEXT_MUTED,
                                                        ),
                                                        ink=True,
                                                        border_radius=6,
                                                        padding=ft.Padding(
                                                            left=4,
                                                            right=4,
                                                            top=2,
                                                            bottom=2,
                                                        ),
                                                    ),
                                                    on_click=lambda _: self._on_back(),
                                                    radius=6,
                                                ),
                                            ],
                                            spacing=16,
                                            vertical_alignment=(
                                                ft.CrossAxisAlignment.CENTER
                                            ),
                                        ),
                                        self._success_panel,
                                        self._error_text,
                                    ],
                                    spacing=16,
                                ),
                            ],
                            scroll=ft.ScrollMode.AUTO,
                            spacing=26,
                        ),
                        padding=ft.Padding(left=40, right=40, top=30, bottom=36),
                    ),
                ),
            ],
            expand=True,
            spacing=0,
        )

    def _build_header(self) -> ft.Column:
        """Build the section title and subtitle.

        Returns:
            A Column with title Text and subtitle Text.
        """
        return ft.Column(
            [
                ft.Text(
                    i18n.t("export.title"),
                    size=24,
                    weight=ft.FontWeight.W_600,
                    color=TEXT_H,
                ),
                ft.Text(
                    i18n.t("export.subtitle"),
                    size=13,
                    color=TEXT_DIM,
                ),
            ],
            spacing=4,
        )

    def _build_counter(self) -> ft.Container:
        """Build the extracted block count card.

        Returns:
            A styled Container with an icon, count, and label.
        """
        return ft.Container(
            content=ft.Row(
                [
                    ft.Container(
                        content=ft.Icon(ft.Icons.SEGMENT, color=ACCENT, size=24),
                        width=48,
                        height=48,
                        border_radius=12,
                        bgcolor="#1f1b2b",
                        alignment=ft.Alignment(x=0, y=0),
                    ),
                    ft.Column(
                        [
                            self._block_count_text,
                            ft.Text(
                                i18n.t("export.blocks_extracted"),
                                size=13,
                                color=TEXT_MUTED,
                            ),
                        ],
                        spacing=5,
                        tight=True,
                    ),
                ],
                spacing=18,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding(left=22, right=22, top=20, bottom=20),
            border_radius=14,
            bgcolor="#201d2b",
            border=border_all(1, "#322f3d"),
        )

    def _build_game_name_section(self) -> ft.Container:
        """Build the game name input with zip filename preview.

        Returns:
            A max-width Container with label, field, and filename preview.
        """
        return ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        i18n.t("export.game_name_label"),
                        size=12,
                        weight=ft.FontWeight.W_600,
                        color=TEXT_MUTED,
                    ),
                    self._game_name_container,
                    self._zip_label,
                ],
                spacing=9,
            ),
            width=380,
        )

    def _make_zip_name(self) -> str:
        """Generate a sanitized zip filename from current game name and language.

        Returns:
            A string like "GameName_french.zip".
        """
        name = re.sub(
            r"[^A-Za-z0-9_\-]",
            "_",
            self._state.game_name.strip() or "game",
        )
        lang = self._state.target_language or "lang"
        return f"{name}_{lang}.zip"

    def _on_game_name_changed(self, e: Event[ft.TextField]) -> None:
        """Update game name in state and refresh the zip filename label.

        Args:
            e: The text field change event.
        """
        self._state.game_name = e.control.value or ""
        self._zip_label.value = self._make_zip_name()
        self._page.update()

    async def _on_export_clicked(self, _: Event[ft.TextButton]) -> None:
        """Warn about out-of-date tl/ files, then run the export.

        Args:
            _: Unused click event.
        """
        if self._exporting or not self._state.game_name.strip():
            return
        sync = self._collect_sync_state()
        untranslated = self._count_untranslated()
        out_of_sync = sync is not None and not sync.in_sync
        if out_of_sync or untranslated:
            self._show_sync_warning(sync, untranslated)
            return
        await self._run_export()

    def _count_untranslated(self) -> int:
        """Count the lines the archive would ship in the source language.

        The SDK fills every generated block with a copy of the source
        text, so an untranslated line is invisible in the archive: it
        looks like a finished file that happens to be in English.

        Returns:
            How many units still hold no translation, zero when the
            project has no open database.
        """
        db = self._state.db
        if db is None:
            return 0
        counts = TranslationUnitRepository(db.conn, db.lock).count_by_status()
        return counts.get("not_translated", 0)

    def _collect_sync_state(self) -> ExportSyncState | None:
        """Compare the tl/ files with the database, when both are available.

        Returns:
            The detected discrepancies, or None if the project has no open
            database or no extraction directory to check.
        """
        db = self._state.db
        tl_dir = self._state.tl_output_dir
        if db is None or tl_dir is None:
            return None
        return check_sync(
            tl_dir,
            ProjectMetaRepository(db.conn, db.lock),
            TranslationUnitRepository(db.conn, db.lock),
        )

    def _show_sync_warning(
        self, sync: ExportSyncState | None, untranslated: int
    ) -> None:
        """Ask for confirmation before archiving an incomplete translation.

        Args:
            sync: The discrepancies to list, None when they cannot be
                checked.
            untranslated: Lines that would ship in the source language.
        """
        messages: list[str] = []
        if sync is not None and sync.never_saved:
            messages.append(i18n.t("export.sync_never_saved"))
        if sync is not None and sync.unsaved_units:
            messages.append(
                i18n.t("export.sync_unsaved_units").format(n=sync.unsaved_units)
            )
        if sync is not None and sync.externally_modified:
            messages.append(i18n.t("export.sync_external_edit"))
        if untranslated:
            messages.append(i18n.t("export.untranslated_lines").format(n=untranslated))

        dialog = ft.AlertDialog(
            modal=True,
            bgcolor="#1a1822",
            title=ft.Text(
                i18n.t("export.incomplete_title"),
                size=15,
                weight=ft.FontWeight.W_600,
                color=WARNING,
            ),
            content=ft.Column(
                [ft.Text(m, size=13, color=TEXT_MUTED) for m in messages],
                spacing=8,
                tight=True,
                width=380,
            ),
            actions=[
                focusable(
                    ft.Container(
                        content=ft.Text(
                            i18n.t("common.cancel"), size=13.5, color=TEXT_MUTED
                        ),
                        padding=ft.Padding(left=12, right=12, top=10, bottom=10),
                        ink=True,
                        border_radius=8,
                    ),
                    on_click=lambda _e: self._page.pop_dialog(),
                ),
                focusable(
                    ft.Container(
                        content=ft.Text(
                            i18n.t("export.sync_export_anyway"),
                            size=13.5,
                            weight=ft.FontWeight.W_600,
                            color=ACCENT_ON,
                        ),
                        bgcolor=ACCENT,
                        border_radius=8,
                        padding=ft.Padding(left=18, right=18, top=10, bottom=10),
                        ink=True,
                    ),
                    on_click=self._on_sync_warning_confirmed,
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self._page.show_dialog(dialog)

    async def _on_sync_warning_confirmed(self, _: Event[ft.TextButton]) -> None:
        """Close the warning dialog and export the files as they are.

        Args:
            _: Unused click event.
        """
        self._page.pop_dialog()
        await self._run_export()

    async def _run_export(self) -> None:
        """Open the save-file dialog and write the zip archive."""
        game_name = self._state.game_name.strip() or "game"
        lang = self._state.target_language or "translation"
        out_path = await ft.FilePicker().save_file(
            file_name=self._make_zip_name(),
            allowed_extensions=["zip"],
        )
        if not out_path:
            return

        self._exporting = True
        self._export_btn.visible = False
        self._exporting_row.visible = True
        self._success_panel.visible = False
        self._error_text.value = ""
        self._page.update()

        tl_dir = self._state.tl_output_dir
        if tl_dir is None:
            self._set_error(i18n.t("export.error_no_tl_dir"))
            self._export_btn.visible = True
            self._exporting_row.visible = False
            self._exporting = False
            self._page.update()
            return

        lang_dir = tl_dir / "tl" / lang if (tl_dir / "tl").exists() else tl_dir
        try:
            TranslationZipExporter().export(lang_dir, game_name, lang, Path(out_path))
            self._success_path_text.value = out_path
            self._success_panel.visible = True
        except Exception as exc:
            self._set_error(str(exc))
        else:
            self._cleanup_unpacked_sources()

        self._export_btn.visible = True
        self._exporting_row.visible = False
        self._exporting = False
        self._page.update()

    def _cleanup_unpacked_sources(self) -> None:
        """Remove sources unpacked from .rpa archives, now that export is done.

        Character detection and re-extraction both need those sources on
        disk while the project is being worked on, but once a translation
        has been exported nothing in this application reads them again. A
        failure here (a file the game or an editor still has open) must
        never turn a completed export into a reported failure, so it is
        only logged.
        """
        project_path = self._state.project_path
        if project_path is None:
            return
        try:
            remove_unpacked_sources(project_path)
        except OSError:
            logger.warning("Could not remove unpacked archive sources", exc_info=True)

    def _set_error(self, message: str) -> None:
        """Display an error message.

        Args:
            message: The error text to display.
        """
        self._error_text.value = message
        self._page.update()
