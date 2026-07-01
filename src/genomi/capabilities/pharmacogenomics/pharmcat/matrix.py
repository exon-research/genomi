from __future__ import annotations

import hashlib
import json
from typing import Any

from ....evidence import envelope as _env
from ._common import JsonObject, _as_dicts, _as_list, _without_none

SAMPLE_PGX_MATRIX_POLICY_ID = "pharmcat_sample_pgx_matrix_v1"
MEDICATION_REVIEW_TARGETS_POLICY_ID = "pharmcat_medication_review_targets_v1"
DEFAULT_MEDICATION_REVIEW_TARGET_LIMIT = 12


def build_sample_pgx_matrix(artifacts: JsonObject) -> JsonObject:
    rows: list[JsonObject] = []
    rows.extend(_rows_from_report(artifacts.get("report_json") if isinstance(artifacts.get("report_json"), dict) else {}))
    rows.extend(_rows_from_phenotype(artifacts.get("phenotype_json") if isinstance(artifacts.get("phenotype_json"), dict) else {}))
    rows.extend(_rows_from_calls(artifacts.get("calls_only") if isinstance(artifacts.get("calls_only"), dict) else {}))
    rows.extend(_rows_from_match(artifacts.get("named_allele_match_json") if isinstance(artifacts.get("named_allele_match_json"), dict) else {}))
    rows = _dedupe_rows(rows)
    return {
        "policy_id": SAMPLE_PGX_MATRIX_POLICY_ID,
        "row_count": len(rows),
        "rows": rows,
        "traceability": _traceability(rows),
    }


def build_medication_review_targets(
    sample_pgx_matrix: Any,
    *,
    limit: int = DEFAULT_MEDICATION_REVIEW_TARGET_LIMIT,
) -> JsonObject:
    rows = _as_dicts(sample_pgx_matrix.get("rows")) if isinstance(sample_pgx_matrix, dict) else []
    targets: list[JsonObject] = []
    seen: set[tuple[str, ...]] = set()
    for row in rows:
        if not _has_medication_scope(row):
            continue
        target = _medication_review_target_from_row(row)
        if not target:
            continue
        key = _medication_review_target_key(target)
        if key in seen:
            continue
        seen.add(key)
        targets.append(target)
        if len(targets) >= max(1, int(limit)):
            break
    return {
        "policy_id": MEDICATION_REVIEW_TARGETS_POLICY_ID,
        "target_count": len(targets),
        "targets": targets,
        "traceability": {
            "sample_pgx_matrix_policy_id": (
                sample_pgx_matrix.get("policy_id") if isinstance(sample_pgx_matrix, dict) else None
            ),
            "sample_pgx_row_ids": [
                target["source_sample_pgx_row_id"]
                for target in targets
                if target.get("source_sample_pgx_row_id")
            ],
        },
    }


def _rows_from_report(report_json: JsonObject) -> list[JsonObject]:
    artifact_ids = _artifact_ids(report_json)
    rows: list[JsonObject] = []
    recommendations = report_json.get("recommendations") if isinstance(report_json.get("recommendations"), dict) else {}
    for record in _as_dicts(recommendations.get("records")):
        genes = [str(item).strip().upper() for item in _as_list(record.get("genes")) if str(item).strip()]
        if not genes:
            genes = _genes_from_diplotypes(record.get("diplotypes"))
        for gene in genes or [None]:
            diplotype = _diplotype_for_gene(record.get("diplotypes"), gene)
            phenotype = _first_string(record.get("phenotypes"))
            rows.append(
                _row(
                    row_type="drug_gene_diplotype" if diplotype else "drug_gene_phenotype",
                    drug=record.get("drug"),
                    gene=gene,
                    diplotype=diplotype,
                    phenotype=phenotype,
                    recommendation_text=record.get("recommendation") or _first_string(record.get("implications")),
                    evidence_classes=["pharmcat_sample_pgx_recommendation"],
                    source_artifact_ids=artifact_ids,
                    clinical_boundary=_clinical_boundary(report_json),
                )
            )
    return rows


