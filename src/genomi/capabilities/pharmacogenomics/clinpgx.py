from __future__ import annotations

import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Any

from ...evidence import envelope as _env
from ...runtime.external import utc_now
from ...runtime.libraries import manager as library_manager

_CLINPGX_LIBRARY = library_manager.get("clinpgx")
CLINPGX_API_URL = _CLINPGX_LIBRARY.source.api_base or ""
CLINPGX_SWAGGER_URL = _CLINPGX_LIBRARY.source.urls[0]
CLINPGX_DATA_USAGE_POLICY_URL = _CLINPGX_LIBRARY.source.urls[1]
CLINPGX_TIMEOUT_SECONDS = 20
CLINPGX_MAX_LIMIT = 25
CLINPGX_MAX_RAW_LIST_ITEMS = 10
CLINPGX_MAX_RAW_TEXT_CHARS = 600
CLINPGX_MAX_TEXT_CHARS = 1600


def lookup_clinpgx(
    *,
    drug: str | None = None,
    gene: str | None = None,
    rsid: str | None = None,
    chemical_id: str | None = None,
    gene_id: str | None = None,
    variant_id: str | None = None,
    guideline_source: str | None = "all",
    include_clinical_annotations: bool = True,
    include_labels: bool = True,
    include_raw_records: bool = False,
    limit: int = 10,
    api_url: str | None = None,
) -> dict[str, Any]:
    """Fetch traceable ClinPGx PGx guideline, annotation, and label context."""

    base_url = _base_url(api_url)
    limit = _bounded_limit(limit)
    requested_source = _guideline_source(guideline_source)
    target = {
        "drug": _clean(drug),
        "gene": _normalize_gene(gene),
        "rsid": _normalize_rsid(rsid),
        "chemical_id": _clean(chemical_id),
        "gene_id": _clean(gene_id),
        "variant_id": _clean(variant_id),
        "guideline_source": requested_source,
    }
    raw_calls: list[dict[str, Any]] = []
    if not any(target[key] for key in ("drug", "gene", "rsid", "chemical_id", "gene_id", "variant_id")):
        return _empty_result(
            base_url,
            target,
            status="invalid_target",
            raw_calls=raw_calls,
            missing_inputs=["drug", "gene", "rsid", "chemical_id", "gene_id", "variant_id"],
        )

    resolved = _resolve_target_ids(base_url, target, raw_calls=raw_calls)
    guideline_records = _fetch_guideline_annotations(
        base_url,
        resolved=resolved,
        source=requested_source,
        raw_calls=raw_calls,
        limit=limit,
        include_raw_records=include_raw_records,
    )
    clinical_annotations: list[dict[str, Any]] = []
    if include_clinical_annotations:
        clinical_annotations = _fetch_clinical_annotations(
            base_url,
            target=target,
            raw_calls=raw_calls,
            limit=limit,
            include_raw_records=include_raw_records,
        )
    label_annotations: list[dict[str, Any]] = []
    if include_labels:
        label_annotations = _fetch_label_annotations(
            base_url,
            target=target,
            resolved=resolved,
            raw_calls=raw_calls,
            limit=limit,
            include_raw_records=include_raw_records,
        )

    source = _source_metadata(base_url)
    record_payloads = _record_research_payloads(
        guideline_records=guideline_records,
        clinical_annotations=clinical_annotations,
        label_annotations=label_annotations,
        source=source,
        target=target,
    )
    status = "completed"
    if not guideline_records and not clinical_annotations and not label_annotations:
        status = "source_unavailable" if _raw_call_errors(raw_calls) else "no_matching_clinpgx_records"

    result = {
        "ok": status in {"completed", "no_matching_clinpgx_records"},
        "status": status,
        "source": source,
        "query": target,
        "resolved": resolved,
        "guideline_annotations": guideline_records,
        "clinical_annotations": clinical_annotations,
        "label_annotations": label_annotations,
        "sample_follow_up_targets": _sample_follow_up_targets(
            guideline_records=guideline_records,
            clinical_annotations=clinical_annotations,
            label_annotations=label_annotations,
            query=target,
        ),
        "record_research_payloads": record_payloads,
        "clinical_verification": _clinical_verification_summary(
            guideline_records=guideline_records,
            clinical_annotations=clinical_annotations,
            label_annotations=label_annotations,
        ),
        "summary": {
            "guideline_annotation_count": len(guideline_records),
            "clinical_annotation_count": len(clinical_annotations),
            "label_annotation_count": len(label_annotations),
            "record_research_payload_count": len(record_payloads),
        },
        "raw_calls": raw_calls,
    }
    raw_errors = _raw_call_errors(raw_calls)
    if raw_errors:
        result["warnings"] = raw_errors
    return _attach_evidence_envelope(result)


