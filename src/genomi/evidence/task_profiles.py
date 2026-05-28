from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .candidate_evidence import (
    AGENT_REASONING_ONLY,
    DIRECT_SOURCE_MATCH,
    EXACT_TRAIT_MATCH,
    LITERATURE_PLAUSIBILITY,
    NEARBY_TRAIT_MATCH,
    NEGATIVE_OR_CONFLICTING_EVIDENCE,
    ONTOLOGY_SYNONYM_MATCH,
    PATHWAY_PLAUSIBILITY,
    SAME_GENE_OR_LOCUS,
)


@dataclass(frozen=True)
class TaskProfile:
    profile_id: str
    candidate_type: str
    preferred_evidence_lanes: tuple[str, ...]
    ranking_weights: dict[str, float]
    answer_format: str
    support_level_cap_without_direct_source: str
    abstain_when_no_supported_candidate: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "candidate_type": self.candidate_type,
            "preferred_evidence_lanes": list(self.preferred_evidence_lanes),
            "ranking_weights": self.ranking_weights,
            "answer_format": self.answer_format,
            "support_level_cap_without_direct_source": self.support_level_cap_without_direct_source,
            "abstain_when_no_supported_candidate": self.abstain_when_no_supported_candidate,
        }


GWAS_VARIANT_PRIORITIZATION = TaskProfile(
    profile_id="gwas_variant_prioritization",
    candidate_type="rsid",
    preferred_evidence_lanes=(
        DIRECT_SOURCE_MATCH,
        EXACT_TRAIT_MATCH,
        ONTOLOGY_SYNONYM_MATCH,
        NEARBY_TRAIT_MATCH,
    ),
    ranking_weights={
        DIRECT_SOURCE_MATCH: 1.0,
        EXACT_TRAIT_MATCH: 0.95,
        ONTOLOGY_SYNONYM_MATCH: 0.9,
        NEARBY_TRAIT_MATCH: 0.45,
    },
    answer_format="rsid_only",
    support_level_cap_without_direct_source="medium",
)

GWAS_GENE_PRIORITIZATION = TaskProfile(
    profile_id="gwas_gene_prioritization",
    candidate_type="gene_symbol",
    preferred_evidence_lanes=(
        DIRECT_SOURCE_MATCH,
        EXACT_TRAIT_MATCH,
        SAME_GENE_OR_LOCUS,
        NEARBY_TRAIT_MATCH,
        LITERATURE_PLAUSIBILITY,
        AGENT_REASONING_ONLY,
    ),
    ranking_weights={
        DIRECT_SOURCE_MATCH: 1.0,
        EXACT_TRAIT_MATCH: 0.85,
        SAME_GENE_OR_LOCUS: 0.25,
        NEARBY_TRAIT_MATCH: 0.45,
        LITERATURE_PLAUSIBILITY: 0.2,
        AGENT_REASONING_ONLY: 0.0,
    },
    answer_format="gene_symbol_only",
    support_level_cap_without_direct_source="medium",
)

SCREEN_GENE_RETRIEVAL = TaskProfile(
    profile_id="functional_genomics_perturbation_evidence",
    candidate_type="gene_symbol",
    preferred_evidence_lanes=(
        DIRECT_SOURCE_MATCH,
        EXACT_TRAIT_MATCH,
        ONTOLOGY_SYNONYM_MATCH,
        NEARBY_TRAIT_MATCH,
        LITERATURE_PLAUSIBILITY,
        PATHWAY_PLAUSIBILITY,
    ),
    ranking_weights={
        DIRECT_SOURCE_MATCH: 1.0,
        EXACT_TRAIT_MATCH: 0.85,
        ONTOLOGY_SYNONYM_MATCH: 0.75,
        NEARBY_TRAIT_MATCH: 0.4,
        LITERATURE_PLAUSIBILITY: 0.25,
        PATHWAY_PLAUSIBILITY: 0.15,
    },
    answer_format="gene_symbol_only",
    support_level_cap_without_direct_source="medium",
)

CLINVAR_CANDIDATE_SCAN = TaskProfile(
    profile_id="clinvar_candidate_scan",
    candidate_type="variant",
    preferred_evidence_lanes=(
        DIRECT_SOURCE_MATCH,
        NEARBY_TRAIT_MATCH,
        NEGATIVE_OR_CONFLICTING_EVIDENCE,
    ),
    ranking_weights={
        DIRECT_SOURCE_MATCH: 1.0,
        NEARBY_TRAIT_MATCH: 0.45,
        NEGATIVE_OR_CONFLICTING_EVIDENCE: 0.35,
    },
    answer_format="variant_candidate_review",
    support_level_cap_without_direct_source="medium",
)

