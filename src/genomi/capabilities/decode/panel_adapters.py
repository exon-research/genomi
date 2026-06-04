"""Dashboard panel adapters for native capability result shapes."""

from __future__ import annotations

from typing import Any

JsonObject = dict[str, Any]


class PanelNormalizationError(Exception):
    """Raised when supplied panel rows are content-bearing but unmappable."""


def normalize_pgx_panel(raw: Any) -> list[JsonObject] | None:
    if isinstance(raw, list):
        return _normalize_pgx_list(raw)
    if isinstance(raw, dict) and _is_native_pgx_result(raw):
        return _pgx_rows_from_native(raw) or None
    return None


def normalize_risk_panel(raw: Any) -> list[JsonObject] | None:
    if not isinstance(raw, list):
        return None
    rows: list[JsonObject] = []
    for index, item in enumerate(raw):
        normalized = _normalize_risk_row(item)
        if not normalized:
            raise PanelNormalizationError(
                f"Panel 'risk' row {index} has no recognized dashboard field. "
                "Expected a dashboard risk row or native prs.calculate_score result."
            )
        rows.append(normalized)
    return rows or None


def is_native_empty_panel(panel: str, raw: Any) -> bool:
    if panel == "pgx" and isinstance(raw, dict) and _is_native_pgx_result(raw):
        return not _pgx_has_native_content(raw)
    if panel == "risk" and isinstance(raw, list) and raw:
        return all(_is_empty_prs_result(item) for item in raw)
    return False


def _normalize_pgx_list(raw: list[Any]) -> list[JsonObject] | None:
    rows: list[JsonObject] = []
    for index, item in enumerate(raw):
        normalized = _normalize_pgx_row(item)
        if not normalized:
            raise PanelNormalizationError(
                f"Panel 'pgx' row {index} has no recognized dashboard field. "
                "Expected a dashboard PGx row, PharmCAT call row, or PharmCAT recommendation row."
            )
        rows.append(normalized)
    return _merge_pgx_rows(rows) or None


def _pgx_rows_from_native(raw: JsonObject) -> list[JsonObject]:
    if isinstance(raw.get("artifacts"), dict):
        return _pgx_rows_from_pharmcat(raw)
    if _is_pgx_review_result(raw):
        return _pgx_rows_from_review(raw)
    return []


def _pgx_rows_from_pharmcat(raw: JsonObject) -> list[JsonObject]:
    artifacts = _as_dict(raw.get("artifacts"))
    rows: list[JsonObject] = []
    calls = _as_dict(artifacts.get("calls_only"))
    for index, item in enumerate(_as_dicts(calls.get("rows"))):
        row = _normalize_pgx_row(item)
        if not row:
            raise PanelNormalizationError(
                f"Panel 'pgx' PharmCAT calls row {index} has no recognized dashboard field."
            )
        rows.append(row)

    phenotype = _as_dict(artifacts.get("phenotype_json"))
    for item in _as_dicts(phenotype.get("records")):
        row = _pgx_row_from_phenotype_record(item)
        if row:
            rows.append(row)

    report = _as_dict(artifacts.get("report_json"))
    recommendations = _as_dict(report.get("recommendations"))
    for item in _as_dicts(recommendations.get("records")):
        rows.extend(_pgx_rows_from_recommendation_record(item))
    return _merge_pgx_rows(rows)


def _pgx_rows_from_review(raw: JsonObject) -> list[JsonObject]:
    query = _as_dict(raw.get("query"))
    sample_evidence = _as_dict(raw.get("sample_evidence"))
    answer_support = _as_dict(raw.get("answer_support"))
    query_drug = _clean(_pick(query, "drug", "raw_drug"))
    query_gene = _clean(query.get("gene"))
    recommendations = _as_dicts(answer_support.get("source_recommendation_summaries"))
    rows: list[JsonObject] = []

    for item in _as_dicts(answer_support.get("star_diplotype_summaries")):
        gene = _clean(_pick(item, "gene"))
        row = _normalize_pgx_row(
            {
                "gene": gene,
                "diplotype": _pick(item, "possible_diplotype", "diplotype"),
                "phenotype": _pick(item, "predicted_phenotype", "phenotype"),
                "drugs": _drugs_for_gene(recommendations, gene, fallback_drug=query_drug),
            }
        )
        if row:
            rows.append(row)

    for item in _as_dicts(sample_evidence.get("user_provided_sample_evidence")):
        gene = _clean(_pick(item, "gene", "known_gene"))
        row = _normalize_pgx_row(
            {
                "gene": gene,
                "diplotype": _pick(item, "known_diplotype", "diplotype"),
                "phenotype": _pick(item, "known_phenotype", "phenotype"),
                "drugs": _drugs_for_gene(recommendations, gene, fallback_drug=query_drug),
            }
        )
        if row:
            rows.append(row)

    if not rows:
        genes = _unique_strings(
            [
                query_gene,
                *_as_list(sample_evidence.get("star_gene_targets")),
                *(_pick(item, "gene") for item in recommendations),
            ]
        )
        for gene in genes:
            row = _normalize_pgx_row(
                {
                    "gene": gene,
                    "drugs": _drugs_for_gene(recommendations, gene, fallback_drug=query_drug),
                }
            )
            if row:
                rows.append(row)
    return _merge_pgx_rows(rows)


