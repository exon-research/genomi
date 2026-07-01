from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from ....evidence import (
    extract_clinvar_candidates,
    fetch_gene_evidence,
    query_research_findings,
    search_research_findings,
)
from ....evidence.candidate_evidence import (
    AGENT_REASONING_ONLY,
    DIRECT_SOURCE_MATCH,
    LITERATURE_PLAUSIBILITY,
    NEARBY_TRAIT_MATCH,
    NEGATIVE_OR_CONFLICTING_EVIDENCE,
    SAME_GENE_OR_LOCUS,
    answerability_for_lane,
    evidence_support_level_for_score,
    empty_lanes,
    lane,
)
from ....evidence.store.candidate_groups import ALL_CLINVAR_REVIEW_EVIDENCE_GROUPS
from ....evidence.sources import evidence_source_catalog

from ._base import (
    CANCER_RISK_SOURCE_IDS,
    RARE_DISEASE_SOURCE_IDS,
    _dedupe,
    _record_template,
    _safe_external_targets,
    _short_search_query,
    _variant_candidate_id,
)
from .review_groups import (
    filtered_review_groups,
    review_group_rows,
)


def _stored_research_context(
    evidence_db: Path,
    *,
    genes: list[str],
    condition: str | None,
    topic: str | None,
    question: str | None,
    genome_build: str,
    limit: int,
) -> dict[str, Any]:
    exact_targets: list[dict[str, Any]] = []
    for gene in genes:
        exact_targets.append(_query_research(evidence_db, "gene", gene=gene, genome_build=genome_build, limit=limit))
    if condition:
        exact_targets.append(_query_research(evidence_db, "condition", condition=condition, genome_build=genome_build, limit=limit))
    if topic:
        exact_targets.append(_query_research(evidence_db, "topic", topic=topic, genome_build=genome_build, limit=limit))

    searches = []
    for query in _stored_search_queries(genes=genes, condition=condition, topic=topic, question=question):
        searches.append(_search_research(evidence_db, query, limit=limit))
    record_count = sum(int(item.get("count") or 0) for item in exact_targets) + sum(int(item.get("count") or 0) for item in searches)
    return {
        "status": "searched",
        "exact_targets": exact_targets,
        "searches": searches,
        "summary": {
            "record_count": record_count,
            "exact_target_count": len(exact_targets),
            "search_count": len(searches),
        },
    }


def _query_research(
    evidence_db: Path,
    target_type: str,
    *,
    gene: str | None = None,
    condition: str | None = None,
    topic: str | None = None,
    genome_build: str,
    limit: int,
) -> dict[str, Any]:
    try:
        return query_research_findings(
            evidence_db,
            target_type,
            gene=gene,
            condition=condition,
            topic=topic,
            genome_build=genome_build,
            limit=limit,
        )
    except (OSError, ValueError, sqlite3.Error) as exc:
        return {"status": "unavailable", "target_type": target_type, "count": 0, "records": [], "error": str(exc)}


def _search_research(evidence_db: Path, query: str, *, limit: int) -> dict[str, Any]:
    try:
        return search_research_findings(evidence_db, query, limit=limit)
    except (OSError, ValueError, sqlite3.Error) as exc:
        return {"status": "unavailable", "query": {"search": query}, "count": 0, "records": [], "error": str(exc)}


def _stored_search_queries(
    *,
    genes: list[str],
    condition: str | None,
    topic: str | None,
    question: str | None,
) -> list[str]:
    queries: list[str] = []
    if genes and condition:
        queries.extend(f"{gene} {condition}" for gene in genes)
    if genes and topic and topic != condition:
        queries.extend(f"{gene} {topic}" for gene in genes)
    if condition:
        queries.append(condition)
    elif topic:
        queries.append(topic)
    elif question:
        queries.append(question)
    return _dedupe([_short_search_query(query) for query in queries if query])


