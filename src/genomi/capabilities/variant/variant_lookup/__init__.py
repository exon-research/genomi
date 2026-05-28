"""Variant lookup facade package.

Splits the former single-module implementation into topical submodules while
preserving the complete public surface and import paths. Importers continue to
use ``from ..variant import variant_lookup`` and ``variant_lookup.lookup_variant``.
"""

from __future__ import annotations

from typing import Any

from .context import (
    _build_variant_envelope,
    _has_any_context_evidence,
    _public_context,
    _sample_context,
    _support_context,
    _target_inventory,
    _unanswered_component,
    _unanswered_components,
)
from .core import lookup_variant
from .parsing import (
    EXACT_ARROW_RE,
    EXACT_COLON_RE,
    LOCUS_RE,
    REGION_RE,
    RSID_RE,
    _allele_target,
    _chrom_aliases,
    _clean_allele,
    _clean_chrom,
    _dedupe_records,
    _dedupe_scalar,
    _dedupe_targets,
    _effective_genome_build,
    _inferred_allele_targets,
    _int_or_none,
    _locus_target,
    _normalize_rsid,
    _overlaps_exact_or_region_match,
    _region_target,
    _resolve_targets,
    _target_key,
)
from .queries import (
    _connect_readonly,
    _index_record,
    _query_active_genome_index,
    _query_clinvar_allele,
    _query_clinvar_locus,
    _query_clinvar_region,
    _query_clinvar_rsid,
    _query_genotype_support,
    _query_population_allele,
    _query_public_rows,
    _query_research_by_target_id,
    _query_research_topic,
    _query_research_variant,
    _record_matches,
    _record_select_sql,
    _table_exists,
)
from .runs import (
    _append_db,
    _append_run,
    _public_db_descriptor,
    _run_summary,
    _selected_evidence_dbs,
    _selected_runs,
)

JsonObject = dict[str, Any]

__all__ = [
    "JsonObject",
    "lookup_variant",
    "RSID_RE",
    "EXACT_COLON_RE",
    "EXACT_ARROW_RE",
    "REGION_RE",
    "LOCUS_RE",
    "_allele_target",
    "_append_db",
    "_append_run",
    "_build_variant_envelope",
    "_chrom_aliases",
    "_clean_allele",
    "_clean_chrom",
    "_connect_readonly",
    "_dedupe_records",
    "_dedupe_scalar",
    "_dedupe_targets",
    "_effective_genome_build",
    "_has_any_context_evidence",
    "_index_record",
    "_inferred_allele_targets",
    "_int_or_none",
    "_locus_target",
    "_normalize_rsid",
    "_overlaps_exact_or_region_match",
    "_public_context",
    "_public_db_descriptor",
    "_query_active_genome_index",
    "_query_clinvar_allele",
    "_query_clinvar_locus",
    "_query_clinvar_region",
    "_query_clinvar_rsid",
    "_query_genotype_support",
    "_query_population_allele",
    "_query_public_rows",
    "_query_research_by_target_id",
    "_query_research_topic",
    "_query_research_variant",
    "_record_matches",
    "_record_select_sql",
    "_region_target",
    "_resolve_targets",
    "_run_summary",
    "_sample_context",
    "_selected_evidence_dbs",
    "_selected_runs",
    "_support_context",
    "_table_exists",
    "_target_inventory",
    "_target_key",
    "_unanswered_component",
    "_unanswered_components",
]