PANEL_MARKER_SCAN = TaskProfile(
    profile_id="panel_marker_scan",
    candidate_type="panel_marker_or_aggregate",
    preferred_evidence_lanes=(
        DIRECT_SOURCE_MATCH,
        EXACT_TRAIT_MATCH,
        SAME_GENE_OR_LOCUS,
        NEARBY_TRAIT_MATCH,
    ),
    ranking_weights={
        DIRECT_SOURCE_MATCH: 0.9,
        EXACT_TRAIT_MATCH: 0.75,
        SAME_GENE_OR_LOCUS: 0.55,
        NEARBY_TRAIT_MATCH: 0.35,
    },
    answer_format="multiple_context_candidates",
    support_level_cap_without_direct_source="medium",
    abstain_when_no_supported_candidate=False,
)

PGX_MEDICATION_REVIEW = TaskProfile(
    profile_id="pgx_medication_review",
    candidate_type="pgx_medication_target",
    preferred_evidence_lanes=(
        DIRECT_SOURCE_MATCH,
        EXACT_TRAIT_MATCH,
        SAME_GENE_OR_LOCUS,
        NEARBY_TRAIT_MATCH,
    ),
    ranking_weights={
        DIRECT_SOURCE_MATCH: 1.0,
        EXACT_TRAIT_MATCH: 0.8,
        SAME_GENE_OR_LOCUS: 0.6,
        NEARBY_TRAIT_MATCH: 0.35,
    },
    answer_format="pgx_evidence_review",
    support_level_cap_without_direct_source="medium",
    abstain_when_no_supported_candidate=False,
)

REPORT_CANDIDATE_REVIEW = TaskProfile(
    profile_id="report_candidate_review",
    candidate_type="report_claim_candidate",
    preferred_evidence_lanes=(
        DIRECT_SOURCE_MATCH,
        EXACT_TRAIT_MATCH,
        SAME_GENE_OR_LOCUS,
        NEARBY_TRAIT_MATCH,
        LITERATURE_PLAUSIBILITY,
    ),
    ranking_weights={
        DIRECT_SOURCE_MATCH: 0.9,
        EXACT_TRAIT_MATCH: 0.75,
        SAME_GENE_OR_LOCUS: 0.55,
        NEARBY_TRAIT_MATCH: 0.35,
        LITERATURE_PLAUSIBILITY: 0.2,
    },
    answer_format="report_claim_review",
    support_level_cap_without_direct_source="medium",
    abstain_when_no_supported_candidate=False,
)

RARE_DISEASE_CANCER_RISK_INVESTIGATION = TaskProfile(
    profile_id="rare_disease_cancer_risk_investigation",
    candidate_type="gene_condition_or_variant",
    preferred_evidence_lanes=(
        DIRECT_SOURCE_MATCH,
        EXACT_TRAIT_MATCH,
        SAME_GENE_OR_LOCUS,
        NEARBY_TRAIT_MATCH,
        LITERATURE_PLAUSIBILITY,
        NEGATIVE_OR_CONFLICTING_EVIDENCE,
        AGENT_REASONING_ONLY,
    ),
    ranking_weights={
        DIRECT_SOURCE_MATCH: 1.0,
        EXACT_TRAIT_MATCH: 0.8,
        SAME_GENE_OR_LOCUS: 0.6,
        NEARBY_TRAIT_MATCH: 0.4,
        LITERATURE_PLAUSIBILITY: 0.25,
        NEGATIVE_OR_CONFLICTING_EVIDENCE: 0.2,
        AGENT_REASONING_ONLY: 0.0,
    },
    answer_format="risk_investigation_review",
    support_level_cap_without_direct_source="medium",
    abstain_when_no_supported_candidate=False,
)

PHENOTYPE_DISEASE_PRIORITIZATION = TaskProfile(
    profile_id="phenotype_disease_prioritization",
    candidate_type="disease_or_condition",
    preferred_evidence_lanes=(
        DIRECT_SOURCE_MATCH,
        EXACT_TRAIT_MATCH,
        ONTOLOGY_SYNONYM_MATCH,
        NEARBY_TRAIT_MATCH,
        LITERATURE_PLAUSIBILITY,
        NEGATIVE_OR_CONFLICTING_EVIDENCE,
        AGENT_REASONING_ONLY,
    ),
    ranking_weights={
        DIRECT_SOURCE_MATCH: 1.0,
        EXACT_TRAIT_MATCH: 0.85,
        ONTOLOGY_SYNONYM_MATCH: 0.75,
        NEARBY_TRAIT_MATCH: 0.45,
        LITERATURE_PLAUSIBILITY: 0.25,
        NEGATIVE_OR_CONFLICTING_EVIDENCE: 0.2,
        AGENT_REASONING_ONLY: 0.0,
    },
    answer_format="disease_review",
    support_level_cap_without_direct_source="medium",
)

