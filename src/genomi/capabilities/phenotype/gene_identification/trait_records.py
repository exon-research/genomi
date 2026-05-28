from __future__ import annotations

import urllib.error
import urllib.request
from collections.abc import Iterable
from typing import Any

from ....retrieval import semantic as retrieval_semantic
from .. import targets

from ._base import (
    OPENTARGETS_GRAPHQL_API_URL,
    OPENTARGETS_TRAIT_TARGET_LIMIT,
    TRAIT_CAUSAL_ASSOCIATION_ONLY_TERMS,
    TRAIT_CAUSAL_DIRECT_SOURCES,
    TRAIT_CAUSAL_DIRECT_TERMS,
    TRAIT_GENE_RECORDS_SCHEMA_VERSION,
    _clean_text,
    _contains_any,
    _dedupe_by_key,
    _dedupe_dicts,
    _fetch_opentargets_graphql,
    _meaningful_tokens,
    _normalize_genes,
    _record_gene_values,
)


def retrieve_trait_gene_records(
    *,
    trait: str | None = None,
    genes: Iterable[str] | None = None,
    use_opentargets: bool = True,
    opentargets_api_url: str = OPENTARGETS_GRAPHQL_API_URL,
    fetch_opentargets_graphql: Any | None = None,
    limit: int = 25,
    semantic_context: object = None,
) -> dict[str, Any]:
    query_trait = _clean_text(trait)
    normalized_genes = _normalize_genes(genes or [])
    if not query_trait:
        raise ValueError("phenotype.retrieve_trait_gene_records requires trait")
    semantic = retrieval_semantic.parse_semantic_context(semantic_context)
    trait_queries = _semantic_trait_queries(semantic, query_trait)

    native_retrieval = _combined_opentargets_trait_targets(
        trait_queries,
        normalized_genes,
        api_url=opentargets_api_url,
        limit=max(limit, OPENTARGETS_TRAIT_TARGET_LIMIT),
        enabled=use_opentargets,
        fetch_graphql=fetch_opentargets_graphql,
    )
    native_records = [
        _normalize_trait_causal_source_record(record, source="opentargets_platform")
        for record in native_retrieval.get("records", [])
        if isinstance(record, dict)
    ]
    clinical_drug_target_retrieval = _combined_clinical_drug_target_records(
        trait_queries,
        normalized_genes,
        api_url=opentargets_api_url,
        fetch_graphql=fetch_opentargets_graphql,
        limit=max(1, int(limit or 25)),
        enabled=use_opentargets,
    )
    clinical_drug_target_records = [
        _normalize_trait_causal_source_record(record, source="opentargets_clinical_drug_targets")
        for record in clinical_drug_target_retrieval.get("source_records", [])
        if isinstance(record, dict)
    ]

    source_record_rows = _dedupe_trait_causal_records([*clinical_drug_target_records, *native_records])
    matched_records: list[dict[str, Any]] = []
    for record in source_record_rows:
        matched_gene = _candidate_gene_for_trait_record(record, normalized_genes) if normalized_genes else _gene_for_trait_record(record)
        if matched_gene is None:
            continue
        trait_match = _trait_match_detail_any(record, trait_queries)
        if not trait_match["matches"]:
            continue
        classified = _classify_trait_causal_record(record)
        matched_records.append(
            {
                **record,
                "gene": matched_gene,
                "evidence_regime": classified["evidence_regime"],
                "evidence_strength": classified["evidence_strength"],
                "matched_trait_terms": trait_match["matched_terms"],
                "matched_trait_query": trait_match.get("query"),
                "why_record_matters": classified["why_record_matters"],
                "limitations": classified["limitations"],
            }
        )

    result_genes = normalized_genes or sorted({record["gene"] for record in matched_records if record.get("gene")})
    gene_records = [_trait_gene_record_row(gene, matched_records) for gene in result_genes]
    direct_count = sum(row["direct_record_count"] for row in gene_records)
    association_count = sum(row["association_record_count"] for row in gene_records)
    if matched_records:
        status = "trait_gene_records_found"
        coverage_state = "data_returned"
        evidence_state = "trait_gene_records_observed" if direct_count else "association_only_not_causal"
    else:
        status = "no_trait_gene_records"
        coverage_state = "in_scope_empty"
        evidence_state = "no_evidence_in_genomi"
    source_coverage = {
        "sources_consulted_and_empty": [],
        "sources_consulted_but_unavailable": [],
        "sources_not_integrated": [
            "GeneCards trait-gene summaries",
            "OMIM/Orphanet trait-to-gene curation",
            "PubMed/NCBI Gene curation-density retrieval",
        ],
    }
    if native_retrieval.get("status") == "searched_empty":
        source_coverage["sources_consulted_and_empty"].append("Open Targets Platform target-disease associations")
    if native_retrieval.get("status") == "unavailable":
        source_coverage["sources_consulted_but_unavailable"].append(
            {"source": "Open Targets Platform target-disease associations", "error": native_retrieval.get("error")}
        )
    if native_retrieval.get("status") == "not_requested":
        source_coverage["sources_not_integrated"].append("Open Targets Platform target-disease associations")
    if clinical_drug_target_retrieval.get("status") in {"no_clinical_drug_targets", "disease_not_found"}:
        source_coverage["sources_consulted_and_empty"].append("Open Targets Platform disease drug and clinical candidates")
    if clinical_drug_target_retrieval.get("status") == "source_unavailable":
        unavailable = clinical_drug_target_retrieval.get("source_coverage", {}).get("sources_consulted_but_unavailable") or []
        source_coverage["sources_consulted_but_unavailable"].append(
            {"source": "Open Targets Platform disease drug and clinical candidates", "error": unavailable[0].get("error") if unavailable and isinstance(unavailable[0], dict) else None}
        )
    if clinical_drug_target_retrieval.get("status") == "not_requested":
        source_coverage["sources_not_integrated"].append("Open Targets Platform disease drug and clinical candidates")
    result = {
        "status": status,
        "agent_decision_required": True,
        "coverage_state": coverage_state,
        "evidence_state": evidence_state,
        "schema": TRAIT_GENE_RECORDS_SCHEMA_VERSION,
        "query": {
            "trait": query_trait,
            "genes_filter": normalized_genes,
            "semantic_trait_queries": trait_queries if semantic.has_hints else [],
        },
        "gene_records": gene_records,
        "records_by_gene": {row["gene"]: row for row in gene_records},
        "source_records": matched_records[:limit],
        "comparison_inputs": {
            "phenotype": query_trait,
            "genes": result_genes,
            "source_records": [
                _trait_causal_record_for_comparison(record)
                for record in matched_records
                if record.get("evidence_regime") == "curated_mechanism_or_target"
            ][:limit],
        },
        "coverage": {
            "records_examined": len(source_record_rows),
            "records_matching_trait_and_gene_filter": len(matched_records),
            "direct_record_count": direct_count,
            "association_record_count": association_count,
            "native_retrieval": {
                "source": "Open Targets Platform",
                "status": native_retrieval.get("status"),
                "record_count": len(native_records),
                "disease_hits": native_retrieval.get("disease_hits", []),
            },
            "clinical_drug_target_retrieval": {
                "source": "Open Targets Platform disease drug and clinical candidates",
                "status": clinical_drug_target_retrieval.get("status"),
                "record_count": len(clinical_drug_target_records),
                "disease_hits": clinical_drug_target_retrieval.get("disease_hits", []),
            },
        },
        "source_coverage": source_coverage,
        "warnings": _trait_gene_records_warnings(status),
        "decision_boundary": (
            "This operation retrieves native trait-to-gene records from declared public sources. "
            "The host agent decides how those records apply."
        ),
        "telemetry": {
            "tool_family": "candidate_gene",
            "returned_answer": False,
            "agent_decision_required": True,
            "records_examined": len(source_record_rows),
            "candidate_records_found": len(matched_records),
        },
    }
    if semantic.has_hints:
        result["semantic_context"] = retrieval_semantic.term_usage_payload(
            semantic,
            term_matches=retrieval_semantic.matched_terms(
                semantic,
                [record.get("matched_trait_query") for record in matched_records],
                match_type="matched_open_targets_trait_or_disease_record",
                source="Open Targets Platform",
            ),
            streams=retrieval_semantic.retrieval_streams(
                raw_query=semantic.raw_query,
                host_terms=retrieval_semantic.search_terms(semantic),
                exact_ids=normalized_genes,
                source_native_filters=[query_trait],
            ),
        )
    return result


