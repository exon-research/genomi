from __future__ import annotations

import urllib.error
from typing import Any

from .constants import (
    CHEMBL_API_BASE,
    CONTROLLED_ENTITY_RELATIONSHIPS_SCHEMA_VERSION,
    DEFAULT_SPECIES,
    DEFAULT_TAXON_ID,
    HPA_API_BASE,
    HPA_TSV_DOWNLOAD_BASE,
    KEGG_REST_API_BASE,
    QUICKGO_API_BASE,
    REACTOME_CONTENT_SERVICE_BASE,
    SOURCE_BY_ENTITY_TYPE,
    SUPPORTED_ENTITY_TYPES,
    SUPPORTED_SOURCES,
)
from .helpers import (
    _candidate_label_matches,
    _clean_text,
    _entity_type_from_id,
    _fetch_bytes,
    _fetch_json,
    _fetch_text,
    _normalize_entity_type,
    _normalize_sources,
    _source_label,
)
from .ordering import (
    _capability_contract,
    _dedupe_records,
    _empty_response,
    _filter_records,
    _query_payload,
    _records_by_gene,
    _relationship_summary,
    _sort_records_source_local,
    _source_coverage,
    _source_local_ordering_policy,
)
from .sources import (
    _chembl_drug_gene_relationship_records,
    _chembl_molecule_by_id,
    _chembl_molecule_search,
    _goa_gene_relationship_records,
    _hpa_entity_search,
    _hpa_gene_relationship_records,
    _kegg_compound_by_id,
    _kegg_compound_search,
    _kegg_gene_relationship_records,
    _quickgo_search,
    _quickgo_term_by_id,
    _reactome_gene_relationship_records,
    _reactome_pathway_by_id,
    _reactome_search,
)


