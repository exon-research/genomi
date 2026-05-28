from __future__ import annotations

from pathlib import Path
from typing import Any

from ....evidence import envelope as _env
from ....evidence.candidate_evidence import (
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
from ....evidence.task_profiles import PGX_MEDICATION_REVIEW
from ....retrieval import semantic as retrieval_semantic
from ...variant import variant_lookup
from .. import clinpgx, fda_pgx, pgx_star, pgxdb, pharmcat
from ._common import (
    JsonObject,
    _clean,
    _compact_public_source_result,
    _normalize_gene,
    _normalize_rsid,
    _pgx_semantic_usage,
    _selected_semantic_target,
    _single_value,
)
from .evidence_matrix import (
    _evidence_item_role_counts,
    _evidence_matrix,
    _evidence_matrix_traceability,
)
from .record_research import (
    _record_research_payload_role_counts,
    _record_research_payload_summaries,
    _source_record_research_payloads,
    _stored_sample_evidence_count,
    _stored_source_evidence_count,
)
from .sample_evidence import (
    _answer_support,
    _follow_up_rsids,
    _follow_up_star_genes,
    _has_active_genome_index_context,
    _readiness,
    _sequencing_sample_match_count,
    _star_marker_match_count,
    _target_inventory,
    _technical_support_count,
)
from .source_state import (
    _evidence_components,
    _evidence_envelope,
    _evidence_state,
    _medication_review_status,
    _source_availability,
    _unanswered_answer_components,
)
from .stored_research import _stored_research_context


def capability_inventory(*, check_pharmcat: bool = False, pharmcat_timeout_seconds: int = 15) -> JsonObject:
    pharmcat_status = (
        pharmcat.pharmcat_status(timeout_seconds=pharmcat_timeout_seconds)
        if check_pharmcat
        else {"schema": "genomi-pharmcat-status-v1", "status": "not_checked", "operation": "pharmacogenomics.check_pharmcat"}
    )
    return {
        "schema": "genomi-pgx-capabilities-v1",
        "status": "completed",
        "capability_axes": {
            "public_source_evidence": {
                "purpose": "Drug, gene, rsID, guideline, label, and association evidence.",
                "operations": ["pharmacogenomics.review_medication", "pharmacogenomics.fetch_clinpgx", "pharmacogenomics.fetch_pgxdb", "pharmacogenomics.fetch_fda_labels", "research.list_sources", "research.record"],
                "implemented_sources": [
                    {"source": "ClinPGx", "evidence": ["CPIC guideline annotations", "DPWG/Pro guideline annotations", "clinical annotations", "FDA label annotations"]},
                    {"source": "PGxDB", "evidence": ["drug-gene-variant association rows", "ATC and DrugBank-targeted records"]},
                    {"source": "FDA PGx tables", "evidence": ["pharmacogenomic biomarker labeling rows", "pharmacogenetic association rows"]},
                ],
                "traceability": "External calls and record_research_payloads are returned by source lookup tools including pharmacogenomics.fetch_clinpgx, pharmacogenomics.fetch_pgxdb, and pharmacogenomics.fetch_fda_labels.",
            },
            "targeted_sample_evidence": {
                "purpose": "Selected rsID, allele, locus, or region lookup against the Active Genome Index.",
                "operations": ["variant.resolve", "active_genome_index.classify_genotype_support", "active_genome_index.classify_region_callability"],
                "evidence_classes": ["observed genotype", "exact allele support", "technical support", "region callability"],
            },
            "implemented_marker_definition_sets": {
                "purpose": "Small deterministic marker definitions for sample-side PGx triage.",
                "operations": ["pharmacogenomics.review_medication"],
                "implementation_scope": "internal marker triage inside medication review; broad named-allele calling uses PharmCAT or imported specialized caller artifacts",
                "implemented_marker_definition_genes": pgx_star.implemented_marker_definition_genes(),
                "definition_sets": [
                    {
                        "gene": definition["gene"],
                        "definition_set": definition["definition_set"],
                        "definition_scope": definition.get("definition_scope"),
                        "marker_count": len(definition["markers"]),
                        "sources": definition["sources"],
                    }
                    for definition in pgx_star.STAR_DEFINITIONS.values()
                ],
            },
            "pharmacogene_requirement_catalog": {
                "purpose": "Gene-specific sample evidence requirements for named allele matching, outside calls, SV/CNV-sensitive genes, HLA typing, MT-RNR1, and G6PD chrX representation.",
                "operations": ["pharmacogenomics.describe_gene_requirements", "pharmacogenomics.prepare_outside_call_tsv", "pharmacogenomics.validate_outside_call_tsv"],
                "traceability": "pharmacogenomics.describe_gene_requirements returns source document URLs for PharmCAT gene handling and outside-call requirements.",
            },
            "broad_vcf_pgx_calling": {
                "purpose": "Broad VCF/gVCF-derived diplotype, phenotype, and recommendation artifacts.",
                "operations": ["pharmacogenomics.preflight_pharmcat", "pharmacogenomics.prepare_outside_call_tsv", "pharmacogenomics.validate_outside_call_tsv", "pharmacogenomics.import_pharmcat_artifacts", "pharmacogenomics.check_pharmcat", "pharmacogenomics.run_pharmcat"],
                "runtime_status": pharmcat_status,
                "artifact_evidence": ["report JSON", "report HTML", "calls-only TSV", "match JSON", "phenotype JSON"],
                "traceability": "pharmacogenomics.preflight_pharmcat returns VCF structure facts; pharmacogenomics.import_pharmcat_artifacts parses existing artifacts; pharmacogenomics.run_pharmcat returns command provenance, version probe, input content hash, artifact list, parsed calls, and record_research_payloads.",
            },
        },
        "evidence_frames": [
            {
                "intent": "public medication or drug-gene question",
                "operation_family": ["pharmacogenomics.review_medication", "pharmacogenomics.fetch_clinpgx", "pharmacogenomics.fetch_pgxdb"],
                "answer_basis": "public PGx evidence only",
            },
            {
                "intent": "does my Active Genome Index affect this medication",
                "operation_family": ["genomi.describe_context", "pharmacogenomics.review_medication"],
                "sample_evidence_artifact_types": [
                    "Active Genome Index variant match",
                    "VCF genotype support",
                    "supported star-allele marker call",
                    "PharmCAT report JSON",
                    "PharmCAT calls-only TSV",
                    "PharmCAT matcher JSON",
                    "PharmCAT phenotype JSON",
                    "PharmCAT outside-call TSV",
                    "specialized caller output",
                ],
                "answer_basis": "public PGx evidence plus selected local sample evidence",
            },
            {
                "intent": "report-ready or reusable PGx interpretation",
                "operation_family": ["pharmacogenomics.review_medication", "pharmacogenomics.run_pharmcat", "research.record"],
                "answer_basis": "stored source-backed and sample-backed findings with scope shared or private",
            },
        ],
        "clinical_boundary": {
            "status": "informational_evidence_review_requires_clinical_confirmation",
            "requires": [
                "sample identity and Active Genome Index selection",
                "source-backed drug guideline, label, clinical annotation, or association evidence",
                "sample-side genotype, diplotype, phenotype, technical support, or PharmCAT artifact evidence",
                "clinical context such as indication, contraindications, current medications, and clinician/pharmacist review",
            ],
        },
    }


def review_medication_interaction(
    *,
    drug: str,
    gene: str | None = None,
    rsid: str | None = None,
    atc_code: str | None = None,
    drugbank_id: str | None = None,
    indication: str | None = None,
    dose: str | None = None,
    current_medications: str | None = None,
    allergies_or_contraindications: str | None = None,
    known_genotype: str | None = None,
    known_diplotype: str | None = None,
    known_phenotype: str | None = None,
    known_activity_score: str | None = None,
    known_pgx_source: str | None = None,
    genome_build: str = "GRCh38",
    db: str | Path | None = None,
    shared_db: str | Path | None = None,
    include_active_genome_index: bool = False,
    include_known_active_genome_indexes: bool = False,
    include_stored_research: bool = True,
    include_record_research_payloads: bool = False,
    has_active_genome_index_context: bool = False,
    limit: int = 10,
    clinpgx_api_url: str | None = None,
    pgxdb_api_url: str | None = None,
    fda_biomarkers_url: str | None = None,
    fda_associations_url: str | None = None,
    semantic_context: object = None,
) -> JsonObject:
    """Compose public PGx evidence with Active Genome Index lookup."""

    semantic = retrieval_semantic.parse_semantic_context(semantic_context)
    raw_drug = _clean(drug)
    selected_drug = _selected_semantic_target(
        raw_value=raw_drug,
        semantic=semantic,
        entity_types=("drug", "medication"),
    )
    proposed_gene = _selected_semantic_target(
        raw_value="",
        semantic=semantic,
        entity_types=("gene",),
    )
    proposed_rsid = _selected_semantic_target(
        raw_value="",
        semantic=semantic,
        entity_types=("variant", "rsid"),
    )
    if not selected_drug and not drugbank_id and not atc_code:
        return {
            "ok": False,
            "status": "invalid_target",
            "query": {"drug": selected_drug, "gene": gene, "rsid": rsid, "atc_code": atc_code, "drugbank_id": drugbank_id},
            "semantic_context": retrieval_semantic.term_usage_payload(
                semantic,
                streams=retrieval_semantic.retrieval_streams(
                    raw_query=semantic.raw_query or raw_drug,
                    host_terms=retrieval_semantic.search_terms(semantic),
                ),
            ),
            "unanswered_answer_components": [
                {"component": "medication_target", "state": "missing", "missing_inputs": ["drug", "atc_code", "drugbank_id"]}
            ],
        }

    selected_gene = _normalize_gene(gene) or _normalize_gene(proposed_gene)
    selected_rsid = _normalize_rsid(rsid) or _normalize_rsid(proposed_rsid)
    bounded_limit = max(1, min(int(limit or 10), 25))
    clinpgx_result = clinpgx.lookup_clinpgx(
        drug=selected_drug,
        gene=selected_gene,
        rsid=selected_rsid,
        include_clinical_annotations=True,
        include_labels=True,
        limit=bounded_limit,
        api_url=clinpgx_api_url,
    )
    pgxdb_result = pgxdb.lookup_pgxdb(
        drug=selected_drug,
        atc_code=atc_code,
        drugbank_id=drugbank_id,
        rsid=selected_rsid,
        gene=selected_gene,
        limit=bounded_limit,
        api_url=pgxdb_api_url,
    )
    fda_result = fda_pgx.lookup_fda_pgx(
        drug=selected_drug,
        gene=selected_gene,
        source="all",
        limit=bounded_limit,
        biomarkers_url=fda_biomarkers_url,
        associations_url=fda_associations_url,
    )
    rsid_targets = _follow_up_rsids(selected_rsid, clinpgx_result, pgxdb_result, limit=bounded_limit)
    star_genes = _follow_up_star_genes(selected_gene, clinpgx_result)
    stored_research = _stored_research_context(
        db=db,
        shared_db=shared_db,
        drug=selected_drug,
        gene=selected_gene,
        genes=star_genes,
        rsid=selected_rsid,
        genome_build=genome_build,
        include_stored_research=include_stored_research,
        limit=bounded_limit,
    )
    known_sample_fact_count = _known_sample_fact_count(
        known_genotype=known_genotype,
        known_diplotype=known_diplotype,
        known_phenotype=known_phenotype,
        known_activity_score=known_activity_score,
        known_pgx_source=known_pgx_source,
    )
    stored_sample_evidence_count = _stored_sample_evidence_count(stored_research)
    active_sample_lookup_requested = bool(include_active_genome_index or has_active_genome_index_context or db)
    sample_context_requested = bool(
        active_sample_lookup_requested
        or include_known_active_genome_indexes
        or known_sample_fact_count
        or stored_sample_evidence_count
    )
    sample_lookups = [
        variant_lookup.lookup_variant(
            rsid=target,
            genome_build=genome_build,
            db=db,
            shared_db=shared_db,
            include_active_genome_index=active_sample_lookup_requested,
            include_known_active_genome_indexes=include_known_active_genome_indexes,
            limit=bounded_limit,
        )
        for target in rsid_targets
    ] if sample_context_requested else []
    star_allele_calls = [
        pgx_star.call_star_alleles(
            gene=target_gene,
            genome_build=genome_build,
            db=db,
            shared_db=shared_db,
            include_active_genome_index=active_sample_lookup_requested,
            include_known_active_genome_indexes=include_known_active_genome_indexes,
            limit=bounded_limit,
        )
        for target_gene in star_genes
        if target_gene in pgx_star.implemented_marker_definition_genes()
    ] if sample_context_requested else []
    sample_match_count = sum(int(lookup.get("sample_context", {}).get("count") or 0) for lookup in sample_lookups)
    technical_support_count = _technical_support_count(sample_lookups)
    sequencing_sample_match_count = _sequencing_sample_match_count(sample_lookups)
    active_genome_index_context_available = bool(has_active_genome_index_context or _has_active_genome_index_context(sample_lookups))
    star_marker_match_count = _star_marker_match_count(star_allele_calls)
    clinical_context = _clinical_context(
        indication=indication,
        dose=dose,
        current_medications=current_medications,
        allergies_or_contraindications=allergies_or_contraindications,
    )
    user_provided_sample_evidence = _user_provided_sample_pgx_evidence(
        selected_gene=selected_gene,
        selected_rsid=selected_rsid,
        rsid_targets=rsid_targets,
        star_genes=star_genes,
        known_genotype=known_genotype,
        known_diplotype=known_diplotype,
        known_phenotype=known_phenotype,
        known_activity_score=known_activity_score,
        known_pgx_source=known_pgx_source,
    )
    user_sample_evidence_count = len(user_provided_sample_evidence)
    public_evidence_count = (
        int(clinpgx_result.get("summary", {}).get("guideline_annotation_count") or 0)
        + int(clinpgx_result.get("summary", {}).get("clinical_annotation_count") or 0)
        + int(clinpgx_result.get("summary", {}).get("label_annotation_count") or 0)
        + int(pgxdb_result.get("summary", {}).get("pgx_record_count") or 0)
        + int(pgxdb_result.get("summary", {}).get("medication_scoped_gene_drug_record_count") or 0)
        + int(fda_result.get("summary", {}).get("biomarker_labeling_count") or 0)
        + int(fda_result.get("summary", {}).get("association_count") or 0)
    )
    stored_source_evidence_count = _stored_source_evidence_count(stored_research)
    total_source_evidence_count = public_evidence_count + stored_source_evidence_count
    total_sample_evidence_count = sample_match_count + star_marker_match_count + stored_sample_evidence_count + user_sample_evidence_count
    sample_context_requested = bool(sample_context_requested or total_sample_evidence_count)
    clinical_context_requested = bool(sample_context_requested or clinical_context.get("provided"))
    source_availability = _source_availability(
        clinpgx_result=clinpgx_result,
        pgxdb_result=pgxdb_result,
        fda_result=fda_result,
        stored_research=stored_research,
        live_public_evidence_count=public_evidence_count,
        stored_source_evidence_count=stored_source_evidence_count,
    )
    status = _medication_review_status(
        source_evidence_count=total_source_evidence_count,
        source_availability=source_availability,
    )
    readiness = _readiness(
        source_evidence_count=total_source_evidence_count,
        sample_match_count=sample_match_count,
        star_marker_match_count=star_marker_match_count,
        stored_sample_evidence_count=stored_sample_evidence_count,
        user_sample_evidence_count=user_sample_evidence_count,
        rsid_targets=rsid_targets,
        star_genes=star_genes,
        star_allele_calls=star_allele_calls,
        clinpgx_result=clinpgx_result,
        sample_context_requested=sample_context_requested,
    )
    answer_support = _answer_support(
        source_evidence_count=total_source_evidence_count,
        stored_sample_evidence_count=stored_sample_evidence_count,
        user_provided_sample_evidence=user_provided_sample_evidence,
        technical_support_count=technical_support_count,
        sequencing_sample_match_count=sequencing_sample_match_count,
        clinpgx_result=clinpgx_result,
        pgxdb_result=pgxdb_result,
        fda_result=fda_result,
        stored_research=stored_research,
        sample_lookups=sample_lookups,
        star_allele_calls=star_allele_calls,
    )
    evidence_components = _evidence_components(
        selected_drug=selected_drug,
        atc_code=atc_code,
        drugbank_id=drugbank_id,
        source_evidence_count=total_source_evidence_count,
        live_public_evidence_count=public_evidence_count,
        stored_source_evidence_count=stored_source_evidence_count,
        sample_match_count=sample_match_count,
        stored_sample_evidence_count=stored_sample_evidence_count,
        user_sample_evidence_count=user_sample_evidence_count,
        technical_support_count=technical_support_count,
        sequencing_sample_match_count=sequencing_sample_match_count,
        active_genome_index_context_available=active_genome_index_context_available,
        star_marker_match_count=star_marker_match_count,
        rsid_targets=rsid_targets,
        star_genes=star_genes,
        supported_star_marker_coverage=readiness["supported_star_marker_coverage"],
        sample_context_requested=sample_context_requested,
        clinpgx_result=clinpgx_result,
        pgxdb_result=pgxdb_result,
        fda_result=fda_result,
        clinical_context=clinical_context,
    )
    target_inventory = _target_inventory(
        drug=selected_drug,
        gene=selected_gene,
        rsid_targets=rsid_targets,
        star_genes=star_genes,
        star_allele_calls=star_allele_calls,
        public_evidence_count=total_source_evidence_count,
        sample_lookups=sample_lookups,
        technical_support_count=technical_support_count,
        active_genome_index_context_available=active_genome_index_context_available,
    )
    unanswered_answer_components = _unanswered_answer_components(
        evidence_components=evidence_components,
        clinical_context_requested=clinical_context_requested,
    )
    evidence_state = _evidence_state(
        source_evidence_count=total_source_evidence_count,
        sample_evidence_count=total_sample_evidence_count,
        live_public_evidence_count=public_evidence_count,
        stored_source_evidence_count=stored_source_evidence_count,
        sample_match_count=sample_match_count,
        star_marker_match_count=star_marker_match_count,
        stored_sample_evidence_count=stored_sample_evidence_count,
        user_sample_evidence_count=user_sample_evidence_count,
        technical_support_count=technical_support_count,
        sequencing_sample_match_count=sequencing_sample_match_count,
        source_availability=source_availability,
        sample_context_requested=sample_context_requested,
        clinical_context=clinical_context,
        unanswered_answer_components=unanswered_answer_components,
    )
    record_research_payloads = _source_record_research_payloads(clinpgx_result, pgxdb_result, fda_result)
    evidence_items = _evidence_matrix(
        clinpgx_result=clinpgx_result,
        pgxdb_result=pgxdb_result,
        fda_result=fda_result,
        stored_research=stored_research,
        sample_lookups=sample_lookups,
        star_allele_calls=star_allele_calls,
        user_provided_sample_evidence=user_provided_sample_evidence,
    )
    evidence_matrix_traceability = _evidence_matrix_traceability(evidence_items)
    semantic_usage = _pgx_semantic_usage(
        semantic,
        raw_drug=raw_drug,
        selected_drug=selected_drug,
        selected_gene=selected_gene,
        selected_rsid=selected_rsid,
        source_evidence_count=total_source_evidence_count,
        rsid_targets=rsid_targets,
        star_genes=star_genes,
    )
    pgx_evidence_scope = _evidence_envelope(
        query={
            "drug": selected_drug,
            "gene": selected_gene,
            "rsid": selected_rsid,
            "atc_code": atc_code,
            "drugbank_id": drugbank_id,
            "genome_build": genome_build,
        },
        source_availability=source_availability,
        evidence_components=evidence_components,
        evidence_state=evidence_state,
        evidence_matrix_traceability=evidence_matrix_traceability,
        sample_context_requested=sample_context_requested,
        clinical_context_requested=clinical_context_requested,
    )
    pgx_candidate_evidence = _pgx_candidate_evidence_view(
        query={
            "drug": selected_drug,
            "gene": selected_gene,
            "rsid": selected_rsid,
            "atc_code": atc_code,
            "drugbank_id": drugbank_id,
            "genome_build": genome_build,
        },
        source_evidence_count=total_source_evidence_count,
        sample_evidence_count=total_sample_evidence_count,
        public_evidence_count=public_evidence_count,
        stored_source_evidence_count=stored_source_evidence_count,
        user_sample_evidence_count=user_sample_evidence_count,
        technical_support_count=technical_support_count,
        status=status,
        unanswered_answer_components=unanswered_answer_components,
        source_availability=source_availability,
    )
    payload = {
        "schema": "genomi-pgx-medication-review-v1",
        "ok": status == "completed",
        "status": status,
        "unanswered_answer_components": unanswered_answer_components,
        "query": {
            "drug": selected_drug,
            "raw_drug": raw_drug if raw_drug != selected_drug else None,
            "gene": selected_gene,
            "rsid": selected_rsid,
            "atc_code": atc_code,
            "drugbank_id": drugbank_id,
            "genome_build": genome_build,
        },
        "semantic_context": semantic_usage,
        "clinical_context": clinical_context,
        "public_evidence": {
            "clinpgx": _compact_public_source_result(clinpgx_result),
            "pgxdb": _compact_public_source_result(pgxdb_result),
            "fda_pgx": _compact_public_source_result(fda_result),
            "stored_research": stored_research,
            "source_availability": source_availability,
            "source_evidence_count": total_source_evidence_count,
            "live_public_evidence_count": public_evidence_count,
            "stored_source_evidence_count": stored_source_evidence_count,
        },
        "sample_evidence": {
            "sample_context_requested": sample_context_requested,
            "rsid_targets": rsid_targets,
            "lookup_count": len(sample_lookups),
            "sample_match_count": sample_match_count,
            "stored_sample_evidence_count": stored_sample_evidence_count,
            "user_provided_sample_evidence_count": user_sample_evidence_count,
            "total_sample_evidence_count": total_sample_evidence_count,
            "technical_support_count": technical_support_count,
            "sequencing_sample_match_count": sequencing_sample_match_count,
            "active_genome_index_context_available": active_genome_index_context_available,
            "variant_lookups": sample_lookups,
            "user_provided_sample_evidence": user_provided_sample_evidence,
            "star_gene_targets": star_genes,
            "star_allele_call_count": len(star_allele_calls),
            "star_marker_match_count": star_marker_match_count,
            "star_allele_calls": star_allele_calls,
        },
        "evidence_matrix": {
            "schema": "genomi-pgx-evidence-matrix-v1",
            "item_count": len(evidence_items),
            "role_counts": _evidence_item_role_counts(evidence_items),
            "traceability": evidence_matrix_traceability,
            "items": evidence_items,
        },
        "pgx_evidence_scope": pgx_evidence_scope,
        "evidence_state": evidence_state,
        "interpretation_readiness": readiness,
        "answer_support": answer_support,
        "evidence_components": evidence_components,
        "target_inventory": target_inventory,
        "traceability": {
            "public_sources": [
                clinpgx_result.get("source"),
                pgxdb_result.get("source"),
                fda_result.get("source"),
            ],
            "source_availability": source_availability,
            "stored_research": stored_research.get("traceability", {}),
            "external_calls": [
                *list(clinpgx_result.get("raw_calls") or []),
                *list(pgxdb_result.get("raw_calls") or []),
                *list(fda_result.get("raw_calls") or []),
            ],
            "record_research_payload_count": len(record_research_payloads),
            "record_research_payload_role_counts": _record_research_payload_role_counts(record_research_payloads),
            "record_research_payload_summaries": _record_research_payload_summaries(record_research_payloads),
            "evidence_matrix_item_count": len(evidence_items),
            "evidence_matrix_role_counts": _evidence_item_role_counts(evidence_items),
            "evidence_matrix_traceability": evidence_matrix_traceability,
            "pgx_evidence_scope": pgx_evidence_scope,
            **(
                {"record_research_payloads": record_research_payloads}
                if include_record_research_payloads
                else {}
            ),
        },
    }
    pgx_envelope = _build_pgx_envelope(
        query=payload["query"],
        pgx_evidence_scope=pgx_evidence_scope,
        evidence_state=evidence_state,
        sample_context_requested=sample_context_requested,
        clinical_context_requested=clinical_context_requested,
        unanswered_answer_components=unanswered_answer_components,
        source_availability=source_availability,
    )
    return apply_evidence_view(
        payload,
        pgx_candidate_evidence,
        operation="pharmacogenomics.review_medication",
        envelope=pgx_envelope,
    )


def _build_pgx_envelope(
    *,
    query: JsonObject,
    pgx_evidence_scope: JsonObject,
    evidence_state: JsonObject,
    sample_context_requested: bool,
    clinical_context_requested: bool,
    unanswered_answer_components: Any,
    source_availability: JsonObject,
) -> JsonObject:
    sources = source_availability.get("sources") or []
    consulted = [str(item.get("source_id")) for item in sources if item.get("source_id") and item.get("availability") not in {"unavailable", "source_unavailable"}]
    unavailable = [str(item.get("source_id")) for item in sources if item.get("availability") in {"unavailable", "source_unavailable"}]
    coverage = _env._coverage(consulted_sources=consulted, unavailable_sources=unavailable)
    observations = {
        "source_evidence_count": evidence_state.get("source_evidence_count"),
        "sample_evidence_count": evidence_state.get("sample_evidence_count"),
        "evidence_matrix_item_count": pgx_evidence_scope.get("checked", {}).get("evidence_matrix_item_count"),
        "unresolved_components": pgx_evidence_scope.get("unresolved_components"),
    }
    personal_context = _env._personal_context(uses_personal_dna=bool(sample_context_requested))
    scope_payload = {
        "drug": query.get("drug"),
        "gene": query.get("gene"),
        "rsid": query.get("rsid"),
        "atc_code": query.get("atc_code"),
        "drugbank_id": query.get("drugbank_id"),
        "genome_build": query.get("genome_build"),
        "sample_context_requested": sample_context_requested,
        "clinical_context_requested": clinical_context_requested,
    }
    pgx_status = pgx_evidence_scope.get("status")
    has_public = bool(evidence_state.get("has_public_pgx_evidence"))
    has_sample = bool(evidence_state.get("has_sample_pgx_evidence"))
    if pgx_status == "source_unavailable":
        return _env.not_assessed(
            operation="pharmacogenomics.review_medication",
            reason="All consulted PGx sources were unavailable.",
            query_scope=scope_payload,
            personal_context=personal_context,
            coverage=coverage,
            observations=observations,
        )
    if not has_public and not has_sample:
        return _env.empty_consulted_scope(
            operation="pharmacogenomics.review_medication",
            query_scope=scope_payload,
            personal_context=personal_context,
            coverage=coverage,
            observations=observations,
        )
    answer_readiness = _env.NEEDS_CLINICAL_CONFIRMATION if (clinical_context_requested and has_public) else _env.SCOPED_ANSWER_ONLY
    return _env.evidence_present(
        operation="pharmacogenomics.review_medication",
        query_scope=scope_payload,
        personal_context=personal_context,
        coverage=coverage,
        observations=observations,
        answer_readiness=answer_readiness,
    )


def _pgx_candidate_evidence_view(
    *,
    query: JsonObject,
    source_evidence_count: int,
    sample_evidence_count: int,
    public_evidence_count: int,
    stored_source_evidence_count: int,
    user_sample_evidence_count: int,
    technical_support_count: int,
    status: str,
    unanswered_answer_components: Any,
    source_availability: JsonObject,
) -> JsonObject:
    row = _pgx_candidate_row(
        query=query,
        source_evidence_count=source_evidence_count,
        sample_evidence_count=sample_evidence_count,
        public_evidence_count=public_evidence_count,
        stored_source_evidence_count=stored_source_evidence_count,
        user_sample_evidence_count=user_sample_evidence_count,
        technical_support_count=technical_support_count,
        status=status,
        unanswered_answer_components=unanswered_answer_components,
        source_availability=source_availability,
    )
    matrix = [row]
    selected = row if row["score"] > 0 else None
    if selected is not None:
        selected["rank"] = 1
    decision_policy = {
        "policy_id": "pgx_medication_review_candidate_matrix_v1",
        "ranking_order": [
            "selected medication target",
            "traceable public PGx source evidence",
            "selected sample or user-provided PGx evidence",
            "technical support and unresolved components",
        ],
        "rule": "PGx review exposes a bounded evidence candidate for the selected medication target; it does not make prescribing decisions.",
    }
    return evidence_view(
        task_profile=PGX_MEDICATION_REVIEW,
        query=query,
        candidate_matrix=matrix,
        top_observed_candidate=selected,
        evidence_policy=decision_policy,
        warnings=_pgx_candidate_warnings(row, unanswered_answer_components, source_availability),
    )


def _pgx_candidate_row(
    *,
    query: JsonObject,
    source_evidence_count: int,
    sample_evidence_count: int,
    public_evidence_count: int,
    stored_source_evidence_count: int,
    user_sample_evidence_count: int,
    technical_support_count: int,
    status: str,
    unanswered_answer_components: JsonObject,
    source_availability: JsonObject,
) -> JsonObject:
    candidate_id = _pgx_candidate_id(query)
    if source_evidence_count and sample_evidence_count:
        best_lane = DIRECT_SOURCE_MATCH
        score = 1.0 if status == "completed" and not unanswered_answer_components else 0.85
        reason = "selected medication target has public PGx source evidence and selected sample-side evidence"
    elif source_evidence_count:
        best_lane = EXACT_TRAIT_MATCH
        score = 0.7
        reason = "selected medication target has public PGx source evidence without sample-side PGx evidence"
    elif sample_evidence_count:
        best_lane = SAME_GENE_OR_LOCUS
        score = 0.55
        reason = "selected medication target has sample-side PGx evidence without matching public source evidence"
    elif public_evidence_count or stored_source_evidence_count:
        best_lane = NEARBY_TRAIT_MATCH
        score = 0.35
        reason = "selected medication target has partial source context"
    else:
        best_lane = None
        score = 0.0
        reason = "no source-supported PGx evidence was found for the selected target"
    lanes = empty_lanes()
    if best_lane:
        lanes[best_lane] = lane(
            best_lane,
            status="present",
            score=score,
            source="PGx evidence review",
            matched_text=reason,
            source_id=candidate_id,
            note=reason,
        )
    return {
        "candidate_id": candidate_id,
        "candidate_type": PGX_MEDICATION_REVIEW.candidate_type,
        "rank": None,
        "score": score,
        "evidence_support_level": evidence_support_level_for_score(score),
        "answerability": answerability_for_lane(best_lane),
        "best_evidence_lane": best_lane,
        "evidence_lanes": lanes,
        "supporting_evidence": [
            {
                "source_evidence_count": source_evidence_count,
                "public_evidence_count": public_evidence_count,
                "stored_source_evidence_count": stored_source_evidence_count,
                "sample_evidence_count": sample_evidence_count,
                "user_sample_evidence_count": user_sample_evidence_count,
                "technical_support_count": technical_support_count,
                "source_availability_status": source_availability.get("status"),
            }
        ],
        "counter_evidence": _pgx_unanswered_counter_evidence(unanswered_answer_components),
        "why_not_selected": [] if score > 0 else ["No PGx source-supported candidate evidence was available for the selected target."],
    }


def _pgx_candidate_id(query: JsonObject) -> str:
    parts = [
        str(query.get("drug") or "drug_unspecified"),
        str(query.get("gene") or "gene_unspecified"),
        str(query.get("rsid") or query.get("atc_code") or query.get("drugbank_id") or "variant_unspecified"),
    ]
    return "pgx:" + "|".join(parts)


def _pgx_unanswered_counter_evidence(unanswered_answer_components: Any) -> list[JsonObject]:
    if isinstance(unanswered_answer_components, dict):
        return [
            {"type": key, "state": value.get("state"), "missing": value.get("missing_inputs")}
            for key, value in unanswered_answer_components.items()
            if isinstance(value, dict)
        ]
    if isinstance(unanswered_answer_components, list):
        return [
            {
                "type": str(item.get("component") or item.get("type") or "unanswered_component"),
                "state": item.get("state"),
                "missing": item.get("missing_inputs") or item.get("missing"),
            }
            for item in unanswered_answer_components
            if isinstance(item, dict)
        ]
    return []


def _pgx_candidate_warnings(row: JsonObject, unanswered_answer_components: Any, source_availability: JsonObject) -> list[str]:
    warnings = []
    if row["score"] <= 0:
        warnings.append("No source-supported PGx candidate evidence was available for the selected medication target.")
    if unanswered_answer_components:
        warnings.append("Some PGx evidence components remain unresolved; inspect unanswered_answer_components before synthesis.")
    if source_availability.get("status") == "source_unavailable":
        warnings.append("One or more live PGx public sources were unavailable.")
    return warnings


def _clinical_context(
    *,
    indication: str | None,
    dose: str | None,
    current_medications: str | None,
    allergies_or_contraindications: str | None,
) -> JsonObject:
    values = {
        "indication": _clean(indication),
        "dose": _clean(dose),
        "current_medications": _clean(current_medications),
        "allergies_or_contraindications": _clean(allergies_or_contraindications),
    }
    missing = [key for key, value in values.items() if not value]
    return {
        "provided": {key: value for key, value in values.items() if value},
        "missing": missing,
        "status": "provided" if not missing else "partial",
    }


def _user_provided_sample_pgx_evidence(
    *,
    selected_gene: str | None,
    selected_rsid: str | None,
    rsid_targets: list[str],
    star_genes: list[str],
    known_genotype: str | None,
    known_diplotype: str | None,
    known_phenotype: str | None,
    known_activity_score: str | None,
    known_pgx_source: str | None,
) -> list[JsonObject]:
    genotype = _clean(known_genotype)
    diplotype = _clean(known_diplotype)
    phenotype = _clean(known_phenotype)
    activity_score = _clean(known_activity_score)
    pgx_source = _clean(known_pgx_source)
    if not any([genotype, diplotype, phenotype, activity_score]):
        return []

    gene_target = selected_gene or _single_value(star_genes)
    rsid_target = selected_rsid or _single_value(rsid_targets)
    gene_level_fact = bool(diplotype or phenotype or activity_score)
    if gene_level_fact and not gene_target:
        return []
    if not gene_target and not rsid_target:
        return []

    evidence: JsonObject = {
        "source": "user_provided",
        "evidence_class": "user_provided_sample_pgx_evidence",
        "status": "user_provided_unverified",
        "clinical_boundary": "informational_evidence_review_requires_independent_confirmation",
    }
    if gene_target:
        evidence["target_type"] = "gene"
        evidence["gene"] = gene_target
    else:
        evidence["target_type"] = "variant"
    if rsid_target:
        evidence["rsid"] = rsid_target
    if genotype:
        evidence["known_genotype"] = genotype
    if diplotype:
        evidence["known_diplotype"] = diplotype
    if phenotype:
        evidence["known_phenotype"] = phenotype
    if activity_score:
        evidence["known_activity_score"] = activity_score
    if pgx_source:
        evidence["known_pgx_source"] = pgx_source
    return [evidence]


def _known_sample_fact_count(
    *,
    known_genotype: str | None,
    known_diplotype: str | None,
    known_phenotype: str | None,
    known_activity_score: str | None,
    known_pgx_source: str | None,
) -> int:
    del known_pgx_source
    return sum(
        1
        for value in [known_genotype, known_diplotype, known_phenotype, known_activity_score]
        if _clean(value)
    )
