"""OS-backed storage for GenomiLab provider credentials.

Credentials are stored as one JSON value per provider so a replacement cannot
leave a multi-field credential partially updated.  The production path uses
only the operating system's keyring; it has no environment or file fallback.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from contextlib import contextmanager
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final, Literal, TypeAlias, cast, overload

from .encrypted_sqlite import exclusive_private_file_lock
from .native_keyring import (
    NativeKeyringBackend,
    NativeKeyringUnavailableError,
    resolve_native_keyring_backend,
)


ProviderId: TypeAlias = Literal["paperclip", "biohub-esm", "proto"]

PAPERCLIP_PROVIDER_ID: Final[ProviderId] = "paperclip"
BIOHUB_ESM_PROVIDER_ID: Final[ProviderId] = "biohub-esm"
PROTO_PROVIDER_ID: Final[ProviderId] = "proto"
PROVIDER_IDS: Final[tuple[ProviderId, ...]] = (
    PAPERCLIP_PROVIDER_ID,
    BIOHUB_ESM_PROVIDER_ID,
    PROTO_PROVIDER_ID,
)

PROVIDER_CREDENTIAL_SERVICE: Final = "com.genomi.genomilab.providers.v1"
PROVIDER_CREDENTIAL_LOCK_TIMEOUT_SECONDS: Final = 30.0
_ACCOUNT_PREFIX: Final = "provider:"
_PROVIDER_FIELDS: Final[Mapping[ProviderId, tuple[str, ...]]] = MappingProxyType(
    {
        PAPERCLIP_PROVIDER_ID: ("api_key",),
        BIOHUB_ESM_PROVIDER_ID: ("api_token",),
        PROTO_PROVIDER_ID: (
            "modal_token_id",
            "modal_token_secret",
            "modal_environment",
        ),
    }
)


class ProviderCredentialError(RuntimeError):
    """Base class for provider credential failures."""


class ProviderCredentialValidationError(ProviderCredentialError):
    """The provider identifier or credential shape is not supported."""


class ProviderCredentialStoreUnavailableError(ProviderCredentialError):
    """The operating system credential store could not complete an operation."""


class ProviderCredentialCorruptError(ProviderCredentialError):
    """A stored provider credential does not match its current schema."""


class ProviderCredentials(Mapping[str, str]):
    """An immutable credential mapping whose representation is always redacted."""

    __slots__ = ("provider_id", "_values")

    def __init__(self, provider_id: str, values: Mapping[str, object]) -> None:
        resolved_provider = _validated_provider_id(provider_id)
        self.provider_id = resolved_provider
        self._values = MappingProxyType(_validated_values(resolved_provider, values))

    def __getitem__(self, field: str) -> str:
        return self._values[field]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __repr__(self) -> str:
        return (
            "ProviderCredentials("
            f"provider_id={self.provider_id!r}, fields={tuple(self)!r}, redacted=True)"
        )


@dataclass(frozen=True)
class ProviderCredentialStatus:
    """Non-secret connection state safe to return through the local portal."""

    provider_id: ProviderId
    configured: bool
    storage: Literal["os_keyring"] = "os_keyring"

    def to_dict(self) -> dict[str, object]:
        return {
            "provider_id": self.provider_id,
            "configured": self.configured,
            "storage": self.storage,
        }


@dataclass(frozen=True, repr=False)
class ProviderCredentialSnapshot:
    """Opaque in-memory rollback value; its representation never exposes secrets."""

    provider_id: ProviderId
    _encoded: str | None

    def __repr__(self) -> str:
        return (
            "ProviderCredentialSnapshot("
            f"provider_id={self.provider_id!r}, configured={self._encoded is not None}, "
            "redacted=True)"
        )


class OSKeyringProviderCredentialStore:
    """Persist exact provider credential records in the native OS keyring."""

    def __init__(self, keyring_backend: NativeKeyringBackend | None = None) -> None:
        self._keyring_backend = keyring_backend
        self._lock = threading.RLock()

    def replace(
        self,
        provider_id: str,
        credentials: Mapping[str, object],
    ) -> None:
        """Atomically create or replace the complete credential for a provider."""

        credential = ProviderCredentials(provider_id, credentials)
        encoded = json.dumps(
            dict(credential),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        account = _account_name(credential.provider_id)
        with self._lock:
            backend = self._backend()
            save_failed = False
            try:
                backend.set_password(
                    PROVIDER_CREDENTIAL_SERVICE,
                    account,
                    encoded,
                )
                retained = backend.get_password(
                    PROVIDER_CREDENTIAL_SERVICE,
                    account,
                )
            except Exception:
                save_failed = True
                retained = None
            if save_failed:
                raise ProviderCredentialStoreUnavailableError(
                    "The operating-system credential store could not save the provider credential."
                )
            if retained != encoded:
                raise ProviderCredentialStoreUnavailableError(
                    "The operating-system credential store did not retain the provider credential."
                )

    def get(self, provider_id: str) -> ProviderCredentials | None:
        """Load one credential without consulting ambient configuration."""

        loaded = self.get_with_revision(provider_id)
        return loaded[0] if loaded is not None else None

    def get_with_revision(
        self, provider_id: str
    ) -> tuple[ProviderCredentials, str] | None:
        """Atomically load one credential and its non-exported content revision."""

        resolved_provider = _validated_provider_id(provider_id)
        with self._lock:
            encoded = self._read_encoded(resolved_provider)
        if encoded is None:
            return None
        decoded: object = None
        try:
            decoded = json.loads(encoded)
        except json.JSONDecodeError:
            pass
        if isinstance(decoded, Mapping):
            try:
                credential = ProviderCredentials(resolved_provider, decoded)
            except ProviderCredentialValidationError:
                pass
            else:
                revision = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
                return credential, revision
        raise ProviderCredentialCorruptError(
            "The stored provider credential does not match its current schema."
        )

    def delete(self, provider_id: str) -> bool:
        """Delete one provider credential; return whether it previously existed."""

        resolved_provider = _validated_provider_id(provider_id)
        account = _account_name(resolved_provider)
        with self._lock:
            if self._read_encoded(resolved_provider) is None:
                return False
            try:
                backend = self._backend()
                backend.delete_password(
                    PROVIDER_CREDENTIAL_SERVICE,
                    account,
                )
                retained = backend.get_password(
                    PROVIDER_CREDENTIAL_SERVICE,
                    account,
                )
            except Exception:
                retained = None
                delete_failed = True
            else:
                delete_failed = retained is not None
            if delete_failed:
                raise ProviderCredentialStoreUnavailableError(
                    "The operating-system credential store could not delete the provider credential."
                )
        return True

    def has(self, provider_id: str) -> bool:
        """Return whether a valid credential is configured for a provider."""

        return self.get(provider_id) is not None

    def capture_snapshot(self, provider_id: str) -> ProviderCredentialSnapshot:
        """Capture the exact stored bytes for an immediate in-process rollback."""

        resolved_provider = _validated_provider_id(provider_id)
        with self._lock:
            encoded = self._read_encoded(resolved_provider)
        return ProviderCredentialSnapshot(resolved_provider, encoded)

    def restore_snapshot(
        self,
        snapshot: ProviderCredentialSnapshot,
        *,
        expected_current: ProviderCredentialSnapshot | None = None,
    ) -> None:
        """Restore one snapshot only if no later credential replaced the command's result."""

        if not isinstance(snapshot, ProviderCredentialSnapshot):
            raise ProviderCredentialValidationError(
                "The provider credential snapshot is invalid."
            )
        account = _account_name(snapshot.provider_id)
        with self._lock:
            backend = self._backend()
            try:
                current = self._read_encoded(snapshot.provider_id)
                if expected_current is not None and (
                    expected_current.provider_id != snapshot.provider_id
                    or current != expected_current._encoded
                ):
                    raise ProviderCredentialStoreUnavailableError(
                        "Provider credentials changed before state could be restored."
                    )
                if snapshot._encoded is None:
                    if current is not None:
                        backend.delete_password(PROVIDER_CREDENTIAL_SERVICE, account)
                else:
                    backend.set_password(
                        PROVIDER_CREDENTIAL_SERVICE,
                        account,
                        snapshot._encoded,
                    )
                retained = backend.get_password(PROVIDER_CREDENTIAL_SERVICE, account)
            except ProviderCredentialStoreUnavailableError:
                raise
            except Exception as exc:
                raise ProviderCredentialStoreUnavailableError(
                    "The operating-system credential store could not restore provider state."
                ) from exc
            if retained != snapshot._encoded:
                raise ProviderCredentialStoreUnavailableError(
                    "The operating-system credential store did not restore provider state."
                )

    @overload
    def status(self, provider_id: str) -> ProviderCredentialStatus: ...

    @overload
    def status(
        self, provider_id: None = None
    ) -> tuple[ProviderCredentialStatus, ...]: ...

    def status(
        self, provider_id: str | None = None
    ) -> ProviderCredentialStatus | tuple[ProviderCredentialStatus, ...]:
        """Return redacted state for one provider or the complete fixed catalog."""

        if provider_id is not None:
            resolved_provider = _validated_provider_id(provider_id)
            return ProviderCredentialStatus(
                provider_id=resolved_provider,
                configured=self.has(resolved_provider),
            )
        return tuple(
            ProviderCredentialStatus(
                provider_id=candidate,
                configured=self.has(candidate),
            )
            for candidate in PROVIDER_IDS
        )

    def _backend(self) -> NativeKeyringBackend:
        if self._keyring_backend is not None:
            return self._keyring_backend
        try:
            backend = resolve_native_keyring_backend()
        except NativeKeyringUnavailableError as exc:
            raise ProviderCredentialStoreUnavailableError(
                "A native operating-system credential store is required."
            ) from exc
        self._keyring_backend = backend
        return self._keyring_backend

    def _read_encoded(self, provider_id: ProviderId) -> str | None:
        read_failed = False
        try:
            encoded = self._backend().get_password(
                PROVIDER_CREDENTIAL_SERVICE,
                _account_name(provider_id),
            )
        except Exception:
            read_failed = True
            encoded = None
        if read_failed:
            raise ProviderCredentialStoreUnavailableError(
                "The operating-system credential store could not read provider credentials."
            )
        if encoded is not None and not isinstance(encoded, str):
            raise ProviderCredentialStoreUnavailableError(
                "The operating-system credential store returned an invalid value."
            )
        return encoded


