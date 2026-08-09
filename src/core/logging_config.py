"""Console logging setup, toggled by the verbose_logging setting."""

import logging

from core.settings import settings

_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_APP_LOGGER_NAMES = ("core", "app")


def configure_logging() -> None:
    """Set this app's own logger level from the verbose_logging setting.

    Only affects loggers under the "core" and "app" namespaces (this
    app's own modules). Third-party loggers (Flet, httpx, httpcore…) are
    left at the default WARNING level so verbose mode doesn't flood the
    console with framework-internal traffic — just this app's own
    diagnostics.

    Call again after toggling the setting to apply the change immediately,
    without restarting the app.
    """
    logging.basicConfig(format=_LOG_FORMAT)
    level = logging.DEBUG if settings.get("verbose_logging") else logging.WARNING
    for name in _APP_LOGGER_NAMES:
        logging.getLogger(name).setLevel(level)
