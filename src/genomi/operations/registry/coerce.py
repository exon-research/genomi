from __future__ import annotations

from pathlib import Path

from ...evidence import init_evidence_db
from ...runtime import context as runtime_context
from ...runtime.paths import expand_user_path, shared_evidence_db_path
from .errors import JsonObject, OperationError
from .model import _operation_parameter_defaults


def _path(params: JsonObject, key: str) -> Path:
    value = params.get(key)
    if value is None or value == "":
        raise OperationError("invalid_params", f"{key} is required")
    return _expanded_path(value)


def _optional_path(params: JsonObject, key: str) -> Path | None:
    value = params.get(key)
    if value is None or value == "":
        return None
    return _expanded_path(value)


def _expanded_path(value: object) -> Path:
    return expand_user_path(str(value))


def _str(params: JsonObject, key: str, default: str | None = None) -> str:
    value = params.get(key, default)
    if value is None:
        raise OperationError("invalid_params", f"{key} is required")
    return str(value)


def _optional_str(params: JsonObject, key: str) -> str | None:
    value = params.get(key)
    if value is None or value == "":
        return None
    return str(value)


def _int(params: JsonObject, key: str, default: int | None = None) -> int:
    value = params.get(key, default)
    if value is None:
        raise OperationError("invalid_params", f"{key} is required")
    return int(value)


def _optional_int(params: JsonObject, key: str) -> int | None:
    value = params.get(key)
    if value is None or value == "":
        return None
    return int(value)


def _float(params: JsonObject, key: str, default: float | None = None) -> float:
    value = params.get(key, default)
    if value is None:
        raise OperationError("invalid_params", f"{key} is required")
    return float(value)


def _optional_float(params: JsonObject, key: str) -> float | None:
    value = params.get(key)
    if value is None or value == "":
        return None
    return float(value)


def _bool(params: JsonObject, key: str, default: bool = False) -> bool:
    value = params.get(key, default)
    return bool(value)


def _list_str(params: JsonObject, key: str) -> list[str]:
    value = params.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise OperationError("invalid_params", f"{key} must be an array")
    return [str(item) for item in value]


def _list_dict(params: JsonObject, key: str) -> list[JsonObject]:
    value = params.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise OperationError("invalid_params", f"{key} must be an array")
    if not all(isinstance(item, dict) for item in value):
        raise OperationError("invalid_params", f"{key} must contain objects")
    return [dict(item) for item in value]


def _target_kwargs(params: JsonObject) -> JsonObject:
    return {
        "gene": params.get("gene"),
        "drug": params.get("drug"),
        "condition": params.get("condition"),
        "topic": params.get("topic"),
        "chrom": params.get("chrom"),
        "pos": params.get("pos"),
        "ref": params.get("ref"),
        "alt": params.get("alt"),
        "genome_build": params.get("genome_build", "GRCh38"),
    }


def _with_context(
    params: JsonObject,
    *,
    db: bool = False,
    matches: bool = False,
    shared_db: bool = False,
    reference_fasta: bool = False,
    genome_build: bool = False,
    allow_shared_db_without_vcf: bool = True,
) -> JsonObject:
    """Resolve non-index auxiliary context (evidence db, shared db, the ClinVar
    matches artifact, reference FASTA, genome build) from the approved active
    run into ``params``.

    Index access itself no longer flows through here: a handler obtains the
    Active Genome Index via ``agi_access.open_agi`` (auth + reader), which is the
    single door. This helper only fills the side resources those handlers still
    need alongside the reader."""
    resolved = dict(params)
    needs_agi_side_context = (
        not allow_shared_db_without_vcf
        or matches
        or reference_fasta
    )
    active = None
    if needs_agi_side_context:
        from .agi_access import resolve_agi_record

        active = resolve_agi_record(resolved, require_approved=True)
    if active is not None:
        if db and not resolved.get("db"):
            resolved["db"] = active.get("evidence_db")
        if matches and not resolved.get("matches"):
            resolved["matches"] = active.get("matches")
        if shared_db and not resolved.get("shared_db"):
            resolved["shared_db"] = active.get("shared_evidence_db")
        if reference_fasta and not resolved.get("reference_fasta"):
            resolved["reference_fasta"] = active.get("reference_fasta")
        active_build = str(active.get("genome_build") or "")
        if genome_build and not resolved.get("genome_build") and active_build and active_build != "auto":
            resolved["genome_build"] = active.get("genome_build")
    if db and allow_shared_db_without_vcf and not resolved.get("db"):
        shared_db_path = shared_evidence_db_path()
        init_evidence_db(shared_db_path)
        resolved["db"] = str(shared_db_path)
    if shared_db and not resolved.get("shared_db"):
        resolved["shared_db"] = str(shared_evidence_db_path())
    return resolved


