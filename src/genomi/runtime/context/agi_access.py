from __future__ import annotations

from pathlib import Path

from .agi_inference import infer_agi_record
from .agi_registry import _find_agi, _find_agi_by_intake_source
from .agi_selection import active_agi_record
from .normalize import (
    AGI_ACCESS_KEY,
    JsonObject,
    _default_user,
    _empty_agi_access_status,
    _find_user,
    _grant_agi_access,
)
from .storage import load_context, load_registry, save_context


def approve_agi_access(
    *,
    agi_id: str | None = None,
    source: str | Path | None = None,
    user_id: str | None = None,
    nickname: str | None = None,
    reason: str | None = None,
    root: str | Path | None = None,
) -> JsonObject:
    context = load_context(root)
    registry = load_registry(root)
    run = _resolve_access_target(
        registry,
        context,
        agi_id=agi_id,
        source=source,
        user_id=user_id,
        nickname=nickname,
        root=root,
    )
    if not isinstance(run, dict):
        raise KeyError(str(agi_id or source or user_id or nickname or context.get("active_agi_id") or "active_agi_id"))
    target_agi_id = str(run.get("agi_id") or "")
    context.setdefault("agis", {})[target_agi_id] = run
    context["active_agi_id"] = target_agi_id
    _grant_agi_access(context, target_agi_id, reason=reason or "User approved Active Genome Index access for this session.")
    save_context(context, root)
    return {
        "status": "completed",
        "active_agi_id": target_agi_id,
        "active_genome_index_access": agi_access_status(target_agi_id, context=context, registry=registry, root=root),
    }


def revoke_agi_access(*, agi_id: str | None = None, root: str | Path | None = None) -> JsonObject:
    context = load_context(root)
    grants = context.setdefault(AGI_ACCESS_KEY, {})
    if not isinstance(grants, dict):
        grants = {}
        context[AGI_ACCESS_KEY] = grants
    if agi_id:
        grants.pop(str(agi_id), None)
    else:
        grants.clear()
    save_context(context, root)
    return {
        "status": "completed",
        "revoked_agi_id": str(agi_id) if agi_id else None,
        "revoked_all": not bool(agi_id),
        "active_genome_index_access": agi_access_status(context.get("active_agi_id"), context=context, root=root),
    }


def agi_access_approved(
    agi: str | JsonObject | None = None,
    *,
    context: JsonObject | None = None,
    root: str | Path | None = None,
) -> bool:
    state = context if context is not None else load_context(root)
    if agi is None:
        run = active_agi_record(state, root=root)
        agi_id = str(run.get("agi_id") or "") if isinstance(run, dict) else str(state.get("active_agi_id") or "")
    elif isinstance(agi, dict):
        agi_id = str(agi.get("agi_id") or "")
    else:
        agi_id = str(agi or "")
    return bool(agi_access_status(agi_id, context=state, root=root).get("approved"))


def active_accessible_agi_record(context: JsonObject | None = None, root: str | Path | None = None) -> JsonObject | None:
    state = context if context is not None else load_context(root)
    active = active_agi_record(state, root=root)
    if active is not None and agi_access_approved(active, context=state, root=root):
        return active
    return None


def agi_access_status(
    agi_id: object | None,
    *,
    context: JsonObject | None = None,
    registry: JsonObject | None = None,
    root: str | Path | None = None,
) -> JsonObject:
    state = context if context is not None else load_context(root)
    target = str(agi_id or "")
    if not target:
        return _empty_agi_access_status(None)
    grants = state.get(AGI_ACCESS_KEY)
    grant = grants.get(target) if isinstance(grants, dict) else None
    if isinstance(grant, dict) and bool(grant.get("approved")):
        return {
            "agi_id": target,
            "approved": True,
            "approved_at": grant.get("approved_at"),
            "scope": grant.get("scope") or "session",
            "reason": grant.get("reason"),
        }
    reg = registry if registry is not None else load_registry(root)
    default_user = _default_user(reg)
    if isinstance(default_user, dict) and str(default_user.get("active_agi_id") or "") == target:
        return {
            "agi_id": target,
            "approved": True,
            "approved_at": default_user.get("default_set_at") or default_user.get("updated_at") or default_user.get("created_at"),
            "scope": "persistent_default",
            "reason": "A default user is configured; access is scoped to that user's selected Active Genome Index.",
        }
    return _empty_agi_access_status(target)


def _resolve_access_target(
    registry: JsonObject,
    context: JsonObject,
    *,
    agi_id: str | None,
    source: str | Path | None,
    user_id: str | None,
    nickname: str | None,
    root: str | Path | None,
) -> JsonObject | None:
    if source:
        existing = _find_agi_by_intake_source(registry, context, source)
        if isinstance(existing, dict):
            return existing
        inferred = infer_agi_record(source, status="set", root=root)
        stored = registry.get("agis", {}).get(str(inferred.get("agi_id") or ""))
        return stored if isinstance(stored, dict) else inferred
    if agi_id:
        return _find_agi(registry, agi_id)
    if user_id or nickname:
        user = _find_user(registry, user_id or nickname)
        active_id = str(user.get("active_agi_id") or "") if isinstance(user, dict) else ""
        run = registry.get("agis", {}).get(active_id)
        return run if isinstance(run, dict) else None
    active = active_agi_record(context, root=root)
    return active if isinstance(active, dict) else None
