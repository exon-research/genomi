from __future__ import annotations

from typing import Any

from ..runtime.libraries import manager as library_manager

SOURCE_HOME_URLS = {
    "clinvar": "https://www.ncbi.nlm.nih.gov/clinvar/",
    "gnomad": library_manager.source_url("gnomad"),
    "clingen_gene_validity": "https://search.clinicalgenome.org/kb/gene-validity",
    "gencc": "https://search.thegencc.org/",
    "genereviews": "https://www.ncbi.nlm.nih.gov/books/NBK1116/",
    "hpo": "https://hpo.jax.org/",
    "mondo": "https://mondo.monarchinitiative.org/",
    "orphanet": "https://www.orpha.net/",
    "omim": "https://www.omim.org/",
    "genecards": "https://www.genecards.org/",
    "malacards": "https://www.malacards.org/",
    "nci_cancer_genetics": "https://www.cancer.gov/about-cancer/causes-prevention/genetics",
    "cosmic_cancer_gene_census": "https://www.cosmickb.org/knowledgebase/cosmic-modules/",
    "opentargets": library_manager.source_url("opentargets"),
    "chembl": "https://www.ebi.ac.uk/chembl/",
    "drugbank": "https://go.drugbank.com/",
    "pharmaprojects": "https://pharmaintelligence.informa.com/products-and-services/data-and-analysis/pharmaprojects",
    "cpic": "https://cpicpgx.org/guidelines/",
    "pharmgkb": "https://www.pharmgkb.org/",
    "pgxdb": "https://pgx-db.org/",
    "fda_pharmacogenomics": "https://www.fda.gov/drugs/science-and-research-drugs/table-pharmacogenomic-biomarkers-drug-labeling",
    "fda_pharmacogenetic_associations": "https://www.fda.gov/medical-devices/precision-medicine/table-pharmacogenetic-associations",
    "gwas_catalog": library_manager.source_url("gwas-catalog"),
    "functional_genomics_perturbation_source": library_manager.source_url("biogrid-orcs"),
    "pubmed_or_primary_literature": "https://pubmed.ncbi.nlm.nih.gov/",
}


