from __future__ import annotations

import urllib.error
import urllib.request
from collections.abc import Iterable
from typing import Any

from ....retrieval import semantic as retrieval_semantic

from ._base import (
    OPENTARGETS_DISEASE_SEARCH_LIMIT,
    OPENTARGETS_GRAPHQL_API_URL,
    _as_list,
    _clean_text,
    _clinical_stage_rank,
    _dedupe,
    _dedupe_dicts,
    _dedupe_records,
    _fetch_opentargets_graphql,
    _first_semantic_text,
    _normalize_gene,
    _normalize_genes,
    _normalize_terms,
    _record_digest,
)


def retrieve_disease_clinical_drug_targets(
    *,
    disease: str | None = None,
    disease_id: str | None = None,
    genes: Iterable[str] | None = None,
    mode: str = "records",
    minimum_clinical_stage: str = "PHASE_2",
    api_url: str = OPENTARGETS_GRAPHQL_API_URL,
    fetch_opentargets_graphql: Any | None = None,
    limit: int = 100,
    semantic_context: object = None,
) -> dict[str, Any]:
    semantic = retrieval_semantic.parse_semantic_context(semantic_context)
    disease_label = _clean_text(disease)
    efo_id = _clean_text(disease_id)
    candidate_genes = _normalize_genes(genes or [])
    if not disease_label:
        disease_label = _first_semantic_text(semantic, "disease", "condition", "trait_or_condition", "phenotype")
    if not disease_label and not efo_id:
        raise ValueError("phenotype.retrieve_disease_drug_targets requires disease or disease_id")
    disease_queries = _semantic_disease_queries(semantic, disease_label)
    mode = _normalize_retrieval_mode(mode)
    if mode == "gene_membership" and not candidate_genes:
        raise ValueError("phenotype.retrieve_disease_drug_targets mode='gene_membership' requires genes")
    fetch = fetch_opentargets_graphql or (lambda query, variables: _fetch_opentargets_graphql(api_url, query, variables))
    try:
        disease_hits = (
            [{"id": efo_id, "name": disease_label or efo_id, "score": None}]
            if efo_id
            else _first_disease_hits(fetch, disease_queries, limit=OPENTARGETS_DISEASE_SEARCH_LIMIT)
        )
        if not disease_hits:
            response = _disease_drug_target_response(
                disease=disease_label,
                disease_id=efo_id,
                candidate_genes=candidate_genes,
                minimum_clinical_stage=minimum_clinical_stage,
                mode=mode,
                status="disease_not_found",
                coverage_state="in_scope_empty",
                disease_hits=[],
                source_records=[],
                targets=[],
                gene_membership=[],
                source_coverage={
                    "sources_consulted_and_empty": ["Open Targets Platform disease search"],
                    "sources_consulted_but_unavailable": [],
                    "sources_not_integrated": ["DrugBank direct licensed target table", "ChEMBL direct REST mechanism table"],
                },
            )
            if semantic.has_hints:
                response["semantic_context"] = _disease_drug_target_semantic_usage(semantic, [], disease_label, candidate_genes)
            return response
        source_records: list[dict[str, Any]] = []
        queried_diseases: list[dict[str, Any]] = []
        raw_candidate_count = 0
        return_limit = max(1, int(limit or 100))
        internal_record_limit = None if mode == "gene_membership" else return_limit
        for hit in disease_hits[:1]:
            retrieval = _opentargets_disease_drug_target_records(
                fetch,
                disease_id=_clean_text(hit.get("id")),
                disease_name=_clean_text(hit.get("name") or disease_label),
                candidate_genes=candidate_genes,
                minimum_clinical_stage=minimum_clinical_stage,
                limit=internal_record_limit,
            )
            queried_diseases.append({"id": hit.get("id"), "name": hit.get("name"), "score": hit.get("score")})
            raw_candidate_count += int(retrieval.get("clinical_candidate_count") or 0)
            source_records.extend(record for record in retrieval.get("source_records", []) if isinstance(record, dict))
        targets = _group_disease_drug_targets(source_records, candidate_genes=candidate_genes, limit=return_limit)
        gene_membership = _gene_membership_rows(candidate_genes, source_records) if mode == "gene_membership" else []
        status = "completed" if targets else "no_clinical_drug_targets"
        coverage_state = "data_returned" if targets else "in_scope_empty"
        consulted_empty = [] if targets else ["Open Targets Platform disease drug and clinical candidates"]
        response = _disease_drug_target_response(
            disease=disease_label,
            disease_id=efo_id or _clean_text(queried_diseases[0].get("id") if queried_diseases else ""),
            candidate_genes=candidate_genes,
            minimum_clinical_stage=minimum_clinical_stage,
            mode=mode,
            status=status,
            coverage_state=coverage_state,
            disease_hits=queried_diseases,
            source_records=source_records[:return_limit],
            targets=targets,
            gene_membership=gene_membership,
            source_coverage={
                "sources_consulted_and_empty": consulted_empty,
                "sources_consulted_but_unavailable": [],
                "sources_not_integrated": ["DrugBank direct licensed target table", "ChEMBL direct REST mechanism table"],
            },
            raw_candidate_count=raw_candidate_count,
        )
        if semantic.has_hints:
            response["query"]["semantic_disease_queries"] = disease_queries
            response["semantic_context"] = _disease_drug_target_semantic_usage(semantic, source_records, disease_label, candidate_genes)
        return response
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, TypeError) as exc:
        response = _disease_drug_target_response(
            disease=disease_label,
            disease_id=efo_id,
            candidate_genes=candidate_genes,
            minimum_clinical_stage=minimum_clinical_stage,
            mode=mode,
            status="source_unavailable",
            coverage_state="out_of_scope_for_input",
            disease_hits=[],
            source_records=[],
            targets=[],
            gene_membership=[],
            source_coverage={
                "sources_consulted_and_empty": [],
                "sources_consulted_but_unavailable": [{"source": "Open Targets Platform disease drug and clinical candidates", "error": str(exc)}],
                "sources_not_integrated": ["DrugBank direct licensed target table", "ChEMBL direct REST mechanism table"],
            },
        )
        if semantic.has_hints:
            response["semantic_context"] = _disease_drug_target_semantic_usage(semantic, [], disease_label, candidate_genes)
        return response