def _pgx_row_from_phenotype_record(raw: JsonObject) -> JsonObject | None:
    gene = _clean(_pick(raw, "gene"))
    diplotypes = [
        *_as_dicts(raw.get("source_diplotypes")),
        *_as_dicts(raw.get("recommendation_diplotypes")),
    ]
    first = _first_diplotype_with_result(diplotypes)
    if not gene or first is None:
        return None
    return _normalize_pgx_row(
        {
            "gene": gene,
            "diplotype": first.get("label"),
            "phenotype": _first_string(first.get("phenotypes")),
        }
    )


def _pgx_rows_from_recommendation_record(raw: JsonObject) -> list[JsonObject]:
    rows: list[JsonObject] = []
    genes = _unique_strings(_as_list(raw.get("genes")))
    if not genes:
        genes = _genes_from_diplotype_strings(_as_list(raw.get("diplotypes")))
    for gene in genes:
        rows.append(
            _normalize_pgx_row(
                {
                    "gene": gene,
                    "diplotype": _diplotype_for_gene(raw.get("diplotypes"), gene),
                    "phenotype": _first_string(raw.get("phenotypes")),
                    "drugs": [_drug_from_recommendation(raw)],
                }
            )
        )
    return [row for row in rows if row]


def _normalize_pgx_row(raw: Any) -> JsonObject | None:
    if not isinstance(raw, dict) or not raw:
        return None
    gene = _clean(_pick(raw, "gene", "Gene"))
    if isinstance(raw.get("genes"), list):
        gene = gene or _first_string(raw.get("genes"))
    diplotype = _clean(
        _pick(
            raw,
            "diplotype",
            "Source Diplotype",
            "Recommendation Lookup Diplotype",
            "possible_diplotype",
        )
    )
    if not diplotype:
        diplotype = _diplotype_for_gene(raw.get("diplotypes"), gene)
    phenotype = _clean(
        _pick(
            raw,
            "phenotype",
            "Phenotype",
            "Recommendation Lookup Phenotype",
            "predicted_phenotype",
        )
    )
    if not phenotype:
        phenotype = _first_string(raw.get("phenotypes"))
    drugs = _normalize_drugs(raw.get("drugs"))
    if not drugs and _looks_like_recommendation(raw):
        drugs = [_drug_from_recommendation(raw)]

    out: JsonObject = {}
    if gene:
        out["gene"] = gene
    if diplotype:
        out["diplotype"] = _strip_gene_prefix(diplotype, gene)
    if phenotype:
        out["phenotype"] = phenotype
    impact = _clean(raw.get("impact")) or _impact_from_phenotype(phenotype)
    if impact:
        out["impact"] = impact
    if drugs:
        out["drugs"] = drugs
    return out or None


def _normalize_risk_row(raw: Any) -> JsonObject | None:
    if not isinstance(raw, dict) or not raw:
        return None
    score = _as_dict(raw.get("polygenic_score"))
    sample_qc = _as_dict(raw.get("sample_qc"))
    score_result = _as_dict(raw.get("score_result"))
    calibration = _as_dict(score_result.get("calibration"))
    interpretation = _as_dict(raw.get("interpretation"))

    trait = _clean(_pick(raw, "trait", "reported_trait", "name")) or _clean(
        _pick(score, "reported_trait", "name", "pgs_id")
    )
    score_value = _pick(raw, "score")
    if score_value is None:
        score_value = _pick(calibration, "z_score", "standardized_score")
    if score_value is None:
        score_value = _pick(score_result, "raw_weighted_score")
    percentile = _pick(raw, "percentile", "percentile_rank") or _pick(
        calibration, "percentile", "percentile_rank"
    )
    sources = _normalize_sources(raw.get("sources"))
    pgs_id = _clean(_pick(score, "pgs_id") or _pick(raw, "pgs_id"))
    if not sources and pgs_id:
        sources = [pgs_id]
    overlap = _pick(raw, "overlap") or _risk_overlap(sample_qc)
    note = _clean(_pick(raw, "note")) or _clean(
        _pick(interpretation, "summary") or _pick(sample_qc, "note")
    )

    out: JsonObject = {}
    if trait:
        out["trait"] = trait
    if score_value is not None:
        out["score"] = score_value
    if percentile is not None:
        out["percentile"] = percentile
    ancestry_adjusted = _pick(raw, "ancestryAdjusted", "ancestry_adjusted")
    if ancestry_adjusted is not None:
        out["ancestryAdjusted"] = ancestry_adjusted
    elif calibration:
        out["ancestryAdjusted"] = False
    if overlap:
        out["overlap"] = overlap
    if sources:
        out["sources"] = sources
    if note:
        out["note"] = note
    if not out.get("trait"):
        return None
    return out or None


