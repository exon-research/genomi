"""Private local-file primitives for Genomi-owned runtime state.

These helpers centralize the small but security-relevant details shared by
runtime metadata and background jobs: private POSIX modes, atomic replacement,
and refusing symbolic links at write/read boundaries.  They intentionally do
not encrypt data; encryption and key management are a separate product layer.
"""

from __future__ import annotations

import errno
import json
import os
import tempfile
from pathlib import Path
from typing import Any, BinaryIO

PRIVATE_DIRECTORY_MODE = 0o700
PRIVATE_FILE_MODE = 0o600


class UnsafePrivateStoragePathError(OSError):
    """Raised when private runtime state would traverse a symbolic link."""


def private_root_for_path(path: str | Path, root: str | Path) -> Path | None:
    """Return ``root`` when ``path`` is lexically inside it, otherwise ``None``.

    This deliberately does not resolve symlinks: resolving first would hide the
    exact condition the private-storage boundary needs to reject.
    """

    candidate = _absolute(path)
    boundary = _absolute(root)
    try:
        candidate.relative_to(boundary)
    except ValueError:
        return None
    return boundary


def ensure_private_directory(path: str | Path, *, private_root: str | Path | None = None) -> Path:
    """Create/harden a Genomi-owned directory and reject symlink components.

    When ``private_root`` is provided, every component from that boundary to
    ``path`` is Genomi-owned and receives mode ``0700``.  Ancestors above the
    boundary are not modified.  Without a boundary, only the requested
    directory is hardened; this is useful for explicitly configured paths
    whose existing parent directories are user-owned.
    """

    target = _absolute(path)
    if private_root is None:
        _ensure_one_private_directory(target, create_parents=True, harden_existing=True)
        return target

    boundary = _absolute(private_root)
    try:
        relative = target.relative_to(boundary)
    except ValueError as exc:
        raise ValueError(f"private directory {target} is outside private root {boundary}") from exc

    _ensure_one_private_directory(boundary, create_parents=True, harden_existing=True)
    current = boundary
    for part in relative.parts:
        current = current / part
        _ensure_one_private_directory(current, create_parents=False, harden_existing=True)
    return target


def atomic_write_private_json(
    path: str | Path,
    payload: Any,
    *,
    private_root: str | Path | None = None,
    default: Any = None,
) -> Path:
    """Serialize JSON and atomically replace a private ``0600`` file."""

    text = json.dumps(payload, indent=2, sort_keys=True, default=default) + "\n"
    return atomic_write_private_text(path, text, private_root=private_root)


def atomic_write_private_text(
    path: str | Path,
    text: str,
    *,
    private_root: str | Path | None = None,
    encoding: str = "utf-8",
) -> Path:
    """Atomically replace ``path`` with private text without following links."""

    target = _absolute(path)
    _prepare_private_parent(target, private_root=private_root)
    _refuse_symlink(target)

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=str(target.parent),
    )
    temporary = Path(temporary_name)
    descriptor_open = True
    try:
        os.fchmod(descriptor, PRIVATE_FILE_MODE)
        with os.fdopen(descriptor, "w", encoding=encoding) as handle:
            descriptor_open = False
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())

        # Refuse a link even if it appeared after the first check.  os.replace
        # would replace (not follow) it, but failing closed makes the contract
        # explicit and visible to callers.
        _refuse_symlink(target)
        os.replace(temporary, target)
        _fsync_directory(target.parent)
        return target
    finally:
        if descriptor_open:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def open_private_binary_append(
    path: str | Path,
    *,
    private_root: str | Path | None = None,
) -> BinaryIO:
    """Open a private append-only binary file without following symlinks."""

    target = _absolute(path)
    _prepare_private_parent(target, private_root=private_root)
    _refuse_symlink(target)
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(target, flags, PRIVATE_FILE_MODE)
    try:
        os.fchmod(descriptor, PRIVATE_FILE_MODE)
        return os.fdopen(descriptor, "ab")
    except Exception:
        os.close(descriptor)
        raise


def read_private_json(path: str | Path) -> Any:
    """Read JSON from a regular file while refusing target/parent symlinks."""

    target = _absolute(path)
    _refuse_symlink(target.parent)
    _refuse_symlink(target)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(target, flags)
    with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
        return json.load(handle)


def refuse_symlink(path: str | Path) -> None:
    """Public assertion used before iterating a private runtime directory."""

    _refuse_symlink(_absolute(path))


def _prepare_private_parent(target: Path, *, private_root: str | Path | None) -> None:
    parent = target.parent
    if private_root is not None:
        ensure_private_directory(parent, private_root=private_root)
        return

    _refuse_symlink(parent)
    existed = parent.exists()
    parent.mkdir(mode=PRIVATE_DIRECTORY_MODE, parents=True, exist_ok=True)
    _refuse_symlink(parent)
    if not parent.is_dir():
        raise NotADirectoryError(str(parent))
    if not existed:
        _harden_directory(parent)


def _ensure_one_private_directory(
    path: Path,
    *,
    create_parents: bool,
    harden_existing: bool,
) -> None:
    _refuse_symlink(path)
    existed = path.exists()
    path.mkdir(mode=PRIVATE_DIRECTORY_MODE, parents=create_parents, exist_ok=True)
    _refuse_symlink(path)
    if not path.is_dir():
        raise NotADirectoryError(str(path))
    if harden_existing or not existed:
        _harden_directory(path)


def _harden_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        os.fchmod(descriptor, PRIVATE_DIRECTORY_MODE)
    finally:
        os.close(descriptor)


def _refuse_symlink(path: Path) -> None:
    if path.is_symlink():
        raise UnsafePrivateStoragePathError(
            errno.ELOOP,
            f"refusing symbolic link for private storage: {path}",
            str(path),
        )


def _absolute(path: str | Path) -> Path:
    return Path(os.path.abspath(os.path.expanduser(str(path))))


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)
