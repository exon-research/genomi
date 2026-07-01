from __future__ import annotations

from pathlib import Path

from ....evidence.candidate_evidence import apply_evidence_view
from ....retrieval import semantic as retrieval_semantic
from ...variant import variant_lookup
from .. import clinpgx, fda_pgx, pgx_star, pgxdb, pharmcat
from ..pgx_envelope import build_medication_review_envelope
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
from .medication_matrix import (
    build_medication_review_matrix,
    medication_review_evidence_view,
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
        else {"status": "not_checked", "operation": "pharmacogenomics.check_pharmcat"}
    )
    return {
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
                "purpose": "Broad AGI-derived PharmCAT diplotype, phenotype, and recommendation artifacts.",
                "operations": ["pharmacogenomics.preflight_pharmcat", "pharmacogenomics.prepare_outside_call_tsv", "pharmacogenomics.validate_outside_call_tsv", "pharmacogenomics.import_pharmcat_artifacts", "pharmacogenomics.check_pharmcat", "pharmacogenomics.run_pharmcat"],
                "runtime_status": pharmcat_status,
                "artifact_evidence": ["report JSON", "report HTML", "calls-only TSV", "match JSON", "phenotype JSON"],
                "traceability": "pharmacogenomics.preflight_pharmcat returns AGI-derived PharmCAT input facts; pharmacogenomics.import_pharmcat_artifacts parses existing artifacts; pharmacogenomics.run_pharmcat returns command provenance, version probe, input content hash, artifact list, parsed calls, and record_research_payloads.",
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
    source_sample_pgx_row_id: str | None = None,
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
        source_sample_pgx_row_id=source_sample_pgx_row_id,
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
    known_sample_pgx_evidence = _known_sample_pgx_evidence(
        selected_gene=selected_gene,
        selected_rsid=selected_rsid,
        rsid_targets=rsid_targets,
        star_genes=star_genes,
        known_genotype=known_genotype,
        known_diplotype=known_diplotype,
        known_phenotype=known_phenotype,
        known_activity_score=known_activity_score,
        known_pgx_source=known_pgx_source,
        source_sample_pgx_row_id=source_sample_pgx_row_id,
    )
    known_sample_pgx_evidence_count = len(known_sample_pgx_evidence)
    user_sample_evidence_count = _known_sample_pgx_source_count(known_sample_pgx_evidence, "user_provided")
    pharmcat_sample_pgx_evidence_count = _known_sample_pgx_source_count(
        known_sample_pgx_evidence,
        "pharmcat_sample_pgx_matrix",
    )
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
    total_sample_evidence_count = (
        sample_match_count
        + star_marker_match_count
        + stored_sample_evidence_count
        + known_sample_pgx_evidence_count
    )
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
        known_sample_pgx_evidence_count=known_sample_pgx_evidence_count,
        rsid_targets=rsid_targets,
        star_genes=star_genes,
        star_allele_calls=star_allele_calls,
        clinpgx_result=clinpgx_result,
        sample_context_requested=sample_context_requested,
    )
    answer_support = _answer_support(
        source_evidence_count=total_source_evidence_count,
        stored_sample_evidence_count=stored_sample_evidence_count,
        known_sample_pgx_evidence=known_sample_pgx_evidence,
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
        known_sample_pgx_evidence_count=known_sample_pgx_evidence_count,
        user_sample_evidence_count=user_sample_evidence_count,
        pharmcat_sample_pgx_evidence_count=pharmcat_sample_pgx_evidence_count,
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
        known_sample_pgx_evidence_count=known_sample_pgx_evidence_count,
        user_sample_evidence_count=user_sample_evidence_count,
        pharmcat_sample_pgx_evidence_count=pharmcat_sample_pgx_evidence_count,
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
        known_sample_pgx_evidence=known_sample_pgx_evidence,
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
    query = {
        "drug": selected_drug,
        "gene": selected_gene,
        "rsid": selected_rsid,
        "atc_code": atc_code,
        "drugbank_id": drugbank_id,
        "genome_build": genome_build,
    }
    medication_review_matrix = build_medication_review_matrix(
        query=query,
        evidence_items=evidence_items,
        sample_context_requested=sample_context_requested,
        interpretation_readiness=readiness,
    )
    pgx_candidate_evidence = medication_review_evidence_view(
        query=query,
        medication_review_matrix=medication_review_matrix,
        status=status,
        unanswered_answer_components=unanswered_answer_components,
        source_availability=source_availability,
    )
    payload = {
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
            "known_sample_pgx_evidence_count": known_sample_pgx_evidence_count,
            "user_provided_sample_evidence_count": user_sample_evidence_count,
            "pharmcat_sample_pgx_matrix_evidence_count": pharmcat_sample_pgx_evidence_count,
            "total_sample_evidence_count": total_sample_evidence_count,
            "technical_support_count": technical_support_count,
            "sequencing_sample_match_count": sequencing_sample_match_count,
            "active_genome_index_context_available": active_genome_index_context_available,
            "variant_lookups": sample_lookups,
            "known_sample_pgx_evidence": known_sample_pgx_evidence,
            "star_gene_targets": star_genes,
            "star_allele_call_count": len(star_allele_calls),
            "star_marker_match_count": star_marker_match_count,
            "star_allele_calls": star_allele_calls,
        },
        "evidence_matrix": {
            "item_count": len(evidence_items),
            "role_counts": _evidence_item_role_counts(evidence_items),
            "traceability": evidence_matrix_traceability,
            "items": evidence_items,
        },
        "medication_review_matrix": medication_review_matrix,
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
            **(
                {"record_research_payloads": record_research_payloads}
                if include_record_research_payloads
                else {}
            ),
        },
    }
    pgx_envelope = build_medication_review_envelope(
        query=payload["query"],
        evidence_state=evidence_state,
        evidence_matrix_traceability=evidence_matrix_traceability,
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


def _known_sample_pgx_evidence(
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
    source_sample_pgx_row_id: str | None,
) -> list[JsonObject]:
    genotype = _clean(known_genotype)
    diplotype = _clean(known_diplotype)
    phenotype = _clean(known_phenotype)
    activity_score = _clean(known_activity_score)
    pgx_source = _clean(known_pgx_source)
    sample_row_id = _clean(source_sample_pgx_row_id)
    if not any([genotype, diplotype, phenotype, activity_score]):
        return []

    gene_target = selected_gene or _single_value(star_genes)
    rsid_target = selected_rsid or _single_value(rsid_targets)
    gene_level_fact = bool(diplotype or phenotype or activity_score)
    if gene_level_fact and not gene_target:
        return []
    if not gene_target and not rsid_target:
        return []

    source = _known_sample_pgx_source(pgx_source=pgx_source, sample_row_id=sample_row_id)
    evidence: JsonObject = {
        "source": source,
        "evidence_class": _known_sample_pgx_evidence_class(source),
        "status": _known_sample_pgx_status(source),
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


def _known_sample_pgx_source(*, pgx_source: str | None, sample_row_id: str | None) -> JsonObject:
    if pgx_source == "pharmcat_sample_pgx_matrix" and sample_row_id:
        return {
            "source_id": "pharmcat_sample_pgx_matrix",
            "title": "PharmCAT sample PGx matrix",
            "source_sample_pgx_row_id": sample_row_id,
        }
    return {
        "source_id": "user_provided",
        "title": pgx_source,
    }


def _known_sample_pgx_evidence_class(source: JsonObject) -> str:
    if source.get("source_id") == "pharmcat_sample_pgx_matrix":
        return "pharmcat_sample_pgx_matrix_row"
    return "user_provided_sample_pgx_evidence"


def _known_sample_pgx_status(source: JsonObject) -> str:
    if source.get("source_id") == "pharmcat_sample_pgx_matrix":
        return "pharmcat_sample_pgx_matrix_observed"
    return "user_provided_unverified"


def _known_sample_pgx_source_count(evidence_items: list[JsonObject], source_id: str) -> int:
    return sum(
        1
        for item in evidence_items
        if isinstance(item.get("source"), dict) and item["source"].get("source_id") == source_id
    )


def _known_sample_fact_count(
    *,
    known_genotype: str | None,
    known_diplotype: str | None,
    known_phenotype: str | None,
    known_activity_score: str | None,
    known_pgx_source: str | None,
    source_sample_pgx_row_id: str | None,
) -> int:
    del known_pgx_source
    del source_sample_pgx_row_id
    return sum(
        1
        for value in [known_genotype, known_diplotype, known_phenotype, known_activity_score]
        if _clean(value)
    )