def retrieve_gene_relationships(
    *,
    entity_name: str | None = None,
    entity_id: str | None = None,
    entity_type: str | None = None,
    relationship_types: list[str] | None = None,
    evidence_classes: list[str] | None = None,
    sources: list[str] | None = None,
    taxon_id: str | int | None = DEFAULT_TAXON_ID,
    species: str | None = DEFAULT_SPECIES,
    limit: int = 100,
    quickgo_api_base: str = QUICKGO_API_BASE,
    reactome_api_base: str = REACTOME_CONTENT_SERVICE_BASE,
    kegg_api_base: str = KEGG_REST_API_BASE,
    hpa_api_base: str = HPA_API_BASE,
    hpa_download_base: str = HPA_TSV_DOWNLOAD_BASE,
    chembl_api_base: str = CHEMBL_API_BASE,
    fetch_json: Any | None = None,
    fetch_text: Any | None = None,
    fetch_bytes: Any | None = None,
) -> dict[str, Any]:
    query_name = _clean_text(entity_name)
    query_id = _clean_text(entity_id)
    query_type = _normalize_entity_type(entity_type)
    requested_sources = _normalize_sources(sources or [])
    if not query_name and not query_id:
        raise ValueError("controlled entity relationship retrieval requires entity_name or entity_id")
    if query_type and query_type not in SUPPORTED_ENTITY_TYPES:
        return _empty_response(
            coverage_state="out_of_scope_for_input",
            status="unsupported_entity_type",
            query=_query_payload(query_name, query_id, query_type, requested_sources, taxon_id, species, relationship_types, evidence_classes),
            empty_reason=f"Unsupported entity_type: {query_type}",
        )
    unsupported_sources = [source for source in requested_sources if source not in SUPPORTED_SOURCES]
    if unsupported_sources:
        return _empty_response(
            coverage_state="out_of_scope_for_input",
            status="unsupported_source",
            query=_query_payload(query_name, query_id, query_type, requested_sources, taxon_id, species, relationship_types, evidence_classes),
            empty_reason=f"Unsupported source(s): {', '.join(unsupported_sources)}",
        )

    inferred_type = query_type or _entity_type_from_id(query_id)
    if requested_sources and inferred_type:
        allowed_source = SOURCE_BY_ENTITY_TYPE.get(inferred_type)
        if allowed_source and allowed_source not in requested_sources:
            return _empty_response(
                coverage_state="out_of_scope_for_input",
                status="source_entity_type_mismatch",
                query=_query_payload(query_name, query_id, inferred_type, requested_sources, taxon_id, species, relationship_types, evidence_classes),
                empty_reason=f"Requested sources do not support entity_type {inferred_type}.",
            )

    json_fetcher = fetch_json or _fetch_json
    text_fetcher = fetch_text or _fetch_text
    bytes_fetcher = fetch_bytes or _fetch_bytes
    try:
        resolution = _resolve_entity(
            entity_name=query_name,
            entity_id=query_id,
            entity_type=inferred_type,
            sources=requested_sources,
            taxon_id=str(taxon_id or DEFAULT_TAXON_ID),
            species=_clean_text(species) or DEFAULT_SPECIES,
            quickgo_api_base=quickgo_api_base,
            reactome_api_base=reactome_api_base,
            kegg_api_base=kegg_api_base,
            hpa_download_base=hpa_download_base,
            chembl_api_base=chembl_api_base,
            fetch_json=json_fetcher,
            fetch_text=text_fetcher,
            fetch_bytes=bytes_fetcher,
        )
        if resolution["state"] != "resolved":
            return _empty_response(
                coverage_state="out_of_scope_for_input",
                status=resolution["state"],
                query=_query_payload(query_name, query_id, inferred_type, requested_sources, taxon_id, species, relationship_types, evidence_classes),
                empty_reason=resolution["reason"],
                resolved_entities=resolution.get("resolved_entities", []),
                resolution_candidates=resolution.get("candidates", []),
                source_coverage=_source_coverage(
                    "out_of_scope_for_input",
                    consulted=resolution.get("sources_consulted", []),
                    unavailable=resolution.get("sources_unavailable", []),
                ),
            )
        resolved_entities = resolution["resolved_entities"]
        records: list[dict[str, Any]] = []
        consulted: list[str] = []
        unavailable: list[dict[str, str]] = []
        return_limit = max(1, int(limit or 100))
        source_fetch_limit = max(return_limit, 100 if (relationship_types or evidence_classes) else return_limit)
        for resolved in resolved_entities:
            source = resolved["source"]
            consulted.append(_source_label(source))
            if source == "goa":
                records.extend(
                    _goa_gene_relationship_records(
                        resolved,
                        taxon_id=str(taxon_id or DEFAULT_TAXON_ID),
                        relationship_types=relationship_types or [],
                        quickgo_api_base=quickgo_api_base,
                        fetch_json=json_fetcher,
                        limit=source_fetch_limit,
                    )
                )
            elif source == "reactome":
                records.extend(
                    _reactome_gene_relationship_records(
                        resolved,
                        relationship_types=relationship_types or [],
                        reactome_api_base=reactome_api_base,
                        fetch_json=json_fetcher,
                        limit=source_fetch_limit,
                    )
                )
            elif source == "kegg":
                records.extend(
                    _kegg_gene_relationship_records(
                        resolved,
                        relationship_types=relationship_types or [],
                        kegg_api_base=kegg_api_base,
                        fetch_text=text_fetcher,
                        limit=source_fetch_limit,
                    )
                )
            elif source == "hpa":
                records.extend(
                    _hpa_gene_relationship_records(
                        resolved,
                        relationship_types=relationship_types or [],
                        hpa_api_base=hpa_api_base,
                        fetch_json=json_fetcher,
                        limit=max(source_fetch_limit, 500),
                    )
                )
            elif source == "chembl":
                records.extend(
                    _chembl_drug_gene_relationship_records(
                        resolved,
                        relationship_types=relationship_types or [],
                        chembl_api_base=chembl_api_base,
                        fetch_json=json_fetcher,
                        limit=source_fetch_limit,
                    )
                )
        records = _dedupe_records(records)
        records = _filter_records(records, relationship_types=relationship_types or [], evidence_classes=evidence_classes or [])
        records = _sort_records_source_local(records)
        records = records[:return_limit]
        coverage_state = "data_returned" if records else "in_scope_empty"
        relationship_summary = _relationship_summary(records)
        payload: dict[str, Any] = {
            "schema": CONTROLLED_ENTITY_RELATIONSHIPS_SCHEMA_VERSION,
            "coverage_state": coverage_state,
            "status": "gene_relationships_found" if records else "no_gene_relationship_records",
            "agent_decision_required": True,
            "query": _query_payload(query_name, query_id, inferred_type, requested_sources, taxon_id, species, relationship_types, evidence_classes),
            "capability": _capability_contract(),
            "resolved_entities": resolved_entities,
            "coverage": {
                "returned_record_count": len(records),
                "resolved_entity_count": len(resolved_entities),
                "supported_entity_types": SUPPORTED_ENTITY_TYPES,
                "supported_sources": SUPPORTED_SOURCES,
            },
            "source_coverage": _source_coverage(coverage_state, consulted=consulted, unavailable=unavailable),
            "telemetry": {
                "tool_family": "controlled_entity_relationships",
                "returned_answer": False,
                "agent_decision_required": True,
                "records_returned": len(records),
            },
        }
        if records:
            payload.update(
                {
                    "gene_relationship_records": records,
                    "records_by_gene": _records_by_gene(records),
                    "relationship_summary": relationship_summary,
                    "source_local_ordering": _source_local_ordering_policy(),
                }
            )
        else:
            payload["empty_reason"] = "Declared sources were queried for the resolved entity, but no records remained after source retrieval and requested filters."
        return payload
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, TypeError) as exc:
        return _empty_response(
            coverage_state="out_of_scope_for_input",
            status="source_unavailable",
            query=_query_payload(query_name, query_id, inferred_type, requested_sources, taxon_id, species, relationship_types, evidence_classes),
            empty_reason="A declared controlled-entity source was unavailable.",
            source_coverage=_source_coverage(
                "out_of_scope_for_input",
                consulted=[],
                unavailable=[{"source": "controlled entity relationship source", "error": str(exc)}],
            ),
        )


