from __future__ import annotations

from pathlib import Path
from typing import Any

from ...active_genome_index.active_genome_index import ActiveGenomeIndexReader
from ...capabilities.analytical_grounding.analytical_grounding.gene_coordinates import (
    resolve_gencode_gene_intervals,
)
from ...evidence import envelope as evidence_envelope


JsonObject = dict[str, Any]

OPERATION = "variant.find_gene_variants"
MIN_CANDIDATE_GENES = 1
MAX_CANDIDATE_GENES = 10
DEFAULT_PER_GENE_LIMIT = 100
MAX_PER_GENE_LIMIT = 200


def find_gene_variants(
    agi_reader: ActiveGenomeIndexReader,
    *,
    genes: list[str],
    genome_build: str,
    gencode_gtf: str | Path,
    coordinate_source: JsonObject,
    per_gene_limit: int = DEFAULT_PER_GENE_LIMIT,
    agi_metadata: JsonObject | None = None,
) -> JsonObject:
    """Find passing AGI variant records overlapping exact GENCODE genes."""

    gene_resolution = resolve_gencode_gene_intervals(
        gencode_gtf,
        genes,
        genome_build=genome_build,
    )
    query_scope = {
        "genes": list(genes),
        "genome_build": genome_build,
        "match_basis": "gencode_gene_interval_overlap",
        "passing_filters_only": True,
        "per_gene_limit": per_gene_limit,
    }
    agi_context = _agi_context(
        agi_reader,
        genome_build,
        agi_metadata=agi_metadata,
    )
    personal_context = {
        "uses_personal_dna": True,
        "source": "active_genome_index",
    }
    coverage = _base_coverage(gene_resolution)
    query_scope.update(
        {
            "consulted_genes": gene_resolution["resolved_genes"],
            "unassessed_genes": gene_resolution["unresolved_genes"],
        }
    )

    if not gene_resolution["resolved_genes"]:
        result: JsonObject = {
            "status": "out_of_scope_for_input",
            "coverage_state": "out_of_scope_for_input",
            "query": query_scope,
            "coordinate_source": coordinate_source,
            "agi_context": agi_context,
            "gene_resolution": gene_resolution,
            "gene_results": [],
            "variants": [],
            "coverage": coverage,
        }
        result["evidence_envelope"] = evidence_envelope.not_assessed(
            operation=OPERATION,
            reason="No requested gene symbol resolved to a canonical GENCODE gene interval.",
            query_scope=query_scope,
            personal_context=personal_context,
            coverage=_envelope_coverage(
                coordinate_source,
                active_genome_index_consulted=False,
                consulted_genes=[],
                unassessed_genes=gene_resolution["unresolved_genes"],
            ),
            observations={
                "requested_gene_count": coverage["requested_gene_count"],
                "resolved_gene_count": 0,
                "returned_variant_count": 0,
            },
            next_actions=[
                {
                    "action": "verify_candidate_gene_symbols",
                    "unresolved_genes": gene_resolution["unresolved_genes"],
                }
            ],
            guidance=["out_of_scope_for_input:verify_candidate_gene_symbols"],
        )
        return result

    intervals_by_gene: dict[str, list[JsonObject]] = {
        gene: [] for gene in gene_resolution["resolved_genes"]
    }
    for interval in gene_resolution["intervals"]:
        intervals_by_gene[str(interval["gene"])].append(interval)

    records_by_gene: dict[str, list[JsonObject]] = {}
    truncated_genes: list[str] = []
    for gene in gene_resolution["resolved_genes"]:
        records: dict[tuple[object, ...], JsonObject] = {}
        interval_hit_limit = False
        for interval in intervals_by_gene[gene]:
            rows = agi_reader.query_region(
                str(interval["chrom"]),
                int(interval["start"]),
                int(interval["end"]),
                variants_only=True,
                pass_only=True,
                limit=per_gene_limit + 1,
            )
            if len(rows) > per_gene_limit:
                interval_hit_limit = True
            for row in rows:
                key = _variant_record_key(row)
                current = records.setdefault(
                    key,
                    {
                        **_present_variant(row),
                        "matched_candidate_genes": [],
                        "matched_gene_interval_ids": [],
                        "match_basis": "gencode_gene_interval_overlap",
                    },
                )
                _append_unique(current["matched_candidate_genes"], gene)
                _append_unique(
                    current["matched_gene_interval_ids"],
                    str(interval["interval_id"]),
                )
        ordered = sorted(records.values(), key=_variant_order_key)
        if interval_hit_limit or len(ordered) > per_gene_limit:
            truncated_genes.append(gene)
        records_by_gene[gene] = ordered[:per_gene_limit]

    combined: dict[tuple[object, ...], JsonObject] = {}
    gene_results_by_gene: dict[str, JsonObject] = {}
    for gene in gene_resolution["resolved_genes"]:
        gene_variant_keys: list[str] = []
        for record in records_by_gene[gene]:
            key = _variant_record_key(record)
            current = combined.setdefault(
                key,
                {
                    **record,
                    "matched_candidate_genes": list(
                        record["matched_candidate_genes"]
                    ),
                    "matched_gene_interval_ids": list(
                        record["matched_gene_interval_ids"]
                    ),
                },
            )
            for matched_gene in record["matched_candidate_genes"]:
                _append_unique(current["matched_candidate_genes"], matched_gene)
            for interval_id in record["matched_gene_interval_ids"]:
                _append_unique(current["matched_gene_interval_ids"], interval_id)
            gene_variant_keys.append(str(current["record_key"]))
        gene_results_by_gene[gene] = {
            "gene": gene,
            "coverage_state": (
                "data_returned" if gene_variant_keys else "in_scope_empty"
            ),
            "interval_ids": [
                str(interval["interval_id"])
                for interval in intervals_by_gene[gene]
            ],
            "returned_variant_count": len(gene_variant_keys),
            "variant_record_keys": gene_variant_keys,
            "truncated": gene in truncated_genes,
        }
    for gene in gene_resolution["unresolved_genes"]:
        gene_results_by_gene[gene] = {
            "gene": gene,
            "coverage_state": "out_of_scope_for_input",
            "interval_ids": [],
            "returned_variant_count": 0,
            "variant_record_keys": [],
            "truncated": False,
        }
    gene_results = [
        gene_results_by_gene[gene]
        for gene in gene_resolution["requested_genes"]
    ]

    variants = sorted(combined.values(), key=_variant_order_key)
    coverage.update(
        {
            "queried_gene_count": len(gene_resolution["resolved_genes"]),
            "queried_interval_count": len(gene_resolution["intervals"]),
            "returned_variant_count": len(variants),
            "truncated_gene_count": len(truncated_genes),
            "truncated_genes": truncated_genes,
            "truncated": bool(truncated_genes),
        }
    )
    result = {
        "status": "variants_found" if variants else "in_scope_empty",
        "coverage_state": "data_returned" if variants else "in_scope_empty",
        "query": query_scope,
        "coordinate_source": coordinate_source,
        "agi_context": agi_context,
        "gene_resolution": gene_resolution,
        "gene_results": gene_results,
        "variants": variants,
        "coverage": coverage,
    }
    observations = {
        "requested_gene_count": coverage["requested_gene_count"],
        "resolved_gene_count": coverage["resolved_gene_count"],
        "unresolved_gene_count": coverage["unresolved_gene_count"],
        "queried_interval_count": coverage["queried_interval_count"],
        "returned_variant_count": coverage["returned_variant_count"],
        "truncated": coverage["truncated"],
    }
    envelope_coverage = _envelope_coverage(
        coordinate_source,
        consulted_genes=gene_resolution["resolved_genes"],
        unassessed_genes=gene_resolution["unresolved_genes"],
    )
    next_actions: list[JsonObject] = []
    if gene_resolution["unresolved_genes"]:
        next_actions.append(
            {
                "action": "verify_candidate_gene_symbols",
                "unresolved_genes": gene_resolution["unresolved_genes"],
            }
        )
    if truncated_genes:
        if per_gene_limit < MAX_PER_GENE_LIMIT:
            next_actions.append(
                {
                    "action": "increase_per_gene_limit",
                    "per_gene_limit": min(
                        MAX_PER_GENE_LIMIT,
                        max(per_gene_limit + 1, per_gene_limit * 2),
                    ),
                    "truncated_genes": truncated_genes,
                }
            )
        else:
            next_actions.append(
                {
                    "action": "review_truncated_gene_intervals",
                    "truncated_genes": truncated_genes,
                }
            )
    if variants:
        next_actions.append({"action": "clinically_confirm_candidate_variants"})
    if variants:
        result["evidence_envelope"] = evidence_envelope.evidence_present(
            operation=OPERATION,
            query_scope=query_scope,
            personal_context=personal_context,
            coverage=envelope_coverage,
            observations=observations,
            answer_readiness=evidence_envelope.NEEDS_CLINICAL_CONFIRMATION,
            next_actions=next_actions,
        )
    else:
        result["evidence_envelope"] = evidence_envelope.empty_consulted_scope(
            operation=OPERATION,
            query_scope=query_scope,
            personal_context=personal_context,
            coverage=envelope_coverage,
            observations=observations,
            next_actions=next_actions,
        )
    return result


