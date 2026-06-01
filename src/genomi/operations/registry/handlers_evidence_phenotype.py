from __future__ import annotations

from ...capabilities.analytical_grounding import analytical_grounding
from ...capabilities.gwas import gwas
from ...capabilities.phenotype import gene_identification, phenotype, targets
from ...capabilities.research import intent_research
from ...evidence import research_scope_choices
from ...retrieval import semantic as retrieval_semantic
from ...runtime.paths import shared_evidence_db_path
from .agi_access import require_session_access
from .coerce import (
    _bool,
    _int,
    _list_dict,
    _list_str,
    _optional_path,
    _path,
    _require_context_value,
    _str,
    _target_kwargs,
    _with_context,
)
from .errors import JsonObject, OperationError


def _population_fetch(params: JsonObject) -> JsonObject:
    resolved = _with_context(params, db=True, shared_db=True, genome_build=True)
    from ...capabilities.clinvar import static_annotation

    return static_annotation.fetch_static_population(
        _path(resolved, "db"),
        _str(resolved, "chrom"),
        _int(resolved, "pos"),
        _str(resolved, "ref"),
        _str(resolved, "alt"),
        shared_evidence_db=_optional_path(resolved, "shared_db"),
        sync_shared=_bool(resolved, "sync_shared", True),
        dataset=_str(resolved, "dataset", "gnomad_r4"),
        genome_build=_str(resolved, "genome_build", "GRCh38"),
        api_url=_str(resolved, "api_url", "https://gnomad.broadinstitute.org/api"),
        force=_bool(resolved, "force"),
    )


def _evidence_packet(params: JsonObject) -> JsonObject:
    resolved = _with_context(params, db=True, genome_build=True)
    return intent_research.evidence_packet(
        _path(resolved, "db"),
        _str(resolved, "target_type"),
        **_target_kwargs(resolved),
        source_id=resolved.get("source_id"),
        limit=_int(resolved, "limit", 20),
    )


def _evidence_gather_allele(params: JsonObject) -> JsonObject:
    resolved = _with_context(params, db=True, matches=True, genome_build=True)
    return intent_research.gather_allele_context(
        _path(resolved, "db"),
        _str(resolved, "chrom"),
        _int(resolved, "pos"),
        _str(resolved, "ref"),
        _str(resolved, "alt"),
        matches=_optional_path(resolved, "matches"),
        genome_build=_str(resolved, "genome_build", "GRCh38"),
        population_source=resolved.get("population_source"),
        population=resolved.get("population"),
    )


def _evidence_gather_gene(params: JsonObject) -> JsonObject:
    resolved = _with_context(params, db=True, matches=True, genome_build=True)
    return intent_research.gather_gene_context(
        _path(resolved, "db"),
        _str(resolved, "gene"),
        matches=_optional_path(resolved, "matches"),
        genome_build=_str(resolved, "genome_build", "GRCh38"),
    )


def _risk_investigate(params: JsonObject) -> JsonObject:
    include_active = _bool(params, "include_active_genome_index", False) or params.get("matches") not in (None, "")
    if include_active:
        # Session-level auth gate: the ClinVar matches artifact is personal,
        # AGI-derived evidence but not tied to one resolved run (a raw matches
        # path may be supplied directly), so the session-approval gate fits
        # better than the run-centric open_agi.
        require_session_access("reading parsed Active Genome Index artifacts for risk investigation")
        resolved = _with_context(params, db=True, matches=True, genome_build=True)
        if resolved.get("matches") in (None, ""):
            raise OperationError(
                "missing_context",
                "Provide matches or select an Active Genome Index with ClinVar matches before using active genome evidence for risk investigation.",
            )
    else:
        resolved = dict(params)
        if not resolved.get("db"):
            resolved["db"] = str(shared_evidence_db_path())
        resolved.setdefault("genome_build", "GRCh38")
    return intent_research.risk_investigation_context(
        _path(resolved, "db"),
        question=resolved.get("question"),
        investigation_type=_str(resolved, "investigation_type", "auto"),
        gene=resolved.get("gene"),
        genes=_list_str(resolved, "genes"),
        condition=resolved.get("condition"),
        topic=resolved.get("topic"),
        matches=_optional_path(resolved, "matches"),
        genome_build=_str(resolved, "genome_build", "GRCh38"),
        limit=_int(resolved, "limit", 25),
        search_stored_research=_bool(resolved, "search_stored_research", True),
    )


