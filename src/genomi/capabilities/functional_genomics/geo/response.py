from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ....retrieval import semantic as retrieval_semantic
from .client import GEO_QUERY_SCHEMA_VERSION
from .text_utils import _dedupe_text, _extract_accessions, _records_by_gene


def _geo_response(
    *,
    query: dict[str, Any],
    geo_hits: list[dict[str, Any]],
    download_candidates: list[dict[str, Any]],
    source_records: list[dict[str, Any]],
    acquisition: dict[str, Any] | None,
    status: str,
    coverage_state: str,
    consulted: list[str],
    unavailable: list[dict[str, str]],
    semantic_context: retrieval_semantic.SemanticContext | None,
) -> dict[str, Any]:
    direct_records = []
    if acquisition:
        direct_records = [record for record in acquisition.get("direct_perturbation_source_records", []) if isinstance(record, dict)]
    payload: dict[str, Any] = {
        "schema": GEO_QUERY_SCHEMA_VERSION,
        "ok": status != "source_unavailable",
        "status": status,
        "coverage_state": coverage_state,
        "query": query,
        "capability": {
            "name": "functional_genomics.query_geo",
            "scope": "NCBI GEO metadata and bounded public table discovery for perturbation source records.",
            "supported_sources": {
                "ncbi_geo_gds": "NCBI GEO DataSets E-Utilities metadata.",
                "geo_ftp": "Bounded text-like GEO SeriesMatrix and supplementary tables.",
            },
        },
        "geo_hits": geo_hits,
        "download_candidates": download_candidates,
        "source_records": source_records,
        "direct_perturbation_source_records": direct_records,
        "records_by_gene": _records_by_gene(source_records),
        "coverage": {
            "geo_hit_count": len(geo_hits),
            "download_candidate_count": len(download_candidates),
            "used_download_candidate_count": sum(1 for item in download_candidates if item.get("status") == "used"),
            "source_record_count": len(source_records),
            "direct_perturbation_source_record_count": len(direct_records),
            "candidate_gene_count": len(query.get("genes") or []),
        },
        "source_coverage": {
            "coverage_state": coverage_state,
            "sources_requested": ["NCBI GEO"],
            "sources_consulted": consulted,
            "sources_consulted_and_empty": ["NCBI GEO"] if consulted and not geo_hits else [],
            "sources_consulted_but_unavailable": unavailable,
            "sources_not_integrated": [
                "ArrayExpress",
                "journal supplementary tables outside GEO",
                "large raw GEO archives",
                "FASTQ/BAM/CEL-style raw assay files",
            ],
        },
    }
    if acquisition:
        payload["source_acquisition"] = {
            "status": acquisition.get("status"),
            "summary": acquisition.get("summary"),
            "source_gaps": acquisition.get("source_gaps"),
            "next_actions": acquisition.get("next_actions"),
        }
    if semantic_context and semantic_context.has_hints:
        payload["semantic_context"] = _geo_semantic_usage(semantic_context, geo_hits, source_records, query)
    if status == "source_unavailable":
        payload["empty_reason"] = "NCBI GEO could not be queried for this input."
    elif geo_hits and not source_records:
        payload["empty_reason"] = (
            "GEO metadata matched, but no bounded text-like table yielded source-verified candidate-gene "
            "perturbation records. Metadata-only matches are not direct evidence."
        )
    elif not geo_hits:
        payload["empty_reason"] = "NCBI GEO returned no metadata hits for the supplied query."
    return payload


def _geo_semantic_usage(
    semantic: retrieval_semantic.SemanticContext,
    geo_hits: Iterable[dict[str, Any]],
    source_records: Iterable[dict[str, Any]],
    query: dict[str, Any],
) -> dict[str, Any]:
    values: list[str] = []
    for hit in geo_hits:
        values.extend(str(hit.get(key) or "") for key in ("accession", "title", "summary", "organism", "geo_type"))
    for record in source_records:
        values.extend(str(item) for item in record.get("genes") or [])
        values.extend(str(record.get(key) or "") for key in ("finding", "cell_line", "perturbation", "assay", "phenotype"))
    return retrieval_semantic.term_usage_payload(
        semantic,
        term_matches=retrieval_semantic.matched_terms(
            semantic,
            _dedupe_text(values),
            match_type="matched_ncbi_geo_metadata_or_table_record",
            source="NCBI GEO",
        ),
        streams=retrieval_semantic.retrieval_streams(
            raw_query=semantic.raw_query,
            host_terms=retrieval_semantic.search_terms(semantic),
            exact_ids=[*(query.get("genes") or []), *(_extract_accessions(query.get("accession") or query.get("context") or ""))],
            source_native_filters=[
                str(query.get(key))
                for key in ("context", "organism", "cell_line", "perturbation", "assay", "phenotype")
                if query.get(key)
            ],
        ),
    )
