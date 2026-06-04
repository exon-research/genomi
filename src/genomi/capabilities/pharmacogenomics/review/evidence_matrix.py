from __future__ import annotations

import hashlib
import json

from ._common import (
    JsonObject,
    _as_dicts,
    _clinpgx_source_title,
    _compact_selected_fields,
    _compact_text,
    _first_reference_name,
    _first_reference_symbol,
    _literature_citations,
    _pgxdb_gene_drug_source_url,
    _pgxdb_record_source_url,
    _pmid_citations,
    _stable_evidence_source_identity,
    _traceability_status,
)
from .record_research import _record_research_payload_role
from .sample_evidence import _is_observed_star_marker


def _evidence_matrix(
    *,
    clinpgx_result: JsonObject,
    pgxdb_result: JsonObject,
    fda_result: JsonObject,
    stored_research: JsonObject,
    sample_lookups: list[JsonObject],
    star_allele_calls: list[JsonObject],
    user_provided_sample_evidence: list[JsonObject],
) -> list[JsonObject]:
    items: list[JsonObject] = []
    items.extend(_clinpgx_evidence_items(clinpgx_result))
    items.extend(_pgxdb_evidence_items(pgxdb_result))
    items.extend(_fda_evidence_items(fda_result))
    items.extend(_stored_research_evidence_items(stored_research))
    items.extend(_sample_lookup_evidence_items(sample_lookups))
    items.extend(_star_allele_evidence_items(star_allele_calls))
    items.extend(_user_provided_sample_evidence_items(user_provided_sample_evidence))
    return _with_evidence_item_ids(_dedupe_evidence_items(items))


def _with_evidence_item_ids(items: list[JsonObject]) -> list[JsonObject]:
    annotated = []
    for item in items:
        copy = dict(item)
        copy["evidence_id"] = _evidence_item_id(copy)
        annotated.append(copy)
    return annotated


def _evidence_item_id(item: JsonObject) -> str:
    identity = {
        "role": item.get("evidence_role"),
        "class": item.get("evidence_class"),
        "source": _stable_evidence_source_identity(item.get("source")),
        "target": item.get("target"),
        "finding": item.get("finding"),
    }
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    return f"pgxev_{digest[:16]}"


def _evidence_matrix_traceability(items: list[JsonObject]) -> JsonObject:
    verification_status_counts: dict[str, int] = {}
    evidence_class_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}
    source_url_counts: dict[str, int] = {}
    traceable_public = 0
    missing_source_url = 0
    local_sample = 0
    observed_marker = 0
    marker_definition = 0
    stored_reviewed = 0
    user_provided = 0
    citation_item_count = 0
    citation_count = 0
    artifact_item_count = 0
    artifact_ids: list[str] = []
    pmids: list[str] = []
    item_ids = []
    for item in items:
        item_id = str(item.get("evidence_id") or "")
        if item_id:
            item_ids.append(item_id)
        evidence_class = str(item.get("evidence_class") or "unknown")
        evidence_class_counts[evidence_class] = evidence_class_counts.get(evidence_class, 0) + 1
        source = item.get("source") if isinstance(item.get("source"), dict) else {}
        source_id = str(source.get("source_id") or "unknown")
        source_counts[source_id] = source_counts.get(source_id, 0) + 1
        source_url = str(source.get("url") or "")
        if source_url:
            source_url_counts[source_url] = source_url_counts.get(source_url, 0) + 1
        artifact = source.get("artifact") if isinstance(source.get("artifact"), dict) else {}
        artifact_id = str(artifact.get("artifact_id") or "")
        if artifact_id:
            artifact_item_count += 1
            artifact_ids.append(artifact_id)
        pmid = str(source.get("pmid") or "")
        if pmid:
            pmids.append(pmid)
        verification = item.get("verification") if isinstance(item.get("verification"), dict) else {}
        status = str(verification.get("status") or "missing_verification")
        verification_status_counts[status] = verification_status_counts.get(status, 0) + 1
        citations = item.get("citations") if isinstance(item.get("citations"), list) else []
        if citations:
            citation_item_count += 1
            citation_count += len(citations)
            for citation in citations:
                if isinstance(citation, dict):
                    citation_pmid = str(citation.get("id") or citation.get("pmid") or "")
                    if citation_pmid:
                        pmids.append(citation_pmid)
        if status == "source_traceable":
            traceable_public += 1
        if status == "missing_source_url":
            missing_source_url += 1
        if status in {"observed_genotype_available", "observed_marker_evidence"}:
            local_sample += 1
        if status == "observed_marker_evidence":
            observed_marker += 1
        if status == "marker_definition_evidence":
            marker_definition += 1
        if status == "stored_reviewed_evidence":
            stored_reviewed += 1
        if status == "user_provided_unverified":
            user_provided += 1
    return {
        "schema": "genomi-pgx-evidence-matrix-traceability-v1",
        "item_count": len(items),
        "item_ids": item_ids,
        "unique_item_id_count": len(set(item_ids)),
        "all_items_have_stable_ids": len(item_ids) == len(items) and len(set(item_ids)) == len(items),
        "all_items_have_verification": all(isinstance(item.get("verification"), dict) and item["verification"].get("status") for item in items),
        "verification_status_counts": verification_status_counts,
        "evidence_class_counts": evidence_class_counts,
        "source_counts": source_counts,
        "source_ids": sorted(source_counts),
        "source_url_counts": source_url_counts,
        "unique_source_url_count": len(source_url_counts),
        "source_traceable_item_count": traceable_public,
        "missing_source_url_item_count": missing_source_url,
        "artifact_item_count": artifact_item_count,
        "artifact_ids": sorted(set(artifact_ids)),
        "pmids": sorted(set(pmids)),
        "local_sample_item_count": local_sample,
        "observed_marker_item_count": observed_marker,
        "marker_definition_item_count": marker_definition,
        "stored_reviewed_evidence_item_count": stored_reviewed,
        "user_provided_unverified_item_count": user_provided,
        "citation_item_count": citation_item_count,
        "citation_count": citation_count,
    }


