"""PGx dashboard row projection for native matrix contracts."""

from __future__ import annotations

from typing import Any

JsonObject = dict[str, Any]


def pgx_matrix_result_has_content(raw: JsonObject) -> bool:
    return bool(
        _as_dicts(_as_dict(raw.get("sample_pgx_matrix")).get("rows"))
        or _as_dicts(_as_dict(raw.get("medication_review_matrix")).get("rows"))
    )


def pgx_dashboard_rows_from_matrix_result(raw: JsonObject) -> list[JsonObject]:
    rows: list[JsonObject] = []
    for matrix_key in ("sample_pgx_matrix", "medication_review_matrix"):
        matrix = _as_dict(raw.get(matrix_key))
        if not matrix:
            continue
        for index, item in enumerate(_as_dicts(matrix.get("rows"))):
            row = _pgx_row_from_matrix_row(item)
            if not row:
                raise ValueError(f"{matrix_key} row {index} has no recognized PGx dashboard field.")
            rows.append(row)
    return merge_dashboard_pgx_rows(rows)


def normalize_dashboard_pgx_row(raw: Any) -> JsonObject | None:
    if not isinstance(raw, dict) or not raw:
        return None
    gene = _clean(raw.get("gene"))
    diplotype = _clean(raw.get("diplotype"))
    phenotype = _clean(raw.get("phenotype"))
    drugs = _normalize_dashboard_drugs(raw.get("drugs"))

    out: JsonObject = {}
    for key in ("row_id", "row_type"):
        if raw.get(key) not in (None, "", []):
            out[key] = raw[key]
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


def merge_dashboard_pgx_rows(rows: list[JsonObject]) -> list[JsonObject]:
    merged: dict[str, JsonObject] = {}
    order: list[str] = []
    for index, row in enumerate(rows):
        if not row:
            continue
        key = _pgx_merge_key(row, fallback_index=index)
        if key not in merged:
            merged[key] = dict(row)
            merged[key]["drugs"] = _normalize_dashboard_drugs(row.get("drugs"))
            order.append(key)
            continue
        target = merged[key]
        for field, value in row.items():
            if field == "drugs":
                continue
            if field == "evidence_classes":
                target[field] = _merge_string_lists(target.get(field), value)
            elif target.get(field) in (None, "", []) and value not in (None, "", []):
                target[field] = value
        target["drugs"] = _merge_drugs(target.get("drugs"), row.get("drugs"))
    return [{key: value for key, value in merged[row_key].items() if value not in (None, "", [])} for row_key in order]


def _pgx_row_from_matrix_row(raw: JsonObject) -> JsonObject | None:
    drug = _clean(raw.get("drug"))
    recommendation = _clean(raw.get("recommendation_text"))
    row = normalize_dashboard_pgx_row(
        {
            "gene": _clean(raw.get("gene")),
            "diplotype": _clean(raw.get("diplotype")),
            "phenotype": _clean(raw.get("phenotype")),
            "drugs": [{"name": drug, "recommendation": recommendation}] if drug or recommendation else [],
        }
    )
    if not row:
        return None
    for source_key, target_key in (
        ("row_id", "row_id"),
        ("row_type", "row_type"),
        ("rsid", "rsid"),
        ("variant_or_haplotype", "variant_or_haplotype"),
        ("activity_score", "activity_score"),
        ("recommendation_text", "recommendation_text"),
        ("clinical_boundary", "clinical_boundary"),
    ):
        value = raw.get(source_key)
        if value not in (None, "", []):
            row[target_key] = value
    evidence_classes = _unique_strings(_as_list(raw.get("evidence_classes")))
    if evidence_classes:
        row["evidence_classes"] = evidence_classes
    sample_relevance = _as_dict(raw.get("sample_relevance"))
    state = _clean(sample_relevance.get("state"))
    if state:
        row["sample_relevance_state"] = state
    readiness_value = raw.get("readiness")
    readiness = _as_dict(readiness_value)
    readiness_state = _clean(readiness.get("answer_readiness")) or _clean(readiness_value)
    if readiness_state:
        row["readiness"] = readiness_state
    return row


def _pgx_merge_key(row: JsonObject, *, fallback_index: int) -> str:
    drugs = _normalize_dashboard_drugs(row.get("drugs"))
    drug_names = "|".join(_clean(item.get("name")) or "" for item in drugs)
    recommendations = "|".join(_clean(item.get("recommendation")) or "" for item in drugs)
    context = [
        drug_names,
        _clean(row.get("gene")) or "",
        _clean(row.get("rsid")) or "",
        _clean(row.get("variant_or_haplotype")) or "",
        _clean(row.get("diplotype")) or "",
        _clean(row.get("phenotype")) or "",
        _clean(row.get("recommendation_text")) or recommendations,
        "|".join(_unique_strings(_as_list(row.get("evidence_classes")))),
    ]
    if any(context):
        return "pgx:" + "\x1f".join(value.lower() for value in context)
    return f"row:{fallback_index}"


def _merge_string_lists(left: Any, right: Any) -> list[str]:
    return _unique_strings([*_as_list(left), *_as_list(right)])


def _merge_drugs(left: Any, right: Any) -> list[JsonObject]:
    out: list[JsonObject] = []
    seen: set[tuple[str, str]] = set()
    for item in [*_normalize_dashboard_drugs(left), *_normalize_dashboard_drugs(right)]:
        name = str(item.get("name") or "")
        recommendation = str(item.get("recommendation") or "")
        key = (name.lower(), recommendation.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _normalize_dashboard_drugs(value: Any) -> list[JsonObject]:
    result: list[JsonObject] = []
    for item in _as_list(value):
        if isinstance(item, dict):
            drug = _clean(item.get("name"))
            recommendation = _clean(item.get("recommendation"))
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


def _strip_gene_prefix(value: str, gene: str | None) -> str:
    if gene and value.upper().startswith(gene.upper() + " "):
        return value.split(" ", 1)[1]
    return value


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
