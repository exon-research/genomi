"""Dashboard panel adapters for native capability result shapes."""

from __future__ import annotations

from typing import Any

from ...evidence.store.candidate_groups import missing_interpretation_gates
from .pgx_panel_rows import (
    merge_dashboard_pgx_rows,
    normalize_dashboard_pgx_row,
    pgx_dashboard_rows_from_matrix_result,
    pgx_matrix_result_has_content,
)
from .panel_states import (
    EMPTY_COVERAGE_STATES,
    EMPTY_NATIVE_STATUSES,
    EMPTY_PGX_STATUSES,
    EMPTY_PRS_STATUSES,
)

JsonObject = dict[str, Any]
_EMPTY_ENVELOPE_FINDING_STATES = {
    "not_assessed",
    "blocked_missing_library",
    "materialization_incomplete",
    "not_observed_in_consulted_scope",
}


class PanelNormalizationError(Exception):
    """Raised when supplied panel rows are content-bearing but unmappable."""


def normalize_pgx_panel(raw: Any) -> list[JsonObject] | None:
    if isinstance(raw, list):
        return _pgx_rows_from_list(raw) or None
    if isinstance(raw, dict) and _is_native_pgx_result(raw):
        return _pgx_rows_from_native(raw) or None
    return None


def normalize_risk_panel(raw: Any) -> list[JsonObject] | None:
    if isinstance(raw, dict) and _is_native_phenotype_review(raw):
        return _risk_rows_from_phenotype_review(raw) or None
    if isinstance(raw, dict) and _is_native_clinvar_risk_result(raw):
        return _risk_rows_from_clinvar_result(raw) or None
    if not isinstance(raw, list):
        return None
    rows: list[JsonObject] = []
    for index, item in enumerate(raw):
        if _is_empty_risk_list_item(item):
            continue
        if isinstance(item, dict) and _is_native_phenotype_review(item):
            rows.extend(_risk_rows_from_phenotype_review(item))
            continue
        if isinstance(item, dict) and _is_native_clinvar_risk_result(item):
            rows.extend(_risk_rows_from_clinvar_result(item))
            continue
        normalized = _normalize_native_prs_row(item) if _is_native_prs_result(item) else _normalize_dashboard_risk_row(item)
        if not normalized:
            raise PanelNormalizationError(
                f"Panel 'risk' row {index} has no recognized dashboard field. "
                "Expected a dashboard risk row, native prs.calculate_score result, native ClinVar review groups, "
                "or native phenotype review result."
            )
        rows.append(normalized)
    return rows or None


def native_panel_rows(panel: str, raw: Any) -> list[JsonObject] | None:
    if not isinstance(raw, dict):
        return None
    if panel in {"variants", "variants_all"}:
        return _native_clinvar_rows(raw)
    if panel == "nutrigenomics":
        return _native_nutrigenomics_rows(raw)
    return None


def is_native_empty_panel(panel: str, raw: Any) -> bool:
    if panel == "pgx" and isinstance(raw, list) and raw:
        return all(_is_empty_pgx_list_item(item) for item in raw)
    if panel == "pgx" and isinstance(raw, dict) and _is_native_pgx_result(raw):
        return not _pgx_has_native_content(raw)
    if panel == "risk" and isinstance(raw, list) and raw:
        return all(_is_empty_risk_list_item(item) for item in raw)
    if panel == "risk" and isinstance(raw, dict) and _is_native_phenotype_review(raw):
        return not _risk_rows_from_phenotype_review(raw)
    if panel == "risk" and isinstance(raw, dict) and _is_native_clinvar_risk_result(raw):
        return not _risk_rows_from_clinvar_result(raw)
    if panel in {"variants", "variants_all", "nutrigenomics"} and isinstance(raw, dict):
        rows = native_panel_rows(panel, raw)
        if rows is not None:
            return not rows
        return _has_empty_native_status(raw)
    if panel == "ancestry" and isinstance(raw, dict):
        return _has_empty_native_status(raw)
    return False


def _native_clinvar_rows(raw: JsonObject) -> list[JsonObject] | None:
    if "candidate_inventory" in raw:
        return _as_dicts(raw.get("candidate_inventory"))
    return None


def _native_nutrigenomics_rows(raw: JsonObject) -> list[JsonObject] | None:
    if "markers" in raw:
        return _as_dicts(raw.get("markers"))
    if "records" in raw:
        return _as_dicts(raw.get("records"))
    return None


def _has_empty_native_status(raw: JsonObject) -> bool:
    status = str(raw.get("status") or "")
    coverage_state = str(raw.get("coverage_state") or "")
    return status in EMPTY_NATIVE_STATUSES or coverage_state in EMPTY_COVERAGE_STATES


