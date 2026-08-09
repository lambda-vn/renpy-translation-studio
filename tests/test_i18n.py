"""Unit tests for core.i18n.I18n."""

import pytest

from core.i18n import SUPPORTED_LOCALES, I18n


@pytest.fixture()
def fresh_i18n() -> I18n:
    """Return a fresh I18n instance (not the global singleton)."""
    return I18n()


def test_existing_key_returns_translation(fresh_i18n: I18n) -> None:
    """A known key returns the correct translated string."""
    assert fresh_i18n.t("onboarding.title") == "Welcome to Ren'Py Translation Studio"


def test_missing_key_returns_key_itself(fresh_i18n: I18n) -> None:
    """An unknown key is returned as-is instead of raising."""
    assert fresh_i18n.t("no.such.key") == "no.such.key"


def test_locale_change_notifies_listener(fresh_i18n: I18n) -> None:
    """Switching locale calls all registered listeners exactly once."""
    called: list[str] = []

    def listener() -> None:
        called.append(fresh_i18n.locale)

    fresh_i18n.on_locale_change(listener)
    fresh_i18n.set_locale("fr")
    assert called == ["fr"]


def test_locale_change_updates_translation(fresh_i18n: I18n) -> None:
    """After switching to 'fr', t() returns the French string."""
    fresh_i18n.set_locale("fr")
    assert fresh_i18n.t("onboarding.finish") == "Commencer"


def test_unsupported_locale_raises(fresh_i18n: I18n) -> None:
    """set_locale() with an unknown code raises ValueError."""
    with pytest.raises(ValueError, match="Unsupported locale"):
        fresh_i18n.set_locale("zz")


def test_remove_listener_stops_notifications(fresh_i18n: I18n) -> None:
    """remove_listener() prevents further calls to the callback."""
    calls: list[int] = []

    def listener() -> None:
        calls.append(1)

    fresh_i18n.on_locale_change(listener)
    fresh_i18n.set_locale("fr")
    fresh_i18n.remove_listener(listener)
    fresh_i18n.set_locale("en")

    assert len(calls) == 1


def test_a_listener_may_remove_itself_while_being_notified(
    fresh_i18n: I18n,
) -> None:
    """A stale listener drops itself mid-broadcast without skipping the next.

    The entry point registers one listener per session and the singleton
    outlives the page, so a listener whose session is gone unregisters
    itself the next time it is called. That happens while set_locale() is
    walking the list, which only stays safe as long as remove_listener()
    rebinds the list instead of mutating the one being iterated.
    """
    survivor: list[int] = []

    def stale() -> None:
        fresh_i18n.remove_listener(stale)

    def live() -> None:
        survivor.append(1)

    fresh_i18n.on_locale_change(stale)
    fresh_i18n.on_locale_change(live)

    fresh_i18n.set_locale("fr")
    assert survivor == [1]

    fresh_i18n.set_locale("en")
    assert survivor == [1, 1]


def test_locale_property_reflects_current(fresh_i18n: I18n) -> None:
    """locale property returns the active locale code."""
    assert fresh_i18n.locale == "en"
    fresh_i18n.set_locale("fr")
    assert fresh_i18n.locale == "fr"


def test_all_supported_locales_loadable() -> None:
    """Every locale listed in SUPPORTED_LOCALES can be loaded without error."""
    inst = I18n()
    for locale in SUPPORTED_LOCALES:
        inst.set_locale(locale)
        assert inst.locale == locale
