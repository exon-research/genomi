from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ...active_genome_index.active_genome_index import (
    ActiveGenomeIndexNeedsReparse as _ActiveGenomeIndexNeedsReparse,
)
from ...active_genome_index.active_genome_index import (
    ActiveGenomeIndexSchemaTooNew as _ActiveGenomeIndexSchemaTooNew,
)
from ...capabilities.research import intent_research
from .catalog_meta import (
    BASE_CAPABILITIES_IN_DEFAULT_TOOLS_LIST,
    CAPABILITY_METADATA,
    CAPABILITY_ORDER,
    NAMESPACE_ORDER,
    _operation_namespace,
)
from .coerce import _int, _list_str, _str, _with_defaults_applied
from .errors import JsonObject, OperationError
from .model import Operation, _operation_capability
from .handlers_admin import (
    _genomi_approve_agi_access,
    _genomi_assign_user_genome,
    _genomi_clear_default_user,
    _genomi_clear_selection,
    _genomi_describe_context,
    _genomi_install,
    _genomi_invoke,
    _genomi_list_users,
    _genomi_parse_source,
    _genomi_rename_user,
    _genomi_revoke_agi_access,
    _genomi_search_indexes,
    _genomi_select_user,
    _genomi_set_default_user,
    _genomi_set_response_profile,
    _resources_libraries,
    _resources_list,
    _runtime_check_background_job,
)
from .handlers_ancestry_prs import (
    _ancestry_build_source_context,
    _ancestry_check_sample_overlap,
    _ancestry_estimate_population_context,
    _ancestry_list_reference_panels,
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
from .handlers_clinvar import _clinvar_match, _clinvar_scan
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
    _gene_retrieve_primary_disease_associations,
    _gwas_compare_trait_gene_evidence,
    _pathway_retrieve_member_genes,
    _phenotype_compare_gene_hpo_evidence,
    _phenotype_normalize,
    _population_fetch,
    _region_retrieve_feature_annotation,
    _risk_investigate,
    _trait_retrieve_gene_records,
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
    _decode_render_dashboard,
    _journal_append_entry,
    _journal_export_memory_artifact,
    _journal_search_entries,
    _journal_summarize_notebook,
    _screen_answer_gene,
    _screen_import_table_evidence_records,
    _screen_query_geo,
    _screen_retrieve_experiment_records,
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
from .handlers_vcf_variant import (
    _variant_lookup,
    _vcf_callability,
    _vcf_genotype_support,
    _vcf_qc,
    _vcf_summary,
)


OPERATIONS: list[Operation] = [
    Operation('genomi.check_background_job', _runtime_check_background_job),
    Operation('genomi.install', _genomi_install),
    Operation('genomi.describe_context', _genomi_describe_context),
    Operation('genomi.invoke', _genomi_invoke),
    Operation('genomi.check_libraries', _resources_libraries),
    Operation('genomi.list_resources', _resources_list),
    Operation('genomi.search_indexes', _genomi_search_indexes),
    Operation('genomi.approve_agi_access', _genomi_approve_agi_access),
    Operation('genomi.revoke_agi_access', _genomi_revoke_agi_access),
    Operation('genomi.list_users', _genomi_list_users),
    Operation('genomi.select_user', _genomi_select_user),
    Operation('genomi.rename_user', _genomi_rename_user),
    Operation('genomi.assign_user_genome', _genomi_assign_user_genome),
    Operation('genomi.set_default_user', _genomi_set_default_user),
    Operation('genomi.set_response_profile', _genomi_set_response_profile),
    Operation('genomi.clear_default_user', _genomi_clear_default_user),
    Operation('genomi.clear_selection', _genomi_clear_selection),
    Operation('genomi.parse_source', _genomi_parse_source),
    Operation('active_genome_index.summarize', _vcf_summary),
    Operation('active_genome_index.classify_callset_qc', _vcf_qc),
    Operation('active_genome_index.classify_genotype_support', _vcf_genotype_support),
    Operation('active_genome_index.classify_region_callability', _vcf_callability),
    Operation('variant.resolve', _variant_lookup),
    Operation('clinvar.match_variants', _clinvar_match),
    Operation('clinvar.scan_candidates', _clinvar_scan),
    Operation('ancestry.list_reference_panels', _ancestry_list_reference_panels),
    Operation('ancestry.check_sample_overlap', _ancestry_check_sample_overlap),
    Operation('ancestry.project_pca', _ancestry_project_pca),
    Operation('ancestry.estimate_population_context', _ancestry_estimate_population_context),
    Operation('ancestry.build_source_context', _ancestry_build_source_context),
    Operation('prs.search_scores', _prs_search_scores),
    Operation('prs.fetch_score_metadata', _prs_fetch_score_metadata),
    Operation('prs.import_scoring_file', _prs_import_scoring_file),
    Operation('prs.list_imported_scores', _prs_list_imported_scores),
    Operation('prs.check_score_overlap', _prs_check_score_overlap),
    Operation('prs.calculate_score', _prs_calculate_score),
    Operation('prs.build_source_context', _prs_build_source_context),
    Operation('nutrigenomics.list_domains', _nutrigenomics_list_domains),
    Operation('nutrigenomics.build_source_context', _nutrigenomics_build_source_context),
    Operation('nutrigenomics.retrieve_domain_markers', _nutrigenomics_retrieve_domain_markers),
    Operation('nutrigenomics.retrieve_variant_records', _nutrigenomics_retrieve_variant_records),
    Operation('gnomad.fetch_population_frequency', _population_fetch),
    Operation('research.list_sources', lambda p: intent_research.source_catalog(target_type=p.get("target_type"), source_id=p.get("source_id"))),
    Operation('research.build_target_packet', _evidence_packet),
    Operation('variant.gather_allele_context', _evidence_gather_allele),
    Operation('variant.gather_gene_context', _evidence_gather_gene),
    Operation('phenotype.plan_risk_investigation', _risk_investigate),
    Operation('phenotype.normalize_terms', _phenotype_normalize),
    Operation('pathway.retrieve_members', _pathway_retrieve_member_genes),
    Operation('cell_type.retrieve_markers', _cell_type_retrieve_canonical_markers),
    Operation('region.retrieve_features', _region_retrieve_feature_annotation),
    Operation('phenotype.retrieve_gene_disease_associations', _gene_retrieve_primary_disease_associations),
    Operation('phenotype.compare_disease_evidence', _disease_compare_phenotype_evidence),
    Operation('phenotype.compare_gene_hpo_evidence', _phenotype_compare_gene_hpo_evidence),
    Operation('phenotype.compare_drug_target_evidence', _drug_compare_target_evidence),
    Operation('phenotype.retrieve_disease_drug_targets', _disease_retrieve_clinical_drug_targets),
    Operation('phenotype.retrieve_trait_gene_records', _trait_retrieve_gene_records),
    Operation('sequence.analyze', _sequence_analyze),
    Operation('sequence.match_reference', _sequence_match_reference_records),
    Operation('sequence.translate', _sequence_translate),
    Operation('sequence.find_orfs', _sequence_find_orfs),
    Operation('sequence.find_restriction_sites', _sequence_restriction_sites),
    Operation('sequence.classify_kozak', _sequence_kozak_context),
    Operation('sequence.check_primers', _sequence_check_primers),
    Operation('research.record', _evidence_record_research),
    Operation('research.query', _evidence_query_research),
    Operation('research.search', _evidence_search_research),
    Operation('journal.append_entry', _journal_append_entry),
    Operation('journal.search_entries', _journal_search_entries),
    Operation('journal.summarize', _journal_summarize_notebook),
    Operation('journal.export_memory', _journal_export_memory_artifact),
    Operation('pharmacogenomics.describe_gene_requirements', _pgx_gene_requirements),
    Operation('pharmacogenomics.review_medication', _pgx_medication_review),
    Operation('pharmacogenomics.preflight_pharmcat', _pgx_pharmcat_preflight),
    Operation('pharmacogenomics.validate_outside_call_tsv', _pgx_outside_call_validate),
    Operation('pharmacogenomics.import_pharmcat_artifacts', _pgx_pharmcat_import),
    Operation('pharmacogenomics.prepare_outside_call_tsv', _pgx_outside_call_prepare),
    Operation('pharmacogenomics.run_pharmcat', _pgx_pharmcat),
    Operation('pharmacogenomics.check_pharmcat', _pgx_pharmcat_status),
    Operation('pharmacogenomics.fetch_clinpgx', _clinpgx_lookup),
    Operation('pharmacogenomics.fetch_fda_labels', _fda_pgx_lookup),
    Operation('pharmacogenomics.fetch_pgxdb', _pgx_lookup),
    Operation('gwas.compare_variant_associations', lambda p: intent_research.compare_gwas_variant_context(
            _str(p, "phenotype"),
            _list_str(p, "variants"),
            association_limit=_int(p, "association_limit", 200),
            api_url=p.get("api_url"),
            semantic_context=p.get("semantic_context"),
        )),
    Operation('gwas.compare_gene_associations', _gwas_compare_trait_gene_evidence),
    Operation('functional_genomics.retrieve_perturbation_records', _screen_retrieve_experiment_records),
    Operation('functional_genomics.query_geo', _screen_query_geo),
    Operation('functional_genomics.import_perturbation_table', _screen_import_table_evidence_records),
    Operation('functional_genomics.compare_gene_perturbation', _screen_answer_gene),
    Operation('decode.render_dashboard', _decode_render_dashboard),
]

_OPERATION_BY_NAME = {operation.name: operation for operation in OPERATIONS}


def list_operations(
    capability: str | None = None,
    namespace: str | None = None,
) -> list[JsonObject]:
    return [
        operation.tool_definition()
        for operation in _select_operations(capability=capability, namespace=namespace)
    ]


def all_operations() -> list[JsonObject]:
    """Return tool definitions for every registered operation, ignoring the
    base-set filter. Used by tests and audit/debug paths that need a
    full inventory regardless of the base-set filter.
    """

    return [operation.tool_definition() for operation in OPERATIONS]


def operation_discovery_payload(
    capability: str | None = None,
    namespace: str | None = None,
) -> JsonObject:
    selected_operations = _select_operations(capability=capability, namespace=namespace)
    tools = [operation.tool_definition() for operation in selected_operations]
    return {"tools": tools}


def _select_operations(
    capability: str | None = None,
    namespace: str | None = None,
) -> list[Operation]:
    capability_key = _optional_capability(capability)
    namespace_key = _optional_namespace(namespace)
    # No filter: return the base set (genomi + journal capabilities plus the
    # genomi.invoke dispatcher). Capability tools outside the base set are
    # reached via genomi.invoke after the agent reads the relevant skill
    # markdown.
    # Explicit capability/namespace filter: return every op in that scope,
    # used by `genomi tools --capability X` CLI debug and capability browsing.
    if capability_key is None and namespace_key is None:
        selected = [
            operation for operation in OPERATIONS
            if _operation_capability(operation) in BASE_CAPABILITIES_IN_DEFAULT_TOOLS_LIST
        ]
    else:
        selected = list(OPERATIONS)
    if capability_key is not None:
        selected = [operation for operation in selected if _operation_capability(operation) == capability_key]
    if namespace_key is not None:
        selected = [operation for operation in selected if _operation_namespace(operation.name) == namespace_key]
    return selected


def _optional_capability(capability: Any) -> str | None:
    if capability in (None, ""):
        return None
    capability_key = str(capability)
    if capability_key not in CAPABILITY_METADATA:
        raise OperationError("invalid_params", f"capability must be one of: {', '.join(CAPABILITY_ORDER)}")
    return capability_key


def _optional_namespace(namespace: Any) -> str | None:
    if namespace in (None, ""):
        return None
    namespace_key = str(namespace)
    if namespace_key not in NAMESPACE_ORDER:
        raise OperationError("invalid_params", f"namespace must be one of: {', '.join(NAMESPACE_ORDER)}")
    return namespace_key


def get_operation(name: str) -> Operation:
    try:
        return _OPERATION_BY_NAME[name]
    except KeyError as exc:
        raise OperationError("unknown_operation", f"Unknown operation: {name}") from exc


def call_operation(name: str, params: JsonObject | None = None) -> JsonObject:
    operation = get_operation(name)
    safe_params = params or {}
    if not isinstance(safe_params, dict):
        raise OperationError("invalid_params", "operation params must be an object")
    try:
        result = operation.handler(safe_params)
    except OperationError:
        # Already structured — pass through so MCP/job_worker emits a clean
        # error envelope instead of background_job_exception.
        raise
    except FileNotFoundError as exc:
        # A required path artifact is missing. Most often this is the
        # Active Genome Index ClinVar match file or an evidence db that hasn't been
        # materialized yet. Surface it as a structured error so agents know
        # which file to produce.
        raise OperationError("needs_file", f"required file not found: {exc}") from exc
    except ValueError as exc:
        # Library functions raise ValueError for missing/invalid required
        # inputs (e.g. "<op> requires gene or condition"). Convert to a
        # structured error so the agent gets an actionable message instead
        # of a background_job_exception.
        raise OperationError("needs_input", str(exc)) from exc
    except _ActiveGenomeIndexNeedsReparse as exc:
        # An on-disk Active Genome Index predates the current schema; the
        # capability tool can't safely read it. Surface a structured code so
        # the agent knows to call genomi.parse_source first.
        raise OperationError("active_genome_index_needs_reparse", str(exc)) from exc
    except _ActiveGenomeIndexSchemaTooNew as exc:
        # The on-disk Active Genome Index was built by a newer Genomi runtime than this
        # one. The agent must upgrade Genomi before reading.
        raise OperationError("active_genome_index_schema_too_new", str(exc)) from exc
    result = _with_defaults_applied(name, safe_params, result)
    return _ensure_envelope(name, result)


# Operations that should always carry an evidence_envelope. Handlers that
# already emit one are passed through unchanged; otherwise a default envelope
# is derived from the result via envelope.derive_default_envelope.
EVIDENCE_PRODUCING_OPERATIONS: frozenset[str] = frozenset(
    {
        # variant / risk / pgx (already emit explicit envelopes)
        "variant.resolve",
        "phenotype.plan_risk_investigation",
        "pharmacogenomics.review_medication",
        "clinvar.scan_candidates",
        # comparator/source tools (auto-injected via apply_evidence_view)
        "phenotype.compare_disease_evidence",
        "phenotype.compare_gene_hpo_evidence",
        "phenotype.compare_drug_target_evidence",
        "functional_genomics.compare_gene_perturbation",
        "gwas.compare_variant_associations",
        "gwas.compare_gene_associations",
        # retrieval / record ops (default envelope from result indicators)
        "phenotype.retrieve_disease_drug_targets",
        "phenotype.retrieve_gene_disease_associations",
        "phenotype.retrieve_trait_gene_records",
        "functional_genomics.retrieve_perturbation_records",
        "functional_genomics.query_geo",
        "functional_genomics.import_perturbation_table",
        "pathway.retrieve_members",
        "cell_type.retrieve_markers",
        "region.retrieve_features",
        "gnomad.fetch_population_frequency",
        "phenotype.normalize_terms",
        # PGx fetch / artifact ops
        "pharmacogenomics.fetch_pgxdb",
        "pharmacogenomics.fetch_clinpgx",
        "pharmacogenomics.fetch_fda_labels",
        "pharmacogenomics.run_pharmcat",
        "pharmacogenomics.describe_gene_requirements",
        "pharmacogenomics.import_pharmcat_artifacts",
        "pharmacogenomics.validate_outside_call_tsv",
        "pharmacogenomics.prepare_outside_call_tsv",
        # evidence build / research ops
        "research.build_target_packet",
        "variant.gather_allele_context",
        "variant.gather_gene_context",
        "research.query",
        "research.search",
        "research.record",
        "ancestry.check_sample_overlap",
        "ancestry.project_pca",
        "ancestry.estimate_population_context",
        "prs.check_score_overlap",
        "prs.calculate_score",
        "decode.render_dashboard",
    }
)


def _ensure_envelope(name: str, result: object) -> object:
    if not isinstance(result, dict):
        return result
    if isinstance(result.get("evidence_envelope"), dict):
        return result
    if name not in EVIDENCE_PRODUCING_OPERATIONS and not _result_needs_guidance(result):
        return result
    try:
        from ...evidence import envelope as _env

        result["evidence_envelope"] = _env.derive_default_envelope(name, result)
    except Exception:
        # Never let envelope derivation break the underlying operation result.
        pass
    return result


def _result_needs_guidance(result: dict[str, object]) -> bool:
    status = str(result.get("status") or "").lower()
    if result.get("ok") is False:
        return True
    if status in {
        "in_progress",
        "requires_library_install",
        "needs_library_install",
        "source_unavailable",
        "source_unavailable_no_evidence",
        "error",
        "unavailable",
        "failed",
    }:
        return True
    return status.startswith(
        (
            "invalid",
            "missing",
            "wrong",
            "blocked",
            "needs",
            "requires",
            "not_",
            "no_",
        )
    ) or status.endswith("_failed")


def load_params(params_json: str | None, params_file: str | Path | None) -> JsonObject:
    if params_json and params_file:
        raise OperationError("invalid_params", "use --params or --params-file, not both")
    if params_file:
        with Path(params_file).open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    elif params_json:
        value = json.loads(params_json)
    else:
        value = {}
    if not isinstance(value, dict):
        raise OperationError("invalid_params", "params must decode to a JSON object")
    return value
