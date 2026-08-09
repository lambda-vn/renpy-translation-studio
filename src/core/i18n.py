"""Internationalisation module with live locale switching support."""

import json
from collections.abc import Callable
from pathlib import Path

SUPPORTED_LOCALES = ["en", "fr"]
DEFAULT_LOCALE = "en"
LOCALES_DIR = Path(__file__).parent.parent / "locales"


class I18n:
    """Simple key-based translator with live locale switching.

    All registered listeners are called when the locale changes,
    so Flet views can update their controls without a full page reload.
    """

    def __init__(self) -> None:
        """Initialize with the default locale loaded."""
        self._locale: str = DEFAULT_LOCALE
        self._strings: dict[str, object] = {}
        self._listeners: list[Callable[[], None]] = []
        self._load(DEFAULT_LOCALE)

    def _load(self, locale: str) -> None:
        """Load the JSON file for the given locale.

        Args:
            locale: Locale code to load (e.g. "en", "fr").
        """
        path = LOCALES_DIR / f"{locale}.json"
        with path.open(encoding="utf-8") as f:
            self._strings = json.load(f)

    def set_locale(self, locale: str) -> None:
        """Switch the active locale and notify all registered listeners.

        Args:
            locale: Locale code to switch to.

        Raises:
            ValueError: If the locale is not in SUPPORTED_LOCALES.
        """
        if locale not in SUPPORTED_LOCALES:
            raise ValueError(f"Unsupported locale: {locale}")
        self._locale = locale
        self._load(locale)
        for listener in self._listeners:
            listener()

    def t(self, key: str) -> str:
        """Translate a dot-separated key (e.g. 'onboarding.title').

        Returns the key itself if not found, so missing translations
        are visible without crashing.

        Args:
            key: Dot-separated translation key.

        Returns:
            Translated string, or the key itself if not found.
        """
        parts = key.split(".")
        node: object = self._strings
        for part in parts:
            if not isinstance(node, dict):
                return key
            node = node.get(part, key)
        return str(node)

    def on_locale_change(self, listener: Callable[[], None]) -> None:
        """Register a callback to be called when the locale changes.

        Args:
            listener: Callable invoked on every locale switch.
        """
        self._listeners.append(listener)

    def remove_listener(self, listener: Callable[[], None]) -> None:
        """Unregister a previously registered listener.

        Args:
            listener: The callable to remove.
        """
        self._listeners = [ln for ln in self._listeners if ln is not listener]

    @property
    def locale(self) -> str:
        """Return the currently active locale code."""
        return self._locale


i18n = I18n()
