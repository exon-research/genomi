from __future__ import annotations

from contextlib import contextmanager
import json
import os
import threading
import uuid
from pathlib import Path
from typing import Any, Callable

from ..runtime.paths import genomi_data_root

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback remains process-local.
    fcntl = None  # type: ignore[assignment]

JsonObject = dict[str, Any]
_LOCK = threading.RLock()
_REQUIRED_OBJECT_SECTIONS = ("projects", "frames", "messages", "artifacts", "artifact_versions")


class PortalStateError(RuntimeError):
    """Raised when persisted portal state cannot be safely loaded."""


def state_path(root: str | Path | None = None) -> Path:
    return genomi_data_root(root) / "portal" / "state.json"


def mutate_state(callback: Callable[[JsonObject], Any], root: str | Path | None = None) -> Any:
    with _LOCK:
        with _state_file_lock(root):
            state = _read_state_unlocked(root)
            result = callback(state)
            _write_state_unlocked(state, root)
            return result


def read_state(root: str | Path | None = None) -> JsonObject:
    with _LOCK:
        with _state_file_lock(root):
            return _read_state_unlocked(root)


def _read_state_unlocked(root: str | Path | None = None) -> JsonObject:
    path = state_path(root)
    if not path.is_file():
        return _empty_state()
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PortalStateError(f"could not read portal state at {path}") from exc
    except json.JSONDecodeError as exc:
        raise PortalStateError(f"portal state at {path} is not valid JSON") from exc
    if not isinstance(loaded, dict):
        raise PortalStateError(f"portal state at {path} must be a JSON object")
    if "schema_version" in loaded:
        raise PortalStateError(f"portal state at {path} contains an unsupported schema marker")
    state = _empty_state()
    for key in _REQUIRED_OBJECT_SECTIONS:
        if key not in loaded:
            raise PortalStateError(f"portal state section {key!r} at {path} is required")
        value = loaded[key]
        if not isinstance(value, dict):
            raise PortalStateError(f"portal state section {key!r} at {path} must be a JSON object")
        state[key] = value
    active_project_id = loaded.get("active_project_id")
    if active_project_id is not None and not isinstance(active_project_id, str):
        raise PortalStateError(f"portal state active_project_id at {path} must be a string or null")
    state["active_project_id"] = active_project_id if isinstance(active_project_id, str) else None
    return state


def _write_state_unlocked(state: JsonObject, root: str | Path | None = None) -> None:
    path = state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(state, indent=2, sort_keys=True))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    _fsync_directory(path.parent)


@contextmanager
def _state_file_lock(root: str | Path | None = None) -> Any:
    path = state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(".lock")
    with lock_path.open("a+", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _fsync_directory(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        try:
            os.fsync(fd)
        except OSError:
            return
    finally:
        os.close(fd)


def _empty_state() -> JsonObject:
    return {
        "active_project_id": None,
        "projects": {},
        "frames": {},
        "messages": {},
        "artifacts": {},
        "artifact_versions": {},
    }