def _empty_result(
    base_url: str,
    target: dict[str, Any],
    *,
    status: str,
    raw_calls: list[dict[str, Any]],
    missing_inputs: list[str],
) -> dict[str, Any]:
    result = {
        "ok": False,
        "status": status,
        "source": _source_metadata(base_url),
        "query": target,
        "resolved": {"chemicals": [], "genes": [], "variants": []},
        "guideline_annotations": [],
        "clinical_annotations": [],
        "label_annotations": [],
        "sample_follow_up_targets": {"genes": [], "rsids": [], "haplotypes": [], "diplotypes": [], "phenotypes": []},
        "record_research_payloads": [],
        "clinical_verification": _clinical_verification_summary(
            guideline_records=[],
            clinical_annotations=[],
            label_annotations=[],
        ),
        "summary": {
            "guideline_annotation_count": 0,
            "clinical_annotation_count": 0,
            "label_annotation_count": 0,
            "record_research_payload_count": 0,
        },
        "raw_calls": raw_calls,
        "unanswered_answer_components": [
            {
                "component": "public_clinpgx_target",
                "state": "missing",
                "missing_inputs": missing_inputs,
            }
        ],
    }
    return _attach_evidence_envelope(result)


def _attach_evidence_envelope(result: dict[str, Any]) -> dict[str, Any]:
    result["evidence_envelope"] = _clinpgx_evidence_envelope(result)
    return result


def _clinpgx_evidence_envelope(result: dict[str, Any]) -> dict[str, Any]:
    operation = "pharmacogenomics.fetch_clinpgx"
    target = dict(result.get("query") or {})
    summary = dict(result.get("summary") or {})
    raw_calls = result.get("raw_calls") or []
    status = str(result.get("status") or "")
    observations = {
        "status": status,
        "guideline_annotation_count": summary.get("guideline_annotation_count", 0),
        "clinical_annotation_count": summary.get("clinical_annotation_count", 0),
        "label_annotation_count": summary.get("label_annotation_count", 0),
    }
    coverage = {
        "libraries": [{"library": "clinpgx", "state": "failed" if status == "source_unavailable" else "installed"}],
        "consulted_sources": ["clinpgx"] if raw_calls and status != "source_unavailable" else [],
        "unavailable_sources": ["clinpgx"] if status == "source_unavailable" else [],
        "materialization": [],
    }
    if status == "invalid_target":
        return _env.not_assessed(
            operation=operation,
            reason="Missing ClinPGx public target.",
            query_scope=target,
            coverage=coverage,
            observations=observations,
            next_actions=[
                {
                    "action": "provide_public_clinpgx_target",
                    "missing_inputs": ["drug", "gene", "rsid", "chemical_id", "gene_id", "variant_id"],
                }
            ],
            guidance=["target_missing:provide_drug_gene_variant_or_pharmgkb_id"],
        )
    if status == "source_unavailable":
        return _env.not_assessed(
            operation=operation,
            reason="ClinPGx source lookup was unavailable.",
            query_scope=target,
            coverage=coverage,
            observations=observations,
            next_actions=[
                {
                    "action": "use_alternate_pgx_source_or_retry",
                    "operations": [
                        "pharmacogenomics.fetch_pgxdb",
                        "pharmacogenomics.fetch_fda_labels",
                    ],
                }
            ],
            guidance=["source_unavailable:retry_or_use_other_pgx_sources"],
        )
    if status == "no_matching_clinpgx_records":
        return _env.empty_consulted_scope(
            operation=operation,
            query_scope=target,
            coverage=coverage,
            observations=observations,
            next_actions=[
                {
                    "action": "try_alternate_pgx_source_or_target_spelling",
                    "operations": [
                        "pharmacogenomics.fetch_pgxdb",
                        "pharmacogenomics.fetch_fda_labels",
                    ],
                    "target_fields": ["drug", "gene", "rsid", "chemical_id", "gene_id", "variant_id"],
                }
            ],
            guidance=[
                "not_observed_in_consulted_scope:clinpgx_no_records_for_target",
                "negative_inference_disallowed:check_other_pgx_sources",
            ],
        )
    return _env.evidence_present(
        operation=operation,
        query_scope=target,
        coverage=coverage,
        observations=observations,
        answer_readiness=_env.SCOPED_ANSWER_ONLY,
        next_actions=[
            {
                "action": "check_sample_support_before_personal_statement",
                "operation": "variant.resolve",
                "follow_up_targets": result.get("sample_follow_up_targets") or {},
            }
        ],
        guidance=[
            "clinpgx_evidence_present:public_guideline_context_only",
            "clinical_verification:check_actionability_boundary",
            "sample_context:use_follow_up_targets",
        ],
    )


