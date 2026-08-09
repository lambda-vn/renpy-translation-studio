"""Tests for core/logging_config.py."""

import logging
from pathlib import Path

import pytest

from core.logging_config import configure_logging
from core.settings import Settings


@pytest.fixture()
def fake_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Point logging_config's settings reference at a fresh temp-backed instance."""
    s = Settings.__new__(Settings)
    s._config_dir = tmp_path
    s._config_file = tmp_path / "settings.json"
    s._data = {}
    s._load()
    monkeypatch.setattr("core.logging_config.settings", s)
    return s


def test_verbose_off_sets_app_logger_to_warning(fake_settings: Settings) -> None:
    configure_logging()
    assert logging.getLogger(
        "core.translation.providers.ollama"
    ).getEffectiveLevel() == (logging.WARNING)


def test_verbose_on_sets_app_logger_to_debug(fake_settings: Settings) -> None:
    fake_settings.set("verbose_logging", "1")
    configure_logging()
    assert logging.getLogger(
        "core.translation.providers.ollama"
    ).getEffectiveLevel() == (logging.DEBUG)


def test_verbose_on_does_not_affect_third_party_loggers(
    fake_settings: Settings,
) -> None:
    fake_settings.set("verbose_logging", "1")
    configure_logging()
    assert logging.getLogger("httpx").getEffectiveLevel() == logging.WARNING
    assert logging.getLogger("flet").getEffectiveLevel() == logging.WARNING


def test_verbose_on_also_covers_the_app_ui_namespace(fake_settings: Settings) -> None:
    fake_settings.set("verbose_logging", "1")
    configure_logging()
    assert logging.getLogger("app.views.review_view").getEffectiveLevel() == (
        logging.DEBUG
    )