def _present_variant(row: JsonObject) -> JsonObject:
    return {
        "record_key": _record_key_text(row),
        "chrom": row.get("chrom"),
        "pos": row.get("pos"),
        "end": row.get("end"),
        "rsid": row.get("rsid"),
        "ref": row.get("ref"),
        "alt": row.get("alt"),
        "filter": row.get("filter"),
        "record_kind": row.get("record_kind"),
        "genotype": row.get("genotype"),
        "depth": row.get("depth"),
        "genotype_quality": row.get("genotype_quality"),
        "observed_alleles": list(row.get("observed_alleles") or []),
        "sample_index": row.get("sample_index"),
        "info_genes": list(row.get("info_genes") or []),
    }


def _variant_record_key(row: JsonObject) -> tuple[object, ...]:
    return (
        str(row.get("chrom") or ""),
        int(row.get("pos") or 0),
        int(row.get("end") or row.get("pos") or 0),
        str(row.get("rsid") or ""),
        str(row.get("ref") or ""),
        str(row.get("alt") or ""),
        int(row.get("sample_index") or 0),
        str(row.get("genotype") or ""),
        str(row.get("filter") or ""),
    )


def _record_key_text(row: JsonObject) -> str:
    key = _variant_record_key(row)
    return (
        f"{key[0]}:{key[1]}-{key[2]}:{key[4]}:{key[5]}:"
        f"{key[3] or '.'}:sample-{key[6]}:gt-{key[7]}:filter-{key[8]}"
    )


