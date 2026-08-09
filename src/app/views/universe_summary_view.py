"""Universe summary view: free-form game context injected into LLM prompts."""

import logging
from collections.abc import Callable

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
    border_all,
    focusable,
)
from app.ui_thread import safe_update
from core.i18n import i18n
from core.settings import settings
from core.storage.repositories import ProjectMetaRepository, TranslationUnitRepository
from core.translation.providers.base import SupportsCompletion, TranslationProviderError
from core.translation.providers.registry import registry
from core.translation.universe_generator import UniverseGenerator

logger = logging.getLogger(__name__)

_META_KEY = "universe_summary"

_LLM_LABELS = {
    "ollama": "Ollama",
    "claude": "Claude",
    "mistral": "Mistral",
}


class UniverseSummaryView:
    """Edit the free-form universe summary sent to the LLM before translation."""

    def __init__(
        self,
        page: ft.Page,
        state: AppState,
        on_back: Callable[[], None],
    ) -> None:
        """Initialize the universe summary view.

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
        self._state = state
        self._on_back = on_back
        self._repo = ProjectMetaRepository(state.db.conn, state.db.lock)
        self._units_repo = TranslationUnitRepository(state.db.conn, state.db.lock)
        self._generating = False

        self._title = ft.Text(
            i18n.t("universe.title"),
            size=26,
            weight=ft.FontWeight.W_700,
            color=TEXT_H,
        )
        self._subtitle = ft.Text(i18n.t("universe.hint"), size=13, color=TEXT_DIM)
        self._summary_field = ft.TextField(
            value=self._repo.get(_META_KEY) or "",
            hint_text=i18n.t("universe.placeholder"),
            hint_style=ft.TextStyle(color=TEXT_HINT),
            bgcolor=BG_INPUT,
            border_color=BORDER_COLOR,
            focused_border_color=FOCUS_RING,
            focused_border_width=FOCUS_RING_WIDTH,
            color=TEXT,
            cursor_color=ACCENT,
            border_radius=11,
            multiline=True,
            min_lines=10,
            max_lines=18,
            content_padding=ft.Padding(left=14, right=14, top=12, bottom=12),
            on_change=self._on_summary_changed,
        )
        self._summary_label = ft.Text(
            i18n.t("universe.field_label").upper(),
            size=12,
            weight=ft.FontWeight.W_600,
            color=TEXT_MUTED,
        )
        self._length_text = ft.Text("", size=11.5, color=TEXT_HINT)
        self._refresh_length()
        available_llm = registry.available_llm()
        self._provider_dropdown = ft.Dropdown(
            value=self._pick_llm_provider(),
            label=i18n.t("translation.choose_provider_label"),
            options=[
                ft.dropdown.Option(key=pid, text=_LLM_LABELS.get(pid, pid))
                for pid in available_llm
            ],
            bgcolor=BG_INPUT,
            border_color=BORDER_COLOR,
            focused_border_color=FOCUS_RING,
            focused_border_width=FOCUS_RING_WIDTH,
            color=TEXT,
            border_radius=8,
            width=180,
            dense=True,
            content_padding=ft.Padding(left=10, right=0, top=0, bottom=0),
            visible=bool(available_llm),
        )
        self._generate_text = ft.Text(
            i18n.t("universe.generate"),
            size=13,
            weight=ft.FontWeight.W_500,
            color=TEXT,
        )
        self._generate_btn = focusable(
            ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.AUTO_AWESOME, size=15, color=TEXT),
                        self._generate_text,
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
            on_click=self._on_generate_clicked,
            disabled=not registry.available_llm(),
        )
        self._generate_ring = ft.ProgressRing(
            width=16, height=16, stroke_width=2, color=ACCENT, visible=False
        )
        self._generate_status = ft.Text("", size=12.5)
        self._generate_hint = ft.Text(
            i18n.t("universe.generate_no_llm"),
            size=12,
            color=TEXT_HINT,
            visible=not registry.available_llm(),
        )

        self._save_text = ft.Text(
            i18n.t("common.save"),
            size=14.5,
            weight=ft.FontWeight.W_600,
            color=ACCENT_ON,
        )
        self._save_btn = focusable(
            ft.Container(
                content=self._save_text,
                bgcolor=ACCENT,
                border_radius=12,
                padding=ft.Padding(left=28, right=28, top=14, bottom=14),
                ink=True,
            ),
            on_click=self._on_save_clicked,
            radius=12,
        )

    def build(self) -> ft.Control:
        """Build and return the view control tree.

        Returns:
            A Flet Control representing the universe summary view.
        """
        return ft.Column(
            controls=[
                ft.Container(
                    expand=True,
                    content=ft.Column(
                        controls=[
                            build_back_link(i18n.t("universe.back"), self._on_back),
                            ft.Column([self._title, self._subtitle], spacing=6),
                            self._build_purpose_card(),
                            self._build_generate_card(),
                            ft.Column(
                                [
                                    self._summary_label,
                                    self._summary_field,
                                    self._length_text,
                                ],
                                spacing=8,
                                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                            ),
                            self._save_btn,
                        ],
                        spacing=22,
                        scroll=ft.ScrollMode.AUTO,
                    ),
                    padding=ft.Padding(left=32, right=32, top=30, bottom=40),
                ),
            ],
            expand=True,
            spacing=0,
        )

    @staticmethod
    def _build_purpose_card() -> ft.Control:
        """Build the panel saying what the summary actually changes.

        The screen offers a blank page and asks for prose about a game the
        application cannot describe on its own, which is why it read as
        empty. What goes in it, and what it buys, is the one thing the
        screen has to supply.

        Returns:
            A bordered panel listing what the summary is used for.
        """
        rows = [
            ("universe.purpose_tone", ft.Icons.RECORD_VOICE_OVER_OUTLINED),
            ("universe.purpose_names", ft.Icons.BADGE_OUTLINED),
            ("universe.purpose_terms", ft.Icons.MENU_BOOK_OUTLINED),
        ]
        return ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        i18n.t("universe.purpose_title"),
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

    def _build_generate_card(self) -> ft.Control:
        """Build the panel offering to draft the summary with an LLM.

        Returns:
            A bordered panel holding the generate action and its warnings.
        """
        return ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        i18n.t("universe.generate_title"),
                        size=13,
                        weight=ft.FontWeight.W_600,
                        color=TEXT_H,
                    ),
                    ft.Text(
                        i18n.t("universe.generate_desc"),
                        size=12.5,
                        color=TEXT_MUTED,
                    ),
                    ft.Row(
                        [
                            self._provider_dropdown,
                            self._generate_btn,
                            self._generate_ring,
                            self._generate_status,
                        ],
                        spacing=12,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    self._generate_hint,
                ],
                spacing=9,
                tight=True,
            ),
            border=border_all(1, BORDER_COLOR),
            border_radius=12,
            padding=ft.Padding(left=18, right=18, top=15, bottom=15),
        )

    def _refresh_length(self) -> None:
        """Update the character count shown under the summary field."""
        length = len(self._summary_field.value or "")
        self._length_text.value = (
            i18n.t("universe.length").format(n=length) if length else ""
        )

    def _on_summary_changed(self, _e: Event[ft.TextField]) -> None:
        """Keep the character count in step with the field.

        Args:
            _e: Unused change event.
        """
        self._refresh_length()
        self._page.update()

    def _on_save_clicked(self, _e: Event[ft.Container]) -> None:
        """Persist the summary and return to the previous view.

        Args:
            _e: Unused click event.
        """
        self._repo.set(_META_KEY, (self._summary_field.value or "").strip())
        self._on_back()

    @staticmethod
    def _pick_llm_provider() -> str | None:
        """Return the LLM provider the choice starts on.

        Prefers the default provider when it is an LLM, otherwise the
        first configured LLM provider. Only the initial selection: which
        provider actually generates is whatever the dropdown holds when
        the button is pressed.

        Returns:
            A provider id, or None if no LLM provider is configured.
        """
        available = registry.available_llm()
        if not available:
            return None
        default = settings.get("default_provider")
        return default if default in available else available[0]

    def _on_generate_clicked(self, _e: Event[ft.Container]) -> None:
        """Show the data-sharing confirmation dialog before generating.

        Shown on every click, even if previously acknowledged — sampled
        game dialogue is sent to the selected AI provider each time.

        Args:
            _e: Unused click event.
        """
        if self._generating:
            return
        provider_id = self._provider_dropdown.value
        if not provider_id:
            return
        self._page.show_dialog(self._build_generate_dialog(provider_id))

    def _build_generate_dialog(self, provider_id: str) -> ft.AlertDialog:
        """Build the confirmation dialog shown before AI generation.

        Args:
            provider_id: The LLM provider that will receive the dialogue.

        Returns:
            An AlertDialog warning that game dialogue is sent to the
            provider.
        """
        label = _LLM_LABELS.get(provider_id, provider_id)
        return ft.AlertDialog(
            modal=True,
            title=ft.Text(
                i18n.t("universe.generate_confirm_title"),
                size=18,
                weight=ft.FontWeight.W_600,
                color=TEXT_H,
            ),
            bgcolor="#1a1822",
            content=ft.Text(
                i18n.t("universe.generate_confirm_message").format(provider=label),
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
                    i18n.t("universe.generate_confirm_action"),
                    lambda _e: self._on_generate_confirmed(provider_id),
                    tone="accent",
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

    def _on_generate_confirmed(self, provider_id: str) -> None:
        """Start the background generation after user confirmation.

        Args:
            provider_id: The LLM provider to generate with.
        """
        self._page.pop_dialog()
        self._generating = True
        self._generate_ring.visible = True
        self._generate_status.value = i18n.t("universe.generating")
        self._generate_status.color = TEXT_MUTED
        self._page.update()
        self._page.run_thread(self._run_generation, provider_id)

    def _run_generation(self, provider_id: str) -> None:
        """Generate the summary in a background thread and pre-fill the field.

        The result is only placed into the text field — the user must
        explicitly save it.

        Args:
            provider_id: The LLM provider to generate with.
        """
        try:
            provider = registry.get(provider_id)
            if not isinstance(provider, SupportsCompletion):
                raise TranslationProviderError(
                    f"Provider {provider_id} cannot generate text."
                )
            units = self._units_repo.get_all()
            if not units:
                self._generate_status.value = i18n.t("universe.generate_no_units")
                self._generate_status.color = ERROR
                return
            target_lang = self._state.target_language or self._state.source_language
            summary = UniverseGenerator().generate(units, provider, target_lang)
            self._summary_field.value = summary
            self._generate_status.value = i18n.t("universe.generate_done")
            self._generate_status.color = SUCCESS
        except (ValueError, TranslationProviderError) as exc:
            logger.warning("Universe summary generation failed: %s", exc)
            self._generate_status.value = i18n.t("universe.generate_failed")
            self._generate_status.color = ERROR
        finally:
            self._generating = False
            self._generate_ring.visible = False
            safe_update(self._page)