PHENOTYPE_GENE_PRIORITIZATION = TaskProfile(
    profile_id="phenotype_gene_prioritization",
    candidate_type="gene_symbol",
    preferred_evidence_lanes=(
        DIRECT_SOURCE_MATCH,
        EXACT_TRAIT_MATCH,
        SAME_GENE_OR_LOCUS,
        ONTOLOGY_SYNONYM_MATCH,
        NEARBY_TRAIT_MATCH,
        LITERATURE_PLAUSIBILITY,
        NEGATIVE_OR_CONFLICTING_EVIDENCE,
        AGENT_REASONING_ONLY,
    ),
    ranking_weights={
        DIRECT_SOURCE_MATCH: 1.0,
        EXACT_TRAIT_MATCH: 0.85,
        SAME_GENE_OR_LOCUS: 0.65,
        ONTOLOGY_SYNONYM_MATCH: 0.55,
        NEARBY_TRAIT_MATCH: 0.4,
        LITERATURE_PLAUSIBILITY: 0.25,
        NEGATIVE_OR_CONFLICTING_EVIDENCE: 0.2,
        AGENT_REASONING_ONLY: 0.0,
    },
    answer_format="gene_review",
    support_level_cap_without_direct_source="medium",
)

DRUG_TARGET_GENE_PRIORITIZATION = TaskProfile(
    profile_id="drug_target_gene_prioritization",
    candidate_type="gene_symbol",
    preferred_evidence_lanes=(
        DIRECT_SOURCE_MATCH,
        EXACT_TRAIT_MATCH,
        SAME_GENE_OR_LOCUS,
        NEARBY_TRAIT_MATCH,
        LITERATURE_PLAUSIBILITY,
        NEGATIVE_OR_CONFLICTING_EVIDENCE,
        AGENT_REASONING_ONLY,
    ),
    ranking_weights={
        DIRECT_SOURCE_MATCH: 1.0,
        EXACT_TRAIT_MATCH: 0.85,
        SAME_GENE_OR_LOCUS: 0.65,
        NEARBY_TRAIT_MATCH: 0.35,
        LITERATURE_PLAUSIBILITY: 0.2,
        NEGATIVE_OR_CONFLICTING_EVIDENCE: 0.2,
        AGENT_REASONING_ONLY: 0.0,
    },
    answer_format="gene_symbol_only_when_direct_target_supported",
    support_level_cap_without_direct_source="medium",
)

GENE_LIST_IDENTIFICATION = TaskProfile(
    profile_id="gene_list_identification",
    candidate_type="gene_symbol",
    preferred_evidence_lanes=(
        DIRECT_SOURCE_MATCH,
        EXACT_TRAIT_MATCH,
        ONTOLOGY_SYNONYM_MATCH,
        SAME_GENE_OR_LOCUS,
        NEARBY_TRAIT_MATCH,
        LITERATURE_PLAUSIBILITY,
        AGENT_REASONING_ONLY,
    ),
    ranking_weights={
        DIRECT_SOURCE_MATCH: 1.0,
        EXACT_TRAIT_MATCH: 0.85,
        ONTOLOGY_SYNONYM_MATCH: 0.75,
        SAME_GENE_OR_LOCUS: 0.6,
        NEARBY_TRAIT_MATCH: 0.4,
        LITERATURE_PLAUSIBILITY: 0.2,
        AGENT_REASONING_ONLY: 0.0,
    },
    answer_format="gene_symbol_only_when_direct_source_supported",
    support_level_cap_without_direct_source="medium",
)

TASK_PROFILES = {
    GWAS_VARIANT_PRIORITIZATION.profile_id: GWAS_VARIANT_PRIORITIZATION,
    GWAS_GENE_PRIORITIZATION.profile_id: GWAS_GENE_PRIORITIZATION,
    SCREEN_GENE_RETRIEVAL.profile_id: SCREEN_GENE_RETRIEVAL,
    CLINVAR_CANDIDATE_SCAN.profile_id: CLINVAR_CANDIDATE_SCAN,
    PANEL_MARKER_SCAN.profile_id: PANEL_MARKER_SCAN,
    PGX_MEDICATION_REVIEW.profile_id: PGX_MEDICATION_REVIEW,
    REPORT_CANDIDATE_REVIEW.profile_id: REPORT_CANDIDATE_REVIEW,
    RARE_DISEASE_CANCER_RISK_INVESTIGATION.profile_id: RARE_DISEASE_CANCER_RISK_INVESTIGATION,
    PHENOTYPE_DISEASE_PRIORITIZATION.profile_id: PHENOTYPE_DISEASE_PRIORITIZATION,
    PHENOTYPE_GENE_PRIORITIZATION.profile_id: PHENOTYPE_GENE_PRIORITIZATION,
    DRUG_TARGET_GENE_PRIORITIZATION.profile_id: DRUG_TARGET_GENE_PRIORITIZATION,
    GENE_LIST_IDENTIFICATION.profile_id: GENE_LIST_IDENTIFICATION,
}


def get_task_profile(profile_id: str) -> TaskProfile:
    try:
        return TASK_PROFILES[profile_id]
    except KeyError as exc:
        raise ValueError(f"unknown task profile {profile_id!r}") from exc
