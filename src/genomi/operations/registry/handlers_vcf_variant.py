from __future__ import annotations

from ...active_genome_index.active_genome_index import ActiveGenomeIndexNeed
from ...capabilities.clinvar import static_annotation
from ...capabilities.variant import variant_lookup
from ...runtime import context as runtime_context
from .agi_access import open_agi
from .coerce import (
    _bool,
    _float,
    _int,
    _optional_int,
    _optional_path,
    _str,
    _with_context,
)
from .errors import JsonObject, OperationError


def _agi_build_reference_pass(params: JsonObject) -> JsonObject:
    """Phase B of a two-phase gVCF parse: append the reference-block tail to a
    variants_ready Active Genome Index and flip it to completed.

    This is an internal continuation launched as a detached background job by
    parse_source — not a user-facing capability. It needs only the index path;
    the canonical source is resolved from the index's own metadata.
    """
    from ...active_genome_index.active_genome_index import append_reference_pass

    agi_path = _optional_path(params, "agi_path")
    if agi_path is None:
        raise OperationError(
            "invalid_params",
            "active_genome_index.build_reference_pass requires agi_path",
        )
    return append_reference_pass(agi_path, parallel_workers=_optional_int(params, "parallel_workers"))


def _agi_summary(params: JsonObject) -> JsonObject:
    # Auth-gate only (need=NONE): the QC/summary capabilities build the Active
    # Genome Index on demand, so they must not be blocked by a readiness gate.
    reader = open_agi(need=ActiveGenomeIndexNeed.NONE, action="reading Active Genome Index artifacts", params=params)
    resolved = _with_context(params, db=True)
    return static_annotation.summarize_static_state_from_agi(
        reader.agi_path,
        evidence_db=_optional_path(resolved, "db"),
    )


def _agi_qc(params: JsonObject) -> JsonObject:
    reader = open_agi(need=ActiveGenomeIndexNeed.REFERENCE, action="reading Active Genome Index artifacts", params=params)
    reader.ensure_ready()
    resolved = _with_context(params, db=True, genome_build=True)
    # reference_pending stamped by the chokepoint: callset QC keys "has
    # reference blocks" / absence-allowed off reference rows, so its
    # classification is provisional until the reference tail (Phase B) lands.
    return static_annotation.run_static_sample_qc_from_agi(
        reader.agi_path,
        evidence_db=_optional_path(resolved, "db"),
        output=_optional_path(params, "output"),
        genome_build=_str(resolved, "genome_build", "auto"),
        scan_records=_int(params, "scan_records", 1000),
    )


def _agi_genotype_support(params: JsonObject) -> JsonObject:
    reader = open_agi(need=ActiveGenomeIndexNeed.REFERENCE, action="reading Active Genome Index artifacts", params=params)
    reader.ensure_ready()
    resolved = _with_context(params, db=True, reference_fasta=True, genome_build=True)
    return static_annotation.run_static_genotype_support_from_agi(
        reader.agi_path,
        _str(params, "chrom"),
        _int(params, "pos"),
        _str(params, "ref"),
        _str(params, "alt"),
        evidence_db=_optional_path(resolved, "db"),
        output=_optional_path(params, "output"),
        genome_build=_str(resolved, "genome_build", "auto"),
        reference_fasta=_optional_path(resolved, "reference_fasta"),
        min_depth=_int(params, "min_depth", 10),
        min_genotype_quality=_int(params, "min_gq", 20),
    )


def _agi_callability(params: JsonObject) -> JsonObject:
    reader = open_agi(need=ActiveGenomeIndexNeed.REFERENCE, action="reading Active Genome Index artifacts", params=params)
    reader.ensure_ready()
    resolved = _with_context(params, db=True, genome_build=True)
    return static_annotation.run_static_callability_from_agi(
        reader.agi_path,
        _str(params, "region"),
        evidence_db=_optional_path(resolved, "db"),
        output=_optional_path(params, "output"),
        genome_build=_str(resolved, "genome_build", "auto"),
        min_depth=_int(params, "min_depth", 10),
        min_covered_fraction=_float(params, "min_covered_fraction", 0.95),
        limit=_int(params, "limit", 5000),
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
            "Explicit user approval is required before reading that Active Genome Index. After approval, call active_genome_index.approve_access for the target agi_id.",
        )
    if (include_known_active_genome_indexes or include_active_genome_index) and not runtime_context.agi_access_approved():
        raise OperationError(
            "active_genome_index_approval_required",
            (
                "Explicit user approval is required before reading parsed Active Genome Index artifacts. "
                "After the user approves Active Genome Index access for this chat, call active_genome_index.approve_access."
            ),
        )
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
