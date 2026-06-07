from __future__ import annotations

from pathlib import Path

from ..paths import shared_evidence_db_path
from .agi_inference import infer_agi_record
from .agi_registry import _find_agi, save_agi_to_registry
from .normalize import (
    AGI_ACCESS_KEY,
    JsonObject,
    _attach_agi_to_user,
    _default_user,
    _ensure_user_record,
    _find_user,
    _find_user_id_for_agi,
    _grant_agi_access,
    _mark_default_user,
    _normalize_agi_record,
    _now,
    _path_str,
)
from .storage import load_context, load_registry, save_context, save_registry


def active_agi_record(context: JsonObject | None = None, root: str | Path | None = None) -> JsonObject | None:
    state = context if context is not None else load_context(root)
    registry = load_registry(root)
    active_id = state.get("active_agi_id")
    if active_id:
        registry_agi = registry.get("agis", {}).get(str(active_id))
        if isinstance(registry_agi, dict):
            return registry_agi
        agi = state.get("agis", {}).get(str(active_id))
        if isinstance(agi, dict):
            return agi
    return _default_selected_agi(registry=registry)


def set_active_agi_from_source(
    agi_intake_source_path: str | Path,
    *,
    agi_source_format: str | None = None,
    operation_result: JsonObject | None = None,
    status: str = "available",
    user_nickname: str | None = None,
    set_default_user: bool = False,
    db: str | Path | None = None,
    agi_path: str | Path | None = None,
    matches: str | Path | None = None,
    shared_db: str | Path | None = None,
    reference_fasta: str | Path | None = None,
    genotype_reference_fasta: str | Path | None = None,
    genome_build: str | None = None,
    grant_access: bool = False,
    root: str | Path | None = None,
) -> JsonObject:
    context = load_context(root)
    run = infer_agi_record(
        agi_intake_source_path,
        agi_source_format=agi_source_format,
        operation_result=operation_result,
        status=status,
        db=db,
        agi_path=agi_path,
        matches=matches,
        shared_db=shared_db,
        reference_fasta=reference_fasta,
        genotype_reference_fasta=genotype_reference_fasta,
        genome_build=genome_build,
        root=root,
    )
    agi_id = str(run["agi_id"])
    previous = context.get("agis", {}).get(agi_id) or load_registry(root).get("agis", {}).get(agi_id)
    if isinstance(previous, dict):
        run["created_at"] = previous.get("created_at") or run["created_at"]
        run["updated_at"] = _now()
    run = _normalize_agi_record(run)
    context.setdefault("agis", {})[agi_id] = run
    context["active_agi_id"] = agi_id
    context["shared_evidence_db"] = run.get("shared_evidence_db") or _path_str(shared_evidence_db_path(root))
    if user_nickname:
        registry = load_registry(root)
        user = _ensure_user_record(registry, nickname=user_nickname)
        _attach_agi_to_user(user, agi_id, make_active=True)
        context["active_user_id"] = user["user_id"]
        if set_default_user:
            _mark_default_user(registry, str(user["user_id"]))
        save_registry(registry, root)
    elif set_default_user:
        registry = load_registry(root)
        user = _active_user(context, registry)
        if not isinstance(user, dict):
            user = _ensure_user_record(registry, nickname="Default user")
        _attach_agi_to_user(user, agi_id, make_active=True)
        context["active_user_id"] = user["user_id"]
        _mark_default_user(registry, str(user["user_id"]))
        save_registry(registry, root)
    if grant_access:
        _grant_agi_access(context, agi_id, reason="User supplied a genome source path in this session.")
    save_context(context, root)
    save_agi_to_registry(run, root)
    return run


def set_active_agi_id(agi_id_or_nickname: str, root: str | Path | None = None) -> JsonObject:
    registry = load_registry(root)
    run = _find_agi(registry, agi_id_or_nickname)
    if not isinstance(run, dict):
        raise KeyError(str(agi_id_or_nickname))
    agi_id = str(run.get("agi_id") or "")
    context = load_context(root)
    context.setdefault("agis", {})[agi_id] = run
    context["active_agi_id"] = agi_id
    user_id = _find_user_id_for_agi(registry, agi_id)
    if user_id:
        context["active_user_id"] = user_id
    context["shared_evidence_db"] = run.get("shared_evidence_db") or _path_str(shared_evidence_db_path(root))
    save_context(context, root)
    return run


def clear_active_genome_index(*, forget_active_genome_indexes: bool = False, root: str | Path | None = None) -> JsonObject:
    from .agi_summary import describe_context

    context = load_context(root)
    previous = context.get("active_agi_id")
    context["active_agi_id"] = None
    context["active_user_id"] = None
    context[AGI_ACCESS_KEY] = {}
    if forget_active_genome_indexes:
        context["agis"] = {}
    save_context(context, root)
    return {
        "status": "completed",
        "previous_active_agi_id": previous,
        "forgot_active_genome_indexes": forget_active_genome_indexes,
        "context": describe_context(root),
    }


def _active_user(context: JsonObject, registry: JsonObject) -> JsonObject | None:
    user = _find_user(registry, context.get("active_user_id"))
    if isinstance(user, dict):
        return user
    active_agi_id = str(context.get("active_agi_id") or "")
    if active_agi_id:
        user_id = _find_user_id_for_agi(registry, active_agi_id)
        if user_id:
            return registry.get("users", {}).get(user_id)
    return _default_user(registry)


def _default_selected_agi(
    root: str | Path | None = None,
    *,
    registry: JsonObject | None = None,
) -> JsonObject | None:
    reg = registry if registry is not None else load_registry(root)
    user = _default_user(reg)
    active_id = str(user.get("active_agi_id") or "") if isinstance(user, dict) else ""
    agi = reg.get("agis", {}).get(active_id)
    return agi if isinstance(agi, dict) else None


def _selection_source(context: JsonObject, registry: JsonObject, active: JsonObject | None) -> str:
    if active is None:
        return "public_only"
    active_id = str(active.get("agi_id") or "")
    if context.get("active_agi_id") and str(context.get("active_agi_id")) == active_id:
        return "explicit_session"
    default_user = _default_user(registry)
    if isinstance(default_user, dict) and str(default_user.get("active_agi_id") or "") == active_id:
        return "default_user_auto_select"
    return "registry_selection"


def _auto_selected_agi_record(root: str | Path | None) -> JsonObject | None:
    return _default_selected_agi(root)