def _combined_opentargets_trait_targets(
    traits: Iterable[str],
    genes: list[str],
    *,
    api_url: str,
    limit: int,
    enabled: bool,
    fetch_graphql: Any | None = None,
) -> dict[str, Any]:
    if not enabled:
        return {"status": "not_requested", "records": [], "disease_hits": [], "error": None}
    records: list[dict[str, Any]] = []
    disease_hits: list[dict[str, Any]] = []
    errors: list[str] = []
    searched_empty = False
    for trait in traits:
        result = _retrieve_opentargets_trait_targets(
            trait,
            genes,
            api_url=api_url,
            limit=limit,
            enabled=enabled,
            fetch_graphql=fetch_graphql,
        )
        records.extend(record for record in result.get("records", []) if isinstance(record, dict))
        disease_hits.extend(hit for hit in result.get("disease_hits", []) if isinstance(hit, dict))
        if result.get("status") == "searched_empty":
            searched_empty = True
        if result.get("status") == "unavailable" and result.get("error"):
            errors.append(str(result.get("error")))
    status = "completed" if records else ("unavailable" if errors and not searched_empty else "searched_empty")
    return {
        "status": status,
        "records": _dedupe_by_key(records, ("record_id", "gene", "condition")),
        "disease_hits": _dedupe_dicts(disease_hits, ("id", "name")),
        "error": "; ".join(errors) if errors else None,
    }


