"""Secrets live in Windows Credential Manager (via keyring), never in config files or logs."""
from __future__ import annotations

from config import KEYRING_SERVICE


def get_secret(name: str) -> str | None:
    import keyring
    return keyring.get_password(KEYRING_SERVICE, name)


def set_secret(name: str, value: str) -> None:
    import keyring
    keyring.set_password(KEYRING_SERVICE, name, value)


def delete_secret(name: str) -> None:
    import keyring
    try:
        keyring.delete_password(KEYRING_SERVICE, name)
    except keyring.errors.PasswordDeleteError:
        pass