def _clinpgx_evidence_items(result: JsonObject) -> list[JsonObject]:
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    items: list[JsonObject] = []
    groups = [
        ("guideline_annotations", "clinpgx_guideline_annotation"),
        ("clinical_annotations", "clinpgx_clinical_annotation"),
        ("label_annotations", "clinpgx_drug_label_annotation"),
    ]
    for key, evidence_class in groups:
        for record in result.get(key) or []:
            summary = record.get("summary") or record.get("text_excerpt") or record.get("prescribing_excerpt")
            items.append(
                {
                    "evidence_role": "medication_source_evidence",
                    "source": {
                        "source_id": source.get("source_id") or "clinpgx",
                        "title": _clinpgx_source_title(record),
                        "url": record.get("source_url") or source.get("api_url"),
                        "accessed_at": source.get("accessed_at"),
                    },
                    "evidence_class": evidence_class,
                    "target": {
                        "drug": _first_reference_name(record.get("related_chemicals")),
                        "gene": _first_reference_symbol(record.get("related_genes") or record.get("prescribing_genes")),
                        "record_id": record.get("id") or record.get("accession_id"),
                    },
                    "finding": {
                        "name": record.get("name") or record.get("display_name"),
                        "summary": _compact_text(summary),
                        "evidence_level": record.get("level_of_evidence"),
                        "guideline_source": record.get("guideline_source"),
                        "label_source": record.get("label_source"),
                    },
                    "citations": _literature_citations(record.get("literature")),
                    "verification": _traceability_status(record.get("source_url") or source.get("api_url")),
                }
            )
    return items


