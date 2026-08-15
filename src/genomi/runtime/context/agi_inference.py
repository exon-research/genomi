from __future__ import annotations

from pathlib import Path

from ...active_genome_index.active_genome_index import default_agi_path
from ..paths import (
    ACTIVE_GENOME_INDEX_DB_NAME,
    CLINVAR_CANDIDATES_NAME,
    CLINVAR_MATCHES_NAME,
    expand_user_path,
    run_evidence_db_path_for_source,
    run_evidence_dir_for_source,
    run_output_path,
    run_output_path_for_source,
    run_project_dir_for_source,
    run_reference_dir_for_source,
    run_work_dir_for_source,
    sample_slug_from_source,
    shared_evidence_db_path,
    vcf_content_hash,
)
from .normalize import JsonObject, _infer_agi_source_format, _now, _outputs_from_result, _path_str


def infer_agi_record(
    agi_intake_source_path: str | Path,
    *,
    agi_source_format: str | None = None,
    operation_result: JsonObject | None = None,
    status: str = "available",
    db: str | Path | None = None,
    agi_path: str | Path | None = None,
    matches: str | Path | None = None,
    shared_db: str | Path | None = None,
    reference_fasta: str | Path | None = None,
    genotype_reference_fasta: str | Path | None = None,
    genome_build: str | None = None,
    root: str | Path | None = None,
) -> JsonObject:
    agi_intake_path = expand_user_path(agi_intake_source_path)
    outputs = _outputs_from_result(operation_result)
    result = operation_result or {}
    effective_format = _infer_agi_source_format(
        agi_intake_path,
        result.get("source_format") or agi_source_format,
    )
    sample_slug = str(
        result.get("sample_slug")
        or sample_slug_from_source(agi_intake_path, source_format=effective_format)
    )
    is_vcf = effective_format in {"vcf", "gvcf"}
    default_agi = (
        default_agi_path(agi_intake_path, root=root)
        if is_vcf
        else run_output_path_for_source(
            agi_intake_path,
            ACTIVE_GENOME_INDEX_DB_NAME,
            source_format=effective_format,
            root=root,
        )
    )
    default_matches = (
        run_output_path(agi_intake_path, CLINVAR_MATCHES_NAME, root=root)
        if is_vcf
        else None
    )
    default_candidate_inventory = (
        run_output_path(agi_intake_path, CLINVAR_CANDIDATES_NAME, root=root)
        if is_vcf
        else None
    )
    run: JsonObject = {
        "agi_id": sample_slug,
        "sample_slug": sample_slug,
        "status": status,
        "agi_intake_source_path": _path_str(result.get("source") or agi_intake_path),
        "agi_source_format": effective_format,
        "agi_source_kind": result.get("source_kind"),
        "agi_source_member": result.get("source_member"),
        "agi_source_provider": result.get("provider"),
        "source_content_sha256": result.get("source_content_sha256") or vcf_content_hash(agi_intake_path),
        "project_dir": _path_str(
            result.get("project_dir")
            or run_project_dir_for_source(agi_intake_path, source_format=effective_format, root=root)
        ),
        "work_dir": _path_str(
            result.get("work_dir")
            or run_work_dir_for_source(agi_intake_path, source_format=effective_format, root=root)
        ),
        "evidence_dir": _path_str(
            result.get("evidence_dir")
            or run_evidence_dir_for_source(agi_intake_path, source_format=effective_format, root=root)
        ),
        "reference_dir": _path_str(
            result.get("reference_dir")
            or run_reference_dir_for_source(agi_intake_path, source_format=effective_format, root=root)
        ),
        "evidence_db": _path_str(
            db
            or result.get("evidence_db")
            or run_evidence_db_path_for_source(agi_intake_path, source_format=effective_format, root=root)
        ),
        "shared_evidence_db": _path_str(shared_db or result.get("shared_evidence_db") or shared_evidence_db_path(root)),
        "agi_path": _path_str(agi_path or outputs.get("agi_path") or default_agi),
        "matches": _path_str(matches or outputs.get("clinvar_matches") or default_matches),
        "candidate_inventory": _path_str(outputs.get("clinvar_scan") or default_candidate_inventory),
        "agi_comparable_variant_export": _path_str(
            result.get("agi_comparable_variant_export")
            or outputs.get("exported_primary_variants")
            or outputs.get("exported_variants")
        ),
        "reference_fasta": _path_str(reference_fasta or result.get("reference_fasta")),
        "genotype_reference_fasta": _path_str(genotype_reference_fasta or result.get("genotype_reference_fasta")),
        "genome_build": genome_build or result.get("genome_build") or "auto",
        "outputs": {key: _path_str(value) for key, value in outputs.items()},
        "created_at": _now(),
        "updated_at": _now(),
    }
    return run


def _resolved_intake_source_path(agi_intake_source: str | Path) -> str:
    return str(expand_user_path(agi_intake_source).resolve(strict=False))
