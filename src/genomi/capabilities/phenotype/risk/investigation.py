from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ....evidence import envelope as _env
from ....evidence.candidate_evidence import (
    apply_evidence_view,
    evidence_view,
)
from ....evidence.store.candidate_groups import missing_interpretation_gates
from ....evidence.task_profiles import RARE_DISEASE_CANCER_RISK_INVESTIGATION
from ....runtime.handoff import evidence_context

from ._base import (
    CANCER_TERMS,
    CARRIER_REVIEW_TERMS,
    OBSERVED_CONDITION_REVIEW_TERMS,
    RARE_DISEASE_TERMS,
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
    matches_path = Path(matches) if matches is not None else None
    if not any((question_text, normalized_genes, normalized_condition, normalized_topic, matches_path)):
        raise ValueError("phenotype.plan_risk_investigation requires question, gene, condition, topic, or matches")

    evidence_db_path = Path(evidence_db)
    mode = _resolve_investigation_type(
        investigation_type,
        question=question_text,
        condition=normalized_condition,
        topic=normalized_topic,
        has_active_candidate_inventory=matches_path is not None,
    )

    target = {
        "question": question_text,
        "investigation_type": mode,
        "genes": normalized_genes,
        "condition": normalized_condition,
        "topic": normalized_topic,
        "genome_build": genome_build,
    }
    if matches_path is not None and not matches_path.exists():
        return _materialization_incomplete_response(target, mode=mode, genome_build=genome_build)

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
        ),
    )
    payload = {
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
            reason="Risk investigation guidance is ready; record reviewed public findings before user-facing interpretation.",
            commands=[
                "genomi call research.list_sources --params '{\"target_type\":\"gene\"}'",
                "genomi call research.record --params '{\"payload\":{...},\"scope\":\"shared\"}'",
                "genomi call variant.gather_gene_context --params '{\"gene\":\"<GENE>\"}'",
            ],
        ),
    }
    personal_context = _env._personal_context(
        uses_personal_dna=context_scope == "active_genome_index_selected",
        source="clinvar_candidate_inventory" if matches_path else None,
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


def _materialization_incomplete_response(
    target: dict[str, Any],
    *,
    mode: str,
    genome_build: str,
) -> dict[str, Any]:
    context_scope = "active_genome_index_selected"
    clinvar_library = _clinvar_library_for_build(genome_build)
    materialization = {
        "library": clinvar_library,
        "artifact": "clinvar_candidate_inventory",
        "status": "not_materialized",
        "genome_build": genome_build,
    }
    active_candidates = {
        "status": "materialization_incomplete",
        "summary": {"candidate_count": 0, "review_group_count": 0},
        "result_state": "clinvar_candidate_inventory_not_materialized",
        "materialization": materialization,
        "candidate_summaries": [],
        "candidate_review_groups": {
            "policy_id": "clinvar_candidate_review_groups_v1",
            "group_count": 0,
            "groups": [],
            "group_counts_by_type": [],
        },
    }
    next_actions = [
        {
            "operation": "clinvar.scan_candidates",
            "params": {"genome_build": genome_build},
            "materializes": "clinvar_candidate_inventory",
            "uses_active_genome_index": True,
        }
    ]
    view = evidence_view(
        task_profile=RARE_DISEASE_CANCER_RISK_INVESTIGATION,
        query=target,
        candidate_matrix=[],
        top_observed_candidate=None,
        evidence_policy=_decision_policy(mode, context_scope=context_scope),
        warnings=[],
        evidence_state="materialization_incomplete",
        coverage_state="materialization_incomplete",
    )
    personal_context = _env._personal_context(
        uses_personal_dna=True,
        source="clinvar_candidate_inventory",
    )
    coverage = _env._coverage(
        libraries=[
            _env.LibraryUse(
                library=clinvar_library,
                state="not_materialized",
                materialization_id="clinvar_candidate_inventory",
            )
        ],
        unavailable_sources=["clinvar_candidate_inventory"],
        materialization=[materialization],
    )
    envelope = _env.envelope(
        operation="phenotype.plan_risk_investigation",
        finding_state=_env.MATERIALIZATION_INCOMPLETE,
        answer_readiness=_env.NEEDS_MATERIALIZATION,
        query_scope={
            **target,
            "context_scope": context_scope,
            "investigation_type": target.get("investigation_type"),
        },
        personal_context=personal_context,
        coverage=coverage,
        observations={
            "active_candidate_count": 0,
            "active_candidate_review_group_count": 0,
            "candidate_review_group_counts_by_type": [],
            "missing_interpretation_gates": [],
            "ranked_review_targets": 0,
            "result_state": active_candidates["result_state"],
            "pending_materialization": "clinvar_candidate_inventory",
        },
        negative_inference=_env._negative_inference(
            allowed=False,
            requires=[_env.REQ_LIBRARY_COVERAGE],
            reason="ClinVar candidate inventory materialization is incomplete.",
        ),
        next_actions=next_actions,
    )
    payload = {
        "status": "materialization_incomplete",
        "workflow_area": "research",
        "context_scope": context_scope,
        "target": target,
        "source_plan": _source_plan(mode, target=target, context_scope=context_scope),
        "stored_research": {
            "status": "not_searched",
            "exact_targets": [],
            "searches": [],
            "summary": {"record_count": 0},
        },
        "gene_context": {
            "status": "not_requested",
            "contexts": [],
            "summary": {
                "gene_count": 0,
                "sample_gene_match_count": 0,
                "reviewed_research_count": 0,
            },
        },
        "active_genome_index_evidence": active_candidates,
        "record_research_templates": [],
        "next_actions": next_actions,
    }
    apply_evidence_view(
        payload,
        view,
        operation="phenotype.plan_risk_investigation",
        envelope=envelope,
        personal_context=personal_context,
    )
    return payload


def _clinvar_library_for_build(genome_build: str) -> str:
    build = str(genome_build or "").strip().lower()
    if build in {"grch37", "hg19"}:
        return "clinvar-grch37"
    return "clinvar-grch38"


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
    active_group_count = int((active_candidates.get("summary") or {}).get("review_group_count") or 0)
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
        "active_candidate_review_group_count": active_group_count,
        "candidate_review_group_counts_by_type": (
            (active_candidates.get("candidate_review_groups") or {}).get("group_counts_by_type")
            if isinstance(active_candidates.get("candidate_review_groups"), dict)
            else []
        ),
        "missing_interpretation_gates": _missing_interpretation_gate_observations(active_candidates),
        "ranked_review_targets": len(rankings),
        "result_state": active_candidates.get("result_state"),
    }

    if context_scope == "active_genome_index_selected" and active_status == "available" and active_count == 0 and active_group_count == 0:
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
            answer_readiness=_env.NEEDS_CLINICAL_CONFIRMATION,
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
    has_active_candidate_inventory: bool = False,
) -> str:
    value = str(investigation_type or "auto").strip().lower()
    if value not in RISK_INVESTIGATION_TYPES:
        raise ValueError("investigation_type must be one of: " + ", ".join(RISK_INVESTIGATION_TYPES))
    if value != "auto":
        return value
    text = " ".join(item for item in (question, condition, topic) if item).casefold()
    if any(term in text for term in CANCER_TERMS):
        return "cancer_risk"
    if any(term in text for term in CARRIER_REVIEW_TERMS):
        return "carrier_review"
    if any(term in text for term in OBSERVED_CONDITION_REVIEW_TERMS):
        return "observed_condition_review"
    if any(term in text for term in RARE_DISEASE_TERMS):
        return "rare_disease"
    if has_active_candidate_inventory:
        return "observed_condition_review"
    return "rare_disease"


def _missing_interpretation_gate_observations(active_candidates: dict[str, Any]) -> list[dict[str, Any]]:
    matrix = active_candidates.get("candidate_review_groups")
    groups = matrix.get("groups") if isinstance(matrix, dict) else []
    missing: list[dict[str, Any]] = []
    for group in groups or []:
        if not isinstance(group, dict):
            continue
        gates = group.get("interpretation_gates") if isinstance(group.get("interpretation_gates"), dict) else {}
        for gate in missing_interpretation_gates(group):
            state = gates.get(gate) if isinstance(gates.get(gate), dict) else {}
            missing.append(
                {
                    "group_id": group.get("group_id"),
                    "group_type": group.get("group_type"),
                    "gate": gate,
                    "state": state.get("state"),
                }
            )
    return missing