def _source_metadata(base_url: str) -> dict[str, Any]:
    return {
        "source_id": "clinpgx",
        "title": "ClinPGx API",
        "api_url": base_url,
        "swagger_url": CLINPGX_SWAGGER_URL,
        "data_usage_policy_url": CLINPGX_DATA_USAGE_POLICY_URL,
        "accessed_at": utc_now(),
    }


def _resolve_target_ids(base_url: str, target: dict[str, Any], *, raw_calls: list[dict[str, Any]]) -> dict[str, Any]:
    chemicals = []
    genes = []
    variants = []
    if target["chemical_id"]:
        chemicals.append({"id": target["chemical_id"], "resolution": "input_id"})
    elif target["drug"]:
        payload = _fetch_json(base_url, "/data/chemical", query={"name": target["drug"], "view": "min"}, raw_calls=raw_calls)
        chemicals = [_normalize_reference(row, resolution="drug_name") for row in _data_list(payload)]
    if target["gene_id"]:
        genes.append({"id": target["gene_id"], "resolution": "input_id"})
    elif target["gene"]:
        payload = _fetch_json(base_url, "/data/gene", query={"symbol": target["gene"], "view": "min"}, raw_calls=raw_calls)
        genes = [_normalize_reference(row, resolution="gene_symbol") for row in _data_list(payload)]
    if target["variant_id"]:
        variants.append({"id": target["variant_id"], "resolution": "input_id"})
    elif target["rsid"]:
        payload = _fetch_json(base_url, "/data/variant/", query={"symbol": target["rsid"], "view": "min"}, raw_calls=raw_calls)
        variants = [_normalize_reference(row, resolution="rsid") for row in _data_list(payload)]
    return {
        "chemicals": [item for item in chemicals if item.get("id")],
        "genes": [item for item in genes if item.get("id")],
        "variants": [item for item in variants if item.get("id")],
    }


def _fetch_guideline_annotations(
    base_url: str,
    *,
    resolved: dict[str, Any],
    source: str,
    raw_calls: list[dict[str, Any]],
    limit: int,
    include_raw_records: bool,
) -> list[dict[str, Any]]:
    sources = ["cpic", "dpwg", "pro"] if source == "all" else [source]
    chemical_ids = [row["id"] for row in resolved.get("chemicals") or []] or [None]
    gene_ids = [row["id"] for row in resolved.get("genes") or []] or [None]
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for guideline_source in sources:
        for chemical_id in chemical_ids:
            for gene_id in gene_ids:
                query = {"source": guideline_source, "view": "base"}
                if chemical_id:
                    query["relatedChemicals.accessionId"] = chemical_id
                if gene_id:
                    query["relatedGenes.accessionId"] = gene_id
                if len(query) == 2:
                    continue
                payload = _fetch_json(base_url, "/data/guidelineAnnotation", query=query, raw_calls=raw_calls)
                for row in _data_list(payload):
                    normalized = _normalize_guideline_annotation(row, base_url=base_url, include_raw_records=include_raw_records)
                    record_id = str(normalized.get("id") or "")
                    if record_id in seen:
                        continue
                    seen.add(record_id)
                    records.append(normalized)
                    if len(records) >= limit:
                        return records
    return records


