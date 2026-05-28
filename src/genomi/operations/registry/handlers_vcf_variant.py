from __future__ import annotations

from ...capabilities.clinvar import static_annotation
from ...capabilities.variant import variant_lookup
from ...runtime import context as runtime_context
from .coerce import (
    _approve_supplied_dna_source,
    _bool,
    _float,
    _int,
    _optional_path,
    _path,
    _require_agi_access,
    _require_personal_artifact_context,
    _remember_result,
    _str,
    _with_context,
)
from .errors import JsonObject, OperationError


def _vcf_init(params: JsonObject) -> JsonObject:
    _approve_supplied_dna_source(params)
    vcf = _path(params, "vcf")
    result = static_annotation.init_static_run(
        vcf,
        source_evidence_db=_optional_path(params, "source_evidence_db"),
        shared_evidence_db=_optional_path(params, "shared_db"),
        force=_bool(params, "force"),
    )
    return _remember_result(vcf, result, status="initialized")


def _vcf_summary(params: JsonObject) -> JsonObject:
    resolved = _with_context(params, vcf=True, db=True)
    _require_personal_artifact_context(
        params,
        resolved,
        "vcf",
        "Provide a genome source or select an Active Genome Index with genomi.parse_source or genomi.assign_user_genome.",
        "reading Active Genome Index artifacts",
    )
    return static_annotation.summarize_static_state(_path(resolved, "vcf"), evidence_db=_optional_path(resolved, "db"))


def _vcf_qc(params: JsonObject) -> JsonObject:
    resolved = _with_context(params, vcf=True, db=True, active_genome_index_path=True, genome_build=True)
    _require_personal_artifact_context(
        params,
        resolved,
        "vcf",
        "Provide a genome source or select an Active Genome Index before running QC.",
        "reading Active Genome Index artifacts",
    )
    return static_annotation.run_static_sample_qc(
        _path(resolved, "vcf"),
        evidence_db=_optional_path(resolved, "db"),
        active_genome_index_path=_optional_path(resolved, "active_genome_index_path"),
        output=_optional_path(resolved, "output"),
        genome_build=_str(resolved, "genome_build", "auto"),
        scan_records=_int(resolved, "scan_records", 1000),
    )


def _vcf_genotype_support(params: JsonObject) -> JsonObject:
    resolved = _with_context(params, vcf=True, db=True, active_genome_index_path=True, reference_fasta=True, genome_build=True)
    _require_personal_artifact_context(
        params,
        resolved,
        "vcf",
        "Provide a genome source or select an Active Genome Index before checking genotype support.",
        "reading Active Genome Index artifacts",
    )
    return static_annotation.run_static_genotype_support(
        _path(resolved, "vcf"),
        _str(resolved, "chrom"),
        _int(resolved, "pos"),
        _str(resolved, "ref"),
        _str(resolved, "alt"),
        evidence_db=_optional_path(resolved, "db"),
        active_genome_index_path=_optional_path(resolved, "active_genome_index_path"),
        output=_optional_path(resolved, "output"),
        genome_build=_str(resolved, "genome_build", "auto"),
        reference_fasta=_optional_path(resolved, "reference_fasta"),
        min_depth=_int(resolved, "min_depth", 10),
        min_genotype_quality=_int(resolved, "min_gq", 20),
    )


def _vcf_callability(params: JsonObject) -> JsonObject:
    resolved = _with_context(params, vcf=True, db=True, active_genome_index_path=True, genome_build=True)
    _require_personal_artifact_context(
        params,
        resolved,
        "vcf",
        "Provide a genome source or select an Active Genome Index before checking callability.",
        "reading Active Genome Index artifacts",
    )
    return static_annotation.run_static_callability(
        _path(resolved, "vcf"),
        _str(resolved, "region"),
        evidence_db=_optional_path(resolved, "db"),
        active_genome_index_path=_optional_path(resolved, "active_genome_index_path"),
        output=_optional_path(resolved, "output"),
        genome_build=_str(resolved, "genome_build", "auto"),
        min_depth=_int(resolved, "min_depth", 10),
        min_covered_fraction=_float(resolved, "min_covered_fraction", 0.95),
        limit=_int(resolved, "limit", 5000),
    )


def _variant_lookup(params: JsonObject) -> JsonObject:
    named_agi = params.get("agi_id")
    include_known_active_genome_indexes = _bool(params, "include_known_active_genome_indexes")
    include_active_genome_index = _bool(
        params,
        "include_active_genome_index",
        runtime_context.agi_access_approved() and not bool(named_agi),
    )
    if named_agi and not runtime_context.agi_access_approved(str(named_agi)):
        raise OperationError(
            "active_genome_index_approval_required",
            "Explicit user approval is required before reading that Active Genome Index. After approval, call genomi.approve_agi_access for the target agi_id.",
        )
    if (include_known_active_genome_indexes or include_active_genome_index) and not runtime_context.agi_access_approved():
        _require_agi_access("reading parsed Active Genome Index artifacts")
    return variant_lookup.lookup_variant(
        query=params.get("query"),
        rsid=params.get("rsid"),
        chrom=params.get("chrom"),
        pos=params.get("pos"),
        ref=params.get("ref"),
        alt=params.get("alt"),
        region=params.get("region"),
        genome_build=_str(params, "genome_build", "GRCh38"),
        db=params.get("db"),
        shared_db=params.get("shared_db"),
        agi_id=named_agi,
        include_active_genome_index=include_active_genome_index,
        include_known_active_genome_indexes=include_known_active_genome_indexes,
        include_fail=_bool(params, "include_fail"),
        limit=_int(params, "limit", 20),
    )
