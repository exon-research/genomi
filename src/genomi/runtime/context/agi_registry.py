from __future__ import annotations

from pathlib import Path

from .agi_inference import _resolved_intake_source_path
from .agi_records import _is_digitized_agi_record
from .normalize import (
    AGI_ACCESS_KEY,
    JsonObject,
    _attach_agi_to_user,
    _find_user_id_for_agi,
    _normalize_agi_record,
    _now,
)
from .storage import load_context, load_registry, save_context, save_registry


def find_agi(agi_id_or_nickname: str, root: str | Path | None = None) -> JsonObject | None:
    return _find_agi(load_registry(root), agi_id_or_nickname)


def find_agi_by_intake_source(
    agi_intake_source: str | Path,
    root: str | Path | None = None,
) -> JsonObject | None:
    registry = load_registry(root)
    context = load_context(root)
    return _find_agi_by_intake_source(registry, context, agi_intake_source)


def save_agi_to_registry(run: JsonObject, root: str | Path | None = None) -> JsonObject:
    registry = load_registry(root)
    run = _normalize_agi_record(run)
    agi_id = str(run.get("agi_id") or "")
    if not agi_id:
        return run
    previous = registry.get("agis", {}).get(agi_id)
    if isinstance(previous, dict):
        run["created_at"] = previous.get("created_at") or run.get("created_at") or _now()
        run["updated_at"] = _now()
        run = _normalize_agi_record(run)
    registry.setdefault("agis", {})[agi_id] = run
    user_id = _find_user_id_for_agi(registry, agi_id)
    if user_id:
        user = registry.get("users", {}).get(user_id)
        if isinstance(user, dict):
            _attach_agi_to_user(user, agi_id, make_active=False)
    save_registry(registry, root)
    return run


def reconcile_current_agi_registry(root: str | Path | None = None) -> JsonObject:
    registry = load_registry(root)
    context = load_context(root)
    agis = registry.setdefault("agis", {})
    groups: dict[str, list[JsonObject]] = {}
    for run in agis.values():
        if not isinstance(run, dict) or not run.get("agi_intake_source_path"):
            continue
        groups.setdefault(_resolved_intake_source_path(run["agi_intake_source_path"]), []).append(run)

    replacements: dict[str, str] = {}
    removed: list[JsonObject] = []
    for records in groups.values():
        if len(records) < 2:
            continue
        keeper = _preferred_agi_record(records)
        if not isinstance(keeper, dict):
            continue
        keeper_id = str(keeper.get("agi_id") or "")
        if not keeper_id:
            continue
        for run in records:
            agi_id = str(run.get("agi_id") or "")
            if not agi_id or agi_id == keeper_id:
                continue
            replacements[agi_id] = keeper_id
            agis.pop(agi_id, None)
            context.get("agis", {}).pop(agi_id, None)
            removed.append(
                {
                    "agi_id": agi_id,
                    "kept_agi_id": keeper_id,
                    "agi_intake_source_path": keeper.get("agi_intake_source_path"),
                }
            )

    if replacements:
        _replace_user_agi_ids(registry, replacements)
        active_id = str(context.get("active_agi_id") or "")
        if active_id in replacements:
            context["active_agi_id"] = replacements[active_id]
        grants = context.get(AGI_ACCESS_KEY)
        if isinstance(grants, dict):
            for old_id, new_id in replacements.items():
                grant = grants.pop(old_id, None)
                if isinstance(grant, dict) and new_id not in grants:
                    grants[new_id] = grant
        new_active_id = str(context.get("active_agi_id") or "")
        if new_active_id in agis:
            context.setdefault("agis", {})[new_active_id] = agis[new_active_id]
        save_registry(registry, root)
        save_context(context, root)

    return {
        "status": "completed",
        "duplicate_source_count": sum(1 for records in groups.values() if len(records) > 1),
        "removed_count": len(removed),
        "removed": removed,
    }


def _find_agi_by_intake_source(
    registry: JsonObject,
    context: JsonObject,
    agi_intake_source: str | Path,
) -> JsonObject | None:
    target = _resolved_intake_source_path(agi_intake_source)
    matches: list[JsonObject] = []
    for container in (context.get("agis"), registry.get("agis")):
        if not isinstance(container, dict):
            continue
        for run in container.values():
            if not isinstance(run, dict) or not run.get("agi_intake_source_path"):
                continue
            if _resolved_intake_source_path(run["agi_intake_source_path"]) == target:
                matches.append(run)
    return _preferred_agi_record(matches)


def _find_agi(registry: JsonObject, agi_id_or_nickname: str) -> JsonObject | None:
    value = str(agi_id_or_nickname or "").strip()
    if not value:
        return None
    agi = registry.get("agis", {}).get(value)
    if isinstance(agi, dict):
        return agi
    return None


def _preferred_agi_record(records: list[JsonObject]) -> JsonObject | None:
    if not records:
        return None

    def rank(run: JsonObject) -> tuple[int, int, str]:
        source_format = str(run.get("agi_source_format") or "")
        return (
            1 if _is_digitized_agi_record(run) else 0,
            1 if source_format and source_format != "source" else 0,
            str(run.get("updated_at") or ""),
        )

    return max(records, key=rank)


def _replace_user_agi_ids(registry: JsonObject, replacements: dict[str, str]) -> None:
    known_agis = registry.get("agis", {})
    for user in registry.get("users", {}).values():
        if not isinstance(user, dict):
            continue
        ids: list[str] = []
        for agi_id in [str(item) for item in user.get("agi_ids", []) if str(item)]:
            current_id = replacements.get(agi_id, agi_id)
            if current_id in known_agis and current_id not in ids:
                ids.append(current_id)
        active_id = str(user.get("active_agi_id") or "")
        if active_id:
            active_id = replacements.get(active_id, active_id)
            if active_id in known_agis and active_id not in ids:
                ids.append(active_id)
            user["active_agi_id"] = active_id if active_id in known_agis else (ids[0] if ids else None)
        user["agi_ids"] = ids
        user["updated_at"] = _now()