def _gene_context(
    evidence_db: Path,
    genes: list[str],
    *,
    matches_path: Path | None,
    genome_build: str,
    limit: int,
) -> dict[str, Any]:
    contexts = []
    for gene in genes[:limit]:
        try:
            gathered = fetch_gene_evidence(
                gene,
                evidence_db,
                matches_path=matches_path,
                genome_build=genome_build,
                clinvar_limit=limit,
                sample_limit=limit,
            )
        except (OSError, ValueError) as exc:
            contexts.append({"gene": gene, "status": "unavailable", "error": str(exc)})
            continue
        sample_matches = gathered.get("sample_matches") or {}
        clinvar_gene = gathered.get("clinvar_gene") or {}
        contexts.append(
            {
                "gene": gene,
                "status": "available",
                "sample_match_count": int(sample_matches.get("total_records") or 0),
                "clinvar_gene_record_count": int(clinvar_gene.get("total_records") or 0),
                "strict_pathogenic_or_likely_pathogenic_count": int(
                    clinvar_gene.get("strict_pathogenic_or_likely_pathogenic_count") or 0
                ),
                "clinical_significance_counts": clinvar_gene.get("clinical_significance_counts") or [],
                "review_status_counts": clinvar_gene.get("review_status_counts") or [],
                "reviewed_research_count": int((gathered.get("research_evidence") or {}).get("count") or 0),
                "evidence_options": gathered.get("evidence_options") or [],
            }
        )
    return {
        "status": "available" if contexts else "not_requested",
        "contexts": contexts,
        "summary": {
            "gene_count": len(contexts),
            "sample_gene_match_count": sum(int(item.get("sample_match_count") or 0) for item in contexts),
            "reviewed_research_count": sum(int(item.get("reviewed_research_count") or 0) for item in contexts),
        },
    }


def _active_candidate_context(
    evidence_db: Path,
    matches_path: Path | None,
    *,
    mode: str,
    genes: list[str],
    condition: str | None,
    genome_build: str,
    limit: int,
) -> dict[str, Any]:
    if matches_path is None:
        return {
            "status": "not_selected",
            "summary": {"candidate_count": 0},
            "candidate_summaries": [],
        }
    evidence_groups = list(ALL_CLINVAR_REVIEW_EVIDENCE_GROUPS)
    try:
        inventory = extract_clinvar_candidates(
            matches_path,
            evidence_db,
            genome_build=genome_build,
            limit=limit,
            evidence_groups=evidence_groups,
        )
    except (OSError, ValueError) as exc:
        return {
            "status": "unavailable",
            "summary": {"candidate_count": 0},
            "candidate_summaries": [],
            "error": str(exc),
        }
    candidates = [
        _active_candidate_summary(candidate, genes=genes, condition=condition)
        for candidate in (inventory.get("candidate_inventory") or [])[:limit]
    ]
    filtered = [
        candidate
        for candidate in candidates
        if candidate["target_match_status"] != "not_requested_target_mismatch"
    ]
    review_groups = filtered_review_groups(
        inventory.get("candidate_review_groups"),
        mode=mode,
        genes=genes,
        condition=condition,
        limit=limit,
    )
    inventory_summary = inventory.get("summary") if isinstance(inventory.get("summary"), dict) else {}
    target_filter_applied = bool(genes or condition)
    result_state = _active_candidate_result_state(
        filtered_count=max(len(filtered), int(review_groups.get("group_count") or 0)),
        unfiltered_count=max(len(candidates), int((inventory.get("candidate_review_groups") or {}).get("group_count") or 0) if isinstance(inventory.get("candidate_review_groups"), dict) else 0),
        target_filter_applied=target_filter_applied,
    )
    return {
        "status": "available",
        "selection": {
            "evidence_groups": evidence_groups,
            "target_filter_applied": target_filter_applied,
        },
        "summary": {
            "candidate_count": len(filtered),
            "review_group_count": int(review_groups.get("group_count") or 0),
            "unfiltered_candidate_count": len(candidates),
            "unfiltered_review_group_count": int((inventory.get("candidate_review_groups") or {}).get("group_count") or 0) if isinstance(inventory.get("candidate_review_groups"), dict) else 0,
            "source_status": inventory.get("status"),
            "total_clinvar_match_records": inventory_summary.get("total_match_records"),
            "total_match_variants": inventory_summary.get("total_match_variants"),
            "total_exact_match_variants": inventory_summary.get("total_exact_match_variants"),
            "total_exact_allele_match_variants": inventory_summary.get("total_exact_allele_match_variants"),
            "total_consumer_array_inferred_match_variants": inventory_summary.get("total_consumer_array_inferred_match_variants"),
            "match_basis_counts": inventory_summary.get("match_basis_counts"),
            "selected_candidate_variants": inventory_summary.get("selected_candidate_variants"),
        },
        "result_state": result_state,
        "candidate_summaries": filtered,
        "candidate_review_groups": review_groups,
    }


