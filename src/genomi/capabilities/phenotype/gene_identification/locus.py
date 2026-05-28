from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ....evidence.candidate_evidence import (
    DIRECT_SOURCE_MATCH,
    LITERATURE_PLAUSIBILITY,
    SAME_GENE_OR_LOCUS,
    answerability_for_lane,
    evidence_support_level_for_score,
    empty_lanes,
    lane,
)
from ....evidence.candidate_evidence import (
    source_local_ordering as evidence_source_local_ordering,
)
from .. import phenotype

from ._base import (
    CAUSAL_GENE_CONTEXT_TERMS,
    DRUG_TARGET_PRIOR,
    EVIDENCE_PRIORS,
    EXPLICIT_GWAS_GENE_FIELD_TERMS,
    GWAS_PRIOR,
    LOCUS_GENE_CONTEXT_TERMS,
    LOCUS_TO_GENE_PRIOR,
    PHENOTYPE_PRIOR,
    STRONG_LOCUS_TO_GENE_TERMS,
    WEAK_LOCUS_NEIGHBOR_TERMS,
    _clean_text,
    _contains_any,
    _dedupe,
    _finding_text_from_record,
    _iterable_len,
    _normalize_genes,
    _record_gene_values,
)


def _evidence_route(
    *,
    phenotype_text: str,
    task_text: str,
    hpo_ids: list[str],
    genes: list[str],
    drug_context: dict[str, str],
    source_records: Iterable[dict[str, Any]] | None,
    gwas_source_records: Iterable[dict[str, Any]] | None,
    locus_source_records: Iterable[dict[str, Any]] | None,
    target_source_records: Iterable[dict[str, Any]] | None,
) -> dict[str, Any]:
    text = " ".join(part for part in (task_text, phenotype_text) if part).casefold()
    hpo_anchored = bool(hpo_ids) or bool(phenotype.HPO_ID_RE.search(text))
    phenotype_case_signal = _contains_any(
        text,
        (
            "patient",
            "proband",
            "single subject",
            "case report",
            "hpo",
            "rare disease",
            "mendelian",
            "syndrome",
            "congenital",
            "developmental",
            "seizure",
            "ataxia",
            "microcephaly",
            "dysmorph",
            "arthrogryposis",
            "encephalopathy",
        ),
    )
    explicit_non_phenotype = _explicit_non_phenotype_prior_context(
        text=text,
        drug_context=drug_context,
        source_records=source_records,
        gwas_source_records=gwas_source_records,
        locus_source_records=locus_source_records,
        target_source_records=target_source_records,
    )
    if len(genes) <= 25 and not explicit_non_phenotype and (hpo_anchored or phenotype_case_signal):
        return {
            "mode": "single_prior",
            "active_source_priors": [PHENOTYPE_PRIOR],
            "suppressed_source_priors": [GWAS_PRIOR, LOCUS_TO_GENE_PRIOR, DRUG_TARGET_PRIOR],
            "reason": (
                "HPO or single-subject phenotype context with a short candidate-gene list is phenotype-match evidence. "
                "Population association, locus-to-gene, and drug-target priors are not run unless explicitly requested."
            ),
            "decision_boundary": "Genomi returns phenotype/HPO evidence only; the host agent decides from the evidence rows.",
        }
    return {
        "mode": "multi_prior",
        "active_source_priors": list(EVIDENCE_PRIORS),
        "suppressed_source_priors": [],
        "reason": "No HPO-anchored single-subject boundary was detected, so source-prior evidence panels are available for host-agent prior selection.",
        "decision_boundary": "Genomi returns source-prior evidence; the host agent chooses which source family fits the question.",
    }