def _combined_clinical_drug_target_records(
    traits: Iterable[str],
    genes: list[str],
    *,
    api_url: str,
    fetch_graphql: Any | None,
    limit: int,
    enabled: bool,
) -> dict[str, Any]:
    if not enabled:
        return {"status": "not_requested", "source_records": [], "coverage_state": "out_of_scope_for_input", "disease_hits": []}
    records: list[dict[str, Any]] = []
    hits: list[dict[str, Any]] = []
    statuses: list[str] = []
    coverage_state = "in_scope_empty"
    for trait in traits:
        result = targets.retrieve_disease_clinical_drug_targets(
            disease=trait,
            genes=genes or None,
            minimum_clinical_stage="PHASE_2",
            api_url=api_url,
            fetch_opentargets_graphql=fetch_graphql,
            limit=limit,
        )
        statuses.append(str(result.get("status") or ""))
        if result.get("coverage_state") == "data_returned":
            coverage_state = "data_returned"
        records.extend(record for record in result.get("source_records", []) if isinstance(record, dict))
        hits.extend(hit for hit in result.get("disease_hits", []) if isinstance(hit, dict))
    status = "completed" if records else ("source_unavailable" if "source_unavailable" in statuses else "no_clinical_drug_targets")
    return {
        "status": status,
        "source_records": _dedupe_by_key(records, ("record_id", "gene", "condition")),
        "coverage_state": coverage_state,
        "disease_hits": _dedupe_dicts(hits, ("id", "name")),
    }


