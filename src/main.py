"""Entry point for Ren'Py Translation Studio."""

from collections.abc import Callable
from typing import Protocol

import flet as ft

from app import palettes, shortcuts, theme
from app.components.app_header import build_app_header
from app.components.help_dialog import build_help_dialog
from app.components.settings_dialog import build_settings_dialog
from app.dialogs import close_top_alert_dialog, top_alert_dialog
from app.state import AppState
from app.views.character_glossary_view import CharacterGlossaryView
from app.views.export_view import ExportView
from app.views.onboarding import OnboardingView
from app.views.project_setup import ProjectSetupView
from app.views.provider_config import ProviderConfigView
from app.views.review_view import ReviewView
from app.views.universe_summary_view import UniverseSummaryView
from core.i18n import i18n
from core.logging_config import configure_logging
from core.settings import settings


class DisposableView(Protocol):
    """A view holding more than its own controls.

    Clearing the page drops a view's controls but not what it installed
    on the page itself, so such a view has to be told when it is being
    replaced.
    """

    def may_leave(self) -> bool:
        """Return whether the view can be replaced without losing work."""

    def dispose(self) -> None:
        """Release everything the view registered outside its controls."""


def _page_theme() -> ft.Theme:
    """Build the Material theme backing the controls we do not paint.

    Most of the interface carries its own colours, but not all of it: the
    ink ripple of every clickable container, the popup menu items, the
    text cursor and the selection handles come from Material's own
    scheme. Left to Flet's default that scheme is a dark one, which is
    invisible work as long as the application is dark and glaring the
    moment it is not.

    Returns:
        The theme to hand to both of the page's theme slots.
    """
    return ft.Theme(
        color_scheme=ft.ColorScheme(
            primary=theme.ACCENT,
            on_primary=theme.ACCENT_ON,
            surface=theme.BG,
            on_surface=theme.TEXT,
            surface_container=theme.BG_MENU,
            outline=theme.BORDER_COLOR,
            error=theme.ERROR,
        ),
        popup_menu_theme=ft.PopupMenuTheme(
            color=theme.BG_MENU,
            icon_color=theme.TEXT_MUTED,
            label_text_style=ft.TextStyle(size=13, color=theme.TEXT),
            shape=ft.RoundedRectangleBorder(radius=10),
        ),
    )


def apply_page_theme(page: ft.Page) -> None:
    """Repaint the page itself with the palette now active.

    Both theme slots get the same object. Flet reads `theme` in light
    mode and `dark_theme` in dark mode, and the palette has already
    resolved which one of those we are in, so filling only one would
    leave the popup menus and the ink ripple to Material's defaults
    exactly half the time.

    Args:
        page: The page to repaint. Its controls are not touched; the
            caller rebuilds them.
    """
    page.bgcolor = theme.BG
    if (settings.get("theme") or palettes.SYSTEM) == palettes.SYSTEM:
        page.theme_mode = ft.ThemeMode.SYSTEM
    elif theme.active_theme().dark:
        page.theme_mode = ft.ThemeMode.DARK
    else:
        page.theme_mode = ft.ThemeMode.LIGHT
    built = _page_theme()
    page.theme = built
    page.dark_theme = built


