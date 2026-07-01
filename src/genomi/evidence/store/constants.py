from __future__ import annotations

from pathlib import Path

from ...runtime.libraries import manager as library_manager
from ...runtime.paths import run_evidence_db_path
from ...runtime.sqlite_support import (
    LONG_WRITE_BUSY_TIMEOUT_SECONDS,
)

CANDIDATE_RULE_SET_VERSION = "clinvar-candidate-inventory-v12"
CLINVAR_ANNOTATION_INDEX_RULE_SET_VERSION = "clinvar-annotation-index-v1"
CLINVAR_RSID_INDEX_RULE_SET_VERSION = "clinvar-rsid-index-v1"
CLINVAR_RSID_ANNOTATION_RULE_SET_VERSION = "clinvar-rsid-annotation-v1"
STRICT_PATHOGENIC_CLINSIG = {"Pathogenic", "Likely_pathogenic", "Pathogenic/Likely_pathogenic"}
CONFLICTING_CLINSIG = "Conflicting_classifications_of_pathogenicity"
VUS_CLINSIG = "Uncertain_significance"
ASSOCIATION_CLINSIG = {"association", "risk_factor", "protective"}
DRUG_RESPONSE_CLINSIG = {"drug_response"}
BENIGN_CLINSIG = {"Benign", "Likely_benign", "Benign/Likely_benign"}
HIGH_REVIEW_STATUS = {
    "practice_guideline",
    "reviewed_by_expert_panel",
    "criteria_provided,_multiple_submitters,_no_conflicts",
}
LOW_REVIEW_STATUS = {
    "no_assertion_criteria_provided",
    "no_classification_for_the_single_variant",
    "criteria_provided,_single_submitter",
}
POPULATION_EVIDENCE_TAGS = {
    "population_evidence_present",
    "needs_public_population_evidence",
    "population_evidence_not_checked",
}
POPULATION_FREQUENCY_TAGS = {
    "population_frequency_common",
    "population_frequency_rare",
    "population_homozygotes_present",
    "population_frequency_context_needed",
}
POPULATION_TAGS = POPULATION_EVIDENCE_TAGS | POPULATION_FREQUENCY_TAGS
POPULATION_COMMON_AF_THRESHOLD = 0.01
POPULATION_RARE_AF_THRESHOLD = 0.001
CLINVAR_CANDIDATE_BUCKETS = [
    (
        "clinvar_p_lp_high_review",
        "ClinVar Pathogenic/Likely pathogenic with a higher review status.",
    ),
    (
        "clinvar_p_lp_low_or_missing_review",
        "ClinVar Pathogenic/Likely pathogenic with low or missing review status.",
    ),
    (
        "clinvar_p_lp_population_context_needed",
        "Disease-like ClinVar label with common public frequency or public homozygote context.",
    ),
    (
        "low_penetrance_or_carrier_context",
        "Pathogenic-style ClinVar label with low-penetrance or carrier-style context; save as clinical context.",
    ),
    (
        "heterozygous_p_lp_context_needed",
        "Heterozygous P/LP observation; carrier, dominant, penetrance, and phase questions depend on intent and external evidence.",
    ),
    (
        "clinvar_conflicting",
        "ClinVar conflicting classifications; keep assertions visible until gathered evidence resolves the context.",
    ),
    (
        "clinvar_vus",
        "ClinVar uncertain significance; use uncertain-context wording.",
    ),
    (
        "drug_response",
        "ClinVar drug-response label; pharmacogenomics needs a dedicated evidence workflow.",
    ),
    (
        "risk_factor_or_association",
        "ClinVar risk, association, or protective label; common variants may still be relevant for this intent.",
    ),
    (
        "needs_population_evidence",
        "No public population-frequency rows are present for this exact allele.",
    ),
    (
        "population_common_context",
        "Public population evidence has global allele frequency at or above the common threshold.",
    ),
    (
        "population_rare_context",
        "Public population evidence has low global allele frequency and no public homozygote rows.",
    ),
    (
        "quality_or_low_call_support_context",
        "Sample call has non-PASS filter, low depth, or low genotype quality.",
    ),
]
CLINVAR_CANDIDATE_BUCKET_DESCRIPTIONS = dict(CLINVAR_CANDIDATE_BUCKETS)
CANDIDATE_EVIDENCE_GROUPS = [
    (
        "clinvar_p_lp",
        "ClinVar clinical significance contains Pathogenic, Likely_pathogenic, or Pathogenic/Likely_pathogenic.",
    ),
    (
        "clinvar_conflicting",
        "ClinVar clinical significance contains Conflicting_classifications_of_pathogenicity.",
    ),
    (
        "clinvar_vus",
        "ClinVar clinical significance contains Uncertain_significance.",
    ),
    (
        "clinvar_risk_association_protective",
        "ClinVar clinical significance contains association, risk_factor, or protective.",
    ),
    (
        "clinvar_drug_response",
        "ClinVar clinical significance contains drug_response.",
    ),
    (
        "clinvar_benign",
        "ClinVar clinical significance contains Benign, Likely_benign, or Benign/Likely_benign.",
    ),
]
CANDIDATE_EVIDENCE_GROUP_DESCRIPTIONS = dict(CANDIDATE_EVIDENCE_GROUPS)
DEFAULT_CANDIDATE_EVIDENCE_GROUPS = [
    "clinvar_p_lp",
    "clinvar_conflicting",
    "clinvar_vus",
    "clinvar_risk_association_protective",
    "clinvar_drug_response",
    "clinvar_benign",
]
DEFAULT_POPULATION_LABEL = "global"
SQLITE_BUSY_TIMEOUT_SECONDS = LONG_WRITE_BUSY_TIMEOUT_SECONDS
GNOMAD_API_URL = library_manager.api_base("gnomad")
RESEARCH_FINDING_TEXT_MAX_CHARS = 1600
RESEARCH_TARGET_TYPES = {"condition", "drug", "gene", "topic", "variant"}
RESEARCH_SCOPES = {"shared", "private"}
GNOMAD_VARIANT_QUERY = """
query($variantId:String!,$dataset:DatasetId!) {
  variant(variantId:$variantId,dataset:$dataset) {
    variant_id
    rsids
    chrom
    pos
    ref
    alt
    exome {
      ac
      an
      af
      homozygote_count
      populations {
        id
        ac
        an
        homozygote_count
      }
    }
    genome {
      ac
      an
      af
      homozygote_count
      populations {
        id
        ac
        an
        homozygote_count
      }
    }
  }
}
"""


def candidate_evidence_group_choices() -> list[str]:
    return [group for group, _description in CANDIDATE_EVIDENCE_GROUPS]


def research_target_type_choices() -> list[str]:
    return sorted(RESEARCH_TARGET_TYPES)


def research_scope_choices() -> list[str]:
    return sorted(RESEARCH_SCOPES)


def default_evidence_path(vcf_path: str | Path, root: str | Path | None = None) -> Path:
    return run_evidence_db_path(vcf_path, root=root)


SHARED_EVIDENCE_ALIAS = "shared_static"
SHARED_EVIDENCE_TABLES = (
    "clinvar_variants",
    "clinvar_variant_genes",
    "clinvar_variant_rsids",
    "population_frequencies",
)
RESEARCH_FINDING_COLUMNS = (
    "finding_id",
    "target_type",
    "target_id",
    "chrom",
    "pos",
    "ref",
    "alt",
    "gene",
    "drug",
    "condition",
    "topic",
    "genome_build",
    "research_scope",
    "source_title",
    "source_url",
    "source_type",
    "source_published_at",
    "source_accessed_at",
    "searched_query",
    "finding_text",
    "finding_summary",
    "finding_type",
    "captured_by",
    "captured_at",
    "raw_json",
)
