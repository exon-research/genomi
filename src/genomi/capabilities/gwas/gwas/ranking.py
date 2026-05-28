from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ....evidence.candidate_evidence import (
    DIRECT_SOURCE_MATCH,
    EXACT_TRAIT_MATCH,
    LITERATURE_PLAUSIBILITY,
    NEARBY_TRAIT_MATCH,
    SAME_GENE_OR_LOCUS,
    answerability_for_lane,
    empty_lanes,
    evidence_support_level_for_score,
    lane,
)
from ....evidence.task_profiles import (
    GWAS_GENE_PRIORITIZATION,
    GWAS_VARIANT_PRIORITIZATION,
)
from .text_utils import _normalize_gene, _normalize_genes, _pvalue_sort_value


def _gene_candidate_matrix(genes: list[str], records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = [_gene_candidate_row(gene, records) for gene in genes]
    ranked = sorted(
        [candidate for candidate in candidates if candidate["score"] > 0],
        key=lambda candidate: (
            -float(candidate["score"]),
            -int(candidate.get("source_gene_match_strength") or 0),
            _pvalue_sort_value(candidate["best_pvalue"]),
            candidate["candidate_id"].casefold(),
        ),
    )
    ranks = {candidate["candidate_id"]: index + 1 for index, candidate in enumerate(ranked)}
    selected = ranked[0] if ranked else None
    for candidate in candidates:
        candidate["rank"] = ranks.get(candidate["candidate_id"])
        candidate["why_not_selected"] = _gene_why_not_selected(candidate, selected)
    return sorted(candidates, key=lambda candidate: (candidate["rank"] is None, candidate["rank"] or 10**9, candidate["candidate_id"].casefold()))


def _gene_candidate_row(gene: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    supported = [
        record
        for record in records
        if gene.upper() in {item.upper() for item in record.get("genes") or []}
        and int(record["phenotype_match"]["score"]) > 0
    ]
    best_record = min(
        supported,
        key=lambda record: (
            -_gene_lane_weight(record["phenotype_match"].get("evidence_lane")),
            -int(_source_gene_match(gene, record)["strength"]),
            _pvalue_sort_value(record.get("pvalue")),
            record.get("association_id") or "",
        ),
        default=None,
    )
    lanes = empty_lanes()
    score = 0.0
    best_lane = None
    best_pvalue = None
    source_gene_match = _empty_source_gene_match()
    if best_record:
        best_lane = best_record["phenotype_match"].get("evidence_lane")
        score = _gene_lane_weight(best_lane)
        best_pvalue = best_record.get("pvalue")
        source_gene_match = _source_gene_match(gene, best_record)
        matched_text = best_record["phenotype_match"].get("matched_trait")
        source_id = best_record["study"].get("accession") or best_record.get("association_id")
        if best_lane:
            lanes[best_lane] = lane(
                best_lane,
                status="present",
                score=score,
                source="GWAS Catalog",
                matched_text=matched_text,
                source_id=source_id,
                note=best_record["phenotype_match"].get("reason"),
            )
        if best_lane == EXACT_TRAIT_MATCH and source_gene_match.get("field") == "reported_genes":
            best_lane = DIRECT_SOURCE_MATCH
            score = 1.0
            lanes[DIRECT_SOURCE_MATCH] = lane(
                DIRECT_SOURCE_MATCH,
                status="present",
                score=1.0,
                source="GWAS Catalog",
                matched_text=matched_text,
                source_id=source_id,
                note="candidate gene is named in an exact GWAS Catalog trait association",
            )
        elif best_lane == EXACT_TRAIT_MATCH and source_gene_match.get("field") == "mapped_genes":
            best_lane = SAME_GENE_OR_LOCUS
            score = _gene_lane_weight(best_lane)
            lanes[SAME_GENE_OR_LOCUS] = lane(
                SAME_GENE_OR_LOCUS,
                status="present",
                score=score,
                source="GWAS Catalog",
                matched_text=matched_text,
                source_id=source_id,
                note="candidate appears in the GWAS Catalog mapped gene field; this is locus/gene-field evidence, not causal assignment",
            )
        elif best_lane == EXACT_TRAIT_MATCH:
            best_lane = LITERATURE_PLAUSIBILITY
            score = _gene_lane_weight(best_lane)
            lanes[LITERATURE_PLAUSIBILITY] = lane(
                LITERATURE_PLAUSIBILITY,
                status="present",
                score=score,
                source="GWAS Catalog",
                matched_text=matched_text,
                source_id=source_id,
                note="candidate appears only in a generic GWAS Catalog gene field; this is weak association-source context",
            )
    return {
        "candidate_id": gene,
        "candidate_type": "gene_symbol",
        "rank": None,
        "score": score,
        "evidence_support_level": evidence_support_level_for_score(score),
        "answerability": answerability_for_lane(best_lane),
        "best_evidence_lane": best_lane,
        "best_pvalue": best_pvalue,
        "source_gene_match": source_gene_match,
        "source_gene_match_strength": source_gene_match["strength"],
        "evidence_lanes": lanes,
        "supporting_evidence": [_gene_evidence_summary(record, candidate_gene=gene) for record in supported],
        "counter_evidence": [],
        "why_not_selected": [],
    }


def _gene_evidence_summary(record: dict[str, Any], *, candidate_gene: str | None = None) -> dict[str, Any]:
    source_gene_match = _source_gene_match(candidate_gene, record) if candidate_gene else _empty_source_gene_match()
    return {
        "source": "GWAS Catalog",
        "association_id": record.get("association_id"),
        "matched_trait": record["phenotype_match"].get("matched_trait"),
        "evidence_lane": record["phenotype_match"].get("evidence_lane"),
        "pvalue": record.get("pvalue"),
        "genes": record.get("genes"),
        "reported_genes": record.get("reported_genes") or [],
        "mapped_genes": record.get("mapped_genes") or [],
        "source_gene_fields": record.get("source_gene_fields") or {},
        "candidate_source_gene_match": source_gene_match,
        "study_accession": record["study"].get("accession"),
        "finding": record.get("finding"),
    }


def _source_gene_match(candidate_gene: str | None, record: dict[str, Any]) -> dict[str, Any]:
    candidate = _normalize_gene(candidate_gene)
    reported_genes = record.get("reported_genes") or []
    mapped_genes = record.get("mapped_genes") or []
    all_named_genes = record.get("genes") or []
    if not candidate:
        return _empty_source_gene_match(
            reported_genes=reported_genes,
            mapped_genes=mapped_genes,
            all_named_genes=all_named_genes,
        )
    if candidate in {_normalize_gene(gene) for gene in reported_genes}:
        return {
            "field": "reported_genes",
            "strength": 3,
            "matched_gene": candidate,
            "matched_names": _matching_gene_names(candidate, reported_genes),
            "reported_genes": reported_genes,
            "mapped_genes": mapped_genes,
            "all_named_genes": all_named_genes,
            "meaning": "candidate appears in the GWAS Catalog author-reported gene field",
        }
    if candidate in {_normalize_gene(gene) for gene in mapped_genes}:
        return {
            "field": "mapped_genes",
            "strength": 2,
            "matched_gene": candidate,
            "matched_names": _matching_gene_names(candidate, mapped_genes),
            "reported_genes": reported_genes,
            "mapped_genes": mapped_genes,
            "all_named_genes": all_named_genes,
            "meaning": "candidate appears in the GWAS Catalog mapped gene field",
        }
    if candidate in {_normalize_gene(gene) for gene in all_named_genes}:
        return {
            "field": "all_named_genes",
            "strength": 1,
            "matched_gene": candidate,
            "matched_names": _matching_gene_names(candidate, all_named_genes),
            "reported_genes": reported_genes,
            "mapped_genes": mapped_genes,
            "all_named_genes": all_named_genes,
            "meaning": "candidate appears only in a generic extracted gene field",
        }
    return _empty_source_gene_match(
        reported_genes=reported_genes,
        mapped_genes=mapped_genes,
        all_named_genes=all_named_genes,
    )


def _empty_source_gene_match(
    *,
    reported_genes: list[str] | None = None,
    mapped_genes: list[str] | None = None,
    all_named_genes: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "field": None,
        "strength": 0,
        "matched_gene": None,
        "matched_names": [],
        "reported_genes": reported_genes or [],
        "mapped_genes": mapped_genes or [],
        "all_named_genes": all_named_genes or [],
        "meaning": "candidate is not named in the source gene fields",
    }


def _matching_gene_names(candidate: str, genes: Iterable[Any]) -> list[str]:
    return _normalize_genes(gene for gene in genes if _normalize_gene(gene) == candidate)


def _gene_lane_weight(lane_name: str | None) -> float:
    if lane_name == EXACT_TRAIT_MATCH:
        return float(GWAS_GENE_PRIORITIZATION.ranking_weights[EXACT_TRAIT_MATCH])
    if lane_name == SAME_GENE_OR_LOCUS:
        return float(GWAS_GENE_PRIORITIZATION.ranking_weights[SAME_GENE_OR_LOCUS])
    if lane_name == NEARBY_TRAIT_MATCH:
        return float(GWAS_GENE_PRIORITIZATION.ranking_weights[NEARBY_TRAIT_MATCH])
    if lane_name == LITERATURE_PLAUSIBILITY:
        return float(GWAS_GENE_PRIORITIZATION.ranking_weights[LITERATURE_PLAUSIBILITY])
    return 0.0


def _gene_why_not_selected(candidate: dict[str, Any], selected: dict[str, Any] | None) -> list[str]:
    if not selected:
        return ["No candidate had supported GWAS Catalog trait evidence."]
    if candidate["candidate_id"] == selected["candidate_id"]:
        return []
    if candidate["score"] <= 0:
        return ["No GWAS Catalog trait association named this candidate gene for the requested phenotype."]
    if candidate["score"] < selected["score"]:
        return [f"Evidence lane {candidate['best_evidence_lane']} is weaker than selected lane {selected['best_evidence_lane']}."]
    if int(candidate.get("source_gene_match_strength") or 0) < int(selected.get("source_gene_match_strength") or 0):
        candidate_field = (candidate.get("source_gene_match") or {}).get("field") or "no source gene field"
        selected_field = (selected.get("source_gene_match") or {}).get("field") or "no source gene field"
        return [
            "Same evidence-lane strength as selected candidate, but weaker GWAS Catalog source gene field "
            f"({candidate_field} vs {selected_field})."
        ]
    if _pvalue_sort_value(candidate["best_pvalue"]) > _pvalue_sort_value(selected["best_pvalue"]):
        return ["Same evidence-lane strength as selected candidate, but weaker p-value."]
    return ["Ranked lower by deterministic candidate tie-breaker."]


def _gene_selection_warnings(selected_candidate: dict[str, Any] | None, candidate_matrix: list[dict[str, Any]]) -> list[str]:
    if not selected_candidate:
        return ["No candidate gene had source-supported GWAS Catalog phenotype evidence."]
    if (selected_candidate.get("source_gene_match") or {}).get("field") == "mapped_genes":
        return ["Selected gene is based on GWAS Catalog mapped_gene evidence, which is not causal-gene evidence."]
    if selected_candidate["answerability"] != "direct_source_supported":
        return ["Selected gene is based on adjacent GWAS trait evidence, not an exact source trait match."]
    direct_count = sum(1 for candidate in candidate_matrix if candidate["answerability"] == "direct_source_supported")
    if direct_count > 1:
        return ["Multiple candidate genes had exact GWAS trait support; inspect p-values and study contexts."]
    return []


def _candidate_matrix(rsids: list[str], matches_by_variant: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    candidates = [_candidate_row(rsid, matches_by_variant.get(rsid, [])) for rsid in rsids]
    ranked = sorted(
        [candidate for candidate in candidates if candidate["score"] > 0],
        key=lambda candidate: (
            -float(candidate["score"]),
            _pvalue_sort_value(candidate["best_pvalue"]),
            candidate["candidate_id"].casefold(),
        ),
    )
    rank_by_candidate = {candidate["candidate_id"]: index + 1 for index, candidate in enumerate(ranked)}
    selected = ranked[0] if ranked else None
    for candidate in candidates:
        candidate["rank"] = rank_by_candidate.get(candidate["candidate_id"])
        candidate["why_not_selected"] = _why_not_selected(candidate, selected)
    return sorted(candidates, key=lambda candidate: (candidate["rank"] is None, candidate["rank"] or 10**9, candidate["candidate_id"].casefold()))


def _candidate_row(rsid: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    supported = [record for record in records if int(record["phenotype_match"]["score"]) > 0]
    best_record = min(
        supported,
        key=lambda record: (
            -_lane_weight(record["phenotype_match"].get("evidence_lane")),
            _pvalue_sort_value(record.get("pvalue")),
            record.get("association_id") or "",
        ),
        default=None,
    )
    lanes = empty_lanes()
    score = 0.0
    best_lane = None
    best_pvalue = None
    supporting_evidence: list[dict[str, Any]] = []
    if best_record:
        best_lane = best_record["phenotype_match"].get("evidence_lane")
        score = _lane_weight(best_lane)
        best_pvalue = best_record.get("pvalue")
        source_id = best_record["study"].get("accession") or best_record.get("association_id")
        matched_text = best_record["phenotype_match"].get("matched_trait")
        if best_lane:
            lanes[best_lane] = lane(
                best_lane,
                status="present",
                score=score,
                source="GWAS Catalog",
                matched_text=matched_text,
                source_id=source_id,
                note=best_record["phenotype_match"].get("reason"),
            )
        if best_lane == EXACT_TRAIT_MATCH:
            lanes[DIRECT_SOURCE_MATCH] = lane(
                DIRECT_SOURCE_MATCH,
                status="present",
                score=1.0,
                source="GWAS Catalog",
                matched_text=matched_text,
                source_id=source_id,
                note="candidate has an exact source trait match in GWAS Catalog",
            )
        supporting_evidence = [_candidate_evidence_summary(record) for record in supported]
    answerability = answerability_for_lane(best_lane)
    support_axes = _variant_support_axes(best_record, best_lane, score)
    evidence_support_level = _minimum_support_level(axis.get("support_level") for axis in support_axes.values())
    return {
        "candidate_id": rsid,
        "candidate_type": "rsid",
        "rank": None,
        "score": score,
        "evidence_support_level": evidence_support_level,
        "support_axes": support_axes,
        "answerability": answerability,
        "best_evidence_lane": best_lane,
        "best_pvalue": best_pvalue,
        "evidence_lanes": lanes,
        "supporting_evidence": supporting_evidence,
        "counter_evidence": [],
        "why_not_selected": [],
    }


def _variant_support_axes(best_record: dict[str, Any] | None, best_lane: str | None, score: float) -> dict[str, dict[str, Any]]:
    if not best_record or not best_lane:
        return {
            "trait_specificity": {"support_level": "none", "reason": "No GWAS Catalog trait match observed."},
            "association_strength": {"support_level": "none", "reason": "No matching association p-value observed."},
            "lead_variant_support": {"support_level": "none", "reason": "No matching association observed."},
        }
    return {
        "trait_specificity": {
            "support_level": "high" if best_lane == EXACT_TRAIT_MATCH else "low",
            "reason": "Exact requested trait match." if best_lane == EXACT_TRAIT_MATCH else "Related or nearby trait match; not a direct requested-trait lead.",
            "matched_trait": best_record["phenotype_match"].get("matched_trait"),
        },
        "association_strength": {
            "support_level": _pvalue_support_level(best_record.get("pvalue")),
            "reason": "P-value strength within the GWAS Catalog association record.",
            "pvalue": best_record.get("pvalue"),
        },
        "lead_variant_support": {
            "support_level": "medium" if score > 0 else "none",
            "reason": (
                "This query observes association records for the rsID; it does not independently verify credible-set lead-variant status."
            ),
        },
    }


def _pvalue_support_level(value: Any) -> str:
    numeric = _pvalue_sort_value(value)
    if numeric <= 5e-8:
        return "high"
    if numeric <= 1e-5:
        return "medium"
    if numeric < float("inf"):
        return "low"
    return "none"


def _minimum_support_level(values: Iterable[str]) -> str:
    order = {"none": 0, "low": 1, "medium": 2, "high": 3}
    normalized = [str(value or "none") for value in values]
    if not normalized:
        return "none"
    return min(normalized, key=lambda value: order.get(value, 0))


def _candidate_evidence_summary(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": "GWAS Catalog",
        "association_id": record.get("association_id"),
        "study_accession": record["study"].get("accession"),
        "matched_trait": record["phenotype_match"].get("matched_trait"),
        "evidence_lane": record["phenotype_match"].get("evidence_lane"),
        "pvalue": record.get("pvalue"),
        "risk_alleles": record.get("risk_alleles"),
        "mapped_genes": record.get("mapped_genes"),
        "reported_genes": record.get("reported_genes"),
        "finding": record.get("finding"),
    }


def _lane_weight(lane_name: str | None) -> float:
    if not lane_name:
        return 0.0
    return float(GWAS_VARIANT_PRIORITIZATION.ranking_weights.get(lane_name, 0.0))


def _why_not_selected(candidate: dict[str, Any], selected: dict[str, Any] | None) -> list[str]:
    if not selected:
        return ["No candidate had supported GWAS Catalog phenotype evidence."]
    if candidate["candidate_id"] == selected["candidate_id"]:
        return []
    if candidate["score"] <= 0:
        return ["No meaningful GWAS Catalog trait match was found for the requested phenotype."]
    if candidate["score"] < selected["score"]:
        return [
            f"Evidence lane {candidate['best_evidence_lane']} is weaker than selected lane {selected['best_evidence_lane']}."
        ]
    if _pvalue_sort_value(candidate["best_pvalue"]) > _pvalue_sort_value(selected["best_pvalue"]):
        return ["Same evidence-lane strength as selected candidate, but weaker p-value."]
    return ["Ranked lower by deterministic candidate tie-breaker."]


def _selection_warnings(selected_candidate: dict[str, Any] | None, candidate_matrix: list[dict[str, Any]]) -> list[str]:
    if not selected_candidate:
        return ["No candidate had source-supported GWAS Catalog phenotype evidence for the requested phenotype."]
    warnings = []
    if selected_candidate["answerability"] != "direct_source_supported":
        warnings.append(
            "Selected candidate is based on adjacent GWAS trait evidence, not an exact source trait match; treat as lower-support prioritization."
        )
    direct_count = sum(1 for candidate in candidate_matrix if candidate["answerability"] == "direct_source_supported")
    if direct_count > 1:
        warnings.append("Multiple candidates had direct source support; inspect p-values and study contexts before final interpretation.")
    return warnings