def _is_native_pgx_result(raw: JsonObject) -> bool:
    schema = str(raw.get("schema") or "")
    return (
        schema in {"genomi-pharmcat-run-v1", "genomi-pharmcat-artifact-import-v1", "genomi-pgx-medication-review-v1"}
        or isinstance(raw.get("artifacts"), dict)
        or _is_pgx_review_result(raw)
    )


def _is_pgx_review_result(raw: JsonObject) -> bool:
    return any(isinstance(raw.get(key), dict) for key in ("public_evidence", "sample_evidence", "answer_support"))


def _pgx_has_native_content(raw: JsonObject) -> bool:
    artifacts = _as_dict(raw.get("artifacts"))
    if artifacts:
        calls = _as_dict(artifacts.get("calls_only"))
        report = _as_dict(artifacts.get("report_json"))
        recommendations = _as_dict(report.get("recommendations"))
        phenotype = _as_dict(artifacts.get("phenotype_json"))
        return bool(
            _as_dicts(calls.get("rows"))
            or _as_dicts(recommendations.get("records"))
            or _as_dicts(phenotype.get("records"))
        )
    return _pgx_review_has_mappable_content(raw)


def _pgx_review_has_mappable_content(raw: JsonObject) -> bool:
    answer_support = _as_dict(raw.get("answer_support"))
    sample_evidence = _as_dict(raw.get("sample_evidence"))
    query = _as_dict(raw.get("query"))
    recommendations = _as_dicts(answer_support.get("source_recommendation_summaries"))
    return bool(
        _clean(query.get("gene"))
        or _unique_strings(_as_list(sample_evidence.get("star_gene_targets")))
        or any(_clean(_pick(item, "gene")) for item in recommendations)
        or any(
            _clean(_pick(item, "gene"))
            for item in _as_dicts(answer_support.get("star_diplotype_summaries"))
        )
        or any(
            _clean(_pick(item, "gene", "known_gene"))
            for item in _as_dicts(sample_evidence.get("user_provided_sample_evidence"))
        )
    )


def _is_empty_prs_result(raw: Any) -> bool:
    if not isinstance(raw, dict):
        return False
    empty_statuses = {
        "requires_score_import",
        "requires_library_install",
        "out_of_scope_for_input",
        "source_unavailable",
    }
    if str(raw.get("status") or "") not in empty_statuses:
        return False
    return not any(isinstance(raw.get(key), dict) for key in ("polygenic_score", "sample_qc", "score_result"))


def _merge_pgx_rows(rows: list[JsonObject]) -> list[JsonObject]:
    merged: dict[str, JsonObject] = {}
    order: list[str] = []
    for row in rows:
        if not row:
            continue
        key = _clean(row.get("gene")) or f"row:{len(order)}"
        if key not in merged:
            merged[key] = {}
            order.append(key)
        target = merged[key]
        for field in ("gene", "diplotype", "phenotype", "impact"):
            if target.get(field) in (None, "", []) and row.get(field) not in (None, "", []):
                target[field] = row[field]
        target["drugs"] = _merge_drugs(target.get("drugs"), row.get("drugs"))
    return [{k: v for k, v in merged[key].items() if v not in (None, "", [])} for key in order]


