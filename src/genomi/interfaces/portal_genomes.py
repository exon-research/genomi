from __future__ import annotations

from typing import Any

from ..operations import OperationError, call_operation
from . import portal_project_genomes, portal_store, portal_turns

JsonObject = dict[str, Any]


def genome_inventory_payload(project_id: str | None = None) -> JsonObject:
    inventory = call_operation("active_genome_index.list", {})
    active = _scoped_active(inventory, project_id)
    users = [_safe_user(user, active) for user in _objects(inventory.get("users"))]
    genomes = [_safe_genome(genome, active) for genome in _objects(inventory.get("active_genome_indexes"))]
    return {
        "status": _public_text(inventory.get("status") or "completed"),
        "active": {
            "agi_id": _public_text(active.get("agi_id")),
            "user_id": _public_text(active.get("user_id")),
            "selection_source": _public_text(active.get("selection_source")),
        },
        "summary": {
            "genome_count": len(genomes),
            "profile_count": len(users),
        },
        "users": users,
        "genomes": genomes,
    }


def select_active_genome(payload: JsonObject, *, project_id: str) -> JsonObject:
    if portal_store.get_project(project_id) is None:
        raise OperationError("portal_project_not_found", "Workspace not found.")
    agi_id = _public_text(payload.get("agiId") or payload.get("agi_id"))
    user_id = _public_text(payload.get("userId") or payload.get("user_id"))
    nickname = _public_text(payload.get("nickname"))
    if not agi_id and not user_id and not nickname:
        raise OperationError("invalid_params", "Choose a genome or profile.")
    inventory = call_operation("active_genome_index.list", {})
    target = _resolve_selection(inventory, agi_id=agi_id, user_id=user_id, nickname=nickname)
    target_agi_id = _public_text(target.get("agi_id"))
    if not target_agi_id:
        raise OperationError("missing_context", "That genome is no longer available. Refresh the genome list and choose another genome.")
    target_user_id = _selection_user_id(
        inventory,
        target,
        requested_user_id=user_id,
        requested_nickname=nickname,
    )
    binding = portal_store.bind_project_genome(
        project_id,
        agi_id=target_agi_id,
        user_id=target_user_id,
    )
    if binding is None:
        raise OperationError("portal_project_not_found", "Workspace not found.")
    portal_project_genomes.ensure_project_context(project_id)
    return {
        "status": "completed",
        "selection": {
            "status": "completed",
            "active_agi_id": target_agi_id,
            "access": {"approved": True, "scope": "portal_project"},
        },
        "inventory": genome_inventory_payload(project_id),
    }


def _selection_user_id(
    inventory: JsonObject,
    genome: JsonObject,
    *,
    requested_user_id: str,
    requested_nickname: str,
) -> str:
    users = _objects(inventory.get("users"))
    agi_id = _public_text(genome.get("agi_id"))
    owner_ids = {
        _public_text(item.get("user_id"))
        for item in _objects(genome.get("users"))
        if _public_text(item.get("user_id"))
    }
    owner_ids.update(
        _public_text(item.get("user_id"))
        for item in users
        if agi_id
        and agi_id in [_public_text(value) for value in item.get("agi_ids", [])]
        and _public_text(item.get("user_id"))
    )
    if requested_user_id or requested_nickname:
        selected = next(
            (
                item
                for item in users
                if (requested_user_id and _public_text(item.get("user_id")) == requested_user_id)
                or (
                    requested_nickname
                    and _public_text(item.get("nickname")).casefold()
                    == requested_nickname.casefold()
                )
            ),
            {},
        )
        selected_user_id = _public_text(selected.get("user_id"))
        if not selected_user_id or selected_user_id not in owner_ids:
            raise OperationError(
                "invalid_params",
                "That Genomi user does not own the selected Active Genome Index.",
            )
        return selected_user_id
    return next(iter(owner_ids)) if len(owner_ids) == 1 else ""