def _retrieve_opentargets_trait_targets(
    trait: str,
    genes: list[str],
    *,
    api_url: str,
    limit: int,
    enabled: bool,
    fetch_graphql: Any | None = None,
) -> dict[str, Any]:
    if not enabled:
        return {"status": "not_requested", "records": [], "disease_hits": [], "error": None}
    if not trait:
        return {"status": "not_applicable", "records": [], "disease_hits": [], "error": None}
    fetch = fetch_graphql or (lambda query, variables: _fetch_opentargets_graphql(api_url, query, variables))
    try:
        search_payload = fetch(
            """
            query SearchDiseases($queryString: String!) {
              search(queryString: $queryString, entityNames: ["disease"]) {
                hits { id name entity }
              }
            }
            """,
            {"queryString": trait},
        )
        hits = [
            hit
            for hit in (((search_payload.get("data") or {}).get("search") or {}).get("hits") or [])
            if isinstance(hit, dict) and hit.get("id") and str(hit.get("entity") or "").casefold() == "disease"
        ][:5]
        records: list[dict[str, Any]] = []
        for hit in hits:
            association_payload = fetch(
                """
                query AssociatedTargets($efoId: String!, $size: Int!) {
                  disease(efoId: $efoId) {
                    id
                    name
                    associatedTargets(page: {index: 0, size: $size}) {
                      rows {
                        score
                        target { id approvedSymbol approvedName }
                      }
                    }
                  }
                }
                """,
                {"efoId": hit["id"], "size": min(max(1, int(limit or OPENTARGETS_TRAIT_TARGET_LIMIT)), 500)},
            )
            disease = (association_payload.get("data") or {}).get("disease") or {}
            rows = ((disease.get("associatedTargets") or {}).get("rows") or []) if isinstance(disease, dict) else []
            for row in rows:
                target = row.get("target") if isinstance(row, dict) else {}
                symbol = _clean_text((target or {}).get("approvedSymbol")).upper()
                if not symbol or (genes and symbol not in genes):
                    continue
                score = row.get("score")
                disease_name = _clean_text(disease.get("name") or hit.get("name") or trait)
                disease_id = _clean_text(disease.get("id") or hit.get("id"))
                records.append(
                    {
                        "record_id": f"opentargets:{disease_id}:{symbol}",
                        "source_id": "opentargets",
                        "source_type": "target-disease association",
                        "source_title": "Open Targets Platform target-disease association",
                        "source_url": f"https://platform.opentargets.org/disease/{disease_id}/associations",
                        "gene": symbol,
                        "condition": disease_name,
                        "trait": trait,
                        "finding": (
                            f"Open Targets Platform target-disease association links {symbol} to {disease_name} "
                            f"with association score {score}."
                        ),
                        "finding_type": "target_disease_association",
                        "verified_fields": {
                            "genes": [symbol],
                            "conditions": [disease_name],
                            "traits": [trait],
                            "disease_ids": [disease_id],
                        },
                        "support_spans": [
                            {
                                "field": "target_disease_association",
                                "value": symbol,
                                "source_text": f"{symbol} associated with {disease_name}; score={score}",
                            }
                        ],
                        "association_score": score,
                        "target": {
                            "gene": symbol,
                            "ensembl_id": (target or {}).get("id"),
                            "approved_name": (target or {}).get("approvedName"),
                        },
                    }
                )
        return {
            "status": "completed" if records else "searched_empty",
            "records": _dedupe_by_key(records, ("record_id", "gene", "condition")),
            "disease_hits": [{"id": hit.get("id"), "name": hit.get("name")} for hit in hits],
            "error": None,
        }
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, TypeError) as exc:
        return {"status": "unavailable", "records": [], "disease_hits": [], "error": str(exc)}


def _normalize_trait_causal_source_record(record: dict[str, Any], *, source: str) -> dict[str, Any]:
    source_info = record.get("source") if isinstance(record.get("source"), dict) else {}
    finding_info = record.get("finding") if isinstance(record.get("finding"), dict) else {}
    target_info = record.get("target") if isinstance(record.get("target"), dict) else {}
    verified_fields = record.get("verified_fields") if isinstance(record.get("verified_fields"), dict) else {}
    support_spans = record.get("support_spans") if isinstance(record.get("support_spans"), list) else record.get("support_span")
    return {
        "record_id": _clean_text(
            record.get("record_id")
            or record.get("finding_id")
            or record.get("source_id")
            or record.get("association_id")
            or record.get("id")
        ),
        "record_origin": source,
        "source_id": _clean_text(record.get("source_id") or source_info.get("source_id")),
        "source_type": _clean_text(record.get("source_type") or source_info.get("type") or record.get("evidence_type")),
        "source_title": _clean_text(record.get("source_title") or source_info.get("title")),
        "source_url": _clean_text(record.get("source_url") or source_info.get("url")),
        "gene": _clean_text(record.get("gene") or target_info.get("gene")),
        "trait": _clean_text(record.get("trait") or record.get("phenotype") or record.get("condition") or target_info.get("condition") or target_info.get("topic")),
        "finding": _clean_text(finding_info.get("text") or finding_info.get("summary") or record.get("finding") or record.get("summary") or record.get("description")),
        "finding_type": _clean_text(record.get("finding_type") or finding_info.get("type")),
        "verified_fields": verified_fields,
        "support_spans": support_spans if support_spans is not None else [],
        "raw_record": record,
    }


