from __future__ import annotations

import json

from ._common import (
    JsonObject,
    _artifact_source_summary,
    _as_dicts,
    _as_list,
    _without_none,
)


def _has_imported_pharmcat_evidence(artifacts: JsonObject) -> bool:
    calls = artifacts.get("calls_only") if isinstance(artifacts.get("calls_only"), dict) else {}
    report = artifacts.get("report_json") if isinstance(artifacts.get("report_json"), dict) else {}
    match = artifacts.get("named_allele_match_json") if isinstance(artifacts.get("named_allele_match_json"), dict) else {}
    phenotype = artifacts.get("phenotype_json") if isinstance(artifacts.get("phenotype_json"), dict) else {}
    return bool(
        (calls.get("available") and calls.get("row_count"))
        or report.get("available")
        or (match.get("available") and match.get("result_count"))
        or (phenotype.get("available") and phenotype.get("gene_report_count"))
    )


def _record_payloads_from_report(report_json: JsonObject, *, captured_by: str = "genomi call pharmacogenomics.run_pharmcat") -> list[JsonObject]:
    recommendations = report_json.get("recommendations", {}).get("records") if isinstance(report_json.get("recommendations"), dict) else []
    payloads = []
    for record in _as_dicts(recommendations):
        drug = record.get("drug")
        genes = record.get("genes") or []
        recommendation = record.get("recommendation")
        implications = record.get("implications") or []
        text = _report_finding_text(record)
        if not text:
            continue
        payloads.append(
            {
                "target": {
                    "type": "drug" if drug else "topic",
                    "drug": drug,
                    "gene": ",".join(str(gene) for gene in genes) if genes else None,
                    "topic": " ".join(str(item) for item in [drug, ",".join(genes), record.get("source_group")] if item),
                },
                "source": _without_none({
                    "title": f"PharmCAT {record.get('source_group')} sample recommendation",
                    "url": record.get("source_url") or "https://pharmcat.clinpgx.org/",
                    "type": "sample_pharmacogenomic_recommendation",
                    "artifact": _artifact_source_summary(report_json),
                    "artifact_metadata": report_json.get("metadata") if isinstance(report_json.get("metadata"), dict) else None,
                }),
                "finding": {
                    "type": "pharmcat_sample_pgx_recommendation",
                    "text": text,
                    "summary": recommendation or "; ".join(str(item) for item in implications),
                },
                "searched_query": json.dumps({"drug": drug, "genes": genes, "source": "pharmcat_report_json"}, sort_keys=True),
                "captured_by": captured_by,
            }
        )
    return payloads


def _record_payloads_from_match(match_json: JsonObject, *, captured_by: str = "genomi call pharmacogenomics.run_pharmcat") -> list[JsonObject]:
    payloads = []
    for record in _as_dicts(match_json.get("records")):
        gene = str(record.get("gene") or "").strip().upper()
        text = _match_finding_text(record)
        if not gene or not text:
            continue
        payloads.append(
            {
                "target": {"type": "gene", "gene": gene},
                "source": _without_none({
                    "title": "PharmCAT named allele matcher JSON artifact",
                    "url": "https://pharmcat.clinpgx.org/",
                    "type": "sample_pharmacogenomic_call",
                    "artifact": _artifact_source_summary(match_json),
                    "artifact_metadata": match_json.get("metadata") if isinstance(match_json.get("metadata"), dict) else None,
                }),
                "finding": {
                    "type": "pharmcat_sample_pgx_match",
                    "text": text,
                    "summary": text,
                },
                "searched_query": json.dumps({"gene": gene, "source": "pharmcat_match_json"}, sort_keys=True),
                "captured_by": captured_by,
            }
        )
    return payloads


