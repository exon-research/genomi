from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ....evidence import envelope as _env
from ....evidence.candidate_evidence import (
    apply_evidence_view,
    evidence_view,
)
from ....evidence.task_profiles import RARE_DISEASE_CANCER_RISK_INVESTIGATION
from ....runtime.handoff import evidence_context

from ._base import (
    CANCER_TERMS,
    RARE_DISEASE_TERMS,
    RISK_INVESTIGATION_SCHEMA_VERSION,
    RISK_INVESTIGATION_TYPES,
    _clean_text,
    _normalize_genes,
)
from .builders import (
    _active_candidate_context,
    _candidate_matrix,
    _decision_policy,
    _gene_context,
    _next_actions,
    _record_research_templates,
    _source_plan,
    _stored_research_context,
    _warnings,
)


def prepare_risk_investigation(
    evidence_db: str | Path,
    *,
    question: str | None = None,
    investigation_type: str = "auto",
    gene: str | None = None,
    genes: Iterable[str] | None = None,
    condition: str | None = None,
    topic: str | None = None,
    matches: str | Path | None = None,
    genome_build: str = "GRCh38",
    limit: int = 25,
    search_stored_research: bool = True,
) -> dict[str, Any]:
    """Prepare a source-review plan and optional Active Genome Index context for disease/cancer risk questions."""
    bounded_limit = max(1, min(int(limit or 25), 200))
    normalized_genes = _normalize_genes(gene, genes)
    normalized_condition = _clean_text(condition)
    normalized_topic = _clean_text(topic) or _clean_text(question)
    question_text = _clean_text(question)
    if not any((question_text, normalized_genes, normalized_condition, normalized_topic)):
        raise ValueError("phenotype.plan_risk_investigation requires question, gene, condition, or topic")

    mode = _resolve_investigation_type(
        investigation_type,
        question=question_text,
        condition=normalized_condition,
        topic=normalized_topic,
    )
    matches_path = Path(matches) if matches is not None else None
    missing_matches_path: Path | None = None
    if matches_path is not None and not matches_path.exists():
        # The Active Genome Index ClinVar match file is materialized lazily by the
        # ClinVar scan; if a caller hands us a path that has not been produced
        # yet, degrade to public-only context with a note instead of hard-
        # crashing the background job. Otherwise the first open-ended risk
        # question after parse_source aborts the investigation.
        missing_matches_path = matches_path
        matches_path = None
    evidence_db_path = Path(evidence_db)

    target = {
        "question": question_text,
        "investigation_type": mode,
        "genes": normalized_genes,
        "condition": normalized_condition,
        "topic": normalized_topic,
        "genome_build": genome_build,
    }
    context_scope = "active_genome_index_selected" if matches_path is not None else "public_only"
    stored_research = (
        _stored_research_context(
            evidence_db_path,
            genes=normalized_genes,
            condition=normalized_condition,
            topic=normalized_topic,
            question=question_text,
            genome_build=genome_build,
            limit=bounded_limit,
        )
        if search_stored_research
        else {"status": "not_requested", "exact_targets": [], "searches": [], "summary": {"record_count": 0}}
    )
    gene_context = _gene_context(
        evidence_db_path,
        normalized_genes,
        matches_path=matches_path,
        genome_build=genome_build,
        limit=bounded_limit,
    )
    active_candidates = _active_candidate_context(
        evidence_db_path,
        matches_path,
        mode=mode,
        genes=normalized_genes,
        condition=normalized_condition,
        genome_build=genome_build,
        limit=bounded_limit,
    )
    source_plan = _source_plan(mode, target=target, context_scope=context_scope)
    matrix = _candidate_matrix(
        target=target,
        context_scope=context_scope,
        stored_research=stored_research,
        gene_context=gene_context,
        active_candidates=active_candidates,
    )
    selected = matrix[0] if matrix else None
    view = evidence_view(
        task_profile=RARE_DISEASE_CANCER_RISK_INVESTIGATION,
        query=target,
        candidate_matrix=matrix,
        top_observed_candidate=selected,
        evidence_policy=_decision_policy(mode, context_scope=context_scope),
        warnings=_warnings(
            stored_research,
            active_candidates,
            context_scope=context_scope,
            missing_matches_path=missing_matches_path,
        ),
    )
    payload = {
        "schema": RISK_INVESTIGATION_SCHEMA_VERSION,
        "status": "completed",
        "workflow_area": "research",
        "context_scope": context_scope,
        "target": target,
        "source_plan": source_plan,
        "stored_research": stored_research,
        "gene_context": gene_context,
        "active_genome_index_evidence": active_candidates,
        "record_research_templates": _record_research_templates(target),
        "next_actions": _next_actions(mode, target=target, context_scope=context_scope),
        "evidence_context": evidence_context(
            "research",
            reason="Risk investigation guidance is ready; record reviewed public findings before report synthesis.",
            commands=[
                "genomi call research.list_sources --params '{\"target_type\":\"gene\"}'",
                "genomi call research.record --params '{\"payload\":{...},\"scope\":\"shared\"}'",
                "genomi call variant.gather_gene_context --params '{\"gene\":\"<GENE>\"}'",
            ],
        ),
    }
    personal_context = _env._personal_context(
        uses_personal_dna=context_scope == "active_genome_index_selected",
        source=str(matches_path) if matches_path else None,
    )
    risk_envelope = _build_risk_envelope(
        view=view,
        target=target,
        context_scope=context_scope,
        active_candidates=active_candidates,
        personal_context=personal_context,
    )
    apply_evidence_view(
        payload,
        view,
        operation="phenotype.plan_risk_investigation",
        envelope=risk_envelope,
        personal_context=personal_context,
    )
    return payload


