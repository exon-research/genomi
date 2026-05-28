"""Rare-disease / cancer risk investigation capability (facade package)."""

from __future__ import annotations

from ._base import (
    CANCER_RISK_SOURCE_IDS,
    CANCER_TERMS,
    RARE_DISEASE_SOURCE_IDS,
    RARE_DISEASE_TERMS,
    RISK_INVESTIGATION_SCHEMA_VERSION,
    RISK_INVESTIGATION_TYPES,
    _clean_text,
    _dedupe,
    _first_review_target,
    _normalize_genes,
    _record_template,
    _safe_external_targets,
    _short_search_query,
    _variant_candidate_id,
)
from .builders import (
    _active_candidate_context,
    _active_candidate_result_state,
    _active_candidate_summary,
    _candidate_matrix,
    _decision_policy,
    _dedupe_candidate_rows,
    _exact_research_counts,
    _gene_best_lane,
    _gene_context,
    _gene_rows,
    _gene_score,
    _next_actions,
    _query_research,
    _record_research_templates,
    _review_steps,
    _sample_variant_counter_evidence,
    _sample_variant_lane,
    _sample_variant_rows,
    _sample_variant_score,
    _sample_variant_text,
    _search_research,
    _source_plan,
    _stored_research_context,
    _stored_search_queries,
    _target_match_status,
    _text_target_row,
    _warnings,
)
from .investigation import (
    _build_risk_envelope,
    _resolve_investigation_type,
    prepare_risk_investigation,
    risk_investigation_type_choices,
)

__all__ = [
    "CANCER_RISK_SOURCE_IDS",
    "CANCER_TERMS",
    "RARE_DISEASE_SOURCE_IDS",
    "RARE_DISEASE_TERMS",
    "RISK_INVESTIGATION_SCHEMA_VERSION",
    "RISK_INVESTIGATION_TYPES",
    "prepare_risk_investigation",
    "risk_investigation_type_choices",
]
