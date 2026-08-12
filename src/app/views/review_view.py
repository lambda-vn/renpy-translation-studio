"""Review view: two-panel layout with file list and paginated block editing."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any, ParamSpec

import flet as ft
from flet.controls.control_event import Event

from app import shortcuts
from app.components.stepper import build_stepper
from app.dialogs import dialog_action
from app.live_server import LiveServer
from app.state import AppState, ReviewViewState
from app.theme import (
    ACCENT,
    ACCENT_ON,
    BG_FILE_SEL,
    BG_INPUT,
    BORDER_COLOR,
    DOT_AI,
    DOT_DRAFT,
    DOT_HUMAN,
    DOT_IMPORTED,
    DOT_NONE,
    ERROR,
    FOCUS_RING,
    FOCUS_RING_WIDTH,
    SUCCESS,
    TEXT,
    TEXT_H,
    TEXT_HINT,
    TEXT_MUTED,
    WARNING,
    border_all,
    focusable,
)
from app.ui_thread import on_ui_thread, safe_update
from core.export_sync import META_SAVED_AT, record_save
from core.file_reveal import RevealError, reveal_in_file_manager
from core.i18n import i18n
from core.interchange import (
    FORMAT_EXTENSION,
    READABLE_EXTENSIONS,
    ImportPlan,
    InterchangeError,
    apply_plan,
    plan_import,
    read_interchange,
    write_interchange,
)
from core.project_actions import fill_from_memory
from core.renpy.writer import TranslateBlockWriter
from core.settings import settings
from core.storage.repositories import (
    CharacterRepository,
    DuplicateStats,
    FileStats,
    ProjectMetaRepository,
    TranslationStatus,
    TranslationUnit,
    TranslationUnitRepository,
)
from core.storage.translation_memory import translation_memory
from core.translation.job import JobProgress, TranslationJob, needs_translation
from core.translation.providers.base import TranslateBatchResult, TranslationUnitPayload
from core.translation.providers.registry import registry
from core.translation.quality import LENGTH_WARNING_KIND
from core.translation.quality import check as quality_check
from core.validators import is_recognized_language

logger = logging.getLogger(__name__)

_P = ParamSpec("_P")

# Pseudo-statut du menu de filtre : une erreur qualite se calcule en Python
# a partir de la source et de la traduction, aucune requete ne peut la poser.
_ERROR_FILTER = "blocking_error"

# Second pseudo-statut : le drapeau "a revoir" est pose a la main et vit a cote
# du statut, pas dedans. Il partage le menu de statut plutot que d'ouvrir un
# troisieme, la question posee etant "ou en sont mes marques", jamais
# "mes marques parmi les suggestions IA".
_REVIEW_FILTER = "needs_review"

_CLEAR_STATUS_SETS: dict[str, list[TranslationStatus]] = {
    "unvalidated": ["ai_suggested", "draft", "imported"],
    "ai_suggested": ["ai_suggested"],
}

# ── Couleurs ──────────────────────────────────────────────────────────────── #
_STATUS_COLORS = {
    "not_translated": DOT_NONE,
    "draft": DOT_DRAFT,
    "imported": DOT_IMPORTED,
    "ai_suggested": DOT_AI,
    "human_validated": DOT_HUMAN,
}

_STATUS_ICONS = {
    "not_translated": ft.Icons.RADIO_BUTTON_UNCHECKED,
    "draft": ft.Icons.EDIT_OUTLINED,
    "imported": ft.Icons.FILE_DOWNLOAD_OUTLINED,
    "ai_suggested": ft.Icons.AUTO_AWESOME,
    "human_validated": ft.Icons.CHECK_CIRCLE,
}

_STATUS_LABEL_KEYS: dict[TranslationStatus, str] = {
    "not_translated": "review.filter_not_translated",
    "draft": "review.filter_draft",
    "imported": "review.filter_imported",
    "ai_suggested": "review.filter_ai_suggested",
    "human_validated": "review.filter_validated",
}

_PROVIDER_LABELS = {
    "deepl": "DeepL",
    "ollama": "Ollama",
    "libretranslate": "LibreTranslate",
    "claude": "Claude",
    "mistral": "Mistral",
}

# ── Mise en page ──────────────────────────────────────────────────────────── #
_PANEL_WIDTH = 240
_INDENT_BASE = 10  # retrait gauche des entrees de premier niveau (px)
_INDENT_STEP = 14  # retrait ajoute par niveau de dossier (px)
_PAGE_SIZE = 50
_COL_STATUS = 40  # largeur fixe colonne statut (px)
_COL_ACTION = (
    44  # largeur fixe d'un bouton d'action (traduire/copier/vider/marquer/valider)
)
_ROW_ACTION_HEIGHT = 32  # hauteur fixe d'un bouton d'action, pour un survol propre (px)
_ROW_SPACING = 12  # espacement entre cellules dans ft.Row
_ROW_ACTIONS = 5  # nombre de boutons d'action par ligne

# Largeur reellement occupee par la colonne des actions. Les lignes voisines,
# la note et l'en-tete de tableau reservent cette largeur d'un seul bloc la ou
# la ligne principale pose cinq boutons espaces : sans les espacements ni
# l'anneau de focus, leurs colonnes tombent 48 px a cote de celles de la ligne
# qu'elles commentent.
_COL_ACTIONS = (
    _ROW_ACTIONS * (_COL_ACTION + 2 * FOCUS_RING_WIDTH)
    + (_ROW_ACTIONS - 1) * _ROW_SPACING
)
_EDIT_DEBOUNCE = 0.35  # delai avant d'ecrire une saisie en base (s)
_JOB_REFRESH_INTERVAL = 1.0  # intervalle min. entre deux rebuilds pendant un job (s)
_CONTEXT_RADIUS = 2  # lignes voisines montrees de chaque cote d'une ligne
_CONTEXT_MARKER = 14  # gouttiere du reperage de la ligne courante (px)


# ── Helpers panneau fichiers ──────────────────────────────────────────────── #


def _split_source_path(source_file: str) -> tuple[str, str]:
    """Split a stored source path into its folder and file name.

    Args:
        source_file: Path as stored in the database. The separator depends
            on the platform that ran the extraction, so both are accepted.

    Returns:
        Tuple of (folder using forward slashes, file name). The folder is
        an empty string for files stored at the project root.
    """
    normalized = source_file.replace("\\", "/")
    folder, _, name = normalized.rpartition("/")
    return folder, name


def _common_root_depth(folders: list[str]) -> int:
    """Return how many leading path segments every folder shares.

    Ren'Py keeps all translatable sources under a fixed root folder, so
    that prefix carries no information and is stripped from the headers.

    Args:
        folders: Folder paths with forward slashes, empty for the root.

    Returns:
        The number of common leading segments, zero as soon as a file sits
        at the root or the folders diverge from the start.
    """
    segments = [folder.split("/") if folder else [] for folder in folders]
    if not segments:
        return 0
    depth = 0
    while depth < min(len(s) for s in segments):
        if len({s[depth] for s in segments}) > 1:
            break
        depth += 1
    return depth


@dataclass
class _FolderNode:
    """One folder of the file panel, holding its subfolders and its files."""

    children: dict[str, _FolderNode] = field(default_factory=dict)
    files: list[FileStats] = field(default_factory=list)


def _build_folder_tree(stats: list[FileStats], root_depth: int) -> _FolderNode:
    """Arrange per-file stats into the folder tree they belong to.

    Args:
        stats: Per-file counts as returned by get_files(), in file order.
        root_depth: Leading path segments shared by every folder, dropped
            since they carry no information.

    Returns:
        The root node, whose children are the top-level folders and whose
        files are the ones sitting outside any folder.
    """
    root = _FolderNode()
    for entry in stats:
        folder, _ = _split_source_path(entry["source_file"])
        segments = folder.split("/")[root_depth:] if folder else []
        node = root
        for segment in segments:
            node = node.children.setdefault(segment, _FolderNode())
        node.files.append(entry)
    return root


def _filter_key(vstate: ReviewViewState) -> str:
    """Return the dropdown entry standing for a stored filter.

    The two entries that are not statuses select on something a status
    cannot express, so they replace it rather than joining it, and the
    dropdown has to be put back on the right one when the view is rebuilt
    from a snapshot.

    Args:
        vstate: The review snapshot to read the running filter from.

    Returns:
        The key of the matching dropdown option, empty for no filter.
    """
    if vstate.errors_only:
        return _ERROR_FILTER
    if vstate.review_only:
        return _REVIEW_FILTER
    return vstate.status_filter or ""


def _has_blocking_issue(unit: TranslationUnit) -> bool:
    """Return whether a unit carries an error that blocks its validation.

    Args:
        unit: The stored unit to check.

    Returns:
        True when a quality check refuses this translation. The length
        warning is left out: it blocks nothing and is a suspicion, not an
        error.
    """
    return any(
        issue.kind != LENGTH_WARNING_KIND
        for issue in quality_check(unit.source_text, unit.translated_text)
    )


# ── Etat local de la vue ──────────────────────────────────────────────────── #


@dataclass
class _Row:
    """One displayed translation row and the controls the view drives.

    Rows are kept in page order so the keyboard can act on the one being
    edited and walk down the list without the mouse.
    """

    unit: TranslationUnit
    field: ft.TextField
    status_icon: ft.Icon
    warning: ft.Text
    review_icon: ft.Icon
    note: ft.TextField
    note_box: ft.Container


@dataclass
class _PendingEdit:
    """A field edit waiting to be written to the database.

    Holds the row it will refresh once written, so a keystroke costs
    nothing until the user stops typing.
    """

    row: _Row
    value: str


# ── Vue principale ────────────────────────────────────────────────────────── #


class ReviewView:
    """Two-panel translation review: file list on the left, paginated blocks."""

    def __init__(
        self,
        page: ft.Page,
        state: AppState,
        on_export: Callable[[], None],
        on_back: Callable[[], None],
        on_configure_provider: Callable[[], None],
        on_manage_characters: Callable[[], None],
        on_manage_universe: Callable[[], None],
        on_global_shortcut: Callable[[str], bool],
    ) -> None:
        """Initialize the review view.

        Args:
            page: The Flet page instance.
            state: Shared application state (db must be connected).
            on_export: Navigate to the zip export view.
            on_back: Navigate back to project setup.
            on_configure_provider: Navigate to the provider settings view.
            on_manage_characters: Navigate to the character glossary view.
            on_manage_universe: Navigate to the universe summary view.
            on_global_shortcut: Run an app-wide shortcut action by name.
                This view owns the page's key handler while it is up, so
                the shortcuts that work everywhere else have to reach it
                from here rather than being reimplemented.
        """
        if state.db is None:
            raise RuntimeError("Database not connected.")

        self._page = page
        self._state = state
        self._on_export = on_export
        self._on_back = on_back
        self._on_configure_provider = on_configure_provider
        self._on_manage_characters = on_manage_characters
        self._on_manage_universe = on_manage_universe
        self._on_global_shortcut = on_global_shortcut
        self._repo = TranslationUnitRepository(state.db.conn, state.db.lock)
        self._character_repo = CharacterRepository(state.db.conn, state.db.lock)
        self._project_meta_repo = ProjectMetaRepository(state.db.conn, state.db.lock)
        self._vstate = state.review_state()
        self._job: TranslationJob | None = None
        self._job_dialog_shown_once = False
        self._disposed = False
        self._translating_units: set[str] = set()
        self._symbol_only_units: set[str] = set()
        self._characters: dict[str, str] = {}
        self._rows: list[_Row] = []
        self._focused_row: int | None = None
        self._editing = False
        self._file_order: list[str] = []
        self._file_buttons: dict[str, ft.TextButton] = {}
        self._file_menus: dict[str, ft.ContextMenu] = {}
        self._focused_file: str | None = None
        self._menu_file: str | None = None
        self._live: LiveServer | None = None
        self._page.run_task(self._start_live)
        self._pending_edit: _PendingEdit | None = None
        self._edit_timer: threading.Timer | None = None
        self._words_counted_for: tuple[int, int] | None = None
        self._panel_refreshed_at = 0.0

        # ── Controles mutables (persistent across page/filter changes) ── #
        self._file_list_col = ft.Column(
            spacing=2,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )
        self._block_list_col = ft.Column(
            spacing=0,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )
        self._pagination_row = ft.Row(
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=4,
        )
        self._counter_text = ft.Text(
            "...",
            size=13,
            weight=ft.FontWeight.W_500,
            color=TEXT_MUTED,
        )
        self._sync_text = ft.Text("", size=12, color=TEXT_HINT)
        self._progress_bar = ft.ProgressBar(
            value=0, color=SUCCESS, bgcolor=BG_INPUT, height=4, border_radius=2
        )
        self._progress_text = ft.Text("", size=11, color=TEXT_HINT)
        self._save_box = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.SAVE_OUTLINED, size=15, color=ACCENT_ON),
                    ft.Text(
                        i18n.t("review.save_btn"),
                        size=13,
                        weight=ft.FontWeight.W_600,
                        color=ACCENT_ON,
                    ),
                ],
                spacing=7,
                tight=True,
            ),
            bgcolor=ACCENT,
            border_radius=9,
            padding=ft.Padding(left=14, right=14, top=9, bottom=9),
            ink=True,
        )
        self._save_btn = focusable(
            self._save_box,
            on_click=self._on_save_clicked,
            radius=9,
        )
        self._status_snack: ft.SnackBar | None = None
        self._filter_dropdown = ft.Dropdown(
            value=_filter_key(self._vstate),
            options=[
                *(self._status_filter_option(status) for status in _STATUS_LABEL_KEYS),
                ft.dropdown.Option(
                    key=_REVIEW_FILTER,
                    text=i18n.t("review.filter_needs_review"),
                    leading_icon=ft.Icon(ft.Icons.FLAG, size=14, color=WARNING),
                ),
                ft.dropdown.Option(
                    key=_ERROR_FILTER,
                    text=i18n.t("review.filter_errors"),
                    leading_icon=ft.Icon(ft.Icons.ERROR_OUTLINE, size=14, color=ERROR),
                ),
                ft.dropdown.Option(
                    key="",
                    text=i18n.t("review.filter_all"),
                    leading_icon=ft.Icon(
                        ft.Icons.FILTER_ALT_OFF_OUTLINED, size=14, color=TEXT_HINT
                    ),
                ),
            ],
            bgcolor=BG_INPUT,
            border_color=BORDER_COLOR,
            focused_border_color=FOCUS_RING,
            focused_border_width=FOCUS_RING_WIDTH,
            color=TEXT,
            border_radius=8,
            width=190,
            content_padding=ft.Padding(left=10, right=0, top=0, bottom=0),
            dense=True,
            on_select=self._on_filter_changed,
        )
        self._character_dropdown = ft.Dropdown(
            value=self._vstate.character_filter or "",
            visible=False,
            editable=True,
            enable_filter=True,
            menu_height=320,
            leading_icon=ft.Icons.PERSON_SEARCH_OUTLINED,
            hint_text=i18n.t("review.filter_character_hint"),
            hint_style=ft.TextStyle(color=TEXT_HINT),
            bgcolor=BG_INPUT,
            border_color=BORDER_COLOR,
            focused_border_color=FOCUS_RING,
            focused_border_width=FOCUS_RING_WIDTH,
            color=TEXT,
            border_radius=8,
            width=260,
            content_padding=ft.Padding(left=10, right=0, top=0, bottom=0),
            dense=True,
            on_select=self._on_character_filter_changed,
        )
        self._search_field = ft.TextField(
            value=self._vstate.search_query,
            hint_text=i18n.t("review.search_hint"),
            hint_style=ft.TextStyle(color=TEXT_HINT),
            prefix_icon=ft.Icons.SEARCH,
            bgcolor=BG_INPUT,
            border_color=BORDER_COLOR,
            focused_border_color=FOCUS_RING,
            focused_border_width=FOCUS_RING_WIDTH,
            border_radius=8,
            color=TEXT,
            cursor_color=ACCENT,
            height=40,
            width=230,
            content_padding=ft.Padding(left=8, right=8, top=0, bottom=0),
            on_change=self._on_search_changed,
        )

        self._scope_dropdown = ft.Dropdown(
            value="all",
            options=[
                ft.dropdown.Option(key="all", text=i18n.t("translation.scope_all")),
                ft.dropdown.Option(key="file", text=i18n.t("translation.scope_file")),
            ],
            bgcolor=BG_INPUT,
            border_color=BORDER_COLOR,
            focused_border_color=FOCUS_RING,
            focused_border_width=FOCUS_RING_WIDTH,
            color=TEXT,
            border_radius=8,
            width=190,
            content_padding=ft.Padding(left=10, right=0, top=0, bottom=0),
            dense=True,
        )
        self._translate_text = ft.Text(
            i18n.t("translation.translate_automatic"),
            size=13,
            weight=ft.FontWeight.W_600,
            color=ACCENT_ON,
        )
        self._translate_btn = focusable(
            ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.AUTO_AWESOME, size=14, color=ACCENT_ON),
                        self._translate_text,
                    ],
                    spacing=7,
                    tight=True,
                ),
                bgcolor=ACCENT,
                border_radius=9,
                padding=ft.Padding(left=14, right=14, top=9, bottom=9),
                ink=True,
            ),
            on_click=self._on_translate_clicked,
            radius=9,
        )
        self._job_provider_text = ft.Text(
            "", size=13.5, weight=ft.FontWeight.W_600, color=TEXT_H
        )
        self._job_progress_bar = ft.ProgressBar(
            value=0, color=ACCENT, bgcolor=BG_INPUT, expand=True
        )
        self._job_counter_text = ft.Text("", size=13, color=TEXT_MUTED)
        self._job_batch_text = ft.Text("", size=12.5, color=TEXT_HINT)
        self._job_hint_text = ft.Text("", size=12, color=TEXT_HINT)
        self._job_event_text = ft.Text("", size=12, color=TEXT_HINT, expand=True)
        self._job_cancel_text = ft.Text(
            i18n.t("translation.cancel"),
            size=13,
            weight=ft.FontWeight.W_600,
            color=ERROR,
        )
        self._job_cancel_btn = focusable(
            ft.Container(
                content=self._job_cancel_text,
                ink=True,
                border_radius=8,
                border=border_all(1, "#4a2828"),
                padding=ft.Padding(left=14, right=14, top=7, bottom=7),
            ),
            on_click=self._on_cancel_clicked,
        )
        self._job_banner = ft.Container(
            visible=False,
            bgcolor="#1b1a26",
            border=ft.Border(bottom=ft.BorderSide(1, "#1a1820")),
            padding=ft.Padding(left=14, right=14, top=10, bottom=10),
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.AUTO_AWESOME, size=15, color=ACCENT),
                            self._job_provider_text,
                            self._job_progress_bar,
                            self._job_counter_text,
                            self._job_cancel_btn,
                        ],
                        spacing=12,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Row(
                        [self._job_batch_text, self._job_event_text],
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    self._job_hint_text,
                ],
                spacing=6,
                tight=True,
            ),
        )
        self._provider_choice_label = ft.Text(
            i18n.t("translation.choose_provider_label").upper(),
            size=12,
            weight=ft.FontWeight.W_600,
            color=TEXT_MUTED,
        )
        self._provider_choice_dropdown = ft.Dropdown(
            options=[],
            bgcolor=BG_INPUT,
            border_color=BORDER_COLOR,
            focused_border_color=FOCUS_RING,
            focused_border_width=FOCUS_RING_WIDTH,
            color=TEXT,
            border_radius=8,
            width=300,
            dense=True,
            content_padding=ft.Padding(left=10, right=0, top=0, bottom=0),
        )
        self._scope_choice_label = ft.Text(
            i18n.t("translation.scope_label").upper(),
            size=12,
            weight=ft.FontWeight.W_600,
            color=TEXT_MUTED,
        )
        self._job_selection_col = ft.Column(
            spacing=9,
            tight=True,
            width=340,
        )
        self._translate_options_available: list[str] = []
        self._provider_choice_start_text = ft.Text(
            i18n.t("translation.start"),
            size=13.5,
            weight=ft.FontWeight.W_600,
            color=ACCENT_ON,
        )
        self._provider_choice_start_btn = focusable(
            ft.Container(
                content=self._provider_choice_start_text,
                bgcolor=ACCENT,
                border_radius=8,
                padding=ft.Padding(left=18, right=18, top=10, bottom=10),
                ink=True,
            ),
            on_click=self._on_provider_choice_confirmed,
        )
        self._provider_choice_cancel_text = ft.Text(
            i18n.t("common.cancel"), size=13.5, color=TEXT_MUTED
        )
        self._provider_choice_cancel_btn = focusable(
            ft.Container(
                content=self._provider_choice_cancel_text,
                padding=ft.Padding(left=12, right=12, top=10, bottom=10),
                ink=True,
                border_radius=8,
            ),
            on_click=lambda _e: self._hide_job_dialog(),
        )
        self._job_dialog = ft.AlertDialog(
            modal=True,
            bgcolor="#1a1822",
            content=self._job_selection_col,
            actions=[
                self._provider_choice_cancel_btn,
                self._provider_choice_start_btn,
            ],
            actions_alignment=ft.MainAxisAlignment.END,
            on_dismiss=self._on_job_dialog_dismissed,
        )
        self._provider_warning_text = ft.Text(
            i18n.t("translation.no_provider_configured"),
            size=12,
            color=WARNING,
        )
        self._language_warning_text = ft.Text(
            "",
            size=12,
            color=WARNING,
        )
        self._provider_link_text = ft.Text(
            i18n.t("provider_config.open_settings"),
            size=12,
            weight=ft.FontWeight.W_600,
            color=ACCENT,
        )
        self._provider_link_btn = focusable(
            ft.Container(
                content=self._provider_link_text,
                ink=True,
                border_radius=6,
                padding=ft.Padding(left=6, right=6, top=3, bottom=3),
            ),
            on_click=lambda _e: self._navigate_provider(),
            radius=6,
        )
        self._characters_btn = self._toolbar_link(
            ft.Icons.GROUP_OUTLINED,
            i18n.t("review.nav_characters"),
            lambda _e: self._navigate_characters(),
        )
        self._universe_btn = self._toolbar_link(
            ft.Icons.PUBLIC,
            i18n.t("review.nav_universe"),
            lambda _e: self._navigate_universe(),
        )
        self._memory_btn = self._toolbar_link(
            ft.Icons.HISTORY_EDU_OUTLINED,
            i18n.t("review.memory_label"),
            lambda _e: self._fill_from_memory(),
            tooltip=i18n.t("review.memory_tooltip"),
        )
        self._interchange_btn = self._toolbar_link(
            ft.Icons.IMPORT_EXPORT,
            i18n.t("interchange.label"),
            lambda _e: self._open_interchange_dialog(),
            tooltip=i18n.t("interchange.tooltip"),
        )
        self._interchange_format_dropdown = ft.Dropdown(
            value="csv",
            label=i18n.t("interchange.format_label"),
            options=[
                ft.dropdown.Option(key="csv", text=i18n.t("interchange.format_csv")),
                ft.dropdown.Option(
                    key="xliff", text=i18n.t("interchange.format_xliff")
                ),
                ft.dropdown.Option(key="json", text=i18n.t("interchange.format_json")),
            ],
            bgcolor=BG_INPUT,
            border_color=BORDER_COLOR,
            focused_border_color=FOCUS_RING,
            focused_border_width=FOCUS_RING_WIDTH,
            color=TEXT,
            border_radius=8,
            content_padding=ft.Padding(left=10, right=0, top=0, bottom=0),
            dense=True,
        )
        self._interchange_scope_dropdown = ft.Dropdown(
            value="file",
            label=i18n.t("interchange.scope_label"),
            options=[
                ft.dropdown.Option(key="file", text=i18n.t("translation.scope_file")),
                ft.dropdown.Option(key="all", text=i18n.t("translation.scope_all")),
            ],
            bgcolor=BG_INPUT,
            border_color=BORDER_COLOR,
            focused_border_color=FOCUS_RING,
            focused_border_width=FOCUS_RING_WIDTH,
            color=TEXT,
            border_radius=8,
            content_padding=ft.Padding(left=10, right=0, top=0, bottom=0),
            dense=True,
        )
        self._clear_btn = self._toolbar_link(
            ft.Icons.DELETE_SWEEP_OUTLINED,
            i18n.t("review.clear_label"),
            lambda _e: self._open_clear_dialog(),
            tooltip=i18n.t("review.clear_tooltip"),
        )
        self._clear_scope_dropdown = ft.Dropdown(
            value="file",
            options=[
                ft.dropdown.Option(key="file", text=i18n.t("translation.scope_file")),
                ft.dropdown.Option(key="all", text=i18n.t("translation.scope_all")),
            ],
            bgcolor=BG_INPUT,
            border_color=BORDER_COLOR,
            focused_border_color=FOCUS_RING,
            focused_border_width=FOCUS_RING_WIDTH,
            color=TEXT,
            border_radius=8,
            width=190,
            content_padding=ft.Padding(left=10, right=0, top=0, bottom=0),
            dense=True,
        )
        self._clear_status_dropdown = ft.Dropdown(
            value="unvalidated",
            label=i18n.t("review.clear_status_label"),
            options=[
                ft.dropdown.Option(
                    key="unvalidated", text=i18n.t("review.clear_status_unvalidated")
                ),
                ft.dropdown.Option(
                    key="ai_suggested", text=i18n.t("review.clear_status_ai")
                ),
                ft.dropdown.Option(key="", text=i18n.t("review.clear_status_all")),
            ],
            bgcolor=BG_INPUT,
            border_color=BORDER_COLOR,
            focused_border_color=FOCUS_RING,
            focused_border_width=FOCUS_RING_WIDTH,
            color=TEXT,
            border_radius=8,
            width=250,
            content_padding=ft.Padding(left=10, right=0, top=0, bottom=0),
            dense=True,
        )
        self._translate_row = ft.Row(
            spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER
        )
        self._rebuild_translate_controls()

        # ── Chargement initial ──────────────────────────────────────────── #
        files = self._repo.get_files()
        known = {entry["source_file"] for entry in files}
        if self._vstate.selected_file not in known:
            self._vstate.selected_file = files[0]["source_file"] if files else None
            self._vstate.current_page = 0
        self._refresh_character_options()
        self._load_files()
        if self._vstate.selected_file:
            self._load_page()

        self._outer_keyboard = self._page.on_keyboard_event
        self._page.on_keyboard_event = self._on_keyboard

    @staticmethod
    def _toolbar_link(
        icon: ft.IconData,
        label: str,
        on_click: Callable[[Any], Any],
        *,
        tooltip: str | None = None,
    ) -> ft.TextButton:
        """Build one labelled button of the toolbar's action row.

        Every entry of the row carries its label, the two leaving the
        screen as much as the three acting on the project. Reduced to bare
        glyphs the latter said nothing about what they would do to a
        project, and a bulk clear is not something to discover by hovering.

        Args:
            icon: The glyph shown before the label.
            label: What the button does, in one or two words; also its
                accessible name.
            on_click: Called on click, on Enter and on Space.
            tooltip: The longer sentence, for the actions whose label
                cannot say what exactly they touch. The navigation entries
                name their own destination and pass nothing.

        Returns:
            The focusable toolbar button.
        """
        return focusable(
            ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(icon, size=17, color=TEXT_MUTED),
                        ft.Text(label, size=12, color=TEXT_MUTED),
                    ],
                    spacing=6,
                    tight=True,
                ),
                ink=True,
                border_radius=8,
                padding=ft.Padding(left=8, right=10, top=6, bottom=6),
            ),
            on_click=on_click,
            tooltip=tooltip,
        )

    @staticmethod
    def _toolbar_separator() -> ft.Container:
        """Build the thin rule standing between two toolbar groups.

        Returns:
            A one pixel wide vertical rule.
        """
        return ft.Container(width=1, height=22, bgcolor=BORDER_COLOR)

    @staticmethod
    def _row_action(
        icon: ft.IconData, tooltip: str, on_click: Callable[[Any], Any]
    ) -> ft.TextButton:
        """Build one of the action buttons at the end of a translation row.

        Args:
            icon: The glyph shown.
            tooltip: What the action does, and its accessible name.
            on_click: Called on click, on Enter and on Space.

        Returns:
            The focusable action, sized to the row's action column.
        """
        return focusable(
            ft.Container(
                content=ft.Icon(icon, size=14, color=TEXT_HINT),
                width=_COL_ACTION,
                height=_ROW_ACTION_HEIGHT,
                alignment=ft.Alignment(0, 0),
                border_radius=8,
                ink=True,
            ),
            on_click=on_click,
            tooltip=tooltip,
            width=_COL_ACTION,
            height=_ROW_ACTION_HEIGHT,
        )

    def _safe_update(self) -> None:
        """Push pending UI changes to the client, safely from any thread."""
        safe_update(self._page)

    def _on_ui_thread(self, handler: Callable[_P, None]) -> Callable[_P, None]:
        """Wrap a job callback so its whole body runs on the event loop.

        Job callbacks fire on a background thread and mutate the control
        tree: the progress bar, the event log column.

        Args:
            handler: The UI-mutating callback to protect.

        Returns:
            A callable with the same signature, safe to invoke from any
            thread.
        """
        return on_ui_thread(self._page, handler)

    def may_leave(self) -> bool:
        """Answer whether this view can be replaced right now.

        Leaving disposes the view, which cancels the translation it is
        running. Every navigation this view owns asks first, but the
        settings dialog reaches the provider screen without going through
        any of them, and it took a whole job down with it. The entry
        point asks here rather than each door growing its own check.

        Returns:
            True when nothing would be lost. False having told the user
            what is holding them, which is the same message the toolbar
            shows.
        """
        if self._disposed:
            return True
        return not self._blocked_by_running_job()

    def dispose(self) -> None:
        """Write any pending edit, then drop the handler and the running job.

        Called both by this view's own navigation and by the entry point
        when another view takes the page over, so it has to survive being
        called twice on the same instance.
        """
        if self._disposed:
            return
        self._disposed = True
        self._flush_pending_edit()
        self._page.on_keyboard_event = self._outer_keyboard
        if self._job is not None:
            self._job.cancel()
        if self._live is not None:
            self._page.run_task(self._stop_live)

    # ── Rafraichissement en direct ────────────────────────────────────────── #

    async def _start_live(self) -> None:
        """Open the endpoint another process uses to say what it wrote.

        Only while this screen is up: it is the one that shows lines, and
        an endpoint outliving it would announce a project nobody is
        looking at.
        """
        if self._disposed or self._state.project_path is None:
            return
        self._live = LiveServer(self._state.project_path, self._on_live_changed)
        await self._live.start()

    async def _stop_live(self) -> None:
        """Withdraw the endpoint on the way out."""
        if self._live is not None:
            await self._live.stop()
            self._live = None

    def _on_live_changed(self, block_ids: list[str] | None) -> None:
        """Refresh the lines another process just wrote, in place.

        Runs on the event loop, the listener being served by it, so the
        controls are reached directly rather than through on_ui_thread().
        Only properties are touched, never the list of rows.

        Rebuilding the page instead would drop every line that no longer
        matches the filter, so a translator watching the untranslated
        ones would see them vanish rather than fill in. Lines outside the
        page are left to the panel counters.

        The row being edited is skipped whatever it holds: the caret is
        in it, and the last word wins is not a rule anyone would accept
        from a machine writing underneath them.

        None means a bulk action rewrote more than it can name, so the
        page is reloaded rather than patched. Not while a field holds the
        caret, though: rebuilding drops the control being typed into, and
        somebody else's mass action is never worth losing a sentence
        somebody is in the middle of writing. The panel counters still
        move, so the change is visible, and the page catches up the next
        time it is loaded.

        Args:
            block_ids: Identifiers of the units that changed, or None
                when too much changed to name it.
        """
        if self._disposed:
            return
        if block_ids is None:
            self._load_files()
            if self._focused_row_or_none() is None:
                self._load_page()
            self._update_sync_indicator()
            self._safe_update()
            return
        wanted = set(block_ids)
        rows = [row for row in self._rows if row.unit.block_id in wanted]
        editing = self._focused_row_or_none()
        editing_id = editing.unit.block_id if editing is not None else None

        fresh = {
            unit.block_id: unit
            for unit in self._repo.get_many([row.unit.block_id for row in rows])
        }
        for row in rows:
            unit = fresh.get(row.unit.block_id)
            if unit is None or unit.block_id == editing_id:
                continue
            row.unit = unit
            row.field.value = unit.translated_text
            self._apply_status(row.status_icon, unit.status)
            self._apply_review_flag(row.review_icon, unit.needs_review)
            row.note.value = unit.note or ""
            row.note_box.visible = unit.needs_review
            self._refresh_warning(row.warning, unit.source_text, unit.translated_text)

        self._load_files()
        self._update_sync_indicator()
        self._safe_update()

    # ── Raccourcis clavier ────────────────────────────────────────────────── #

    async def _on_keyboard(self, e: Any) -> None:
        """Run the shortcuts, both the app-wide ones and this view's own.

        The global table is consulted first and unconditionally: this view
        holds the page handler while it is up, so Escape and F1 would
        otherwise stop working the moment the review is on screen.

        Nothing else runs while a dialog is up. Keystrokes still reach
        this handler under a modal, and acting on them would edit or save
        a screen the user cannot even see.

        Args:
            e: Flet KeyboardEvent.
        """
        key = str(getattr(e, "key", "")).upper()
        ctrl = bool(getattr(e, "ctrl", False)) or bool(getattr(e, "meta", False))
        shift = bool(getattr(e, "shift", False))
        alt = bool(getattr(e, "alt", False))

        global_shortcut = shortcuts.match(
            key, ctrl=ctrl, shift=shift, alt=alt, table=shortcuts.GLOBAL_SHORTCUTS
        )
        if global_shortcut is not None:
            if self._on_global_shortcut(global_shortcut.action):
                return
            if global_shortcut.action == "close_dialog":
                self._clear_search()
            return

        if self._dialog_is_open():
            return

        shortcut = shortcuts.match(
            key, ctrl=ctrl, shift=shift, alt=alt, table=shortcuts.REVIEW_SHORTCUTS
        )
        if shortcut is None:
            return
        await self._run_shortcut(shortcut.action)

    async def _run_shortcut(self, action: str) -> None:
        """Run the review action a shortcut names.

        The names come from app.shortcuts, which is the only place a key
        combination is written down. A name with nothing behind it is a
        typo in that table rather than a user error, so it raises.

        Args:
            action: The action name declared on the matched shortcut.

        Raises:
            KeyError: If the table names an action this view does not have.
        """
        match action:
            case "focus_search":
                await self._search_field.focus()  # type: ignore[no-untyped-call]
                self._safe_update()
            case "save":
                self._on_save_clicked(None)
            case "validate_row":
                await self._validate_focused_row()
            case "spread_duplicates":
                self._spread_focused_row_to_duplicates()
            case "copy_source":
                self._copy_source_into_focused_row()
            case "toggle_review":
                self._toggle_focused_row_review()
            case "focus_previous_row":
                await self._focus_row(-1)
            case "focus_next_row":
                await self._focus_row(1)
            case "focus_previous_file":
                await self._focus_file(-1)
            case "focus_next_file":
                await self._focus_file(1)
            case "open_file_menu":
                self._open_selected_file_menu()
            case "previous_page":
                self._go_to_page(self._vstate.current_page - 1)
            case "next_page":
                self._go_to_page(self._vstate.current_page + 1)
            case _:
                raise KeyError(f"Unbound review shortcut action: {action}")

    def _open_selected_file_menu(self) -> None:
        """Raise the context menu of the file entry holding the focus.

        The very menu the right button opens, so the two ways in cannot
        drift apart. Bound to the dedicated context-menu key.

        The focused entry, not the open one. Walking the panel with the
        keyboard moves the focus without opening anything, and a menu
        answering for the file opened several entries ago acts on
        something the user is no longer looking at. The open file is only
        the fallback, for a menu called while the focus sits outside the
        panel entirely.

        What makes this work is not here but in _file_menu(): the menu has
        to be the one the client already knows. open() is a round trip,
        and a menu rebuilt by a panel refresh has no listener to answer
        it.

        Scheduled rather than awaited so the page's keyboard handler
        returns without waiting on that round trip. A failure then
        surfaces as an unhandled future rather than an exception raised
        here, which is the price of not holding the handler open.
        """
        target = self._focused_file or self._vstate.selected_file
        if target is None:
            return
        menu = self._file_menus.get(target)
        if menu is None:
            return
        self._page.run_task(menu.open)

    async def _focus_file(self, step: int) -> None:
        """Open the file above or below the one currently selected.

        The file panel gets its own pair of keys rather than sharing the
        line keys: a shortcut whose meaning depends on where the focus
        happens to sit is a shortcut nobody can rely on, and the two
        lists are walked at different moments anyway.

        Args:
            step: -1 for the file above, 1 for the file below.
        """
        if not self._file_order:
            return
        selected = self._vstate.selected_file
        current = (
            self._file_order.index(selected) if selected in self._file_order else 0
        )
        target = current + step
        if target < 0 or target >= len(self._file_order):
            return
        wanted = self._file_order[target]
        self._select_file(wanted)
        button = self._file_buttons.get(wanted)
        if button is None:
            return
        self._page.update()
        await button.focus()  # type: ignore[no-untyped-call]

    async def _focus_row(self, step: int) -> None:
        """Move the caret to the translation field above or below.

        Walking the lines is the other half of validating without the
        mouse: Ctrl+Enter goes down the list only as long as every line
        is worth validating, and skipping one has to be as cheap.

        Past either end of the page the neighbouring page is opened and
        the caret lands on the line that continues the walk, so a pass
        over a long file is never interrupted by the pagination.

        Args:
            step: -1 for the line above, 1 for the line below.
        """
        if not self._rows:
            return
        self._flush_pending_edit()
        index = self._focused_row
        target = 0 if index is None else index + step

        if target < 0 or target >= len(self._rows):
            total_pages = max(1, -(-self._vstate.total_units // _PAGE_SIZE))
            page = self._vstate.current_page + (1 if target >= len(self._rows) else -1)
            if page < 0 or page >= total_pages:
                return
            self._go_to_page(page, keep_scroll=True)
            if not self._rows:
                return
            target = 0 if step > 0 else len(self._rows) - 1

        self._focused_row = target
        self._editing = True
        self._page.update()
        await self._rows[target].field.focus()  # type: ignore[no-untyped-call]

    def _dialog_is_open(self) -> bool:
        """Return whether a dialog is standing in front of the review.

        Only AlertDialogs count: status toasts go through the same stack
        and must not disable the keyboard for the five seconds they show.
        The stack itself is private to Flet, so a version that no longer
        exposes it is read as "a dialog is open": the shortcuts this
        guards write the whole project, and refusing them is recoverable
        where firing them behind a modal is not.

        Returns:
            True when a dialog is on screen, blocking every shortcut.
        """
        dialogs = getattr(self._page, "_dialogs", None)
        if dialogs is None:
            return True
        return any(
            isinstance(dialog, ft.AlertDialog) and dialog.open
            for dialog in dialogs.controls
        )

    def _clear_search(self) -> None:
        """Empty the search field and show the whole file again."""
        if not self._search_field.value:
            return
        self._flush_pending_edit()
        self._search_field.value = ""
        self._vstate.search_query = ""
        self._vstate.current_page = 0
        self._load_page(scroll_to_top=True)
        self._load_files()
        self._safe_update()

    def _focused_row_or_none(self) -> _Row | None:
        """Return the row the keyboard acts on, if it still exists.

        The focused index outlives the focus itself: clicking into the
        search field leaves it pointing at the last edited row, which the
        editing flag is what distinguishes. Acting on it there would
        overwrite a line the caret is nowhere near.

        Returns:
            The row whose translation field currently has the focus, None
            when the caret is elsewhere or the page was rebuilt shorter
            since.
        """
        index = self._focused_row
        if not self._editing or index is None or index >= len(self._rows):
            return None
        return self._rows[index]

    def _copy_source_into_focused_row(self) -> None:
        """Put the source text into the translation field being edited."""
        row = self._focused_row_or_none()
        if row is not None:
            self._set_row_text(row, row.unit.source_text)

    async def _validate_focused_row(self) -> None:
        """Validate the row being edited, then focus the next line to do.

        The list is rebuilt by the validation, so which row comes next
        depends on the active filter: under "not translated" the validated
        line is gone and the next one took its index, otherwise the next
        line sits one row further down. Past the last row the next page is
        opened, so a keyboard pass is not stopped every fifty lines.

        The editing flag is raised without waiting for the focus event to
        come back from the client: a second Ctrl+Enter fired before the
        round-trip must still find a focused row to validate.
        """
        index = self._focused_row
        row = self._focused_row_or_none()
        if row is None or index is None:
            return
        if not self._validate_unit(row):
            return

        target = index
        if target < len(self._rows) and self._rows[target].unit.block_id == (
            row.unit.block_id
        ):
            target += 1
        if target >= len(self._rows):
            total_pages = max(1, -(-self._vstate.total_units // _PAGE_SIZE))
            if self._vstate.current_page + 1 >= total_pages:
                return
            self._go_to_page(self._vstate.current_page + 1, keep_scroll=True)
            target = 0
        if not self._rows:
            return
        self._focused_row = target
        self._editing = True
        self._page.update()
        await self._rows[target].field.focus()  # type: ignore[no-untyped-call]

    # ── Chargement panel fichiers ─────────────────────────────────────────── #

    def _load_files(self) -> None:
        """Reload the file list panel, grouping files under their folder.

        While a search or a speaker filter is running, every file carries
        its own match count and the ones with nothing to show are dimmed,
        turning the panel into the map of a question the block list can
        only ever answer for the open file. Both narrow the same way:
        without the panel, a speaker who says nothing in the file being
        read looks like a speaker who says nothing at all.

        The whole-project bar is fed from the counts fetched here rather
        than from a query of its own: they cover every file, so summing
        them is the same figure for nothing. It used to cost a 44 ms scan
        of every unit, under every keystroke of the search field and
        every change of filter, neither of which can move it.
        """
        started = time.perf_counter()
        stats = self._repo.get_files()
        self._vstate.file_stats = {s["source_file"]: s for s in stats}
        self._update_project_progress(stats)
        matches = self._repo.count_matches_by_file(
            self._vstate.search_query,
            self._vstate.status_filter or None,
            self._vstate.character_filter,
            self._vstate.review_only,
        )
        filtering = bool(
            self._vstate.search_query.strip()
            or self._vstate.character_filter
            or self._vstate.review_only
        )
        self._file_list_col.controls.clear()
        self._file_order = []
        self._file_buttons = {}

        folders = {_split_source_path(s["source_file"])[0] for s in stats}
        self._render_folder(
            _build_folder_tree(stats, _common_root_depth(list(folders))),
            path="",
            indent=_INDENT_BASE,
            matches=matches,
            filtering=filtering,
        )
        logger.debug(
            "File panel rebuilt in %.0f ms (%d files)",
            (time.perf_counter() - started) * 1000,
            len(stats),
        )

    def _render_folder(
        self,
        node: _FolderNode,
        *,
        path: str,
        indent: int,
        matches: dict[str, int],
        filtering: bool,
    ) -> None:
        """Append a folder's subfolders, then its own files, to the panel.

        Subfolders come first at every level and each level is sorted on
        its own, the way every file browser does it.

        Args:
            node: The folder to render, the root included.
            path: Its path relative to the shared root, shown on hover so a
                nested folder can still be placed at a glance.
            indent: Left padding in pixels for the entries of this level.
            matches: Match count per file.
            filtering: Whether a search or a speaker filter is running,
                which tells a file with no match from a panel showing no
                counts at all.
        """
        for name in sorted(node.children):
            child_path = f"{path}/{name}" if path else name
            self._file_list_col.controls.append(
                self._build_folder_header(name, child_path, indent)
            )
            self._render_folder(
                node.children[name],
                path=child_path,
                indent=indent + _INDENT_STEP,
                matches=matches,
                filtering=filtering,
            )
        for entry in node.files:
            self._file_list_col.controls.append(
                self._build_file_row(
                    entry,
                    indent,
                    matches.get(entry["source_file"], 0) if filtering else None,
                )
            )

    def _build_folder_header(self, label: str, path: str, indent: int) -> ft.Container:
        """Build the non-clickable header introducing a folder group.

        Args:
            label: The folder's own name, without any parent segment.
            path: Its full path relative to the deepest shared root folder,
                shown as the tooltip.
            indent: Left padding in pixels, reflecting the folder depth.

        Returns:
            A Container with a folder icon and the folder name.
        """
        return ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.FOLDER_OUTLINED, size=12, color=TEXT_HINT),
                    ft.Text(
                        label,
                        size=11,
                        weight=ft.FontWeight.W_700,
                        color=TEXT_HINT,
                        expand=True,
                        no_wrap=True,
                        overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                ],
                spacing=5,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            tooltip=path,
            padding=ft.Padding(left=indent, right=8, top=10, bottom=2),
        )

    def _build_file_row(
        self, stats: FileStats, indent: int, matches: int | None = None
    ) -> ft.Control:
        """Build one selectable file entry of the left panel.

        The entry is registered in the panel's own order as it is built,
        which is what Alt+Up and Alt+Down walk: the control list also
        holds folder headers, and the database order is not the order the
        panel shows.

        Args:
            stats: Per-file counts as returned by get_files().
            indent: Left padding in pixels, one step past the folder header.
            matches: Units matching the running search, None when no search
                is active. A file with no match is dimmed rather than
                hidden, so the project keeps its shape under the eye.

        Returns:
            A focusable entry showing the file name and its progress.
        """
        _, fname = _split_source_path(stats["source_file"])
        total: int = int(stats["total"])
        validated: int = int(stats["validated"])
        ai_suggested: int = int(stats.get("ai_suggested", 0))
        draft: int = int(stats.get("draft", 0))
        imported: int = int(stats.get("imported", 0))
        is_done = validated == total
        is_sel = stats["source_file"] == self._vstate.selected_file

        if is_done:
            status: TranslationStatus = "human_validated"
        elif ai_suggested > 0:
            status = "ai_suggested"
        elif imported > 0:
            status = "imported"
        elif draft > 0:
            status = "draft"
        else:
            status = "not_translated"

        box = ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        fname,
                        size=13,
                        weight=(ft.FontWeight.W_600 if is_sel else ft.FontWeight.W_400),
                        color=TEXT if is_sel else TEXT_MUTED,
                        no_wrap=True,
                        overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                    ft.Row(
                        [
                            ft.Icon(
                                ft.Icons.SEARCH,
                                size=11,
                                color=ACCENT,
                                visible=bool(matches),
                            ),
                            ft.Text(
                                str(matches) if matches else "",
                                size=10,
                                color=ACCENT,
                                weight=ft.FontWeight.W_600,
                            ),
                            ft.Icon(
                                _STATUS_ICONS[status],
                                size=11,
                                color=_STATUS_COLORS[status],
                                semantics_label=i18n.t(_STATUS_LABEL_KEYS[status]),
                            ),
                            ft.Text(
                                f"{validated}/{total}",
                                size=11,
                                color=SUCCESS if is_done else TEXT_HINT,
                            ),
                            self._build_count_badge(
                                "ai_suggested",
                                ai_suggested,
                                i18n.t("review.ai_suggested_badge"),
                            ),
                            self._build_count_badge(
                                "imported",
                                imported,
                                i18n.t("review.imported_badge"),
                            ),
                            self._build_count_badge(
                                "draft", draft, i18n.t("review.draft_badge")
                            ),
                        ],
                        spacing=5,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                spacing=3,
                tight=True,
            ),
            opacity=0.35 if matches == 0 else 1.0,
            bgcolor=BG_FILE_SEL if is_sel else "transparent",
            border_radius=6,
            padding=ft.Padding(left=indent, right=10, top=8, bottom=8),
            ink=True,
        )
        source_file = stats["source_file"]
        button = focusable(
            box,
            on_click=lambda _e: self._select_file(source_file),
            tooltip=source_file,
            radius=6,
            expand=True,
            on_focus=partial(self._on_file_focused, source_file),
            on_blur=partial(self._on_file_blurred, source_file),
        )
        self._file_order.append(source_file)
        self._file_buttons[source_file] = button
        return self._file_menu(source_file, button)

    def _on_file_focused(self, source_file: str, _e: Any) -> None:
        """Remember which file entry the keyboard is sitting on.

        Args:
            source_file: The file whose entry took the focus.
            _e: Unused focus event.
        """
        self._focused_file = source_file

    def _on_file_blurred(self, source_file: str, _e: Any) -> None:
        """Forget the focused file, unless another entry already took over.

        Blur is not guaranteed to arrive before the next entry's focus,
        so clearing unconditionally would wipe the entry that just took
        the focus and send the menu back to the open file.

        Args:
            source_file: The file whose entry lost the focus.
            _e: Unused blur event.
        """
        if self._focused_file == source_file:
            self._focused_file = None

    def _file_menu(self, source_file: str, row: ft.Control) -> ft.ContextMenu:
        """Return this file's context menu, created once and kept alive.

        The menu outlives the row it wraps, and that is the whole point.
        A ContextMenu built by a panel refresh answers no method call: the
        client binds no listener to the replacement, so open() ends on a
        ten second timeout while the right button, handled entirely on the
        Flutter side, keeps working. Every refresh therefore swaps the row
        inside the menu rather than the menu around the row.

        The panel is rebuilt on every keystroke of the search field, so
        this also stops six menu entries per file from being rebuilt each
        time.

        Args:
            source_file: The file the menu acts on, and its key here.
            row: The freshly built entry the menu has to wrap now.

        Returns:
            The menu for that file, holding the given row.
        """
        menu = self._file_menus.get(source_file)
        if menu is None:
            menu = ft.ContextMenu(
                content=row,
                items=self._file_menu_items(source_file),
                secondary_items=self._file_menu_items(source_file),
            )
            self._file_menus[source_file] = menu
        else:
            menu.content = row
        return menu

    def _file_menu_items(self, source_file: str) -> list[ft.PopupMenuItem]:
        """Build the six actions offered on one file of the panel.

        Built fresh on each call rather than shared: a control belongs to
        a single parent, and the menu declares its entries twice, once for
        the right button and once for what open() raises.

        The last three lead to the dialogs the toolbar already opens, with
        the file selected first and pinned as their scope. They keep their
        own confirmation, which is what a clear reachable from a
        right-click needs most.

        Args:
            source_file: The file the actions apply to, as stored in the
                database, which is its absolute path on disk.

        Returns:
            The menu entries, in the order they are shown.
        """
        return [
            ft.PopupMenuItem(
                content=i18n.t("review.file_menu_open"),
                icon=ft.Icons.SUBJECT,
                on_click=lambda _e: self._select_file(source_file),
            ),
            ft.PopupMenuItem(
                content=i18n.t("review.file_menu_copy_path"),
                icon=ft.Icons.CONTENT_COPY_OUTLINED,
                on_click=partial(self._copy_file_path, source_file),
            ),
            ft.PopupMenuItem(
                content=i18n.t("review.file_menu_reveal"),
                icon=ft.Icons.FOLDER_OPEN_OUTLINED,
                on_click=lambda _e: self._reveal_file(source_file),
            ),
            ft.PopupMenuItem(
                content=i18n.t("review.file_menu_translate"),
                icon=ft.Icons.AUTO_AWESOME,
                on_click=lambda _e: self._translate_file(source_file),
            ),
            ft.PopupMenuItem(
                content=i18n.t("review.file_menu_interchange"),
                icon=ft.Icons.IMPORT_EXPORT,
                on_click=lambda _e: self._interchange_file(source_file),
            ),
            ft.PopupMenuItem(
                content=i18n.t("review.file_menu_clear"),
                icon=ft.Icons.DELETE_SWEEP_OUTLINED,
                on_click=lambda _e: self._clear_file(source_file),
            ),
        ]

    def _copy_file_path(self, source_file: str, _e: Any) -> None:
        """Put the file's path on the clipboard.

        The clipboard service is a coroutine, handed to the page rather
        than awaited, so this handler keeps the plain signature every menu
        entry has.

        Args:
            source_file: The path stored for this file.
            _e: Unused click event.
        """
        self._page.run_task(ft.Clipboard().set, source_file)
        self._show_status(i18n.t("review.file_menu_copied"), SUCCESS)

    def _reveal_file(self, source_file: str) -> None:
        """Open the desktop file manager on this file.

        Starting a file manager blocks for as long as the desktop takes
        to answer, so it goes to a background thread like every other
        call that leaves the application.

        Args:
            source_file: The path stored for this file.
        """
        self._page.run_thread(self._run_reveal, source_file)

    def _run_reveal(self, source_file: str) -> None:
        """Reveal a file, reporting a failure as a toast.

        Args:
            source_file: The path stored for this file.
        """
        try:
            reveal_in_file_manager(Path(source_file))
        except RevealError:
            self._show_status(i18n.t("review.file_menu_reveal_failed"), ERROR)

    def _translate_file(self, source_file: str) -> None:
        """Open the translation dialog, pinned to one file.

        Args:
            source_file: The file to translate.
        """
        self._select_file(source_file)
        self._start_translate_flow(source_file)

    def _interchange_file(self, source_file: str) -> None:
        """Open the bilingual file dialog, pinned to one file.

        Args:
            source_file: The file to export or import.
        """
        self._select_file(source_file)
        self._open_interchange_dialog(source_file)

    def _clear_file(self, source_file: str) -> None:
        """Open the clear dialog, pinned to one file.

        Args:
            source_file: The file whose translations are up for clearing.
        """
        self._select_file(source_file)
        self._open_clear_dialog(source_file)

    def _scope_control(self, dropdown: ft.Dropdown) -> ft.Control:
        """Return the scope chooser, or the file the dialog is pinned to.

        A dialog reached from a file's own menu has already been told
        which file it acts on, so offering to widen it to the whole
        project turns one right-click into a project-wide clear. The
        chooser is replaced by the file's name rather than merely preset
        to it: the question is answered, not asked again.

        Args:
            dropdown: The scope chooser shown when the dialog is opened
                from the toolbar.

        Returns:
            That dropdown, or a line naming the pinned file.
        """
        if self._menu_file is None:
            return dropdown
        _, name = _split_source_path(self._menu_file)
        return ft.Row(
            [
                ft.Icon(ft.Icons.DESCRIPTION_OUTLINED, size=15, color=TEXT_HINT),
                ft.Text(name, size=13, color=TEXT, expand=True, no_wrap=True),
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _dialog_scope(
        self, dropdown: ft.Dropdown, default: str
    ) -> tuple[str, str | None]:
        """Return the scope a dialog runs with, and the file it acts on.

        A pinned file wins over the chooser, which _scope_control() has
        replaced with that file's name anyway. Both are returned together
        so no caller can read one from the pin and the other from a
        dropdown still holding what the last toolbar run left in it.

        Args:
            dropdown: The scope chooser, ignored when a file is pinned.
            default: The scope assumed when the chooser holds nothing.

        Returns:
            Tuple of (scope, file to act on). The file is None when the
            scope is the whole project.
        """
        if self._menu_file is not None:
            return "file", self._menu_file
        scope = dropdown.value or default
        return scope, (self._vstate.selected_file if scope == "file" else None)

    @staticmethod
    def _build_count_badge(
        status: TranslationStatus, count: int, label: str
    ) -> ft.Control:
        """Build one per-file count badge of the left panel.

        Each status carries its own icon, so the badges stay apart for a
        reader who cannot tell their colors from one another.

        Args:
            status: The status being counted.
            count: How many units hold it in this file.
            label: The badge text, still holding its "{n}" placeholder.

        Returns:
            The badge, or an invisible placeholder when the count is zero.
        """
        if not count:
            return ft.Container(visible=False)
        color = _STATUS_COLORS[status]
        return ft.Row(
            [
                ft.Icon(_STATUS_ICONS[status], size=10, color=color),
                ft.Text(label.format(n=count), size=10, color=color),
            ],
            spacing=2,
            tight=True,
        )

    @staticmethod
    def _status_filter_option(status: TranslationStatus) -> ft.dropdown.Option:
        """Build one status entry of the filter menu, glyph included.

        The list carries the same icons as the rows it filters, so the
        menu and the lines it selects can be matched without reading
        either, and so the status is not left to the color alone.

        Args:
            status: The status this entry selects.

        Returns:
            The dropdown option for that status.
        """
        return ft.dropdown.Option(
            key=status,
            text=i18n.t(_STATUS_LABEL_KEYS[status]),
            leading_icon=ft.Icon(
                _STATUS_ICONS[status], size=14, color=_STATUS_COLORS[status]
            ),
        )

    @staticmethod
    def _build_status_icon(status: TranslationStatus) -> ft.Icon:
        """Build the status indicator shown at the head of a translation row.

        Status is carried by the glyph as much as by the color, and named
        in a label screen readers can reach, since a colored dot alone
        leaves the information out of reach.

        Args:
            status: The unit's current status.

        Returns:
            The icon control, kept around so the row can update it in place.
        """
        label = i18n.t(_STATUS_LABEL_KEYS[status])
        return ft.Icon(
            _STATUS_ICONS[status],
            size=15,
            color=_STATUS_COLORS[status],
            tooltip=label,
            semantics_label=label,
        )

    def _select_file(self, source_file: str) -> None:
        """Switch to a file and reset pagination to page 0.

        The speaker filter is left alone, the way the search field is: it
        belongs to the project, not to the file, and the panel is what
        told the user this file had lines for that speaker.

        Args:
            source_file: The source_file value as stored in the DB.
        """
        self._flush_pending_edit()
        self._vstate.selected_file = source_file
        self._vstate.current_page = 0
        self._load_files()
        self._load_page(scroll_to_top=True)
        self._safe_update()

    # ── Chargement page de blocs ──────────────────────────────────────────── #

    def _load_page(self, *, scroll_to_top: bool = False) -> None:
        """Load the current page of blocks and rebuild the block list.

        The rows, the focused index and the editing flag are dropped up
        front: they point at controls this rebuild is about to replace,
        and a keyboard shortcut landing on a stale index would edit
        whichever line took that spot. The flag has to go with them since
        a destroyed field never sends its blur event, and a flag stuck on
        would suppress every later refresh. A caller that means to keep
        the focus (validating from the keyboard) sets both again once the
        new rows exist.

        A page number pointing past the end falls back to the last page
        rather than showing an empty list. The number outlives the view,
        so it can come back to a project whose lines were translated
        elsewhere in the meantime, and "no result" on page forty of a
        file that now has three is not something to page out of by hand.

        Args:
            scroll_to_top: Whether to put the list back at its first
                line. Asked for by the moves that change what the list
                shows, never by a refresh happening under the reader: a
                translation job rebuilds this every chunk, and yanking
                the page up under someone reading it is worse than the
                stale row it was refreshing.
        """
        started = time.perf_counter()
        self._rows = []
        self._focused_row = None
        self._editing = False
        self._characters = {
            character.variable: character.display_name
            for character in self._character_repo.get_all()
        }
        self._update_sync_indicator()
        if not self._vstate.selected_file:
            self._block_list_col.controls = [
                ft.Container(
                    content=ft.Text(
                        i18n.t("review.no_file_selected"),
                        color=TEXT_HINT,
                        size=13,
                    ),
                    padding=ft.Padding(left=20, right=20, top=20, bottom=20),
                )
            ]
            self._pagination_row.controls.clear()
            return

        units, total = self._fetch_page()
        last_page = max(0, -(-total // _PAGE_SIZE) - 1)
        if not units and self._vstate.current_page > last_page:
            self._vstate.current_page = last_page
            units, total = self._fetch_page()
        self._vstate.current_units = units
        self._vstate.total_units = total

        self._update_counter()

        if not units:
            self._block_list_col.controls = [
                ft.Container(
                    content=ft.Text(
                        i18n.t("review.no_results"),
                        color=TEXT_HINT,
                        size=13,
                    ),
                    padding=ft.Padding(left=20, right=20, top=20, bottom=20),
                )
            ]
        else:
            duplicates = self._repo.count_duplicates(
                [u.source_text for u in units], self._vstate.selected_file
            )
            self._block_list_col.controls = [
                self._build_unit_row(u, duplicates.get(u.source_text)) for u in units
            ]

        total_pages = max(1, -(-total // _PAGE_SIZE))
        self._build_pagination(total_pages)
        if scroll_to_top:
            self._scroll_blocks_to_top()
        logger.debug(
            "Block list rebuilt in %.0f ms (%d rows of %d)",
            (time.perf_counter() - started) * 1000,
            len(units),
            total,
        )

    def _scroll_blocks_to_top(self) -> None:
        """Put the block list back at its first line.

        Replacing the controls of a scrollable column does not move it:
        opening a file or turning a page from halfway down a long one
        landed on the bottom of the new list, which reads as a page that
        did not change. Scheduled rather than awaited, since the caller
        is not always in a coroutine and the scroll is a round trip to
        the client.
        """
        self._page.run_task(self._block_list_col.scroll_to, 0)

    def _fetch_page(self) -> tuple[list[TranslationUnit], int]:
        """Read the page the current filters and page number point at.

        Returns:
            Tuple of (units for this page, total matching row count).
            Empty when no file is open.
        """
        selected = self._vstate.selected_file
        if selected is None:
            return [], 0
        if self._vstate.errors_only:
            return self._load_error_page(selected)
        return self._repo.get_page(
            source_file=selected,
            page=self._vstate.current_page,
            page_size=_PAGE_SIZE,
            status_filter=self._vstate.status_filter or None,
            search_query=self._vstate.search_query,
            character=self._vstate.character_filter,
            needs_review=self._vstate.review_only,
        )

    def _load_error_page(self, source_file: str) -> tuple[list[TranslationUnit], int]:
        """Page through the lines the quality checks refuse to validate.

        Only blocking issues count, the ones _validate_unit() turns down:
        a lost {i} tag or a dropped [variable] breaks the game, where a
        translation merely running long is a suspicion nobody has to hunt
        down. That is what makes the filter mean "lines in error" rather
        than "lines worth a second look".

        An error weighs the source against the translation, which no query
        can do, so the file is read whole, filtered in Python and sliced
        here rather than by SQL. This is the one filter that costs the
        whole open file on every page load, and the search box is not
        debounced, so a long script pays a full quality pass per keystroke
        while this filter is on. Only the open file is scanned, and only
        its translated lines are checked, which is what keeps it bearable.

        Args:
            source_file: The file the review is showing.

        Returns:
            Tuple of (units for this page, total matching row count).
        """
        matching = [
            unit
            for unit in self._repo.get_matching(
                source_file,
                self._vstate.status_filter or None,
                self._vstate.search_query,
                self._vstate.character_filter,
                self._vstate.review_only,
            )
            if unit.translated_text and _has_blocking_issue(unit)
        ]
        start = self._vstate.current_page * _PAGE_SIZE
        return matching[start : start + _PAGE_SIZE], len(matching)

    def _build_unit_row(
        self, unit: TranslationUnit, duplicates: DuplicateStats | None = None
    ) -> ft.Control:
        """Build one translation row.

        Layout (same widths as _build_table_header):
          [_COL_STATUS] [expand] [expand] [_COL_ACTIONS]

        Args:
            unit: The unit to display.
            duplicates: Occurrence counts for this unit's source text, None
                when the text is unique in the project.

        Returns:
            A styled Container for one row.
        """
        status_icon = self._build_status_icon(unit.status)

        field = ft.TextField(
            value=unit.translated_text,
            hint_text="...",
            hint_style=ft.TextStyle(color=TEXT_HINT),
            bgcolor=BG_INPUT,
            border_color=BORDER_COLOR,
            focused_border_color=FOCUS_RING,
            focused_border_width=FOCUS_RING_WIDTH,
            border_radius=8,
            color=TEXT,
            cursor_color=ACCENT,
            expand=True,
            multiline=True,
            min_lines=1,
            max_lines=4,
            content_padding=ft.Padding(left=10, right=10, top=8, bottom=8),
        )

        warning_text = ft.Text("", size=11, color=WARNING, visible=False)
        self._refresh_warning(warning_text, unit.source_text, unit.translated_text)

        review_icon = self._build_review_icon(unit.needs_review)
        note_field = ft.TextField(
            value=unit.note or "",
            hint_text=i18n.t("review.note_hint"),
            hint_style=ft.TextStyle(color=TEXT_HINT),
            bgcolor=BG_INPUT,
            border_color=BORDER_COLOR,
            focused_border_color=FOCUS_RING,
            focused_border_width=FOCUS_RING_WIDTH,
            border_radius=8,
            color=TEXT_MUTED,
            cursor_color=ACCENT,
            text_size=12.5,
            expand=True,
            multiline=True,
            min_lines=2,
            max_lines=4,
            content_padding=ft.Padding(left=10, right=10, top=8, bottom=8),
        )
        note_box = self._build_note_box(note_field, visible=unit.needs_review)

        row = _Row(
            unit, field, status_icon, warning_text, review_icon, note_field, note_box
        )
        index = len(self._rows)
        self._rows.append(row)

        note_on_focus = unit.note or ""

        def _on_note_changed(e: Event[ft.TextField]) -> None:
            self._store_note(row, e.control.value or "")

        def _on_note_focus(_e: Any) -> None:
            """Remember what the note held before this visit."""
            nonlocal note_on_focus
            note_on_focus = note_field.value or ""

        def _on_note_blur(_e: Any) -> None:
            """Confirm a note that changed, once the caret has left it.

            The note is already written, on every keystroke, so nothing
            here saves anything: it says so. Reporting each keystroke
            would put a toast under every letter, and reporting a field
            merely crossed would report nothing at all.
            """
            if (note_field.value or "") == note_on_focus:
                return
            self._show_status(i18n.t("review.note_saved"), SUCCESS)

        note_field.on_change = _on_note_changed
        note_field.on_focus = _on_note_focus
        note_field.on_blur = _on_note_blur

        context_col = ft.Column([], spacing=3, tight=True, visible=False)

        def _on_toggle_context(_e: Any) -> None:
            self._toggle_context(unit, context_col)

        def _on_validate(_e: Any) -> None:
            self._validate_unit(row)

        def _on_field_changed(e: Event[ft.TextField]) -> None:
            self._schedule_edit(row, e.control.value or "")

        def _on_clear_field(_e: Any) -> None:
            self._set_row_text(row, "")

        def _on_copy_source(_e: Any) -> None:
            self._set_row_text(row, unit.source_text)

        def _on_field_focused(_e: Any) -> None:
            self._focused_row = index
            self._editing = True

        def _on_field_blurred(_e: Any) -> None:
            self._editing = False
            self._flush_pending_edit()

        field.on_submit = _on_validate
        field.on_change = _on_field_changed
        field.on_focus = _on_field_focused
        field.on_blur = _on_field_blurred

        is_translating = unit.block_id in self._translating_units

        def _on_translate_unit(_e: Any) -> None:
            if unit.block_id in self._translating_units:
                return
            self._translate_single_unit(unit)

        translate_unit_btn = self._row_action(
            ft.Icons.HOURGLASS_TOP if is_translating else ft.Icons.TRANSLATE,
            i18n.t("review.translate_unit_tooltip"),
            _on_translate_unit,
        )
        validate_btn = self._row_action(
            ft.Icons.CHECK, i18n.t("review.validate"), _on_validate
        )
        copy_source_btn = self._row_action(
            ft.Icons.EAST, i18n.t("review.copy_source"), _on_copy_source
        )
        clear_field_btn = self._row_action(
            ft.Icons.BACKSPACE_OUTLINED, i18n.t("review.clear_field"), _on_clear_field
        )
        review_btn = focusable(
            ft.Container(
                content=review_icon,
                width=_COL_ACTION,
                height=_ROW_ACTION_HEIGHT,
                alignment=ft.Alignment(0, 0),
                border_radius=8,
                ink=True,
            ),
            on_click=lambda _e: self._toggle_review(row),
            tooltip=i18n.t("review.needs_review_tooltip"),
            width=_COL_ACTION,
            height=_ROW_ACTION_HEIGHT,
        )

        main_row = ft.Row(
            [
                ft.Container(
                    content=status_icon,
                    width=_COL_STATUS,
                    alignment=ft.Alignment(0, 0),
                ),
                ft.Column(
                    [
                        self._build_speaker_label(unit.character_variable),
                        ft.Row(
                            [
                                ft.Text(
                                    unit.source_text,
                                    expand=True,
                                    size=13,
                                    color=TEXT,
                                    selectable=True,
                                    no_wrap=False,
                                ),
                                self._build_duplicate_marker(row, duplicates),
                                focusable(
                                    ft.Container(
                                        content=ft.Icon(
                                            ft.Icons.UNFOLD_MORE,
                                            size=13,
                                            color=TEXT_HINT,
                                        ),
                                        width=22,
                                        height=22,
                                        alignment=ft.Alignment(0, 0),
                                        border_radius=6,
                                        ink=True,
                                    ),
                                    on_click=_on_toggle_context,
                                    tooltip=i18n.t("review.context_tooltip"),
                                    radius=6,
                                    width=22,
                                    height=22,
                                ),
                            ],
                            spacing=6,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                    ],
                    expand=True,
                    spacing=2,
                    tight=True,
                ),
                field,
                translate_unit_btn,
                copy_source_btn,
                clear_field_btn,
                review_btn,
                validate_btn,
            ],
            spacing=_ROW_SPACING,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        return ft.Container(
            content=ft.Column(
                [
                    main_row,
                    ft.Container(
                        content=warning_text,
                        padding=ft.Padding(
                            left=_COL_STATUS + _ROW_SPACING, right=0, top=0, bottom=0
                        ),
                    ),
                    ft.Row(
                        [
                            ft.Container(width=_COL_STATUS),
                            ft.Container(content=context_col, expand=True),
                            ft.Container(content=note_box, expand=True),
                            ft.Container(width=_COL_ACTIONS),
                        ],
                        spacing=_ROW_SPACING,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                    ),
                ],
                spacing=4,
                tight=True,
            ),
            padding=ft.Padding(left=12, right=8, top=8, bottom=8),
            border=ft.Border(bottom=ft.BorderSide(1, "#1e1d27")),
        )

    def _build_duplicate_marker(
        self, row: _Row, duplicates: DuplicateStats | None
    ) -> ft.Control:
        """Build the badge telling that a source text occurs elsewhere.

        Accented when some occurrences live in other files, since the list
        only ever shows one file at a time: those are the ones no amount of
        scrolling would reveal.

        The badge is also the way back to spreading a translation over
        those lines. The offer otherwise lives in a toast that a translator
        meets once, seconds after validating, and never again.

        Args:
            row: The row the badge belongs to, acted on when it is clicked.
            duplicates: Occurrence counts for the text, None when unique.

        Returns:
            The badge, or an invisible placeholder when the text is unique.
        """
        if duplicates is None:
            return ft.Container(visible=False)

        elsewhere = duplicates["other_files"]
        here = duplicates["total"] - 1 - elsewhere
        counts = (
            i18n.t("review.duplicates_split_tooltip").format(
                here=here, elsewhere=elsewhere
            )
            if elsewhere
            else i18n.t("review.duplicates_here_tooltip").format(here=here)
        )
        color = ACCENT if elsewhere else TEXT_HINT
        counts_tooltip = f"{counts} {i18n.t('review.duplicates_badge_action')}"
        return focusable(
            ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.CONTENT_COPY, size=11, color=color),
                        ft.Text(str(duplicates["total"] - 1), size=11, color=color),
                    ],
                    spacing=3,
                    tight=True,
                ),
                ink=True,
                border_radius=6,
                padding=ft.Padding(left=4, right=4, top=2, bottom=2),
            ),
            on_click=lambda _e: self._spread_to_duplicates(row),
            tooltip=counts_tooltip,
            radius=6,
        )

    def _spread_to_duplicates(self, row: _Row) -> None:
        """Validate a row, then hand its translation to every identical line.

        Validating first is what makes this safe: the quality checks run on
        the text before it is copied anywhere, and a line that fails them
        spreads nothing. Lines already validated by a human are left out by
        find_duplicate_block_ids().

        It also has to come before the count, or the click does nothing at
        all on a line whose duplicates are all validated already: the badge
        counts every occurrence, so it still reads 2 there, and returning
        early on an empty list would leave even the clicked line unvalidated.

        Args:
            row: The row whose translation is spread.
        """
        self._flush_pending_edit()
        translated = (row.field.value or "").strip()
        if not translated:
            self._show_row_error(row.warning, i18n.t("review.error_empty"))
            return

        source_text = row.unit.source_text
        block_id = row.unit.block_id
        if not self._validate_unit(row):
            return

        block_ids = self._repo.find_duplicate_block_ids(source_text, block_id)
        if not block_ids:
            self._show_status(i18n.t("review.duplicates_none"), WARNING)
            self._safe_update()
            return

        self._validate_duplicates(block_ids, translated)
        self._show_status(
            i18n.t("review.duplicates_done").format(n=len(block_ids)), SUCCESS
        )
        self._safe_update()

    def _spread_focused_row_to_duplicates(self) -> None:
        """Spread the translation of the row being edited to its duplicates."""
        row = self._focused_row_or_none()
        if row is not None:
            self._spread_to_duplicates(row)

    def _toggle_context(self, unit: TranslationUnit, holder: ft.Column) -> None:
        """Show or hide the lines surrounding a unit in its file.

        The neighbours are read on the first opening only: they do not
        change under a review, and a query per displayed row would be paid
        by every page load for a panel almost always closed.

        Args:
            unit: The unit whose neighbours are wanted.
            holder: The column the context lines are rendered into.
        """
        if not holder.controls:
            neighbours = self._repo.get_neighbours(
                unit.source_file, unit.source_line, _CONTEXT_RADIUS
            )
            holder.controls = [
                self._build_context_line(
                    neighbour, current=neighbour.block_id == unit.block_id
                )
                for neighbour in neighbours
            ] or [ft.Text(i18n.t("review.context_empty"), size=11, color=TEXT_HINT)]
        holder.visible = not holder.visible
        self._safe_update()

    def _build_context_line(
        self, unit: TranslationUnit, *, current: bool
    ) -> ft.Control:
        """Build one neighbouring line, sized to the panel's own column.

        The line being reviewed is rendered among its neighbours rather
        than left out, and marked. Without it the panel is a list with no
        anchor: five lines under a row read as the five that follow it,
        when two of them come before.

        The panel shares a row with the note, so it lives inside the
        source column rather than across the whole table. The marker sits
        in a gutter of its own width so the lines stay flush with one
        another whichever of them is the current one.

        Args:
            unit: The neighbouring unit to show.
            current: Whether this is the line the panel was opened from.

        Returns:
            A Row pairing the neighbour's source with its translation.
        """
        variable = unit.character_variable
        speaker = self._characters.get(variable, variable) if variable else ""
        color = TEXT if current else TEXT_HINT
        return ft.Row(
            [
                ft.Container(
                    content=ft.Icon(
                        ft.Icons.ARROW_RIGHT,
                        size=13,
                        color=ACCENT,
                        semantics_label=i18n.t("review.context_current"),
                        tooltip=i18n.t("review.context_current"),
                        visible=current,
                    ),
                    width=_CONTEXT_MARKER,
                    alignment=ft.Alignment(1, 0),
                ),
                ft.Text(
                    f"{speaker}: {unit.source_text}" if speaker else unit.source_text,
                    size=11.5,
                    color=color,
                    weight=ft.FontWeight.W_600 if current else ft.FontWeight.W_400,
                    expand=True,
                ),
                ft.Text(
                    unit.translated_text,
                    size=11.5,
                    color=TEXT_HINT,
                    expand=True,
                ),
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )

    def _build_speaker_label(self, variable: str | None) -> ft.Control:
        """Build the line naming who speaks the source text.

        Knowing the speaker is what settles gender, register and address
        in the target language, so it is shown above the line rather than
        left in the payload sent to the providers. The glossary display
        name is preferred, the Ren'Py variable standing in until a
        character is named there.

        Args:
            variable: The unit's character variable, None for narration.

        Returns:
            The speaker line, or an invisible placeholder for narration.
        """
        if not variable:
            return ft.Container(visible=False)
        return ft.Text(
            self._characters.get(variable, variable),
            size=11,
            weight=ft.FontWeight.W_600,
            color=TEXT_MUTED,
        )

    @staticmethod
    def _build_note_box(note_field: ft.TextField, *, visible: bool) -> ft.Container:
        """Wrap a note in the frame that ties it to its translation.

        Args:
            note_field: The editable note itself.
            visible: Whether the line is currently flagged.

        Returns:
            The framed note, hidden until the line is flagged.
        """
        return ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.FLAG, size=13, color=WARNING),
                    note_field,
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.START,
            ),
            border=ft.Border(left=ft.BorderSide(2, WARNING)),
            padding=ft.Padding(left=8, right=0, top=2, bottom=2),
            visible=visible,
        )

    @staticmethod
    def _build_review_icon(needs_review: bool) -> ft.Icon:
        """Build the flag telling a line was set aside for a second look.

        Like the status glyph, the mark is carried by the shape as much as
        by the color, and named in a label screen readers can reach.

        Args:
            needs_review: Whether the line is currently flagged.

        Returns:
            The icon control, kept around so the row can toggle it in place.
        """
        icon = ft.Icon(ft.Icons.OUTLINED_FLAG, size=14)
        ReviewView._apply_review_flag(icon, needs_review)
        return icon

    @staticmethod
    def _apply_review_flag(icon: ft.Icon, needs_review: bool) -> None:
        """Move a row's review flag to the other state, in place.

        Args:
            icon: The flag built by _build_review_icon().
            needs_review: The state it must now show.
        """
        icon.icon = ft.Icons.FLAG if needs_review else ft.Icons.OUTLINED_FLAG
        icon.color = WARNING if needs_review else TEXT_HINT
        icon.semantics_label = i18n.t(
            "review.needs_review_on" if needs_review else "review.needs_review_off"
        )

    def _toggle_review(self, row: _Row) -> None:
        """Raise or clear the review flag of a row, note included.

        The note says why a line was set aside, so it lives and dies with
        the flag. Nothing lists the notes on their own: one left on an
        unflagged line would be findable only by whoever remembered which
        line carried it, which is no better than not keeping it.

        The list itself is left alone: unflagging a line under the review
        filter would make it vanish from under the eyes of whoever just
        decided it was fine. It leaves on the next page load, like a line
        that stops being in error under the error filter. Only the file
        panel is refreshed, and only when it is counting flagged lines.

        Args:
            row: The row whose flag is toggled.
        """
        if row.unit.needs_review and row.unit.note:
            self._page.show_dialog(self._build_drop_note_dialog(row))
            return
        self._apply_toggle_review(row)

    def _build_drop_note_dialog(self, row: _Row) -> ft.AlertDialog:
        """Ask before unflagging a line whose note would go with it.

        The note is a sentence somebody typed and nothing else holds it,
        so it is the one half of the pair worth stopping for. Raising the
        flag, and lowering it on a line with no note, stay immediate.

        Args:
            row: The row whose flag is about to come down.

        Returns:
            An AlertDialog asking the user to confirm losing the note.
        """

        def _confirm(_e: Any) -> None:
            self._page.pop_dialog()
            self._apply_toggle_review(row)

        return ft.AlertDialog(
            modal=True,
            bgcolor="#1a1822",
            title=ft.Text(
                i18n.t("review.drop_note_title"),
                size=18,
                weight=ft.FontWeight.W_600,
                color=TEXT_H,
            ),
            content=ft.Text(
                i18n.t("review.drop_note_message").format(note=row.unit.note),
                size=13.5,
                color=TEXT_MUTED,
                width=320,
            ),
            actions=[
                dialog_action(
                    i18n.t("common.cancel"),
                    lambda _e: self._page.pop_dialog(),
                ),
                dialog_action(
                    i18n.t("review.drop_note_action"),
                    _confirm,
                    tone="danger",
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

    def _apply_toggle_review(self, row: _Row) -> None:
        """Flip a row's review flag, dropping its note when it comes down.

        Args:
            row: The row whose flag is toggled.
        """
        unit = row.unit
        unit.needs_review = not unit.needs_review
        self._repo.set_needs_review(unit.block_id, unit.needs_review)
        self._apply_review_flag(row.review_icon, unit.needs_review)
        row.note_box.visible = unit.needs_review
        if not unit.needs_review and unit.note:
            unit.note = None
            row.note.value = ""
            self._repo.set_note(unit.block_id, "")

        if self._vstate.review_only:
            self._load_files()
        self._safe_update()

    def _toggle_focused_row_review(self) -> None:
        """Toggle the review flag of the row being edited."""
        row = self._focused_row_or_none()
        if row is not None:
            self._toggle_review(row)

    def _store_note(self, row: _Row, note: str) -> None:
        """Write a line's note as it is typed, flagging the line with it.

        Written on every keystroke, unlike the translation field: a note
        is left on the rare line somebody stumbles on, it changes no
        status and rebuilds nothing, so there is no rebuild to spare and
        nothing can be lost by leaving the view at the wrong moment.

        Args:
            row: The row the note belongs to.
            note: The note field's current value.
        """
        row.unit.note = note or None
        self._repo.set_note(row.unit.block_id, note)

    @staticmethod
    def _apply_status(icon: ft.Icon, status: TranslationStatus) -> None:
        """Move a row's status indicator to another status, in place.

        Args:
            icon: The indicator built by _build_status_icon().
            status: The status it must now show.
        """
        label = i18n.t(_STATUS_LABEL_KEYS[status])
        icon.icon = _STATUS_ICONS[status]
        icon.color = _STATUS_COLORS[status]
        icon.tooltip = label
        icon.semantics_label = label

    @staticmethod
    def _refresh_warning(warning: ft.Text, source_text: str, translated: str) -> None:
        """Show the quality issues of a translation on its own row.

        The message lives where the eye already is and stays there as long
        as the issue does, rather than vanishing on the next keystroke.

        Args:
            warning: The row's warning line.
            source_text: Text the translation must stay faithful to.
            translated: The translation to check, possibly empty.
        """
        issues = quality_check(source_text, translated) if translated else []
        warning.value = "; ".join(issue.detail for issue in issues)
        warning.color = WARNING
        warning.visible = bool(issues)

    def _set_row_text(self, row: _Row, text: str) -> None:
        """Replace a row's translation with a text the user did not type.

        Args:
            row: The row to fill.
            text: The new translation, empty to clear the field.
        """
        row.field.value = text
        self._schedule_edit(row, text)
        self._safe_update()

    def _schedule_edit(self, row: _Row, new_value: str) -> None:
        """Hold a live edit for a moment before writing it to the database.

        Writing on every keystroke means one commit per character, and a
        rebuild of the whole file panel whenever the status flips: both are
        felt on a large project. Waiting for a short pause in the typing
        costs nothing the user can observe: leaving the field, the line,
        the page or the view all flush first, so the value is on disk
        before anything can read it back. Only killing the window between
        the last keystroke and the timer loses it.

        Args:
            row: The row being edited, refreshed once written.
            new_value: The field's current value.
        """
        if (
            self._pending_edit is not None
            and self._pending_edit.row.unit.block_id != row.unit.block_id
        ):
            self._flush_pending_edit()
        self._pending_edit = _PendingEdit(row, new_value)
        if self._edit_timer is not None:
            self._edit_timer.cancel()
        self._edit_timer = threading.Timer(
            _EDIT_DEBOUNCE, self._on_ui_thread(self._flush_pending_edit)
        )
        self._edit_timer.daemon = True
        self._edit_timer.start()

    def _flush_pending_edit(self) -> None:
        """Write the held edit, dropping a stale ai_suggested/human_validated flag.

        A stored translation is only trustworthy as long as it matches what
        a human or the AI actually produced. As soon as the field diverges
        from that, the unit drops its flag: non-empty text becomes a draft,
        an emptied field falls back to not_translated.

        Runs on the event loop thread, either from the debounce timer or
        from any handler about to move away from the edited row.
        """
        if self._edit_timer is not None:
            self._edit_timer.cancel()
            self._edit_timer = None
        pending = self._pending_edit
        self._pending_edit = None
        if pending is None:
            return

        unit = pending.row.unit
        self._refresh_warning(pending.row.warning, unit.source_text, pending.value)
        if pending.value != unit.translated_text:
            new_status = self._repo.mark_as_draft(unit.block_id, pending.value)
            unit.translated_text = pending.value
            if unit.status != new_status:
                unit.status = new_status
                self._apply_status(pending.row.status_icon, new_status)
                self._load_files()
            self._update_sync_indicator()
        self._safe_update()

    # ── Validation ────────────────────────────────────────────────────────── #

    def _validate_unit(self, row: _Row) -> bool:
        """Run quality checks and persist the translation to the DB.

        Blocks on missing tags/vars, warns on length. What blocks is
        reported on the row itself, since that is where the text to fix
        is. On success, rebuilds the page and updates the file panel counts.

        Args:
            row: The row being validated.

        Returns:
            True when the translation was stored, False when an issue
            keeps it from being validated.
        """
        self._flush_pending_edit()
        unit = row.unit
        translated = (row.field.value or "").strip()

        if not translated:
            self._show_row_error(row.warning, i18n.t("review.error_empty"))
            return False

        issues = quality_check(unit.source_text, translated)
        blocking = [i for i in issues if i.kind != LENGTH_WARNING_KIND]
        warnings = [i for i in issues if i.kind == LENGTH_WARNING_KIND]

        if blocking:
            self._show_row_error(row.warning, blocking[0].detail)
            return False

        self._repo.update_translation(unit.block_id, translated, "human_validated")
        self._remember_in_background(unit.source_text, translated)
        self._announce_validation(
            warnings[0].detail if warnings else None,
            self._repo.find_duplicate_block_ids(unit.source_text, unit.block_id),
            translated,
        )

        self._load_page()
        self._load_files()
        self._safe_update()
        return True

    def _remember_in_background(self, source_text: str, translated: str) -> None:
        """Hand a validated pair to the machine-wide translation memory.

        Off the event loop because it is a second database, with a commit
        of its own, on the path of every Ctrl+Enter. Nothing on screen
        waits for it: the memory is read when a project asks to be
        pre-filled, never while reviewing, and remember() swallows its
        own failures.

        Args:
            source_text: The source the translation answers.
            translated: The translation just validated.
        """
        self._page.run_thread(
            translation_memory.remember,
            [(source_text, translated)],
            self._state.source_language,
            self._state.target_language,
        )

    def _show_row_error(self, warning: ft.Text, message: str) -> None:
        """Report a blocking issue on the row that carries it.

        Args:
            warning: The row's warning line.
            message: What keeps the translation from being validated.
        """
        warning.value = message
        warning.color = ERROR
        warning.visible = True
        self._safe_update()

    def _announce_validation(
        self, warning: str | None, duplicates: list[str], translated: str
    ) -> None:
        """Report the outcome and offer to spread it to identical lines.

        A single toast carries both the quality warning and the offer,
        since only one can be shown at a time: either would otherwise
        hide the other.

        Args:
            warning: Length warning raised by the quality check, if any.
            duplicates: Block ids sharing the validated unit's source text.
            translated: The validated translation, applied if the offer is taken.
        """
        if not duplicates:
            if warning:
                self._show_status(warning, WARNING)
            else:
                self._hide_status()
            return

        key = (
            "review.duplicates_notice_one"
            if len(duplicates) == 1
            else "review.duplicates_notice_many"
        )
        notice = i18n.t(key).format(count=len(duplicates))
        self._show_status(
            f"{warning} {notice}" if warning else notice,
            WARNING if warning else SUCCESS,
            action=i18n.t("review.duplicates_action"),
            on_action=lambda: self._validate_duplicates(duplicates, translated),
        )

    def _validate_duplicates(self, block_ids: list[str], translated: str) -> None:
        """Apply a validated translation to every line sharing its source text.

        The quality checks already passed on this exact source text, so
        they hold for these units too and are not run again.

        Args:
            block_ids: Units to validate, none of them already validated.
            translated: The translation to store.
        """
        self._repo.update_translations(
            [(block_id, translated, "human_validated") for block_id in block_ids]
        )
        self._load_page()
        self._load_files()
        self._safe_update()

    # ── Memoire de traduction ─────────────────────────────────────────────── #

    def _fill_from_memory(self) -> None:
        """Fill untranslated lines with what the memory already holds.

        The work itself is fill_from_memory(), which says why nothing
        reviewed can be overwritten and why the scope is the whole project
        rather than the open file. The tooltip and the result message say
        so too, the button sitting on a screen showing one file.
        """
        if self._blocked_by_running_job():
            return
        self._flush_pending_edit()

        filled = fill_from_memory(
            self._repo,
            source_language=self._state.source_language,
            target_language=self._state.target_language,
        )

        if not filled:
            self._show_status(i18n.t("review.memory_none"), WARNING)
            self._safe_update()
            return

        self._load_page()
        self._load_files()
        self._show_status(i18n.t("review.memory_filled").format(n=filled), SUCCESS)
        self._safe_update()

    # ── Import / export bilingue ──────────────────────────────────────────── #

    def _open_interchange_dialog(self, source_file: str | None = None) -> None:
        """Open the dialog offering a CSV, XLIFF or JSON round-trip.

        Args:
            source_file: The file the dialog is pinned to, None when it is
                opened from the toolbar and the scope stays a choice.
        """
        self._menu_file = source_file
        self._page.show_dialog(self._build_interchange_dialog())

    def _build_interchange_dialog(self) -> ft.AlertDialog:
        """Build the format and scope choice shared by import and export.

        Returns:
            An AlertDialog carrying both an import and an export action.
        """
        return ft.AlertDialog(
            modal=True,
            bgcolor="#1a1822",
            title=ft.Text(
                i18n.t("interchange.title"),
                size=18,
                weight=ft.FontWeight.W_600,
                color=TEXT_H,
            ),
            content=ft.Column(
                [
                    ft.Text(
                        i18n.t("interchange.message"),
                        size=13.5,
                        color=TEXT_MUTED,
                        width=360,
                    ),
                    self._interchange_format_dropdown,
                    self._scope_control(self._interchange_scope_dropdown),
                ],
                spacing=16,
                tight=True,
            ),
            actions=[
                dialog_action(
                    i18n.t("common.cancel"),
                    lambda _e: self._page.pop_dialog(),
                ),
                dialog_action(
                    i18n.t("interchange.import_action"),
                    self._on_interchange_import,
                    tone="accent",
                ),
                dialog_action(
                    i18n.t("interchange.export_action"),
                    self._on_interchange_export,
                    tone="primary",
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

    def _interchange_stem(self, source_file: str | None) -> str:
        """Return the file name proposed for an exported bilingual file.

        Args:
            source_file: The file being exported, None for the whole project.

        Returns:
            A name pairing the exported scope with the target language.
        """
        if source_file:
            scope = Path(source_file).stem
        elif self._state.project_path:
            scope = self._state.project_path.name
        else:
            scope = "project"
        return f"{scope}_{self._state.target_language or 'translation'}"

    async def _on_interchange_export(self, _: Event[ft.Container]) -> None:
        """Write the chosen scope to a bilingual file the user names.

        The whole scope goes out, untranslated lines included: sending the
        file to a translator is precisely what it is for.

        Args:
            _: Unused click event.
        """
        self._flush_pending_edit()
        fmt = self._interchange_format_dropdown.value or "csv"
        scope, source_file = self._dialog_scope(
            self._interchange_scope_dropdown, "file"
        )
        self._page.pop_dialog()

        if scope == "file" and source_file is None:
            self._show_status(i18n.t("translation.scope_file_none"), WARNING)
            self._safe_update()
            return

        extension = FORMAT_EXTENSION[fmt]
        destination = await ft.FilePicker().save_file(
            file_name=f"{self._interchange_stem(source_file)}.{extension}",
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=[extension],
        )
        if not destination:
            return

        path = Path(destination)
        if path.suffix.lower() != f".{extension}":
            path = path.with_name(f"{path.name}.{extension}")

        units = self._repo.get_all(source_file=source_file)
        try:
            write_interchange(
                path,
                units,
                source_language=self._state.source_language,
                target_language=self._state.target_language,
            )
        except (InterchangeError, OSError) as exc:
            self._show_status(str(exc), ERROR)
        else:
            self._show_status(
                i18n.t("interchange.export_done").format(n=len(units)), SUCCESS
            )
        self._safe_update()

    async def _on_interchange_import(self, _: Event[ft.Container]) -> None:
        """Read a bilingual file back into the project and report what applied.

        The format comes from the picked file's own extension, not from the
        dropdown: a file coming back from a third party is whatever they
        sent, and silently reading it as something else would be worse than
        refusing it.

        Args:
            _: Unused click event.
        """
        self._page.pop_dialog()
        if self._blocked_by_running_job():
            return
        self._flush_pending_edit()

        picked = await ft.FilePicker().pick_files(
            allow_multiple=False,
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=READABLE_EXTENSIONS,
        )
        if not picked or not picked[0].path:
            return

        try:
            units = read_interchange(Path(picked[0].path))
        except (InterchangeError, OSError) as exc:
            self._show_status(str(exc), ERROR)
            self._safe_update()
            return

        plan = plan_import(units, self._repo)
        if not plan.applicable:
            self._show_status(self._import_summary(plan, 0), WARNING)
            self._safe_update()
            return
        self._page.show_dialog(self._build_import_confirm_dialog(plan))

    def _build_import_confirm_dialog(self, plan: ImportPlan) -> ft.AlertDialog:
        """Show what a file would change, before anything is written.

        A file coming back from a third party is opaque until it is read,
        and applying it is not something the project can undo. The plan is
        already computed at this point, so showing it costs nothing and
        cancelling costs nothing either.

        Args:
            plan: What plan_import() decided the file would do.

        Returns:
            An AlertDialog listing the plan and confirming it.
        """
        counts = (
            ("interchange.confirm_flagged", plan.flagged),
            ("interchange.confirm_protected", plan.protected),
            ("interchange.confirm_stale", plan.stale),
            ("interchange.confirm_unknown", plan.unknown),
            ("interchange.confirm_empty", plan.empty),
        )
        lines: list[ft.Control] = [
            ft.Text(
                i18n.t("interchange.confirm_applicable").format(n=plan.applicable),
                size=13.5,
                color=TEXT,
                width=360,
            )
        ]
        lines.extend(
            ft.Text(i18n.t(key).format(n=count), size=13, color=TEXT_MUTED, width=360)
            for key, count in counts
            if count
        )
        return ft.AlertDialog(
            modal=True,
            bgcolor="#1a1822",
            title=ft.Text(
                i18n.t("interchange.confirm_title"),
                size=18,
                weight=ft.FontWeight.W_600,
                color=TEXT_H,
            ),
            content=ft.Column(lines, spacing=8, tight=True),
            actions=[
                dialog_action(
                    i18n.t("common.cancel"),
                    lambda _e: self._page.pop_dialog(),
                ),
                dialog_action(
                    i18n.t("interchange.confirm_action"),
                    partial(self._on_import_confirmed, plan),
                    tone="primary",
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

    def _on_import_confirmed(self, plan: ImportPlan, _e: Event[ft.Container]) -> None:
        """Write a confirmed plan and refresh everything it touched.

        Args:
            plan: The plan the user just accepted.
            _e: Unused click event.
        """
        self._page.pop_dialog()
        applied = apply_plan(plan, self._repo)
        self._load_page()
        self._load_files()
        self._rebuild_translate_controls()
        self._show_status(
            self._import_summary(plan, applied),
            SUCCESS if applied else WARNING,
        )
        self._safe_update()

    @staticmethod
    def _import_summary(plan: ImportPlan, applied: int) -> str:
        """Sum up an import in one line, naming only what actually happened.

        Args:
            plan: What plan_import() made of the file.
            applied: How many translations were really written.

        Returns:
            A comma-separated message for the status toast.
        """
        counts = (
            ("interchange.import_flagged", plan.flagged),
            ("interchange.import_protected", plan.protected),
            ("interchange.import_stale", plan.stale),
            ("interchange.import_unknown", plan.unknown),
            ("interchange.import_empty", plan.empty),
        )
        parts = [i18n.t("interchange.import_applied").format(n=applied)]
        parts.extend(i18n.t(key).format(n=count) for key, count in counts if count)
        return ", ".join(parts)

    # ── Traduction automatique ────────────────────────────────────────────── #

    def _active_provider_id(self) -> str | None:
        """Return the provider to use for the translate button.

        Prefers the user's saved default_provider when it is still
        configured, otherwise falls back to the first available provider.

        Returns:
            A provider id, or None if no provider is configured.
        """
        available = registry.available()
        if not available:
            return None
        default = settings.get("default_provider")
        return default if default in available else available[0]

    def _translate_label(self, provider_id: str) -> str:
        """Return the progress modal title for the given provider.

        Args:
            provider_id: The provider running the current job.

        Returns:
            "Translate with <Provider>" using the provider's display name.
        """
        name = _PROVIDER_LABELS.get(provider_id, provider_id)
        return f"{i18n.t('translation.translate_with')} {name}"

    def _rebuild_translate_controls(self) -> None:
        """Rebuild the translate-row controls based on job and provider state."""
        self._translate_row.controls.clear()

        job = self._job
        if job is not None and job.progress.running:
            return

        if self._active_provider_id() is None:
            self._translate_row.controls = [
                self._provider_warning_text,
                self._provider_link_btn,
            ]
            return

        if not is_recognized_language(self._state.target_language):
            self._language_warning_text.value = i18n.t(
                "translation.unsupported_language"
            ).format(lang=self._state.target_language)
            self._translate_row.controls = [self._language_warning_text]
            return

        self._translate_row.controls = [self._translate_btn]

    def _show_job_dialog(self) -> None:
        """Show the translation options dialog, reusing the same instance.

        Flet's Page.show_dialog() raises if called twice for the same
        AlertDialog instance, because Page.pop_dialog() only flips its
        `open` flag back to False — it never forgets the dialog. So the
        very first display goes through show_dialog(), and every later
        one just flips `open` back on directly.

        Uses page.update() rather than the dialog's own update(), like
        every other UI change in this view.
        """
        if self._job_dialog_shown_once:
            self._job_dialog.open = True
            self._safe_update()
        else:
            self._page.show_dialog(self._job_dialog)
            self._job_dialog_shown_once = True

    def _hide_job_dialog(self) -> None:
        """Close the options dialog directly, not via Page.pop_dialog().

        pop_dialog() closes whichever dialog Flet considers topmost in its
        internal stack, which can be a status toast (SnackBar) that is
        still technically marked open rather than our own dialog — its
        client-side auto-dismiss timer doesn't necessarily sync `open`
        back to False on the Python side right away. Setting `open` on
        our own dialog instance avoids that ambiguity entirely.
        """
        self._job_dialog.open = False
        self._safe_update()

    def _on_job_dialog_dismissed(self, _e: Event[ft.DialogControl]) -> None:
        """Forget the dialog instance once Flet unmounts it.

        Flet's AlertDialog has no barrier_dismissible flag, so even a
        modal dialog can still be closed by clicking outside it or
        pressing Esc. Flet fully unmounts the dialog when that happens
        (unlike pop_dialog(), which only hides it), so the next display
        has to go through show_dialog() again.

        Args:
            _e: Unused dismiss event.
        """
        self._job_dialog_shown_once = False

    def _on_translate_clicked(self, _: Any) -> None:
        """Open the translation options dialog from the toolbar.

        Args:
            _: Unused click event.
        """
        self._start_translate_flow(None)

    def _start_translate_flow(self, source_file: str | None) -> None:
        """Open the translation options dialog (provider and scope).

        The provider picker is only included when more than one provider
        is configured; with a single provider it is auto-selected and
        only the scope choice is shown.

        Args:
            source_file: The file the run is pinned to, None when the
                scope stays a choice.
        """
        self._menu_file = source_file
        self._flush_pending_edit()
        available = registry.available()
        if not available or not is_recognized_language(self._state.target_language):
            self._rebuild_translate_controls()
            self._safe_update()
            return

        self._open_translate_options_dialog(available)

    def _open_translate_options_dialog(self, available: list[str]) -> None:
        """Show a dialog to confirm the translation scope and provider.

        Args:
            available: Ids of the configured, ready-to-use providers.
        """
        self._translate_options_available = available
        controls: list[ft.Control] = []

        if len(available) > 1:
            default = settings.get("default_provider")
            self._provider_choice_dropdown.options = [
                ft.dropdown.Option(key=pid, text=_PROVIDER_LABELS.get(pid, pid))
                for pid in available
            ]
            self._provider_choice_dropdown.value = (
                default if default in available else available[0]
            )
            controls += [self._provider_choice_label, self._provider_choice_dropdown]

        controls += [
            self._scope_choice_label,
            self._scope_control(self._scope_dropdown),
        ]
        self._job_selection_col.controls = controls

        self._job_dialog.title = ft.Text(
            i18n.t("translation.options_title"),
            size=16,
            weight=ft.FontWeight.W_700,
            color=TEXT_H,
        )
        self._show_job_dialog()
        self._safe_update()

    def _on_provider_choice_confirmed(self, _e: Event[ft.Container]) -> None:
        """Close the dialog and start the job with the chosen options.

        Args:
            _e: Unused click event.
        """
        available = self._translate_options_available
        if len(available) > 1:
            provider_id = self._provider_choice_dropdown.value
            if not provider_id:
                return
        else:
            provider_id = available[0]
        self._hide_job_dialog()
        self._start_translation_job(provider_id)

    def _start_translation_job(self, provider_id: str) -> None:
        """Resolve the scope, then prompt about drafts or launch the job.

        Drafts (lines a human typed but did not validate) are skipped by
        default. When the chosen scope contains any, the user is asked
        whether to retranslate and overwrite them before the job starts.

        Args:
            provider_id: Id of the provider to translate with.
        """
        scope, source_file = self._dialog_scope(self._scope_dropdown, "all")
        if scope == "file" and source_file is None:
            self._show_status(i18n.t("translation.scope_file_none"), WARNING)
            self._safe_update()
            return

        draft_count = len(
            self._repo.get_all(status_filter="draft", source_file=source_file)
        )
        if draft_count:
            self._open_include_drafts_dialog(provider_id, source_file, draft_count)
            return
        self._launch_translation_job(provider_id, source_file, include_drafts=False)

    def _open_include_drafts_dialog(
        self, provider_id: str, source_file: str | None, draft_count: int
    ) -> None:
        """Ask whether the batch job should also overwrite existing drafts.

        Args:
            provider_id: Id of the provider to translate with.
            source_file: File to restrict the job to, or None for all files.
            draft_count: Number of draft lines in the chosen scope.
        """

        def _launch(include_drafts: bool) -> None:
            self._page.pop_dialog()
            self._launch_translation_job(
                provider_id, source_file, include_drafts=include_drafts
            )

        dialog = ft.AlertDialog(
            modal=True,
            bgcolor="#1a1822",
            title=ft.Text(
                i18n.t("translation.include_drafts_title"),
                size=16,
                weight=ft.FontWeight.W_700,
                color=TEXT_H,
            ),
            content=ft.Text(
                i18n.t("translation.include_drafts_message").format(n=draft_count),
                size=13.5,
                color=TEXT,
            ),
            actions=[
                dialog_action(
                    i18n.t("translation.cancel"),
                    lambda _e: self._page.pop_dialog(),
                ),
                dialog_action(
                    i18n.t("translation.include_drafts_no"),
                    lambda _e: _launch(False),
                    tone="accent",
                ),
                dialog_action(
                    i18n.t("translation.include_drafts_yes"),
                    lambda _e: _launch(True),
                    tone="primary",
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self._page.show_dialog(dialog)

    def _launch_translation_job(
        self, provider_id: str, source_file: str | None, include_drafts: bool
    ) -> None:
        """Build the provider and payload, then run the translation job.

        Args:
            provider_id: Id of the provider to translate with.
            source_file: File to restrict the job to, or None for all files.
            include_drafts: Whether to also retranslate (and overwrite)
                existing draft lines in the chosen scope.
        """
        try:
            provider = registry.get(
                provider_id,
                universe_summary=self._project_meta_repo.get("universe_summary"),
                characters=self._character_repo.get_all(),
            )
        except ValueError:
            self._rebuild_translate_controls()
            self._safe_update()
            return

        units = self._repo.get_all(
            status_filter="not_translated", source_file=source_file
        )
        if include_drafts:
            units = units + self._repo.get_all(
                status_filter="draft", source_file=source_file
            )
        if not units:
            self._show_status(
                i18n.t("translation.translation_done").format(done=0, failed=0),
                WARNING,
            )
            self._safe_update()
            return

        payload: list[TranslationUnitPayload] = [
            {
                "block_id": u.block_id,
                "source_text": u.source_text,
                "character_variable": u.character_variable,
            }
            for u in units
        ]
        self._symbol_only_units |= {
            u.block_id for u in units if not needs_translation(u.source_text)
        }

        self._hide_status()
        self._vstate.status_filter = None
        self._vstate.errors_only = False
        self._vstate.review_only = False
        self._filter_dropdown.value = ""

        self._job_provider_text.value = self._translate_label(provider_id)
        self._job_progress_bar.value = 0
        self._job_counter_text.value = f"0 / {len(units)}"
        self._job_batch_text.value = ""
        self._job_hint_text.value = (
            f"{i18n.t('translation.ollama_slow_hint')} "
            f"{i18n.t('provider_config.ollama_reliability_hint')}"
            if provider_id == "ollama"
            else ""
        )
        self._job_event_text.value = ""
        self._job_cancel_text.value = i18n.t("translation.cancel")
        self._job_banner.visible = True

        self._job = TranslationJob(
            on_chunk=self._on_job_chunk,
            on_progress=self._on_ui_thread(self._on_job_progress),
            on_complete=self._on_ui_thread(self._on_job_complete),
            on_batch_start=self._on_ui_thread(self._on_job_batch_start),
            on_event=self._on_ui_thread(self._on_job_event),
            thread_runner=self._page.run_thread,
        )
        self._job.start(
            payload, provider, self._state.source_language, self._state.target_language
        )
        self._rebuild_translate_controls()
        self._load_page()
        self._safe_update()

    def _on_cancel_clicked(self, _: Any) -> None:
        """Request cancellation of the running translation job.

        The background thread finishes the request currently in flight
        before it checks for cancellation, so the banner is updated to
        reflect that a short wait is still expected.
        """
        if self._job is not None:
            self._job.cancel()
            self._job_cancel_text.value = i18n.t("translation.cancelling")
            self._job_batch_text.value = i18n.t("translation.cancelling_hint")
            self._safe_update()

    def _on_job_chunk(self, result: TranslateBatchResult) -> None:
        """Persist one translated chunk as ai_suggested.

        Called from the job's background thread after each chunk, so that
        cancelling the job preserves everything translated so far.

        Units the job copied verbatim because their source has nothing to
        translate never went through a model, so they are persisted as
        human_validated instead — there is nothing to review.

        Args:
            result: The translations and failures for one chunk.
        """
        for unit in result.translations:
            block_id = unit["block_id"]
            status: TranslationStatus = (
                "human_validated"
                if block_id in self._symbol_only_units
                else "ai_suggested"
            )
            self._repo.update_translation(block_id, unit["translated_text"], status)

    def _on_job_batch_start(self, index: int, total: int) -> None:
        """Update the banner's batch indicator before a network request.

        Scheduled by the job before each request the provider is about
        to send, so the banner shows activity even while a single slow
        request (e.g. a local LLM) is still in flight. Runs on the event
        loop's thread via _on_ui_thread().

        Args:
            index: 1-based index of the request about to be sent.
            total: Total number of requests for the current chunk.
        """
        self._job_batch_text.value = i18n.t("translation.batch_progress").format(
            index=index, total=total
        )
        self._safe_update()

    def _on_job_event(self, message: str) -> None:
        """Show the latest notable job event in the banner.

        Only the last one is kept: the banner sits above the lines being
        reviewed and must not grow into the list. The full history is in
        the log file when verbose logging is on.

        Runs on the event loop's thread via _on_ui_thread().

        Args:
            message: Human-readable description of what happened.
        """
        self._job_event_text.value = message
        self._safe_update()

    def _on_job_progress(self, progress: JobProgress) -> None:
        """Refresh the banner and current page after each chunk.

        The line list is left alone while a field has the focus: the job
        no longer blocks the screen, so a rebuild here would pull the
        field out from under someone typing in it. Whatever was typed is
        written first, and the next navigation shows the new suggestions.

        The banner moves on every chunk, the two lists at most once a
        second. A chunk is fifty units, so a whole game is eight hundred
        of them, and rebuilding fifty rows and a hundred file entries
        that many times is work nobody can read going by. The job's last
        word is _on_job_complete(), which reloads unconditionally, so
        nothing stays stale for longer than the job itself.

        Args:
            progress: The job's current progress.
        """
        self._job_progress_bar.value = progress.done / progress.total
        self._job_counter_text.value = f"{progress.done} / {progress.total}"
        self._job_batch_text.value = ""
        self._flush_pending_edit()
        now = time.monotonic()
        if now - self._panel_refreshed_at >= _JOB_REFRESH_INTERVAL:
            self._panel_refreshed_at = now
            if not self._editing:
                self._load_page()
            self._load_files()
        self._safe_update()

    def _on_job_complete(self, progress: JobProgress) -> None:
        """Hide the banner and finalize the UI once the job stops.

        Args:
            progress: The job's final progress.
        """
        self._job = None
        self._job_banner.visible = False
        self._flush_pending_edit()
        self._rebuild_translate_controls()
        self._load_page()
        self._load_files()

        if progress.error:
            self._show_status(progress.error, ERROR)
        else:
            color = SUCCESS if progress.failed == 0 else WARNING
            self._show_status(
                i18n.t("translation.translation_done").format(
                    done=progress.done, failed=progress.failed
                ),
                color,
            )
        self._safe_update()

    # ── Traduction d'une seule ligne ──────────────────────────────────────── #

    def _translate_single_unit(self, unit: TranslationUnit) -> None:
        """Translate one row, prompting for a provider if more than one is set up.

        The in-flight block_id is tracked on self (_translating_units)
        rather than on the row's controls, so the hourglass indicator and
        the eventual result survive switching pages, files or filters
        while the request is in flight — the same way the batch translate
        button reflects progress purely from the database, never from a
        specific row's controls.

        Args:
            unit: The unit to translate.
        """
        if self._blocked_by_running_job():
            return
        self._flush_pending_edit()
        available = registry.available()
        if not available:
            self._show_status(i18n.t("translation.no_provider_configured"), WARNING)
            self._safe_update()
            return

        if not is_recognized_language(self._state.target_language):
            self._show_status(
                i18n.t("translation.unsupported_language").format(
                    lang=self._state.target_language
                ),
                WARNING,
            )
            self._safe_update()
            return

        if len(available) > 1:
            self._open_unit_provider_dialog(available, unit)
            return

        self._run_unit_translation(available[0], unit)

    def _open_unit_provider_dialog(
        self, available: list[str], unit: TranslationUnit
    ) -> None:
        """Show a one-shot dialog to pick the provider for this row.

        Args:
            available: Ids of the configured, ready-to-use providers.
            unit: The unit to translate.
        """
        default = settings.get("default_provider")
        dropdown = ft.Dropdown(
            value=default if default in available else available[0],
            options=[
                ft.dropdown.Option(key=pid, text=_PROVIDER_LABELS.get(pid, pid))
                for pid in available
            ],
            bgcolor=BG_INPUT,
            border_color=BORDER_COLOR,
            focused_border_color=FOCUS_RING,
            focused_border_width=FOCUS_RING_WIDTH,
            color=TEXT,
            border_radius=8,
            width=260,
            dense=True,
            content_padding=ft.Padding(left=10, right=0, top=0, bottom=0),
        )

        def _on_confirm(_e: Any) -> None:
            self._page.pop_dialog()
            self._run_unit_translation(dropdown.value or available[0], unit)

        dialog = ft.AlertDialog(
            modal=True,
            bgcolor="#1a1822",
            title=ft.Text(
                i18n.t("translation.translate_unit_title"),
                size=16,
                weight=ft.FontWeight.W_700,
                color=TEXT_H,
            ),
            content=ft.Column(
                [
                    ft.Text(
                        i18n.t("translation.choose_provider_label").upper(),
                        size=12,
                        weight=ft.FontWeight.W_600,
                        color=TEXT_MUTED,
                    ),
                    dropdown,
                ],
                spacing=9,
                tight=True,
                width=300,
            ),
            actions=[
                dialog_action(
                    i18n.t("common.cancel"),
                    lambda _e: self._page.pop_dialog(),
                ),
                dialog_action(
                    i18n.t("translation.start"),
                    _on_confirm,
                    tone="primary",
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self._page.show_dialog(dialog)

    def _run_unit_translation(self, provider_id: str, unit: TranslationUnit) -> None:
        """Build the provider and run a one-unit TranslationJob in the background.

        Reuses TranslationJob rather than calling the provider directly so
        this single line goes through the same quality gate and retry
        passes as the batch translate button, and persists through
        on_chunk exactly like the batch job does.

        Args:
            provider_id: Id of the provider to translate with.
            unit: The unit to translate.
        """
        try:
            provider = registry.get(
                provider_id,
                universe_summary=self._project_meta_repo.get("universe_summary"),
                characters=self._character_repo.get_all(),
            )
        except ValueError:
            self._show_status(i18n.t("translation.no_provider_configured"), WARNING)
            self._safe_update()
            return

        self._translating_units.add(unit.block_id)
        self._load_page()
        self._safe_update()

        payload: TranslationUnitPayload = {
            "block_id": unit.block_id,
            "source_text": unit.source_text,
            "character_variable": unit.character_variable,
        }
        if not needs_translation(unit.source_text):
            self._symbol_only_units.add(unit.block_id)
        job = TranslationJob(
            on_chunk=self._on_job_chunk,
            on_progress=lambda _progress: None,
            on_complete=self._on_ui_thread(
                partial(self._on_unit_job_complete, unit.block_id)
            ),
            thread_runner=self._page.run_thread,
        )
        job.start(
            [payload],
            provider,
            self._state.source_language,
            self._state.target_language,
        )

    def _on_unit_job_complete(self, block_id: str, progress: JobProgress) -> None:
        """Clear the in-flight marker and refresh from the database.

        Runs on the event loop thread. Reloading from the database rather
        than touching specific row controls means this works correctly
        even if the user navigated to a different page, file or filter
        while the translation was in flight. As in the batch job, the
        line list is left alone while a field has the focus: rebuilding
        it would pull the field out from under someone typing on another
        line, and show them their own text disappearing.

        Args:
            block_id: The unit that finished translating.
            progress: The one-unit job's final progress.
        """
        self._translating_units.discard(block_id)

        if progress.error:
            self._show_status(progress.error, ERROR)
        elif progress.failed:
            self._show_status(i18n.t("translation.unit_failed"), ERROR)

        self._flush_pending_edit()
        if not self._editing:
            self._load_page()
        self._load_files()
        self._safe_update()

    # ── Pagination ────────────────────────────────────────────────────────── #

    def _build_pagination(self, total_pages: int) -> None:
        """Rebuild the pagination row.

        Args:
            total_pages: Total number of pages for the current filter.
        """
        self._pagination_row.controls.clear()
        if total_pages <= 1:
            return

        cur = self._vstate.current_page

        self._pagination_row.controls = [
            focusable(
                ft.Container(
                    content=ft.Icon(ft.Icons.CHEVRON_LEFT, size=18, color=TEXT_MUTED),
                    width=36,
                    height=36,
                    alignment=ft.Alignment(0, 0),
                    border_radius=8,
                    ink=True,
                    opacity=1.0 if cur > 0 else 0.3,
                ),
                on_click=lambda _e: self._go_to_page(cur - 1),
                tooltip=i18n.t("help.shortcut_prev_page"),
                width=36,
                height=36,
                disabled=cur == 0,
            ),
            ft.TextField(
                value=str(cur + 1),
                width=58,
                height=34,
                text_size=13,
                text_align=ft.TextAlign.CENTER,
                bgcolor=BG_INPUT,
                border_color=BORDER_COLOR,
                focused_border_color=FOCUS_RING,
                focused_border_width=FOCUS_RING_WIDTH,
                border_radius=8,
                color=TEXT,
                cursor_color=ACCENT,
                content_padding=ft.Padding(left=4, right=4, top=0, bottom=0),
                tooltip=i18n.t("review.page_jump"),
                on_submit=self._on_page_submitted,
            ),
            ft.Text(
                i18n.t("review.pagination_total").format(total=total_pages),
                size=13,
                color=TEXT_MUTED,
            ),
            focusable(
                ft.Container(
                    content=ft.Icon(ft.Icons.CHEVRON_RIGHT, size=18, color=TEXT_MUTED),
                    width=36,
                    height=36,
                    alignment=ft.Alignment(0, 0),
                    border_radius=8,
                    ink=True,
                    opacity=1.0 if cur < total_pages - 1 else 0.3,
                ),
                on_click=lambda _e: self._go_to_page(cur + 1),
                tooltip=i18n.t("help.shortcut_next_page"),
                width=36,
                height=36,
                disabled=cur >= total_pages - 1,
            ),
        ]

    def _on_page_submitted(self, e: Event[ft.TextField]) -> None:
        """Navigate to the page number typed in the pagination field.

        Anything unusable simply reloads the current page, which puts the
        real number back in the field.

        Args:
            e: TextField submit event.
        """
        total_pages = max(1, -(-self._vstate.total_units // _PAGE_SIZE))
        try:
            wanted = int((e.control.value or "").strip())
        except ValueError:
            wanted = self._vstate.current_page + 1
        self._go_to_page(min(max(wanted, 1), total_pages) - 1)

    def _go_to_page(self, page_index: int, *, keep_scroll: bool = False) -> None:
        """Navigate to a page index.

        Args:
            page_index: Zero-based page index to navigate to.
            keep_scroll: Whether to leave the scroll position alone. Set
                by the keyboard walk, which crosses a page boundary to
                land the caret on a line and lets that focus bring the
                line into view; scrolling to the top first would fight
                it, and the line it lands on is the last one on the page
                when walking upwards.
        """
        total_pages = max(1, -(-self._vstate.total_units // _PAGE_SIZE))
        if page_index < 0 or page_index >= total_pages:
            return
        self._flush_pending_edit()
        self._vstate.current_page = page_index
        self._load_page(scroll_to_top=not keep_scroll)
        self._safe_update()

    # ── Evenements toolbar ────────────────────────────────────────────────── #

    def _on_filter_changed(self, e: Event[ft.Dropdown]) -> None:
        """Update status filter and reload the page and the file panel.

        The panel is reloaded because the search match counts it shows
        obey the status filter too.

        The error entry is not a status: it selects the lines a quality
        check refuses, whatever their status, so it clears the status
        filter rather than joining it.

        Args:
            e: Dropdown select event.
        """
        self._flush_pending_edit()
        chosen = e.control.value or ""
        self._vstate.errors_only = chosen == _ERROR_FILTER
        self._vstate.review_only = chosen == _REVIEW_FILTER
        self._vstate.status_filter = (
            None
            if self._vstate.errors_only or self._vstate.review_only
            else chosen or None
        )
        self._vstate.current_page = 0
        self._load_page(scroll_to_top=True)
        self._load_files()
        self._safe_update()

    def _on_character_filter_changed(self, e: Event[ft.Dropdown]) -> None:
        """Restrict the list to one speaker, or show them all again.

        Args:
            e: Dropdown select event.
        """
        self._flush_pending_edit()
        self._vstate.character_filter = e.control.value or None
        self._vstate.current_page = 0
        self._load_page(scroll_to_top=True)
        self._load_files()
        self._safe_update()

    def _refresh_character_options(self) -> None:
        """Fill the speaker filter with every speaker of the project.

        Project-wide, and kept across file changes, for the same reason
        the search field is: a speaker who says nothing in the file being
        read would otherwise be indistinguishable from one who says
        nothing at all. The file panel answers where they do speak. A
        project with no speaker at all hides the filter.
        """
        variables = self._repo.character_variables()
        names = {
            character.variable: character.display_name
            for character in self._character_repo.get_all()
        }
        self._character_dropdown.options = [
            ft.dropdown.Option(key="", text=i18n.t("review.filter_character_all")),
            *(
                ft.dropdown.Option(key=variable, text=names.get(variable) or variable)
                for variable in variables
            ),
        ]
        self._character_dropdown.visible = bool(variables)

    def _on_search_changed(self, e: Event[ft.TextField]) -> None:
        """Update search query and reload the page and the file panel.

        Args:
            e: TextField change event.
        """
        self._flush_pending_edit()
        self._vstate.search_query = e.control.value or ""
        self._vstate.current_page = 0
        self._load_page(scroll_to_top=True)
        self._load_files()
        self._safe_update()

    def _open_clear_dialog(self, source_file: str | None = None) -> None:
        """Show a dialog to confirm clearing translations.

        Args:
            source_file: The file the clear is pinned to, None when it is
                opened from the toolbar and the scope stays a choice.
        """
        self._menu_file = source_file
        self._page.show_dialog(self._build_clear_dialog())

    def _build_clear_dialog(self) -> ft.AlertDialog:
        """Build the confirmation dialog shown before clearing translations.

        Returns:
            An AlertDialog with a scope choice and a destructive confirm
            action.
        """
        return ft.AlertDialog(
            modal=True,
            title=ft.Text(
                i18n.t("review.clear_title"),
                size=18,
                weight=ft.FontWeight.W_600,
                color=TEXT_H,
            ),
            bgcolor="#1a1822",
            content=ft.Column(
                [
                    ft.Text(
                        i18n.t("review.clear_message"),
                        size=13.5,
                        color=TEXT_MUTED,
                        width=320,
                    ),
                    self._scope_control(self._clear_scope_dropdown),
                    self._clear_status_dropdown,
                ],
                spacing=14,
                tight=True,
            ),
            actions=[
                dialog_action(
                    i18n.t("common.cancel"),
                    lambda _e: self._page.pop_dialog(),
                ),
                dialog_action(
                    i18n.t("review.clear_confirm_action"),
                    self._on_clear_confirmed,
                    tone="danger",
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

    def _on_clear_confirmed(self, _e: Event[ft.Container]) -> None:
        """Clear translations for the chosen scope and refresh the view.

        Args:
            _e: Unused click event.
        """
        self._flush_pending_edit()
        scope, source_file = self._dialog_scope(self._clear_scope_dropdown, "file")
        if scope == "file" and source_file is None:
            self._page.pop_dialog()
            self._show_status(i18n.t("translation.scope_file_none"), WARNING)
            self._safe_update()
            return

        statuses = _CLEAR_STATUS_SETS.get(self._clear_status_dropdown.value or "")
        count = self._repo.clear_translations(source_file, statuses)
        self._page.pop_dialog()
        self._load_page()
        self._load_files()
        self._rebuild_translate_controls()
        self._show_status(i18n.t("review.clear_done").format(n=count), SUCCESS)
        self._safe_update()

    def _on_save_clicked(self, _: Any) -> None:
        """Write every stored translation back to .rpy files.

        Statuses are deliberately not filtered. The SDK fills each block it
        generates with a copy of the source text, so the line an unvalidated
        suggestion or draft replaces is the source language itself: writing
        it can only bring the file closer to the target language, and it is
        what makes the translation reviewable in game. The database remains
        the only source of truth, and unit statuses are left untouched.

        A unit with no translation is written back as its source text, which
        is exactly what the SDK had generated. Skipping it instead would
        leave a translation the user has just cleared alive in the file.
        """
        self._flush_pending_edit()
        stored = self._repo.get_all()
        strings_units = [u for u in stored if u.block_id.startswith("strings_")]

        # Dialogue blocks: block_id -> translated_text, or source text if cleared
        dialogue = {
            u.block_id: u.translated_text or u.source_text
            for u in stored
            if not u.block_id.startswith("strings_")
        }

        # Strings blocks: old_text -> new_text, a translation winning over a
        # cleared unit sharing the same source text
        old_to_new = {u.source_text: u.source_text for u in strings_units}
        old_to_new.update(
            {
                u.source_text: u.translated_text
                for u in strings_units
                if u.translated_text
            }
        )

        if not dialogue and not old_to_new:
            self._show_status(i18n.t("review.error_save_nothing"), WARNING)
            self._safe_update()
            return

        tl_output = self._state.tl_output_dir
        project = self._state.project_path

        if tl_output is None or project is None:
            self._show_status(i18n.t("review.error_save_no_path"), ERROR)
            self._safe_update()
            return

        lang_dir = tl_output
        backup_dir = project / ".rts" / "backups"

        try:
            writer = TranslateBlockWriter(lang_dir, backup_dir)
            writer.write_all(dialogue, old_to_new=old_to_new or None)
            record_save(self._project_meta_repo, lang_dir)
            n = sum(1 for u in stored if u.translated_text)
            self._show_status(i18n.t("review.saved_ok").format(n=n), SUCCESS)
        except Exception as exc:
            self._show_status(str(exc), ERROR)

        self._update_sync_indicator()
        self._safe_update()

    # ── Compteur et banniere ──────────────────────────────────────────────── #

    def _update_counter(self) -> None:
        """Refresh the validated/total counter using current file stats."""
        stats = self._vstate.file_stats.get(self._vstate.selected_file or "")
        validated = stats["validated"] if stats else 0
        total = stats["total"] if stats else 0
        suffix = i18n.t("review.validated")
        self._counter_text.value = f"{validated} / {total} {suffix}"

    def _update_project_progress(self, stats: list[FileStats]) -> None:
        """Refresh the whole-project progress shown above the file list.

        The toolbar counter only ever speaks about the open file, which
        says nothing about a game of three hundred of them. Lines lead
        here because they are what the rest of the screen counts, from the
        per-file badges to the unwritten-lines notice: a bar advancing in
        words was the one figure nothing else could be checked against.
        The word counts, which is what a translation is planned and billed
        in, stay one hover away.

        The bar itself is summed from the per-file counts the panel was
        given, so it costs nothing and is always exact. Only the words
        need a query, and only when a line was validated or the project
        gained lines: no filter, no search and no page turn can move
        them, and asking anyway was 44 ms under every keystroke.

        Args:
            stats: The per-file counts the file panel is being built
                from, covering every file of the project.
        """
        lines = sum(int(entry["total"]) for entry in stats)
        done = sum(int(entry["validated"]) for entry in stats)
        ratio = done / lines if lines else 0.0
        self._progress_bar.value = ratio
        self._progress_text.value = i18n.t("review.project_progress").format(
            percent=int(ratio * 100), done=done, total=lines
        )
        if self._words_counted_for == (lines, done):
            return
        self._words_counted_for = (lines, done)
        progress = self._repo.project_progress()
        self._progress_text.tooltip = i18n.t("review.project_progress_words").format(
            done=progress["validated_words"], total=progress["words"]
        )

    def _update_sync_indicator(self) -> None:
        """Tell how much of the database is still missing from the .rpy files.

        Every keystroke reaches the database while the files only change on
        save, so the two drift apart with nothing to show for it. Only the
        pending count is read here: whether the files were touched from
        outside is the export view's check, far too costly to run on every
        page load.

        A project never written out once says the same thing as one written
        out long ago, with the same sentence and the same number. It used to
        get a state of its own reading "never written to .rpy", which named
        neither what was unwritten nor how much of it.

        The button is dimmed rather than disabled when the count reaches
        zero. Both timestamps have a one-second resolution, so an edit
        landing in the very second of a save is invisible to the count, and
        a disabled button would leave no way to write it out.
        """
        saved_at = self._project_meta_repo.get(META_SAVED_AT)
        pending = self._repo.count_modified_since(saved_at)

        if pending:
            self._sync_text.value = i18n.t("review.sync_pending").format(n=pending)
            self._sync_text.color = WARNING
        else:
            self._sync_text.value = i18n.t("review.sync_ok")
            self._sync_text.color = TEXT_HINT

        self._save_box.opacity = 1.0 if pending else 0.45

    def _show_status(
        self,
        message: str,
        color: str,
        *,
        action: str | None = None,
        on_action: Callable[[], None] | None = None,
    ) -> None:
        """Show a toast notification with a status message.

        Builds a fresh SnackBar for every message, as Flet's own
        documentation does. A single reused instance only ever shows its
        first message: once the client reports the toast dismissed, Flet
        drops it from the page's dialog stack without flipping its `open`
        flag back to False, so setting `open = True` again produces no
        diff and page.update() sends nothing.

        The previous toast is closed first, otherwise the client queues
        the new one behind the remainder of its display duration.

        Page.show_dialog() mutates the dialog stack and pushes it to the
        client directly, so it is scheduled on the event loop the same way
        _safe_update() does — status messages also come from Flet's
        handler threads.

        A toast carrying an action stays up longer: five seconds is enough
        to read a message, not to notice a button, aim and click it.

        Args:
            message: Text to display.
            color: Hex color (ERROR, WARNING, or SUCCESS).
            action: Label of an optional button shown next to the message.
            on_action: Called when that button is clicked.
        """
        if color == SUCCESS:
            bgcolor = "#16281c"
        elif color == WARNING:
            bgcolor = "#2b2210"
        else:
            bgcolor = "#2b1c1c"

        self._hide_status()
        snack = ft.SnackBar(
            content=ft.Text(message, size=13, color=color),
            bgcolor=bgcolor,
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
        self._status_snack = snack
        self._page.session.connection.loop.call_soon_threadsafe(
            self._page.show_dialog, snack
        )

    def _hide_status(self) -> None:
        """Dismiss the current status toast, if one is showing."""
        if self._status_snack is None:
            return
        self._status_snack.open = False
        self._status_snack = None
        self._safe_update()

    # ── Construction du layout ────────────────────────────────────────────── #

    def build(self) -> ft.Control:
        """Build and return the complete two-panel review view.

        Returns:
            A Flet Column with stepper + two-panel content.
        """
        return ft.Column(
            [
                build_stepper(
                    2,
                    on_setup=lambda: self._on_setup_step_clicked(None),
                    export_label_key="review.step_export",
                ),
                ft.Row(
                    [
                        self._build_left_panel(),
                        self._build_right_panel(),
                    ],
                    expand=True,
                    spacing=0,
                    vertical_alignment=ft.CrossAxisAlignment.STRETCH,
                ),
            ],
            expand=True,
            spacing=0,
        )

    def _build_left_panel(self) -> ft.Container:
        """Build the fixed-width file list panel.

        Returns:
            A Container with title and scrollable file list.
        """
        return ft.Container(
            content=ft.Column(
                [
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Text(
                                    i18n.t("review.files_panel_title"),
                                    size=11,
                                    weight=ft.FontWeight.W_700,
                                    color=TEXT_HINT,
                                ),
                                self._progress_bar,
                                self._progress_text,
                            ],
                            spacing=5,
                            tight=True,
                        ),
                        padding=ft.Padding(left=10, right=10, top=14, bottom=6),
                    ),
                    self._file_list_col,
                ],
                spacing=0,
                expand=True,
            ),
            width=_PANEL_WIDTH,
            border=ft.Border(right=ft.BorderSide(1, "#1a1820")),
        )

    def _build_right_panel(self) -> ft.Column:
        """Build the expanding right panel: toolbar, table, pagination.

        Returns:
            A Column with all right-panel controls.
        """
        return ft.Column(
            [
                self._build_toolbar(),
                self._job_banner,
                self._build_table_header(),
                self._block_list_col,
                self._pagination_row,
            ],
            expand=True,
            spacing=0,
        )

    def _build_toolbar(self) -> ft.Container:
        """Build the filter / search / counter / save toolbar.

        Two rows rather than one. Fifteen controls of four different
        kinds never fit on a single line: three of the filters alone hold
        600 fixed pixels, so the save button was pushed off the right
        edge even on a maximised window. A Row does not wrap, it simply
        overflows, and what it drops first is the end of the line, which
        is where the primary action sat.

        The split follows what the controls do rather than their size, so
        it survives a window resize: acting on the project on top, from
        leaving the screen through to writing the files out; looking at
        the open file below, filters and search with the count they
        produce. Each row keeps its own spacer, so both stay pinned to
        the two edges.

        Turning these two rows into wrapping ones, so the labelled
        actions could spill onto a third line instead of off the edge,
        takes the whole right panel down: it renders as a grey rectangle,
        toolbar, table and pagination together. Whatever Flet 0.85 makes
        of `wrap=True` here, it is not a drop-in for these rows, and the
        overflow is the lesser of the two.

        Returns:
            A Container with action controls.
        """
        actions = ft.Row(
            [
                self._characters_btn,
                self._universe_btn,
                self._toolbar_separator(),
                self._memory_btn,
                self._interchange_btn,
                self._clear_btn,
                ft.Container(expand=True),
                self._translate_row,
                self._sync_text,
                self._save_btn,
            ],
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        view = ft.Row(
            [
                self._filter_dropdown,
                self._character_dropdown,
                self._search_field,
                ft.Container(expand=True),
                self._counter_text,
            ],
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        return ft.Container(
            content=ft.Column([actions, view], spacing=10, tight=True),
            padding=ft.Padding(left=14, right=14, top=10, bottom=10),
            border=ft.Border(bottom=ft.BorderSide(1, "#1a1820")),
            bgcolor="#17161f",
        )

    def _build_table_header(self) -> ft.Container:
        """Build the column header row.

        Widths mirror _build_unit_row exactly to guarantee alignment.

        Returns:
            A styled Container with column labels.
        """
        lbl = ft.TextStyle(size=10, weight=ft.FontWeight.W_700, color=TEXT_HINT)
        return ft.Container(
            content=ft.Row(
                [
                    ft.Container(
                        content=ft.Icon(
                            ft.Icons.LABEL_OUTLINE,
                            size=12,
                            color=TEXT_HINT,
                            semantics_label=i18n.t("review.status_column"),
                        ),
                        width=_COL_STATUS,
                        alignment=ft.Alignment(0, 0),
                        tooltip=i18n.t("review.status_column"),
                    ),
                    ft.Container(
                        content=ft.Text(i18n.t("review.source_column"), style=lbl),
                        expand=True,
                    ),
                    ft.Container(
                        content=ft.Text(i18n.t("review.translation_column"), style=lbl),
                        expand=True,
                    ),
                    ft.Container(width=_COL_ACTIONS),
                ],
                spacing=_ROW_SPACING,
            ),
            padding=ft.Padding(left=12, right=8, top=8, bottom=8),
            bgcolor="#15141d",
            border=ft.Border(bottom=ft.BorderSide(1, "#201e2c")),
        )

    # ── Navigation ────────────────────────────────────────────────────────── #

    def _on_setup_step_clicked(self, _: Any) -> None:
        """Ask for confirmation before returning to project setup."""
        if self._blocked_by_running_job():
            return
        self._page.show_dialog(self._build_back_confirm_dialog())

    def _build_back_confirm_dialog(self) -> ft.AlertDialog:
        """Build the confirmation dialog shown before leaving the review.

        Returns:
            An AlertDialog asking the user to confirm returning to setup.
        """
        return ft.AlertDialog(
            modal=True,
            title=ft.Text(
                i18n.t("review.back_confirm_title"),
                size=18,
                weight=ft.FontWeight.W_600,
                color=TEXT_H,
            ),
            bgcolor="#1a1822",
            content=ft.Text(
                i18n.t("review.back_confirm_message"),
                size=13.5,
                color=TEXT_MUTED,
                width=320,
            ),
            actions=[
                dialog_action(
                    i18n.t("common.cancel"),
                    lambda _e: self._page.pop_dialog(),
                ),
                dialog_action(
                    i18n.t("review.back_confirm_action"),
                    lambda _e: self._on_back_confirmed(),
                    tone="danger",
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

    def _on_back_confirmed(self) -> None:
        """Close the confirmation dialog and navigate back to setup."""
        self._page.pop_dialog()
        self._navigate_back()

    def _blocked_by_running_job(self) -> bool:
        """Refuse an action that would silently kill a running job.

        Leaving the view disposes it, which cancels the translation. The
        progress used to sit behind a modal that made this unreachable;
        now that it is a banner, the check has to be explicit.

        Returns:
            True when a job is running, having told the user so.
        """
        if self._job is None or not self._job.progress.running:
            return False
        self._show_status(i18n.t("translation.job_running"), WARNING)
        self._safe_update()
        return True

    def _navigate_back(self) -> None:
        """Dispose and navigate back to project setup."""
        self.dispose()
        self._on_back()

    def _navigate_provider(self) -> None:
        """Dispose and navigate to the provider settings view."""
        if self._blocked_by_running_job():
            return
        self.dispose()
        self._on_configure_provider()

    def _navigate_export(self) -> None:
        """Dispose and navigate to the zip export view."""
        if self._blocked_by_running_job():
            return
        self.dispose()
        self._on_export()

    def _navigate_characters(self) -> None:
        """Dispose and navigate to the character glossary view."""
        if self._blocked_by_running_job():
            return
        self.dispose()
        self._on_manage_characters()

    def _navigate_universe(self) -> None:
        """Dispose and navigate to the universe summary view."""
        if self._blocked_by_running_job():
            return
        self.dispose()
        self._on_manage_universe()
