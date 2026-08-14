"""Authenticated, encrypted persistence for a private in-memory SQLite database.

The SQLite database is never opened from a filesystem path.  Each operation
decrypts the persisted database into an in-memory connection and atomically
replaces the encrypted container only after the transaction commits.  The
encryption key is obtained from a caller-supplied provider; the production
provider below stores it in the operating system's configured secret store,
never beside the database.
"""

from __future__ import annotations

import base64
import errno
import os
import secrets
import sqlite3
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Protocol

try:  # GenomiLab's supported local persistence boundary is POSIX.
    import fcntl
except ImportError:  # pragma: no cover - exercised only on unsupported hosts
    fcntl = None  # type: ignore[assignment]

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..runtime.private_storage import (
    PRIVATE_FILE_MODE,
    ensure_private_directory,
    refuse_symlink,
)
from .native_keyring import (
    NativeKeyringBackend,
    NativeKeyringUnavailableError,
    resolve_native_keyring_backend,
)

_MAGIC = b"GENOMILAB-ENCRYPTED-SQLITE\x00"
_FORMAT_VERSION = b"\x01"
_KEY_ID_BYTES = 32
_NONCE_BYTES = 12
_SQLITE_HEADER = b"SQLite format 3\x00"
_AES_KEY_BYTES = 32

_LOCKS_GUARD = threading.Lock()
_PATH_LOCKS: dict[Path, threading.RLock] = {}
_ACTIVE_LOCK_DESCRIPTORS: set[int] = set()
_CONNECT_LOCAL = threading.local()
_PRIVATE_LOCK_LOCAL = threading.local()
_LOCKS_PID = os.getpid()


class EncryptedSQLiteError(RuntimeError):
    """Base class for encrypted database persistence failures."""


class EncryptedSQLiteFormatError(EncryptedSQLiteError):
    """The on-disk container is not a supported encrypted database."""


class PlaintextSQLiteRejectedError(EncryptedSQLiteFormatError):
    """A plaintext SQLite database was found where ciphertext is required."""


class EncryptedSQLiteAuthenticationError(EncryptedSQLiteError):
    """The encrypted database could not be authenticated with its stored key."""


class EncryptionKeyUnavailableError(EncryptedSQLiteError):
    """A valid database encryption key could not be loaded."""


class EncryptedSQLiteLockTimeoutError(EncryptedSQLiteError, TimeoutError):
    """Another process held the encrypted database transaction lock too long."""


class EncryptedSQLiteNestedTransactionError(EncryptedSQLiteError):
    """The same thread attempted a nested snapshot transaction for one database."""


class EncryptionKeyProvider(Protocol):
    """Loads or creates one 256-bit key for an opaque database key identifier."""

    def get_or_create_key(self, key_id: str) -> bytes:
        """Return exactly 32 key bytes for ``key_id``."""


class OSKeyringKeyProvider:
    """Store database keys in the operating system's configured secret store.

    ``keyring`` selects the native secure backend (for example macOS Keychain,
    Windows Credential Locker, or Secret Service).  A missing/non-functional
    backend is an error: this provider never falls back to a file next to the
    encrypted database.
    """

    def __init__(
        self,
        service_name: str = "com.genomi.genomilab",
        *,
        keyring_backend: NativeKeyringBackend | None = None,
    ) -> None:
        self.service_name = service_name
        self._keyring_backend = keyring_backend
        self._lock = threading.Lock()

    def get_or_create_key(self, key_id: str) -> bytes:
        try:
            keyring_backend = self._keyring_backend or resolve_native_keyring_backend()
            self._keyring_backend = keyring_backend
        except NativeKeyringUnavailableError as exc:
            raise EncryptionKeyUnavailableError(
                "The OS secret-store integration is unavailable."
            ) from exc

        account = f"database:{key_id}"
        with self._lock:
            try:
                encoded = keyring_backend.get_password(self.service_name, account)
            except Exception as exc:
                raise EncryptionKeyUnavailableError(
                    "The operating-system secret store could not be read."
                ) from exc

            if encoded is None:
                key = secrets.token_bytes(_AES_KEY_BYTES)
                encoded = base64.urlsafe_b64encode(key).decode("ascii")
                try:
                    keyring_backend.set_password(self.service_name, account, encoded)
                    encoded = keyring_backend.get_password(self.service_name, account)
                except Exception as exc:
                    raise EncryptionKeyUnavailableError(
                        "The operating-system secret store could not save the database key."
                    ) from exc
                if encoded is None:
                    raise EncryptionKeyUnavailableError(
                        "The operating-system secret store did not retain the database key."
                    )

        try:
            key = base64.b64decode(encoded, altchars=b"-_", validate=True)
        except (ValueError, TypeError) as exc:
            raise EncryptionKeyUnavailableError(
                "The operating-system secret store returned an invalid database key."
            ) from exc
        return _validated_key(key)