def _merge_drugs(left: Any, right: Any) -> list[JsonObject]:
    out: list[JsonObject] = []
    seen: set[tuple[str, str]] = set()
    for item in [*_normalize_drugs(left), *_normalize_drugs(right)]:
        name = str(item.get("name") or "")
        recommendation = str(item.get("recommendation") or "")
        key = (name.lower(), recommendation.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _normalize_drugs(value: Any) -> list[JsonObject]:
    result: list[JsonObject] = []
    for item in _as_list(value):
        if isinstance(item, dict):
            drug = _clean(_pick(item, "name", "drug", "label"))
            recommendation = _clean(_pick(item, "recommendation", "summary", "drugRecommendation"))
        else:
            drug = _clean(item)
            recommendation = None
        if drug or recommendation:
            row: JsonObject = {}
            if drug:
                row["name"] = drug
            if recommendation:
                row["recommendation"] = recommendation
            result.append(row)
    return result


def _drug_from_recommendation(raw: JsonObject) -> JsonObject:
    row: JsonObject = {}
    drug = _clean(_pick(raw, "drug", "name"))
    recommendation = _clean(_pick(raw, "recommendation", "summary", "drugRecommendation"))
    if not recommendation:
        recommendation = "; ".join(str(item) for item in _as_list(raw.get("implications")) if item) or None
    if drug:
        row["name"] = drug
    if recommendation:
        row["recommendation"] = recommendation
    return row


def _drugs_for_gene(recommendations: list[JsonObject], gene: str | None, *, fallback_drug: str | None) -> list[JsonObject]:
    rows: list[JsonObject] = []
    for item in recommendations:
        record_gene = _clean(_pick(item, "gene"))
        if gene and record_gene and record_gene != gene:
            continue
        row = _drug_from_recommendation(item)
        if row:
            rows.append(row)
    if not rows and fallback_drug:
        rows.append({"name": fallback_drug})
    return rows


def _looks_like_recommendation(raw: JsonObject) -> bool:
    return bool(_pick(raw, "drug", "name") and _pick(raw, "recommendation", "summary", "drugRecommendation"))


def _impact_from_phenotype(value: str | None) -> str | None:
    text = (value or "").strip().lower()
    if not text or text in {"unknown", "no result", "n/a"}:
        return None
    if "poor" in text:
        return "poor"
    if any(token in text for token in ("intermediate", "reduced", "decreased", "loss")):
        return "reduced"
    if any(token in text for token in ("rapid", "ultrarapid", "increased")):
        return "increased"
    if any(token in text for token in ("normal", "extensive")):
        return "normal"
    return None


def _risk_overlap(sample_qc: JsonObject) -> str | None:
    matched = sample_qc.get("matched_variant_count")
    total = sample_qc.get("score_variant_count")
    if isinstance(matched, (int, float)) and isinstance(total, (int, float)) and total:
        return f"{int(matched)}/{int(total)} variants"
    return None


def _first_diplotype_with_result(items: list[JsonObject]) -> JsonObject | None:
    for item in items:
        label = _clean(item.get("label"))
        phenotypes = [_clean(value) for value in _as_list(item.get("phenotypes"))]
        phenotypes = [value for value in phenotypes if value and value.lower() not in {"unknown", "no result", "n/a"}]
        if label and label.lower() not in {"unknown", "unknown/unknown", "no result"}:
            return item
        if phenotypes:
            return item
    return None


def _diplotype_for_gene(value: Any, gene: str | None) -> str | None:
    gene_text = _clean(gene)
    for item in _as_list(value):
        text = _clean(item)
        if not text:
            continue
        if not gene_text or text.upper().startswith(gene_text.upper() + " "):
            return _strip_gene_prefix(text, gene_text)
    return None


def _genes_from_diplotype_strings(value: list[Any]) -> list[str]:
    genes: list[str] = []
    for item in value:
        text = _clean(item)
        if not text or " " not in text:
            continue
        genes.append(text.split(" ", 1)[0])
    return _unique_strings(genes)


def _strip_gene_prefix(value: str, gene: str | None) -> str:
    if gene and value.upper().startswith(gene.upper() + " "):
        return value.split(" ", 1)[1]
    return value


def _normalize_sources(value: Any) -> list[str]:
    return _unique_strings(_as_list(value))


def _unique_strings(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _clean(value)
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _first_string(value: Any) -> str | None:
    for item in _as_list(value):
        text = _clean(item)
        if text:
            return text
    return None


def _pick(d: dict, *keys: str) -> Any:
    for key in keys:
        if key in d and d[key] not in (None, "", []):
            return d[key]
    return None


def _as_dict(value: Any) -> JsonObject:
    return value if isinstance(value, dict) else {}


def _as_dicts(value: Any) -> list[JsonObject]:
    return [item for item in _as_list(value) if isinstance(item, dict)]


def _as_list(value: Any) -> list[Any]:
    if value in (None, "", []):
        return []
    return value if isinstance(value, list) else [value]


def _clean(value: Any) -> str | None:
    if value in (None, "", []):
        return None
    text = str(value).strip()
    return text or None