def _fetch_clinical_annotations(
    base_url: str,
    *,
    target: dict[str, Any],
    raw_calls: list[dict[str, Any]],
    limit: int,
    include_raw_records: bool,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for query in _clinical_annotation_queries(target):
        payload = _fetch_json(base_url, "/data/clinicalAnnotation", query=query, raw_calls=raw_calls)
        for row in _data_list(payload):
            normalized = _normalize_clinical_annotation(row, base_url=base_url, include_raw_records=include_raw_records)
            record_id = str(normalized.get("id") or normalized.get("accession_id") or normalized.get("name") or "")
            if record_id in seen:
                continue
            seen.add(record_id)
            records.append(normalized)
            if len(records) >= limit:
                return records
    return records


def _clinical_annotation_queries(target: dict[str, Any]) -> list[dict[str, str]]:
    base_query = {"view": "base"}
    candidate_queries: list[dict[str, str]] = []

    exact_query = dict(base_query)
    if target["drug"]:
        exact_query["relatedChemicals.name"] = target["drug"]
    if target["gene"]:
        exact_query["location.genes.symbol"] = target["gene"]
    if target["rsid"]:
        exact_query["location.fingerprint"] = target["rsid"]
    if len(exact_query) > 1:
        candidate_queries.append(exact_query)

    if target["drug"] and target["gene"]:
        candidate_queries.append(
            {
                "view": "base",
                "relatedChemicals.name": target["drug"],
                "location.genes.symbol": target["gene"],
            }
        )
    if target["rsid"]:
        candidate_queries.append({"view": "base", "location.fingerprint": target["rsid"]})
    if target["drug"]:
        candidate_queries.append({"view": "base", "relatedChemicals.name": target["drug"]})
    if target["gene"]:
        candidate_queries.append({"view": "base", "location.genes.symbol": target["gene"]})

    deduped: list[dict[str, str]] = []
    seen: set[tuple[tuple[str, str], ...]] = set()
    for query in candidate_queries:
        key = tuple(sorted(query.items()))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(query)
    return deduped


def _fetch_label_annotations(
    base_url: str,
    *,
    target: dict[str, Any],
    resolved: dict[str, Any],
    raw_calls: list[dict[str, Any]],
    limit: int,
    include_raw_records: bool,
) -> list[dict[str, Any]]:
    queries: list[dict[str, str]] = []
    base_query = {"source": "fda", "view": "base"}
    if target["drug"]:
        query = dict(base_query)
        query["relatedChemicals.name"] = target["drug"]
        if target["gene"]:
            query["relatedGenes.symbol"] = target["gene"]
        queries.append(query)
    for chemical in resolved.get("chemicals") or []:
        query = dict(base_query)
        query["relatedChemicals.accessionId"] = chemical["id"]
        for gene in resolved.get("genes") or [None]:
            gene_query = dict(query)
            if gene:
                gene_query["relatedGenes.accessionId"] = gene["id"]
            queries.append(gene_query)
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for query in queries:
        payload = _fetch_json(base_url, "/data/label", query=query, raw_calls=raw_calls)
        for row in _data_list(payload):
            normalized = _normalize_label_annotation(row, base_url=base_url, include_raw_records=include_raw_records)
            record_id = str(normalized.get("id") or "")
            if record_id in seen:
                continue
            seen.add(record_id)
            records.append(normalized)
            if len(records) >= limit:
                return records
    return records


def _normalize_guideline_annotation(row: dict[str, Any], *, base_url: str, include_raw_records: bool) -> dict[str, Any]:
    record = {
        "source_id": "clinpgx",
        "evidence_class": "guideline_annotation",
        "id": row.get("id"),
        "name": row.get("name"),
        "guideline_source": row.get("source"),
        "recommendation": row.get("recommendation"),
        "dosing_information": row.get("dosingInformation"),
        "alternate_drug_available": row.get("alternateDrugAvailable"),
        "has_testing_info": row.get("hasTestingInfo"),
        "pediatric": row.get("pediatric"),
        "cancer_genome": row.get("cancerGenome"),
        "summary": _markdown_text(row.get("summaryMarkdown")),
        "text_excerpt": _bounded_text(_markdown_text(row.get("textMarkdown")), CLINPGX_MAX_TEXT_CHARS),
        "related_genes": _references(row.get("relatedGenes")),
        "related_chemicals": _references(row.get("relatedChemicals")),
        "related_alleles": _references(row.get("relatedAlleles")),
        "literature": _literature(row.get("literature")),
        "history": _history(row.get("history")),
        "source_url": _record_url(base_url, "guidelineAnnotation", row.get("id")),
    }
    if include_raw_records:
        record["raw"] = _compact_raw(row)
    return record


def _normalize_clinical_annotation(row: dict[str, Any], *, base_url: str, include_raw_records: bool) -> dict[str, Any]:
    location = row.get("location") if isinstance(row.get("location"), dict) else {}
    record = {
        "source_id": "clinpgx",
        "evidence_class": "clinical_annotation",
        "id": row.get("id") or row.get("accessionId"),
        "accession_id": row.get("accessionId"),
        "name": row.get("name"),
        "level_of_evidence": _term(row.get("levelOfEvidence")),
        "phenotype_categories": [_term(item) for item in _as_list(row.get("phenotypeCategories"))],
        "summary": _markdown_text(row.get("summaryMarkdown")),
        "text_excerpt": _bounded_text(_markdown_text(row.get("textMarkdown")) or _first_allele_phenotype(row), CLINPGX_MAX_TEXT_CHARS),
        "related_genes": _references(location.get("genes")),
        "related_chemicals": _references(row.get("relatedChemicals")),
        "haplotypes": _references(location.get("haplotypes")),
        "diplotypes": _references(location.get("diplotypes")),
        "display_name": location.get("displayName"),
        "literature": _literature(row.get("literature")),
        "history": _history(row.get("history")),
        "source_url": _record_url(base_url, "clinicalAnnotation", row.get("id") or row.get("accessionId")),
    }
    if include_raw_records:
        record["raw"] = _compact_raw(row)
    return record


def _normalize_label_annotation(row: dict[str, Any], *, base_url: str, include_raw_records: bool) -> dict[str, Any]:
    testing = row.get("testing") if isinstance(row.get("testing"), dict) else {}
    record = {
        "source_id": "clinpgx",
        "evidence_class": "drug_label_annotation",
        "id": row.get("id"),
        "name": row.get("name"),
        "label_source": row.get("source"),
        "biomarker_status": row.get("biomarkerStatus"),
        "testing_level": testing.get("term"),
        "pgx_related": row.get("pgxRelated"),
        "dosing_information": row.get("dosingInformation"),
        "alternate_drug_available": row.get("alternateDrugAvailable"),
        "summary": _markdown_text(row.get("summaryMarkdown")),
        "prescribing_excerpt": _bounded_text(_markdown_text(row.get("prescribingMarkdown")), CLINPGX_MAX_TEXT_CHARS),
        "text_excerpt": _bounded_text(_markdown_text(row.get("textMarkdown")), CLINPGX_MAX_TEXT_CHARS),
        "related_genes": _references(row.get("relatedGenes")),
        "prescribing_genes": _references(row.get("prescribingGenes")),
        "related_chemicals": _references(row.get("relatedChemicals")),
        "literature": _literature(row.get("literature")),
        "history": _history(row.get("history")),
        "source_url": _record_url(base_url, "label", row.get("id")),
    }
    if include_raw_records:
        record["raw"] = _compact_raw(row)
    return record


def _sample_follow_up_targets(
    *,
    guideline_records: list[dict[str, Any]],
    clinical_annotations: list[dict[str, Any]],
    label_annotations: list[dict[str, Any]],
    query: dict[str, Any],
) -> dict[str, Any]:
    genes: dict[str, dict[str, Any]] = {}
    rsids: set[str] = set()
    haplotypes: dict[str, dict[str, Any]] = {}
    diplotypes: dict[str, dict[str, Any]] = {}
    phenotypes: set[str] = set()
    if query.get("gene"):
        genes[query["gene"]] = {"symbol": query["gene"], "source": "query"}
    if query.get("rsid"):
        rsids.add(query["rsid"])
    for record in [*guideline_records, *clinical_annotations, *label_annotations]:
        for gene in [*record.get("related_genes", []), *record.get("prescribing_genes", [])]:
            symbol = gene.get("symbol") or gene.get("name")
            if symbol:
                genes[str(symbol).upper()] = gene
        for haplotype in record.get("haplotypes", []):
            symbol = haplotype.get("symbol") or haplotype.get("name")
            if symbol:
                haplotypes[str(symbol)] = haplotype
        for diplotype in record.get("diplotypes", []):
            symbol = diplotype.get("symbol") or diplotype.get("name")
            if symbol:
                diplotypes[str(symbol)] = diplotype
        for value in record.get("phenotype_categories", []):
            if value:
                phenotypes.add(str(value))
    return {
        "genes": sorted(genes.values(), key=lambda item: str(item.get("symbol") or item.get("name") or "")),
        "rsids": sorted(rsids),
        "haplotypes": sorted(haplotypes.values(), key=lambda item: str(item.get("symbol") or item.get("name") or "")),
        "diplotypes": sorted(diplotypes.values(), key=lambda item: str(item.get("symbol") or item.get("name") or "")),
        "phenotypes": sorted(phenotypes),
        "sample_evidence_needed": [
            "Active Genome Index variant lookup for selected rsIDs or loci",
            "star-allele/diplotype or phenotype translation when guideline interpretation depends on haplotypes",
            "VCF/gVCF coverage, phasing, copy-number, or specialized pharmacogene caller evidence when required by the gene",
        ],
    }


def _clinical_verification_summary(
    *,
    guideline_records: list[dict[str, Any]],
    clinical_annotations: list[dict[str, Any]],
    label_annotations: list[dict[str, Any]],
) -> dict[str, Any]:
    evidence_classes = []
    if guideline_records:
        evidence_classes.append("guideline_annotation")
    if clinical_annotations:
        evidence_classes.append("clinical_annotation")
    if label_annotations:
        evidence_classes.append("drug_label_annotation")
    return {
        "status": "informational_evidence_review_requires_clinical_confirmation",
        "public_evidence_classes": evidence_classes,
        "can_support": [
            "source-backed PGx interpretation when combined with matching sample genotype/diplotype evidence",
            "traceable citation of guideline, annotation, label, literature, and API access metadata",
        ],
        "requires_before_personal_actionability": [
            "matching Active Genome Index evidence for the relevant allele, haplotype, diplotype, gene, or phenotype",
            "sample quality and coverage appropriate for the pharmacogene",
            "clinical context such as indication, contraindications, current medications, and clinician review",
        ],
    }


def _record_research_payloads(
    *,
    guideline_records: list[dict[str, Any]],
    clinical_annotations: list[dict[str, Any]],
    label_annotations: list[dict[str, Any]],
    source: dict[str, Any],
    target: dict[str, Any],
) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for record in [*guideline_records, *clinical_annotations, *label_annotations]:
        text = str(record.get("summary") or record.get("text_excerpt") or record.get("prescribing_excerpt") or "").strip()
        if not text:
            continue
        payloads.append(
            {
                "target": _research_target(record, target),
                "source": {
                    "source_id": source["source_id"],
                    "title": _source_title(record),
                    "url": record.get("source_url") or source["api_url"],
                    "type": record.get("evidence_class"),
                    "api_url": source["api_url"],
                    "swagger_url": source["swagger_url"],
                    "citations": _payload_citations(record),
                    "accessed_at": source["accessed_at"],
                    "published_at": _first_literature_date(record),
                },
                "finding": {
                    "type": f"clinpgx_{record.get('evidence_class')}",
                    "text": _bounded_text(text, CLINPGX_MAX_TEXT_CHARS),
                    "summary": _summary_from_record(record),
                },
                "searched_query": json.dumps(target, sort_keys=True),
                "captured_by": "genomi call pharmacogenomics.fetch_clinpgx",
            }
        )
    return payloads


def _payload_citations(record: dict[str, Any]) -> list[dict[str, Any]]:
    citations = []
    for item in record.get("literature") or []:
        if not isinstance(item, dict):
            continue
        citations.append(
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "url": item.get("url"),
                "pub_date": item.get("pub_date"),
                "cross_references": item.get("cross_references"),
            }
        )
    return citations[:10]


