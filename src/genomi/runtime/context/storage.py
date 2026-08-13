from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

try:  # POSIX is the supported production boundary; tests retain a thread lock.
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None  # type: ignore[assignment]

from ..host_response import host_response_profiles
from ..paths import (
    genomi_data_root,
    shared_evidence_db_path,
)
from ..private_storage import (
    PRIVATE_FILE_MODE,
    atomic_write_private_json,
    ensure_private_directory,
    private_root_for_path,
    read_private_json,
    refuse_symlink,
)
from .normalize import (
    AGI_ACCESS_KEY,
    CONTEXT_FILE_NAME,
    DEFAULT_CONTEXT_POLICY,
    GENOMI_CONTEXT_ENV,
    GENOMI_CONTEXT_POLICY_ENV,
    GENOMI_SESSION_ENV,
    REGISTRY_FILE_NAME,
    SESSIONS_DIR_NAME,
    JsonObject,
    _agent_session_id,
    _empty_context,
    _empty_registry,
    _normalize_context,
    _normalize_registry,
    _now,
    _path_str,
    _redact_session_value,
    _stable_session_id,
    _workspace_session_id,
)


_CONTEXT_LOCKS_GUARD = threading.Lock()
_CONTEXT_LOCKS: dict[Path, threading.RLock] = {}
_CONTEXT_LOCK_LOCAL = threading.local()
_AUTHORITY_TRANSACTION_FILE = ".context-registry.transaction.json"


def context_path(root: str | Path | None = None) -> Path:
    if root is not None:
        return genomi_data_root(root) / CONTEXT_FILE_NAME
    configured_context = os.environ.get(GENOMI_CONTEXT_ENV)
    if configured_context:
        return Path(configured_context).expanduser()
    session_id = os.environ.get(GENOMI_SESSION_ENV)
    if session_id:
        return genomi_data_root() / SESSIONS_DIR_NAME / _stable_session_id(session_id) / CONTEXT_FILE_NAME
    agent_session = _agent_session_id()
    if agent_session:
        return genomi_data_root() / SESSIONS_DIR_NAME / _stable_session_id(agent_session) / CONTEXT_FILE_NAME
    return genomi_data_root() / SESSIONS_DIR_NAME / _workspace_session_id() / CONTEXT_FILE_NAME


@contextmanager
def context_authority_lock(root: str | Path | None = None) -> Iterator[None]:
    """Serialize current-user context reads/writes across threads and processes.

    Compound context operations hold this boundary for their full read/modify/
    write cycle. Ordinary readers and writers enter it briefly, so a selection
    cannot become current halfway through a related registry commit.
    """

    authority_root = genomi_data_root(root)
    lock_path = authority_root / ".context-registry.authority.lock"
    with _CONTEXT_LOCKS_GUARD:
        process_lock = _CONTEXT_LOCKS.setdefault(lock_path, threading.RLock())
    with process_lock:
        depths = dict(getattr(_CONTEXT_LOCK_LOCAL, "depths", {}))
        depth = int(depths.get(lock_path, 0))
        if depth:
            depths[lock_path] = depth + 1
            _CONTEXT_LOCK_LOCAL.depths = depths
            try:
                yield
            finally:
                latest = dict(getattr(_CONTEXT_LOCK_LOCAL, "depths", {}))
                remaining = int(latest.get(lock_path, 1)) - 1
                if remaining:
                    latest[lock_path] = remaining
                else:
                    latest.pop(lock_path, None)
                _CONTEXT_LOCK_LOCAL.depths = latest
            return

        boundary = private_root_for_path(lock_path, genomi_data_root(root))
        if boundary is not None:
            ensure_private_directory(lock_path.parent, private_root=boundary)
        else:
            # An explicitly configured context may live in a user-owned
            # directory.  Create a missing parent privately, but never chmod an
            # existing directory outside Genomi's own data root.
            refuse_symlink(lock_path.parent)
            lock_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            refuse_symlink(lock_path.parent)
        refuse_symlink(lock_path)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(lock_path, flags, PRIVATE_FILE_MODE)
        os.fchmod(descriptor, PRIVATE_FILE_MODE)
        depths[lock_path] = 1
        _CONTEXT_LOCK_LOCAL.depths = depths
        try:
            if fcntl is not None:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
            _recover_authority_transaction(root)
            yield
        finally:
            latest = dict(getattr(_CONTEXT_LOCK_LOCAL, "depths", {}))
            latest.pop(lock_path, None)
            _CONTEXT_LOCK_LOCAL.depths = latest
            if fcntl is not None:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)


