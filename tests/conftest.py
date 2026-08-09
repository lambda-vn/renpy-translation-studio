"""Shared pytest fixtures for the test suite."""

import keyring.errors
import pytest

from core import settings as settings_module


class FakeKeyring:
    """In-memory stand-in for the keyring module.

    Keeps every test off the real OS credential store (Windows Credential
    Manager, macOS Keychain, Linux Secret Service).
    """

    errors = keyring.errors

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        """Return the stored password, or None if not set."""
        return self._store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        """Store a password."""
        self._store[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        """Delete a stored password, raising if none exists."""
        if (service, username) not in self._store:
            raise keyring.errors.PasswordDeleteError("not found")
        del self._store[(service, username)]


@pytest.fixture(autouse=True)
def fake_keyring(monkeypatch: pytest.MonkeyPatch) -> FakeKeyring:
    """Replace core.settings' keyring reference with an in-memory fake."""
    fake = FakeKeyring()
    monkeypatch.setattr(settings_module, "keyring", fake)
    return fake
