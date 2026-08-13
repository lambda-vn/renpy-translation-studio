"""Provider configuration view: DeepL API key setup, reachable from settings."""

from collections.abc import Callable
from urllib.parse import urlparse

import deepl
import flet as ft
import httpx
from flet.controls.control_event import Event

from app import theme
from app.theme import border_all, focusable
from app.ui_thread import on_ui_thread, safe_update
from core.i18n import i18n
from core.logging_config import configure_logging
from core.settings import SettingsError, settings
from core.translation.context_builder import MAX_UNITS_PER_BATCH
from core.translation.providers.claude_provider import (
    CLAUDE_DEFAULT_MODEL,
    ClaudeProvider,
)
from core.translation.providers.deepl import DeepLProvider
from core.translation.providers.libretranslate import LibreTranslateProvider
from core.translation.providers.mistral_provider import (
    MISTRAL_DEFAULT_MODEL,
    MistralProvider,
)
from core.translation.providers.ollama import OllamaProvider
from core.translation.providers.registry import (
    MAX_OLLAMA_BATCH_SIZE,
    MIN_OLLAMA_BATCH_SIZE,
)

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _is_cleartext_remote(url: str) -> bool:
    """Check whether a URL would send data unencrypted to a non-local host.

    Args:
        url: The endpoint URL to inspect.

    Returns:
        True if the URL uses http:// and its host isn't a loopback address.
    """
    parsed = urlparse(url)
    return parsed.scheme == "http" and parsed.hostname not in _LOCAL_HOSTS