def _dedupe_trait_causal_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        key = "|".join(
            _clean_text(record.get(field)).casefold()
            for field in ("record_id", "source_id", "source_url", "gene", "finding")
        )
        if not key.strip("|"):
            key = str(id(record))
        if key in seen:
            continue
        seen.add(key)
        output.append(record)
    return output


def _candidate_gene_for_trait_record(record: dict[str, Any], genes: list[str]) -> str | None:
    gene_values = _normalize_genes(
        [
            record.get("gene"),
            *_record_gene_values(record.get("verified_fields") if isinstance(record.get("verified_fields"), dict) else {}),
            *_record_gene_values(record.get("raw_record") if isinstance(record.get("raw_record"), dict) else {}),
        ]
    )
    text = _trait_causal_record_text(record).casefold()
    for gene in genes:
        if gene in gene_values or gene.casefold() in text:
            return gene
    return None


def _gene_for_trait_record(record: dict[str, Any]) -> str | None:
    gene_values = _normalize_genes(
        [
            record.get("gene"),
            *_record_gene_values(record.get("verified_fields") if isinstance(record.get("verified_fields"), dict) else {}),
            *_record_gene_values(record.get("raw_record") if isinstance(record.get("raw_record"), dict) else {}),
        ]
    )
    return gene_values[0] if gene_values else None


def _semantic_trait_queries(semantic: retrieval_semantic.SemanticContext, trait: str) -> list[str]:
    queries = retrieval_semantic.query_texts(
        semantic,
        raw_query=trait,
        entity_types=("trait", "phenotype", "condition", "trait_or_condition", "disease"),
        max_terms=8,
    )
    return [_clean_text(query) for query in queries if _clean_text(query)] or [trait]


def _trait_match_detail_any(record: dict[str, Any], traits: Iterable[str]) -> dict[str, Any]:
    best = {"matches": False, "matched_terms": [], "query": None}
    for trait in traits:
        match = _trait_match_detail(record, trait)
        if not match["matches"]:
            continue
        if len(match["matched_terms"]) > len(best["matched_terms"]):
            best = {**match, "query": trait}
    return best


def _trait_match_detail(record: dict[str, Any], trait: str) -> dict[str, Any]:
    trait_tokens = _meaningful_tokens(trait)
    if not trait_tokens:
        return {"matches": False, "matched_terms": []}
    text = _trait_causal_record_text(record).casefold()
    matched = [token for token in trait_tokens if token in text]
    return {
        "matches": bool(matched) and (len(matched) >= min(2, len(trait_tokens)) or trait.casefold() in text),
        "matched_terms": matched,
    }


def _classify_trait_causal_record(record: dict[str, Any]) -> dict[str, Any]:
    text = _trait_causal_record_text(record).casefold()
    direct = _contains_any(text, TRAIT_CAUSAL_DIRECT_TERMS)
    association_only = _contains_any(text, TRAIT_CAUSAL_ASSOCIATION_ONLY_TERMS)
    direct_source = _contains_any(text, TRAIT_CAUSAL_DIRECT_SOURCES)
    if direct:
        return {
            "evidence_regime": "curated_mechanism_or_target",
            "evidence_strength": "medium",
            "why_record_matters": _trait_causal_record_reasons(record, direct=direct, direct_source=direct_source),
            "limitations": ["Direct-source evidence still needs host-agent interpretation against the exact question wording."],
        }
    if association_only:
        return {
            "evidence_regime": "association_only_not_causal",
            "evidence_strength": "low",
            "why_record_matters": ["record links the candidate to the trait only through association or locus gene-field evidence"],
            "limitations": ["Association, mapped-gene, reported-gene, nearest-gene, or locus evidence is not a causal-gene answer."],
        }
    return {
        "evidence_regime": "context_only",
        "evidence_strength": "low",
        "why_record_matters": ["record mentions the candidate and trait but does not state causal, mechanism, target, or canonical-gene support"],
        "limitations": ["Context-only co-mention should not select the causal gene."],
    }