def _opentargets_disease_search(fetch: Any, query_text: str, *, limit: int) -> list[dict[str, Any]]:
    payload = fetch(
        """
        query DiseaseSearch($query: String!, $size: Int!) {
          search(queryString: $query, entityNames: ["disease"], page: {index: 0, size: $size}) {
            hits { id name entity score }
          }
        }
        """,
        {"query": query_text, "size": max(1, int(limit or OPENTARGETS_DISEASE_SEARCH_LIMIT))},
    )
    hits = ((payload.get("data") or {}).get("search") or {}).get("hits") or []
    return [
        {
            "id": _clean_text(hit.get("id")),
            "name": _clean_text(hit.get("name")),
            "entity": _clean_text(hit.get("entity")),
            "score": hit.get("score"),
        }
        for hit in hits
        if isinstance(hit, dict) and _clean_text(hit.get("id"))
    ]


def _first_disease_hits(fetch: Any, queries: Iterable[str], *, limit: int) -> list[dict[str, Any]]:
    for query in queries:
        hits = _opentargets_disease_search(fetch, query, limit=limit)
        if hits:
            return hits
    return []


def _semantic_disease_queries(semantic: retrieval_semantic.SemanticContext, disease: str) -> list[str]:
    queries = retrieval_semantic.query_texts(
        semantic,
        raw_query=disease,
        entity_types=("disease", "condition", "trait_or_condition", "phenotype"),
        max_terms=8,
    )
    return [_clean_text(query) for query in queries if _clean_text(query)] or [disease]


def _semantic_drug_target_fields(semantic: retrieval_semantic.SemanticContext) -> dict[str, str]:
    return {
        "drug": _first_semantic_text(semantic, "drug", "medication"),
        "drug_class": _first_semantic_text(semantic, "drug_class", "medication_class"),
        "indication": _first_semantic_text(semantic, "indication", "condition", "disease", "phenotype", "trait_or_condition"),
        "mechanism": _first_semantic_text(semantic, "mechanism", "target_relationship", "drug_target"),
    }


def _record_context_values(records: Iterable[dict[str, Any]]) -> list[str]:
    values: list[str] = []
    for record in records:
        for key in ("drugs", "drug_classes", "indications", "mechanisms", "genes"):
            values.extend(str(item) for item in (record.get(key) or []) if str(item or "").strip())
    return _normalize_terms(values)


