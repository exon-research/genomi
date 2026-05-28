from __future__ import annotations

from typing import Any

from .constants import (
    CELL_TYPE_MARKERS_SCHEMA_VERSION,
    NOT_INTEGRATED_CELL_MARKER_SOURCES,
    NOT_INTEGRATED_PATHWAY_SOURCES,
    NOT_INTEGRATED_REGION_SOURCES,
    PATHWAY_MEMBER_GENES_SCHEMA_VERSION,
    REGION_FEATURE_ANNOTATION_SCHEMA_VERSION,
    SUPPORTED_CELL_MARKER_SOURCES,
    SUPPORTED_PATHWAY_SOURCES,
    SUPPORTED_REGION_ASSEMBLIES,
)
from .helpers import (
    _cell_marker_source_label,
    _clean_text,
    _is_reactome_id,
    _normalise_label,
    _normalize_kegg_pathway_id,
    _normalize_source,
    _pathway_source_label,
)


def _pathway_response(
    *,
    status: str,
    coverage_status: str,
    query: dict[str, Any],
    pathway: dict[str, Any],
    members: list[dict[str, Any]],
    source_coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema": PATHWAY_MEMBER_GENES_SCHEMA_VERSION,
        "coverage_status": coverage_status,
        "coverage_state": coverage_status,
        "status": status,
        "agent_decision_required": True,
        "query": query,
        "capability": _pathway_capability_contract(),
        "pathway": pathway,
        "members": _dedupe_members(members),
        "coverage": {
            "returned_member_count": len(_dedupe_members(members)),
            "source": pathway.get("source"),
        },
        "source_coverage": source_coverage
        or _source_coverage(coverage_status, consulted=[_pathway_source_label(pathway.get("source"))], unavailable=[], not_integrated=NOT_INTEGRATED_PATHWAY_SOURCES),
    }


def _pathway_empty(
    *,
    status: str,
    coverage_status: str,
    query: dict[str, Any],
    empty_reason: str,
    resolved_pathways: list[dict[str, Any]] | None = None,
    resolution_candidates: list[dict[str, Any]] | None = None,
    source_coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema": PATHWAY_MEMBER_GENES_SCHEMA_VERSION,
        "coverage_status": coverage_status,
        "coverage_state": coverage_status,
        "status": status,
        "agent_decision_required": True,
        "query": query,
        "capability": _pathway_capability_contract(),
        "resolved_pathways": resolved_pathways or [],
        "resolution_candidates": resolution_candidates or [],
        "empty_reason": empty_reason,
        "source_coverage": source_coverage
        or _source_coverage(coverage_status, consulted=[], unavailable=[], not_integrated=NOT_INTEGRATED_PATHWAY_SOURCES),
    }


