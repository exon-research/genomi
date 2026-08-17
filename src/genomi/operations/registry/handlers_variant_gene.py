from __future__ import annotations

from pathlib import Path
from typing import Any

from ...active_genome_index.active_genome_index import ActiveGenomeIndexNeed
from ...capabilities.variant import gene_variants
from ...evidence import envelope as evidence_envelope
from ...runtime.libraries import manager as library_manager
from .agi_access import open_agi, resolve_agi_record
from .errors import JsonObject, OperationError
from .execution import current_execution_context


_SUPPORTED_GENE_VARIANT_BUILDS = ("GRCh37", "GRCh38")


def _variant_find_gene_variants(params: JsonObject) -> JsonObject:
    genes = _candidate_genes(params)
    per_gene_limit = _bounded_int(
        params,
        "per_gene_limit",
        default=gene_variants.DEFAULT_PER_GENE_LIMIT,
        minimum=1,
        maximum=gene_variants.MAX_PER_GENE_LIMIT,
    )
    agi_reader = open_agi(
        need=ActiveGenomeIndexNeed.VARIANT,
        action="finding variants in candidate-gene intervals",
        params=params,
    )
    agi_metadata = _gene_variant_agi_metadata(params)
    genome_build = _normalize_gene_variant_build(
        params.get("genome_build") or agi_reader.genome_build or "GRCh38"
    )
    unsupported = _gene_variant_unsupported_build(genes, genome_build)
    if unsupported is not None:
        return unsupported
    mismatch = _gene_variant_build_mismatch(
        agi_reader,
        params,
        genes,
        genome_build,
    )
    if mismatch is not None:
        return mismatch
    unsupported_source = _gene_variant_unsupported_agi_source(
        agi_reader,
        agi_metadata,
        genes,
        genome_build,
    )
    if unsupported_source is not None:
        return unsupported_source

    library = f"gencode-{genome_build.lower()}"
    library_status = library_manager.status(library)
    coordinate_source = _gencode_source(library, library_status, genome_build)
    if not library_status.get("installed"):
        return _gene_variant_missing_library(
            genes,
            genome_build,
            library,
            library_status,
        )

    from ...capabilities.analytical_grounding.analytical_grounding.library import (
        default_gencode_gtf_path,
    )

    gencode_gtf = default_gencode_gtf_path(genome_build)
    if gencode_gtf is None:
        return _gene_variant_missing_library(
            genes,
            genome_build,
            library,
            library_status,
        )
    try:
        return gene_variants.find_gene_variants(
            agi_reader,
            genes=genes,
            genome_build=genome_build,
            gencode_gtf=gencode_gtf,
            coordinate_source=coordinate_source,
            per_gene_limit=per_gene_limit,
            agi_metadata=agi_metadata,
        )
    except OSError as exc:
        return _gene_variant_source_unavailable(
            genes,
            genome_build,
            coordinate_source,
            exc,
        )


def _candidate_genes(params: JsonObject) -> list[str]:
    raw = params.get("genes")
    if not isinstance(raw, list):
        raise OperationError("invalid_params", "genes must be an array")
    if not gene_variants.MIN_CANDIDATE_GENES <= len(raw) <= gene_variants.MAX_CANDIDATE_GENES:
        raise OperationError(
            "invalid_params",
            "genes must contain between 1 and 10 candidate gene symbols",
        )
    genes: list[str] = []
    seen: set[str] = set()
    for value in raw:
        if not isinstance(value, str):
            raise OperationError("invalid_params", "genes must contain strings")
        gene = value.strip().upper()
        if not gene or len(gene) > 64:
            raise OperationError(
                "invalid_params",
                "each candidate gene symbol must contain 1 to 64 characters",
            )
        if gene in seen:
            raise OperationError(
                "invalid_params",
                "genes must contain unique candidate gene symbols",
            )
        seen.add(gene)
        genes.append(gene)
    return genes