def _resolve_entity(
    *,
    entity_name: str,
    entity_id: str,
    entity_type: str | None,
    sources: list[str],
    taxon_id: str,
    species: str,
    quickgo_api_base: str,
    reactome_api_base: str,
    kegg_api_base: str,
    hpa_download_base: str,
    chembl_api_base: str,
    fetch_json: Any,
    fetch_text: Any,
    fetch_bytes: Any,
) -> dict[str, Any]:
    source = sources[0] if len(sources) == 1 else (SOURCE_BY_ENTITY_TYPE.get(entity_type or "") if entity_type else "")
    if entity_id:
        id_type = _entity_type_from_id(entity_id)
        if entity_type and id_type and entity_type != id_type:
            return {"state": "entity_type_mismatch", "reason": "entity_id prefix does not match entity_type.", "candidates": []}
        if (entity_type or id_type) == "drug":
            source = SOURCE_BY_ENTITY_TYPE["drug"]
            if sources and source not in sources:
                return {"state": "source_entity_type_mismatch", "reason": "Requested sources do not support entity_id.", "candidates": []}
            entity = _chembl_molecule_by_id(entity_id, chembl_api_base=chembl_api_base, fetch_json=fetch_json)
            if not entity:
                return {
                    "state": "entity_not_found",
                    "reason": "No ChEMBL molecule resolved the supplied entity_id.",
                    "candidates": [],
                    "sources_consulted": [_source_label(source)],
                }
            return {"state": "resolved", "resolved_entities": [entity], "sources_consulted": [_source_label(source)]}
        if not id_type:
            return {"state": "unsupported_entity_id", "reason": "entity_id is not a supported GO, Reactome, KEGG, or ChEMBL identifier.", "candidates": []}
        source = SOURCE_BY_ENTITY_TYPE[id_type]
        if sources and source not in sources:
            return {"state": "source_entity_type_mismatch", "reason": "Requested sources do not support entity_id.", "candidates": []}
        if id_type == "go_term":
            entity = _quickgo_term_by_id(entity_id, quickgo_api_base=quickgo_api_base, fetch_json=fetch_json)
        elif id_type == "pathway":
            entity = _reactome_pathway_by_id(entity_id, reactome_api_base=reactome_api_base, fetch_json=fetch_json)
        else:
            entity = _kegg_compound_by_id(entity_id, kegg_api_base=kegg_api_base, fetch_text=fetch_text)
        if not entity:
            return {
                "state": "entity_not_found",
                "reason": "No declared source resolved the supplied entity_id.",
                "candidates": [],
                "sources_consulted": [_source_label(source)],
            }
        return {"state": "resolved", "resolved_entities": [entity], "sources_consulted": [_source_label(source)]}

    if not entity_type and not source:
        return {
            "state": "entity_type_required",
            "reason": "Free-text entity_name requires entity_type or a single declared source to avoid cross-source entity ambiguity.",
            "candidates": [
                {"entity_type": key, "default_source": SOURCE_BY_ENTITY_TYPE[key], "scope": value}
                for key, value in sorted(SUPPORTED_ENTITY_TYPES.items())
            ],
            "sources_consulted": [],
        }

    resolved_source = source or SOURCE_BY_ENTITY_TYPE.get(entity_type or "")
    if not resolved_source:
        return {"state": "unsupported_entity_type", "reason": "Unsupported or missing entity_type.", "candidates": []}
    candidates = _search_entity_candidates(
        entity_name,
        resolved_source,
        entity_type=entity_type or "",
        taxon_id=taxon_id,
        species=species,
        quickgo_api_base=quickgo_api_base,
        reactome_api_base=reactome_api_base,
        kegg_api_base=kegg_api_base,
        hpa_download_base=hpa_download_base,
        chembl_api_base=chembl_api_base,
        fetch_json=fetch_json,
        fetch_text=fetch_text,
        fetch_bytes=fetch_bytes,
    )
    exact = [candidate for candidate in candidates if _candidate_label_matches(candidate, entity_name)]
    if len(exact) == 1:
        return {"state": "resolved", "resolved_entities": exact, "sources_consulted": [_source_label(resolved_source)]}
    if candidates:
        return {
            "state": "disambiguation_required",
            "reason": "The entity name did not exactly resolve to one controlled entity. Supply entity_id.",
            "candidates": candidates[:10],
            "sources_consulted": [_source_label(resolved_source)],
        }
    return {
        "state": "entity_not_found",
        "reason": "No declared source resolved the supplied entity_name.",
        "candidates": [],
        "sources_consulted": [_source_label(resolved_source)],
    }


def _search_entity_candidates(
    entity_name: str,
    source: str,
    *,
    entity_type: str,
    taxon_id: str,
    species: str,
    quickgo_api_base: str,
    reactome_api_base: str,
    kegg_api_base: str,
    hpa_download_base: str,
    chembl_api_base: str,
    fetch_json: Any,
    fetch_text: Any,
    fetch_bytes: Any,
) -> list[dict[str, Any]]:
    if source == "goa":
        return _quickgo_search(entity_name, quickgo_api_base=quickgo_api_base, fetch_json=fetch_json)
    if source == "reactome":
        return _reactome_search(entity_name, species=species, reactome_api_base=reactome_api_base, fetch_json=fetch_json)
    if source == "kegg":
        return _kegg_compound_search(entity_name, kegg_api_base=kegg_api_base, fetch_text=fetch_text)
    if source == "hpa":
        return _hpa_entity_search(entity_name, entity_type=entity_type, hpa_download_base=hpa_download_base, fetch_bytes=fetch_bytes)
    if source == "chembl":
        return _chembl_molecule_search(entity_name, chembl_api_base=chembl_api_base, fetch_json=fetch_json)
    return []
