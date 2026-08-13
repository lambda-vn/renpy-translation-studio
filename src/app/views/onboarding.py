"""Onboarding view shown on first launch: UI language and SDK path."""

from collections.abc import Callable
from pathlib import Path

import flet as ft
from flet.controls.control_event import Event

from app import theme
from app.theme import border_all, focusable
from core.i18n import SUPPORTED_LOCALES, i18n
from core.settings import settings

_LOCALE_OPTIONS = [
    ft.dropdown.Option(key="en", text="English"),
    ft.dropdown.Option(key="fr", text="Français"),
]

_SDK_DOWNLOAD_URL = "https://www.renpy.org/latest.html"


def _sdk_is_valid(path: Path) -> bool:
    """Return True if path points to a Ren'Py executable.

    Args:
        path: Path to test.

    Returns:
        True if renpy.exe or renpy.py is found in the directory.
    """
    if path.is_file():
        return path.name.lower() in ("renpy.exe", "renpy.py", "renpy.sh")
    if path.is_dir():
        return any(
            (path / name).exists() for name in ("renpy.exe", "renpy.py", "renpy.sh")
        )
    return False


class OnboardingView:
    """First-launch screen for language selection and SDK setup."""

    def __init__(self, page: ft.Page, on_done: Callable[[], None]) -> None:
        """Initialize the onboarding view.

        Args:
            page: The Flet page instance.
            on_done: Callback invoked when the user clicks "Get started".
        """
        self._page = page
        self._on_done = on_done

        self._title = ft.Text(
            i18n.t("onboarding.title"),
            size=26,
            weight=ft.FontWeight.W_700,
            color=theme.TEXT_H,
        )
        self._subtitle = ft.Text(
            i18n.t("onboarding.subtitle"),
            size=13,
            color=theme.TEXT_DIM,
        )

        self._lang_label = ft.Text(
            i18n.t("onboarding.language_label").upper(),
            size=12,
            weight=ft.FontWeight.W_600,
            color=theme.TEXT_MUTED,
        )
        self._lang_dropdown = ft.Dropdown(
            options=_LOCALE_OPTIONS,
            value=i18n.locale,
            bgcolor=theme.BG_INPUT,
            border_color=theme.BORDER_COLOR,
            focused_border_color=theme.FOCUS_RING,
            focused_border_width=theme.FOCUS_RING_WIDTH,
            color=theme.TEXT,
            border_radius=11,
            height=48,
            dense=True,
            width=220,
            on_select=self._on_locale_changed,
        )

        self._sdk_label = ft.Text(
            i18n.t("onboarding.sdk_label").upper(),
            size=12,
            weight=ft.FontWeight.W_600,
            color=theme.TEXT_MUTED,
        )
        self._sdk_hint = ft.Text(
            i18n.t("onboarding.sdk_hint"),
            size=11.5,
            color=theme.TEXT_HINT,
        )
        self._sdk_download_link = focusable(
            ft.Container(
                content=ft.Text(
                    i18n.t("onboarding.sdk_download"),
                    size=11.5,
                    weight=ft.FontWeight.W_600,
                    color=theme.ACCENT,
                ),
                ink=True,
                border_radius=6,
                padding=ft.Padding(left=4, right=4, top=2, bottom=2),
            ),
            on_click=self._on_sdk_download_clicked,
            radius=6,
        )
        self._sdk_examples = ft.Text(
            i18n.t("onboarding.sdk_examples"),
            size=11,
            color=theme.TEXT_HINT,
        )
        self._sdk_path_label = ft.Text(
            settings.get("sdk_path") or "",
            size=13,
            color=theme.TEXT_PATH,
        )
        self._sdk_status = ft.Text("", size=12)
        self._sdk_browse_text = ft.Text(
            i18n.t("onboarding.sdk_browse"),
            size=13,
            weight=ft.FontWeight.W_500,
            color=theme.TEXT,
        )
        self._sdk_browse_btn = focusable(
            ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.FOLDER_OPEN, size=15, color=theme.TEXT),
                        self._sdk_browse_text,
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
            on_click=self._on_sdk_clicked,
        )

        self._finish_text = ft.Text(
            i18n.t("onboarding.finish"),
            size=14.5,
            weight=ft.FontWeight.W_600,
            color=theme.ACCENT_ON,
        )
        self._finish_btn = focusable(
            ft.Container(
                content=self._finish_text,
                bgcolor=theme.ACCENT,
                border_radius=12,
                padding=ft.Padding(left=28, right=28, top=14, bottom=14),
                ink=True,
            ),
            on_click=self._on_finish_clicked,
            radius=12,
        )

        if settings.get("sdk_path"):
            self._apply_sdk_path(Path(settings.get("sdk_path")))  # type: ignore[arg-type]

    def build(self) -> ft.Control:
        """Build and return the view control tree.

        Returns:
            A Flet Control representing the onboarding view.
        """
        return ft.Column(
            controls=[
                ft.Container(
                    expand=True,
                    content=ft.Column(
                        controls=[
                            ft.Column(
                                [
                                    ft.Image(
                                        src=theme.logo_asset(256),
                                        width=96,
                                        height=96,
                                    ),
                                    ft.Column(
                                        [self._title, self._subtitle],
                                        spacing=6,
                                    ),
                                ],
                                spacing=16,
                            ),
                            ft.Column(
                                [self._lang_label, self._lang_dropdown],
                                spacing=9,
                            ),
                            ft.Column(
                                [
                                    self._sdk_label,
                                    self._sdk_hint,
                                    self._sdk_download_link,
                                    self._sdk_examples,
                                    ft.Row(
                                        [
                                            self._sdk_browse_btn,
                                            self._sdk_path_label,
                                        ],
                                        spacing=12,
                                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                    ),
                                    self._sdk_status,
                                ],
                                spacing=8,
                            ),
                            self._finish_btn,
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

    def _on_locale_changed(self, e: Event[ft.Dropdown]) -> None:
        """Switch locale and persist the choice.

        Args:
            e: The dropdown select event.
        """
        locale = e.control.value or "en"
        if locale in SUPPORTED_LOCALES:
            i18n.set_locale(locale)
            settings.set("locale", locale)

    async def _on_sdk_download_clicked(self, _: Event[ft.TextButton]) -> None:
        """Open the Ren'Py download page in the system browser.

        Goes through UrlLauncher rather than Page.launch_url(), deprecated
        since Flet 0.90, and is awaited: the launcher is a coroutine, and
        a handler that only builds it opens nothing at all.

        Args:
            _: Unused click event.
        """
        await ft.UrlLauncher().launch_url(_SDK_DOWNLOAD_URL)

    async def _on_sdk_clicked(self, _: Event[ft.TextButton]) -> None:
        """Open a file picker to select the Ren'Py executable.

        Args:
            _: Unused click event.
        """
        results = await ft.FilePicker().pick_files(allow_multiple=False)
        if results and results[0].path:
            path = Path(results[0].path)
            self._apply_sdk_path(path)
            settings.set("sdk_path", str(path))
            self._page.update()

    def _apply_sdk_path(self, path: Path) -> None:
        """Update SDK path display and validation status.

        Args:
            path: Selected filesystem path.
        """
        self._sdk_path_label.value = str(path)
        if _sdk_is_valid(path):
            self._sdk_status.value = i18n.t("onboarding.sdk_valid")
            self._sdk_status.color = theme.SUCCESS
        else:
            self._sdk_status.value = i18n.t("onboarding.sdk_invalid")
            self._sdk_status.color = theme.ERROR

    def _on_finish_clicked(self, _: Event[ft.TextButton]) -> None:
        """Navigate to project setup unless the chosen SDK path is wrong.

        A game ships the engine that extracts it, in the version its own
        sources were written for, so leaving with no SDK at all is the
        ordinary case and goes through. A path that was picked and does
        not name a Ren'Py launcher is another matter: it is a mistake
        made on this screen, and letting it through would only surface
        the day an extraction needs the fallback.

        The locale is written on the way out even when it never changed:
        first launch is "no settings file yet", and leaving without ever
        writing one would put this screen back up at every start.

        Args:
            _: Unused click event.
        """
        saved = settings.get("sdk_path")
        if saved and not _sdk_is_valid(Path(saved)):
            self._sdk_status.value = i18n.t("onboarding.sdk_invalid")
            self._sdk_status.color = theme.ERROR
            self._page.update()
            return
        settings.set("locale", i18n.locale)
        self._on_done()
