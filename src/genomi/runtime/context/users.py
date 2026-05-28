from __future__ import annotations

from pathlib import Path

from .normalize import (
    JsonObject,
    _assert_unique_user_nickname,
    _attach_agi_to_user,
    _ensure_user_record,
    _find_user,
    _grant_agi_access,
    _mark_default_user,
    _normalize_agi_record,
    _normalize_nickname,
    _now,
)
from .agi import (
    _find_agi,
    describe_user,
    infer_source_run,
)
from .storage import (
    load_context,
    load_registry,
    save_context,
    save_registry,
)


def list_users(root: str | Path | None = None) -> list[JsonObject]:
    registry = load_registry(root)
    users = [user for user in registry.get("users", {}).values() if isinstance(user, dict)]
    return [
        describe_user(user, registry=registry)
        for user in sorted(users, key=lambda item: str(item.get("updated_at", "")), reverse=True)
    ]


def select_user(user_id_or_nickname: str, root: str | Path | None = None) -> JsonObject:
    registry = load_registry(root)
    user = _find_user(registry, user_id_or_nickname)
    if not isinstance(user, dict):
        raise KeyError(str(user_id_or_nickname))
    context = load_context(root)
    context["active_user_id"] = user["user_id"]
    context["active_agi_id"] = user.get("active_agi_id")
    active_id = str(user.get("active_agi_id") or "")
    if active_id and active_id in registry.get("agis", {}):
        context.setdefault("agis", {})[active_id] = registry["agis"][active_id]
    save_context(context, root)
    return user


def rename_user(user_id_or_nickname: str, new_nickname: str, root: str | Path | None = None) -> JsonObject:
    registry = load_registry(root)
    user = _find_user(registry, user_id_or_nickname)
    if not isinstance(user, dict):
        raise KeyError(str(user_id_or_nickname))
    nickname = _normalize_nickname(new_nickname)
    if not nickname:
        raise ValueError("new_nickname is required")
    _assert_unique_user_nickname(registry, nickname, existing_user_id=str(user["user_id"]))
    user["nickname"] = nickname
    user["updated_at"] = _now()
    save_registry(registry, root)
    return user


def assign_user_genome(
    *,
    user_id: str | None = None,
    nickname: str | None = None,
    agi_id: str | None = None,
    source: str | Path | None = None,
    source_format: str | None = None,
    db: str | Path | None = None,
    active_genome_index_path: str | Path | None = None,
    matches: str | Path | None = None,
    shared_db: str | Path | None = None,
    reference_fasta: str | Path | None = None,
    genotype_reference_fasta: str | Path | None = None,
    genome_build: str | None = None,
    set_active: bool = True,
    set_default_user: bool = False,
    root: str | Path | None = None,
) -> JsonObject:
    if not nickname and not user_id:
        raise ValueError("user_id or nickname is required")
    registry = load_registry(root)
    user = _find_user(registry, user_id) if user_id else None
    if not isinstance(user, dict):
        user = _ensure_user_record(registry, nickname=nickname or user_id or "User")
    run: JsonObject | None = None
    if agi_id:
        run = _find_agi(registry, agi_id)
        if not isinstance(run, dict):
            raise KeyError(str(agi_id))
    elif source:
        run = infer_source_run(
            source,
            source_format=source_format,
            status="set",
            db=db,
            active_genome_index_path=active_genome_index_path,
            matches=matches,
            shared_db=shared_db,
            reference_fasta=reference_fasta,
            genotype_reference_fasta=genotype_reference_fasta,
            genome_build=genome_build,
            root=root,
        )
        existing = registry.get("agis", {}).get(str(run.get("agi_id") or ""))
        if isinstance(existing, dict):
            run = {**existing, **{key: value for key, value in run.items() if value is not None}, "updated_at": _now()}
        registry.setdefault("agis", {})[str(run["agi_id"])] = _normalize_agi_record(run)
    else:
        raise ValueError("agi_id or source is required")
    target_agi_id = str(run.get("agi_id") or "")
    _attach_agi_to_user(user, target_agi_id, make_active=set_active or not user.get("active_agi_id"))
    if set_default_user:
        _mark_default_user(registry, str(user["user_id"]))
    save_registry(registry, root)
    context = load_context(root)
    if set_active:
        context["active_user_id"] = user["user_id"]
        context["active_agi_id"] = target_agi_id
        context.setdefault("agis", {})[target_agi_id] = registry["agis"][target_agi_id]
        if source:
            _grant_agi_access(context, target_agi_id, reason="User supplied a genome source path in this session.")
        save_context(context, root)
    return user


def set_default_user(user_id_or_nickname: str, root: str | Path | None = None) -> JsonObject:
    registry = load_registry(root)
    user = _find_user(registry, user_id_or_nickname)
    if not isinstance(user, dict):
        raise KeyError(str(user_id_or_nickname))
    _mark_default_user(registry, str(user["user_id"]))
    save_registry(registry, root)
    return user


def clear_default_user(root: str | Path | None = None) -> JsonObject:
    registry = load_registry(root)
    changed = bool(registry.get("default_user_id"))
    registry["default_user_id"] = None
    for user in registry.setdefault("users", {}).values():
        if isinstance(user, dict) and user.get("default"):
            user["default"] = False
            user["updated_at"] = _now()
            changed = True
    save_registry(registry, root)
    return {
        "status": "completed",
        "cleared_default": changed,
        "users": list_users(root),
    }
