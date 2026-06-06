from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path
from urllib.parse import quote

DEFAULT_BUSY_TIMEOUT_SECONDS = 30
LONG_WRITE_BUSY_TIMEOUT_SECONDS = 1800


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> bool:
        suppress = super().__exit__(exc_type, exc_value, traceback)
        self.close()
        return bool(suppress)

    def __del__(self) -> None:
        with contextlib.suppress(sqlite3.Error):
            self.close()


def connect_sqlite(
    path: str | Path,
    *,
    timeout_seconds: int = DEFAULT_BUSY_TIMEOUT_SECONDS,
    create_parent: bool = False,
    row_factory: bool = True,
    wal: bool = False,
    foreign_keys: bool = False,
) -> sqlite3.Connection:
    database = Path(path)
    if create_parent:
        database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(
        database,
        timeout=timeout_seconds,
        factory=ClosingConnection,
    )
    _configure_connection(
        connection,
        timeout_seconds=timeout_seconds,
        row_factory=row_factory,
        wal=wal,
        foreign_keys=foreign_keys,
    )
    return connection


def connect_readonly_sqlite(
    path: str | Path,
    *,
    timeout_seconds: int = DEFAULT_BUSY_TIMEOUT_SECONDS,
    row_factory: bool = True,
) -> sqlite3.Connection:
    resolved = Path(path).expanduser().resolve(strict=False)
    connection = sqlite3.connect(
        f"file:{quote(str(resolved))}?mode=ro",
        uri=True,
        timeout=timeout_seconds,
        factory=ClosingConnection,
    )
    _configure_connection(
        connection,
        timeout_seconds=timeout_seconds,
        row_factory=row_factory,
        wal=False,
        foreign_keys=False,
    )
    return connection


def _configure_connection(
    connection: sqlite3.Connection,
    *,
    timeout_seconds: int,
    row_factory: bool,
    wal: bool,
    foreign_keys: bool,
) -> None:
    if row_factory:
        connection.row_factory = sqlite3.Row
    connection.execute(f"pragma busy_timeout = {int(timeout_seconds) * 1000}")
    if wal:
        enable_wal(connection)
    if foreign_keys:
        connection.execute("pragma foreign_keys = on")


def enable_wal(connection: sqlite3.Connection) -> bool:
    try:
        connection.execute("pragma journal_mode = wal")
    except sqlite3.OperationalError:
        return False
    return True