def _record_payloads_from_phenotype(phenotype_json: JsonObject, *, captured_by: str = "genomi call pharmacogenomics.run_pharmcat") -> list[JsonObject]:
    payloads = []
    for record in _as_dicts(phenotype_json.get("records")):
        gene = str(record.get("gene") or "").strip().upper()
        if not _phenotype_record_has_result(record):
            continue
        text = _phenotype_finding_text(record)
        if not gene or not text:
            continue
        payloads.append(
            {
                "target": {"type": "gene", "gene": gene},
                "source": _without_none({
                    "title": "PharmCAT phenotyper JSON artifact",
                    "url": "https://pharmcat.clinpgx.org/",
                    "type": "sample_pharmacogenomic_call",
                    "artifact": _artifact_source_summary(phenotype_json),
                    "artifact_metadata": phenotype_json.get("metadata") if isinstance(phenotype_json.get("metadata"), dict) else None,
                }),
                "finding": {
                    "type": "pharmcat_sample_pgx_phenotype",
                    "text": text,
                    "summary": text,
                },
                "searched_query": json.dumps({"gene": gene, "source": "pharmcat_phenotype_json"}, sort_keys=True),
                "captured_by": captured_by,
            }
        )
    return payloads


def _phenotype_record_has_result(record: JsonObject) -> bool:
    if str(record.get("call_source") or "").strip().upper() == "NONE":
        return False
    diplotypes = [*_as_dicts(record.get("source_diplotypes")), *_as_dicts(record.get("recommendation_diplotypes"))]
    if not diplotypes:
        return False
    for diplotype in diplotypes:
        label = str(diplotype.get("label") or "").strip().lower()
        phenotypes = [str(item).strip().lower() for item in _as_list(diplotype.get("phenotypes")) if item]
        activity = str(diplotype.get("activity_score") or "").strip().lower()
        if label and label not in {"unknown", "unknown/unknown", "no result"}:
            return True
        if any(phenotype not in {"unknown", "no result", "n/a"} for phenotype in phenotypes):
            return True
        if activity and activity not in {"unknown", "no result", "n/a"}:
            return True
    return False


def _report_finding_text(record: JsonObject) -> str:
    pieces = []
    drug = record.get("drug")
    genes = record.get("genes") or []
    if drug:
        pieces.append(f"PharmCAT recommendation for {drug}")
    if genes:
        pieces.append(f"genes {', '.join(str(gene) for gene in genes)}")
    if record.get("phenotypes"):
        pieces.append(f"phenotypes {', '.join(str(item) for item in record['phenotypes'])}")
    if record.get("recommendation"):
        pieces.append(f"recommendation {record['recommendation']}")
    if record.get("classification"):
        pieces.append(f"classification {record['classification']}")
    return "; ".join(pieces) + "." if pieces else ""


def _match_finding_text(record: JsonObject) -> str:
    pieces = []
    gene = record.get("gene")
    if gene:
        pieces.append(f"PharmCAT named allele match for {gene}")
    diplotypes = [str(item.get("name")) for item in _as_dicts(record.get("diplotypes")) if item.get("name")]
    if diplotypes:
        pieces.append(f"diplotypes {', '.join(diplotypes)}")
    scores = [str(item.get("score")) for item in _as_dicts(record.get("diplotypes")) if item.get("score") is not None]
    if scores:
        pieces.append(f"match scores {', '.join(scores)}")
    if record.get("warning_count"):
        pieces.append(f"warnings {record['warning_count']}")
    if record.get("uncallable_haplotype_count"):
        pieces.append(f"uncallable haplotypes {record['uncallable_haplotype_count']}")
    return "; ".join(pieces) + "." if pieces else ""


def _phenotype_finding_text(record: JsonObject) -> str:
    pieces = []
    gene = record.get("gene")
    if gene:
        pieces.append(f"PharmCAT phenotype for {gene}")
    source_labels = _diplotype_texts(record.get("source_diplotypes"))
    if source_labels:
        pieces.append(f"source diplotypes {', '.join(source_labels)}")
    recommendation_labels = _diplotype_texts(record.get("recommendation_diplotypes"))
    if recommendation_labels:
        pieces.append(f"recommendation diplotypes {', '.join(recommendation_labels)}")
    if record.get("call_source"):
        pieces.append(f"call source {record['call_source']}")
    if record.get("message_count"):
        pieces.append(f"messages {record['message_count']}")
    return "; ".join(pieces) + "." if pieces else ""