def _explicit_non_phenotype_prior_context(
    *,
    text: str,
    drug_context: dict[str, str],
    source_records: Iterable[dict[str, Any]] | None,
    gwas_source_records: Iterable[dict[str, Any]] | None,
    locus_source_records: Iterable[dict[str, Any]] | None,
    target_source_records: Iterable[dict[str, Any]] | None,
) -> bool:
    if any(drug_context.values()):
        return True
    if _iterable_len(gwas_source_records) or _iterable_len(locus_source_records) or _iterable_len(target_source_records):
        return True
    if _contains_any(
        text,
        (
            "gwas-catalog",
            "genome-wide association",
            "association catalog",
            "catalog association",
            "efo",
            "mapped gene",
            "common variant",
            "risk locus",
            "locus-to-gene",
            "locus to gene",
            "variant-to-gene",
            "variant to gene",
            "fine-mapping",
            "finemapping",
            "colocalization",
            "colocalisation",
            "eqtl",
            "sqtl",
            "drug target",
            "target gene",
            "mechanism",
            "chembl",
            "drugbank",
            "therapeutic target",
            "inhibitor",
            "agonist",
            "antagonist",
        ),
    ):
        return True
    return _records_have_non_phenotype_prior_terms(source_records)


def _records_have_non_phenotype_prior_terms(records: Iterable[dict[str, Any]] | None) -> bool:
    if records is None:
        return False
    for record in records:
        if not isinstance(record, dict):
            continue
        text = " ".join(
            _clean_text(value)
            for value in (
                record.get("source_id"),
                record.get("source"),
                record.get("source_type"),
                record.get("source_title"),
                record.get("evidence_type"),
                record.get("method"),
                record.get("finding"),
                record.get("summary"),
            )
        ).casefold()
        if _contains_any(
            text,
            (
                "gwas-catalog",
                "association catalog",
                "variant-to-gene",
                "locus-to-gene",
                "colocalization",
                "colocalisation",
                "eqtl",
                "sqtl",
                "chembl",
                "drugbank",
                "drug target",
                "therapeutic target",
            ),
        ):
            return True
    return False


def _prior_fit(
    *,
    phenotype_text: str,
    task_text: str,
    hpo_ids: list[str],
    drug_context: dict[str, str],
    evidence_panels: dict[str, dict[str, Any]],
    source_records: Iterable[dict[str, Any]] | None,
    phenotype_source_records: Iterable[dict[str, Any]] | None,
    gwas_source_records: Iterable[dict[str, Any]] | None,
    locus_source_records: Iterable[dict[str, Any]] | None,
    target_source_records: Iterable[dict[str, Any]] | None,
) -> dict[str, Any]:
    text = " ".join(part for part in (task_text, phenotype_text) if part).casefold()
    fit_inputs = {
        GWAS_PRIOR: (gwas_source_records, source_records),
        LOCUS_TO_GENE_PRIOR: (locus_source_records, source_records),
        DRUG_TARGET_PRIOR: (target_source_records, source_records),
        PHENOTYPE_PRIOR: (phenotype_source_records, source_records),
    }
    fits = {
        prior: _prior_fit_row(
            prior,
            text=text,
            hpo_ids=hpo_ids,
            drug_context=drug_context,
            evidence_panel=evidence_panels.get(prior, {}),
            source_records=fit_inputs[prior][0],
            shared_source_records=fit_inputs[prior][1],
        )
        for prior in EVIDENCE_PRIORS
        if prior in evidence_panels
    }
    ranked = sorted(fits.values(), key=lambda row: (-int(row["score"]), row["source_prior"]))
    top_score = int(ranked[0]["score"]) if ranked else 0
    tied_top = [row for row in ranked if int(row["score"]) == top_score and top_score > 0]
    support_level = _prior_fit_support_level(top_score, tied_top, ranked)
    context_aligned_prior = tied_top[0]["source_prior"] if len(tied_top) == 1 and support_level in {"medium", "high"} else None
    return {
        "context_aligned_prior": context_aligned_prior,
        "support_level": support_level,
        "fits": {row["source_prior"]: row for row in ranked},
        "decision_rule": "Use the prior whose source family is requested by the task. Do not answer from the top candidate of a prior that has weak or ambiguous context fit.",
    }