def _build_risk_envelope(
    *,
    view: dict[str, Any],
    target: dict[str, Any],
    context_scope: str,
    active_candidates: dict[str, Any],
    personal_context: dict[str, Any],
) -> dict[str, Any]:
    active_status = active_candidates.get("status")
    active_count = int((active_candidates.get("summary") or {}).get("candidate_count") or 0)
    rankings = view.get("rankings") or []
    query_scope = {
        **(dict(view.get("query") or {})),
        "context_scope": context_scope,
        "investigation_type": target.get("investigation_type"),
    }
    coverage = _env._coverage(
        consulted_sources=["clinvar_candidate_inventory"] if context_scope == "active_genome_index_selected" else [],
        unavailable_sources=[] if active_status == "available" else ["clinvar_candidate_inventory"],
    )
    observations = {
        "active_candidate_count": active_count,
        "ranked_review_targets": len(rankings),
        "result_state": active_candidates.get("result_state"),
    }

    if context_scope == "active_genome_index_selected" and active_status == "available" and active_count == 0:
        return _env.empty_consulted_scope(
            operation="phenotype.plan_risk_investigation",
            query_scope=query_scope,
            personal_context=personal_context,
            coverage=coverage,
            observations=observations,
            requires_for_true_negative=(
                _env.REQ_CALLABILITY,
                _env.REQ_LIBRARY_COVERAGE,
                _env.REQ_GENOTYPE_SUPPORT,
                _env.REQ_CLINICAL_CONFIRMATION,
            ),
            notes=[
                "Zero stored ClinVar candidate-inventory hits in the selected evidence groups is a scoped result, not a clinical negative.",
            ],
        )

    if rankings:
        return _env.evidence_present(
            operation="phenotype.plan_risk_investigation",
            query_scope=query_scope,
            personal_context=personal_context,
            coverage=coverage,
            observations=observations,
            answer_readiness=_env.SCOPED_ANSWER_ONLY,
        )

    return _env.not_assessed(
        operation="phenotype.plan_risk_investigation",
        reason="No review targets ranked; provide gene, condition, or topic.",
        query_scope=query_scope,
        personal_context=personal_context,
        coverage=coverage,
        observations=observations,
    )


def risk_investigation_type_choices() -> list[str]:
    return list(RISK_INVESTIGATION_TYPES)


def _resolve_investigation_type(
    investigation_type: str,
    *,
    question: str | None,
    condition: str | None,
    topic: str | None,
) -> str:
    value = str(investigation_type or "auto").strip().lower()
    if value not in RISK_INVESTIGATION_TYPES:
        raise ValueError("investigation_type must be one of: " + ", ".join(RISK_INVESTIGATION_TYPES))
    if value != "auto":
        return value
    text = " ".join(item for item in (question, condition, topic) if item).casefold()
    if any(term in text for term in CANCER_TERMS):
        return "cancer_risk"
    if any(term in text for term in RARE_DISEASE_TERMS):
        return "rare_disease"
    return "rare_disease"