def _pgx_rows_from_list(raw: list[Any]) -> list[JsonObject]:
    rows: list[JsonObject] = []
    for index, item in enumerate(raw):
        if _is_empty_pgx_list_item(item):
            continue
        if isinstance(item, dict) and _is_native_pgx_result(item):
            try:
                rows.extend(pgx_dashboard_rows_from_matrix_result(item))
            except ValueError as exc:
                raise PanelNormalizationError(f"Panel 'pgx' {exc}") from exc
            continue
        normalized = normalize_dashboard_pgx_row(item)
        if not normalized:
            raise PanelNormalizationError(
                f"Panel 'pgx' row {index} has no recognized dashboard field. "
                "Expected a dashboard PGx row or native PGx matrix result."
            )
        rows.append(normalized)
    return merge_dashboard_pgx_rows(rows)


def _pgx_rows_from_native(raw: JsonObject) -> list[JsonObject]:
    try:
        return pgx_dashboard_rows_from_matrix_result(raw)
    except ValueError as exc:
        raise PanelNormalizationError(f"Panel 'pgx' {exc}") from exc


def _normalize_dashboard_risk_row(raw: Any) -> JsonObject | None:
    if not isinstance(raw, dict) or not raw:
        return None
    out: JsonObject = {}
    row_type = _clean(raw.get("row_type") or raw.get("rowType"))
    if row_type:
        out["row_type"] = row_type
    for key in ("trait", "score", "percentile", "ancestryAdjusted", "overlap", "note"):
        if raw.get(key) not in (None, "", []):
            out[key] = raw[key]
    sources = _normalize_sources(raw.get("sources"))
    if sources:
        out["sources"] = sources
    if not out.get("trait"):
        return None
    return out or None


def _normalize_native_prs_row(raw: Any) -> JsonObject | None:
    if not isinstance(raw, dict) or not raw:
        return None
    score = _as_dict(raw.get("polygenic_score"))
    sample_qc = _as_dict(raw.get("sample_qc"))
    score_result = _as_dict(raw.get("score_result"))
    calibration = _as_dict(score_result.get("calibration"))
    interpretation = _as_dict(raw.get("interpretation"))

    trait = _clean(_pick(score, "reported_trait", "name", "pgs_id"))
    score_value = _pick(calibration, "z_score")
    if score_value is None:
        score_value = score_result.get("raw_weighted_score")
    percentile = calibration.get("percentile")
    sources: list[str] = []
    pgs_id = _clean(score.get("pgs_id"))
    if not sources and pgs_id:
        sources = [pgs_id]
    overlap = _risk_overlap(sample_qc)
    note = _clean(_pick(interpretation, "summary") or _pick(sample_qc, "note"))

    out: JsonObject = {}
    out["row_type"] = "polygenic_score"
    if trait:
        out["trait"] = trait
    if pgs_id:
        out["score_id"] = pgs_id
    if score_value is not None:
        out["score"] = score_value
    if percentile is not None:
        out["percentile"] = percentile
    if calibration:
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


def _is_native_phenotype_review(raw: JsonObject) -> bool:
    return (
        raw.get("target") not in (None, "", [])
        and isinstance(raw.get("candidate_matrix"), list)
        and str(raw.get("target", {}).get("investigation_type") if isinstance(raw.get("target"), dict) else "")
        in {"carrier_review", "observed_condition_review", "rare_disease", "cancer_risk"}
    )


def _is_native_clinvar_risk_result(raw: JsonObject) -> bool:
    return isinstance(raw, dict) and (
        isinstance(raw.get("candidate_review_groups"), dict)
        or isinstance(raw.get("candidate_inventory"), list)
    )


def _risk_rows_from_clinvar_result(raw: JsonObject) -> list[JsonObject]:
    matrix = _as_dict(raw.get("candidate_review_groups"))
    rows: list[JsonObject] = []
    for group in _as_dicts(matrix.get("groups")):
        row = _risk_row_from_review_group(group)
        if row:
            rows.append(row)
    return rows


def _risk_rows_from_phenotype_review(raw: JsonObject) -> list[JsonObject]:
    rows: list[JsonObject] = []
    for candidate in _as_dicts(raw.get("candidate_matrix")):
        row = _risk_row_from_review_candidate(candidate)
        if row:
            rows.append(row)
    if rows:
        return rows
    active = _as_dict(raw.get("active_genome_index_evidence"))
    matrix = _as_dict(active.get("candidate_review_groups"))
    for group in _as_dicts(matrix.get("groups")):
        row = _risk_row_from_review_group(group)
        if row:
            rows.append(row)
    return rows