def _variant_order_key(row: JsonObject) -> tuple[object, ...]:
    chrom = str(row.get("chrom") or "")
    if chrom.lower().startswith("chr"):
        chrom = chrom[3:]
    chrom_order = (
        int(chrom)
        if chrom.isdigit()
        else {"X": 23, "Y": 24, "M": 25, "MT": 25}.get(chrom.upper(), 99)
    )
    return (
        chrom_order,
        chrom,
        int(row.get("pos") or 0),
        int(row.get("end") or row.get("pos") or 0),
        str(row.get("ref") or ""),
        str(row.get("alt") or ""),
        int(row.get("sample_index") or 0),
    )


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _agi_context(
    agi_reader: ActiveGenomeIndexReader,
    genome_build: str,
    *,
    agi_metadata: JsonObject | None = None,
) -> JsonObject:
    context: JsonObject = {
        "genome_build": genome_build,
        "agi_snapshot_id": agi_reader.verified_snapshot_id,
        "agi_artifact_sha256": agi_reader.verified_artifact_sha256,
        "agi_parse_state": agi_reader.parse_state(),
    }
    metadata = agi_metadata or {}
    source_format = str(metadata.get("agi_source_format") or "").strip()
    source_kind = str(metadata.get("agi_source_kind") or "").strip()
    if source_format:
        context["source_format"] = source_format
    if source_kind:
        context["source_kind"] = source_kind
    return context


def _base_coverage(gene_resolution: JsonObject) -> JsonObject:
    resolved_count = len(gene_resolution["resolved_genes"])
    unresolved_count = len(gene_resolution["unresolved_genes"])
    return {
        "requested_gene_count": len(gene_resolution["requested_genes"]),
        "resolved_gene_count": resolved_count,
        "unresolved_gene_count": unresolved_count,
        "gene_scope_state": (
            "complete"
            if unresolved_count == 0
            else "partial"
            if resolved_count
            else "none_assessed"
        ),
        "queried_gene_count": 0,
        "queried_interval_count": 0,
        "returned_variant_count": 0,
        "truncated_gene_count": 0,
        "truncated_genes": [],
        "truncated": False,
    }


def _envelope_coverage(
    coordinate_source: JsonObject,
    *,
    active_genome_index_consulted: bool = True,
    consulted_genes: list[str] | None = None,
    unassessed_genes: list[str] | None = None,
) -> JsonObject:
    consulted_sources = ["managed_gencode_gtf"]
    if active_genome_index_consulted:
        consulted_sources.insert(0, "active_genome_index")
    coverage = evidence_envelope._coverage(
        libraries=[
            {
                "library": coordinate_source.get("library"),
                "state": "installed",
                "title": coordinate_source.get("title"),
            }
        ],
        consulted_sources=consulted_sources,
    )
    resolved = list(consulted_genes or [])
    unresolved = list(unassessed_genes or [])
    coverage.update(
        {
            "consulted_genes": resolved,
            "unassessed_genes": unresolved,
            "gene_scope_state": (
                "complete"
                if not unresolved
                else "partial"
                if resolved
                else "none_assessed"
            ),
        }
    )
    return coverage
