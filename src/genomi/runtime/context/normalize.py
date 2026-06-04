from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..paths import shared_evidence_db_path

JsonObject = dict[str, Any]
CONTEXT_VERSION = 1
CONTEXT_FILE_NAME = "context.json"
REGISTRY_FILE_NAME = "registry.json"
SESSIONS_DIR_NAME = "sessions"
AGI_ACCESS_KEY = "agi_access"
GENOMI_CONTEXT_ENV = "GENOMI_CONTEXT"
GENOMI_SESSION_ENV = "GENOMI_SESSION_ID"
GENOMI_CONTEXT_POLICY_ENV = "GENOMI_CONTEXT_POLICY"
AGENT_SESSION_ENVS = (
    "CODEX_THREAD_ID",
    "OPENHARNESS_DATA_DIR",
    "OPENHARNESS_CONFIG_DIR",
    "CLAUDE_CODE_SESSION_ID",
    "CLAUDE_SESSION_ID",
)
DEFAULT_CONTEXT_POLICY = "explicit"
DIGITIZATION_CONTRACT: JsonObject = {
    "intake_source_role": "ingestion_source_for_digitization",
    "normal_query_substrate": [
        "active_genome_index",
        "evidence_db",
        "matches",
        "candidate_inventory",
        "reviewed_research",
        "report_context",
    ],
    "rule": (
        "After genomi.parse_source, agents answer future inquiries from the Active Genome Index. "
        "The original intake file is reserved for first parse, forced reparse, Active Genome Index rebuild, "
        "or checks that explicitly require re-materializing from the original file."
    ),
}


def _context_source_format(source_path: Path, source_format: object | None) -> str:
    requested = str(source_format or "").strip().lower()
    if requested:
        return requested
    name = source_path.name.lower()
    if name.endswith((".g.vcf.gz", ".gvcf.gz")):
        return "gvcf"
    if name.endswith((".vcf", ".vcf.gz")):
        return "vcf"
    if name.endswith(".bam"):
        return "bam"
    if name.endswith((".fastq", ".fq", ".fastq.gz", ".fq.gz", ".fastq.bgz")):
        return "fastq"
    if "ancestry" in name:
        return "ancestrydna"
    if "23andme" in name or "23and-me" in name:
        return "23andme"
    if "myheritage" in name:
        return "myheritage"
    if "living-dna" in name or "livingdna" in name:
        return "livingdna"
    if "ftdna" in name or "familytreedna" in name or "_autosomal_o37_" in name or "autosomal_o37" in name:
        return "ftdna"
    return "source"


def _normalize_context(value: JsonObject, root: str | Path | None) -> JsonObject:
    value.setdefault("version", CONTEXT_VERSION)
    active_agi_id = value.get("active_agi_id")
    value["active_agi_id"] = str(active_agi_id) if active_agi_id not in (None, "") else None
    active_user_id = value.get("active_user_id")
    value["active_user_id"] = str(active_user_id) if active_user_id not in (None, "") else None
    value["agis"] = _agi_map(value.get("agis"))
    for key in _removed_context_keys():
        value.pop(key, None)
    access = value.get(AGI_ACCESS_KEY)
    value[AGI_ACCESS_KEY] = access if isinstance(access, dict) else {}
    value.setdefault("shared_evidence_db", _path_str(shared_evidence_db_path(root)))
    return value


def _normalize_registry(value: JsonObject) -> JsonObject:
    value.setdefault("version", CONTEXT_VERSION)
    agis = _agi_map(value.get("agis"))
    users = _user_map(value.get("users"))
    default_user_id = str(value.get("default_user_id") or "") or None
    if default_user_id and default_user_id in users:
        _mark_default_user({"users": users}, default_user_id)
    else:
        for user in users.values():
            if isinstance(user, dict):
                user["default"] = False
        default_user_id = None
    value["agis"] = agis
    value["users"] = users
    value["default_user_id"] = default_user_id
    response_profile = value.get("response_profile")
    if response_profile in (None, ""):
        value["response_profile"] = None
    else:
        value["response_profile"] = str(response_profile)
    for key in _removed_context_keys():
        value.pop(key, None)
    value.pop("default" + "_run_id", None)
    return value