def _diplotype_texts(value: object) -> list[str]:
    texts = []
    for item in _as_dicts(value):
        parts = []
        if item.get("label"):
            parts.append(str(item["label"]))
        phenotypes = [str(phenotype) for phenotype in _as_list(item.get("phenotypes")) if phenotype]
        if phenotypes:
            parts.append(f"phenotype {'/'.join(phenotypes)}")
        if item.get("activity_score") is not None:
            parts.append(f"activity score {item['activity_score']}")
        if item.get("match_score") is not None:
            parts.append(f"match score {item['match_score']}")
        if parts:
            texts.append(" ".join(parts))
    return texts


def _readiness(returncode: int, artifacts: JsonObject) -> JsonObject:
    calls = artifacts.get("calls_only") or {}
    match = artifacts.get("named_allele_match_json") or {}
    phenotype = artifacts.get("phenotype_json") or {}
    missing = artifacts.get("missing_pgx_positions") or {}
    has_calls = bool(calls.get("available") and calls.get("row_count"))
    has_match = bool(match.get("available") and match.get("result_count"))
    has_phenotype = bool(phenotype.get("available") and phenotype.get("gene_report_count"))
    has_report = any(item.get("artifact_type") in {"report_json", "report_html"} for item in artifacts.get("files") or [])
    missing_count = int(missing.get("record_count") or 0)
    requirements = [
        "Confirm VCF build, normalization, included PGx positions, sample identity, and clinical context before medication decisions.",
    ]
    if missing_count:
        requirements.append("Review PharmCAT missing PGx positions before treating broad PGx output as coverage-sufficient for the selected question.")
    if returncode == 0 and not has_report and (has_calls or has_match or has_phenotype):
        requirements.append("Use report JSON or report HTML for drug recommendation text when medication-specific guidance is needed.")
    personal_support = "needs_more_evidence"
    if returncode == 0 and has_report:
        personal_support = "pharmcat_report_available"
    elif returncode == 0 and (has_calls or has_match or has_phenotype):
        personal_support = "pharmcat_sample_call_available"
    return {
        "status": "pharmcat_completed" if returncode == 0 else "pharmcat_failed",
        "has_calls_only_tsv": bool(calls.get("available")),
        "has_named_allele_match_json": bool(match.get("available")),
        "has_phenotype_json": bool(phenotype.get("available")),
        "has_parsed_gene_calls": has_calls,
        "has_parsed_match_records": has_match,
        "has_parsed_phenotype_records": has_phenotype,
        "has_report_artifact": has_report,
        "missing_pgx_position_count": missing_count,
        "personal_statement_support": personal_support,
        "requires_before_personal_actionability": requirements,
    }


def _record_payloads_from_calls(calls: JsonObject, *, captured_by: str = "genomi call pharmacogenomics.run_pharmcat") -> list[JsonObject]:
    payloads = []
    rows = calls.get("rows") or []
    for row in rows:
        if not isinstance(row, dict):
            continue
        gene = str(row.get("Gene") or row.get("gene") or "").strip().upper()
        if not gene:
            continue
        diplotype = row.get("Source Diplotype") or row.get("Recommendation Lookup Diplotype")
        phenotype = row.get("Phenotype") or row.get("Recommendation Lookup Phenotype")
        activity = row.get("Activity Score") or row.get("Recommendation Lookup Activity Score")
        text = _call_finding_text(gene=gene, diplotype=diplotype, phenotype=phenotype, activity=activity)
        payloads.append(
            {
                "target": {"type": "gene", "gene": gene},
                "source": _without_none({
                    "title": "PharmCAT sample PGx call artifact",
                    "url": "https://pharmcat.clinpgx.org/",
                    "type": "sample_pharmacogenomic_call",
                    "artifact": _artifact_source_summary(calls),
                }),
                "finding": {
                    "type": "pharmcat_sample_pgx_call",
                    "text": text,
                    "summary": text,
                },
                "searched_query": json.dumps({"gene": gene, "source": "pharmcat_calls_only_tsv"}, sort_keys=True),
                "captured_by": captured_by,
            }
        )
    return payloads


def _call_finding_text(*, gene: str, diplotype: object, phenotype: object, activity: object) -> str:
    pieces = [f"PharmCAT call for {gene}"]
    if diplotype:
        pieces.append(f"diplotype {diplotype}")
    if phenotype:
        pieces.append(f"phenotype {phenotype}")
    if activity:
        pieces.append(f"activity score {activity}")
    return "; ".join(pieces) + "."