def _cell_marker_response(
    *,
    status: str,
    coverage_status: str,
    query: dict[str, Any],
    cell_type: dict[str, Any],
    markers: list[dict[str, Any]],
    source_coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    deduped = _dedupe_markers(markers)
    return {
        "schema": CELL_TYPE_MARKERS_SCHEMA_VERSION,
        "coverage_status": coverage_status,
        "coverage_state": coverage_status,
        "status": status,
        "agent_decision_required": True,
        "query": query,
        "capability": _cell_marker_capability_contract(),
        "cell_type": cell_type,
        "markers": deduped,
        "coverage": {
            "returned_marker_count": len(deduped),
            "source": cell_type.get("source"),
        },
        "source_coverage": source_coverage
        or _source_coverage(coverage_status, consulted=[_cell_marker_source_label(cell_type.get("source"))], unavailable=[], not_integrated=NOT_INTEGRATED_CELL_MARKER_SOURCES),
    }


def _cell_marker_empty(
    *,
    status: str,
    coverage_status: str,
    query: dict[str, Any],
    empty_reason: str,
    resolved_cell_types: list[dict[str, Any]] | None = None,
    resolution_candidates: list[dict[str, Any]] | None = None,
    source_coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema": CELL_TYPE_MARKERS_SCHEMA_VERSION,
        "coverage_status": coverage_status,
        "coverage_state": coverage_status,
        "status": status,
        "agent_decision_required": True,
        "query": query,
        "capability": _cell_marker_capability_contract(),
        "resolved_cell_types": resolved_cell_types or [],
        "resolution_candidates": resolution_candidates or [],
        "empty_reason": empty_reason,
        "source_coverage": source_coverage
        or _source_coverage(coverage_status, consulted=[], unavailable=[], not_integrated=NOT_INTEGRATED_CELL_MARKER_SOURCES),
    }


def _region_empty(*, status: str, coverage_status: str, query: dict[str, Any], empty_reason: str, source_coverage: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "schema": REGION_FEATURE_ANNOTATION_SCHEMA_VERSION,
        "coverage_status": coverage_status,
        "coverage_state": coverage_status,
        "status": status,
        "agent_decision_required": True,
        "query": query,
        "capability": _region_capability_contract(),
        "features": [],
        "classification": {
            "dominant_feature_class": "",
            "distance_to_nearest_TSS": None,
            "nearest_tss_gene": "",
            "nearest_tss_feature_id": "",
            "nearest_tss_position": None,
        },
        "empty_reason": empty_reason,
        "source_coverage": source_coverage
        or _source_coverage(coverage_status, consulted=[], unavailable=[], not_integrated=NOT_INTEGRATED_REGION_SOURCES),
    }


def _library_install_response(
    *,
    schema: str,
    query: dict[str, Any],
    capability: dict[str, Any],
    library: str,
    intent: str,
    operation: str,
    source_label: str,
    not_integrated: list[str],
    additional_missing_libraries: list[str] | None = None,
) -> dict[str, Any]:
    from ....runtime.library_status import library_install_request, library_status

    request = library_install_request(library, intent=intent, operation=operation)
    extra_libraries = [library_status(name) for name in (additional_missing_libraries or [])]
    payload: dict[str, Any] = {
        **request,
        "schema": schema,
        "coverage_status": "out_of_scope_for_input",
        "coverage_state": "out_of_scope_for_input",
        "agent_decision_required": True,
        "query": query,
        "capability": capability,
        "source_coverage": _source_coverage(
            "out_of_scope_for_input",
            consulted=[],
            unavailable=[{"source": source_label, "error": f"{library} library is not installed"}],
            not_integrated=not_integrated,
        ),
        "additional_missing_libraries": extra_libraries,
    }
    if schema == PATHWAY_MEMBER_GENES_SCHEMA_VERSION:
        payload.update({"members": [], "resolved_pathways": [], "resolution_candidates": []})
    elif schema == CELL_TYPE_MARKERS_SCHEMA_VERSION:
        payload.update({"markers": [], "resolved_cell_types": [], "resolution_candidates": []})
    elif schema == REGION_FEATURE_ANNOTATION_SCHEMA_VERSION:
        payload.update(
            {
                "features": [],
                "classification": {
                    "dominant_feature_class": "",
                    "distance_to_nearest_TSS": None,
                    "nearest_tss_gene": "",
                    "nearest_tss_feature_id": "",
                    "nearest_tss_position": None,
                },
            }
        )
    return payload


def _pathway_capability_contract() -> dict[str, Any]:
    return {
        "name": "pathway.retrieve_members",
        "scope": "Retrieve canonical member genes for controlled pathway or gene-set entities from declared sources.",
        "supported_sources": SUPPORTED_PATHWAY_SOURCES,
        "out_of_scope": ["free-text pathway descriptions", "ad-hoc literature-derived sets", "user-defined modules"],
    }


def _cell_marker_capability_contract() -> dict[str, Any]:
    return {
        "name": "cell_type.retrieve_markers",
        "scope": "Retrieve canonical marker genes for controlled cell-type entities from declared marker sources.",
        "supported_sources": SUPPORTED_CELL_MARKER_SOURCES,
        "out_of_scope": ["free-text cell-state descriptions", "unannotated cluster IDs", "hypothetical cell types"],
    }


def _region_capability_contract() -> dict[str, Any]:
    return {
        "name": "region.retrieve_features",
        "scope": "Classify GRCh37/GRCh38 genomic intervals against supplied GENCODE transcript features and ENCODE cCRE records.",
        "supported_assemblies": list(SUPPORTED_REGION_ASSEMBLIES.values()),
        "supported_sources": {"gencode_gtf": "GENCODE transcript annotation", "encode_ccre_bed": "ENCODE candidate cis-regulatory elements"},
        "out_of_scope": NOT_INTEGRATED_REGION_SOURCES,
    }


def _source_coverage(coverage_status: str, *, consulted: list[str], unavailable: list[dict[str, str]], not_integrated: list[str]) -> dict[str, Any]:
    consulted_unique = sorted(set(item for item in consulted if item))
    return {
        "coverage_status": coverage_status,
        "coverage_state": coverage_status,
        "sources_consulted": consulted_unique,
        "sources_consulted_and_empty": consulted_unique if coverage_status == "in_scope_empty" else [],
        "sources_consulted_but_unavailable": unavailable,
        "sources_not_integrated": not_integrated,
    }


def _pathway_source_for_target(target: str, source: str) -> str:
    if source:
        return source if source in SUPPORTED_PATHWAY_SOURCES else "unsupported"
    if _is_reactome_id(target):
        return "reactome"
    if _normalize_kegg_pathway_id(target):
        return "kegg"
    if _normalise_label(target).startswith("hallmark") or _clean_text(target).upper().startswith("HALLMARK_"):
        return "msigdb_hallmark"
    return "source_required"


def _pathway_source_candidates() -> list[dict[str, str]]:
    return [{"source": key, "scope": value} for key, value in SUPPORTED_PATHWAY_SOURCES.items()]


def _member_from_relationship_record(record: dict[str, Any], *, source: str) -> dict[str, Any]:
    return {
        "gene_symbol": _clean_text(record.get("gene")).upper(),
        "ensembl_id": _clean_text(record.get("ensembl_id")),
        "source_evidence": {
            "source": source,
            "source_record_id": _clean_text(record.get("source_record_id")),
            "relationship_type": _clean_text(record.get("relationship_type")) or "pathway_member",
            "evidence_class": _clean_text(record.get("evidence_class")),
            "reference": _clean_text(record.get("reference")),
        },
    }


def _marker_from_hpa_record(record: dict[str, Any], resolved: dict[str, Any]) -> dict[str, Any]:
    expression = record.get("expression") if isinstance(record.get("expression"), dict) else {}
    return {
        "gene_symbol": _clean_text(record.get("gene")).upper(),
        "marker_strength": {
            "specificity": _clean_text(record.get("specificity") or record.get("evidence_code")),
            "specificity_score": record.get("specificity_score"),
            "expression_value": expression.get("value"),
            "expression_unit": expression.get("unit"),
        },
        "lineage_context": _clean_text(resolved.get("cell_type_group") or resolved.get("cell_type_class")),
        "source": "Human Protein Atlas",
        "source_evidence": {
            "source": "Human Protein Atlas",
            "source_record_id": _clean_text(record.get("source_record_id")),
            "evidence_class": _clean_text(record.get("evidence_class")),
            "relationship_type": _clean_text(record.get("relationship_type")),
            "reference": _clean_text(record.get("reference")),
        },
    }


def _dedupe_members(members: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    deduped = []
    for member in members:
        gene = _clean_text(member.get("gene_symbol")).upper()
        if not gene or gene in seen:
            continue
        seen.add(gene)
        deduped.append({**member, "gene_symbol": gene})
    return deduped


def _dedupe_markers(markers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    deduped = []
    for marker in markers:
        gene = _clean_text(marker.get("gene_symbol")).upper()
        if not gene or gene in seen:
            continue
        seen.add(gene)
        deduped.append({**marker, "gene_symbol": gene})
    return deduped