def _prior_fit_row(
    source_prior: str,
    *,
    text: str,
    hpo_ids: list[str],
    drug_context: dict[str, str],
    evidence_panel: dict[str, Any],
    source_records: Iterable[dict[str, Any]] | None,
    shared_source_records: Iterable[dict[str, Any]] | None,
) -> dict[str, Any]:
    signals: list[str] = []
    cautions: list[str] = []
    score = 0
    source_record_count = _iterable_len(source_records)
    shared_record_count = _iterable_len(shared_source_records)
    causal_gene_context = _causal_gene_context(text, "")
    explicit_gwas_gene_field_context = _explicit_gwas_gene_field_context(text)

    if source_prior == GWAS_PRIOR:
        if causal_gene_context and not explicit_gwas_gene_field_context:
            cautions.append("task asks for causal, effector, target, or locus-gene selection; GWAS gene fields are association-only context")
            if source_record_count:
                cautions.append("GWAS records were supplied but cannot by themselves establish the causal gene")
        elif _contains_any(text, ("gwas-catalog", "genome-wide association", "association catalog", "catalog association", "efo", "locus", "mapped gene", "trait association", "common variant", "risk locus")):
            score += 5
            signals.append("task text names GWAS, association-catalog, locus, EFO, or common-variant evidence")
        if source_record_count:
            if causal_gene_context and not explicit_gwas_gene_field_context:
                pass
            else:
                score += 5
                signals.append("GWAS-specific source records were supplied")
        if (
            not causal_gene_context
            and not hpo_ids
            and not any(drug_context.values())
            and _contains_any(text, ("trait", "risk", "susceptibility", "association", "neoplasm", "cancer", "asthma", "diabetes", "body mass", "height", "blood pressure"))
        ):
            score += 2
            signals.append("phenotype text resembles a public trait-association question")
        if hpo_ids:
            cautions.append("HPO IDs usually indicate phenotype-curation evidence, not GWAS association evidence")
        if any(drug_context.values()):
            cautions.append("drug, drug class, or mechanism context usually indicates drug-target evidence")
    elif source_prior == LOCUS_TO_GENE_PRIOR:
        strong_record_count, weak_record_count = _locus_record_strength_counts(source_records)
        if _contains_any(text, STRONG_LOCUS_TO_GENE_TERMS):
            score += 6
            signals.append("task text names explicit locus-to-gene, variant-to-gene, fine-mapping, colocalization, QTL, or credible-set evidence")
        elif _contains_any(text, WEAK_LOCUS_NEIGHBOR_TERMS):
            score += 1
            signals.append("task text names weak locus-neighbor context")
            cautions.append("nearest, mapped, or generic risk-locus wording is weak context and should not select a causal gene by itself")
        if strong_record_count:
            score += 6
            signals.append("explicit locus-to-gene source records were supplied")
        elif weak_record_count:
            cautions.append("locus source records are only nearest, mapped, or same-locus evidence")
        if shared_record_count and not source_record_count:
            filtered = _filter_locus_source_records(shared_source_records)
            shared_strong_count, shared_weak_count = _locus_record_strength_counts(filtered)
            if shared_strong_count:
                score += 4
                signals.append("shared source records include explicit locus-to-gene evidence")
            elif shared_weak_count:
                cautions.append("shared source records include only weak locus-neighbor evidence")
        if evidence_panel.get("ranking") and _locus_panel_has_only_weak_neighbor_evidence(evidence_panel):
            cautions.append("this prior returned only weak locus-neighbor evidence; do not treat it as canonical trait-gene evidence")
        if hpo_ids:
            cautions.append("HPO IDs usually indicate phenotype-curation evidence, not locus-to-gene evidence")
        if any(drug_context.values()):
            cautions.append("drug, drug class, or mechanism context usually indicates drug-target evidence")
    elif source_prior == DRUG_TARGET_PRIOR:
        drug_signal_count = sum(1 for value in drug_context.values() if value)
        if drug_signal_count:
            score += 5 + drug_signal_count
            signals.append("drug, drug class, or mechanism context was supplied")
        if source_record_count:
            score += 5
            signals.append("drug-target-specific source records were supplied")
        if _contains_any(text, ("drug target", "target gene", "mechanism", "pharmaproject", "chembl", "drugbank", "therapeutic target", "inhibitor", "agonist", "antagonist")):
            score += 4
            signals.append("task text names drug-target or mechanism evidence")
        if hpo_ids:
            cautions.append("HPO IDs do not by themselves establish drug-target mechanism evidence")
    elif source_prior == PHENOTYPE_PRIOR:
        if hpo_ids:
            score += 6
            signals.append("HPO IDs were supplied")
        if source_record_count:
            score += 5
            signals.append("phenotype-specific source records were supplied")
        if _contains_any(text, ("hpo", "phenotype", "patient", "rare disease", "mendelian", "omim", "orphanet", "clingen", "gencc", "syndrome", "congenital", "developmental", "seizure", "ataxia", "microcephaly", "dysmorph")):
            score += 4
            signals.append("task text names patient, HPO, rare-disease, or expert-curation evidence")
        if any(drug_context.values()):
            cautions.append("drug context usually indicates a drug-target prior unless the task asks for phenotype matching")

    if evidence_panel.get("status") == "not_requested":
        cautions.append("this prior was not requested for this call")
    if not evidence_panel.get("ranking"):
        cautions.append("this prior returned no ranked candidate evidence")
    elif score == 0:
        cautions.append("this prior has candidate evidence, but the task context did not identify it as the intended prior")
    if shared_record_count and not source_record_count:
        signals.append("shared source records were supplied; inspect record source_type before trusting this prior")

    return {
        "source_prior": source_prior,
        "fit": _fit_label(score),
        "score": score,
        "signals": signals,
        "cautions": cautions,
        "top_candidate": evidence_panel.get("ranking", [{}])[0].get("candidate") if evidence_panel.get("ranking") else None,
        "when_to_trust": _when_to_trust_prior(source_prior),
    }