def _research_target(record: dict[str, Any], query: dict[str, Any]) -> dict[str, str]:
    drug = query.get("drug") or _first_name(record.get("related_chemicals"))
    gene = query.get("gene") or _first_symbol(record.get("related_genes") or record.get("prescribing_genes"))
    rsid = query.get("rsid")
    topic = " ".join(str(item) for item in [drug, gene, rsid, record.get("evidence_class")] if item)
    if drug:
        return {"type": "drug", "drug": str(drug), "topic": topic}
    if gene:
        return {"type": "gene", "gene": str(gene), "topic": topic}
    if rsid:
        return {"type": "topic", "topic": topic}
    return {"type": "topic", "topic": topic or str(record.get("name") or "ClinPGx pharmacogenomic evidence")}


def _fetch_json(
    base_url: str,
    path: str,
    *,
    query: dict[str, str] | None = None,
    raw_calls: list[dict[str, Any]],
) -> Any:
    url = _url(base_url, path, query=query)
    call: dict[str, Any] = {"url": url, "status": None, "attempts": 0}
    raw_calls.append(call)
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "genomi/0.1"})
    for attempt in range(2):
        call["attempts"] = attempt + 1
        try:
            with urllib.request.urlopen(request, timeout=CLINPGX_TIMEOUT_SECONDS) as response:
                call["status"] = int(getattr(response, "status", 0) or 0)
                call["content_type"] = response.headers.get("content-type")
                body = response.read()
            return json.loads(body.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            call["status"] = exc.code
            if exc.code == 404:
                call["not_found"] = True
                return {"data": []}
            call["error"] = f"HTTP {exc.code}"
            if 400 <= exc.code < 500:
                return None
        except urllib.error.URLError as exc:
            call["error"] = f"URL error: {exc.reason}"
        except TimeoutError as exc:
            call["error"] = f"timeout: {exc}"
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            call["error"] = f"parse error: {exc}"
            return None
        except OSError as exc:
            call["error"] = f"I/O error: {exc}"
        if attempt == 0:
            time.sleep(0.5)
    return None


def _url(base_url: str, path: str, *, query: dict[str, str] | None = None) -> str:
    encoded_path = "/".join(urllib.parse.quote(part, safe="/") for part in path.split("/"))
    url = base_url.rstrip("/") + "/" + encoded_path.lstrip("/")
    if query:
        url += "?" + urllib.parse.urlencode({key: value for key, value in query.items() if value})
    return url


def _base_url(value: str | None) -> str:
    return (value or CLINPGX_API_URL).rstrip("/")


def _guideline_source(value: str | None) -> str:
    source = (value or "all").strip().lower()
    return source if source in {"all", "cpic", "dpwg", "pro"} else "all"


def _bounded_limit(value: int) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return 10
    return max(1, min(limit, CLINPGX_MAX_LIMIT))


def _data_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return [item for item in payload["data"] if isinstance(item, dict)]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _normalize_reference(row: dict[str, Any], *, resolution: str) -> dict[str, Any]:
    return {
        "id": row.get("id") or row.get("accessionId"),
        "accession_id": row.get("accessionId"),
        "symbol": row.get("symbol"),
        "name": row.get("name"),
        "object_class": row.get("objCls"),
        "resolution": resolution,
    }


def _references(value: Any) -> list[dict[str, Any]]:
    return [_normalize_reference(item, resolution="record") for item in _as_list(value) if isinstance(item, dict)]


def _literature(value: Any) -> list[dict[str, Any]]:
    records = []
    for row in _as_list(value):
        if not isinstance(row, dict):
            continue
        records.append(
            {
                "id": row.get("id"),
                "title": row.get("title"),
                "url": row.get("_sameAs"),
                "pub_date": row.get("pubDate"),
                "cross_references": _cross_references(row.get("crossReferences")),
                "type": row.get("type"),
            }
        )
    return records


def _cross_references(value: Any) -> list[dict[str, Any]]:
    return [
        {"resource": row.get("resource"), "resource_id": row.get("resourceId"), "url": row.get("_url")}
        for row in _as_list(value)
        if isinstance(row, dict)
    ]


def _history(value: Any) -> list[dict[str, Any]]:
    return [
        {"date": row.get("date"), "type": row.get("type"), "description": row.get("description")}
        for row in _as_list(value)
        if isinstance(row, dict)
    ]


def _term(value: Any) -> str | None:
    if isinstance(value, dict):
        return value.get("term") or value.get("name")
    if isinstance(value, str):
        return value
    return None


def _first_allele_phenotype(row: dict[str, Any]) -> str | None:
    for allele in _as_list(row.get("allelePhenotypes")):
        if isinstance(allele, dict) and allele.get("phenotype"):
            return str(allele.get("phenotype"))
    return None


def _markdown_text(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("html") or value.get("text") or value.get("markdown")
    if not isinstance(value, str) or not value.strip():
        return None
    parser = _HTMLTextParser()
    parser.feed(value)
    return _clean(parser.text()) or _clean(html.unescape(re.sub(r"<[^>]+>", " ", value)))


class _HTMLTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def text(self) -> str:
        return html.unescape(" ".join(self._parts))


def _record_url(base_url: str, entity: str, record_id: Any) -> str:
    if record_id is None:
        return base_url
    return f"{base_url.rstrip('/')}/data/{entity}/{urllib.parse.quote(str(record_id))}"


def _source_title(record: dict[str, Any]) -> str:
    evidence_class = str(record.get("evidence_class") or "pharmacogenomic evidence").replace("_", " ")
    name = record.get("name")
    source = record.get("guideline_source") or record.get("label_source") or "ClinPGx"
    return f"{source} {evidence_class}: {name}" if name else f"{source} {evidence_class}"


def _summary_from_record(record: dict[str, Any]) -> str:
    pieces = [
        record.get("guideline_source") or record.get("label_source"),
        record.get("evidence_class"),
        record.get("level_of_evidence"),
        record.get("biomarker_status"),
        record.get("testing_level"),
        record.get("summary"),
    ]
    return " ".join(str(piece) for piece in pieces if piece)


def _first_literature_date(record: dict[str, Any]) -> str | None:
    literature = record.get("literature") or []
    if literature and isinstance(literature[0], dict):
        return literature[0].get("pub_date")
    return None


def _first_name(value: Any) -> str | None:
    for item in _as_list(value):
        if isinstance(item, dict) and item.get("name"):
            return str(item["name"])
    return None


def _first_symbol(value: Any) -> str | None:
    for item in _as_list(value):
        if isinstance(item, dict) and (item.get("symbol") or item.get("name")):
            return str(item.get("symbol") or item.get("name"))
    return None


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(str(value).strip().split())
    return cleaned or None


def _normalize_rsid(value: str | None) -> str | None:
    cleaned = _clean(value)
    if not cleaned:
        return None
    token = cleaned.split()[0].split(",")[0].strip()
    return token.lower() if token.lower().startswith("rs") else token


def _normalize_gene(value: str | None) -> str | None:
    cleaned = _clean(value)
    return cleaned.upper() if cleaned else None


def _bounded_text(value: Any, max_chars: int) -> Any:
    if not isinstance(value, str):
        return value
    if len(value) <= max_chars:
        return value
    return value[:max_chars] + "...<truncated>"


def _compact_raw(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _compact_raw(item) for key, item in value.items()}
    if isinstance(value, list):
        compacted = [_compact_raw(item) for item in value[:CLINPGX_MAX_RAW_LIST_ITEMS]]
        if len(value) > CLINPGX_MAX_RAW_LIST_ITEMS:
            compacted.append({"truncated_items": len(value) - CLINPGX_MAX_RAW_LIST_ITEMS})
        return compacted
    if isinstance(value, str):
        return _bounded_text(value, CLINPGX_MAX_RAW_TEXT_CHARS)
    return value


def _raw_call_errors(raw_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"url": call.get("url"), "status": call.get("status"), "error": call.get("error")}
        for call in raw_calls
        if call.get("error")
    ]
