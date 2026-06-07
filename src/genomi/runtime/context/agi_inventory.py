from __future__ import annotations

from pathlib import Path

from .agi_records import describe_agi_record, describe_user
from .agi_summary import describe_context
from .normalize import JsonObject
from .storage import load_registry


def list_active_genome_index_inventory(root: str | Path | None = None) -> JsonObject:
    registry = load_registry(root)
    context = describe_context(root)
    users = _inventory_users(registry)
    user_links = _agi_user_links(users)
    agis = [
        _inventory_agi_record(run, linked_users=user_links.get(str(run.get("agi_id") or ""), []))
        for run in sorted(
            [run for run in registry.get("agis", {}).values() if isinstance(run, dict)],
            key=lambda item: str(item.get("updated_at", "")),
            reverse=True,
        )
    ]
    return {
        "status": "completed",
        "active": {
            "agi_id": context.get("active_agi_id"),
            "user_id": context.get("active_user_id"),
            "selection_source": context.get("selection_source"),
        },
        "users": users,
        "active_genome_indexes": agis,
    }


def _inventory_users(registry: JsonObject) -> list[JsonObject]:
    records = [
        user for user in registry.get("users", {}).values()
        if isinstance(user, dict)
    ]
    users: list[JsonObject] = []
    for user in sorted(records, key=lambda item: str(item.get("updated_at", "")), reverse=True):
        described = describe_user(user, registry=registry, include_genomes=False) or {}
        users.append(
            {
                "user_id": described.get("user_id"),
                "nickname": described.get("nickname"),
                "default": described.get("default"),
                "active_agi_id": described.get("active_agi_id"),
                "agi_ids": described.get("agi_ids") or [],
            }
        )
    return users


def _agi_user_links(users: list[JsonObject]) -> dict[str, list[JsonObject]]:
    links: dict[str, list[JsonObject]] = {}
    for user in users:
        user_ref = {
            "user_id": user.get("user_id"),
            "nickname": user.get("nickname"),
            "default": user.get("default"),
            "active": False,
        }
        for agi_id in user.get("agi_ids") or []:
            ref = dict(user_ref)
            ref["active"] = str(user.get("active_agi_id") or "") == str(agi_id)
            links.setdefault(str(agi_id), []).append(ref)
    return links


def _inventory_agi_record(run: JsonObject, *, linked_users: list[JsonObject]) -> JsonObject:
    described = describe_agi_record(run) or {}
    agi_id = str(run.get("agi_id") or described.get("agi_id") or "")
    sample_slug = str(run.get("sample_slug") or described.get("sample_slug") or "")
    user_names = [str(user.get("nickname")) for user in linked_users if user.get("nickname")]
    display_name = str(run.get("nickname") or (user_names[0] if user_names else "") or sample_slug or agi_id)
    return {
        "agi_id": agi_id,
        "sample_slug": sample_slug,
        "names": {
            "display": display_name,
            "sample_slug": sample_slug,
            "user_nicknames": user_names,
        },
        "hashes": _hashes(run),
        "source": {
            "format": run.get("agi_source_format") or described.get("agi_source_format"),
            "kind": run.get("agi_source_kind") or described.get("agi_source_kind"),
            "provider": run.get("agi_source_provider") or described.get("agi_source_provider"),
            "member": run.get("agi_source_member") or described.get("agi_source_member"),
        },
        "source_references": _source_references(run),
        "users": linked_users,
        "status": run.get("status") or described.get("status"),
        "genome_build": run.get("genome_build") or described.get("genome_build"),
        "digitized": described.get("digitized"),
        "availability": described.get("availability") or {},
        "active_genome_index_readiness": described.get("active_genome_index_readiness"),
    }


def _source_references(run: JsonObject) -> list[JsonObject]:
    references: list[JsonObject] = []
    seen: set[tuple[str, str]] = set()
    for key in ("agi_intake_source_path", "source_url", "source"):
        value = run.get(key)
        if value not in (None, ""):
            text = str(value)
            kind = "url" if text.startswith(("http://", "https://")) else "local_path"
            marker = (kind, text)
            if marker not in seen:
                seen.add(marker)
                references.append({"kind": kind, "value": text})
    return references


def _hashes(run: JsonObject) -> JsonObject:
    payload: JsonObject = {}
    source_content_sha256 = run.get("source_content_sha256")
    if source_content_sha256:
        payload["source_content_sha256"] = str(source_content_sha256)
    return payload