def _active_candidate_result_state(
    *,
    filtered_count: int,
    unfiltered_count: int,
    target_filter_applied: bool,
) -> str:
    if filtered_count:
        return "candidate_inventory_hits_present"
    if target_filter_applied and unfiltered_count:
        return "candidate_inventory_hits_outside_requested_target"
    if target_filter_applied:
        return "no_candidate_inventory_hits_for_requested_target"
    return "no_candidate_inventory_hits_in_selected_evidence_groups"


def _active_candidate_summary(candidate: dict[str, Any], *, genes: list[str], condition: str | None) -> dict[str, Any]:
    variant = candidate.get("variant") or {}
    match_provenance = candidate.get("match_provenance") or {}
    candidate_genes = [str(item).upper() for item in candidate.get("genes") or []]
    conditions = [str(item) for item in (candidate.get("clinvar") or {}).get("conditions") or []]
    target_match_status = _target_match_status(candidate_genes, conditions, genes=genes, condition=condition)
    return {
        "candidate_id": _variant_candidate_id(variant),
        "match_provenance": match_provenance,
        "variant": {
            "chrom": variant.get("chrom"),
            "pos": variant.get("pos"),
            "ref": variant.get("ref"),
            "alt": variant.get("alt"),
            "genotype": variant.get("genotype"),
            "filter": variant.get("filter"),
            "source_record_ref": variant.get("source_record_ref"),
            "source_record_alt": variant.get("source_record_alt"),
            "source_record_format": variant.get("source_record_format"),
            "source_record_genotype": variant.get("source_record_genotype"),
        },
        "genes": candidate_genes,
        "conditions": conditions,
        "clinical_significance_counts": (candidate.get("clinvar") or {}).get("clinical_significance_counts") or [],
        "review_status_counts": (candidate.get("clinvar") or {}).get("review_status_counts") or [],
        "evidence_groups": candidate.get("evidence_groups") or [],
        "tags": candidate.get("tags") or [],
        "population_evidence": candidate.get("population_evidence") or {},
        "genotype_support": candidate.get("genotype_support") or {},
        "decision_points": candidate.get("decision_points") or [],
        "target_match_status": target_match_status,
    }


def _target_match_status(
    candidate_genes: list[str],
    conditions: list[str],
    *,
    genes: list[str],
    condition: str | None,
) -> str:
    if not genes and not condition:
        return "no_target_filter"
    if genes and set(candidate_genes) & set(genes):
        return "requested_gene_match"
    if condition:
        condition_text = condition.casefold()
        if any(condition_text in item.casefold() for item in conditions):
            return "requested_condition_text_match"
    return "not_requested_target_mismatch"


