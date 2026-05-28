from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import entity_relationships
from .constants import NOT_INTEGRATED_CELL_MARKER_SOURCES
from .helpers import (
    _cell_marker_source_label,
    _clean_text,
    _first_present,
    _normalise_label,
    _read_marker_table,
    _row_matches_species,
    _table_cell_type_value,
    _table_gene_value,
)
from .responses import (
    _cell_marker_empty,
    _cell_marker_response,
    _marker_from_hpa_record,
    _source_coverage,
)


def _retrieve_hpa_cell_type_markers(
    *,
    target: str,
    query: dict[str, Any],
    limit: int,
    hpa_api_base: str,
    hpa_download_base: str,
    fetch_json: Any,
    fetch_bytes: Any,
) -> dict[str, Any]:
    result = entity_relationships.retrieve_gene_relationships(
        entity_name=target,
        entity_type="cell_type",
        sources=["hpa"],
        limit=limit,
        hpa_api_base=hpa_api_base,
        hpa_download_base=hpa_download_base,
        fetch_json=fetch_json,
        fetch_bytes=fetch_bytes,
    )
    coverage_status = result.get("coverage_state") or result.get("coverage_status") or "out_of_scope_for_input"
    if coverage_status != "data_returned":
        return _cell_marker_empty(
            status=result.get("status") or "no_canonical_markers",
            coverage_status=coverage_status,
            query=query,
            empty_reason=result.get("empty_reason") or "HPA returned no cell-type marker records.",
            resolved_cell_types=result.get("resolved_entities") or [],
            resolution_candidates=result.get("resolution_candidates") or [],
            source_coverage=result.get("source_coverage"),
        )
    resolved = (result.get("resolved_entities") or [{}])[0]
    markers = [_marker_from_hpa_record(record, resolved) for record in result.get("gene_relationship_records") or [] if isinstance(record, dict)]
    return _cell_marker_response(
        status="canonical_markers_found" if markers else "no_canonical_markers",
        coverage_status="data_returned" if markers else "in_scope_empty",
        query=query,
        cell_type={
            "id": _clean_text(resolved.get("entity_id")),
            "name": _clean_text(resolved.get("name")),
            "parent_lineage": _clean_text(resolved.get("cell_type_group") or resolved.get("cell_type_class")),
            "source": "hpa",
            "version": "Human Protein Atlas current",
        },
        markers=markers,
        source_coverage=result.get("source_coverage"),
    )


def _retrieve_table_cell_type_markers(
    *,
    target: str,
    source_key: str,
    query: dict[str, Any],
    marker_table: Path,
    limit: int,
) -> dict[str, Any]:
    rows = _read_marker_table(marker_table)
    target_norm = _normalise_label(target)
    candidates: list[dict[str, str]] = []
    markers: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not _row_matches_species(row, query.get("species")):
            continue
        cell_type = _table_cell_type_value(row, source_key)
        gene = _table_gene_value(row, source_key)
        if not cell_type or not gene:
            continue
        if _normalise_label(cell_type) != target_norm:
            if target_norm and target_norm in _normalise_label(cell_type):
                candidates.append({"id": cell_type, "name": cell_type, "source": source_key})
            continue
        strength = _first_present(row, ["marker_strength", "strength", "specificity_score", "score", "avg_log2FC", "effect_size"])
        lineage = _first_present(row, ["lineage_context", "lineage", "parent_lineage", "tissue", "organ", "cell_type_group"])
        markers.append(
            {
                "gene_symbol": _clean_text(gene).upper(),
                "marker_strength": strength,
                "lineage_context": lineage,
                "source": _cell_marker_source_label(source_key),
                "source_evidence": {
                    "source": _cell_marker_source_label(source_key),
                    "source_record_id": _first_present(row, ["record_id", "id", "source_id"]) or f"{source_key}:{index + 1}",
                    "evidence_class": f"{source_key}_canonical_marker",
                    "reference": _first_present(row, ["reference", "source_url", "url", "pmid"]),
                },
            }
        )
        if len(markers) >= limit:
            break
    if markers:
        return _cell_marker_response(
            status="canonical_markers_found",
            coverage_status="data_returned",
            query=query,
            cell_type={
                "id": target,
                "name": target,
                "parent_lineage": markers[0].get("lineage_context") or "",
                "source": source_key,
                "version": f"{_cell_marker_source_label(source_key)} exported table",
            },
            markers=markers,
            source_coverage=_source_coverage(
                "data_returned",
                consulted=[_cell_marker_source_label(source_key)],
                unavailable=[],
                not_integrated=NOT_INTEGRATED_CELL_MARKER_SOURCES,
            ),
        )
    return _cell_marker_empty(
        status="cell_type_not_found" if candidates else "no_canonical_markers",
        coverage_status="out_of_scope_for_input" if candidates else "in_scope_empty",
        query=query,
        empty_reason=(
            "The marker table contained similar cell-type names but no exact controlled cell-type match."
            if candidates
            else "The supplied marker table was in scope but had no marker rows for this cell type."
        ),
        resolution_candidates=candidates[:10],
        source_coverage=_source_coverage(
            "out_of_scope_for_input" if candidates else "in_scope_empty",
            consulted=[_cell_marker_source_label(source_key)],
            unavailable=[],
            not_integrated=NOT_INTEGRATED_CELL_MARKER_SOURCES,
        ),
    )