def _pgxdb_evidence_items(result: JsonObject) -> list[JsonObject]:
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    items: list[JsonObject] = []
    for record in result.get("pgx_records") or []:
        source_url = _pgxdb_record_source_url(record)
        items.append(
            {
                "evidence_role": "medication_source_evidence",
                "source": {
                    "source_id": source.get("source_id") or "pgxdb",
                    "title": "PGxDB PharmGKB pharmacogenomics data",
                    "url": source_url,
                    "accessed_at": source.get("accessed_at"),
                },
                "evidence_class": "pgxdb_pharmacogenomic_association",
                "target": {
                    "drug": record.get("drug"),
                    "drugbank_id": record.get("drugbank_id"),
                    "atc_code": record.get("atc_code"),
                    "rsid": record.get("rsid"),
                    "variant_or_haplotype": record.get("variant_or_haplotype"),
                },
                "finding": {
                    "summary": _compact_text(record.get("sentence") or record.get("notes")),
                    "alleles": record.get("alleles"),
                    "direction_of_effect": record.get("direction_of_effect"),
                    "pd_pk_terms": record.get("pd_pk_terms"),
                    "phenotype_category": record.get("phenotype_category"),
                    "significance": record.get("significance"),
                    "p_value": record.get("p_value"),
                    "study_type": record.get("study_type"),
                },
                "citations": _pmid_citations(record.get("pmid")),
                "verification": _traceability_status(source_url),
            }
        )
    for record in result.get("medication_scoped_gene_drug_records") or []:
        source_url = _pgxdb_gene_drug_source_url()
        items.append(
            {
                "evidence_role": "medication_source_evidence",
                "source": {
                    "source_id": source.get("source_id") or "pgxdb",
                    "title": "PGxDB gene-drug context",
                    "url": source_url,
                    "accessed_at": source.get("accessed_at"),
                },
                "evidence_class": "pgxdb_gene_drug_context",
                "target": {
                    "gene": record.get("gene"),
                    "drugbank_id": record.get("drugbank_id"),
                    "target_scope": record.get("target_scope"),
                },
                "finding": {
                    "summary": _compact_text(
                        " ".join(
                            str(item)
                            for item in (record.get("actions"), record.get("known_action"), record.get("interaction_type"))
                            if item
                        )
                    )
                },
                "citations": [],
                "verification": _traceability_status(source_url),
            }
        )
    return items


def _fda_evidence_items(result: JsonObject) -> list[JsonObject]:
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    items: list[JsonObject] = []
    for record in result.get("rows") or []:
        source_url = record.get("source_url")
        items.append(
            {
                "evidence_role": "medication_source_evidence",
                "source": {
                    "source_id": source.get("source_id") or "fda_pgx",
                    "title": "FDA PGx tables",
                    "url": source_url,
                    "accessed_at": source.get("accessed_at"),
                },
                "evidence_class": record.get("evidence_class"),
                "target": {
                    "drug": record.get("drug"),
                    "gene_or_biomarker": record.get("gene_or_biomarker"),
                },
                "finding": {
                    "summary": _compact_text(record.get("description") or record.get("labeling_sections") or record.get("affected_subgroups")),
                    "therapeutic_area": record.get("therapeutic_area"),
                    "labeling_sections": record.get("labeling_sections"),
                    "affected_subgroups": record.get("affected_subgroups"),
                },
                "citations": [],
                "verification": _traceability_status(source_url),
            }
        )
    return items


def _stored_research_evidence_items(stored_research: JsonObject) -> list[JsonObject]:
    items = []
    for record in stored_research.get("records") or []:
        role = _record_research_payload_role(record)
        if role == "context_only":
            continue
        source = record.get("source") if isinstance(record.get("source"), dict) else {}
        finding = record.get("finding") if isinstance(record.get("finding"), dict) else {}
        target = record.get("target") if isinstance(record.get("target"), dict) else {}
        items.append(
            {
                "evidence_role": role,
                "source": {
                    "source_id": "stored_research",
                    "title": source.get("title"),
                    "url": source.get("url"),
                    "type": source.get("type"),
                    "artifact": source.get("artifact"),
                    "artifact_metadata": source.get("artifact_metadata"),
                    "store": record.get("store"),
                    "captured_by": record.get("captured_by"),
                    "captured_at": record.get("captured_at"),
                },
                "evidence_class": finding.get("type") or "stored_research",
                "target": _compact_selected_fields(target, ("type", "drug", "gene", "topic", "genome_build")),
                "finding": {"summary": _compact_text(finding.get("summary") or finding.get("text"))},
                "citations": _stored_source_citations(source),
                "verification": {
                    **_traceability_status(source.get("url")),
                    "status": "stored_reviewed_evidence",
                },
            }
        )
    return items


def _stored_source_citations(source: JsonObject) -> list[JsonObject]:
    citations: list[JsonObject] = []
    citations.extend(_pmid_citations(source.get("pmid")))
    for citation in _as_dicts(source.get("citations")):
        compact = _compact_selected_fields(citation, ("id", "title", "url", "pub_date", "published_at"))
        if compact:
            citations.append(compact)
    return citations[:12]


