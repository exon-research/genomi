from __future__ import annotations

import json
import os
from pathlib import Path

from ..host_response import host_response_profiles
from ..paths import (
    genomi_data_root,
    shared_evidence_db_path,
)
from .normalize import (
    AGI_ACCESS_KEY,
    CONTEXT_FILE_NAME,
    CONTEXT_VERSION,
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


def registry_path(root: str | Path | None = None) -> Path:
    return genomi_data_root(root) / REGISTRY_FILE_NAME


def load_context(root: str | Path | None = None) -> JsonObject:
    path = context_path(root)
    if not path.exists():
        return _empty_context(root)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _empty_context(root)
    if not isinstance(value, dict):
        return _empty_context(root)
    value = _normalize_context(value, root)
    value.setdefault(AGI_ACCESS_KEY, {})
    value.setdefault("shared_evidence_db", _path_str(shared_evidence_db_path(root)))
    return value


def load_registry(root: str | Path | None = None) -> JsonObject:
    path = registry_path(root)
    if not path.exists():
        return _empty_registry()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _empty_registry()
    if not isinstance(value, dict):
        return _empty_registry()
    return _normalize_registry(value)


def save_context(context: JsonObject, root: str | Path | None = None) -> JsonObject:
    path = context_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    context = _normalize_context(context, root)
    context["version"] = CONTEXT_VERSION
    context["updated_at"] = _now()
    path.write_text(json.dumps(context, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return context


def save_registry(registry: JsonObject, root: str | Path | None = None) -> JsonObject:
    path = registry_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    registry = _normalize_registry(registry)
    registry["version"] = CONTEXT_VERSION
    registry["updated_at"] = _now()
    path.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return registry


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
        "default_user_auto_selection": "A configured default user is auto-selected independent of this policy, but only that user's selected Active Genome Index is readable.",
        "recommended": "explicit",
    }
