from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

from ..runtime.context.normalize import (
    AGI_ACCESS_KEY,
    DEFAULT_USER_AUTO_SELECTION_KEY,
    GENOMI_CONTEXT_ENV,
    GENOMI_CONTEXT_POLICY_ENV,
)
from . import portal_state, portal_store

JsonObject = dict[str, Any]


def project_context_path(project_id: str, root: str | Path | None = None) -> Path:
    clean_project_id = _clean_project_id(project_id)
    return portal_state.state_path(root).parent / "project-contexts" / clean_project_id / "context.json"


def ensure_project_context(project_id: str, root: str | Path | None = None) -> Path:
    binding = portal_store.project_genome_binding(project_id, root=root)
    path = project_context_path(project_id, root=root)
    payload = _project_context_payload(binding)
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json_atomically(path, payload)
    return path


def agent_environment(project_id: str, root: str | Path | None = None) -> dict[str, str]:
    return {
        GENOMI_CONTEXT_ENV: str(ensure_project_context(project_id, root=root)),
        GENOMI_CONTEXT_POLICY_ENV: "explicit",
    }


def _project_context_payload(binding: JsonObject | None) -> JsonObject:
    agi_id = str(binding.get("agi_id") or "").strip() if isinstance(binding, dict) else ""
    access: JsonObject = {}
    if agi_id:
        access[agi_id] = {
            "approved": True,
            "approved_at": binding.get("approved_at"),
            "scope": "portal_project",
            "reason": "User selected this Active Genome Index for the current GenomiLab workspace.",
        }
    return {
        "active_agi_id": agi_id or None,
        "active_user_id": None,
        "agis": {},
        AGI_ACCESS_KEY: access,
        DEFAULT_USER_AUTO_SELECTION_KEY: False,
    }


def _clean_project_id(value: str) -> str:
    clean = str(value or "").strip()
    if not clean or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for character in clean):
        raise ValueError("invalid portal project id")
    return clean


def _write_json_atomically(path: Path, payload: JsonObject) -> None:
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