def _rows_from_phenotype(phenotype_json: JsonObject) -> list[JsonObject]:
    artifact_ids = _artifact_ids(phenotype_json)
    rows: list[JsonObject] = []
    for record in _as_dicts(phenotype_json.get("records")):
        gene = _clean_gene(record.get("gene"))
        if not gene:
            continue
        diplotypes = [
            *_as_dicts(record.get("source_diplotypes")),
            *_as_dicts(record.get("recommendation_diplotypes")),
        ]
        if not diplotypes:
            continue
        for diplotype in diplotypes:
            label = _clean(diplotype.get("label"))
            phenotype = _first_string(diplotype.get("phenotypes"))
            activity_score = diplotype.get("activity_score")
            if not any((label, phenotype, activity_score)):
                continue
            rows.append(
                _row(
                    row_type="sample_only",
                    gene=gene,
                    diplotype=label,
                    phenotype=phenotype,
                    activity_score=activity_score,
                    evidence_classes=["pharmcat_sample_pgx_phenotype"],
                    source_artifact_ids=artifact_ids,
                    clinical_boundary=_clinical_boundary(phenotype_json),
                )
            )
    return rows


def _rows_from_calls(calls: JsonObject) -> list[JsonObject]:
    artifact_ids = _artifact_ids(calls)
    rows: list[JsonObject] = []
    for record in _as_dicts(calls.get("rows")):
        gene = _clean_gene(record.get("Gene") or record.get("gene"))
        if not gene:
            continue
        rows.append(
            _row(
                row_type="sample_only",
                gene=gene,
                diplotype=record.get("Source Diplotype") or record.get("Recommendation Lookup Diplotype"),
                phenotype=record.get("Phenotype") or record.get("Recommendation Lookup Phenotype"),
                activity_score=record.get("Activity Score") or record.get("Recommendation Lookup Activity Score"),
                evidence_classes=["pharmcat_sample_pgx_call"],
                source_artifact_ids=artifact_ids,
                clinical_boundary=_clinical_boundary(calls),
            )
        )
    return rows


def _rows_from_match(match_json: JsonObject) -> list[JsonObject]:
    artifact_ids = _artifact_ids(match_json)
    rows: list[JsonObject] = []
    for record in _as_dicts(match_json.get("records")):
        gene = _clean_gene(record.get("gene"))
        if not gene:
            continue
        diplotypes = _as_dicts(record.get("diplotypes"))
        if not diplotypes:
            rows.append(
                _row(
                    row_type="sample_only",
                    gene=gene,
                    evidence_classes=["pharmcat_sample_pgx_match"],
                    source_artifact_ids=artifact_ids,
                    clinical_boundary=_clinical_boundary(match_json),
                )
            )
            continue
        for diplotype in diplotypes:
            rows.append(
                _row(
                    row_type="sample_only",
                    gene=gene,
                    diplotype=diplotype.get("name"),
                    evidence_classes=["pharmcat_sample_pgx_match"],
                    source_artifact_ids=artifact_ids,
                    clinical_boundary=_clinical_boundary(match_json),
                )
            )
    return rows


def _row(
    *,
    row_type: str,
    drug: object = None,
    gene: object = None,
    rsid: object = None,
    variant_or_haplotype: object = None,
    diplotype: object = None,
    phenotype: object = None,
    activity_score: object = None,
    recommendation_text: object = None,
    evidence_classes: list[str],
    source_artifact_ids: list[str],
    clinical_boundary: list[str],
) -> JsonObject:
    row = _without_none(
        {
            "row_type": row_type,
            "drug": _clean(drug),
            "gene": _clean_gene(gene),
            "rsid": _clean(rsid),
            "variant_or_haplotype": _clean(variant_or_haplotype) or _clean(rsid),
            "diplotype": _clean(diplotype),
            "phenotype": _clean(phenotype),
            "activity_score": activity_score,
            "recommendation_text": _clean(recommendation_text),
            "evidence_classes": evidence_classes,
            "source_artifact_ids": source_artifact_ids,
            "source_evidence_ids": [],
            "sample_evidence_ids": source_artifact_ids,
            "sample_relevance": {
                "state": "sample_target_observed",
                "matched_sample_evidence_ids": source_artifact_ids,
            },
            "readiness": _env.NEEDS_CLINICAL_CONFIRMATION if _clean(drug) else _env.CANNOT_ANSWER_YET,
            "clinical_boundary": clinical_boundary,
        }
    )
    row["row_id"] = _row_id(row)
    return row


def _artifact_ids(artifact: JsonObject) -> list[str]:
    source = artifact.get("artifact") if isinstance(artifact.get("artifact"), dict) else {}
    artifact_id = source.get("artifact_id")
    return [str(artifact_id)] if artifact_id else []


def _clinical_boundary(_artifact: JsonObject) -> list[str]:
    return [
        "sample identity",
        "PharmCAT input coverage and missing-position review",
        "clinical indication and current medications",
        "clinician or pharmacist confirmation",
    ]


