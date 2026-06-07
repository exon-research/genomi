from __future__ import annotations

from pathlib import Path

from ..host_response import resolve_active_response_profile
from ..paths import shared_evidence_db_path
from .agi_access import agi_access_status
from .agi_records import describe_agi_record, describe_user
from .agi_selection import _active_user, _selection_source, active_agi_record
from .normalize import (
    DIGITIZATION_CONTRACT,
    JsonObject,
    _default_user,
    _empty_agi_access_status,
    _path_str,
)
from .storage import (
    context_path,
    context_policy,
    context_scope,
    get_response_profile_id,
    load_context,
    load_registry,
    registry_path,
)


def describe_context(root: str | Path | None = None) -> JsonObject:
    context = load_context(root)
    registry = load_registry(root)
    active = active_agi_record(context, root=root)
    session_agis = [agi for agi in context.get("agis", {}).values() if isinstance(agi, dict)]
    known_agis = [agi for agi in registry.get("agis", {}).values() if isinstance(agi, dict)]
    known_users = [user for user in registry.get("users", {}).values() if isinstance(user, dict)]
    default_user = _default_user(registry)
    policy = context_policy()
    selection_source = _selection_source(context, registry, active)
    active_agi_id = context.get("active_agi_id") or (active.get("agi_id") if active else None)
    active_user = _active_user(context, registry)
    active_genome_index = describe_agi_record(active) if active else None
    active_access = agi_access_status(active_agi_id, context=context, registry=registry, root=root) if active_agi_id else _empty_agi_access_status(None)
    return {
        "context_file": _path_str(context_path(root)),
        "context_scope": context_scope(root),
        "context_policy": policy,
        "active_genome_index_access": active_access,
        "has_active_genome_index": active is not None,
        "active_agi_id": active_agi_id,
        "active_user_id": active_user.get("user_id") if isinstance(active_user, dict) else None,
        "active_user": describe_user(active_user, include_genomes=False) if isinstance(active_user, dict) else None,
        "active_genome_index": active_genome_index,
        "selection_source": selection_source,
        "default_auto_selected": selection_source == "default_user_auto_select",
        "shared_evidence_db": context.get("shared_evidence_db") or _path_str(shared_evidence_db_path(root)),
        "active_genome_index_registry": {
            "registry_file": _path_str(registry_path(root)),
            "known_agi_count": len(known_agis),
            "known_user_count": len(known_users),
            "default_user": describe_user(default_user, include_genomes=False) if isinstance(default_user, dict) else None,
            "resume_requires": "Explicitly approve a resolved genomi agi, supply a source path, or select a default user before sample-specific evidence is read.",
        },
        "users": [describe_user(user, include_genomes=False) for user in sorted(known_users, key=lambda item: str(item.get("updated_at", "")), reverse=True)],
        "session_agis": [describe_agi_record(agi) for agi in sorted(session_agis, key=lambda item: str(item.get("updated_at", "")), reverse=True)],
        "selection_contract": {
            "active_genome_index_optional": True,
            "supported_private_sources": [
                "vcf",
                "gvcf",
                "bam",
                "fastq",
                "23andme",
                "ancestrydna",
                "myheritage",
                "ftdna",
                "livingdna",
            ],
            "active_genome_index_is_primary": True,
            "rule": "The current chat can select a user or genomi agi. A supplied source path grants scoped access to that source's Active Genome Index for this session; a default user grants persistent access only to that user's selected Active Genome Index.",
        },
        "context_axes": {
            "active_genome_index": {
                "selected_by": ["genomi.parse_source", "active_genome_index.assign_user_genome", "active_genome_index.select_user", "default user auto-select"],
                "current_state": "active_accessible" if active and bool(active_access.get("approved")) else ("metadata_only" if active else "public_only"),
                "known_agis": len(known_agis),
            },
            "evidence_context": {
                "shared_evidence_db": context.get("shared_evidence_db") or _path_str(shared_evidence_db_path(root)),
                "shared_scope": "reusable public-target and reviewed-source findings",
                "private_scope": "sample-derived evidence and user-specific reviewed findings",
            },
            "source_context": {
                "selected_by": ["research.list_sources", "operation metadata", "focused skill instructions"],
                "external_target_rule": "Use selected public targets only for external research.",
            },
        },
        "digitization_contract": DIGITIZATION_CONTRACT,
        "active_response_profile": resolve_active_response_profile(get_response_profile_id(registry)),
    }