def _prior_fit_support_level(top_score: int, tied_top: list[dict[str, Any]], ranked: list[dict[str, Any]]) -> str:
    if top_score <= 0:
        return "none"
    if len(tied_top) > 1:
        return "ambiguous"
    second = int(ranked[1]["score"]) if len(ranked) > 1 else 0
    margin = top_score - second
    if top_score >= 8 and margin >= 3:
        return "high"
    if top_score >= 5 and margin >= 2:
        return "medium"
    return "low"


def _fit_label(score: int) -> str:
    if score >= 8:
        return "strong"
    if score >= 5:
        return "moderate"
    if score > 0:
        return "weak"
    return "no_context_signal"


def _when_to_trust_prior(source_prior: str) -> str:
    if source_prior == GWAS_PRIOR:
        return "Trust for explicit GWAS Catalog gene-field, association, EFO, mapped-gene, or public trait-association questions; not for causal-gene selection."
    if source_prior == LOCUS_TO_GENE_PRIOR:
        return "Trust for explicit locus-to-gene, variant-to-gene, fine-mapping, colocalization, QTL/eQTL, or credible-set questions. Nearest or mapped gene evidence is weak context only."
    if source_prior == DRUG_TARGET_PRIOR:
        return "Trust for drug, drug-class, therapeutic-target, or mechanism-of-action questions."
    if source_prior == PHENOTYPE_PRIOR:
        return "Trust for HPO, patient phenotype, rare-disease, OMIM, Orphanet, ClinGen, or GenCC questions."
    return "Trust only when the task explicitly asks for this source family."


def _causal_gene_context(task_text: str, phenotype_text: str) -> bool:
    text = " ".join(part for part in (task_text, phenotype_text) if part).casefold()
    if not text:
        return False
    if _contains_any(text, CAUSAL_GENE_CONTEXT_TERMS):
        return True
    return "gene" in text and _contains_any(text, LOCUS_GENE_CONTEXT_TERMS)


def _explicit_gwas_gene_field_context(text: str) -> bool:
    return _contains_any(text.casefold(), EXPLICIT_GWAS_GENE_FIELD_TERMS)