def _phenotype_normalize(params: JsonObject) -> JsonObject:
    return phenotype.normalize_phenotypes(
        text=params.get("text") or params.get("phenotype_text"),
        terms=_list_str(params, "terms") or _list_str(params, "phenotypes"),
        hpo_ids=_list_str(params, "hpo_ids"),
        semantic_context=params.get("semantic_context"),
    )


def _pathway_retrieve_member_genes(params: JsonObject) -> JsonObject:
    return analytical_grounding.retrieve_pathway_member_genes(
        pathway_id_or_name=params.get("pathway_id_or_name"),
        pathway_id=params.get("pathway_id"),
        pathway_name=params.get("pathway_name"),
        source=params.get("source"),
        species=params.get("species"),
        limit=_int(params, "limit", 500),
        reactome_api_base=_str(params, "reactome_api_base", analytical_grounding.REACTOME_CONTENT_SERVICE_BASE),
        kegg_api_base=_str(params, "kegg_api_base", analytical_grounding.KEGG_REST_API_BASE),
        msigdb_gmt=_optional_path(params, "msigdb_gmt"),
        msigdb_gmt_url=params.get("msigdb_gmt_url"),
        msigdb_version=params.get("msigdb_version"),
        semantic_context=params.get("semantic_context"),
    )


def _cell_type_retrieve_canonical_markers(params: JsonObject) -> JsonObject:
    return analytical_grounding.retrieve_canonical_markers(
        cell_type_id_or_name=params.get("cell_type_id_or_name"),
        cell_type_id=params.get("cell_type_id"),
        cell_type_name=params.get("cell_type_name"),
        source=params.get("source"),
        species=params.get("species"),
        marker_table=_optional_path(params, "marker_table"),
        limit=_int(params, "limit", 100),
        hpa_api_base=_str(params, "hpa_api_base", analytical_grounding.HPA_API_BASE),
        hpa_download_base=_str(params, "hpa_download_base", analytical_grounding.HPA_TSV_DOWNLOAD_BASE),
        semantic_context=params.get("semantic_context"),
    )


def _region_retrieve_feature_annotation(params: JsonObject) -> JsonObject:
    return analytical_grounding.retrieve_region_feature_annotation(
        chrom=params.get("chrom"),
        start=params.get("start"),
        end=params.get("end"),
        assembly=params.get("assembly"),
        region=params.get("region"),
        gencode_gtf=_optional_path(params, "gencode_gtf"),
        encode_ccre_bed=_optional_path(params, "encode_ccre_bed"),
        limit=_int(params, "limit", 100),
    )


def _disease_compare_phenotype_evidence(params: JsonObject) -> JsonObject:
    resolved = _with_context(params, db=True, allow_shared_db_without_vcf=True)
    return phenotype.compare_disease_phenotype_evidence(
        _path(resolved, "db"),
        phenotype_text=resolved.get("phenotype_text") or resolved.get("text"),
        phenotypes=_list_str(resolved, "phenotypes") or _list_str(resolved, "terms"),
        hpo_ids=_list_str(resolved, "hpo_ids"),
        candidate_diseases=_list_str(resolved, "candidate_diseases") or _list_str(resolved, "diseases"),
        genes=_list_str(resolved, "genes") or _list_str(resolved, "gene_symbols"),
        source_records=_list_dict(resolved, "source_records"),
        search_stored_research=_bool(resolved, "search_stored_research", True),
        use_hpo_annotations=_bool(resolved, "use_hpo_annotations", True),
        download_hpo_annotations=_bool(resolved, "download_hpo_annotations", False),
        hpo_disease_file=_optional_path(resolved, "hpo_disease_file"),
        use_primary_gene_disease=_bool(resolved, "use_primary_gene_disease", True),
        download_primary_gene_disease=_bool(resolved, "download_primary_gene_disease", False),
        gencc_file=_optional_path(resolved, "gencc_file"),
        limit=_int(resolved, "limit", 25),
        semantic_context=resolved.get("semantic_context"),
    )


def _gene_retrieve_primary_disease_associations(params: JsonObject) -> JsonObject:
    semantic = retrieval_semantic.parse_semantic_context(params.get("semantic_context"))
    genes = _list_str(params, "genes") or _list_str(params, "gene_symbols") or _semantic_entity_texts(semantic, "gene")
    result = phenotype.retrieve_primary_gene_disease_associations(
        genes=genes,
        gencc_file=_optional_path(params, "gencc_file"),
        download_gencc=_bool(params, "download_gencc", False),
        classifications=_list_str(params, "classifications"),
        limit=_int(params, "limit", 100),
    )
    if semantic.has_hints:
        matched_genes = {str(gene).upper() for gene in genes}
        term_matches = [
            {
                "text": str(entity.get("text") or ""),
                "status": "hit",
                "match_type": "used_as_exact_gene_lookup",
                "source": "GenCC submissions",
            }
            for entity in semantic.host_entities
            if str(entity.get("type") or "").casefold() == "gene"
            and str(entity.get("text") or "").upper() in matched_genes
        ]
        result["semantic_context"] = retrieval_semantic.term_usage_payload(
            semantic,
            term_matches=term_matches,
            streams=retrieval_semantic.retrieval_streams(
                raw_query=semantic.raw_query,
                host_terms=[str(entity.get("text") or "") for entity in semantic.host_entities if str(entity.get("type") or "").casefold() == "gene"],
                exact_ids=genes,
                source_native_filters=genes,
            ),
        )
    return result


def _semantic_entity_texts(semantic: retrieval_semantic.SemanticContext, *entity_types: str) -> list[str]:
    allowed = {item.casefold() for item in entity_types}
    return [
        str(entity.get("text") or "").strip()
        for entity in semantic.host_entities
        if str(entity.get("type") or "").strip().casefold() in allowed
        and str(entity.get("text") or "").strip()
    ]


def _first_semantic_entity_text(semantic: retrieval_semantic.SemanticContext, *entity_types: str) -> str | None:
    texts = _semantic_entity_texts(semantic, *entity_types)
    return texts[0] if texts else None


def _with_simple_semantic_lookup_usage(
    result: JsonObject,
    semantic: retrieval_semantic.SemanticContext,
    selected_values: list[str | None],
    *,
    source: str,
) -> JsonObject:
    if not semantic.has_hints:
        return result
    matched = [value for value in selected_values if value]
    if not _result_has_source_records(result):
        matched = []
    result["semantic_context"] = retrieval_semantic.term_usage_payload(
        semantic,
        term_matches=retrieval_semantic.matched_terms(
            semantic,
            matched,
            match_type="matched_source_lookup_result",
            source=source,
        ),
        streams=retrieval_semantic.retrieval_streams(
            raw_query=semantic.raw_query,
            host_terms=retrieval_semantic.search_terms(semantic),
            source_native_filters=[value for value in selected_values if value],
        ),
    )
    return result


def _result_has_source_records(value: object) -> bool:
    if isinstance(value, dict):
        summary = value.get("summary")
        if isinstance(summary, dict):
            for key, item in summary.items():
                if key.endswith("_count") and isinstance(item, int) and item > 0:
                    return True
        for key, item in value.items():
            if key in {"raw_records", "query", "summary", "semantic_context"}:
                continue
            if isinstance(item, list) and item and (
                key.endswith("records")
                or key.endswith("annotations")
                or key.endswith("rows")
                or key in {"guidelines", "labels", "associations"}
            ):
                return True
            if _result_has_source_records(item):
                return True
    return False


def _trait_retrieve_gene_records(params: JsonObject) -> JsonObject:
    return gene_identification.retrieve_trait_gene_records(
        trait=_str(params, "trait"),
        genes=_list_str(params, "genes"),
        opentargets_api_url=_str(params, "opentargets_api_url", gene_identification.OPENTARGETS_GRAPHQL_API_URL),
        limit=_int(params, "limit", 25),
        semantic_context=params.get("semantic_context"),
    )


def _gwas_compare_trait_gene_evidence(params: JsonObject) -> JsonObject:
    evidence_intent = _str(params, "evidence_intent", gwas.GWAS_GENE_FIELD_EVIDENCE_INTENT)
    if evidence_intent != gwas.GWAS_GENE_FIELD_EVIDENCE_INTENT:
        raise OperationError(
            "invalid_params",
            f"evidence_intent must be {gwas.GWAS_GENE_FIELD_EVIDENCE_INTENT!r}",
        )
    return gene_identification.compare_gwas_catalog_gene_evidence(
        _str(params, "phenotype"),
        _list_str(params, "genes"),
        api_url=_str(params, "api_url", gwas.GWAS_CATALOG_V2_API_URL),
        association_limit=_int(params, "association_limit", 200),
        source_records=_list_dict(params, "source_records") if params.get("source_records") is not None else None,
        task_text=params.get("task_text") or params.get("question") or params.get("text"),
        evidence_intent=evidence_intent,
        semantic_context=params.get("semantic_context"),
    )