def _source_plan(mode: str, *, target: dict[str, Any], context_scope: str) -> dict[str, Any]:
    source_ids = CANCER_RISK_SOURCE_IDS if mode == "cancer_risk" else RARE_DISEASE_SOURCE_IDS
    catalog = evidence_source_catalog()
    by_id = {source["source_id"]: source for source in catalog.get("sources") or []}
    sources = [by_id[source_id] for source_id in source_ids if source_id in by_id]
    return {
        "status": "ready",
        "investigation_type": mode,
        "safe_external_targets": _safe_external_targets(target),
        "source_order": [
            {
                "source_id": source["source_id"],
                "title": source["title"],
                "query_mode": source["agent_contract"]["query_mode"],
                "best_for": source["best_for"],
                "limitations": source["limitations"],
                "official_url": source.get("official_url"),
            }
            for source in sources
        ],
        "review_steps": _review_steps(mode, context_scope=context_scope),
        "write_back_rule": "Record narrow reviewed findings before using public source context in an interpretation or report.",
    }


def _review_steps(mode: str, *, context_scope: str) -> list[str]:
    steps = []
    if context_scope == "active_genome_index_selected":
        steps.extend(
            [
                "Start from observed sample variants and gene-level sample matches; treat them as review targets, not diagnoses.",
                "For any exact allele selected for interpretation, check genotype support and population evidence before personal wording.",
            ]
        )
    else:
        steps.append("Keep the answer public-only; do not imply anything about a person's genome.")
    steps.extend(
        [
            "Use ClinVar for exact variant assertions and review status when a variant target exists.",
            "Use ClinGen and GenCC to cross-check gene-disease validity before treating gene context as disease evidence.",
            "Use GeneReviews when disease mechanism, inheritance, penetrance, or management context is needed.",
            "Use GeneCards for gene aliases, function, pathway, and disease-association context; cross-check clinical claims in validity or clinical sources.",
            "Use MalaCards for disease-centric aliases, phenotype, and associated-gene context; cross-check gene-disease strength elsewhere.",
        ]
    )
    if mode == "cancer_risk":
        steps.extend(
            [
                "Separate inherited germline cancer-risk evidence from somatic cancer biology evidence.",
                "Use NCI cancer genetics material for hereditary cancer framing and genetic-counseling boundaries.",
                "Use COSMIC Cancer Gene Census only for cancer-gene role context unless a source explicitly supports germline risk.",
            ]
        )
    elif mode == "carrier_review":
        steps.extend(
            [
                "Treat heterozygous ClinVar P/LP groups as carrier-relevance evidence, not carrier status.",
                "Resolve inheritance, phase, zygosity, population frequency, source review, and clinical confirmation before carrier-style wording.",
            ]
        )
    elif mode == "observed_condition_review":
        steps.extend(
            [
                "Separate observed-condition, uncertain, risk-association, benign, and population-context groups before interpretation.",
                "Do not convert a source review group into a clinical finding without the required interpretation gates.",
            ]
        )
    return steps