def registry_path(root: str | Path | None = None) -> Path:
    return genomi_data_root(root) / REGISTRY_FILE_NAME


def load_context(root: str | Path | None = None) -> JsonObject:
    with context_authority_lock(root):
        path = context_path(root)
        if not path.exists():
            return _empty_context(root)
        try:
            value = read_private_json(path)
        except (ValueError, OSError):
            return _empty_context(root)
        if not isinstance(value, dict):
            return _empty_context(root)
        value = _normalize_context(value, root)
        value.setdefault(AGI_ACCESS_KEY, {})
        value.setdefault("shared_evidence_db", _path_str(shared_evidence_db_path(root)))
        return value


def load_registry(root: str | Path | None = None) -> JsonObject:
    with context_authority_lock(root):
        path = registry_path(root)
        if not path.exists():
            return _empty_registry()
        try:
            value = read_private_json(path)
        except (ValueError, OSError):
            return _empty_registry()
        if not isinstance(value, dict):
            return _empty_registry()
        return _normalize_registry(value)


def save_context(context: JsonObject, root: str | Path | None = None) -> JsonObject:
    with context_authority_lock(root):
        return _save_context_at_path_locked(
            context,
            context_path(root),
            root,
            stamp_updated_at=True,
        )


def save_registry(registry: JsonObject, root: str | Path | None = None) -> JsonObject:
    with context_authority_lock(root):
        return _save_registry_locked(registry, root)


def save_context_and_registry(
    context: JsonObject,
    registry: JsonObject,
    root: str | Path | None = None,
) -> tuple[JsonObject, JsonObject]:
    """Publish session selection and registry state as one recoverable commit.

    The journal is private and atomically written before either destination.
    If the process exits between the two replacements, the next authority-lock
    holder completes the same generation before exposing either store.
    """

    with context_authority_lock(root):
        normalized_context = _normalize_context(context, root)
        normalized_context["updated_at"] = _now()
        normalized_registry = _normalize_registry(registry)
        normalized_registry["updated_at"] = _now()
        transaction_path = _authority_transaction_path(root)
        atomic_write_private_json(
            transaction_path,
            {
                "context_path": str(context_path(root).absolute()),
                "context": normalized_context,
                "registry": normalized_registry,
            },
            private_root=genomi_data_root(root),
        )
        _save_registry_locked(normalized_registry, root, stamp_updated_at=False)
        _save_context_at_path_locked(
            normalized_context,
            context_path(root),
            root,
            stamp_updated_at=False,
        )
        transaction_path.unlink(missing_ok=True)
        return normalized_context, normalized_registry


def _save_registry_locked(
    registry: JsonObject,
    root: str | Path | None,
    *,
    stamp_updated_at: bool = True,
) -> JsonObject:
    path = registry_path(root)
    registry = _normalize_registry(registry)
    if stamp_updated_at:
        registry["updated_at"] = _now()
    atomic_write_private_json(
        path,
        registry,
        private_root=private_root_for_path(path, genomi_data_root(root)),
    )
    return registry


def _save_context_at_path_locked(
    context: JsonObject,
    path: Path,
    root: str | Path | None,
    *,
    stamp_updated_at: bool,
) -> JsonObject:
    context = _normalize_context(context, root)
    if stamp_updated_at:
        context["updated_at"] = _now()
    atomic_write_private_json(
        path,
        context,
        private_root=private_root_for_path(path, genomi_data_root(root)),
    )
    return context