def main(page: ft.Page) -> None:
    """Configure and render the main application page.

    Args:
        page: The Flet page instance.
    """
    configure_logging()

    page.title = "Ren'Py Translation Studio"
    page.padding = 0
    page.window.min_width = 800
    page.window.min_height = 700
    page.window.width = 1000
    page.window.height = 820
    page.window.maximized = True

    saved_locale = settings.get("locale") or "en"
    i18n.set_locale(saved_locale)
    theme.apply_setting(page.platform_brightness)
    apply_page_theme(page)

    state = AppState()

    current_show: Callable[[], None] = lambda: None  # noqa: E731 - set by first show_*
    current_view: DisposableView | None = None

    def enter(show: Callable[[], None]) -> bool:
        """Leave the current view before the next one is built.

        The review view installs the keyboard shortcuts on the page, and
        those outlive its controls: an undisposed review still answers
        Ctrl+S from whatever screen replaced it, writing the whole
        project from behind another view. Every navigation goes through
        here, including the ones that reach a view from the settings
        dialog rather than from the view itself.

        Which is why the outgoing view is asked first: disposing a review
        cancels the translation it is running, and the settings dialog
        reaches the provider screen without passing any of that view's
        own checks.

        Args:
            show: The view being entered, re-run on a locale change.

        Returns:
            True when the navigation may proceed. False when the current
            view refused it, having said so itself; the caller must then
            build nothing.
        """
        nonlocal current_show, current_view
        if current_view is not None and not current_view.may_leave():
            return False
        current_show = show
        if current_view is not None:
            current_view.dispose()
            current_view = None
        return True

    def render(content: ft.Control) -> None:
        """Clear the page and render the persistent header above the view.

        Args:
            content: The current view's built control tree.
        """
        page.controls.clear()
        header = build_app_header(
            on_settings_click=lambda _: open_settings(),
            on_help_click=lambda _: open_help(),
            game_name=state.game_name,
            target_language=state.target_language,
        )
        page.add(ft.Column([header, content], expand=True, spacing=0))

    def open_help() -> None:
        """Show the shortcut list, unless a dialog is already in front.

        Stacking it over an open dialog would bury the one the user was
        answering under a list they can only read, which is the exact
        situation the help is supposed to get them out of.
        """
        if top_alert_dialog(page) is None:
            page.show_dialog(build_help_dialog(page))

    def run_global_shortcut(action: str) -> bool:
        """Run one of the shortcuts that work on every screen.

        Shared with the review view, which owns the page handler while it
        is up and would otherwise have to reimplement these two.

        Args:
            action: The action name declared in shortcuts.GLOBAL_SHORTCUTS.

        Returns:
            True when the action ran, False when it had nothing to do.

        Raises:
            KeyError: If the table names an action nothing implements.
        """
        match action:
            case "open_help":
                open_help()
                return True
            case "close_dialog":
                return close_top_alert_dialog(page)
            case _:
                raise KeyError(f"Unbound global shortcut action: {action}")

    def open_settings() -> None:
        """Show the settings dialog, rebuilding the view only if it must.

        Rebuilding drops whatever the view held: the setup screen goes
        back to its project list, losing a form half filled in. The SDK
        path is the one setting a built view reads and cannot refresh on
        its own, so it alone is worth that cost. A locale change already
        rebuilds through i18n.on_locale_change().
        """
        sdk_before = settings.get("sdk_path")

        def on_close() -> None:
            if settings.get("sdk_path") != sdk_before:
                current_show()

        page.show_dialog(
            build_settings_dialog(
                page,
                on_configure_provider=lambda: show_provider_config(current_show),
                on_close=on_close,
            )
        )

    def show_setup() -> None:
        """Render the project setup view."""
        if not enter(show_setup):
            return
        view = ProjectSetupView(
            page,
            state,
            on_done=show_review,
        )
        render(view.build())

    def show_review() -> None:
        """Render the translation review view."""
        nonlocal current_view
        if not enter(show_review):
            return
        view = ReviewView(
            page,
            state,
            on_export=show_export,
            on_back=show_setup,
            on_configure_provider=lambda: show_provider_config(current_show),
            on_manage_characters=show_characters,
            on_manage_universe=show_universe_summary,
            on_global_shortcut=run_global_shortcut,
        )
        current_view = view
        render(view.build())

    def show_provider_config(on_back: Callable[[], None]) -> None:
        """Render the provider configuration view.

        Args:
            on_back: View to return to after saving or skipping.
        """
        if not enter(lambda: show_provider_config(on_back)):
            return
        view = ProviderConfigView(page, on_back=on_back)
        render(view.build())

    def show_characters() -> None:
        """Render the character glossary view."""
        if not enter(show_characters):
            return
        view = CharacterGlossaryView(page, state, on_back=show_review)
        render(view.build())

    def show_universe_summary() -> None:
        """Render the universe summary view."""
        if not enter(show_universe_summary):
            return
        view = UniverseSummaryView(page, state, on_back=show_review)
        render(view.build())

    def show_export() -> None:
        """Render the export (zip) view."""
        if not enter(show_export):
            return
        view = ExportView(page, state, on_back=show_review, on_setup=show_setup)
        render(view.build())

    def show_onboarding() -> None:
        """Render the onboarding view."""
        if not enter(show_onboarding):
            return
        view = OnboardingView(page, on_done=show_setup)
        render(view.build())

    def rerender() -> None:
        """Re-render the current view so it reflects the active locale.

        Drops itself when the session it belongs to is gone. The i18n
        singleton lives in the module and outlives the page, while this
        listener closes over one particular session: a second window in
        the same process, which a hot reload also produces, would find
        the first one's listener still registered and re-render a page
        that no longer exists. main() sets the saved locale before
        registering anything, so the stale listener is reached on the
        very first line of the new session.
        """
        try:
            _ = page.session
        except RuntimeError:
            i18n.remove_listener(rerender)
            return
        current_show()

    def repaint() -> None:
        """Re-render the current view so it reflects the active theme.

        Drops itself when its session is gone, for the same reason
        rerender() does: the palette is a module singleton outliving the
        page, so a second window would find this one's listener still
        registered.

        A view refusing to leave, which the review does while it is
        translating, keeps the colours it was built with until the next
        navigation. That is already what a locale change does.
        """
        try:
            _ = page.session
        except RuntimeError:
            theme.remove_listener(repaint)
            return
        apply_page_theme(page)
        current_show()

    def on_brightness_change(_e: ft.PlatformBrightnessChangeEvent) -> None:
        """Follow the host platform when the settings say to follow it.

        Args:
            _e: The event, whose brightness is read back from the page so
                a stale value can never be applied.
        """
        if (settings.get("theme") or palettes.SYSTEM) != palettes.SYSTEM:
            return
        theme.apply_setting(page.platform_brightness)

    async def on_window_event(e: ft.WindowEvent[ft.Window]) -> None:
        """Let the view being closed write what it still holds.

        The review view keeps the last keystrokes in memory for a moment
        before committing them, so closing the window is a way out like
        any other and has to flush first. The native close is intercepted
        (prevent_close) to make room for that, then destroy() ends the
        app without going through the interception again. The flush is
        guarded: a view failing to close itself must not leave a window
        nothing can shut.

        Args:
            e: The window event; only CLOSE is acted on.
        """
        if e.type is not ft.WindowEventType.CLOSE:
            return
        try:
            if current_view is not None:
                current_view.dispose()
        finally:
            await page.window.destroy()

    async def on_keyboard(e: ft.KeyboardEvent) -> None:
        """Run the app-wide shortcuts, whatever screen is showing.

        Installed app-wide, since help and dialogs exist on every screen.
        The review view takes the page handler over for its own shortcuts,
        defers to this table first, and puts this handler back when it
        leaves.

        Args:
            e: The key event.
        """
        shortcut = shortcuts.match(
            str(e.key).upper(),
            ctrl=bool(e.ctrl) or bool(e.meta),
            shift=bool(e.shift),
            alt=bool(e.alt),
            table=shortcuts.GLOBAL_SHORTCUTS,
        )
        if shortcut is not None:
            run_global_shortcut(shortcut.action)

    page.window.prevent_close = True
    page.window.on_event = on_window_event
    page.on_keyboard_event = on_keyboard
    page.on_platform_brightness_change = on_brightness_change

    i18n.on_locale_change(rerender)
    theme.on_theme_change(repaint)

    if settings.is_first_launch:
        show_onboarding()
    else:
        show_setup()


if __name__ == "__main__":
    ft.run(main)