def _risk_row_from_review_candidate(candidate: JsonObject) -> JsonObject | None:
    support = _as_dicts(candidate.get("supporting_evidence"))
    group = support[0] if support and support[0].get("group_type") else {}
    if group:
        row = _risk_row_from_review_group(group, row_type="phenotype_review_target")
        if row is None:
            return None
        for source_key, target_key in (
            ("candidate_id", "candidate_id"),
            ("candidate_type", "candidate_type"),
            ("rank", "rank"),
            ("score", "score"),
            ("evidence_support_level", "evidence_support_level"),
            ("answerability", "answerability"),
            ("best_evidence_lane", "best_evidence_lane"),
        ):
            value = candidate.get(source_key)
            if value not in (None, "", []):
                row[target_key] = value
        row["sources"] = ["phenotype.plan_risk_investigation", "ClinVar"]
        return row
    trait = _clean(candidate.get("candidate_id"))
    if not trait:
        return None
    out: JsonObject = {
        "row_type": "phenotype_review_target",
        "trait": trait,
        "score": candidate.get("score"),
        "candidate_id": candidate.get("candidate_id"),
        "candidate_type": candidate.get("candidate_type"),
        "sources": ["phenotype.plan_risk_investigation"],
    }
    return {key: value for key, value in out.items() if value not in (None, "", [])}


def _risk_row_from_review_group(group: JsonObject, *, row_type: str = "clinvar_review_group") -> JsonObject | None:
    trait = _review_trait(group)
    if not trait:
        return None
    row = {
        "row_type": row_type,
        "trait": trait,
        "group_id": group.get("group_id"),
        "group_type": group.get("group_type"),
        "gene": group.get("gene"),
        "condition": group.get("condition"),
        "candidate_ids": group.get("candidate_ids"),
        "clinical_significance_counts": group.get("clinical_significance_counts"),
        "review_status_counts": group.get("review_status_counts"),
        "evidence_groups": group.get("evidence_groups"),
        "zygosity_counts": group.get("zygosity_counts"),
        "match_basis_counts": group.get("match_basis_counts"),
        "population_flags": group.get("population_flags"),
        "interpretation_gates": group.get("interpretation_gates"),
        "missing_interpretation_gates": missing_interpretation_gates(group),
        "sources": ["ClinVar"],
    }
    return {key: value for key, value in row.items() if value not in (None, "", [])}


def _review_trait(group: JsonObject) -> str | None:
    values = [group.get("gene"), group.get("condition")]
    if not any(values):
        values = [group.get("group_type")]
    return " / ".join(str(value) for value in values if value) or None


def _is_native_pgx_result(raw: JsonObject) -> bool:
    return (
        isinstance(raw.get("sample_pgx_matrix"), dict)
        or isinstance(raw.get("medication_review_matrix"), dict)
        or _is_empty_pgx_result(raw)
    )


def _pgx_has_native_content(raw: JsonObject) -> bool:
    return pgx_matrix_result_has_content(raw)


def _is_empty_pgx_result(raw: JsonObject) -> bool:
    if str(raw.get("status") or "") in EMPTY_PGX_STATUSES:
        return True
    envelope = _as_dict(raw.get("evidence_envelope"))
    return str(envelope.get("finding_state") or "") in _EMPTY_ENVELOPE_FINDING_STATES


def _is_empty_pgx_list_item(raw: Any) -> bool:
    return isinstance(raw, dict) and _is_native_pgx_result(raw) and not _pgx_has_native_content(raw)


def _is_empty_risk_list_item(raw: Any) -> bool:
    if isinstance(raw, dict) and _is_native_phenotype_review(raw):
        return not _risk_rows_from_phenotype_review(raw)
    if isinstance(raw, dict) and _is_native_clinvar_risk_result(raw):
        return not _risk_rows_from_clinvar_result(raw)
    return _is_empty_prs_result(raw)


def _is_empty_prs_result(raw: Any) -> bool:
    if not isinstance(raw, dict):
        return False
    if str(raw.get("status") or "") not in EMPTY_PRS_STATUSES:
        return False
    return not any(isinstance(raw.get(key), dict) for key in ("polygenic_score", "sample_qc", "score_result"))


def _is_native_prs_result(raw: Any) -> bool:
    return isinstance(raw, dict) and any(
        isinstance(raw.get(key), dict)
        for key in ("polygenic_score", "sample_qc", "score_result", "interpretation")
    )


def _risk_overlap(sample_qc: JsonObject) -> str | None:
    matched = sample_qc.get("matched_variant_count")
    total = sample_qc.get("score_variant_count")
    if isinstance(matched, (int, float)) and isinstance(total, (int, float)) and total:
        return f"{int(matched)}/{int(total)} variants"
    return None


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
