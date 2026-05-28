from __future__ import annotations

from ._common import JsonObject, _compact_selected_fields


def _source_record_research_payloads(*results: JsonObject) -> list[JsonObject]:
    payloads: list[JsonObject] = []
    for result in results:
        payloads.extend(list(result.get("record_research_payloads") or []))
    return payloads


def _record_research_payload_summaries(payloads: list[JsonObject], *, limit: int = 12) -> list[JsonObject]:
    summaries = []
    for payload in payloads[:limit]:
        target = payload.get("target") if isinstance(payload.get("target"), dict) else {}
        source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
        finding = payload.get("finding") if isinstance(payload.get("finding"), dict) else {}
        summaries.append(
            {
                "evidence_role": _record_research_payload_role(payload),
                "target": _compact_selected_fields(target, ("type", "drug", "gene", "topic", "genome_build")),
                "source": _compact_selected_fields(source, ("title", "url", "type", "accessed_at", "published_at")),
                "finding": _compact_selected_fields(finding, ("type", "summary")),
                "captured_by": payload.get("captured_by"),
            }
        )
    return summaries


def _record_research_payload_role_counts(payloads: list[JsonObject]) -> JsonObject:
    counts: dict[str, int] = {}
    for payload in payloads:
        role = _record_research_payload_role(payload)
        counts[role] = counts.get(role, 0) + 1
    return counts


def _record_research_payload_role(payload: JsonObject) -> str:
    finding = payload.get("finding") if isinstance(payload.get("finding"), dict) else {}
    source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
    finding_type = str(finding.get("type") or "").strip().lower()
    source_type = str(source.get("type") or "").strip().lower()
    if finding_type in {
        "clinpgx_guideline_annotation",
        "clinpgx_clinical_annotation",
        "clinpgx_drug_label_annotation",
        "pgxdb_pharmacogenomic_association",
        "pgxdb_gene_drug_context",
        "fda_pharmacogenomic_biomarker_labeling",
        "fda_pharmacogenetic_association",
    }:
        return "medication_source_evidence"
    if finding_type.startswith("pharmcat_sample") or source_type in {"sample_pharmacogenomic_call", "sample_pharmacogenomic_recommendation"}:
        return "sample_pgx_evidence"
    return "context_only"


def _stored_source_evidence_count(stored_research: JsonObject) -> int:
    return sum(1 for record in stored_research.get("records") or [] if _is_stored_source_pgx_record(record))


def _stored_sample_evidence_count(stored_research: JsonObject) -> int:
    return sum(1 for record in stored_research.get("records") or [] if _is_stored_sample_pgx_record(record))


def _is_stored_sample_pgx_record(record: JsonObject) -> bool:
    return _record_research_payload_role(record) == "sample_pgx_evidence"


def _is_stored_source_pgx_record(record: JsonObject) -> bool:
    return _record_research_payload_role(record) == "medication_source_evidence"