class StaticEncryptionKeyProvider:
    """Injectable fixed-key provider intended for tests and controlled hosts."""

    def __init__(self, key: bytes) -> None:
        self._key = _validated_key(key)

    def get_or_create_key(self, key_id: str) -> bytes:
        del key_id
        return self._key


class EncryptedSQLiteDatabase:
    """Thread-safe, encrypted persistence for serialized in-memory SQLite."""

    def __init__(
        self,
        path: str | Path,
        *,
        key_provider: EncryptionKeyProvider | None = None,
        timeout_seconds: float = 10,
    ) -> None:
        self.path = Path(path).absolute()
        ensure_private_directory(self.path.parent)
        refuse_symlink(self.path)
        self._key_provider = key_provider or OSKeyringKeyProvider()
        self._timeout_seconds = timeout_seconds
        self._lock_path = self.path.with_name(f".{self.path.name}.lock")
        self._key_id: str | None = None
        self._key: bytes | None = None
        if self.path.exists():
            self._harden_existing_file()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Yield a private in-memory connection and persist only on success."""

        canonical = Path(os.path.abspath(self.path))
        depths = dict(getattr(_CONNECT_LOCAL, "depths", {}))
        if depths.get(canonical):
            raise EncryptedSQLiteNestedTransactionError(
                "Nested GenomiLab database transactions are not supported."
            )
        process_lock = _lock_for_path(canonical)
        with process_lock:
            depths = dict(getattr(_CONNECT_LOCAL, "depths", {}))
            if depths.get(canonical):
                raise EncryptedSQLiteNestedTransactionError(
                    "Nested GenomiLab database transactions are not supported."
                )
            depths[canonical] = 1
            _CONNECT_LOCAL.depths = depths
            try:
                with self._cross_process_lock():
                    with self._connected_transaction() as connection:
                        yield connection
            finally:
                current = dict(getattr(_CONNECT_LOCAL, "depths", {}))
                current.pop(canonical, None)
                _CONNECT_LOCAL.depths = current

    @contextmanager
    def _connected_transaction(self) -> Iterator[sqlite3.Connection]:
        """Run one already-locked in-memory SQLite transaction."""

        connection = sqlite3.connect(":memory:", timeout=self._timeout_seconds)
        connection.row_factory = sqlite3.Row
        try:
            if self.path.exists():
                serialized = self._decrypt_container(self._read_container())
                try:
                    connection.deserialize(serialized)
                except sqlite3.DatabaseError as exc:
                    raise EncryptedSQLiteFormatError(
                        "The authenticated payload is not a valid SQLite database."
                    ) from exc
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 5000")
            yield connection
            connection.commit()
            serialized = connection.serialize()
            if not serialized.startswith(_SQLITE_HEADER):
                raise EncryptedSQLiteFormatError(
                    "SQLite did not produce a valid serialized database."
                )
            self._atomic_write(self._encrypt_container(serialized))
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def _cross_process_lock(self) -> Iterator[None]:
        """Hold one path-keyed OS lock across the complete read/replace cycle."""

        with exclusive_private_file_lock(
            self._lock_path, timeout_seconds=self._timeout_seconds
        ):
            yield

    def _read_container(self) -> bytes:
        refuse_symlink(self.path)
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self.path, flags)
        try:
            os.fchmod(descriptor, PRIVATE_FILE_MODE)
            with os.fdopen(descriptor, "rb") as handle:
                descriptor = -1
                return handle.read()
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def _decrypt_container(self, container: bytes) -> bytes:
        if container.startswith(_SQLITE_HEADER):
            raise PlaintextSQLiteRejectedError(
                "Refusing to open a plaintext SQLite database as GenomiLab state."
            )
        minimum_length = len(_MAGIC) + 1 + _KEY_ID_BYTES + _NONCE_BYTES + 16
        if len(container) < minimum_length or not container.startswith(_MAGIC):
            raise EncryptedSQLiteFormatError(
                "The GenomiLab database is not a supported encrypted container."
            )
        cursor = len(_MAGIC)
        version = container[cursor : cursor + 1]
        cursor += 1
        if version != _FORMAT_VERSION:
            raise EncryptedSQLiteFormatError(
                "The GenomiLab encrypted database format is not supported."
            )
        key_id_bytes = container[cursor : cursor + _KEY_ID_BYTES]
        cursor += _KEY_ID_BYTES
        try:
            key_id = key_id_bytes.decode("ascii")
        except UnicodeDecodeError as exc:
            raise EncryptedSQLiteFormatError(
                "The GenomiLab encrypted database key identifier is invalid."
            ) from exc
        if len(key_id) != _KEY_ID_BYTES or any(
            character not in "0123456789abcdef" for character in key_id
        ):
            raise EncryptedSQLiteFormatError(
                "The GenomiLab encrypted database key identifier is invalid."
            )
        nonce = container[cursor : cursor + _NONCE_BYTES]
        ciphertext = container[cursor + _NONCE_BYTES :]
        aad = _MAGIC + version + key_id_bytes
        key = self._load_key(key_id)
        try:
            plaintext = AESGCM(key).decrypt(nonce, ciphertext, aad)
        except InvalidTag as exc:
            raise EncryptedSQLiteAuthenticationError(
                "The GenomiLab encrypted database failed authentication."
            ) from exc
        if not plaintext.startswith(_SQLITE_HEADER):
            raise EncryptedSQLiteFormatError(
                "The authenticated payload is not a valid SQLite database."
            )
        return plaintext

    def _encrypt_container(self, serialized: bytes) -> bytes:
        key_id = self._key_id or secrets.token_hex(_KEY_ID_BYTES // 2)
        key = self._load_key(key_id)
        key_id_bytes = key_id.encode("ascii")
        aad = _MAGIC + _FORMAT_VERSION + key_id_bytes
        nonce = secrets.token_bytes(_NONCE_BYTES)
        ciphertext = AESGCM(key).encrypt(nonce, serialized, aad)
        return aad + nonce + ciphertext

    def _load_key(self, key_id: str) -> bytes:
        if self._key_id is not None and self._key_id != key_id:
            raise EncryptedSQLiteAuthenticationError(
                "The encrypted database key identifier changed unexpectedly."
            )
        if self._key is None:
            try:
                candidate = self._key_provider.get_or_create_key(key_id)
            except EncryptedSQLiteError:
                raise
            except Exception as exc:
                raise EncryptionKeyUnavailableError(
                    "The database encryption key provider failed."
                ) from exc
            self._key = _validated_key(candidate)
            self._key_id = key_id
        return self._key

    def _atomic_write(self, container: bytes) -> None:
        ensure_private_directory(self.path.parent)
        refuse_symlink(self.path)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            dir=str(self.path.parent),
        )
        temporary = Path(temporary_name)
        descriptor_open = True
        try:
            os.fchmod(descriptor, PRIVATE_FILE_MODE)
            with os.fdopen(descriptor, "wb") as handle:
                descriptor_open = False
                handle.write(container)
                handle.flush()
                os.fsync(handle.fileno())
            refuse_symlink(self.path)
            os.replace(temporary, self.path)
            _fsync_directory(self.path.parent)
        finally:
            if descriptor_open:
                os.close(descriptor)
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def _harden_existing_file(self) -> None:
        refuse_symlink(self.path)
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self.path, flags)
        try:
            os.fchmod(descriptor, PRIVATE_FILE_MODE)
        finally:
            os.close(descriptor)


@contextmanager
def exclusive_private_file_lock(
    path: str | Path, *, timeout_seconds: float = 10
) -> Iterator[None]:
    """Serialize one private local resource across threads and processes."""

    lock_path = Path(path).absolute()
    process_lock = _lock_for_path(lock_path)
    with process_lock:
        depths = dict(getattr(_PRIVATE_LOCK_LOCAL, "depths", {}))
        if depths.get(lock_path):
            depths[lock_path] += 1
            _PRIVATE_LOCK_LOCAL.depths = depths
            try:
                yield
            finally:
                current = dict(getattr(_PRIVATE_LOCK_LOCAL, "depths", {}))
                current[lock_path] -= 1
                _PRIVATE_LOCK_LOCAL.depths = current
            return
        depths[lock_path] = 1
        _PRIVATE_LOCK_LOCAL.depths = depths
        try:
            with _exclusive_os_file_lock(lock_path, timeout_seconds=timeout_seconds):
                yield
        finally:
            current = dict(getattr(_PRIVATE_LOCK_LOCAL, "depths", {}))
            current.pop(lock_path, None)
            _PRIVATE_LOCK_LOCAL.depths = current


@contextmanager
def _exclusive_os_file_lock(
    lock_path: Path, *, timeout_seconds: float
) -> Iterator[None]:
    """Hold one hardened POSIX advisory lock for an already serialized caller."""

    if fcntl is None:
        raise EncryptedSQLiteError(
            "GenomiLab encrypted persistence requires POSIX cross-process locking."
        )
    ensure_private_directory(lock_path.parent)
    refuse_symlink(lock_path)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    with _LOCKS_GUARD:
        descriptor = os.open(lock_path, flags, PRIVATE_FILE_MODE)
        _ACTIVE_LOCK_DESCRIPTORS.add(descriptor)
    try:
        os.fchmod(descriptor, PRIVATE_FILE_MODE)
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                    raise
                if time.monotonic() >= deadline:
                    raise EncryptedSQLiteLockTimeoutError(
                        "Timed out waiting for the GenomiLab private resource lock."
                    ) from exc
                time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        with _LOCKS_GUARD:
            try:
                os.close(descriptor)
            finally:
                _ACTIVE_LOCK_DESCRIPTORS.discard(descriptor)


def _validated_key(key: bytes) -> bytes:
    if not isinstance(key, bytes) or len(key) != _AES_KEY_BYTES:
        raise EncryptionKeyUnavailableError(
            "The database encryption key must contain exactly 32 bytes."
        )
    return key


def _lock_for_path(path: Path) -> threading.RLock:
    _reset_process_locks_after_unregistered_fork()
    canonical = Path(os.path.abspath(path))
    with _LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(canonical, threading.RLock())


def _reset_process_locks_after_unregistered_fork() -> None:
    """Defensively reset inherited thread state if a host bypassed at-fork hooks."""

    global _LOCKS_GUARD, _PATH_LOCKS, _ACTIVE_LOCK_DESCRIPTORS, _CONNECT_LOCAL
    global _PRIVATE_LOCK_LOCAL
    global _LOCKS_PID
    current_pid = os.getpid()
    if current_pid == _LOCKS_PID:
        return
    for descriptor in tuple(_ACTIVE_LOCK_DESCRIPTORS):
        try:
            os.close(descriptor)
        except OSError:
            pass
    _LOCKS_GUARD = threading.Lock()
    _PATH_LOCKS = {}
    _ACTIVE_LOCK_DESCRIPTORS = set()
    _CONNECT_LOCAL = threading.local()
    _PRIVATE_LOCK_LOCAL = threading.local()
    _LOCKS_PID = current_pid


def _before_fork() -> None:  # pragma: no cover - behavior asserted in child process
    _LOCKS_GUARD.acquire()


def _after_fork_parent() -> None:  # pragma: no cover - behavior asserted indirectly
    _LOCKS_GUARD.release()


def _after_fork_child() -> (
    None
):  # pragma: no cover - behavior asserted in child process
    global _LOCKS_GUARD, _PATH_LOCKS, _ACTIVE_LOCK_DESCRIPTORS, _CONNECT_LOCAL
    global _PRIVATE_LOCK_LOCAL
    global _LOCKS_PID
    for descriptor in tuple(_ACTIVE_LOCK_DESCRIPTORS):
        try:
            os.close(descriptor)
        except OSError:
            pass
    _LOCKS_GUARD = threading.Lock()
    _PATH_LOCKS = {}
    _ACTIVE_LOCK_DESCRIPTORS = set()
    _CONNECT_LOCAL = threading.local()
    _PRIVATE_LOCK_LOCAL = threading.local()
    _LOCKS_PID = os.getpid()


if hasattr(os, "register_at_fork"):  # pragma: no branch - true on supported POSIX hosts
    os.register_at_fork(
        before=_before_fork,
        after_in_parent=_after_fork_parent,
        after_in_child=_after_fork_child,
    )


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
