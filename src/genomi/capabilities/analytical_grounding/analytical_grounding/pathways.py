from __future__ import annotations

import urllib.parse
from pathlib import Path
from typing import Any

from .. import entity_relationships
from .constants import (
    NOT_INTEGRATED_PATHWAY_SOURCES,
    PATHWAY_MEMBER_GENES_SCHEMA_VERSION,
)
from .helpers import (
    _clean_text,
    _is_reactome_id,
    _kegg_gene_symbol,
    _normalise_label,
    _normalize_kegg_pathway_id,
    _parse_kegg_flat_entry,
    _parse_kegg_links,
    _parse_kegg_pathway_find,
    _parse_gmt,
    _url,
)
from .responses import (
    _library_install_response,
    _member_from_relationship_record,
    _pathway_capability_contract,
    _pathway_empty,
    _pathway_response,
    _source_coverage,
)


def _retrieve_reactome_pathway_members(
    *,
    target: str,
    query: dict[str, Any],
    limit: int,
    reactome_api_base: str,
    fetch_json: Any,
) -> dict[str, Any]:
    is_id = _is_reactome_id(target)
    relationship_result = entity_relationships.retrieve_gene_relationships(
        entity_id=target if is_id else None,
        entity_name=None if is_id else target,
        entity_type="pathway",
        sources=["reactome"],
        limit=limit,
        reactome_api_base=reactome_api_base,
        fetch_json=fetch_json,
    )
    coverage_status = relationship_result.get("coverage_state") or relationship_result.get("coverage_status") or "out_of_scope_for_input"
    if coverage_status != "data_returned":
        return _pathway_empty(
            status=relationship_result.get("status") or "no_pathway_members",
            coverage_status=coverage_status,
            query=query,
            empty_reason=relationship_result.get("empty_reason") or "Reactome returned no pathway participant records.",
            resolved_pathways=relationship_result.get("resolved_entities") or [],
            resolution_candidates=relationship_result.get("resolution_candidates") or [],
            source_coverage=relationship_result.get("source_coverage"),
        )
    resolved = (relationship_result.get("resolved_entities") or [{}])[0]
    members = [
        _member_from_relationship_record(record, source="Reactome ContentService")
        for record in relationship_result.get("gene_relationship_records") or []
        if isinstance(record, dict)
    ]
    return _pathway_response(
        status="pathway_members_found" if members else "no_pathway_members",
        coverage_status="data_returned" if members else "in_scope_empty",
        query=query,
        pathway={
            "id": _clean_text(resolved.get("entity_id")),
            "name": _clean_text(resolved.get("name")),
            "source": "reactome",
            "version": "Reactome ContentService current",
        },
        members=members,
        source_coverage=relationship_result.get("source_coverage"),
    )


def _retrieve_kegg_pathway_members(
    *,
    target: str,
    query: dict[str, Any],
    limit: int,
    kegg_api_base: str,
    fetch_text: Any,
) -> dict[str, Any]:
    resolved = _resolve_kegg_pathway(target, kegg_api_base=kegg_api_base, fetch_text=fetch_text)
    if resolved["state"] != "resolved":
        return _pathway_empty(
            status=resolved["state"],
            coverage_status="out_of_scope_for_input",
            query=query,
            empty_reason=resolved["reason"],
            resolution_candidates=resolved.get("candidates", []),
            source_coverage=_source_coverage(
                "out_of_scope_for_input",
                consulted=["KEGG REST"],
                unavailable=[],
                not_integrated=NOT_INTEGRATED_PATHWAY_SOURCES,
            ),
        )
    pathway = resolved["pathway"]
    link_text = fetch_text(_url(kegg_api_base, f"/link/hsa/{urllib.parse.quote(pathway['id'], safe=':')}", {}))
    members: list[dict[str, Any]] = []
    for _, gene_ref in _parse_kegg_links(link_text):
        gene_ref = _clean_text(gene_ref)
        if not gene_ref.startswith("hsa:"):
            continue
        gene_entry = _parse_kegg_flat_entry(fetch_text(_url(kegg_api_base, f"/get/{urllib.parse.quote(gene_ref, safe=':')}", {})))
        gene_symbol = _kegg_gene_symbol(gene_entry, gene_ref)
        if not gene_symbol:
            continue
        members.append(
            {
                "gene_symbol": gene_symbol,
                "ensembl_id": "",
                "source_evidence": {
                    "source": "KEGG REST",
                    "source_record_id": f"{pathway['id']}|{gene_ref}",
                    "relationship_type": "pathway_member",
                    "evidence_class": "kegg_pathway_membership",
                    "reference": f"https://www.kegg.jp/entry/{pathway['id']}+{gene_ref}",
                },
            }
        )
        if len(members) >= limit:
            break
    return _pathway_response(
        status="pathway_members_found" if members else "no_pathway_members",
        coverage_status="data_returned" if members else "in_scope_empty",
        query=query,
        pathway=pathway,
        members=members,
        source_coverage=_source_coverage(
            "data_returned" if members else "in_scope_empty",
            consulted=["KEGG REST"],
            unavailable=[],
            not_integrated=NOT_INTEGRATED_PATHWAY_SOURCES,
        ),
    )


