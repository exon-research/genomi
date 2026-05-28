from __future__ import annotations

from pathlib import Path

from ...active_genome_index.active_genome_index import (
    active_genome_index_readiness,
    default_active_genome_index_path,
)
from ..host_response import resolve_active_response_profile
from ..paths import (
    run_evidence_db_path_for_source,
    run_evidence_dir_for_source,
    run_output_path,
    run_output_path_for_source,
    run_project_dir_for_source,
    run_reference_dir_for_source,
    run_work_dir_for_source,
    sample_slug_from_source,
    shared_evidence_db_path,
)
from .normalize import (
    AGI_ACCESS_KEY,
    DIGITIZATION_CONTRACT,
    JsonObject,
    _attach_agi_to_user,
    _context_source_format,
    _default_user,
    _empty_agi_access_status,
    _ensure_user_record,
    _find_user,
    _find_user_id_for_agi,
    _grant_agi_access,
    _mark_default_user,
    _normalize_agi_record,
    _normalize_user_record,
    _now,
    _outputs_from_result,
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
    save_context,
    save_registry,
)


def describe_context(root: str | Path | None = None) -> JsonObject:
    context = load_context(root)
    registry = load_registry(root)
    active = active_run(context, root=root)
    session_agis = [agi for agi in context.get("agis", {}).values() if isinstance(agi, dict)]
    known_agis = [agi for agi in registry.get("agis", {}).values() if isinstance(agi, dict)]
    known_users = [user for user in registry.get("users", {}).values() if isinstance(user, dict)]
    default_user = _default_user(registry)
    policy = context_policy()
    selection_source = _selection_source(context, registry, active)
    active_agi_id = context.get("active_agi_id") or (active.get("agi_id") if active else None)
    active_user = _active_user(context, registry)
    active_genome_index = describe_run(active) if active else None
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
        "session_agis": [describe_run(agi) for agi in sorted(session_agis, key=lambda item: str(item.get("updated_at", "")), reverse=True)],
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
                "selected_by": ["genomi.parse_source", "genomi.assign_user_genome", "genomi.select_user", "default user auto-select"],
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


def active_run(context: JsonObject | None = None, root: str | Path | None = None) -> JsonObject | None:
    state = context if context is not None else load_context(root)
    registry = load_registry(root)
    active_id = state.get("active_agi_id")
    if active_id:
        agi = state.get("agis", {}).get(str(active_id))
        if isinstance(agi, dict):
            return agi
        registry_agi = registry.get("agis", {}).get(str(active_id))
        if isinstance(registry_agi, dict):
            return registry_agi
    return _default_selected_agi(registry=registry)


def active_accessible_run(context: JsonObject | None = None, root: str | Path | None = None) -> JsonObject | None:
    state = context if context is not None else load_context(root)
    active = active_run(state, root=root)
    if active is not None and agi_access_approved(active, context=state, root=root):
        return active
    return None


def set_active_genome_index(
    vcf: str | Path,
    *,
    operation_result: JsonObject | None = None,
    status: str = "available",
    user_nickname: str | None = None,
    set_default_user: bool = False,
    db: str | Path | None = None,
    active_genome_index_path: str | Path | None = None,
    matches: str | Path | None = None,
    shared_db: str | Path | None = None,
    reference_fasta: str | Path | None = None,
    genotype_reference_fasta: str | Path | None = None,
    genome_build: str | None = None,
    grant_access: bool = False,
    root: str | Path | None = None,
) -> JsonObject:
    return set_active_source(
        vcf,
        source_format="vcf",
        operation_result=operation_result,
        status=status,
        user_nickname=user_nickname,
        set_default_user=set_default_user,
        db=db,
        active_genome_index_path=active_genome_index_path,
        matches=matches,
        shared_db=shared_db,
        reference_fasta=reference_fasta,
        genotype_reference_fasta=genotype_reference_fasta,
        genome_build=genome_build,
        grant_access=grant_access,
        root=root,
    )