def _agi_map(container: object) -> JsonObject:
    agis: JsonObject = {}
    if not isinstance(container, dict):
        return agis
    for key, item in container.items():
        if not isinstance(item, dict):
            continue
        record = _normalize_agi_record(item, agi_id_hint=str(key))
        agi_id = str(record.get("agi_id") or "")
        if agi_id:
            agis[agi_id] = record
    return agis


def _normalize_agi_record(record: JsonObject, agi_id_hint: str | None = None) -> JsonObject:
    normalized = dict(record)
    agi_id = normalized.get("agi_id") or agi_id_hint or normalized.get("sample_slug")
    normalized["agi_id"] = str(agi_id) if agi_id not in (None, "") else ""
    normalized.pop("run" + "_id", None)
    normalized.pop("nickname", None)
    normalized.pop("default", None)
    normalized.pop("default_set_at", None)
    normalized.pop("source" + "_label", None)
    normalized.pop("vcf", None)
    normalized.pop("vcf_path", None)
    return normalized


def _normalize_nickname(value: object | None) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _removed_context_keys() -> tuple[str, ...]:
    return ("runs", "active" + "_run_id", "personal" + "_dna_access")


def _user_map(container: object) -> JsonObject:
    users: JsonObject = {}
    if not isinstance(container, dict):
        return users
    for key, item in container.items():
        if not isinstance(item, dict):
            continue
        record = _normalize_user_record(item, user_id_hint=str(key))
        user_id = str(record.get("user_id") or "")
        if user_id:
            users[user_id] = record
    return users


def _normalize_user_record(record: JsonObject, user_id_hint: str | None = None) -> JsonObject:
    now = _now()
    nickname = _normalize_nickname(record.get("nickname")) or _normalize_nickname(user_id_hint) or "User"
    user_id = record.get("user_id") or user_id_hint or _user_id_for_nickname(nickname)
    agi_ids = [
        str(item)
        for item in (record.get("agi_ids") if isinstance(record.get("agi_ids"), list) else [])
        if str(item)
    ]
    active_agi_id = record.get("active_agi_id")
    if active_agi_id not in (None, ""):
        active_text = str(active_agi_id)
        if active_text not in agi_ids:
            agi_ids.append(active_text)
    else:
        active_text = agi_ids[0] if agi_ids else None
    return {
        "user_id": str(user_id),
        "nickname": nickname,
        "default": bool(record.get("default", False)),
        "active_agi_id": active_text,
        "agi_ids": list(dict.fromkeys(agi_ids)),
        "created_at": record.get("created_at") or now,
        "updated_at": record.get("updated_at") or now,
        **({"default_set_at": record.get("default_set_at")} if record.get("default_set_at") else {}),
    }


def _user_id_for_nickname(nickname: str) -> str:
    return "user-" + _digest(nickname.casefold())


def _ensure_user_record(registry_or_users: JsonObject, *, nickname: str) -> JsonObject:
    users = registry_or_users.setdefault("users", {}) if "agis" in registry_or_users or "default_user_id" in registry_or_users else registry_or_users
    normalized_nickname = _normalize_nickname(nickname)
    if not normalized_nickname:
        raise ValueError("nickname is required")
    found = _find_user({"users": users}, normalized_nickname)
    if isinstance(found, dict):
        return found
    _assert_unique_user_nickname({"users": users}, normalized_nickname)
    now = _now()
    user = {
        "user_id": _user_id_for_nickname(normalized_nickname),
        "nickname": normalized_nickname,
        "default": False,
        "active_agi_id": None,
        "agi_ids": [],
        "created_at": now,
        "updated_at": now,
    }
    users[user["user_id"]] = user
    return user