def _downgrade_gwas_association_for_causal_context(result: dict[str, Any]) -> dict[str, Any]:
    matrix = result.get("candidate_matrix") if isinstance(result.get("candidate_matrix"), list) else []
    downgraded_matrix = [_downgrade_gwas_candidate_for_causal_context(row) for row in matrix]
    downgraded = {
        **result,
        "status": "association_only_not_causal_gene_evidence" if any(row.get("rank") is not None for row in downgraded_matrix) else result.get("status"),
        "candidate_matrix": downgraded_matrix,
        "warnings": _dedupe(
            [
                *(result.get("warnings") or []),
                "GWAS Catalog gene-field evidence is association-only context for this causal-gene task; it is not causal-gene evidence.",
            ]
        ),
        "causal_gene_boundary": {
            "evidence_regime": "association_only_not_causal",
            "rule": "Do not use GWAS Catalog reported_gene or mapped_gene fields as the causal-gene verdict when the task asks for a causal, effector, target, or gene-at-locus answer.",
        },
    }
    source_ranking = [
        {"candidate": row.get("candidate_id"), "rank": row.get("rank"), "score": row.get("score"), "evidence_support_level": row.get("evidence_support_level", "none")}
        for row in downgraded_matrix
        if row.get("rank") is not None
    ]
    downgraded["source_local_ordering"] = evidence_source_local_ordering(
        source_ranking,
        valid_for="GWAS Catalog source-local association ordering.",
        not_valid_for="Causal-gene selection; GWAS Catalog gene fields are not causal-gene assignments.",
    )
    downgraded["top_observed"] = None
    downgraded["top_observed_candidate"] = None
    summary = dict(result.get("summary") or {})
    summary["top_observed_candidate"] = None
    summary["top_observed_support_level"] = "none"
    summary["evidence_regime"] = "association_only_not_causal"
    downgraded["summary"] = summary
    return downgraded