def _authority_transaction_path(root: str | Path | None) -> Path:
    return genomi_data_root(root) / _AUTHORITY_TRANSACTION_FILE


def _recover_authority_transaction(root: str | Path | None) -> None:
    transaction_path = _authority_transaction_path(root)
    if not transaction_path.exists():
        return
    try:
        transaction = read_private_json(transaction_path)
    except (OSError, ValueError):
        transaction_path.unlink(missing_ok=True)
        return
    if not isinstance(transaction, dict):
        transaction_path.unlink(missing_ok=True)
        return
    context = transaction.get("context")
    registry = transaction.get("registry")
    raw_context_path = transaction.get("context_path")
    if (
        not isinstance(context, dict)
        or not isinstance(registry, dict)
        or raw_context_path in (None, "")
    ):
        transaction_path.unlink(missing_ok=True)
        return
    target_context_path = Path(str(raw_context_path))
    if target_context_path.name != CONTEXT_FILE_NAME:
        transaction_path.unlink(missing_ok=True)
        return
    _save_registry_locked(registry, root, stamp_updated_at=False)
    _save_context_at_path_locked(
        context,
        target_context_path,
        root,
        stamp_updated_at=False,
    )
    transaction_path.unlink(missing_ok=True)


def get_response_profile_id(registry: JsonObject) -> str | None:
    """Return the persisted response-profile id from the registry, or None."""
    value = registry.get("response_profile")
    if value in (None, ""):
        return None
    return str(value)


def set_response_profile_id(profile_id: str | None, root: str | Path | None = None) -> JsonObject:
    """Persist the chosen response-profile id in registry.json.

    Pass `None` (or an empty string) to clear the selection and fall back to
    the catalog default. Raises `ValueError` if `profile_id` does not match a
    known profile id in `host_response_profiles.json`.
    """
    catalog = host_response_profiles()
    known_ids = {
        str(profile.get("id"))
        for profile in (catalog.get("profiles") or [])
        if isinstance(profile, dict) and profile.get("id")
    }
    normalized = str(profile_id).strip() if profile_id not in (None, "") else None
    if normalized is not None and normalized not in known_ids:
        raise ValueError(
            f"Unknown response profile id: {normalized!r}. Known ids: {sorted(known_ids)}."
        )
    with context_authority_lock(root):
        registry = load_registry(root)
        registry["response_profile"] = normalized
        return save_registry(registry, root)


def context_scope(root: str | Path | None = None) -> JsonObject:
    if root is not None:
        return {"type": "explicit_root", "id": _path_str(genomi_data_root(root))}
    configured_context = os.environ.get(GENOMI_CONTEXT_ENV)
    if configured_context:
        return {"type": "context_file_env", "env": GENOMI_CONTEXT_ENV, "id": _path_str(configured_context)}
    session_id = os.environ.get(GENOMI_SESSION_ENV)
    if session_id:
        return {"type": "session_env", "env": GENOMI_SESSION_ENV, "id": _stable_session_id(session_id)}
    agent_session = _agent_session_id()
    if agent_session:
        env_name, raw_value = agent_session.split(":", 1)
        return {"type": "agent_chat_env", "env": env_name, "id": _stable_session_id(agent_session), "source": _redact_session_value(raw_value)}
    return {"type": "workspace", "id": _workspace_session_id(), "workspace": _path_str(Path.cwd())}


def context_policy() -> JsonObject:
    mode = (os.environ.get(GENOMI_CONTEXT_POLICY_ENV) or DEFAULT_CONTEXT_POLICY).strip().lower()
    if mode not in {"explicit", "resume", "auto"}:
        mode = DEFAULT_CONTEXT_POLICY
    return {
        "mode": mode,
        "default": DEFAULT_CONTEXT_POLICY,
        "env": GENOMI_CONTEXT_POLICY_ENV,
        "implicit_artifact_selection": mode == "auto",
        "default_user_auto_selection": "A configured default user is auto-selected as metadata independent of this policy; the selected Active Genome Index still requires current-session approval before it is read.",
        "recommended": "explicit",
    }