def set_active_source(
    source: str | Path,
    *,
    source_format: str | None = None,
    operation_result: JsonObject | None = None,
    status: str = "available",
    user_nickname: str | None = None,
    set_default_user: bool = False,
    db: str | Path | None = None,
    active_genome_index_path: str | Path | None = None,
    matches: str | Path | None = None,
    shared_db: str | Path | None = None,
    reference_fasta: str | Path | None = None,
    genotype_reference_fasta: str | Path | None = None,
    genome_build: str | None = None,
    grant_access: bool = False,
    root: str | Path | None = None,
) -> JsonObject:
    context = load_context(root)
    run = infer_source_run(
        source,
        source_format=source_format,
        operation_result=operation_result,
        status=status,
        db=db,
        active_genome_index_path=active_genome_index_path,
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
        merged = {**previous, **{key: value for key, value in run.items() if value is not None}}
        merged["created_at"] = previous.get("created_at") or run["created_at"]
        merged["updated_at"] = _now()
        run = merged
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
        run = active_run(state, root=root)
        agi_id = str(run.get("agi_id") or "") if isinstance(run, dict) else str(state.get("active_agi_id") or "")
    elif isinstance(agi, dict):
        agi_id = str(agi.get("agi_id") or "")
    else:
        agi_id = str(agi or "")
    return bool(agi_access_status(agi_id, context=state, root=root).get("approved"))


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


def save_agi_to_registry(run: JsonObject, root: str | Path | None = None) -> JsonObject:
    registry = load_registry(root)
    run = _normalize_agi_record(run)
    agi_id = str(run.get("agi_id") or "")
    if not agi_id:
        return run
    previous = registry.get("agis", {}).get(agi_id)
    if isinstance(previous, dict):
        run = {**previous, **{key: value for key, value in run.items() if value is not None}}
        run["created_at"] = previous.get("created_at") or run.get("created_at") or _now()
        run["updated_at"] = _now()
    registry.setdefault("agis", {})[agi_id] = run
    user_id = _find_user_id_for_agi(registry, agi_id)
    if user_id:
        user = registry.get("users", {}).get(user_id)
        if isinstance(user, dict):
            _attach_agi_to_user(user, agi_id, make_active=False)
    save_registry(registry, root)
    return run


def save_run_to_registry(run: JsonObject, root: str | Path | None = None) -> JsonObject:
    return save_agi_to_registry(run, root=root)


def set_active_paths(
    *,
    source: str | Path | None = None,
    vcf: str | Path | None = None,
    source_format: str | None = None,
    user_nickname: str | None = None,
    set_default_user: bool = False,
    db: str | Path | None = None,
    active_genome_index_path: str | Path | None = None,
    matches: str | Path | None = None,
    shared_db: str | Path | None = None,
    reference_fasta: str | Path | None = None,
    genotype_reference_fasta: str | Path | None = None,
    genome_build: str | None = None,
    root: str | Path | None = None,
) -> JsonObject:
    selected_source = source or vcf
    if selected_source is None:
        raise ValueError("source is required")
    return set_active_source(
        selected_source,
        source_format=source_format or ("vcf" if vcf and not source else None),
        status="set",
        user_nickname=user_nickname,
        set_default_user=set_default_user,
        db=db,
        active_genome_index_path=active_genome_index_path,
        matches=matches,
        shared_db=shared_db,
        reference_fasta=reference_fasta,
        genotype_reference_fasta=genotype_reference_fasta,
        genome_build=genome_build,
        root=root,
    )


def clear_active_genome_index(*, forget_active_genome_indexes: bool = False, root: str | Path | None = None) -> JsonObject:
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


def infer_run(
    vcf: str | Path,
    *,
    operation_result: JsonObject | None = None,
    status: str = "available",
    db: str | Path | None = None,
    active_genome_index_path: str | Path | None = None,
    matches: str | Path | None = None,
    shared_db: str | Path | None = None,
    reference_fasta: str | Path | None = None,
    genotype_reference_fasta: str | Path | None = None,
    genome_build: str | None = None,
    root: str | Path | None = None,
) -> JsonObject:
    return infer_source_run(
        vcf,
        source_format="vcf",
        operation_result=operation_result,
        status=status,
        db=db,
        active_genome_index_path=active_genome_index_path,
        matches=matches,
        shared_db=shared_db,
        reference_fasta=reference_fasta,
        genotype_reference_fasta=genotype_reference_fasta,
        genome_build=genome_build,
        root=root,
    )


def infer_source_run(
    source: str | Path,
    *,
    source_format: str | None = None,
    operation_result: JsonObject | None = None,
    status: str = "available",
    db: str | Path | None = None,
    active_genome_index_path: str | Path | None = None,
    matches: str | Path | None = None,
    shared_db: str | Path | None = None,
    reference_fasta: str | Path | None = None,
    genotype_reference_fasta: str | Path | None = None,
    genome_build: str | None = None,
    root: str | Path | None = None,
) -> JsonObject:
    source_path = Path(source)
    outputs = _outputs_from_result(operation_result)
    result = operation_result or {}
    effective_format = _context_source_format(source_path, result.get("source_format") or source_format)
    sample_slug = str(result.get("sample_slug") or sample_slug_from_source(source_path, source_format=effective_format))
    is_vcf = effective_format in {"vcf", "gvcf"} or bool(result.get("vcf"))
    run: JsonObject = {
        "agi_id": sample_slug,
        "sample_slug": sample_slug,
        "status": status,
        "source": _path_str(result.get("source") or source_path),
        "source_format": effective_format,
        "source_kind": result.get("source_kind"),
        "source_member": result.get("source_member"),
        "vcf": _path_str(result.get("vcf") or source_path) if is_vcf else None,
        "project_dir": _path_str(result.get("project_dir") or run_project_dir_for_source(source_path, source_format=effective_format, root=root)),
        "work_dir": _path_str(result.get("work_dir") or run_work_dir_for_source(source_path, source_format=effective_format, root=root)),
        "evidence_dir": _path_str(result.get("evidence_dir") or run_evidence_dir_for_source(source_path, source_format=effective_format, root=root)),
        "reference_dir": _path_str(result.get("reference_dir") or run_reference_dir_for_source(source_path, source_format=effective_format, root=root)),
        "evidence_db": _path_str(db or result.get("evidence_db") or run_evidence_db_path_for_source(source_path, source_format=effective_format, root=root)),
        "shared_evidence_db": _path_str(shared_db or result.get("shared_evidence_db") or shared_evidence_db_path(root)),
        "active_genome_index_path": _path_str(active_genome_index_path or outputs.get("active_genome_index_path") or (default_active_genome_index_path(source_path, root=root) if is_vcf else run_output_path_for_source(source_path, "active-genome-index.sqlite", source_format=effective_format, root=root))),
        "matches": _path_str(matches or outputs.get("clinvar_matches") or (run_output_path(source_path, "clinvar.matches.jsonl", root=root) if is_vcf else None)),
        "candidate_inventory": _path_str(outputs.get("clinvar_scan") or (run_output_path(source_path, "clinvar.candidates.json", root=root) if is_vcf else None)),
        "comparable_vcf": _path_str(result.get("comparable_vcf") or outputs.get("exported_primary_variants") or outputs.get("exported_variants")),
        "reference_fasta": _path_str(reference_fasta or result.get("reference_fasta")),
        "genotype_reference_fasta": _path_str(genotype_reference_fasta or result.get("genotype_reference_fasta")),
        "genome_build": genome_build or result.get("genome_build") or "auto",
        "outputs": {key: _path_str(value) for key, value in outputs.items()},
        "created_at": _now(),
        "updated_at": _now(),
    }
    return run


def describe_run(run: JsonObject | None) -> JsonObject | None:
    if run is None:
        return None
    run = _normalize_agi_record(run)
    active_genome_index_state = _active_genome_index_state(run)
    digitized = _is_digitized_run(run)
    path_keys = [
        "source",
        "vcf",
        "evidence_db",
        "shared_evidence_db",
        "active_genome_index_path",
        "matches",
        "candidate_inventory",
        "comparable_vcf",
        "reference_fasta",
        "genotype_reference_fasta",
    ]
    availability = {
        key: Path(value).exists()
        for key in path_keys
        if (value := run.get(key))
    }
    payload = {**run, "availability": availability, "digitized": digitized}
    if active_genome_index_state is not None:
        payload["active_genome_index_readiness"] = active_genome_index_state
    if digitized:
        source_path = payload.pop("source", None)
        intake_path = payload.pop("vcf", None)
        comparable_variant_export = payload.pop("comparable_vcf", None)
        payload["availability"] = {
            key: value
            for key, value in availability.items()
            if key not in {"source", "vcf", "comparable_vcf"}
        }
        if comparable_variant_export:
            payload["comparable_variant_export"] = comparable_variant_export
            payload["availability"]["comparable_variant_export"] = Path(comparable_variant_export).exists()
        payload["intake_source"] = {
            "role": "ingestion_source_for_digitization",
            "hidden_after_digitization": True,
            "available_for_rebuild": bool((source_path and Path(str(source_path)).exists()) or (intake_path and Path(str(intake_path)).exists())),
        }
    return payload


def list_agis(root: str | Path | None = None) -> list[JsonObject]:
    registry = load_registry(root)
    records = [agi for agi in registry.get("agis", {}).values() if isinstance(agi, dict)]
    return [
        describe_run(agi) or {}
        for agi in sorted(records, key=lambda item: str(item.get("updated_at", "")), reverse=True)
    ]


def find_agi(agi_id_or_nickname: str, root: str | Path | None = None) -> JsonObject | None:
    return _find_agi(load_registry(root), agi_id_or_nickname)


def describe_user(user: JsonObject | None, *, registry: JsonObject | None = None, include_genomes: bool = True) -> JsonObject | None:
    if not isinstance(user, dict):
        return None
    normalized = _normalize_user_record(user)
    payload: JsonObject = {
        "user_id": normalized.get("user_id"),
        "nickname": normalized.get("nickname"),
        "default": bool(normalized.get("default")),
        "active_agi_id": normalized.get("active_agi_id"),
        "agi_ids": list(normalized.get("agi_ids") or []),
        "created_at": normalized.get("created_at"),
        "updated_at": normalized.get("updated_at"),
    }
    if include_genomes:
        reg = registry if registry is not None else load_registry()
        payload["active_genome_index"] = describe_run(reg.get("agis", {}).get(str(normalized.get("active_agi_id") or "")))
        payload["genomes"] = [
            describe_run(reg.get("agis", {}).get(str(agi_id))) or {"agi_id": str(agi_id)}
            for agi_id in normalized.get("agi_ids", [])
        ]
    return payload


def _is_digitized_run(run: JsonObject) -> bool:
    if str(run.get("status") or "") == "parsed":
        active_genome_index_state = _active_genome_index_state(run)
        return bool(active_genome_index_state.get("complete")) if active_genome_index_state is not None else True
    if str(run.get("source_format") or "") in {"vcf", "gvcf"}:
        active_genome_index_state = _active_genome_index_state(run)
        return bool(active_genome_index_state and active_genome_index_state.get("complete"))
    for key in ("active_genome_index_path", "matches", "candidate_inventory"):
        value = run.get(key)
        if value and Path(str(value)).exists():
            return True
    return False


def _active_genome_index_state(run: JsonObject) -> JsonObject | None:
    active_genome_index_path = run.get("active_genome_index_path")
    if not active_genome_index_path or str(run.get("source_format") or "") not in {"vcf", "gvcf"}:
        return None
    return active_genome_index_readiness(str(active_genome_index_path))


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
        inferred = infer_source_run(source, status="set", root=root)
        stored = registry.get("agis", {}).get(str(inferred.get("agi_id") or ""))
        return stored if isinstance(stored, dict) else inferred
    if agi_id:
        return _find_agi(registry, agi_id)
    if user_id or nickname:
        user = _find_user(registry, user_id or nickname)
        active_id = str(user.get("active_agi_id") or "") if isinstance(user, dict) else ""
        run = registry.get("agis", {}).get(active_id)
        return run if isinstance(run, dict) else None
    active = active_run(context, root=root)
    return active if isinstance(active, dict) else None


def _find_agi(registry: JsonObject, agi_id_or_nickname: str) -> JsonObject | None:
    value = str(agi_id_or_nickname or "").strip()
    if not value:
        return None
    agi = registry.get("agis", {}).get(value)
    if isinstance(agi, dict):
        return agi
    return None


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


def _auto_selected_run(root: str | Path | None) -> JsonObject | None:
    return _default_selected_agi(root)