def _disease_drug_target_semantic_usage(
    semantic: retrieval_semantic.SemanticContext,
    records: Iterable[dict[str, Any]],
    disease: str,
    genes: Iterable[str],
) -> dict[str, Any]:
    return retrieval_semantic.term_usage_payload(
        semantic,
        term_matches=retrieval_semantic.matched_terms(
            semantic,
            [*_record_context_values(records), disease],
            match_type="matched_open_targets_disease_or_drug_target_record",
            source="Open Targets Platform",
        ),
        streams=retrieval_semantic.retrieval_streams(
            raw_query=semantic.raw_query,
            host_terms=retrieval_semantic.search_terms(semantic),
            exact_ids=genes,
            source_native_filters=[disease],
        ),
    )


def _opentargets_disease_drug_target_records(
    fetch: Any,
    *,
    disease_id: str,
    disease_name: str,
    candidate_genes: list[str],
    minimum_clinical_stage: str,
    limit: int | None,
) -> dict[str, Any]:
    payload = fetch(
        """
        query DiseaseClinicalDrugTargets($diseaseId: String!) {
          disease(efoId: $diseaseId) {
            id
            name
            drugAndClinicalCandidates {
              count
              rows {
                id
                maxClinicalStage
                drug {
                  id
                  name
                  drugType
                  maximumClinicalStage
                  mechanismsOfAction {
                    rows {
                      mechanismOfAction
                      actionType
                      targetName
                      targets { id approvedSymbol approvedName }
                      references { source ids urls }
                    }
                  }
                }
                clinicalReports {
                  source
                  clinicalStage
                  phaseFromSource
                  trialPhase
                  trialOverallStatus
                  url
                  title
                }
              }
            }
          }
        }
        """,
        {"diseaseId": disease_id},
    )
    disease = (payload.get("data") or {}).get("disease") or {}
    disease_label = _clean_text(disease.get("name") or disease_name)
    rows = ((disease.get("drugAndClinicalCandidates") or {}).get("rows") or []) if isinstance(disease, dict) else []
    records: list[dict[str, Any]] = []
    minimum_rank = _clinical_stage_rank(minimum_clinical_stage)
    for row in rows:
        if not isinstance(row, dict):
            continue
        stage = _clean_text(row.get("maxClinicalStage"))
        if minimum_rank and _clinical_stage_rank(stage) < minimum_rank:
            continue
        drug = row.get("drug") if isinstance(row.get("drug"), dict) else {}
        drug_name = _clean_text((drug or {}).get("name"))
        drug_id = _clean_text((drug or {}).get("id"))
        moa_rows = (((drug or {}).get("mechanismsOfAction") or {}).get("rows") or []) if isinstance(drug, dict) else []
        report = _representative_clinical_report(row.get("clinicalReports") or [])
        for moa in moa_rows:
            if not isinstance(moa, dict):
                continue
            mechanism = _clean_text(moa.get("mechanismOfAction"))
            action_type = _clean_text(moa.get("actionType"))
            target_name = _clean_text(moa.get("targetName"))
            references = _reference_urls(moa.get("references") or [])
            for target in moa.get("targets") or []:
                if not isinstance(target, dict):
                    continue
                symbol = _normalize_gene(target.get("approvedSymbol"))
                if not symbol:
                    continue
                if candidate_genes and symbol not in candidate_genes:
                    continue
                source_text = (
                    f"Open Targets Platform links {drug_name} for {disease_label} to {symbol} "
                    f"via {mechanism or target_name}; stage={stage}; action={action_type}."
                )
                records.append(
                    {
                        "record_id": f"opentargets:clinical-drug-target:{disease_id}:{drug_id}:{symbol}:{_record_digest({'moa': mechanism, 'action': action_type})[:8]}",
                        "source_id": "opentargets",
                        "source_type": "clinical drug target",
                        "source_title": "Open Targets Platform disease drug and clinical candidates",
                        "source_url": f"https://platform.opentargets.org/disease/{disease_id}/drug",
                        "gene": symbol,
                        "genes": [symbol],
                        "disease": disease_label,
                        "condition": disease_label,
                        "indication": disease_label,
                        "drug": drug_name,
                        "drugs": [drug_name],
                        "drug_id": drug_id,
                        "drug_type": _clean_text((drug or {}).get("drugType")),
                        "mechanism": mechanism,
                        "mechanisms": [mechanism] if mechanism else [],
                        "action_type": action_type,
                        "target_name": target_name,
                        "max_clinical_stage": stage,
                        "clinical_stage_rank": _clinical_stage_rank(stage),
                        "clinical_report": report,
                        "references": references,
                        "finding": source_text,
                        "finding_type": "clinical_drug_target",
                        "verified_fields": {
                            "genes": [symbol],
                            "drugs": [drug_name] if drug_name else [],
                            "indications": [disease_label] if disease_label else [],
                            "mechanisms": [mechanism] if mechanism else [],
                            "target_relationships": ["clinical drug target", action_type, mechanism],
                        },
                        "support_spans": [
                            {"field": "gene", "value": symbol, "source_text": source_text},
                            {"field": "drug", "value": drug_name, "source_text": source_text},
                            {"field": "indication", "value": disease_label, "source_text": source_text},
                            {"field": "mechanism", "value": mechanism, "source_text": source_text},
                        ],
                        "target": {
                            "gene": symbol,
                            "ensembl_id": _clean_text(target.get("id")),
                            "approved_name": _clean_text(target.get("approvedName")),
                        },
                    }
                )
                if limit is not None and len(records) >= limit:
                    return {
                        "clinical_candidate_count": (disease.get("drugAndClinicalCandidates") or {}).get("count", len(rows)),
                        "source_records": _dedupe_records(records),
                    }
    return {
        "clinical_candidate_count": (disease.get("drugAndClinicalCandidates") or {}).get("count", len(rows)),
        "source_records": _dedupe_records(records),
    }


