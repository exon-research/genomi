"""Active Genome Indexing and library-scoped static evidence materialization.

This package preserves the public surface and import paths of the former
``static_annotation.py`` module. Submodules are organized by topic, while this
package re-exports the complete public API so that
``from genomi.capabilities.clinvar.static_annotation import <name>`` and
``static_annotation.<name>`` continue to resolve unchanged.
"""

from __future__ import annotations

# Patchable static dependencies are bound at the package namespace so tests that
# patch ``static_annotation.<name>`` affect the call sites that resolve them.
from ....active_genome_index.export import export_variants
from ....active_genome_index.normalize import normalize_vcf
from ....runtime.static_dependencies import ensure_clinvar_vcf, ensure_reference_fasta

from ._helpers import (
    LONG_RUNNING_STATIC_REASON,
    WORKFLOW_AREA_ID,
    WORKFLOW_AREA_NAME,
    _copy_shared_metadata,
    _copy_unique_rows,
    _ensure_clinvar_cache_imported,
    _ensure_clinvar_evidence,
    _evidence_from_matches,
    _has_clinvar_evidence,
    _link_run_db_to_shared_static,
    _linked_shared_static_db,
    _other_build,
    _record_run_metadata,
    _resolve_clinvar_cache_build,
    _reusable_static_db_with_clinvar,
    _shared_static_write_db,
    _unlink_sqlite_db,
    default_static_outputs,
    init_static_run,
    sync_static_evidence_to_shared,
    workflow_contract,
)
from .build import (
    build_static_annotation,
    fetch_static_population,
    match_static_clinvar,
    match_static_clinvar_from_active_genome_index,
    scan_static_candidates,
)
from .queries import (
    query_static_coverage,
    query_static_region,
    query_static_rsid,
    query_static_variant,
    run_static_callability,
    run_static_genotype_support,
    run_static_sample_qc,
    static_db_lookup,
    summarize_static_state,
)

__all__ = [
    "LONG_RUNNING_STATIC_REASON",
    "WORKFLOW_AREA_ID",
    "WORKFLOW_AREA_NAME",
    "build_static_annotation",
    "default_static_outputs",
    "ensure_clinvar_vcf",
    "ensure_reference_fasta",
    "export_variants",
    "fetch_static_population",
    "init_static_run",
    "match_static_clinvar",
    "match_static_clinvar_from_active_genome_index",
    "normalize_vcf",
    "query_static_coverage",
    "query_static_region",
    "query_static_rsid",
    "query_static_variant",
    "run_static_callability",
    "run_static_genotype_support",
    "run_static_sample_qc",
    "scan_static_candidates",
    "static_db_lookup",
    "summarize_static_state",
    "sync_static_evidence_to_shared",
    "workflow_contract",
]