def _drug_compare_target_evidence(params: JsonObject) -> JsonObject:
    resolved = _with_context(params, db=True, allow_shared_db_without_vcf=True)
    return gene_identification.compare_drug_target_gene_evidence(
        _path(resolved, "db"),
        drug=resolved.get("drug"),
        drug_class=resolved.get("drug_class"),
        indication=resolved.get("indication") or resolved.get("phenotype"),
        mechanism=resolved.get("mechanism"),
        genes=_list_str(resolved, "genes"),
        source_records=_list_dict(resolved, "source_records"),
        search_stored_research=_bool(resolved, "search_stored_research", True),
        limit=_int(resolved, "limit", 25),
        semantic_context=resolved.get("semantic_context"),
    )


def _disease_retrieve_clinical_drug_targets(params: JsonObject) -> JsonObject:
    return targets.retrieve_disease_clinical_drug_targets(
        disease=params.get("disease"),
        disease_id=params.get("disease_id"),
        genes=_list_str(params, "genes"),
        mode=_str(params, "mode", "records"),
        minimum_clinical_stage=_str(params, "minimum_clinical_stage", "PHASE_2"),
        api_url=_str(params, "opentargets_api_url", targets.OPENTARGETS_GRAPHQL_API_URL),
        limit=_int(params, "limit", 100),
        semantic_context=params.get("semantic_context"),
    )


def _phenotype_compare_gene_hpo_evidence(params: JsonObject) -> JsonObject:
    resolved = _with_context(params, db=True, allow_shared_db_without_vcf=True)
    phenotype_text = resolved.get("phenotype") or resolved.get("phenotype_text") or resolved.get("text")
    return gene_identification.compare_phenotype_annotation_gene_evidence(
        _path(resolved, "db"),
        phenotype_text=phenotype_text,
        phenotypes=_list_str(resolved, "phenotypes") or _list_str(resolved, "terms"),
        hpo_ids=_list_str(resolved, "hpo_ids"),
        condition=resolved.get("condition"),
        genes=_list_str(resolved, "genes"),
        source_records=_list_dict(resolved, "source_records"),
        search_stored_research=_bool(resolved, "search_stored_research", True),
        use_hpo_annotations=_bool(resolved, "use_hpo_annotations", True),
        download_hpo_annotations=_bool(resolved, "download_hpo_annotations", False),
        hpo_gene_file=_optional_path(resolved, "hpo_gene_file"),
        limit=_int(resolved, "limit", 25),
        semantic_context=resolved.get("semantic_context"),
    )


def _evidence_record_research(params: JsonObject) -> JsonObject:
    scope = _str(params, "scope", "shared")
    if scope not in research_scope_choices():
        raise OperationError("invalid_params", "scope must be one of: " + ", ".join(research_scope_choices()))
    resolved = _with_context(
        params,
        db=True,
        shared_db=True,
        allow_shared_db_without_vcf=scope == "shared",
    )
    if scope == "private":
        _require_context_value(
            resolved,
            "db",
            "Private reviewed research requires a selected Active Genome Index or explicit private evidence DB.",
        )
    payload = resolved.get("payload")
    if payload is not None:
        if not isinstance(payload, (dict, list)):
            raise OperationError("invalid_params", "payload must be an object or array of objects")
        return intent_research.record_reviewed_research(
            _path(resolved, "db"),
            payload,
            scope=scope,
            shared_evidence_db=_optional_path(resolved, "shared_db"),
            sync_shared=_bool(resolved, "sync_shared", True),
        )
    if resolved.get("input"):
        return intent_research.record_reviewed_research_file(
            _path(resolved, "db"),
            _path(resolved, "input"),
            scope=scope,
            shared_evidence_db=_optional_path(resolved, "shared_db"),
            sync_shared=_bool(resolved, "sync_shared", True),
        )
    raise OperationError("invalid_params", "Provide input or payload for research.record.")


def _evidence_query_research(params: JsonObject) -> JsonObject:
    resolved = _with_context(params, db=True, genome_build=True)
    return intent_research.query_reviewed_research(
        _path(resolved, "db"),
        _str(resolved, "target_type"),
        **_target_kwargs(resolved),
        scope=resolved.get("scope"),
        limit=_int(resolved, "limit", 20),
    )


def _evidence_search_research(params: JsonObject) -> JsonObject:
    resolved = _with_context(params, db=True)
    return intent_research.search_reviewed_research(
        _path(resolved, "db"),
        _str(resolved, "query"),
        target_type=resolved.get("target_type"),
        scope=resolved.get("scope"),
        limit=_int(resolved, "limit", 50),
        semantic_context=resolved.get("semantic_context"),
    )