PUBLIC_EVIDENCE_SOURCES: list[dict[str, Any]] = [
    {
        "source_id": "clinvar",
        "title": "ClinVar",
        "target_types": ["variant", "gene", "condition"],
        "evidence_types": ["clinical_assertion", "review_status", "condition_assertion"],
        "adapter_status": "implemented_local_import",
        "genomi_operations": ["genomi.parse_source", "clinvar.match_variants", "clinvar.scan_candidates"],
        "best_for": "Exact variant clinical assertions and condition labels.",
        "limitations": ["labels need canonical parsing", "conflicts and low-penetrance labels need downgrade context"],
    },
    {
        "source_id": "gnomad",
        "title": "gnomAD",
        "target_types": ["variant"],
        "evidence_types": ["population_frequency", "homozygote_context"],
        "adapter_status": "implemented_api_fetch",
        "genomi_operations": ["variant.resolve", "gnomad.fetch_population_frequency", "variant.gather_allele_context"],
        "best_for": "Public allele frequency and homozygote context for exact normalized alleles.",
        "limitations": ["population frequency context", "dataset/build compatibility matters"],
    },
    {
        "source_id": "clingen_gene_validity",
        "title": "ClinGen Gene-Disease Validity",
        "target_types": ["gene", "condition"],
        "evidence_types": ["gene_disease_validity", "inheritance", "mechanism"],
        "adapter_status": "record_via_research",
        "genomi_operations": ["research.record", "research.query"],
        "best_for": "Whether a gene is validly associated with a disease and under what inheritance model.",
        "limitations": ["gene-level evidence must be connected back to specific sample variant evidence"],
    },
    {
        "source_id": "gencc",
        "title": "GenCC",
        "target_types": ["gene", "condition"],
        "evidence_types": ["gene_disease_validity", "inheritance"],
        "adapter_status": "implemented_public_tsv_download",
        "genomi_operations": ["phenotype.retrieve_gene_disease_associations", "phenotype.compare_disease_evidence", "research.record", "research.query"],
        "best_for": "Primary gene-disease validity assertions used as the disease-candidate universe before phenotype/HPO comparison.",
        "limitations": ["GenCC download excludes OMIM source data because of licensing; gene-level validity must be connected back to exact variant evidence"],
    },
    {
        "source_id": "genereviews",
        "title": "GeneReviews",
        "target_types": ["gene", "condition"],
        "evidence_types": ["clinical_review", "inheritance", "management_context"],
        "adapter_status": "record_via_research",
        "genomi_operations": ["research.record", "research.query", "variant.gather_gene_context"],
        "best_for": "Readable disease mechanism, inheritance, penetrance, and clinical context.",
        "limitations": ["review text is exact variant evidence when it names the allele"],
    },
    {
        "source_id": "hpo",
        "title": "Human Phenotype Ontology",
        "target_types": ["condition", "gene", "topic"],
        "evidence_types": ["phenotype_term", "phenotype_synonym", "phenotype_overlap"],
        "adapter_status": "implemented_local_normalization",
        "genomi_operations": [
            "phenotype.normalize_terms",
            "phenotype.compare_disease_evidence",
            "phenotype.compare_gene_hpo_evidence",
        ],
        "best_for": "Normalizing phenotype terms and HPO identifiers before disease or gene prioritization.",
        "limitations": ["phenotype overlap is not diagnostic by itself", "term normalization needs curated source review when text is ambiguous"],
    },
    {
        "source_id": "mondo",
        "title": "MONDO Disease Ontology",
        "target_types": ["condition", "gene", "topic"],
        "evidence_types": ["disease_normalization", "disease_synonym", "ontology_lineage"],
        "adapter_status": "record_via_research",
        "genomi_operations": ["phenotype.compare_disease_evidence", "phenotype.compare_gene_hpo_evidence", "research.record"],
        "best_for": "Disease identifier and synonym context for phenotype-to-disease review.",
        "limitations": ["source review is needed until a local ontology import is added"],
    },
    {
        "source_id": "orphanet",
        "title": "Orphanet",
        "target_types": ["condition", "gene", "topic"],
        "evidence_types": ["rare_disease", "phenotype_association", "gene_disease_context"],
        "adapter_status": "record_via_research",
        "genomi_operations": ["phenotype.compare_disease_evidence", "phenotype.compare_gene_hpo_evidence", "research.record"],
        "best_for": "Rare disease phenotype, inheritance, and gene association context.",
        "limitations": ["reviewed disease/source records are required before strong ranking claims"],
    },
    {
        "source_id": "omim",
        "title": "OMIM",
        "target_types": ["condition", "gene", "topic"],
        "evidence_types": ["mendelian_disease", "gene_disease_context", "inheritance"],
        "adapter_status": "record_via_research",
        "genomi_operations": ["phenotype.compare_disease_evidence", "phenotype.compare_gene_hpo_evidence", "research.record"],
        "best_for": "Mendelian disease and gene-phenotype relationship context when the user or source provides an OMIM target.",
        "limitations": ["access and licensing constraints mean findings should be stored as reviewed source summaries"],
    },
    {
        "source_id": "genecards",
        "title": "GeneCards",
        "target_types": ["gene", "condition", "topic"],
        "evidence_types": ["gene_function", "disease_association_context", "pathway_context", "alias_context"],
        "adapter_status": "record_via_research",
        "genomi_operations": ["phenotype.plan_risk_investigation", "research.record", "research.query"],
        "best_for": "Gene-centric context, aliases, pathway/function summaries, and disease-association triage before cross-checking clinical-validity sources.",
        "limitations": [
            "integrative context is not exact sample evidence",
            "clinical or personal-risk claims need ClinVar, ClinGen, GenCC, GeneReviews, population, and sample-support checks",
        ],
    },
    {
        "source_id": "malacards",
        "title": "MalaCards",
        "target_types": ["condition", "gene", "topic"],
        "evidence_types": ["disease_summary", "rare_disease_context", "associated_genes", "phenotype_context"],
        "adapter_status": "record_via_research",
        "genomi_operations": ["phenotype.plan_risk_investigation", "research.record", "research.query"],
        "best_for": "Disease-centric context for rare, genetic, and complex disorders, including associated genes and phenotype terms.",
        "limitations": [
            "disease-card associations require gene-disease validity cross-checks",
            "not a diagnostic source by itself",
        ],
    },
    {
        "source_id": "nci_cancer_genetics",
        "title": "NCI Cancer Genetics",
        "target_types": ["condition", "gene", "topic"],
        "evidence_types": ["hereditary_cancer_context", "genetic_testing_context", "clinical_counseling_context"],
        "adapter_status": "record_via_research",
        "genomi_operations": ["phenotype.plan_risk_investigation", "research.record", "research.query"],
        "best_for": "Public hereditary cancer background, germline versus acquired cancer genetics, and genetic-counseling context.",
        "limitations": [
            "general education pages do not classify a specific allele",
            "personal risk claims need exact variant and clinical context",
        ],
    },
    {
        "source_id": "cosmic_cancer_gene_census",
        "title": "COSMIC Cancer Gene Census",
        "target_types": ["gene", "condition", "topic"],
        "evidence_types": ["cancer_gene_role", "somatic_cancer_gene_context", "oncogene_tumor_suppressor_context"],
        "adapter_status": "record_via_research",
        "genomi_operations": ["phenotype.plan_risk_investigation", "research.record", "research.query"],
        "best_for": "Cancer-gene role and mechanism context, especially whether a gene is implicated in cancer biology.",
        "limitations": [
            "somatic cancer-gene roles are separate from inherited germline risk",
            "licensing and login requirements can affect direct review",
        ],
    },
    {
        "source_id": "cpic",
        "title": "CPIC",
        "target_types": ["drug", "gene", "variant"],
        "evidence_types": ["pharmacogenomic_guideline", "dosing_context", "phenotype_mapping"],
        "adapter_status": "implemented_api_fetch",
        "genomi_operations": ["pharmacogenomics.fetch_clinpgx", "research.record", "research.query"],
        "best_for": "Medication-specific pharmacogenomic guidance when a relevant genotype/phenotype is known.",
        "limitations": ["use diplotype/phenotype translation together with any intake-file allele evidence"],
    },
    {
        "source_id": "opentargets",
        "title": "Open Targets",
        "target_types": ["gene", "condition", "drug", "topic"],
        "evidence_types": ["target_disease_association", "variant_to_gene", "locus_to_gene", "clinical_drug_target", "drug_target_context", "tractability_context"],
        "adapter_status": "implemented_api_fetch_for_target_disease_and_clinical_drug_targets",
        "genomi_operations": [
            "phenotype.retrieve_disease_drug_targets",
            "phenotype.retrieve_trait_gene_records",
            "phenotype.compare_drug_target_evidence",
            "research.record",
            "research.query",
        ],
        "best_for": "Native target-disease association retrieval and disease-scoped clinical drug-target records; recorded evidence for variant-to-gene, locus-to-gene, and tractability context.",
        "limitations": ["target-disease association scores are evidence, not final causal-gene decisions", "direct DrugBank and ChEMBL table retrieval are separate coverage gaps"],
    },
    {
        "source_id": "quickgo_goa",
        "title": "QuickGO Gene Ontology Annotation",
        "target_types": ["gene", "topic"],
        "evidence_types": ["go_term_to_gene_relationship", "biological_process", "molecular_function", "cellular_component"],
        "adapter_status": "record_via_research",
        "genomi_operations": ["research.record", "research.query"],
        "best_for": "Controlled GO term to human gene-product relationship records with GO evidence codes and provenance.",
        "limitations": ["GO annotations are curated relationships, not causal-gene decisions", "free-text entity names require exact controlled-term resolution or disambiguation"],
    },
    {
        "source_id": "reactome",
        "title": "Reactome",
        "target_types": ["gene", "topic"],
        "evidence_types": ["pathway_to_gene_relationship", "pathway_participant"],
        "adapter_status": "implemented_api_fetch",
        "genomi_operations": ["pathway.retrieve_members", "research.record", "research.query"],
        "best_for": "Reactome pathway participant records for controlled human pathway entities.",
        "limitations": ["Pathway membership is relationship evidence, not a final answer", "drug knowledge-graph adapters are separate coverage gaps"],
    },
    {
        "source_id": "kegg",
        "title": "KEGG",
        "target_types": ["gene", "topic"],
        "evidence_types": ["compound_to_enzyme_gene_relationship"],
        "adapter_status": "record_via_research",
        "genomi_operations": ["research.record", "research.query"],
        "best_for": "KEGG compound to enzyme to human gene relationship records for controlled compound entities.",
        "limitations": ["Compound-enzyme links do not encode reaction direction", "ChEBI/HMDB chemical ontology and metabolite-protein adapters are separate coverage gaps"],
    },
    {
        "source_id": "human_protein_atlas",
        "title": "Human Protein Atlas",
        "target_types": ["gene", "topic"],
        "evidence_types": ["tissue_to_gene_expression_relationship", "cell_type_to_gene_expression_relationship"],
        "adapter_status": "implemented_api_fetch",
        "genomi_operations": ["cell_type.retrieve_markers", "research.record", "research.query"],
        "best_for": "Controlled tissue and single-cell type to gene expression-specificity records with HPA RNA specificity provenance.",
        "limitations": ["Expression specificity is relationship evidence, not causal mechanism", "direct GTEx and CellxGene adapters are separate coverage gaps"],
    },
    {
        "source_id": "chembl",
        "title": "ChEMBL",
        "target_types": ["gene", "drug", "condition", "topic"],
        "evidence_types": ["drug_target", "mechanism_of_action", "bioactivity"],
        "adapter_status": "implemented_api_fetch_for_drug_mechanism_targets",
        "genomi_operations": ["phenotype.compare_drug_target_evidence", "research.record", "research.query"],
        "best_for": "Native drug-to-target gene mechanism records and recorded drug-target evidence for candidate gene ranking.",
        "limitations": ["bioactivity is not the same as clinical indication support", "drug-to-target mechanism records are not disease-specific without indication context"],
    },
    {
        "source_id": "drugbank",
        "title": "DrugBank",
        "target_types": ["gene", "drug", "topic"],
        "evidence_types": ["drug_target", "drug_mechanism", "drug_class"],
        "adapter_status": "record_via_research",
        "genomi_operations": ["phenotype.compare_drug_target_evidence", "research.record", "research.query"],
        "best_for": "Drug-target and mechanism context when the user has a drug or drug class.",
        "limitations": ["access constraints can require source-reviewed summaries rather than direct adapter calls"],
    },
    {
        "source_id": "pharmaprojects",
        "title": "Pharmaprojects",
        "target_types": ["gene", "drug", "condition", "topic"],
        "evidence_types": ["drug_program", "drug_target", "indication_context"],
        "adapter_status": "record_via_research",
        "genomi_operations": ["phenotype.compare_drug_target_evidence", "research.record", "research.query"],
        "best_for": "Drug-program target and indication context from reviewed source records.",
        "limitations": ["access constraints require explicit reviewed source records"],
    },
    {
        "source_id": "pharmgkb",
        "title": "PharmGKB",
        "target_types": ["drug", "gene", "variant"],
        "evidence_types": ["pharmacogenomic_annotation", "guideline_link", "variant_drug_association"],
        "adapter_status": "implemented_api_fetch",
        "genomi_operations": ["pharmacogenomics.fetch_clinpgx", "pharmacogenomics.fetch_pgxdb", "research.record", "research.query"],
        "best_for": "Drug-gene-variant annotations and links to curated PGx guidelines.",
        "limitations": ["annotation levels differ; CPIC/FDA guideline strength should be kept separate"],
    },
    {
        "source_id": "pgxdb",
        "title": "PGxDB",
        "target_types": ["drug", "gene", "variant", "topic"],
        "evidence_types": ["pharmacogenomic_annotation", "drug_response", "variant_drug_association"],
        "adapter_status": "implemented_api_fetch",
        "genomi_operations": ["pharmacogenomics.fetch_pgxdb", "research.record", "research.query"],
        "best_for": "Drug-response evidence for selected drug, ATC code, DrugBank ID, gene, and rsID targets.",
        "limitations": ["drug or ATC context improves retrieval for PharmGKB association rows"],
    },
    {
        "source_id": "fda_pharmacogenomics",
        "title": "FDA Pharmacogenomic Biomarkers In Drug Labeling",
        "target_types": ["drug", "gene"],
        "evidence_types": ["drug_label_biomarker_context", "label_section_context", "actionability_context"],
        "adapter_status": "implemented_web_fetch",
        "genomi_operations": ["pharmacogenomics.fetch_fda_labels", "pharmacogenomics.fetch_clinpgx", "research.record", "research.query"],
        "best_for": "Whether FDA-approved labeling includes pharmacogenomic biomarker information for a selected drug or gene.",
        "limitations": ["label biomarker presence is separate from CPIC/DPWG prescribing recommendations"],
    },
    {
        "source_id": "fda_pharmacogenetic_associations",
        "title": "FDA Pharmacogenetic Associations",
        "target_types": ["drug", "gene"],
        "evidence_types": ["pharmacogenetic_association", "safety_context", "therapeutic_management_context"],
        "adapter_status": "implemented_web_fetch",
        "genomi_operations": ["pharmacogenomics.fetch_fda_labels", "research.list_sources", "research.record", "research.query"],
        "best_for": "Whether FDA has evaluated a drug-gene association as having sufficient scientific evidence for altered metabolism, safety, or therapeutic-effect context.",
        "limitations": ["label context and CPIC dosing recommendations are separate evidence classes"],
    },
    {
        "source_id": "gwas_catalog",
        "title": "GWAS Catalog",
        "target_types": ["variant", "gene", "condition", "topic"],
        "evidence_types": ["association", "risk_context", "trait_context"],
        "adapter_status": "implemented_api_fetch",
        "genomi_operations": ["gwas.compare_variant_associations", "gwas.compare_gene_associations", "research.record", "research.query"],
        "best_for": "Prioritizing candidate rsIDs or candidate genes under the GWAS Catalog association prior.",
        "limitations": [
            "association evidence is usually limited context for diagnosis or actionability",
            "sample genotype support still must come from active_genome_index.classify_genotype_support",
        ],
    },
    {
        "source_id": "functional_genomics_perturbation_source",
        "title": "Functional Genomics Perturbation Source Records",
        "target_types": ["gene", "topic"],
        "evidence_types": ["screen_hit", "perturbation_context", "assay_context", "candidate_gene_ranking"],
        "adapter_status": "implemented_native_retrieval_and_record_verification",
        "genomi_operations": [
            "functional_genomics.retrieve_perturbation_records",
            "functional_genomics.query_geo",
            "functional_genomics.import_perturbation_table",
            "functional_genomics.compare_gene_perturbation",
            "research.record",
            "research.query",
        ],
        "best_for": "Retrieving BioGRID ORCS, configured DepMap, bounded GEO table records, or verifying local/public perturbation source records before ranking candidate genes.",
        "limitations": [
            "BioGRID ORCS requires an access key",
            "DepMap retrieval requires a configured public CRISPR gene-effect release table",
            "GEO metadata-only matches are not direct perturbation evidence",
            "large GEO raw archives and binary assay files are skipped",
            "automatic discovery of journal supplementary tables is not integrated",
            "generic literature evidence should not be treated as direct perturbation support",
        ],
    },
    {
        "source_id": "pubmed_or_primary_literature",
        "title": "PubMed Or Primary Literature",
        "target_types": ["variant", "gene", "drug", "condition", "topic"],
        "evidence_types": ["primary_literature", "review_literature", "source_tension"],
        "adapter_status": "record_via_research",
        "genomi_operations": ["research.record", "research.query"],
        "best_for": "Filling focused evidence gaps after local structured sources are insufficient.",
        "limitations": ["agent must summarize narrowly and store source dates and exact finding excerpts"],
    },
]


def evidence_source_catalog(
    *,
    target_type: str | None = None,
    source_id: str | None = None,
) -> dict[str, Any]:
    target_type = target_type.strip().lower() if target_type else None
    source_id = source_id.strip().lower() if source_id else None
    sources = [
        _agent_source_contract(source)
        for source in PUBLIC_EVIDENCE_SOURCES
        if (target_type is None or target_type in source["target_types"])
        and (source_id is None or source_id == source["source_id"])
    ]
    return {
        "filters": {"target_type": target_type, "source_id": source_id},
        "summary": {"source_count": len(sources)},
        "sources": sources,
        "storage_contract": {
            "structured_local_sources": [
                "Use existing local adapters when adapter_status starts with implemented_.",
                "Use research.record for current web, guideline, database, or literature findings that use external review.",
            ],
            "record_research_target_types": ["variant", "gene", "drug", "condition", "topic"],
            "record_research_required_fields": [
                "target.type and target identifier",
                "source.title",
                "source.url",
                "source.accessed_at",
                "finding.text",
            ],
            "finding_text_rule": "Store a short exact excerpt or precise finding.",
        },
    }


def _agent_source_contract(source: dict[str, Any]) -> dict[str, Any]:
    source_id = str(source["source_id"])
    adapter_status = str(source["adapter_status"])
    contract: dict[str, Any] = {
        **source,
        "official_url": SOURCE_HOME_URLS.get(source_id),
        "agent_contract": {
            "query_mode": "implemented_operation" if adapter_status.startswith("implemented_") else "focused_source_review",
            "public_target_inputs": _public_target_inputs(source),
            "available_operations": list(source["genomi_operations"]),
            "record_with": "research.record",
            "record_scope": {
                "shared": "Reusable public-target findings such as guideline rows, variant assertions, gene validity, and source summaries.",
                "private": "User-specific combinations involving personal genotype, medication list, phenotype, family history, or interpretation.",
            },
            "reviewed_finding_shape": {
                "target": "type plus gene, drug, condition, topic, or normalized allele fields",
                "source": "title, url, accessed_at, optional published_at",
                "finding": "short exact excerpt or precise source-backed summary",
            },
        },
    }
    if adapter_status.startswith("implemented_"):
        contract["agent_contract"]["use_implemented_adapter_first"] = True
    else:
        contract["agent_contract"]["focused_review_steps"] = [
            "Use the selected public target to inspect the official source or primary literature.",
            "Extract only the finding needed for the user's question.",
            "Store the reviewed finding before interpretation or future reuse.",
        ]
    return contract


def _public_target_inputs(source: dict[str, Any]) -> list[str]:
    inputs = []
    for target_type in source.get("target_types", []):
        if target_type == "variant":
            inputs.extend(["rsID", "normalized allele"])
        elif target_type == "gene":
            inputs.append("gene")
        elif target_type == "drug":
            inputs.extend(["drug", "ATC code", "DrugBank ID"])
        elif target_type == "condition":
            inputs.append("condition")
        elif target_type == "topic":
            inputs.append("topic")
    return sorted(set(inputs))
