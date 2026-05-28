"""GWAS Catalog comparison capability.

This package was split from a single ``gwas.py`` module. The public surface
(both the two entry points and every previously module-level helper/constant)
is re-exported here so existing import paths and attribute accesses keep
working unchanged.
"""

from __future__ import annotations

from .compare import (
    _wrong_gwas_gene_evidence_regime,
    compare_gwas_gene_evidence,
    compare_gwas_variant_evidence,
)
from .constants import (
    GWAS_CATALOG_API_URL,
    GWAS_CATALOG_PROJECTION,
    GWAS_CATALOG_SOURCE_URL,
    GWAS_CATALOG_V2_API_URL,
    GWAS_GENE_FIELD_EVIDENCE_INTENT,
    GWAS_MAX_ASSOCIATION_LIMIT,
    GWAS_MAX_EMITTED_ASSOCIATIONS,
    _CAUSAL_GENE_REQUEST_TERMS,
    _EXPLICIT_GWAS_GENE_FIELD_TERMS,
    _LOCUS_GENE_REQUEST_TERMS,
    _LOW_INFORMATION_TRAIT_TOKENS,
    _TOKEN_RE,
    _TRAIT_TOKEN_ALIASES,
)
from .parsing import (
    _association_record,
    _causal_gene_task_text,
    _dedupe_gene_records,
    _explicit_gwas_gene_field_task_text,
    _fetch_gwas_catalog_records,
    _fetch_gwas_efo_traits,
    _fetch_json,
    _finding_text,
    _gene_association_record,
    _gene_finding_text,
    _gene_mapped_genes,
    _gene_record_genes,
    _gene_record_study,
    _gene_record_traits,
    _gene_reported_genes,
    _generic_association_records,
    _generic_efo_trait_records,
)
from .phenotype_match import (
    _association_traits,
    _best_phenotype_match,
    _gwas_semantic_usage,
    _phenotype_match,
    _semantic_trait_queries,
)
from .ranking import (
    _candidate_evidence_summary,
    _candidate_matrix,
    _candidate_row,
    _empty_source_gene_match,
    _gene_candidate_matrix,
    _gene_candidate_row,
    _gene_evidence_summary,
    _gene_lane_weight,
    _gene_selection_warnings,
    _gene_why_not_selected,
    _lane_weight,
    _matching_gene_names,
    _minimum_support_level,
    _pvalue_support_level,
    _selection_warnings,
    _source_gene_match,
    _variant_support_axes,
    _why_not_selected,
)
from .text_utils import (
    _as_list,
    _best_pvalue,
    _clean_text,
    _dedupe_text,
    _embedded_list,
    _expanded_trait_token,
    _link_href,
    _locations,
    _mapped_genes,
    _meaningful_tokens,
    _normalize_gene,
    _normalize_genes,
    _normalize_rsids,
    _pvalue_from_parts,
    _pvalue_sort_value,
    _record_research_payload,
    _reported_genes,
    _risk_alleles,
    _tokens,
)

__all__ = [
    "GWAS_CATALOG_API_URL",
    "GWAS_CATALOG_PROJECTION",
    "GWAS_CATALOG_SOURCE_URL",
    "GWAS_CATALOG_V2_API_URL",
    "GWAS_GENE_FIELD_EVIDENCE_INTENT",
    "GWAS_MAX_ASSOCIATION_LIMIT",
    "GWAS_MAX_EMITTED_ASSOCIATIONS",
    "compare_gwas_gene_evidence",
    "compare_gwas_variant_evidence",
]