def _find_user(registry: JsonObject, user_id_or_nickname: object | None) -> JsonObject | None:
    value = str(user_id_or_nickname or "").strip()
    if not value:
        return None
    user = registry.get("users", {}).get(value)
    if isinstance(user, dict):
        return user
    folded = value.casefold()
    matches = [
        item
        for item in registry.get("users", {}).values()
        if isinstance(item, dict) and str(item.get("nickname") or "").casefold() == folded
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def _find_user_id_for_agi(registry: JsonObject, agi_id: str) -> str | None:
    for user_id, user in registry.get("users", {}).items():
        if isinstance(user, dict) and agi_id in [str(item) for item in user.get("agi_ids", [])]:
            return str(user_id)
    return None


def _attach_agi_to_user(user: JsonObject, agi_id: str, *, make_active: bool) -> None:
    ids = [str(item) for item in user.get("agi_ids", []) if str(item)]
    if agi_id not in ids:
        ids.append(agi_id)
    user["agi_ids"] = ids
    if make_active or not user.get("active_agi_id"):
        user["active_agi_id"] = agi_id
    user["updated_at"] = _now()


def _mark_default_user(registry: JsonObject, user_id: str) -> None:
    now = _now()
    registry["default_user_id"] = user_id
    for key, user in registry.setdefault("users", {}).items():
        if not isinstance(user, dict):
            continue
        user["default"] = str(key) == user_id
        if str(key) == user_id:
            user["default_set_at"] = now
            user["updated_at"] = now


def _assert_unique_user_nickname(registry: JsonObject, nickname: str, *, existing_user_id: str | None = None) -> None:
    folded = nickname.casefold()
    for user_id, user in registry.get("users", {}).items():
        if existing_user_id and str(user_id) == existing_user_id:
            continue
        if isinstance(user, dict) and str(user.get("nickname") or "").casefold() == folded:
            raise ValueError(f"Nickname already belongs to another user: {nickname}")


def _default_user(registry: JsonObject) -> JsonObject | None:
    default_user_id = str(registry.get("default_user_id") or "")
    user = registry.get("users", {}).get(default_user_id)
    if isinstance(user, dict):
        return user
    defaults = [user for user in registry.get("users", {}).values() if isinstance(user, dict) and user.get("default")]
    return defaults[0] if len(defaults) == 1 else None


def _grant_agi_access(context: JsonObject, agi_id: str, *, reason: str) -> None:
    context.setdefault(AGI_ACCESS_KEY, {})[agi_id] = {
        "approved": True,
        "approved_at": _now(),
        "scope": "session",
        "reason": reason,
    }


def _empty_agi_access_status(agi_id: object | None) -> JsonObject:
    return {
        "agi_id": str(agi_id) if agi_id not in (None, "") else None,
        "approved": False,
        "approved_at": None,
        "scope": "session",
        "reason": None,
    }


def _empty_context(root: str | Path | None) -> JsonObject:
    now = _now()
    return {
        "version": CONTEXT_VERSION,
        "active_agi_id": None,
        "active_user_id": None,
        AGI_ACCESS_KEY: {},
        "shared_evidence_db": _path_str(shared_evidence_db_path(root)),
        "agis": {},
        "created_at": now,
        "updated_at": now,
    }


def _empty_registry() -> JsonObject:
    now = _now()
    return {
        "version": CONTEXT_VERSION,
        "agis": {},
        "users": {},
        "default_user_id": None,
        "response_profile": None,
        "created_at": now,
        "updated_at": now,
    }


def _workspace_session_id() -> str:
    return "workspace-" + _digest(Path.cwd().expanduser().resolve(strict=False))


def _agent_session_id() -> str | None:
    for env_name in AGENT_SESSION_ENVS:
        raw_value = os.environ.get(env_name)
        if raw_value:
            return f"{env_name}:{raw_value}"
    return None


def _redact_session_value(value: str) -> str:
    if len(value) <= 12:
        return value
    return f"{value[:6]}...{value[-4:]}"


def _stable_session_id(value: str) -> str:
    cleaned = "".join(character.lower() if character.isalnum() else "-" for character in value.strip())
    cleaned = "-".join(piece for piece in cleaned.split("-") if piece)
    if not cleaned:
        cleaned = "session"
    return f"{cleaned[:64]}-{_digest(value)[:8]}"


def _digest(value: object) -> str:
    return hashlib.sha256(str(value).encode("utf-8", errors="replace")).hexdigest()[:16]


def _outputs_from_result(result: JsonObject | None) -> JsonObject:
    if not isinstance(result, dict):
        return {}
    outputs = result.get("outputs") or result.get("default_outputs") or {}
    return outputs if isinstance(outputs, dict) else {}


def _path_str(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(Path(value).expanduser().resolve(strict=False))


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