def _bounded_int(
    params: JsonObject,
    key: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw_value = params.get(key, default)
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise OperationError("invalid_params", f"{key} must be an integer")
    value = raw_value
    if value < minimum or value > maximum:
        raise OperationError(
            "invalid_params",
            f"{key} must be between {minimum} and {maximum}",
        )
    return value


def _normalize_gene_variant_build(value: object) -> str:
    normalized = str(value or "").strip().upper().replace("-", "")
    return {
        "GRCH37": "GRCh37",
        "HG19": "GRCh37",
        "GRCH38": "GRCh38",
        "HG38": "GRCh38",
    }.get(normalized, str(value or "").strip())


def _gene_variant_query_scope(genes: list[str], genome_build: str) -> JsonObject:
    return {
        "genes": genes,
        "consulted_genes": [],
        "unassessed_genes": genes,
        "genome_build": genome_build,
        "match_basis": "gencode_gene_interval_overlap",
        "passing_filters_only": True,
    }


def _gene_variant_agi_metadata(params: JsonObject) -> JsonObject:
    execution_context = current_execution_context()
    if execution_context is not None and execution_context.agi_read_lease is not None:
        return dict(execution_context.agi_read_lease.agi_record)
    record = resolve_agi_record(params, require_approved=True)
    return dict(record) if isinstance(record, dict) else {}


def _gene_variant_unsupported_agi_source(
    agi_reader: Any,
    agi_metadata: JsonObject,
    genes: list[str],
    genome_build: str,
) -> JsonObject | None:
    source_kind = str(agi_metadata.get("agi_source_kind") or "").strip()
    if source_kind != "consumer_genotype_array":
        return None
    source_format = str(agi_metadata.get("agi_source_format") or "").strip()
    agi_context: JsonObject = {
        "genome_build": genome_build,
        "source_kind": source_kind,
        "agi_snapshot_id": agi_reader.verified_snapshot_id,
        "agi_artifact_sha256": agi_reader.verified_artifact_sha256,
        "agi_parse_state": agi_reader.parse_state(),
    }
    if source_format:
        agi_context["source_format"] = source_format
    next_actions = [
        {
            "action": "use_variant_callset_or_sequencing_active_genome_index",
        }
    ]
    result: JsonObject = {
        "status": "out_of_scope_for_input",
        "coverage_state": "out_of_scope_for_input",
        "query": _gene_variant_query_scope(genes, genome_build),
        "agi_context": agi_context,
        "gene_resolution": {
            "requested_genes": genes,
            "resolved_genes": [],
            "unresolved_genes": [],
            "unassessed_genes": genes,
            "intervals": [],
        },
        "gene_results": [],
        "variants": [],
        "coverage": {
            "requested_gene_count": len(genes),
            "returned_variant_count": 0,
            "blocked_by_source_kind": source_kind,
        },
    }
    observations: JsonObject = {
        "active_genome_index_source_kind": source_kind,
        "returned_variant_count": 0,
    }
    if source_format:
        observations["active_genome_index_source_format"] = source_format
    result["evidence_envelope"] = evidence_envelope.not_assessed(
        operation=gene_variants.OPERATION,
        reason=(
            "Consumer genotype-array rows do not provide the ref/alt variant "
            "records required by this interval scan."
        ),
        query_scope=result["query"],
        personal_context={"uses_personal_dna": True},
        observations=observations,
        next_actions=next_actions,
        guidance=[
            "out_of_scope_for_input:use_variant_callset_or_sequencing_active_genome_index"
        ],
    )
    return result


def _gene_variant_unsupported_build(
    genes: list[str],
    genome_build: str,
) -> JsonObject | None:
    if genome_build in _SUPPORTED_GENE_VARIANT_BUILDS:
        return None
    next_actions = [
        {
            "action": "use_supported_genome_build",
            "supported_genome_builds": list(_SUPPORTED_GENE_VARIANT_BUILDS),
        }
    ]
    result: JsonObject = {
        "status": "out_of_scope_for_input",
        "coverage_state": "out_of_scope_for_input",
        "query": _gene_variant_query_scope(genes, genome_build),
        "supported_genome_builds": list(_SUPPORTED_GENE_VARIANT_BUILDS),
        "gene_resolution": {
            "requested_genes": genes,
            "resolved_genes": [],
            "unresolved_genes": [],
            "unassessed_genes": genes,
            "intervals": [],
        },
        "gene_results": [],
        "variants": [],
        "coverage": {
            "requested_gene_count": len(genes),
            "returned_variant_count": 0,
        },
    }
    result["evidence_envelope"] = evidence_envelope.not_assessed(
        operation=gene_variants.OPERATION,
        reason="Candidate-gene interval lookup supports GRCh37 and GRCh38.",
        query_scope=result["query"],
        personal_context={"uses_personal_dna": True},
        observations={
            "supported_genome_builds": list(_SUPPORTED_GENE_VARIANT_BUILDS)
        },
        next_actions=next_actions,
        guidance=["out_of_scope_for_input:choose_supported_genome_build"],
    )
    return result


def _gene_variant_build_mismatch(
    agi_reader: Any,
    params: JsonObject,
    genes: list[str],
    requested_build: str,
) -> JsonObject | None:
    if params.get("genome_build") in (None, "") or not agi_reader.genome_build:
        return None
    agi_build = _normalize_gene_variant_build(agi_reader.genome_build)
    if agi_build == requested_build:
        return None
    next_actions = [
        {"action": "use_active_genome_index_build", "genome_build": agi_build}
    ]
    result: JsonObject = {
        "status": "out_of_scope_for_input",
        "coverage_state": "out_of_scope_for_input",
        "query": _gene_variant_query_scope(genes, requested_build),
        "requested_genome_build": requested_build,
        "active_genome_index_genome_build": agi_build,
        "gene_results": [],
        "variants": [],
        "coverage": {
            "requested_gene_count": len(genes),
            "returned_variant_count": 0,
        },
    }
    result["evidence_envelope"] = evidence_envelope.not_assessed(
        operation=gene_variants.OPERATION,
        reason="Requested genome build conflicts with Active Genome Index metadata.",
        query_scope=result["query"],
        personal_context={"uses_personal_dna": True},
        observations={
            "requested_genome_build": requested_build,
            "active_genome_index_genome_build": agi_build,
        },
        next_actions=next_actions,
        guidance=["out_of_scope_for_input:use_active_genome_index_genome_build"],
    )
    return result


def _gene_variant_missing_library(
    genes: list[str],
    genome_build: str,
    library: str,
    library_status: JsonObject,
) -> JsonObject:
    request = library_manager.missing_request(
        library,
        intent="mapping candidate gene symbols to genomic intervals",
        operation=gene_variants.OPERATION,
        genome_build=genome_build,
    )
    missing_library = _present_library_status(
        request.get("missing_library")
        if isinstance(request.get("missing_library"), dict)
        else library_status
    )
    request["missing_library"] = missing_library
    request.update(
        {
            "coverage_state": "blocked_missing_library",
            "query": _gene_variant_query_scope(genes, genome_build),
            "gene_resolution": {
                "requested_genes": genes,
                "resolved_genes": [],
                "unresolved_genes": [],
                "unassessed_genes": genes,
                "intervals": [],
            },
            "gene_results": [],
            "variants": [],
            "coverage": {
                "requested_gene_count": len(genes),
                "returned_variant_count": 0,
                "blocked_by_library": library,
            },
        }
    )
    request["evidence_envelope"] = evidence_envelope.missing_library(
        operation=gene_variants.OPERATION,
        library=library,
        library_status_payload=missing_library,
        query_scope=request["query"],
        personal_context={"uses_personal_dna": True},
        intent="mapping candidate gene symbols to genomic intervals",
        guidance=["blocked_missing_library:ask_user_to_install"],
    )
    return request


def _gene_variant_source_unavailable(
    genes: list[str],
    genome_build: str,
    coordinate_source: JsonObject,
    error: OSError,
) -> JsonObject:
    result: JsonObject = {
        "status": "source_unavailable",
        "coverage_state": "source_unavailable",
        "query": _gene_variant_query_scope(genes, genome_build),
        "coordinate_source": coordinate_source,
        "gene_results": [],
        "variants": [],
        "coverage": {
            "requested_gene_count": len(genes),
            "returned_variant_count": 0,
        },
    }
    result["evidence_envelope"] = evidence_envelope.not_assessed(
        operation=gene_variants.OPERATION,
        reason="The installed GENCODE annotation could not be read.",
        query_scope=result["query"],
        personal_context={"uses_personal_dna": True},
        coverage=evidence_envelope._coverage(
            libraries=[
                {
                    "library": coordinate_source.get("library"),
                    "state": "failed",
                    "title": coordinate_source.get("title"),
                    "error": type(error).__name__,
                }
            ],
            unavailable_sources=["managed_gencode_gtf"],
        ),
        observations={"returned_variant_count": 0},
        next_actions=[{"action": "repair_or_reinstall_gencode_library"}],
        guidance=["source_unavailable:repair_or_reinstall_gencode_library"],
    )
    return result


def _present_library_status(status: JsonObject) -> JsonObject:
    return {
        key: status.get(key)
        for key in (
            "library",
            "title",
            "kind",
            "size_class",
            "installed",
            "status",
            "install_libraries",
            "install_command",
            "helps",
        )
        if status.get(key) not in (None, "", [], {})
    }


def _gencode_source(
    library: str,
    library_status: JsonObject,
    genome_build: str,
) -> JsonObject:
    spec = library_manager.get(library)
    source_url = spec.source.urls[0] if spec.source.urls else ""
    return {
        "library": library,
        "title": library_status.get("title") or spec.title,
        "genome_build": genome_build,
        "source": "GENCODE",
        "source_url": source_url,
        "source_artifact": Path(source_url).name if source_url else "",
    }