def _downgrade_gwas_candidate_for_causal_context(row: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(row, dict):
        return row
    output = dict(row)
    if float(output.get("score") or 0.0) <= 0:
        return output
    original_lane = output.get("best_evidence_lane")
    original_score = float(output.get("score") or 0.0)
    downgraded_score = min(original_score, 0.25)
    output["source_evidence_regime"] = "association_only_not_causal"
    output["original_score_basis"] = {
        "best_evidence_lane": original_lane,
        "score": original_score,
        "evidence_support_level": output.get("evidence_support_level"),
        "answerability": output.get("answerability"),
    }
    output["best_evidence_lane"] = SAME_GENE_OR_LOCUS
    output["score"] = downgraded_score
    output["evidence_support_level"] = "none"
    output["answerability"] = "not_supported"
    output["causal_gene_limitation"] = "GWAS Catalog source gene fields are association annotations, not causal-gene assignments."
    output["ordering_scope"] = {
        "valid_for": "GWAS Catalog source-local association ordering.",
        "not_valid_for": "Causal-gene selection.",
    }
    lanes = {
        lane_name: dict(lane_payload)
        for lane_name, lane_payload in (output.get("evidence_lanes") or {}).items()
        if isinstance(lane_payload, dict)
    }
    lanes[SAME_GENE_OR_LOCUS] = lane(
        SAME_GENE_OR_LOCUS,
        status="present",
        score=downgraded_score,
        source="GWAS Catalog",
        matched_text=(output.get("supporting_evidence") or [{}])[0].get("matched_trait") if output.get("supporting_evidence") else None,
        source_id=(output.get("supporting_evidence") or [{}])[0].get("study_accession") if output.get("supporting_evidence") else None,
        note="association-only GWAS gene-field evidence; not a causal-gene verdict",
    )
    output["evidence_lanes"] = lanes
    output["supporting_evidence"] = [
        {
            **record,
            "evidence_regime": "association_only_not_causal",
        }
        if isinstance(record, dict)
        else record
        for record in (output.get("supporting_evidence") or [])
    ]
    output["why_not_selected"] = [
        *output.get("why_not_selected", []),
        "GWAS Catalog gene-field support is association-only for causal-gene questions.",
    ] if output.get("why_not_selected") else []
    return output


def _locus_record_strength_counts(records: Iterable[dict[str, Any]] | None) -> tuple[int, int]:
    strong = 0
    weak = 0
    for record in records or []:
        if not isinstance(record, dict):
            continue
        lane_name = _locus_record_lane(record)
        if lane_name == DIRECT_SOURCE_MATCH:
            strong += 1
        elif lane_name == SAME_GENE_OR_LOCUS:
            weak += 1
    return strong, weak


def _locus_panel_has_only_weak_neighbor_evidence(evidence_panel: dict[str, Any]) -> bool:
    ranking = evidence_panel.get("ranking") if isinstance(evidence_panel.get("ranking"), list) else []
    if not ranking:
        return False
    for row in ranking:
        if not isinstance(row, dict):
            continue
        discriminators = row.get("evidence_discriminators") if isinstance(row.get("evidence_discriminators"), dict) else {}
        if discriminators.get("best_evidence_lane") != SAME_GENE_OR_LOCUS:
            return False
    return True


def _compare_locus_to_gene_evidence(genes: list[str], source_records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    records = [_locus_gene_record(record) for record in source_records if isinstance(record, dict)]
    records = [record for record in records if record["genes"]]
    matrix = [_locus_candidate_row(gene, records) for gene in genes]
    ranked = sorted(
        [candidate for candidate in matrix if candidate["score"] > 0],
        key=lambda candidate: (-float(candidate["score"]), str(candidate["candidate_id"]).casefold()),
    )
    selected = ranked[0] if ranked else None
    ranks = {candidate["candidate_id"]: index + 1 for index, candidate in enumerate(ranked)}
    for candidate in matrix:
        candidate["rank"] = ranks.get(candidate["candidate_id"])
        candidate["why_not_selected"] = _locus_why_not_selected(candidate, selected)
    matrix = sorted(matrix, key=lambda candidate: (candidate["rank"] is None, candidate["rank"] or 10**9, candidate["candidate_id"].casefold()))
    return {
        "ok": True,
        "status": "completed" if ranked else "no_matching_locus_to_gene_evidence",
        "query": {"genes": genes},
        "summary": {
            "gene_count": len(genes),
            "source_record_count": len(records),
            "ranked_candidate_count": len(ranked),
            "top_observed_candidate": selected["candidate_id"] if selected else None,
            "top_observed_support_level": selected["evidence_support_level"] if selected else "none",
        },
        "source_records": records,
        "candidate_matrix": matrix,
        "decision_policy": {
            "policy_id": "locus_to_gene_candidate_matrix_v1",
            "ranking_order": [
                "direct variant-to-gene, fine-mapping, colocalization, or QTL source evidence",
                "same-locus mapped or nearest-gene source evidence",
                "candidate identifier for deterministic tie-breaking",
            ],
            "rule": "This is a locus-to-gene evidence lane. It returns source records linking loci or variants to genes; the host agent decides whether that prior fits the task.",
        },
    }


def _filter_locus_source_records(records: Iterable[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if records is None:
        return []
    return [record for record in records if isinstance(record, dict) and _is_locus_source_record(record)]


def _is_locus_source_record(record: dict[str, Any]) -> bool:
    text = " ".join(
        _clean_text(value)
        for value in (
            record.get("source_id"),
            record.get("source"),
            record.get("source_title"),
            record.get("evidence_type"),
            record.get("method"),
            record.get("finding"),
            record.get("summary"),
        )
    ).casefold()
    return _contains_any(
        text,
        (
            "locus-to-gene",
            "locus to gene",
            "variant-to-gene",
            "variant to gene",
            "v2g",
            "l2g",
            "colocalization",
            "colocalisation",
            "eqtl",
            "sqtl",
            "fine-mapping",
            "finemapping",
            "credible set",
            "nearest gene",
            "mapped gene",
        ),
    )


def _locus_gene_record(record: dict[str, Any]) -> dict[str, Any]:
    genes = _normalize_genes(_record_gene_values(record))
    method = _clean_text(record.get("method") or record.get("evidence_type") or record.get("type"))
    source_id = _clean_text(record.get("source_id") or record.get("source") or record.get("database"))
    source_title = _clean_text(record.get("source_title") or record.get("title"))
    evidence_type = _clean_text(record.get("evidence_type") or method or source_id)
    score = _normalized_locus_score(record)
    return {
        "record_id": _clean_text(record.get("record_id") or record.get("id") or record.get("source_record_id")),
        "source": source_id or source_title or "locus_to_gene_source",
        "source_title": source_title,
        "source_url": _clean_text(record.get("source_url") or record.get("url")),
        "evidence_type": evidence_type,
        "method": method,
        "genes": genes,
        "variant": _clean_text(record.get("variant") or record.get("rsid") or record.get("lead_variant")),
        "locus": _clean_text(record.get("locus") or record.get("region")),
        "score": score,
        "finding": _clean_text(_finding_text_from_record(record)),
        "support_span": _clean_text(record.get("support_span") or record.get("supporting_text")),
    }


def _locus_candidate_row(gene: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    supported = [record for record in records if gene.upper() in {item.upper() for item in record["genes"]}]
    best_record = max(supported, key=_locus_record_score, default=None)
    lanes = empty_lanes()
    score = 0.0
    best_lane = None
    if best_record:
        best_lane = _locus_record_lane(best_record)
        score = _locus_record_score(best_record)
        lanes[best_lane] = lane(
            best_lane,
            status="present",
            score=score,
            source=best_record["source"],
            matched_text=best_record["variant"] or best_record["locus"] or best_record["finding"],
            source_id=best_record["record_id"] or best_record["source_title"],
            note=best_record["evidence_type"] or "locus-to-gene source evidence",
        )
    return {
        "candidate_id": gene,
        "candidate_type": "gene_symbol",
        "rank": None,
        "score": score,
        "evidence_support_level": evidence_support_level_for_score(score),
        "answerability": answerability_for_lane(best_lane),
        "best_evidence_lane": best_lane,
        "best_source_family": "locus_to_gene",
        "evidence_lanes": lanes,
        "supporting_evidence": [_locus_evidence_summary(record) for record in supported],
        "counter_evidence": [],
        "why_not_selected": [],
    }


def _locus_record_lane(record: dict[str, Any]) -> str:
    text = _locus_record_text(record)
    if _contains_any(text, STRONG_LOCUS_TO_GENE_TERMS):
        return DIRECT_SOURCE_MATCH
    if _contains_any(text, WEAK_LOCUS_NEIGHBOR_TERMS) or _contains_any(text, ("locus", "variant", "region")):
        return SAME_GENE_OR_LOCUS
    return LITERATURE_PLAUSIBILITY


def _locus_record_text(record: dict[str, Any]) -> str:
    return " ".join(
        str(record.get(key) or "")
        for key in (
            "source",
            "source_id",
            "source_title",
            "evidence_type",
            "method",
            "finding",
            "summary",
            "support_span",
        )
    ).casefold()


def _locus_record_score(record: dict[str, Any]) -> float:
    lane_name = _locus_record_lane(record)
    score = record.get("score")
    numeric_score = float(score) if isinstance(score, (int, float)) else None
    if numeric_score is None:
        return 0.75 if lane_name == DIRECT_SOURCE_MATCH else (0.55 if lane_name == SAME_GENE_OR_LOCUS else 0.35)
    if lane_name == DIRECT_SOURCE_MATCH:
        return max(0.65, min(1.0, numeric_score))
    if lane_name == SAME_GENE_OR_LOCUS:
        return max(0.4, min(0.65, numeric_score))
    return max(0.1, min(0.45, numeric_score))


def _normalized_locus_score(record: dict[str, Any]) -> float | None:
    for key in ("locus_to_gene_score", "variant_to_gene_score", "l2g_score", "v2g_score", "score", "probability", "posterior_probability", "coloc_probability", "credible_set_probability", "pip"):
        value = record.get(key)
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if numeric > 1 and numeric <= 100:
            numeric = numeric / 100.0
        return max(0.0, min(1.0, numeric))
    return None


def _locus_evidence_summary(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": record.get("source"),
        "source_title": record.get("source_title"),
        "source_url": record.get("source_url"),
        "record_id": record.get("record_id"),
        "evidence_type": record.get("evidence_type"),
        "method": record.get("method"),
        "variant": record.get("variant"),
        "locus": record.get("locus"),
        "score": record.get("score"),
        "genes": record.get("genes"),
        "finding": record.get("finding"),
        "support_span": record.get("support_span"),
    }


def _locus_why_not_selected(candidate: dict[str, Any], selected: dict[str, Any] | None) -> list[str]:
    if not selected:
        return ["No candidate had locus-to-gene source evidence."]
    if candidate["candidate_id"] == selected["candidate_id"]:
        return []
    if candidate["score"] <= 0:
        return ["No locus-to-gene source record supported this candidate."]
    if candidate["score"] < selected["score"]:
        return ["Weaker locus-to-gene evidence score than the top observed candidate."]
    return ["Ranked lower by deterministic candidate tie-breaker."]