def _sample_lookup_evidence_items(sample_lookups: list[JsonObject]) -> list[JsonObject]:
    items = []
    for lookup in sample_lookups:
        query = lookup.get("query") if isinstance(lookup.get("query"), dict) else {}
        for match in lookup.get("sample_context", {}).get("matches") or []:
            items.append(
                {
                    "evidence_role": "sample_pgx_evidence",
                    "source": {
                        "source_id": "active_genome_index",
                        "source_format": match.get("source_format"),
                    },
                    "evidence_class": "active_genome_index_variant_match",
                    "target": {
                        "rsid": match.get("rsid") or query.get("rsid"),
                        "chrom": match.get("chrom"),
                        "pos": match.get("pos"),
                        "ref": match.get("ref"),
                        "alt": match.get("alt"),
                    },
                    "finding": {
                        "genotype": match.get("genotype"),
                        "filter": match.get("filter"),
                        "depth": match.get("depth"),
                        "genotype_quality": match.get("genotype_quality"),
                    },
                    "citations": [],
                    "verification": {"status": "observed_genotype_available"},
                }
            )
    return items


def _star_allele_evidence_items(star_allele_calls: list[JsonObject]) -> list[JsonObject]:
    items = []
    for call in star_allele_calls:
        if not isinstance(call, dict):
            continue
        diplotype = call.get("diplotype") if isinstance(call.get("diplotype"), dict) else {}
        marker_calls = call.get("marker_calls") if isinstance(call.get("marker_calls"), list) else []
        observed_markers = [
            marker
            for marker in marker_calls
            if isinstance(marker, dict) and _is_observed_star_marker(marker)
        ]
        if not call.get("called_star_alleles") and not observed_markers and not diplotype.get("possible_diplotype") and not diplotype.get("predicted_phenotype"):
            continue
        items.append(
            {
                "evidence_role": "sample_pgx_evidence",
                "source": {
                    "source_id": "genomi_pgx_star_alleles",
                    "definition_set": call.get("definition_set"),
                    "source_urls": [
                        source.get("url")
                        for source in call.get("traceability", {}).get("definition_sources", [])
                        if isinstance(source, dict) and source.get("url")
                    ],
                },
                "evidence_class": "pgx_star_allele_marker_call",
                "target": {"gene": call.get("gene")},
                "finding": {
                    "possible_diplotype": diplotype.get("possible_diplotype"),
                    "predicted_phenotype": diplotype.get("predicted_phenotype"),
                    "marker_support_status": diplotype.get("marker_support_status"),
                    "observed_marker_count": len(observed_markers),
                    "marker_count": len(marker_calls),
                    "called_star_alleles": [
                        _compact_selected_fields(item, ("star_allele", "function", "rsid", "support", "genotype_support"))
                        for item in call.get("called_star_alleles") or []
                    ],
                },
                "citations": [],
                "verification": {"status": "observed_marker_evidence"},
            }
        )
    return items


def _user_provided_sample_evidence_items(user_provided_sample_evidence: list[JsonObject]) -> list[JsonObject]:
    items = []
    for evidence in user_provided_sample_evidence:
        items.append(
            {
                "evidence_role": "sample_pgx_evidence",
                "source": {
                    "source_id": "user_provided",
                    "title": evidence.get("known_pgx_source"),
                },
                "evidence_class": evidence.get("evidence_class") or "user_provided_sample_pgx_evidence",
                "target": _compact_selected_fields(evidence, ("target_type", "gene", "rsid")),
                "finding": _compact_selected_fields(
                    evidence,
                    ("known_genotype", "known_diplotype", "known_phenotype", "known_activity_score"),
                ),
                "citations": [],
                "verification": {
                    "status": evidence.get("status") or "user_provided_unverified",
                    "clinical_boundary": evidence.get("clinical_boundary"),
                },
            }
        )
    return items


def _evidence_item_role_counts(items: list[JsonObject]) -> JsonObject:
    counts: dict[str, int] = {}
    for item in items:
        role = str(item.get("evidence_role") or "unknown")
        counts[role] = counts.get(role, 0) + 1
    return counts


def _dedupe_evidence_items(items: list[JsonObject]) -> list[JsonObject]:
    deduped = []
    seen = set()
    for item in items:
        key = json.dumps(
            {
                "role": item.get("evidence_role"),
                "class": item.get("evidence_class"),
                "source": _stable_evidence_source_identity(item.get("source")),
                "target": item.get("target"),
                "finding": item.get("finding"),
            },
            sort_keys=True,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped
