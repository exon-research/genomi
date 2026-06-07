"""Operation registry package.

This package exposes the operation catalog, handler table, coercion helpers,
and capability module handles used by operation dispatch and tests.
"""

from __future__ import annotations

# --- Module-level names included in the current registry surface. ---
import json
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...active_genome_index.active_genome_index import (
    ActiveGenomeIndexNeedsReparse as _ActiveGenomeIndexNeedsReparse,
)
from ...active_genome_index.active_genome_index import (
    ActiveGenomeIndexSchemaTooNew as _ActiveGenomeIndexSchemaTooNew,
)

# --- Capability module handles used by dispatch tests and handler patches. ---
from ..catalog import TOOL_CATALOG_FILENAME, load_tool_catalog
from ...active_genome_index import source_intake
from ...active_genome_index.active_genome_index import default_agi_path
from ...capabilities.analytical_grounding import analytical_grounding
from ...capabilities.ancestry import overlap as ancestry_overlap
from ...capabilities.ancestry import pca as ancestry_pca
from ...capabilities.ancestry import reference_panels as ancestry_reference_panels
from ...capabilities.ancestry import source_context as ancestry_source_context
from ...capabilities.clinvar import static_annotation
from ...capabilities.decode import dashboard as decode_dashboard
from ...capabilities.functional_genomics import evidence_acquisition, geo, screen
from ...capabilities.gwas import gwas
from ...capabilities.journal import journal
from ...capabilities.nutrigenomics import operations as nutrigenomics_operations
from ...capabilities.pharmacogenomics import (
    clinpgx,
    fda_pgx,
    pgx_outside_calls,
    pgx_requirements,
    pgxdb,
    pharmcat,
)
from ...capabilities.pharmacogenomics import review as pgx
from ...capabilities.phenotype import gene_identification, phenotype, targets
from ...capabilities.prs import pgs_catalog as prs_pgs_catalog
from ...capabilities.prs import scorer as prs_scorer
from ...capabilities.prs import scoring_files as prs_scoring_files
from ...capabilities.prs import source_context as prs_source_context
from ...capabilities.research import intent_research
from ...capabilities.sequence import sequence
from ...capabilities.variant import variant_lookup
from ...evidence import init_evidence_db, research_scope_choices
from ...runtime import context as runtime_context
from ...runtime import host_response, resources
from ...runtime.libraries.manager import (
    inventory as library_inventory,
    missing_request as library_install_request,
    status as library_status,
)
from ...runtime.paths import shared_evidence_db_path
from ...retrieval import hybrid as retrieval_hybrid
from ...retrieval import index as retrieval_index
from ...retrieval import semantic as retrieval_semantic

# --- Core surface ---
from .errors import JsonObject, OperationError, OperationHandler
from .catalog_meta import (
    BASE_CAPABILITIES_IN_DEFAULT_TOOLS_LIST,
    CAPABILITY_ENTRY_OPERATION_NAMES,
    CAPABILITY_ENTRY_OPERATIONS,
    CAPABILITY_METADATA,
    CAPABILITY_ORDER,
    JOURNAL_ENTRY_TYPES,
    LOCAL_SOURCE_DEPENDENCIES,
    NAMESPACE_ORDER,
    PROJECT_ROOT,
    TOOL_CATALOG,
    TOOL_CATALOG_OPERATIONS,
    TOP_LEVEL_FUNCTION_SCHEMA_KEYWORDS,
    WRITE_OPERATIONS,
    _catalog_input_schema,
    _catalog_tuple,
    _data_access,
    _expand_schema_property_groups,
    _operation_catalog_entry,
    _operation_dependency_contract,
    _operation_namespace,
    _operation_scope,
    _resolve_catalog_ref,
    _resolve_schema_refs,
    _schema_constraint_note,
    _without_top_level_schema_combinators,
)
from .model import (
    Operation,
    _DISPLAY_TITLE_OVERRIDES,
    _display_title,
    _operation_capability,
    _operation_parameter_defaults,
    _tool_role,
)
from .coerce import (
    _SKIP_DEFAULT,
    _UNRESOLVED_DEFAULT,
    _bool,
    _float,
    _hidden_intake_path_strings,
    _hide_intake_source_after_digitization,
    _int,
    _is_hidden_intake_path,
    _list_dict,
    _list_str,
    _optional_float,
    _optional_int,
    _optional_path,
    _optional_str,
    _path,
    _redact_intake_paths,
    _remember_source_result,
    _require_context_value,
    _resolved_default_value,
    _str,
    _target_kwargs,
    _with_context,
    _with_defaults_applied,
    defaults_applied_for_call,
)
from .handlers_agi_lifecycle import (
    _genomi_approve_agi_access,
    _genomi_assign_user_genome,
    _genomi_clear_default_user,
    _genomi_clear_selection,
    _genomi_describe_context,
    _genomi_rename_user,
    _genomi_revoke_agi_access,
    _genomi_select_user,
    _genomi_set_default_user,
)
from .handlers_admin import (
    _genomi_install,
    _genomi_invoke,
    _genomi_parse_source,
    _genomi_search_indexes,
    _genomi_set_response_profile,
    _metadata_retrieval_queries,
    _refresh_active_metadata_index,
    _refresh_public_retrieval_indexes,
    _resources_libraries,
    _resources_list,
    _runtime_check_background_job,
)
from .handlers_vcf_variant import (
    _agi_callability,
    _agi_genotype_support,
    _agi_qc,
    _agi_summary,
    _variant_lookup,
)
from .handlers_clinvar import (
    _clinvar_match,
    _clinvar_scan,
    _materialize_clinvar_matches_for_scan,
)
from .handlers_ancestry_prs import (
    _ancestry_build_source_context,
    _ancestry_check_sample_overlap,
    _ancestry_estimate_population_context,
    _ancestry_list_reference_panels,
    _ancestry_missing_library,
    _ancestry_project_pca,
    _nutrigenomics_build_source_context,
    _nutrigenomics_list_domains,
    _nutrigenomics_retrieve_domain_markers,
    _nutrigenomics_retrieve_variant_records,
    _prs_build_source_context,
    _prs_calculate_score,
    _prs_check_score_overlap,
    _prs_fetch_score_metadata,
    _prs_import_scoring_file,
    _prs_list_imported_scores,
    _prs_search_scores,
)
from .handlers_evidence_phenotype import (
    _cell_type_retrieve_canonical_markers,
    _disease_compare_phenotype_evidence,
    _disease_retrieve_clinical_drug_targets,
    _drug_compare_target_evidence,
    _evidence_gather_allele,
    _evidence_gather_gene,
    _evidence_packet,
    _evidence_query_research,
    _evidence_record_research,
    _evidence_search_research,
    _first_semantic_entity_text,
    _gene_retrieve_primary_disease_associations,
    _gwas_compare_trait_gene_evidence,
    _pathway_retrieve_member_genes,
    _phenotype_compare_gene_hpo_evidence,
    _phenotype_normalize,
    _population_fetch,
    _region_retrieve_feature_annotation,
    _result_has_source_records,
    _risk_investigate,
    _semantic_entity_texts,
    _trait_retrieve_gene_records,
    _with_simple_semantic_lookup_usage,
)
from .handlers_sequence import (
    _sequence_analyze,
    _sequence_check_primers,
    _sequence_find_orfs,
    _sequence_kozak_context,
    _sequence_match_reference_records,
    _sequence_restriction_sites,
    _sequence_translate,
)
from .handlers_pgx import (
    _clinpgx_lookup,
    _fda_pgx_lookup,
    _pgx_gene_requirements,
    _pgx_lookup,
    _pgx_medication_review,
    _pgx_outside_call_prepare,
    _pgx_outside_call_validate,
    _pgx_pharmcat,
    _pgx_pharmcat_import,
    _pgx_pharmcat_preflight,
    _pgx_pharmcat_status,
)
from .handlers_screen_journal import (
    _decode_build_dashboard_evidence,
    _decode_render_dashboard,
    _journal_append_entry,
    _journal_error,
    _journal_export_memory_artifact,
    _journal_search_entries,
    _journal_summarize_notebook,
    _screen_answer_gene,
    _screen_import_table_evidence_records,
    _screen_query_geo,
    _screen_retrieve_experiment_records,
)
from .table import (
    EVIDENCE_PRODUCING_OPERATIONS,
    OPERATIONS,
    _OPERATION_BY_NAME,
    _ensure_envelope,
    _optional_capability,
    _optional_namespace,
    _result_needs_guidance,
    _select_operations,
    all_operations,
    call_operation,
    get_operation,
    list_operations,
    load_params,
    operation_discovery_payload,
)