def provider_credential_lock_path(provider_id: str) -> Path:
    """Return the installation-wide lock for one OS-keyring provider account."""

    resolved_provider = _validated_provider_id(provider_id)
    service_identity = hashlib.sha256(
        PROVIDER_CREDENTIAL_SERVICE.encode("utf-8")
    ).hexdigest()[:16]
    lock_root = Path(tempfile.gettempdir()) / (
        f"genomi-provider-locks-{os.getuid()}-{service_identity}"
    )
    return lock_root / f"{resolved_provider}.lock"


@contextmanager
def provider_credential_lock(
    provider_id: str,
    *,
    timeout_seconds: float = PROVIDER_CREDENTIAL_LOCK_TIMEOUT_SECONDS,
) -> Iterator[None]:
    """Serialize one provider account across local services and processes."""

    with exclusive_private_file_lock(
        provider_credential_lock_path(provider_id),
        timeout_seconds=timeout_seconds,
    ):
        yield


def _validated_provider_id(provider_id: str) -> ProviderId:
    if not isinstance(provider_id, str) or provider_id not in _PROVIDER_FIELDS:
        raise ProviderCredentialValidationError(
            "The provider credential identifier is not supported."
        )
    return cast(ProviderId, provider_id)


def _validated_values(
    provider_id: ProviderId,
    values: Mapping[str, object],
) -> dict[str, str]:
    if not isinstance(values, Mapping):
        raise ProviderCredentialValidationError(
            "Provider credentials must match the exact provider schema."
        )
    fields = _PROVIDER_FIELDS[provider_id]
    try:
        supplied_fields = set(values)
    except Exception:
        supplied_fields = None
    if supplied_fields != set(fields):
        raise ProviderCredentialValidationError(
            "Provider credentials must match the exact provider schema."
        )
    normalized: dict[str, str] = {}
    for field in fields:
        value_missing = False
        try:
            value = values[field]
        except Exception:
            value_missing = True
            value = None
        if value_missing:
            raise ProviderCredentialValidationError(
                "Provider credentials must match the exact provider schema."
            )
        if not isinstance(value, str) or not value.strip():
            raise ProviderCredentialValidationError(
                "Provider credential values must be non-empty strings."
            )
        normalized[field] = value
    return normalized


def _account_name(provider_id: ProviderId) -> str:
    return f"{_ACCOUNT_PREFIX}{provider_id}"
