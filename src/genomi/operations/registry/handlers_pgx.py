from __future__ import annotations

from ...capabilities.pharmacogenomics import (
    clinpgx,
    fda_pgx,
    pgx_outside_calls,
    pgx_requirements,
    pgxdb,
    pharmcat,
)
from ...capabilities.pharmacogenomics import review as pgx
from ...retrieval import semantic as retrieval_semantic
from ...runtime import context as runtime_context
from ...runtime.paths import shared_evidence_db_path
from .coerce import (
    _approve_supplied_dna_source,
    _bool,
    _int,
    _optional_path,
    _path,
    _require_agi_access,
    _require_personal_artifact_context,
    _str,
    _with_context,
)
from .errors import JsonObject
from .handlers_evidence_phenotype import (
    _first_semantic_entity_text,
    _with_simple_semantic_lookup_usage,
)


def _pgx_lookup(params: JsonObject) -> JsonObject:
    semantic = retrieval_semantic.parse_semantic_context(params.get("semantic_context"))
    drug = params.get("drug") or _first_semantic_entity_text(semantic, "drug", "medication")
    gene = params.get("gene") or _first_semantic_entity_text(semantic, "gene")
    rsid = params.get("rsid") or _first_semantic_entity_text(semantic, "rsid", "variant")
    result = pgxdb.lookup_pgxdb(
        drug=drug,
        atc_code=params.get("atc_code"),
        drugbank_id=params.get("drugbank_id"),
        rsid=rsid,
        variant_marker=params.get("variant_marker"),
        gene=gene,
        include_raw_records=_bool(params, "include_raw_records", False),
        limit=_int(params, "limit", 25),
        api_url=params.get("api_url"),
    )
    return _with_simple_semantic_lookup_usage(result, semantic, [drug, gene, rsid], source="PGxDB")


def _pgx_gene_requirements(params: JsonObject) -> JsonObject:
    semantic = retrieval_semantic.parse_semantic_context(params.get("semantic_context"))
    gene = params.get("gene") or _first_semantic_entity_text(semantic, "gene")
    return pgx_requirements.pharmacogene_requirements(
        gene=gene,
        refresh_sources=_bool(params, "refresh_sources", False),
        pharmcat_genes_drugs_url=params.get("pharmcat_genes_drugs_url"),
    )


def _clinpgx_lookup(params: JsonObject) -> JsonObject:
    semantic = retrieval_semantic.parse_semantic_context(params.get("semantic_context"))
    drug = params.get("drug") or _first_semantic_entity_text(semantic, "drug", "medication")
    gene = params.get("gene") or _first_semantic_entity_text(semantic, "gene")
    rsid = params.get("rsid") or _first_semantic_entity_text(semantic, "rsid", "variant")
    result = clinpgx.lookup_clinpgx(
        drug=drug,
        gene=gene,
        rsid=rsid,
        chemical_id=params.get("chemical_id"),
        gene_id=params.get("gene_id"),
        variant_id=params.get("variant_id"),
        guideline_source=params.get("guideline_source"),
        include_clinical_annotations=_bool(params, "include_clinical_annotations", True),
        include_labels=_bool(params, "include_labels", True),
        include_raw_records=_bool(params, "include_raw_records", False),
        limit=_int(params, "limit", 10),
        api_url=params.get("api_url"),
    )
    return _with_simple_semantic_lookup_usage(result, semantic, [drug, gene, rsid], source="ClinPGx")


def _fda_pgx_lookup(params: JsonObject) -> JsonObject:
    semantic = retrieval_semantic.parse_semantic_context(params.get("semantic_context"))
    drug = params.get("drug") or _first_semantic_entity_text(semantic, "drug", "medication")
    gene = params.get("gene") or _first_semantic_entity_text(semantic, "gene")
    result = fda_pgx.lookup_fda_pgx(
        drug=drug,
        gene=gene,
        source=_str(params, "source", "all"),
        include_raw_rows=_bool(params, "include_raw_rows", False),
        limit=_int(params, "limit", 25),
        biomarkers_url=params.get("biomarkers_url"),
        associations_url=params.get("associations_url"),
    )
    return _with_simple_semantic_lookup_usage(result, semantic, [drug, gene], source="FDA PGx tables")