def _scoped_active(inventory: JsonObject, project_id: str | None) -> JsonObject:
    if not project_id:
        return _object(inventory.get("active"))
    binding = portal_store.project_genome_binding(project_id)
    target_agi_id = _public_text(binding.get("agi_id")) if isinstance(binding, dict) else ""
    genomes = _objects(inventory.get("active_genome_indexes"))
    if not target_agi_id or not any(_public_text(item.get("agi_id")) == target_agi_id for item in genomes):
        return {"selection_source": "portal_project"}
    user = next(
        (
            item
            for item in _objects(inventory.get("users"))
            if target_agi_id in [_public_text(value) for value in item.get("agi_ids", [])]
        ),
        {},
    )
    return {
        "agi_id": target_agi_id,
        "user_id": _public_text(user.get("user_id")),
        "selection_source": "portal_project",
    }


def _resolve_selection(
    inventory: JsonObject,
    *,
    agi_id: str,
    user_id: str,
    nickname: str,
) -> JsonObject:
    genomes = _objects(inventory.get("active_genome_indexes"))
    if agi_id:
        return next((item for item in genomes if _public_text(item.get("agi_id")) == agi_id), {})
    users = _objects(inventory.get("users"))
    user = next(
        (
            item
            for item in users
            if (user_id and _public_text(item.get("user_id")) == user_id)
            or (nickname and _public_text(item.get("nickname")).casefold() == nickname.casefold())
        ),
        {},
    )
    target_agi_id = _public_text(user.get("active_agi_id"))
    return next((item for item in genomes if _public_text(item.get("agi_id")) == target_agi_id), {})


def _safe_user(user: JsonObject, active: JsonObject) -> JsonObject:
    active_agi_id = _public_text(user.get("active_agi_id"))
    user_id = _public_text(user.get("user_id"))
    agi_ids = user.get("agi_ids") if isinstance(user.get("agi_ids"), list) else []
    return {
        "user_id": user_id,
        "nickname": _public_text(user.get("nickname")),
        "default": bool(user.get("default")),
        "active": bool(user_id and user_id == _public_text(active.get("user_id"))),
        "active_agi_id": active_agi_id,
        "genome_count": len([item for item in agi_ids if item]),
    }


def _safe_genome(genome: JsonObject, active: JsonObject) -> JsonObject:
    names = _object(genome.get("names"))
    source = _object(genome.get("source"))
    readiness = _object(genome.get("active_genome_index_readiness"))
    agi_id = _public_text(genome.get("agi_id"))
    users = [_safe_user_ref(user, active) for user in _objects(genome.get("users"))]
    return {
        "agi_id": agi_id,
        "display_name": _public_text(names.get("display") or genome.get("nickname") or genome.get("sample_slug") or _short_id(agi_id)),
        "sample_slug": _public_text(names.get("sample_slug") or genome.get("sample_slug")),
        "active": bool(agi_id and agi_id == _public_text(active.get("agi_id"))),
        "users": users,
        "status": _public_text(genome.get("status")),
        "genome_build": _public_text(genome.get("genome_build")),
        "source": {
            "format": _public_text(source.get("format")),
            "kind": _public_text(source.get("kind")),
            "provider": _public_text(source.get("provider")),
            "member": _public_text(source.get("member")),
        },
        "digitized": bool(genome.get("digitized")),
        "readiness": {
            "status": _public_text(readiness.get("status")),
            "complete": bool(readiness.get("complete")),
            "variants_ready": bool(readiness.get("variants_ready")),
        },
    }


def _safe_user_ref(user: JsonObject, active: JsonObject) -> JsonObject:
    user_id = _public_text(user.get("user_id"))
    return {
        "user_id": user_id,
        "nickname": _public_text(user.get("nickname")),
        "default": bool(user.get("default")),
        "active": bool(user_id and user_id == _public_text(active.get("user_id"))),
    }


def _objects(value: object) -> list[JsonObject]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _object(value: object) -> JsonObject:
    return value if isinstance(value, dict) else {}


def _public_text(value: object) -> str:
    return portal_turns.prompt_safe_text("" if value is None else str(value)).strip()


def _short_id(value: str) -> str:
    clean = _public_text(value)
    if not clean:
        return ""
    return clean if len(clean) <= 14 else clean[:10] + "..."