def _require_context_value(params: JsonObject, key: str, message: str) -> None:
    if params.get(key) is None or params.get(key) == "":
        raise OperationError("missing_context", message)


def _remember_source_result(
    agi_intake_source_path: Path,
    result: JsonObject,
    *,
    status: str,
    user_nickname: str | None = None,
    set_default_user: bool = False,
) -> JsonObject:
    try:
        active = runtime_context.set_active_agi_from_source(
            agi_intake_source_path,
            agi_source_format=result.get("source_format"),
            operation_result=result,
            status=status,
            user_nickname=user_nickname,
            set_default_user=set_default_user,
            grant_access=True,
        )
    except ValueError as exc:
        raise OperationError("invalid_params", str(exc)) from exc
    agent_result = _hide_intake_source_after_digitization(result) if status == "parsed" else dict(result)
    agent_result["active_genome_index"] = runtime_context.describe_agi_record(active)
    return agent_result


def _hide_intake_source_after_digitization(result: JsonObject) -> JsonObject:
    payload = dict(result)
    agi_intake_source_path = payload.pop("source", None)
    agi_comparable_variant_export = payload.pop("agi_comparable_variant_export", None)
    if agi_comparable_variant_export:
        payload["agi_comparable_variant_export"] = agi_comparable_variant_export
    payload["intake_source"] = {
        "role": "ingestion_source_for_digitization",
        "hidden_after_digitization": True,
        "available_for_rebuild": bool(
            agi_intake_source_path
            and Path(str(agi_intake_source_path)).exists()
        ),
    }
    payload["digitization_contract"] = runtime_context.DIGITIZATION_CONTRACT
    hidden_paths = _hidden_intake_path_strings(agi_intake_source_path)
    return _redact_intake_paths(payload, hidden_paths)


def _hidden_intake_path_strings(*values: object) -> set[str]:
    hidden: set[str] = set()
    for value in values:
        if value is None or value == "":
            continue
        text = str(value)
        hidden.add(text)
        hidden.add(str(Path(text).expanduser().resolve(strict=False)))
    return hidden


def _redact_intake_paths(value: object, hidden_paths: set[str]) -> object:
    if isinstance(value, dict):
        redacted: JsonObject = {}
        for key, item in value.items():
            if isinstance(item, str) and _is_hidden_intake_path(item, hidden_paths):
                continue
            redacted[key] = _redact_intake_paths(item, hidden_paths)
        return redacted
    if isinstance(value, list):
        return [_redact_intake_paths(item, hidden_paths) for item in value]
    if isinstance(value, str) and _is_hidden_intake_path(value, hidden_paths):
        return "[hidden_intake_source]"
    return value


def _is_hidden_intake_path(value: str, hidden_paths: set[str]) -> bool:
    if value in hidden_paths:
        return True
    try:
        return str(Path(value).expanduser().resolve(strict=False)) in hidden_paths
    except OSError:
        return False


_UNRESOLVED_DEFAULT = object()
_SKIP_DEFAULT = object()