def _row_id(row: JsonObject) -> str:
    identity = {
        "row_type": row.get("row_type"),
        "drug": row.get("drug"),
        "gene": row.get("gene"),
        "rsid": row.get("rsid"),
        "variant_or_haplotype": row.get("variant_or_haplotype"),
        "diplotype": row.get("diplotype"),
        "phenotype": row.get("phenotype"),
        "evidence_classes": row.get("evidence_classes"),
        "source_artifact_ids": row.get("source_artifact_ids"),
    }
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    return f"samplepgx_{digest[:16]}"


def _dedupe_rows(rows: list[JsonObject]) -> list[JsonObject]:
    output: list[JsonObject] = []
    seen: set[str] = set()
    for row in rows:
        row_id = str(row.get("row_id") or "")
        if not row_id or row_id in seen:
            continue
        seen.add(row_id)
        output.append(row)
    return output


def _traceability(rows: list[JsonObject]) -> JsonObject:
    artifact_ids = sorted(
        {
            str(artifact_id)
            for row in rows
            for artifact_id in row.get("source_artifact_ids") or []
            if artifact_id
        }
    )
    row_type_counts: dict[str, int] = {}
    evidence_class_counts: dict[str, int] = {}
    for row in rows:
        row_type = str(row.get("row_type") or "unknown")
        row_type_counts[row_type] = row_type_counts.get(row_type, 0) + 1
        for evidence_class in row.get("evidence_classes") or []:
            key = str(evidence_class)
            evidence_class_counts[key] = evidence_class_counts.get(key, 0) + 1
    return {
        "row_ids": [row["row_id"] for row in rows if row.get("row_id")],
        "unique_row_id_count": len({row.get("row_id") for row in rows if row.get("row_id")}),
        "artifact_ids": artifact_ids,
        "row_type_counts": row_type_counts,
        "evidence_class_counts": evidence_class_counts,
    }


def _has_medication_scope(row: JsonObject) -> bool:
    if any(row.get(field) not in (None, "", []) for field in ("drug", "atc_code", "drugbank_id")):
        return True
    # Gene-only calls remain sample PGx evidence. They should not trigger a
    # medication review unless the artifact row carries medication context.
    return bool(row.get("rsid") and str(row.get("row_type") or "") == "drug_gene_variant")


def _medication_review_target_from_row(row: JsonObject) -> JsonObject:
    target: JsonObject = {}
    for key in ("drug", "gene", "rsid", "atc_code", "drugbank_id"):
        value = row.get(key)
        if value not in (None, "", []):
            target[key] = value
    for source_key, target_key in (
        ("diplotype", "known_diplotype"),
        ("phenotype", "known_phenotype"),
        ("activity_score", "known_activity_score"),
    ):
        value = row.get(source_key)
        if value not in (None, "", []):
            target[target_key] = value
    if not target:
        return {}
    target["known_pgx_source"] = "pharmcat_sample_pgx_matrix"
    target["source_sample_pgx_row_id"] = row.get("row_id")
    return {key: value for key, value in target.items() if value not in (None, "", [])}


def _medication_review_target_key(target: JsonObject) -> tuple[str, ...]:
    fields = (
        "drug",
        "gene",
        "rsid",
        "atc_code",
        "drugbank_id",
        "known_diplotype",
        "known_phenotype",
        "known_activity_score",
        "source_sample_pgx_row_id",
    )
    return tuple(str(target.get(field) or "").casefold() for field in fields)


def _genes_from_diplotypes(value: object) -> list[str]:
    genes: list[str] = []
    for text in _as_list(value):
        cleaned = _clean(text)
        if cleaned and " " in cleaned:
            genes.append(cleaned.split(" ", 1)[0].upper())
    return sorted(set(genes))


def _diplotype_for_gene(value: object, gene: object) -> str | None:
    gene_text = _clean_gene(gene)
    for item in _as_list(value):
        text = _clean(item)
        if not text:
            continue
        if not gene_text:
            return text
        prefix = gene_text + " "
        if text.upper().startswith(prefix):
            return text[len(prefix):]
    return None


def _first_string(value: object) -> str | None:
    for item in _as_list(value):
        text = _clean(item)
        if text:
            return text
    return None


def _clean_gene(value: object) -> str | None:
    text = _clean(value)
    return text.upper() if text else None


def _clean(value: object) -> str | None:
    if value in (None, "", []):
        return None
    text = " ".join(str(value).split())
    return text or None