def _retrieve_msigdb_hallmark_members(
    *,
    target: str,
    query: dict[str, Any],
    limit: int,
    gmt_path: str | Path | None,
    gmt_url: str | None,
    version: str | None,
    fetch_text: Any,
) -> dict[str, Any]:
    if not gmt_path and not gmt_url:
        return _library_install_response(
            schema=PATHWAY_MEMBER_GENES_SCHEMA_VERSION,
            query=query,
            capability=_pathway_capability_contract(),
            library="msigdb-hallmark",
            intent=f"MSigDB Hallmark member-gene lookup for {target}",
            operation="pathway.retrieve_members",
            source_label="MSigDB Hallmark GMT",
            not_integrated=NOT_INTEGRATED_PATHWAY_SOURCES,
        )
    text = Path(gmt_path).read_text(encoding="utf-8") if gmt_path else fetch_text(str(gmt_url))
    target_norm = _normalise_label(target.replace("HALLMARK_", ""))
    candidates = []
    for row in _parse_gmt(text):
        set_name = _clean_text(row.get("name"))
        if not set_name.startswith("HALLMARK_"):
            continue
        if _normalise_label(set_name.replace("HALLMARK_", "")) == target_norm or _normalise_label(set_name) == _normalise_label(target):
            genes = [_clean_text(gene).upper() for gene in row.get("genes", []) if _clean_text(gene)]
            members = [
                {
                    "gene_symbol": gene,
                    "ensembl_id": "",
                    "source_evidence": {
                        "source": "MSigDB Hallmark",
                        "source_record_id": set_name,
                        "relationship_type": "gene_set_member",
                        "evidence_class": "msigdb_hallmark_membership",
                        "reference": _clean_text(row.get("description")),
                    },
                }
                for gene in genes[:limit]
            ]
            return _pathway_response(
                status="pathway_members_found" if members else "no_pathway_members",
                coverage_status="data_returned" if members else "in_scope_empty",
                query=query,
                pathway={
                    "id": set_name,
                    "name": set_name,
                    "source": "msigdb_hallmark",
                    "version": _clean_text(version) or "MSigDB Hallmark GMT",
                },
                members=members,
                source_coverage=_source_coverage(
                    "data_returned" if members else "in_scope_empty",
                    consulted=["MSigDB Hallmark GMT"],
                    unavailable=[],
                    not_integrated=NOT_INTEGRATED_PATHWAY_SOURCES,
                ),
            )
        candidates.append({"id": set_name, "name": set_name, "source": "msigdb_hallmark"})
    return _pathway_empty(
        status="pathway_not_found",
        coverage_status="out_of_scope_for_input",
        query=query,
        empty_reason="No Hallmark gene set in the supplied MSigDB GMT matched the requested identifier or name.",
        resolution_candidates=candidates[:10],
        source_coverage=_source_coverage(
            "out_of_scope_for_input",
            consulted=["MSigDB Hallmark GMT"],
            unavailable=[],
            not_integrated=NOT_INTEGRATED_PATHWAY_SOURCES,
        ),
    )


def _resolve_kegg_pathway(target: str, *, kegg_api_base: str, fetch_text: Any) -> dict[str, Any]:
    pathway_id = _normalize_kegg_pathway_id(target)
    if pathway_id:
        entry = _parse_kegg_flat_entry(fetch_text(_url(kegg_api_base, f"/get/{urllib.parse.quote(pathway_id, safe=':')}", {})))
        names = entry.get("NAME") or []
        if not names:
            return {"state": "pathway_not_found", "reason": "No KEGG PATHWAY record resolved the supplied pathway_id.", "candidates": []}
        return {"state": "resolved", "pathway": {"id": pathway_id, "name": names[0], "source": "kegg", "version": "KEGG REST current"}}
    text = fetch_text(_url(kegg_api_base, f"/find/pathway/{urllib.parse.quote(target, safe='')}", {}))
    candidates = _parse_kegg_pathway_find(text)
    exact = [candidate for candidate in candidates if _normalise_label(candidate["name"].split(" - ", 1)[0]) == _normalise_label(target)]
    if len(exact) == 1:
        return {"state": "resolved", "pathway": exact[0]}
    if candidates:
        return {
            "state": "disambiguation_required",
            "reason": "The pathway name did not exactly resolve to one KEGG PATHWAY record. Supply pathway_id.",
            "candidates": candidates[:10],
        }
    return {"state": "pathway_not_found", "reason": "No KEGG PATHWAY record resolved the supplied pathway name.", "candidates": []}