def _candidate_matrix(
    *,
    target: dict[str, Any],
    context_scope: str,
    stored_research: dict[str, Any],
    gene_context: dict[str, Any],
    active_candidates: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    group_rows = review_group_rows(active_candidates)
    rows.extend(group_rows)
    group_review_mode = target.get("investigation_type") in {"carrier_review", "observed_condition_review"}
    if not (group_review_mode and group_rows):
        rows.extend(_sample_variant_rows(active_candidates))
        rows.extend(_gene_rows(target, stored_research=stored_research, gene_context=gene_context))
        if target.get("condition"):
            rows.append(_text_target_row("condition", str(target["condition"]), stored_research, context_scope=context_scope))
        if target.get("topic") and target.get("topic") != target.get("condition"):
            rows.append(_text_target_row("topic", str(target["topic"]), stored_research, context_scope=context_scope))
    rows = _dedupe_candidate_rows(rows)
    rows.sort(key=_candidate_row_sort_key)
    for index, row in enumerate(rows, start=1):
        row["rank"] = index
        row["why_not_selected"] = [] if index == 1 else ["Lower investigation-priority score than the selected review target."]
    return rows


def _candidate_row_sort_key(item: dict[str, Any]) -> tuple[float, int, int, str]:
    lane_order = {
        DIRECT_SOURCE_MATCH: 0,
        SAME_GENE_OR_LOCUS: 1,
        NEARBY_TRAIT_MATCH: 2,
        LITERATURE_PLAUSIBILITY: 3,
        NEGATIVE_OR_CONFLICTING_EVIDENCE: 4,
        AGENT_REASONING_ONLY: 5,
    }
    type_order = {
        "clinvar_review_group": 0,
        "sample_variant": 1,
        "gene": 2,
        "condition": 3,
        "topic": 4,
    }
    return (
        -float(item.get("score") or 0.0),
        lane_order.get(str(item.get("best_evidence_lane") or ""), 9),
        type_order.get(str(item.get("candidate_type") or ""), 9),
        str(item.get("candidate_id") or ""),
    )


def _sample_variant_rows(active_candidates: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for candidate in active_candidates.get("candidate_summaries") or []:
        best_lane = _sample_variant_lane(candidate)
        score = _sample_variant_score(candidate, best_lane)
        lanes = empty_lanes()
        lanes[best_lane] = lane(
            best_lane,
            status="present",
            score=score,
            source="ClinVar sample match",
            matched_text=_sample_variant_text(candidate),
            note="observed active-genome-index candidate requiring source review",
        )
        rows.append(
            {
                "candidate_id": candidate["candidate_id"],
                "candidate_type": "sample_variant",
                "rank": None,
                "score": score,
                "evidence_support_level": evidence_support_level_for_score(score),
                "answerability": answerability_for_lane(best_lane),
                "best_evidence_lane": best_lane,
                "evidence_lanes": lanes,
                "supporting_evidence": [candidate],
                "counter_evidence": _sample_variant_counter_evidence(candidate),
            }
        )
    return rows


def _sample_variant_lane(candidate: dict[str, Any]) -> str:
    tags = set(candidate.get("tags") or [])
    if "clinvar_conflicting" in tags or "clinvar_vus" in tags:
        return NEGATIVE_OR_CONFLICTING_EVIDENCE
    if "clinvar_risk_association_protective" in set(candidate.get("evidence_groups") or []):
        return NEARBY_TRAIT_MATCH
    if _candidate_primary_match_basis(candidate) == "consumer_array_allele_inference":
        return SAME_GENE_OR_LOCUS
    return DIRECT_SOURCE_MATCH


def _sample_variant_score(candidate: dict[str, Any], best_lane: str) -> float:
    if best_lane == DIRECT_SOURCE_MATCH:
        return 0.9
    if best_lane == NEARBY_TRAIT_MATCH:
        return 0.65
    if best_lane == SAME_GENE_OR_LOCUS:
        return 0.6
    return 0.35


def _sample_variant_text(candidate: dict[str, Any]) -> str:
    significance = ", ".join(
        f"{label}:{count}" for label, count in (candidate.get("clinical_significance_counts") or [])[:3]
    )
    genes = ", ".join(candidate.get("genes") or [])
    basis = _candidate_primary_match_basis(candidate)
    provenance_note = "consumer-array allele inference" if basis == "consumer_array_allele_inference" else str(basis or "")
    return f"{candidate['candidate_id']} {genes} {significance} {provenance_note}".strip()


def _candidate_primary_match_basis(candidate: dict[str, Any]) -> str | None:
    provenance = candidate.get("match_provenance")
    if not isinstance(provenance, dict):
        return None
    basis = provenance.get("primary_match_basis")
    return str(basis) if basis else None


def _sample_variant_counter_evidence(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    counter = []
    tags = set(candidate.get("tags") or [])
    if "population_frequency_common" in tags or "population_homozygotes_present" in tags:
        counter.append({"type": "population_tension", "note": "Public population evidence may downgrade personal disease-style interpretation."})
    if "clinvar_vus" in tags:
        counter.append({"type": "uncertain_significance", "note": "VUS entries should not be treated as actionable risk evidence."})
    if "clinvar_conflicting" in tags:
        counter.append({"type": "conflicting_classification", "note": "Conflicting ClinVar assertions require source review before use."})
    return counter


def _gene_rows(target: dict[str, Any], *, stored_research: dict[str, Any], gene_context: dict[str, Any]) -> list[dict[str, Any]]:
    exact_counts = _exact_research_counts(stored_research)
    context_by_gene = {item.get("gene"): item for item in gene_context.get("contexts") or []}
    rows = []
    for gene in target.get("genes") or []:
        context = context_by_gene.get(gene) or {}
        exact_count = exact_counts.get(("gene", gene), 0)
        sample_count = int(context.get("sample_match_count") or 0)
        clinvar_count = int(context.get("clinvar_gene_record_count") or 0)
        best_lane = _gene_best_lane(exact_count, sample_count, clinvar_count)
        score = _gene_score(best_lane, exact_count=exact_count, sample_count=sample_count, clinvar_count=clinvar_count)
        lanes = empty_lanes()
        lanes[best_lane] = lane(
            best_lane,
            status="present" if score > 0 else "target_selected",
            score=score,
            source="reviewed research" if exact_count else ("Active Genome Index" if sample_count else "user target"),
            matched_text=gene,
            note="gene-level investigation target",
        )
        rows.append(
            {
                "candidate_id": f"gene:{gene}",
                "candidate_type": "gene",
                "rank": None,
                "score": score,
                "evidence_support_level": evidence_support_level_for_score(score),
                "answerability": answerability_for_lane(best_lane),
                "best_evidence_lane": best_lane,
                "evidence_lanes": lanes,
                "supporting_evidence": [
                    {
                        "gene": gene,
                        "reviewed_research_count": exact_count,
                        "sample_match_count": sample_count,
                        "clinvar_gene_record_count": clinvar_count,
                        "strict_pathogenic_or_likely_pathogenic_count": context.get("strict_pathogenic_or_likely_pathogenic_count"),
                    }
                ],
                "counter_evidence": [],
            }
        )
    return rows


def _gene_best_lane(exact_count: int, sample_count: int, clinvar_count: int) -> str:
    if exact_count:
        return DIRECT_SOURCE_MATCH
    if sample_count:
        return SAME_GENE_OR_LOCUS
    if clinvar_count:
        return LITERATURE_PLAUSIBILITY
    return AGENT_REASONING_ONLY


def _gene_score(best_lane: str, *, exact_count: int, sample_count: int, clinvar_count: int) -> float:
    if best_lane == DIRECT_SOURCE_MATCH:
        return min(0.85, 0.65 + exact_count * 0.05)
    if best_lane == SAME_GENE_OR_LOCUS:
        return min(0.7, 0.5 + sample_count * 0.03)
    if best_lane == LITERATURE_PLAUSIBILITY:
        return min(0.45, 0.25 + clinvar_count * 0.01)
    return 0.0


def _text_target_row(target_type: str, value: str, stored_research: dict[str, Any], *, context_scope: str) -> dict[str, Any]:
    exact_count = _exact_research_counts(stored_research).get((target_type, value.casefold()), 0)
    best_lane = DIRECT_SOURCE_MATCH if exact_count else AGENT_REASONING_ONLY
    score = min(0.75, 0.55 + exact_count * 0.05) if exact_count else 0.0
    lanes = empty_lanes()
    lanes[best_lane] = lane(
        best_lane,
        status="present" if exact_count else "target_selected",
        score=score,
        source="reviewed research" if exact_count else "user target",
        matched_text=value,
        note=f"{target_type}-level investigation target",
    )
    return {
        "candidate_id": f"{target_type}:{value}",
        "candidate_type": target_type,
        "rank": None,
        "score": score,
        "evidence_support_level": evidence_support_level_for_score(score),
        "answerability": answerability_for_lane(best_lane),
        "best_evidence_lane": best_lane,
        "evidence_lanes": lanes,
        "supporting_evidence": [
            {
                "target_type": target_type,
                "target": value,
                "reviewed_research_count": exact_count,
                "context_scope": context_scope,
            }
        ],
        "counter_evidence": [],
    }


def _exact_research_counts(stored_research: dict[str, Any]) -> dict[tuple[str, str], int]:
    counts: dict[tuple[str, str], int] = {}
    for item in stored_research.get("exact_targets") or []:
        query = item.get("query") or {}
        target_type = str(query.get("target_type") or item.get("target_type") or "")
        if target_type == "gene" and query.get("gene"):
            key = ("gene", str(query["gene"]).upper())
        elif target_type == "condition" and query.get("condition"):
            key = ("condition", str(query["condition"]).casefold())
        elif target_type == "topic" and query.get("topic"):
            key = ("topic", str(query["topic"]).casefold())
        else:
            continue
        counts[key] = counts.get(key, 0) + int(item.get("count") or 0)
    return counts


def _dedupe_candidate_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    seen = set()
    for row in rows:
        key = str(row.get("candidate_id") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(row)
    return output


def _decision_policy(mode: str, *, context_scope: str) -> dict[str, Any]:
    return {
        "policy_id": "condition_review_investigation_v1",
        "investigation_type": mode,
        "context_scope": context_scope,
        "ranking_order": [
            "ClinVar candidate review groups for the selected investigation type",
            "observed active-genome-index candidate variants when selected",
            "stored reviewed public-target findings",
            "gene-level sample matches",
            "gene or condition context needing source review",
        ],
        "rule": (
            "Rank review targets for investigation; do not convert target rank into diagnosis, actionability, or quantitative personal risk."
        ),
    }


def _warnings(
    stored_research: dict[str, Any],
    active_candidates: dict[str, Any],
    *,
    context_scope: str,
) -> list[str]:
    warnings = []
    if context_scope == "public_only":
        warnings.append("public_only_context:user_specific_ranking_not_assessed")
    if int((stored_research.get("summary") or {}).get("record_count") or 0) == 0:
        warnings.append("no_stored_reviewed_research:source_review_not_returned")
    active_summary = active_candidates.get("summary") or {}
    if (
        active_candidates.get("status") == "available"
        and int(active_summary.get("candidate_count") or 0) == 0
        and int(active_summary.get("review_group_count") or 0) == 0
    ):
        warnings.append("no_clinvar_candidate_review_groups:review_selected_group_contract")
    return warnings


def _next_actions(mode: str, *, target: dict[str, Any], context_scope: str) -> list[dict[str, Any]]:
    actions = []
    for gene in target.get("genes") or []:
        actions.append(
            {
                "operation": "variant.gather_gene_context",
                "params": {"gene": gene, "genome_build": target.get("genome_build")},
                "reason": "refresh gene-level ClinVar, sample-match, and reviewed-source context",
            }
        )
    if context_scope == "active_genome_index_selected":
        actions.append(
            {
                "operation": "active_genome_index.classify_genotype_support",
                "params": {"chrom": "<chrom>", "pos": "<pos>", "ref": "<ref>", "alt": "<alt>"},
                "reason": "confirm exact sample support before personal wording for a selected allele",
            }
        )
    actions.append(
        {
            "operation": "research.record",
            "params": {"payload": "<reviewed finding>", "scope": "shared"},
            "reason": "store source-backed findings from GeneCards, MalaCards, ClinGen, GenCC, GeneReviews, NCI, or COSMIC review",
        }
    )
    if mode == "cancer_risk":
        actions.append(
            {
                "operation": "research.query",
                "params": {"target_type": "gene", "gene": "<gene>"},
                "reason": "separate hereditary cancer source support from somatic cancer-gene context before final synthesis",
            }
        )
    return actions


def _record_research_templates(target: dict[str, Any]) -> list[dict[str, Any]]:
    templates = []
    for gene in target.get("genes") or []:
        templates.append(_record_template({"type": "gene", "gene": gene}))
    if target.get("condition"):
        templates.append(_record_template({"type": "condition", "condition": target["condition"]}))
    if target.get("topic"):
        templates.append(_record_template({"type": "topic", "topic": target["topic"]}))
    return templates
