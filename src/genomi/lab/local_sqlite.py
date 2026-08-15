"""Plain local SQLite persistence for GenomiLab.

Lab state is an ordinary SQLite database.  SQLite owns transaction and
cross-process locking; Genomi additionally refuses symlinks and keeps the file
and its sidecars private to the current operating-system user.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ..runtime.private_storage import ensure_private_directory, refuse_symlink


class LocalSQLiteError(RuntimeError):
    """Base class for local Lab SQLite persistence failures."""


class LocalSQLiteLockTimeoutError(LocalSQLiteError, TimeoutError):
    """Another process held the Lab SQLite write lock too long."""


class LocalSQLiteDatabase:
    """Small transaction boundary around one private plaintext SQLite file."""

    def __init__(self, path: str | Path, *, timeout_seconds: float = 10) -> None:
        self.path = Path(path).absolute()
        ensure_private_directory(self.path.parent)
        refuse_symlink(self.path)
        self.timeout_seconds = timeout_seconds
        if not self.path.exists():
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            try:
                descriptor = os.open(self.path, flags, 0o600)
            except FileExistsError:
                pass
            else:
                os.close(descriptor)
        refuse_symlink(self.path)
        self._harden_permissions()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        refuse_symlink(self.path)
        try:
            connection = sqlite3.connect(
                self.path,
                timeout=self.timeout_seconds,
                isolation_level=None,
            )
        except sqlite3.Error as exc:
            raise LocalSQLiteError("The local Lab database could not be opened.") from exc
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            try:
                connection.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as exc:
                if "locked" in str(exc).lower() or "busy" in str(exc).lower():
                    raise LocalSQLiteLockTimeoutError(
                        "Another Lab database transaction is still active."
                    ) from exc
                raise LocalSQLiteError("The local Lab database transaction could not start.") from exc
            self._harden_permissions()
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
            self._harden_permissions()

    def _harden_permissions(self) -> None:
        for path in (
            self.path,
            self.path.with_name(f"{self.path.name}-wal"),
            self.path.with_name(f"{self.path.name}-shm"),
            self.path.with_name(f"{self.path.name}-journal"),
        ):
            try:
                if path.exists():
                    refuse_symlink(path)
                    path.chmod(0o600)
            except OSError:
                pass


__all__ = ["LocalSQLiteDatabase", "LocalSQLiteError", "LocalSQLiteLockTimeoutError"]