def _group_disease_drug_targets(
    source_records: list[dict[str, Any]],
    *,
    candidate_genes: list[str],
    limit: int,
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for record in source_records:
        gene = _normalize_gene(record.get("gene"))
        if not gene:
            continue
        item = grouped.setdefault(
            gene,
            {
                "gene": gene,
                "ensembl_id": _clean_text((record.get("target") or {}).get("ensembl_id")),
                "approved_name": _clean_text((record.get("target") or {}).get("approved_name")),
                "candidate_match": gene in candidate_genes if candidate_genes else None,
                "max_clinical_stage": _clean_text(record.get("max_clinical_stage")),
                "clinical_stage_rank": _clinical_stage_rank(record.get("max_clinical_stage")),
                "drug_count": 0,
                "mechanism_count": 0,
                "clinical_report_count": 0,
                "drugs": [],
                "mechanisms": [],
                "source_record_ids": [],
            },
        )
        if _clinical_stage_rank(record.get("max_clinical_stage")) > int(item.get("clinical_stage_rank") or 0):
            item["max_clinical_stage"] = _clean_text(record.get("max_clinical_stage"))
            item["clinical_stage_rank"] = _clinical_stage_rank(record.get("max_clinical_stage"))
        drug = {
            "drug": _clean_text(record.get("drug")),
            "drug_id": _clean_text(record.get("drug_id")),
            "drug_type": _clean_text(record.get("drug_type")),
            "max_clinical_stage": _clean_text(record.get("max_clinical_stage")),
            "clinical_stage_rank": _clinical_stage_rank(record.get("max_clinical_stage")),
        }
        if drug["drug"]:
            item["drugs"] = _dedupe_dicts([*item["drugs"], drug], key_fields=("drug_id", "drug"))
        mechanism = {
            "mechanism": _clean_text(record.get("mechanism")),
            "action_type": _clean_text(record.get("action_type")),
            "target_name": _clean_text(record.get("target_name")),
        }
        if mechanism["mechanism"] or mechanism["target_name"]:
            item["mechanisms"] = _dedupe_dicts([*item["mechanisms"], mechanism], key_fields=("mechanism", "action_type", "target_name"))
        if record.get("clinical_report"):
            item["clinical_report_count"] = int(item.get("clinical_report_count") or 0) + 1
        item["source_record_ids"] = _dedupe([*item["source_record_ids"], _clean_text(record.get("record_id"))])
        item["drug_count"] = len(item["drugs"])
        item["mechanism_count"] = len(item["mechanisms"])
    return sorted(
        grouped.values(),
        key=lambda item: (
            -int(item.get("clinical_stage_rank") or 0),
            -int(item.get("drug_count") or 0),
            str(item.get("gene") or ""),
        ),
    )[:limit]


def _gene_membership_rows(candidate_genes: list[str], source_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records_by_gene: dict[str, list[dict[str, Any]]] = {}
    for record in source_records:
        gene = _normalize_gene(record.get("gene"))
        if gene:
            records_by_gene.setdefault(gene, []).append(record)
    rows: list[dict[str, Any]] = []
    for gene in candidate_genes:
        records = records_by_gene.get(gene, [])
        stage = _highest_stage(records)
        rows.append(
            {
                "gene_symbol": gene,
                "is_clinical_target": bool(records),
                "highest_phase": stage,
                "evidence_record_count": len(records),
                "source_record_ids": [_clean_text(record.get("record_id")) for record in records if _clean_text(record.get("record_id"))],
            }
        )
    return rows


def _highest_stage(records: list[dict[str, Any]]) -> str:
    if not records:
        return ""
    best = max(records, key=lambda record: _clinical_stage_rank(record.get("max_clinical_stage")))
    return _clean_text(best.get("max_clinical_stage"))


def _disease_drug_target_response(
    *,
    disease: str,
    disease_id: str,
    candidate_genes: list[str],
    minimum_clinical_stage: str,
    mode: str,
    status: str,
    coverage_state: str,
    disease_hits: list[dict[str, Any]],
    source_records: list[dict[str, Any]],
    targets: list[dict[str, Any]],
    gene_membership: list[dict[str, Any]] | None = None,
    source_coverage: dict[str, Any],
    raw_candidate_count: int = 0,
) -> dict[str, Any]:
    return {
        "status": status,
        "mode": mode,
        "coverage_state": coverage_state,
        "agent_decision_required": True,
        "query": {
            "disease": disease,
            "disease_id": disease_id,
            "candidate_genes": candidate_genes,
            "minimum_clinical_stage": minimum_clinical_stage,
            "mode": mode,
        },
        "disease_hits": disease_hits,
        "targets": targets,
        "targets_by_gene": {target["gene"]: target for target in targets},
        "gene_membership": gene_membership or [],
        "source_records": source_records,
        "coverage": {
            "source": "Open Targets Platform disease drug and clinical candidates",
            "disease_hits": len(disease_hits),
            "raw_clinical_candidate_count": raw_candidate_count,
            "source_record_count": len(source_records),
            "target_count": len(targets),
            "gene_membership_count": len(gene_membership or []),
        },
        "source_coverage": source_coverage,
        "decision_boundary": (
            "This operation retrieves disease-scoped clinical drug-target evidence from declared sources. "
            "It does not select a causal gene, infer treatment efficacy, or ingest agent-located evidence."
        ),
        "telemetry": {
            "tool_family": "clinical_drug_target",
            "returned_answer": False,
            "agent_decision_required": True,
            "records_examined": len(source_records),
            "candidate_records_found": len(targets),
        },
    }


def _normalize_retrieval_mode(mode: Any) -> str:
    text = _clean_text(mode or "records").lower().replace("-", "_")
    if text in {"", "records", "record", "targets", "target_records", "standard"}:
        return "records"
    if text == "gene_membership":
        return "gene_membership"
    raise ValueError("mode must be 'records' or 'gene_membership'")


def _representative_clinical_report(reports: Iterable[Any]) -> dict[str, Any] | None:
    normalized = [
        {
            "source": _clean_text(report.get("source")),
            "clinical_stage": _clean_text(report.get("clinicalStage") or report.get("trialPhase") or report.get("phaseFromSource")),
            "status": _clean_text(report.get("trialOverallStatus")),
            "url": _clean_text(report.get("url")),
            "title": _clean_text(report.get("title")),
        }
        for report in reports
        if isinstance(report, dict)
    ]
    if not normalized:
        return None
    return sorted(normalized, key=lambda item: (-_clinical_stage_rank(item.get("clinical_stage")), item.get("source", ""), item.get("title", "")))[0]


def _reference_urls(references: Iterable[Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for reference in references:
        if not isinstance(reference, dict):
            continue
        output.append(
            {
                "source": _clean_text(reference.get("source")),
                "ids": _dedupe([str(item) for item in _as_list(reference.get("ids"))]),
                "urls": _dedupe([str(item) for item in _as_list(reference.get("urls"))]),
            }
        )
    return _dedupe_dicts(output, key_fields=("source", "ids", "urls"))