class ProviderConfigView:
    """Settings screen for configuring the DeepL API key."""

    def __init__(self, page: ft.Page, on_back: Callable[[], None]) -> None:
        """Initialize the provider configuration view.

        Args:
            page: The Flet page instance.
            on_back: Callback invoked after saving or skipping.
        """
        self._page = page
        self._on_back = on_back
        self._test_running = False

        self._title = ft.Text(
            i18n.t("provider_config.title"),
            size=26,
            weight=ft.FontWeight.W_700,
            color=theme.TEXT_H,
        )
        self._subtitle = ft.Text(
            i18n.t("provider_config.subtitle"),
            size=13,
            color=theme.TEXT_DIM,
        )

        self._api_key_label = ft.Text(
            i18n.t("provider_config.api_key_label").upper(),
            size=12,
            weight=ft.FontWeight.W_600,
            color=theme.TEXT_MUTED,
        )
        self._api_key_field = ft.TextField(
            value=settings.get("deepl_api_key") or "",
            hint_text=i18n.t("provider_config.api_key_hint"),
            hint_style=ft.TextStyle(color=theme.TEXT_HINT),
            password=True,
            can_reveal_password=True,
            bgcolor=theme.BG_INPUT,
            border_color=theme.BORDER_COLOR,
            focused_border_color=theme.FOCUS_RING,
            focused_border_width=theme.FOCUS_RING_WIDTH,
            color=theme.TEXT,
            cursor_color=theme.ACCENT,
            border_radius=11,
            height=48,
            width=380,
            content_padding=ft.Padding(left=14, right=14, top=0, bottom=0),
            on_change=self._on_key_changed,
        )

        self._status_text = ft.Text("", size=12.5)

        self._test_text = ft.Text(
            i18n.t("provider_config.test_connection"),
            size=13,
            weight=ft.FontWeight.W_500,
            color=theme.TEXT,
        )
        self._test_btn = focusable(
            ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.WIFI_TETHERING, size=15, color=theme.TEXT),
                        self._test_text,
                    ],
                    spacing=7,
                    tight=True,
                ),
                bgcolor=theme.BG_INPUT,
                border=border_all(1, theme.BORDER_STRONG),
                border_radius=8,
                padding=ft.Padding(left=14, right=14, top=9, bottom=9),
                ink=True,
            ),
            on_click=self._on_test_clicked,
        )

        self._save_text = ft.Text(
            i18n.t("common.save"),
            size=14.5,
            weight=ft.FontWeight.W_600,
            color=theme.ACCENT_ON,
        )
        self._save_btn = focusable(
            ft.Container(
                content=self._save_text,
                bgcolor=theme.ACCENT,
                border_radius=12,
                padding=ft.Padding(left=28, right=28, top=14, bottom=14),
                ink=True,
            ),
            on_click=self._on_save_clicked,
            radius=12,
        )
        self._later_text = ft.Text(
            i18n.t("provider_config.configure_later"),
            size=13,
            color=theme.TEXT_HINT,
        )
        self._later_btn = focusable(
            ft.Container(
                content=self._later_text,
                padding=ft.Padding(left=14, right=14, top=14, bottom=14),
                border_radius=12,
                ink=True,
            ),
            on_click=self._on_later_clicked,
            radius=12,
        )

        self._ollama_reliability_hint = ft.Text(
            i18n.t("provider_config.ollama_reliability_hint"),
            size=12,
            color=theme.WARNING,
        )
        self._ollama_endpoint_label = ft.Text(
            i18n.t("provider_config.ollama_endpoint_label").upper(),
            size=12,
            weight=ft.FontWeight.W_600,
            color=theme.TEXT_MUTED,
        )
        self._ollama_endpoint_field = ft.TextField(
            value=settings.get("ollama_endpoint") or "http://localhost:11434",
            bgcolor=theme.BG_INPUT,
            border_color=theme.BORDER_COLOR,
            focused_border_color=theme.FOCUS_RING,
            focused_border_width=theme.FOCUS_RING_WIDTH,
            color=theme.TEXT,
            cursor_color=theme.ACCENT,
            border_radius=11,
            height=48,
            width=380,
            content_padding=ft.Padding(left=14, right=14, top=0, bottom=0),
        )
        self._ollama_model_label = ft.Text(
            i18n.t("provider_config.ollama_model_label").upper(),
            size=12,
            weight=ft.FontWeight.W_600,
            color=theme.TEXT_MUTED,
        )
        saved_model = settings.get("ollama_model")
        self._ollama_model_dropdown = ft.Dropdown(
            value=saved_model,
            options=(
                [ft.dropdown.Option(key=saved_model, text=saved_model)]
                if saved_model
                else []
            ),
            hint_text=i18n.t("provider_config.ollama_model_hint"),
            on_select=self._on_badge_source_changed,
            bgcolor=theme.BG_INPUT,
            border_color=theme.BORDER_COLOR,
            focused_border_color=theme.FOCUS_RING,
            focused_border_width=theme.FOCUS_RING_WIDTH,
            color=theme.TEXT,
            border_radius=11,
            width=380,
            dense=True,
            content_padding=ft.Padding(left=14, right=0, top=0, bottom=0),
        )
        self._ollama_batch_size_label = ft.Text(
            i18n.t("provider_config.ollama_batch_size_label").upper(),
            size=12,
            weight=ft.FontWeight.W_600,
            color=theme.TEXT_MUTED,
        )
        self._ollama_batch_size_field = ft.TextField(
            value=settings.get("ollama_batch_size") or "",
            hint_text=str(MAX_UNITS_PER_BATCH),
            hint_style=ft.TextStyle(color=theme.TEXT_HINT),
            keyboard_type=ft.KeyboardType.NUMBER,
            bgcolor=theme.BG_INPUT,
            border_color=theme.BORDER_COLOR,
            focused_border_color=theme.FOCUS_RING,
            focused_border_width=theme.FOCUS_RING_WIDTH,
            color=theme.TEXT,
            cursor_color=theme.ACCENT,
            border_radius=11,
            height=48,
            width=380,
            content_padding=ft.Padding(left=14, right=14, top=0, bottom=0),
        )
        self._ollama_batch_size_help = ft.Text(
            i18n.t("provider_config.ollama_batch_size_hint"),
            color=theme.TEXT_HINT,
            size=11.5,
        )
        self._ollama_status_text = ft.Text("", size=12.5)
        self._ollama_test_text = ft.Text(
            i18n.t("provider_config.test_connection"),
            size=13,
            weight=ft.FontWeight.W_500,
            color=theme.TEXT,
        )
        self._ollama_test_btn = focusable(
            ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.WIFI_TETHERING, size=15, color=theme.TEXT),
                        self._ollama_test_text,
                    ],
                    spacing=7,
                    tight=True,
                ),
                bgcolor=theme.BG_INPUT,
                border=border_all(1, theme.BORDER_STRONG),
                border_radius=8,
                padding=ft.Padding(left=14, right=14, top=9, bottom=9),
                ink=True,
            ),
            on_click=self._on_ollama_test_clicked,
        )

        self._lt_warning = ft.Text(
            i18n.t("provider_config.libretranslate_public_warning"),
            size=12,
            color=theme.WARNING,
        )
        self._lt_cleartext_warning = ft.Text(
            i18n.t("provider_config.libretranslate_cleartext_warning"),
            size=12,
            color=theme.WARNING,
            visible=False,
        )
        self._lt_url_label = ft.Text(
            i18n.t("provider_config.libretranslate_url_label").upper(),
            size=12,
            weight=ft.FontWeight.W_600,
            color=theme.TEXT_MUTED,
        )
        self._lt_url_field = self._make_text_field(
            value=settings.get("libretranslate_url") or "",
            hint=i18n.t("provider_config.libretranslate_url_hint"),
            on_change=self._on_badge_source_changed,
        )
        self._lt_key_label = ft.Text(
            i18n.t("provider_config.libretranslate_api_key_label").upper(),
            size=12,
            weight=ft.FontWeight.W_600,
            color=theme.TEXT_MUTED,
        )
        self._lt_key_field = self._make_text_field(
            value=settings.get("libretranslate_api_key") or "",
            hint=i18n.t("provider_config.libretranslate_api_key_hint"),
            password=True,
            on_change=self._on_badge_source_changed,
        )
        self._lt_status_text = ft.Text("", size=12.5)
        self._lt_test_btn = self._make_test_button(self._on_lt_test_clicked)

        self._claude_key_label = ft.Text(
            i18n.t("provider_config.claude_api_key_label").upper(),
            size=12,
            weight=ft.FontWeight.W_600,
            color=theme.TEXT_MUTED,
        )
        self._claude_key_field = self._make_text_field(
            value=settings.get("claude_api_key") or "",
            hint=i18n.t("provider_config.claude_api_key_hint"),
            password=True,
            on_change=self._on_badge_source_changed,
        )
        self._claude_model_label = ft.Text(
            i18n.t("provider_config.claude_model_label").upper(),
            size=12,
            weight=ft.FontWeight.W_600,
            color=theme.TEXT_MUTED,
        )
        self._claude_model_field = self._make_text_field(
            value=settings.get("claude_model") or "",
            hint=CLAUDE_DEFAULT_MODEL,
        )
        self._claude_status_text = ft.Text("", size=12.5)
        self._claude_test_btn = self._make_test_button(self._on_claude_test_clicked)

        self._mistral_key_label = ft.Text(
            i18n.t("provider_config.mistral_api_key_label").upper(),
            size=12,
            weight=ft.FontWeight.W_600,
            color=theme.TEXT_MUTED,
        )
        self._mistral_key_field = self._make_text_field(
            value=settings.get("mistral_api_key") or "",
            hint=i18n.t("provider_config.mistral_api_key_hint"),
            password=True,
            on_change=self._on_badge_source_changed,
        )
        self._mistral_model_label = ft.Text(
            i18n.t("provider_config.mistral_model_label").upper(),
            size=12,
            weight=ft.FontWeight.W_600,
            color=theme.TEXT_MUTED,
        )
        self._mistral_model_field = self._make_text_field(
            value=settings.get("mistral_model") or "",
            hint=MISTRAL_DEFAULT_MODEL,
        )
        self._mistral_status_text = ft.Text("", size=12.5)
        self._mistral_test_btn = self._make_test_button(self._on_mistral_test_clicked)

        configured = i18n.t("provider_config.configured")
        self._deepl_badge = self._make_badge(configured, theme.SUCCESS)
        self._ollama_badge = self._make_badge(configured, theme.SUCCESS)
        self._lt_badge = self._make_badge(configured, theme.SUCCESS)
        self._claude_badge = self._make_badge(configured, theme.SUCCESS)
        self._mistral_badge = self._make_badge(configured, theme.SUCCESS)
        self._claude_beta_badge = self._make_badge(
            i18n.t("provider_config.beta_badge"),
            theme.WARNING,
            tooltip=i18n.t("provider_config.beta_hint"),
            visible=True,
        )
        self._mistral_beta_badge = self._make_badge(
            i18n.t("provider_config.beta_badge"),
            theme.WARNING,
            tooltip=i18n.t("provider_config.beta_hint"),
            visible=True,
        )
        self._refresh_badges()

        self._verbose_label = ft.Text(
            i18n.t("provider_config.verbose_logging_label"),
            size=13,
            weight=ft.FontWeight.W_600,
            color=theme.TEXT,
        )
        self._verbose_hint = ft.Text(
            i18n.t("provider_config.verbose_logging_hint"),
            size=12,
            color=theme.TEXT_HINT,
        )
        self._verbose_switch = ft.Switch(
            value=bool(settings.get("verbose_logging")),
            active_color=theme.ACCENT,
            inactive_thumb_color=theme.TEXT_HINT,
            inactive_track_color=theme.BG_INPUT,
            on_change=self._on_verbose_changed,
        )

    def _make_text_field(
        self,
        value: str,
        hint: str = "",
        password: bool = False,
        on_change: Callable[[Event[ft.TextField]], None] | None = None,
    ) -> ft.TextField:
        """Build a text field with the standard provider-config styling.

        Args:
            value: Initial field value.
            hint: Placeholder text shown when empty.
            password: Whether to mask the value (API keys).
            on_change: Optional change handler.

        Returns:
            A styled ft.TextField.
        """
        return ft.TextField(
            value=value,
            hint_text=hint,
            hint_style=ft.TextStyle(color=theme.TEXT_HINT),
            password=password,
            can_reveal_password=password,
            on_change=on_change,
            bgcolor=theme.BG_INPUT,
            border_color=theme.BORDER_COLOR,
            focused_border_color=theme.FOCUS_RING,
            focused_border_width=theme.FOCUS_RING_WIDTH,
            color=theme.TEXT,
            cursor_color=theme.ACCENT,
            border_radius=11,
            height=48,
            width=380,
            content_padding=ft.Padding(left=14, right=14, top=0, bottom=0),
        )

    def _make_test_button(
        self, on_click: Callable[[Event[ft.TextButton]], None]
    ) -> ft.TextButton:
        """Build a "Test connection" button with the standard styling.

        Args:
            on_click: Click handler for the button.

        Returns:
            A focusable button styled like every other test button.
        """
        return focusable(
            ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.WIFI_TETHERING, size=15, color=theme.TEXT),
                        ft.Text(
                            i18n.t("provider_config.test_connection"),
                            size=13,
                            weight=ft.FontWeight.W_500,
                            color=theme.TEXT,
                        ),
                    ],
                    spacing=7,
                    tight=True,
                ),
                bgcolor=theme.BG_INPUT,
                border=border_all(1, theme.BORDER_STRONG),
                border_radius=8,
                padding=ft.Padding(left=14, right=14, top=9, bottom=9),
                ink=True,
            ),
            on_click=on_click,
        )

    def _make_badge(
        self,
        label: str,
        color: str,
        tooltip: str | None = None,
        visible: bool = False,
    ) -> ft.Container:
        """Build a pill-shaped badge shown next to a provider title.

        Args:
            label: Short text displayed inside the badge.
            color: Text and border color.
            tooltip: Optional hover explanation.
            visible: Initial visibility; the "Configured" badges stay
                hidden until _refresh_badges() enables them.

        Returns:
            A pill-shaped ft.Container.
        """
        return ft.Container(
            content=ft.Text(
                label,
                size=11,
                weight=ft.FontWeight.W_600,
                color=color,
            ),
            border=border_all(1, color),
            border_radius=999,
            padding=ft.Padding(left=10, right=10, top=3, bottom=3),
            tooltip=tooltip,
            visible=visible,
        )

    def _make_section(
        self, title: str, badges: list[ft.Container], controls: list[ft.Control]
    ) -> ft.Container:
        """Build a collapsible provider section with a clickable header.

        Args:
            title: Provider display name shown in the header.
            badges: Badge controls shown next to the title.
            controls: The section body, hidden until expanded.

        Returns:
            A bordered ft.Container holding the header and the
            collapsible content.
        """
        content = ft.Container(
            content=ft.Column(controls, spacing=9),
            padding=ft.Padding(left=16, right=16, top=2, bottom=16),
            visible=False,
        )
        chevron = ft.Icon(ft.Icons.KEYBOARD_ARROW_DOWN, size=20, color=theme.TEXT_MUTED)

        def _toggle(_e: Event[ft.TextButton]) -> None:
            content.visible = not content.visible
            chevron.icon = (
                ft.Icons.KEYBOARD_ARROW_UP
                if content.visible
                else ft.Icons.KEYBOARD_ARROW_DOWN
            )
            self._page.update()

        header = focusable(
            ft.Container(
                content=ft.Row(
                    [
                        ft.Row(
                            [
                                ft.Text(
                                    title,
                                    size=16,
                                    weight=ft.FontWeight.W_700,
                                    color=theme.TEXT_H,
                                ),
                                *badges,
                            ],
                            spacing=12,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        chevron,
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                padding=ft.Padding(left=16, right=16, top=13, bottom=13),
                ink=True,
                border_radius=12,
            ),
            on_click=_toggle,
            radius=12,
            expand=True,
        )
        return ft.Container(
            content=ft.Column([header, content], spacing=0),
            border=border_all(1, theme.BORDER_COLOR),
            border_radius=12,
        )

    def _refresh_badges(self) -> None:
        """Sync each provider's "Configured" badge with its current fields."""
        lt_url = (self._lt_url_field.value or "").strip()
        lt_key = (self._lt_key_field.value or "").strip()
        self._deepl_badge.visible = bool((self._api_key_field.value or "").strip())
        self._ollama_badge.visible = bool(self._ollama_model_dropdown.value)
        self._lt_badge.visible = bool(lt_url)
        self._lt_cleartext_warning.visible = bool(lt_key) and _is_cleartext_remote(
            lt_url
        )
        self._claude_badge.visible = bool((self._claude_key_field.value or "").strip())
        self._mistral_badge.visible = bool(
            (self._mistral_key_field.value or "").strip()
        )

    def _on_badge_source_changed(
        self, _: Event[ft.TextField] | Event[ft.Dropdown]
    ) -> None:
        """Refresh the badges when a configuration field changes.

        Args:
            _: Unused change event.
        """
        self._refresh_badges()
        self._page.update()

    def build(self) -> ft.Control:
        """Build and return the view control tree.

        Returns:
            A Flet Control representing the provider config view.
        """
        return ft.Column(
            controls=[
                ft.Container(
                    expand=True,
                    content=ft.Column(
                        controls=[
                            ft.Column([self._title, self._subtitle], spacing=6),
                            ft.Column(
                                [
                                    self._make_section(
                                        i18n.t("provider_config.deepl_title"),
                                        [self._deepl_badge],
                                        [
                                            self._api_key_label,
                                            self._api_key_field,
                                            ft.Row([self._test_btn], spacing=12),
                                            self._status_text,
                                        ],
                                    ),
                                    self._make_section(
                                        i18n.t("provider_config.ollama_title"),
                                        [self._ollama_badge],
                                        [
                                            self._ollama_reliability_hint,
                                            self._ollama_endpoint_label,
                                            self._ollama_endpoint_field,
                                            self._ollama_model_label,
                                            self._ollama_model_dropdown,
                                            self._ollama_batch_size_label,
                                            self._ollama_batch_size_field,
                                            self._ollama_batch_size_help,
                                            ft.Row([self._ollama_test_btn], spacing=12),
                                            self._ollama_status_text,
                                        ],
                                    ),
                                    self._make_section(
                                        i18n.t("provider_config.libretranslate_title"),
                                        [self._lt_badge],
                                        [
                                            self._lt_warning,
                                            self._lt_url_label,
                                            self._lt_url_field,
                                            self._lt_key_label,
                                            self._lt_key_field,
                                            self._lt_cleartext_warning,
                                            ft.Row([self._lt_test_btn], spacing=12),
                                            self._lt_status_text,
                                        ],
                                    ),
                                    self._make_section(
                                        i18n.t("provider_config.claude_title"),
                                        [self._claude_badge, self._claude_beta_badge],
                                        [
                                            self._claude_key_label,
                                            self._claude_key_field,
                                            self._claude_model_label,
                                            self._claude_model_field,
                                            ft.Row([self._claude_test_btn], spacing=12),
                                            self._claude_status_text,
                                        ],
                                    ),
                                    self._make_section(
                                        i18n.t("provider_config.mistral_title"),
                                        [
                                            self._mistral_badge,
                                            self._mistral_beta_badge,
                                        ],
                                        [
                                            self._mistral_key_label,
                                            self._mistral_key_field,
                                            self._mistral_model_label,
                                            self._mistral_model_field,
                                            ft.Row(
                                                [self._mistral_test_btn], spacing=12
                                            ),
                                            self._mistral_status_text,
                                        ],
                                    ),
                                ],
                                spacing=12,
                            ),
                            ft.Container(height=1, bgcolor=theme.BORDER_COLOR),
                            ft.Row(
                                [
                                    ft.Column(
                                        [self._verbose_label, self._verbose_hint],
                                        spacing=2,
                                        expand=True,
                                    ),
                                    self._verbose_switch,
                                ],
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                            ft.Row(
                                [self._save_btn, self._later_btn],
                                spacing=4,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                        ],
                        spacing=32,
                        scroll=ft.ScrollMode.AUTO,
                    ),
                    padding=ft.Padding(left=60, right=60, top=60, bottom=40),
                ),
            ],
            expand=True,
            spacing=0,
        )

    def _on_key_changed(self, _: Event[ft.TextField]) -> None:
        """Clear the connection status when the API key is edited."""
        self._status_text.value = ""
        self._refresh_badges()
        self._page.update()

    def _run_connection_test(
        self, status_control: ft.Text, worker: Callable[[], None]
    ) -> None:
        """Run a blocking connection test on a background thread.

        Shows an immediate "testing" status so the UI stays responsive
        while the network request is in flight, and refuses to start a
        second test while one is already running.

        Args:
            status_control: The status text updated with the progress
                message; the worker is responsible for the final message.
            worker: Blocking callable performing the test and setting
                the final status itself.
        """
        if self._test_running:
            return
        self._test_running = True
        self._set_status(
            status_control, i18n.t("provider_config.testing"), theme.TEXT_HINT
        )
        self._page.update()

        def _run() -> None:
            try:
                worker()
            finally:
                self._test_running = False
                safe_update(self._page)

        self._page.run_thread(_run)

    def _on_test_clicked(self, _: Event[ft.TextButton]) -> None:
        """Test the entered API key against the DeepL API.

        Args:
            _: Unused click event.
        """
        key = (self._api_key_field.value or "").strip()
        if not key:
            self._show_status(
                i18n.t("translation.provider_not_configured").format(provider="DeepL"),
                theme.ERROR,
            )
            self._page.update()
            return

        def _worker() -> None:
            provider = DeepLProvider(api_key=key)
            try:
                used, limit = provider.get_character_usage()
                available = (
                    limit - used if used is not None and limit is not None else None
                )
                chars = (
                    f"{available:,}".replace(",", " ") if available is not None else "?"
                )
                self._show_status(
                    i18n.t("translation.connection_ok").format(chars=chars),
                    theme.SUCCESS,
                )
            except deepl.DeepLException:
                self._show_status(i18n.t("translation.connection_failed"), theme.ERROR)

        self._run_connection_test(self._status_text, _worker)

    def _on_save_clicked(self, _: Event[ft.TextButton]) -> None:
        """Persist the DeepL and Ollama settings, then return to the previous view.

        Rejects the whole save when the Ollama batch size is out of bounds
        or not a number, showing an error status instead.

        Args:
            _: Unused click event.
        """
        batch_size_text = (self._ollama_batch_size_field.value or "").strip()
        if batch_size_text:
            try:
                batch_size = int(batch_size_text)
            except ValueError:
                self._show_ollama_status(
                    self._batch_size_invalid_message(), theme.ERROR
                )
                self._page.update()
                return
            if not (MIN_OLLAMA_BATCH_SIZE <= batch_size <= MAX_OLLAMA_BATCH_SIZE):
                self._show_ollama_status(
                    self._batch_size_invalid_message(), theme.ERROR
                )
                self._page.update()
                return

        key = (self._api_key_field.value or "").strip()
        lt_url = (self._lt_url_field.value or "").strip()
        claude_key = (self._claude_key_field.value or "").strip()
        mistral_key = (self._mistral_key_field.value or "").strip()
        model = self._ollama_model_dropdown.value

        try:
            settings.set("deepl_api_key", key or None)

            endpoint = (self._ollama_endpoint_field.value or "").strip()
            settings.set("ollama_endpoint", endpoint or "http://localhost:11434")
            settings.set("ollama_model", model)
            settings.set("ollama_batch_size", batch_size_text or None)

            settings.set("libretranslate_url", lt_url or None)
            settings.set(
                "libretranslate_api_key",
                (self._lt_key_field.value or "").strip() or None,
            )
            settings.set("claude_api_key", claude_key or None)
            settings.set(
                "claude_model", (self._claude_model_field.value or "").strip() or None
            )
            settings.set("mistral_api_key", mistral_key or None)
            settings.set(
                "mistral_model",
                (self._mistral_model_field.value or "").strip() or None,
            )
        except SettingsError:
            self._show_status(
                i18n.t("provider_config.keyring_unavailable"), theme.ERROR
            )
            self._page.update()
            return

        configured = [
            ("deepl", key),
            ("ollama", model),
            ("libretranslate", lt_url),
            ("claude", claude_key),
            ("mistral", mistral_key),
        ]
        default = next((pid for pid, value in configured if value), None)
        settings.set("default_provider", default)
        self._on_back()

    def _on_later_clicked(self, _: Event[ft.TextButton]) -> None:
        """Return to the previous view without saving.

        Args:
            _: Unused click event.
        """
        self._on_back()

    def _show_status(self, message: str, color: str) -> None:
        """Show a message below the API key field.

        Args:
            message: Text to display.
            color: Hex color (ERROR or SUCCESS).
        """
        self._status_text.value = message
        self._status_text.color = color

    def _on_ollama_test_clicked(self, _: Event[ft.TextButton]) -> None:
        """Test the Ollama server and populate the model dropdown.

        Args:
            _: Unused click event.
        """
        endpoint = (self._ollama_endpoint_field.value or "").strip()

        def _worker() -> None:
            provider = OllamaProvider(
                endpoint=endpoint or "http://localhost:11434", model=""
            )
            if not provider.test_connection():
                self._show_ollama_status(
                    i18n.t("provider_config.ollama_connection_failed"), theme.ERROR
                )
                return

            try:
                models = provider.list_models()
            except httpx.HTTPError:
                self._show_ollama_status(
                    i18n.t("provider_config.ollama_connection_failed"), theme.ERROR
                )
                return

            if not models:
                self._show_ollama_status(
                    i18n.t("provider_config.ollama_no_models"), theme.WARNING
                )
                return

            on_ui_thread(self._page, self._fill_model_dropdown)(models)

        self._run_connection_test(self._ollama_status_text, _worker)

    def _fill_model_dropdown(self, models: list[str]) -> None:
        """List the models the server answered with, keeping the chosen one.

        Replaces the dropdown's options, the one thing a connection test
        does that flet's patch builder cannot survive being done from a
        background thread, hence the trip through on_ui_thread().

        Args:
            models: Model names the Ollama server reported.
        """
        current = self._ollama_model_dropdown.value
        self._ollama_model_dropdown.options = [
            ft.dropdown.Option(key=m, text=m) for m in models
        ]
        self._ollama_model_dropdown.value = current if current in models else models[0]
        self._show_ollama_status(
            i18n.t("provider_config.ollama_connection_ok").format(n=len(models)),
            theme.SUCCESS,
        )
        self._refresh_badges()

    def _batch_size_invalid_message(self) -> str:
        """Build the error message shown for an out-of-bounds batch size.

        Returns:
            The formatted, localized error message.
        """
        return i18n.t("provider_config.ollama_batch_size_invalid").format(
            min=MIN_OLLAMA_BATCH_SIZE, max=MAX_OLLAMA_BATCH_SIZE
        )

    def _show_ollama_status(self, message: str, color: str) -> None:
        """Show a message below the Ollama section controls.

        Args:
            message: Text to display.
            color: Hex color (ERROR, WARNING, or SUCCESS).
        """
        self._ollama_status_text.value = message
        self._ollama_status_text.color = color

    def _on_lt_test_clicked(self, _: Event[ft.TextButton]) -> None:
        """Test the LibreTranslate instance URL.

        Args:
            _: Unused click event.
        """
        url = (self._lt_url_field.value or "").strip()
        if not url:
            self._set_status(
                self._lt_status_text,
                i18n.t("translation.provider_not_configured").format(
                    provider="LibreTranslate"
                ),
                theme.ERROR,
            )
            self._page.update()
            return
        api_key = (self._lt_key_field.value or "").strip() or None

        def _worker() -> None:
            provider = LibreTranslateProvider(endpoint=url, api_key=api_key)
            if provider.test_connection():
                self._set_status(
                    self._lt_status_text,
                    i18n.t("provider_config.llm_connection_ok"),
                    theme.SUCCESS,
                )
            else:
                self._set_status(
                    self._lt_status_text,
                    i18n.t("provider_config.ollama_connection_failed"),
                    theme.ERROR,
                )

        self._run_connection_test(self._lt_status_text, _worker)

    def _on_claude_test_clicked(self, _: Event[ft.TextButton]) -> None:
        """Test the Anthropic API key with a minimal request.

        Args:
            _: Unused click event.
        """
        key = (self._claude_key_field.value or "").strip()
        if not key:
            self._set_status(
                self._claude_status_text,
                i18n.t("translation.provider_not_configured").format(provider="Claude"),
                theme.ERROR,
            )
            self._page.update()
            return
        model = (self._claude_model_field.value or "").strip() or CLAUDE_DEFAULT_MODEL

        def _worker() -> None:
            provider = ClaudeProvider(api_key=key, model=model)
            if provider.test_connection():
                self._set_status(
                    self._claude_status_text,
                    i18n.t("provider_config.llm_connection_ok"),
                    theme.SUCCESS,
                )
            else:
                self._set_status(
                    self._claude_status_text,
                    i18n.t("translation.connection_failed"),
                    theme.ERROR,
                )

        self._run_connection_test(self._claude_status_text, _worker)

    def _on_mistral_test_clicked(self, _: Event[ft.TextButton]) -> None:
        """Test the Mistral API key by listing models.

        Args:
            _: Unused click event.
        """
        key = (self._mistral_key_field.value or "").strip()
        if not key:
            self._set_status(
                self._mistral_status_text,
                i18n.t("translation.provider_not_configured").format(
                    provider="Mistral"
                ),
                theme.ERROR,
            )
            self._page.update()
            return
        model = (self._mistral_model_field.value or "").strip() or MISTRAL_DEFAULT_MODEL

        def _worker() -> None:
            provider = MistralProvider(api_key=key, model=model)
            if provider.test_connection():
                self._set_status(
                    self._mistral_status_text,
                    i18n.t("provider_config.llm_connection_ok"),
                    theme.SUCCESS,
                )
            else:
                self._set_status(
                    self._mistral_status_text,
                    i18n.t("translation.connection_failed"),
                    theme.ERROR,
                )

        self._run_connection_test(self._mistral_status_text, _worker)

    def _set_status(self, control: ft.Text, message: str, color: str) -> None:
        """Show a status message on the given text control.

        Args:
            control: The status text control to update.
            message: Text to display.
            color: Hex color (ERROR, WARNING, or SUCCESS).
        """
        control.value = message
        control.color = color

    def _on_verbose_changed(self, e: Event[ft.Switch]) -> None:
        """Persist the verbose logging toggle and apply it immediately.

        Args:
            e: Change event carrying the new switch value.
        """
        settings.set("verbose_logging", "1" if e.control.value else None)
        configure_logging()