def _trait_causal_record_reasons(record: dict[str, Any], *, direct: bool, direct_source: bool) -> list[str]:
    reasons: list[str] = []
    if direct:
        reasons.append("record text names causal, effector, mechanism, target, or canonical-gene support")
    if direct_source:
        reasons.append("record source is a curated target, mechanism, disease-gene, or reviewed literature source")
    if not reasons:
        reasons.append("record matched trait and candidate")
    return reasons


def _trait_gene_record_row(gene: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    gene_records = [record for record in records if record.get("gene") == gene]
    direct_records = [record for record in gene_records if record.get("evidence_regime") == "curated_mechanism_or_target"]
    association_records = [record for record in gene_records if record.get("evidence_regime") == "association_only_not_causal"]
    context_records = [record for record in gene_records if record.get("evidence_regime") == "context_only"]
    return {
        "gene": gene,
        "direct_record_count": len(direct_records),
        "association_record_count": len(association_records),
        "context_only_record_count": len(context_records),
        "strongest_evidence_regime": (
            "curated_mechanism_or_target"
            if direct_records
            else "association_only_not_causal"
            if association_records
            else "context_only"
            if context_records
            else "no_matching_records"
        ),
        "records": [*_compact_trait_causal_records(direct_records), *_compact_trait_causal_records(association_records), *_compact_trait_causal_records(context_records)],
    }


def _compact_trait_causal_records(records: list[dict[str, Any]], *, limit: int = 5) -> list[dict[str, Any]]:
    return [
        {
            "record_id": record.get("record_id"),
            "source_id": record.get("source_id"),
            "source_type": record.get("source_type"),
            "source_title": record.get("source_title"),
            "source_url": record.get("source_url"),
            "evidence_regime": record.get("evidence_regime"),
            "evidence_strength": record.get("evidence_strength"),
            "finding": record.get("finding"),
            "matched_trait_terms": record.get("matched_trait_terms") or [],
            "why_record_matters": record.get("why_record_matters") or [],
            "limitations": record.get("limitations") or [],
            "support_spans": record.get("support_spans") or [],
        }
        for record in records[:limit]
    ]


def _trait_causal_record_for_comparison(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "record_id": record.get("record_id"),
        "source_id": record.get("source_id") or record.get("source_title"),
        "source_type": record.get("source_type") or "trait causal/mechanism evidence",
        "source_title": record.get("source_title"),
        "source_url": record.get("source_url"),
        "gene": record.get("gene"),
        "condition": record.get("trait"),
        "finding": record.get("finding"),
        "verified_fields": record.get("verified_fields") or {},
        "support_spans": record.get("support_spans") or [],
        "evidence_regime": record.get("evidence_regime"),
    }


def _trait_gene_records_warnings(status: str) -> list[str]:
    if status == "trait_gene_records_found":
        return ["Trait-to-gene records were found in integrated sources; inspect evidence regimes before deciding how to use them."]
    return ["No native trait-to-gene records were found in integrated sources."]


def _trait_causal_record_text(record: dict[str, Any]) -> str:
    verified_fields = record.get("verified_fields") if isinstance(record.get("verified_fields"), dict) else {}
    support_spans = record.get("support_spans")
    if isinstance(support_spans, list):
        support_text = " ".join(_clean_text(item) for item in support_spans)
    else:
        support_text = _clean_text(support_spans)
    raw = record.get("raw_record") if isinstance(record.get("raw_record"), dict) else {}
    return " ".join(
        _clean_text(value)
        for value in (
            record.get("source_id"),
            record.get("source_type"),
            record.get("source_title"),
            record.get("gene"),
            record.get("trait"),
            record.get("finding"),
            record.get("finding_type"),
            support_text,
            verified_fields,
            raw.get("source_id"),
            raw.get("source_type"),
            raw.get("evidence_type"),
            raw.get("method"),
            raw,
        )
    )