def defaults_applied_for_call(operation_name: str, params: JsonObject | None = None) -> list[JsonObject]:
    from .table import get_operation

    operation = get_operation(operation_name)
    safe_params = params or {}
    applied: list[JsonObject] = []
    for default in _operation_parameter_defaults(operation):
        parameter = str(default.get("parameter") or "")
        if not parameter or parameter in safe_params:
            continue
        record = dict(default)
        resolved = _resolved_default_value(operation_name, parameter, safe_params)
        if resolved is _SKIP_DEFAULT:
            continue
        if resolved is not _UNRESOLVED_DEFAULT:
            record["value"] = resolved
        applied.append(record)
    return applied


def _resolved_default_value(operation_name: str, parameter: str, params: JsonObject) -> object:
    if operation_name == "variant.resolve" and parameter == "include_active_genome_index":
        named_agi = params.get("agi_id")
        return runtime_context.agi_access_approved() and not bool(named_agi)
    if operation_name == "phenotype.plan_risk_investigation" and parameter == "include_active_genome_index":
        return params.get("matches") not in (None, "")
    if operation_name == "pharmacogenomics.review_medication" and parameter == "include_active_genome_index":
        return bool(
            params.get("db")
            or params.get("agi_path")
            or (runtime_context.agi_access_approved() and runtime_context.active_agi_record() is not None)
        )
    if operation_name == "journal.append_entry":
        if parameter == "scope":
            return "session_and_project" if params.get("entry_id") not in (None, "") else "session"
        if parameter == "created_by":
            return _SKIP_DEFAULT if params.get("entry_id") not in (None, "") else "host_agent"
        if parameter == "amendment_type":
            if params.get("entry_id") in (None, "") or params.get("content") in (None, ""):
                return _SKIP_DEFAULT
            return "correction"
    if operation_name == "sequence.analyze":
        mode = str(params.get("mode") or "summary")
        if parameter == "frame" and mode not in {"summary", "translate"}:
            return _SKIP_DEFAULT
        if parameter == "strand" and mode not in {"summary", "translate", "orfs"}:
            return _SKIP_DEFAULT
        if parameter == "min_aa" and mode not in {"summary", "orfs"}:
            return _SKIP_DEFAULT
        if parameter == "max_matches" and params.get("reference_fasta") in (None, ""):
            return _SKIP_DEFAULT
    if parameter == "genome_build" and operation_name == "prs.import_scoring_file":
        return "GRCh38"
    if parameter == "genome_build" and operation_name in {
        "ancestry.check_sample_overlap",
        "ancestry.project_pca",
        "ancestry.estimate_population_context",
        "prs.check_score_overlap",
        "prs.calculate_score",
        "variant.find_gene_variants",
    }:
        return _default_genome_build_from_approved_agi(params) or "GRCh38"
    return _UNRESOLVED_DEFAULT


def _default_genome_build_from_approved_agi(params: JsonObject) -> str | None:
    from .execution import current_execution_context

    execution_context = current_execution_context()
    if execution_context is not None and execution_context.agi_read_lease is not None:
        build = _run_genome_build(dict(execution_context.agi_read_lease.agi_record))
        if build:
            return build

    explicit_path = params.get("agi_path")
    if explicit_path not in (None, ""):
        from .agi_access import _registered_run_for_agi_path

        run = _registered_run_for_agi_path(explicit_path)
        build = _run_genome_build(run) if isinstance(run, dict) and runtime_context.agi_access_approved(run) else None
        if build:
            return build

    named = params.get("agi_id")
    if named not in (None, ""):
        run = runtime_context.find_agi(str(named))
        build = _run_genome_build(run) if isinstance(run, dict) and runtime_context.agi_access_approved(run) else None
        if build:
            return build

    active = runtime_context.active_agi_record()
    if isinstance(active, dict) and runtime_context.agi_access_approved(active):
        return _run_genome_build(active)
    return None


def _run_genome_build(run: JsonObject | None) -> str | None:
    build = str((run or {}).get("genome_build") or "").strip()
    return build if build and build != "auto" else None


def _with_defaults_applied(operation_name: str, params: JsonObject, result: object) -> object:
    if not isinstance(result, dict):
        return result
    defaults = defaults_applied_for_call(operation_name, params)
    if defaults and "defaults_applied" not in result:
        result["defaults_applied"] = defaults
    return result
