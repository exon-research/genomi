from __future__ import annotations

from typing import Any

from .constants import (
    CONTROLLED_ENTITY_RELATIONSHIPS_SCHEMA_VERSION,
    DEFAULT_SPECIES,
    DEFAULT_TAXON_ID,
    NOT_INTEGRATED_SOURCES,
    SUPPORTED_ENTITY_TYPES,
    SUPPORTED_SOURCES,
)
from .helpers import (
    _clean_text,
    _normalize_evidence_class,
    _normalize_relationship_type,
    _safe_float,
)


def _dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for record in records:
        key = (
            _clean_text(record.get("source")),
            _clean_text((record.get("entity") or {}).get("entity_id") if isinstance(record.get("entity"), dict) else ""),
            _clean_text(record.get("gene")),
            _clean_text(record.get("relationship_type")),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def _records_by_gene(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        gene = _clean_text(record.get("gene")).upper()
        if gene:
            grouped.setdefault(gene, []).append(record)
    return grouped


def _filter_records(
    records: list[dict[str, Any]],
    *,
    relationship_types: list[str],
    evidence_classes: list[str],
) -> list[dict[str, Any]]:
    requested_relationships = {_normalize_relationship_type(item) for item in relationship_types if _clean_text(item)}
    requested_evidence_classes = {_normalize_evidence_class(item) for item in evidence_classes if _clean_text(item)}
    filtered: list[dict[str, Any]] = []
    for record in records:
        relationship_type = _normalize_relationship_type(record.get("relationship_type"))
        evidence_class = _normalize_evidence_class(record.get("evidence_class"))
        if requested_relationships and relationship_type not in requested_relationships:
            continue
        if requested_evidence_classes and evidence_class not in requested_evidence_classes:
            continue
        filtered.append(record)
    return filtered


def _sort_records_source_local(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(records, key=_record_order_key)


def _record_order_key(record: dict[str, Any]) -> tuple[Any, ...]:
    source = _clean_text(record.get("source"))
    evidence_class = _normalize_evidence_class(record.get("evidence_class"))
    evidence_code = _clean_text(record.get("evidence_code")).upper()
    return (
        _source_order_rank(source),
        _evidence_class_order_rank(evidence_class),
        _relationship_type_order_rank(record.get("relationship_type")),
        -_safe_float(record.get("specificity_score")),
        -_safe_float((record.get("expression") or {}).get("value") if isinstance(record.get("expression"), dict) else None),
        _go_evidence_code_rank(evidence_code),
        _clean_text(record.get("gene")).upper(),
        _clean_text(record.get("source_record_id")),
    )


def _source_order_rank(source: str) -> int:
    return {
        "QuickGO GOA": 10,
        "Reactome ContentService": 20,
        "KEGG REST": 30,
        "ChEMBL": 40,
        "Human Protein Atlas": 50,
    }.get(source, 90)


def _relationship_type_order_rank(value: Any) -> int:
    return {
        "tissue_enriched_expression": 0,
        "cell_type_enriched_expression": 0,
        "tissue_group_enriched_expression": 10,
        "cell_type_group_enriched_expression": 10,
        "tissue_enhanced_expression": 20,
        "cell_type_enhanced_expression": 20,
    }.get(_normalize_relationship_type(value), 50)


def _evidence_class_order_rank(evidence_class: str) -> int:
    return {
        "experimental": 0,
        "curated_pathway_membership": 10,
        "compound_enzyme_gene_link": 20,
        "chembl_drug_mechanism_target": 25,
        "hpa_tissue_rna_specificity": 30,
        "hpa_single_cell_type_rna_specificity": 31,
        "curated_or_computational": 30,
        "unspecified": 90,
    }.get(evidence_class, 80)


def _go_evidence_code_rank(evidence_code: str) -> int:
    return {
        "EXP": 0,
        "IDA": 1,
        "IPI": 2,
        "IMP": 3,
        "IGI": 4,
        "IEP": 5,
        "HTP": 6,
        "HDA": 7,
        "HMP": 8,
        "HGI": 9,
        "HEP": 10,
        "TAS": 20,
        "NAS": 30,
        "ISS": 40,
        "ISO": 41,
        "ISA": 42,
        "ISM": 43,
        "IGC": 44,
        "IBA": 45,
        "IBD": 46,
        "IKR": 47,
        "IRD": 48,
        "RCA": 49,
        "IEA": 80,
    }.get(evidence_code, 50)


def _relationship_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_gene: dict[str, dict[str, Any]] = {}
    for record in records:
        gene = _clean_text(record.get("gene")).upper()
        if not gene:
            continue
        summary = by_gene.setdefault(
            gene,
            {
                "gene": gene,
                "record_count": 0,
                "sources": {},
                "relationship_types": {},
                "evidence_classes": {},
                "evidence_codes": {},
            },
        )
        summary["record_count"] += 1
        _increment(summary["sources"], _clean_text(record.get("source")) or "unknown")
        _increment(summary["relationship_types"], _normalize_relationship_type(record.get("relationship_type")) or "unknown")
        _increment(summary["evidence_classes"], _normalize_evidence_class(record.get("evidence_class")) or "unknown")
        _increment(summary["evidence_codes"], _clean_text(record.get("evidence_code")) or "unknown")
    genes = sorted(by_gene.values(), key=lambda item: (-int(item["record_count"]), item["gene"]))
    return {
        "total_records": len(records),
        "gene_count": len(genes),
        "genes": genes,
    }


def _increment(counter: dict[str, int], key: str) -> None:
    counter[key] = int(counter.get(key) or 0) + 1


def _source_local_ordering_policy() -> dict[str, Any]:
    return {
        "policy": "source_local_evidence_order",
        "description": "Records are ordered by source family, then evidence class, then source-local signal strength, then gene symbol. This is presentation order, not a selected answer.",
        "source_order": ["QuickGO GOA", "Reactome ContentService", "KEGG REST", "ChEMBL", "Human Protein Atlas"],
        "evidence_class_order": [
            "experimental",
            "curated_pathway_membership",
            "compound_enzyme_gene_link",
            "chembl_drug_mechanism_target",
            "hpa_tissue_rna_specificity",
            "hpa_single_cell_type_rna_specificity",
            "curated_or_computational",
            "unspecified",
        ],
    }


def _source_coverage(coverage_state: str, *, consulted: list[str], unavailable: list[dict[str, str]]) -> dict[str, Any]:
    consulted_unique = sorted(set(item for item in consulted if item))
    return {
        "coverage_state": coverage_state,
        "sources_consulted": consulted_unique,
        "sources_consulted_and_empty": consulted_unique if coverage_state == "in_scope_empty" else [],
        "sources_consulted_but_unavailable": unavailable,
        "sources_not_integrated": NOT_INTEGRATED_SOURCES,
    }


def _empty_response(
    *,
    coverage_state: str,
    status: str,
    query: dict[str, Any],
    empty_reason: str,
    resolved_entities: list[dict[str, Any]] | None = None,
    resolution_candidates: list[dict[str, Any]] | None = None,
    source_coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema": CONTROLLED_ENTITY_RELATIONSHIPS_SCHEMA_VERSION,
        "coverage_state": coverage_state,
        "status": status,
        "agent_decision_required": True,
        "query": query,
        "capability": _capability_contract(),
        "resolved_entities": resolved_entities or [],
        "resolution_candidates": resolution_candidates or [],
        "empty_reason": empty_reason,
        "source_coverage": source_coverage or _source_coverage(coverage_state, consulted=[], unavailable=[]),
    }


def _capability_contract() -> dict[str, Any]:
    return {
        "name": "controlled_entity_relationship_retrieval",
        "scope": "Retrieve curated biological-entity to gene relationship records from declared knowledge-graph sources.",
        "supported_entity_types": SUPPORTED_ENTITY_TYPES,
        "supported_sources": SUPPORTED_SOURCES,
        "unsupported_but_planned_source_families": NOT_INTEGRATED_SOURCES,
    }


def _query_payload(
    entity_name: str,
    entity_id: str,
    entity_type: str | None,
    sources: list[str],
    taxon_id: str | int | None,
    species: str | None,
    relationship_types: list[str] | None,
    evidence_classes: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "entity_name": entity_name,
        "entity_id": entity_id,
        "entity_type": entity_type,
        "sources": sources,
        "taxon_id": str(taxon_id or DEFAULT_TAXON_ID),
        "species": _clean_text(species) or DEFAULT_SPECIES,
        "relationship_types": [_normalize_relationship_type(item) for item in relationship_types or [] if _clean_text(item)],
        "evidence_classes": [_normalize_evidence_class(item) for item in evidence_classes or [] if _clean_text(item)],
    }
