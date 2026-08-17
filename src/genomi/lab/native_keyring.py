"""Resolve only native operating-system keyring backends for production secrets."""

from __future__ import annotations

import sys
from types import MappingProxyType
from typing import Mapping, Protocol, cast


class NativeKeyringBackend(Protocol):
    def get_password(self, service_name: str, username: str) -> str | None: ...

    def set_password(self, service_name: str, username: str, password: str) -> None: ...

    def delete_password(self, service_name: str, username: str) -> None: ...


class NativeKeyringUnavailableError(RuntimeError):
    """The selected keyring is absent, non-native, or unusable."""


_NATIVE_KEYRING_MODULES: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "darwin": ("keyring.backends.macOS",),
        "win32": ("keyring.backends.Windows",),
        "linux": (
            "keyring.backends.SecretService",
            "keyring.backends.kwallet",
        ),
    }
)


def resolve_native_keyring_backend() -> NativeKeyringBackend:
    """Return the platform's native secure backend; reject facade overrides."""

    try:
        import keyring

        backend = keyring.get_keyring()
    except Exception as exc:
        raise NativeKeyringUnavailableError(
            "The operating-system credential store integration is unavailable."
        ) from exc
    allowed_modules = _NATIVE_KEYRING_MODULES.get(sys.platform, ())
    if type(backend).__module__ not in allowed_modules:
        raise NativeKeyringUnavailableError(
            "A native operating-system credential store is required."
        )
    return cast(NativeKeyringBackend, backend)


__all__ = [
    "NativeKeyringBackend",
    "NativeKeyringUnavailableError",
    "resolve_native_keyring_backend",
]
