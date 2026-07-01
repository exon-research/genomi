"""Pharmacogenomics medication-review facade package."""

from __future__ import annotations

from ....evidence import envelope as _env  # noqa: F401
from ....evidence.candidate_evidence import (  # noqa: F401
    DIRECT_SOURCE_MATCH,
    EXACT_TRAIT_MATCH,
    NEARBY_TRAIT_MATCH,
    SAME_GENE_OR_LOCUS,
    answerability_for_lane,
    apply_evidence_view,
    evidence_support_level_for_score,
    empty_lanes,
    evidence_view,
    lane,
)
from ....evidence.task_profiles import PGX_MEDICATION_REVIEW  # noqa: F401
from ....retrieval import semantic as retrieval_semantic  # noqa: F401
from ...research import intent_research  # noqa: F401

from ._common import (  # noqa: F401
    JsonObject,
    _as_dicts,
    _clean,
    _clinpgx_source_title,
    _compact_clinpgx_record,
    _compact_pgxdb_record,
    _compact_public_source_result,
    _compact_references,
    _compact_selected_fields,
    _compact_text,
    _dedupe,
    _dedupe_params,
    _first_reference_name,
    _first_reference_symbol,
    _literature_citations,
    _looks_like_free_text_target,
    _normalize_gene,
    _normalize_rsid,
    _pgx_semantic_usage,
    _pgxdb_record_source_url,
    _pmid_citations,
    _pmid_values,
    _selected_semantic_target,
    _single_value,
    _stable_evidence_source_identity,
    _traceability_status,
)
from .record_research import (  # noqa: F401
    _is_stored_sample_pgx_record,
    _is_stored_source_pgx_record,
    _record_research_payload_role,
    _record_research_payload_role_counts,
    _record_research_payload_summaries,
    _source_record_research_payloads,
    _stored_sample_evidence_count,
    _stored_source_evidence_count,
)
from .stored_research import (  # noqa: F401
    _compact_stored_research_record,
    _dedupe_stored_research,
    _stored_research_context,
    _stored_research_stores,
    _stored_research_targets,
)
from .sample_evidence import (  # noqa: F401
    _answer_support,
    _answer_technical_status,
    _canonical_genotype_token,
    _compare_reported_alleles,
    _follow_up_rsids,
    _follow_up_star_genes,
    _genotype_support_loci,
    _genotype_support_params,
    _has_active_genome_index_context,
    _has_supported_star_marker_coverage,
    _is_observed_star_marker,
    _matched_pgxdb_associations,
    _observed_alleles,
    _observed_sample_genotype,
    _readiness,
    _reported_genotype_tokens,
    _sample_matches_by_rsid,
    _sequencing_sample_match_count,
    _sequencing_star_marker_count,
    _source_recommendation_summaries,
    _star_diplotype_summaries,
    _star_marker_genotype_support_loci,
    _star_marker_match_count,
    _stored_sample_pgx_summaries,
    _target_inventory,
    _technical_support_count,
    _known_sample_pgx_summaries,
)
from .evidence_matrix import (  # noqa: F401
    _clinpgx_evidence_items,
    _dedupe_evidence_items,
    _evidence_item_id,
    _evidence_item_role_counts,
    _evidence_matrix,
    _evidence_matrix_traceability,
    _fda_evidence_items,
    _pgxdb_evidence_items,
    _sample_lookup_evidence_items,
    _star_allele_evidence_items,
    _stored_research_evidence_items,
    _stored_source_citations,
    _known_sample_pgx_evidence_items,
    _with_evidence_item_ids,
)
from .source_state import (  # noqa: F401
    _component_has_evidence,
    _evidence_components,
    _evidence_state,
    _medication_review_status,
    _source_availability,
    _source_availability_item,
    _unanswered_answer_components,
)
from .interaction import (  # noqa: F401
    _clinical_context,
    _known_sample_fact_count,
    _known_sample_pgx_evidence,
    capability_inventory,
    review_medication_interaction,
)
from .medication_matrix import (  # noqa: F401
    MEDICATION_REVIEW_MATRIX_POLICY_ID,
    build_medication_review_matrix,
    medication_review_evidence_view,
)