def _pgx_medication_review(params: JsonObject) -> JsonObject:
    _approve_supplied_dna_source(params, ("vcf",))
    include_active_supplied = "include_active_genome_index" in params
    include_active_requested = (
        _bool(params, "include_active_genome_index", False)
        if include_active_supplied
        else runtime_context.active_run() is not None
    )
    personal_context_requested = (
        any(params.get(key) for key in ("vcf", "db", "active_genome_index_path", "matches"))
        or include_active_requested
        or _bool(params, "include_known_active_genome_indexes", False)
    )
    if personal_context_requested:
        _require_agi_access("reading parsed Active Genome Index artifacts")
        resolved = _with_context(
            params,
            vcf=True,
            db=True,
            shared_db=True,
            genome_build=True,
            allow_shared_db_without_vcf=False,
        )
    else:
        resolved = dict(params)
        resolved.setdefault("shared_db", str(shared_evidence_db_path()))
    return pgx.review_medication_interaction(
        drug=_str(resolved, "drug", ""),
        gene=resolved.get("gene"),
        rsid=resolved.get("rsid"),
        atc_code=resolved.get("atc_code"),
        drugbank_id=resolved.get("drugbank_id"),
        indication=resolved.get("indication"),
        dose=resolved.get("dose"),
        current_medications=resolved.get("current_medications"),
        allergies_or_contraindications=resolved.get("allergies_or_contraindications"),
        known_genotype=resolved.get("known_genotype"),
        known_diplotype=resolved.get("known_diplotype"),
        known_phenotype=resolved.get("known_phenotype"),
        known_activity_score=resolved.get("known_activity_score"),
        known_pgx_source=resolved.get("known_pgx_source"),
        genome_build=_str(resolved, "genome_build", "GRCh38"),
        db=resolved.get("db"),
        shared_db=resolved.get("shared_db"),
        include_active_genome_index=_bool(resolved, "include_active_genome_index", bool(resolved.get("db") or resolved.get("vcf"))),
        include_known_active_genome_indexes=_bool(resolved, "include_known_active_genome_indexes", False),
        include_stored_research=_bool(resolved, "include_stored_research", True),
        include_record_research_payloads=_bool(resolved, "include_record_research_payloads", False),
        has_active_genome_index_context=bool(resolved.get("vcf")),
        limit=_int(resolved, "limit", 10),
        clinpgx_api_url=resolved.get("clinpgx_api_url"),
        pgxdb_api_url=resolved.get("pgxdb_api_url"),
        fda_biomarkers_url=resolved.get("fda_biomarkers_url"),
        fda_associations_url=resolved.get("fda_associations_url"),
        semantic_context=resolved.get("semantic_context"),
    )


def _pgx_pharmcat(params: JsonObject) -> JsonObject:
    resolved = _with_context(params, vcf=True, genome_build=True, allow_shared_db_without_vcf=False)
    _require_personal_artifact_context(
        params,
        resolved,
        "vcf",
        "Select an Active Genome Index or provide a genome source path before running PharmCAT.",
        "reading raw or parsed Active Genome Index artifacts",
    )
    return pharmcat.run_pharmcat(
        vcf=_path(resolved, "vcf"),
        output_dir=resolved.get("output_dir"),
        base_filename=resolved.get("base_filename"),
        mode=_str(resolved, "mode", "auto"),
        pipeline_command=resolved.get("pipeline_command"),
        pharmcat_jar=resolved.get("pharmcat_jar"),
        java_command=resolved.get("java_command"),
        sample=resolved.get("sample"),
        sample_file=resolved.get("sample_file"),
        sample_metadata=resolved.get("sample_metadata"),
        outside_call_file=resolved.get("outside_call_file"),
        reporter_sources=resolved.get("reporter_sources"),
        research_mode=resolved.get("research_mode"),
        max_memory=resolved.get("max_memory"),
        max_concurrent_processes=resolved.get("max_concurrent_processes"),
        include_reporter_json=_bool(resolved, "include_reporter_json", True),
        include_calls_only_tsv=_bool(resolved, "include_calls_only_tsv", True),
        probe_version=_bool(resolved, "probe_version", True),
        dry_run=_bool(resolved, "dry_run", False),
        timeout_seconds=_int(resolved, "timeout_seconds", 7200),
    )


def _pgx_pharmcat_preflight(params: JsonObject) -> JsonObject:
    resolved = _with_context(params, vcf=True, genome_build=True, allow_shared_db_without_vcf=False)
    _require_personal_artifact_context(
        params,
        resolved,
        "vcf",
        "Select an Active Genome Index or provide a genome source path before checking PharmCAT preflight.",
        "reading raw or parsed Active Genome Index artifacts",
    )
    return pharmcat.pharmcat_preflight(vcf=_path(resolved, "vcf"))


def _pgx_pharmcat_import(params: JsonObject) -> JsonObject:
    return pharmcat.import_pharmcat_artifacts(
        output_dir=params.get("output_dir"),
        base_filename=params.get("base_filename"),
        report_json=params.get("report_json"),
        calls_only_tsv=params.get("calls_only_tsv"),
        match_json=params.get("match_json"),
        phenotype_json=params.get("phenotype_json"),
        missing_pgx_positions_vcf=params.get("missing_pgx_positions_vcf"),
    )


def _pgx_outside_call_validate(params: JsonObject) -> JsonObject:
    return pgx_outside_calls.validate_outside_call_file(
        params.get("outside_call_file"),
        max_rows=_int(params, "max_rows", 200),
    )


def _pgx_outside_call_prepare(params: JsonObject) -> JsonObject:
    return pgx_outside_calls.prepare_outside_call_file(
        params.get("caller_output_file"),
        caller_format=_str(params, "caller_format", "auto"),
        output_file=params.get("output_file"),
        sample=params.get("sample"),
        max_rows=_int(params, "max_rows", 200),
    )


def _pgx_pharmcat_status(params: JsonObject) -> JsonObject:
    return pharmcat.pharmcat_status(
        mode=_str(params, "mode", "auto"),
        pipeline_command=params.get("pipeline_command"),
        pharmcat_jar=params.get("pharmcat_jar"),
        java_command=params.get("java_command"),
        timeout_seconds=_int(params, "timeout_seconds", 15),
    )
