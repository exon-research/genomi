from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

JsonObject = dict[str, object]
ParamsFactory = Callable[["MatrixCaseContext"], JsonObject]
ResultAssertion = Callable[[JsonObject, "MatrixCaseContext"], None]


@dataclass(frozen=True)
class MatrixCaseContext:
    tmp_path: Path

    def write_text(self, name: str, content: str) -> str:
        path = self.tmp_path / name
        path.write_text(content, encoding="utf-8")
        return str(path)


@dataclass(frozen=True)
class OperationCase:
    operation: str
    lane: str
    params: ParamsFactory
    assert_result: ResultAssertion


SOURCE_FORMAT_MATRIX_CAPABILITIES = frozenset(
    {
        "active-genome-index",
        "ancestry",
        "clinvar",
        "decode",
        "pharmacogenomics",
        "polygenic-score",
        "variant-evidence",
    }
)

SOURCE_FORMAT_MATRIX_SOURCE_FORMATS = frozenset(
    {
        "23andme",
        "ancestrydna",
        "bam",
        "fastq",
        "ftdna",
        "genome",
        "gvcf",
        "livingdna",
        "myheritage",
        "vcf",
    }
)
SOURCE_FORMAT_MATRIX_CAPABILITY_CELLS = frozenset(
    (source_format, capability)
    for source_format in SOURCE_FORMAT_MATRIX_SOURCE_FORMATS
    for capability in SOURCE_FORMAT_MATRIX_CAPABILITIES
)

PUBLIC_DETERMINISTIC_CAPABILITIES = frozenset(
    {
        "analytical-grounding",
        "functional-genomics",
        "nutrigenomics",
        "phenotype-gene",
        "sequence",
    }
)

EXTERNAL_SOURCE_CAPABILITIES = frozenset({"gnomad", "gwas-catalog"})
STATEFUL_RUNTIME_CAPABILITIES = frozenset({"genomi", "journal"})

SOURCE_FORMAT_MATRIX_OPERATIONS = frozenset(
    {
        "active_genome_index.summarize",
        "active_genome_index.classify_callset_qc",
        "active_genome_index.classify_genotype_support",
        "active_genome_index.classify_region_callability",
        "ancestry.check_sample_overlap",
        "ancestry.estimate_population_context",
        "ancestry.project_pca",
        "clinvar.match_variants",
        "clinvar.scan_candidates",
        "decode.render_dashboard",
        "pharmacogenomics.review_medication",
        "prs.calculate_score",
        "prs.check_score_overlap",
        "variant.resolve",
    }
)

SOURCE_FORMAT_SUPPORT_OPERATION_RATIONALES = {
    "active_genome_index.approve_access": "session authorization state",
    "active_genome_index.assign_user_genome": "session/user selection state",
    "active_genome_index.build_reference_pass": "source-format setup operation",
    "active_genome_index.clear_default_user": "session/user selection state",
    "active_genome_index.clear_selection": "session/user selection state",
    "active_genome_index.list": "Active Genome Index lifecycle metadata",
    "active_genome_index.remove": "Active Genome Index lifecycle cleanup",
    "active_genome_index.rename_user": "session/user selection state",
    "active_genome_index.revoke_access": "session authorization state",
    "active_genome_index.select_user": "session/user selection state",
    "active_genome_index.set_default_user": "session/user selection state",
    "ancestry.build_source_context": "source-format support metadata",
    "ancestry.list_reference_panels": "installed-reference library inventory",
    "decode.build_dashboard_evidence": "internal evidence builder behind decode.render_dashboard",
    "pharmacogenomics.check_pharmcat": "local PharmCAT installation state",
    "pharmacogenomics.describe_gene_requirements": "PGx source-format support metadata",
    "pharmacogenomics.import_pharmcat_artifacts": "artifact import setup for PharmCAT output",
    "pharmacogenomics.preflight_pharmcat": "source-format PharmCAT readiness check",
    "pharmacogenomics.prepare_outside_call_tsv": "PharmCAT input artifact preparation",
    "pharmacogenomics.run_pharmcat": "long-running PharmCAT execution over AGI-derived calls",
    "pharmacogenomics.validate_outside_call_tsv": "PharmCAT input artifact validation",
    "prs.build_source_context": "source-format support metadata",
    "prs.fetch_score_metadata": "PGS catalog/library metadata lookup",
    "prs.import_scoring_file": "score-library setup operation",
    "prs.list_imported_scores": "installed score-library inventory",
    "prs.search_scores": "PGS catalog/library metadata lookup",
    "variant.gather_allele_context": "source-format evidence packet over ClinVar matches",
    "variant.gather_gene_context": "source-format evidence packet over ClinVar matches",
}
SOURCE_FORMAT_SUPPORT_OPERATIONS = frozenset(SOURCE_FORMAT_SUPPORT_OPERATION_RATIONALES)

SOURCE_FORMAT_SUPPORT_EXECUTABLE_OPERATIONS = frozenset(
    {
        "active_genome_index.approve_access",
        "active_genome_index.assign_user_genome",
        "active_genome_index.clear_default_user",
        "active_genome_index.clear_selection",
        "active_genome_index.list",
        "active_genome_index.rename_user",
        "active_genome_index.revoke_access",
        "active_genome_index.select_user",
        "active_genome_index.set_default_user",
        "ancestry.build_source_context",
        "ancestry.list_reference_panels",
        "decode.build_dashboard_evidence",
        "pharmacogenomics.describe_gene_requirements",
        "pharmacogenomics.preflight_pharmcat",
        "pharmacogenomics.prepare_outside_call_tsv",
        "pharmacogenomics.validate_outside_call_tsv",
        "prs.build_source_context",
        "prs.list_imported_scores",
        "variant.gather_allele_context",
        "variant.gather_gene_context",
    }
)

EXTERNAL_SOURCE_OPERATION_RATIONALES = {
    "functional_genomics.query_geo": "live NCBI GEO query",
    "functional_genomics.retrieve_perturbation_records": "live public screen-source retrieval",
    "gnomad.fetch_population_frequency": "live gnomAD/static-population fetch",
    "gwas.compare_gene_associations": "live GWAS Catalog gene association query",
    "gwas.compare_variant_associations": "live GWAS Catalog variant association query",
    "pharmacogenomics.fetch_clinpgx": "live ClinPGx source fetch",
    "pharmacogenomics.fetch_fda_labels": "live FDA label source fetch",
    "pharmacogenomics.fetch_pgxdb": "live PGxDB source fetch",
    "phenotype.retrieve_disease_drug_targets": "live Open Targets drug-candidate query",
    "phenotype.retrieve_trait_gene_records": "live Open Targets trait-gene query",
}
EXTERNAL_SOURCE_OPERATIONS = frozenset(EXTERNAL_SOURCE_OPERATION_RATIONALES)
EXTERNAL_SOURCE_EXECUTABLE_OPERATIONS = EXTERNAL_SOURCE_OPERATIONS

STATEFUL_RUNTIME_OPERATION_RATIONALES = {
    "genomi.check_background_job": "background job polling state",
    "genomi.check_libraries": "installed library inventory state",
    "genomi.describe_context": "active session context",
    "genomi.install": "runtime installation mutation",
    "genomi.invoke": "dispatcher wrapper, not a capability behavior",
    "genomi.list_resources": "runtime resource inventory",
    "genomi.parse_source": "source-format setup operation",
    "genomi.search_indexes": "runtime metadata index search",
    "genomi.set_response_profile": "runtime profile mutation",
    "journal.append_entry": "journal store mutation",
    "journal.export_memory": "journal state export",
    "journal.search_entries": "journal state search",
    "journal.summarize": "journal state summary",
    "research.build_target_packet": "reviewed-research store orchestration",
    "research.list_sources": "source catalog inventory",
    "research.query": "reviewed-research store query",
    "research.record": "reviewed-research store mutation",
    "research.search": "reviewed-research store search",
}
STATEFUL_RUNTIME_OPERATIONS = frozenset(STATEFUL_RUNTIME_OPERATION_RATIONALES)
STATEFUL_RUNTIME_EXECUTABLE_OPERATIONS = STATEFUL_RUNTIME_OPERATIONS - {"genomi.install"}

def _empty_params(_ctx: MatrixCaseContext) -> JsonObject:
    return {}


def _pathway_params(ctx: MatrixCaseContext) -> JsonObject:
    return {
        "pathway_id_or_name": "G2M checkpoint",
        "source": "msigdb_hallmark",
        "msigdb_gmt": ctx.write_text("hallmark.gmt", "HALLMARK_G2M_CHECKPOINT\thttps://example.test/msigdb\tCDK1\tCCNB1\n"),
        "msigdb_version": "contract",
    }


def _cell_marker_params(ctx: MatrixCaseContext) -> JsonObject:
    return {
        "cell_type_id_or_name": "hepatocytes",
        "source": "cellmarker",
        "marker_table": ctx.write_text("markers.tsv", "cell_type\tgene_symbol\tmarker_strength\nhepatocytes\tALB\tstrong\n"),
    }


def _region_params(ctx: MatrixCaseContext) -> JsonObject:
    return {
        "region": "1:1150-1175",
        "assembly": "GRCh38",
        "gencode_gtf": ctx.write_text("gencode.gtf", 'chr1\tGENCODE\tgene\t1000\t1500\t.\t+\t.\tgene_id "ENSG1"; gene_name "GENE1";\n'),
        "encode_ccre_bed": ctx.write_text("ccre.bed", "chr1\t1149\t1300\tEH38E1\t0\t.\t1150\t1300\t255,0,0\tpromoter-like\n"),
    }


def _screen_import_params(ctx: MatrixCaseContext) -> JsonObject:
    return {
        "table": ctx.write_text(
            "screen.tsv",
            "symbol\tcell line\ttreatment\treadout\tscore\n"
            "EGFR\tA549\tDMSO\tresistance\t9.2\n"
            "MYC\tA549\tDMSO\tresistance\t1.1\n",
        ),
        "context": "A549 DMSO resistance screen",
        "genes": ["EGFR", "MYC"],
        "cell_line": "A549",
        "perturbation": "DMSO",
        "phenotype": "resistance",
        "source_title": "A549 DMSO resistance supplementary table",
    }


def _screen_compare_params(_ctx: MatrixCaseContext) -> JsonObject:
    return {
        "context": "A549 DMSO resistance screen",
        "genes": ["EGFR", "MYC"],
        "cell_line": "A549",
        "perturbation": "DMSO",
        "phenotype": "resistance",
        "search_stored_research": False,
        "retrieve_native": False,
        "source_records": [
            {
                "record_id": "screen-egfr",
                "source_type": "CRISPR screen",
                "source_title": "A549 resistance screen",
                "finding": "EGFR was the top resistance hit in an A549 perturbation screen.",
                "verified_fields": {
                    "genes": ["EGFR"],
                    "cell_line": "A549",
                    "perturbation": "DMSO",
                    "phenotype": "resistance",
                },
            }
        ],
    }


def _gwas_gene_params(_ctx: MatrixCaseContext) -> JsonObject:
    return {
        "phenotype": "LDL cholesterol",
        "genes": ["APOB", "PCSK9"],
    }


def _nutrigenomics_domain_params(_ctx: MatrixCaseContext) -> JsonObject:
    return {"domain_id": "folate_metabolism"}


def _nutrigenomics_variant_params(_ctx: MatrixCaseContext) -> JsonObject:
    return {"rsid": "rs1801133"}


def _disease_compare_params(_ctx: MatrixCaseContext) -> JsonObject:
    return {
        "phenotype_text": "hypertension hyperkalemia",
        "candidate_diseases": ["Gordon syndrome", "Other"],
        "search_stored_research": False,
        "use_hpo_annotations": False,
        "source_records": [
            {
                "record_id": "orphanet-gordon",
                "source_id": "orphanet",
                "source_type": "rare disease phenotype source",
                "source_title": "Orphanet Gordon syndrome",
                "finding": "Gordon syndrome is described with hypertension and hyperkalemia.",
                "verified_fields": {"diseases": ["Gordon syndrome"], "phenotypes": ["hypertension", "hyperkalemia"]},
            }
        ],
    }


def _drug_target_params(_ctx: MatrixCaseContext) -> JsonObject:
    return {
        "drug_class": "beta agonist",
        "genes": ["IL13", "ADRB2"],
        "search_stored_research": False,
        "source_records": [
            {
                "record_id": "chembl-adrb2",
                "source_id": "chembl",
                "source_type": "drug mechanism target",
                "source_title": "ChEMBL beta agonist mechanism",
                "finding": "Beta agonist source supports ADRB2 as a receptor target.",
                "verified_fields": {"genes": ["ADRB2"], "drug_classes": ["beta agonist"], "target_relationships": ["drug target"]},
            }
        ],
    }


def _gene_hpo_params(_ctx: MatrixCaseContext) -> JsonObject:
    return {
        "phenotypes": ["ataxia", "microcephaly"],
        "genes": ["PNKP"],
        "search_stored_research": False,
        "use_hpo_annotations": False,
        "source_records": [_phenotype_gene_source_record()],
    }


def _phenotype_normalize_params(_ctx: MatrixCaseContext) -> JsonObject:
    return {"text": "Ataxia; seizures; HP:0001250", "phenotypes": ["microcephaly"]}


def _risk_plan_params(_ctx: MatrixCaseContext) -> JsonObject:
    return {"question": "BRCA1 hereditary breast cancer risk", "gene": "BRCA1", "search_stored_research": False}


def _gene_disease_params(ctx: MatrixCaseContext) -> JsonObject:
    return {
        "genes": ["GENE1"],
        "gencc_file": _write_gencc_file(ctx),
    }


def _sequence_analyze_params(ctx: MatrixCaseContext) -> JsonObject:
    return {"sequence": "ATGAAATAA", "reference_fasta": _write_reference_fasta(ctx)}


def _primer_params(_ctx: MatrixCaseContext) -> JsonObject:
    return {"forward_primer": "ATGAAA", "reverse_primer": "CCCTTT", "template": "GGGATGAAATTTGGGAAAGGG"}


def _kozak_params(_ctx: MatrixCaseContext) -> JsonObject:
    return {"sequence": "CCACCATGG", "start_pos": 6}


def _orf_params(_ctx: MatrixCaseContext) -> JsonObject:
    return {"sequence": "CCCATGAAATAAGGG", "min_aa": 2, "strand": "forward"}


def _restriction_params(_ctx: MatrixCaseContext) -> JsonObject:
    return {"sequence": "TTTGAATTCGGATCC", "enzymes": ["EcoRI", "BamHI"]}


def _sequence_match_params(ctx: MatrixCaseContext) -> JsonObject:
    return {"sequence": "ATGAAATAA", "reference_fasta": _write_reference_fasta(ctx)}


def _translate_params(_ctx: MatrixCaseContext) -> JsonObject:
    return {"sequence": "ATGTAA"}


def _write_gencc_file(ctx: MatrixCaseContext) -> str:
    return ctx.write_text(
        "gencc.tsv",
        "uuid\tgene_curie\tgene_symbol\tdisease_curie\tdisease_title\tclassification_title\tmoi_title\n"
        "SGC-1\tHGNC:1\tGENE1\tMONDO:0000001\tPrimary disease\tDefinitive\tAutosomal dominant\n",
    )


def _write_reference_fasta(ctx: MatrixCaseContext) -> str:
    return ctx.write_text("refs.fa", ">NM_0001 gene=TEST1 product:Example\nGGGATGAAATAACCC\n")


def _gwas_association(rsid: str, trait: str, gene: str) -> JsonObject:
    return {
        "pvalue": 2e-9,
        "loci": [{"strongestRiskAlleles": [{"riskAlleleName": f"{rsid}-A"}], "authorReportedGenes": [{"geneName": gene}]}],
        "snps": [{"rsId": rsid, "genomicContexts": [{"gene": {"geneName": gene}}]}],
        "study": {"accessionId": "GCSTCONTRACT", "diseaseTrait": {"trait": trait}, "publicationInfo": {"pubmedId": "123"}},
    }


def _phenotype_gene_source_record() -> JsonObject:
    return {
        "record_id": "orphanet-pnkp",
        "source_id": "orphanet",
        "source_type": "rare disease gene phenotype source",
        "source_title": "Orphanet PNKP disorder",
        "finding": "PNKP is associated with ataxia and microcephaly.",
        "verified_fields": {"genes": ["PNKP"], "phenotypes": ["ataxia", "microcephaly"]},
    }


def _assert_pathway(result: JsonObject, _ctx: MatrixCaseContext) -> None:
    assert result["coverage_state"] == "data_returned"
    assert {member["gene_symbol"] for member in result["members"]} == {"CDK1", "CCNB1"}


def _assert_cell_markers(result: JsonObject, _ctx: MatrixCaseContext) -> None:
    assert result["coverage_state"] == "data_returned"
    assert result["markers"][0]["gene_symbol"] == "ALB"


def _assert_region(result: JsonObject, _ctx: MatrixCaseContext) -> None:
    assert result["coverage_state"] == "data_returned"
    assert result["features"][0]["gene_symbol"] == "GENE1"


def _assert_screen_import(result: JsonObject, _ctx: MatrixCaseContext) -> None:
    assert result["status"] == "direct_source_records_found"
    assert result["direct_perturbation_source_records"][0]["verified_fields"]["genes"] == ["EGFR"]


def _assert_screen_compare(result: JsonObject, _ctx: MatrixCaseContext) -> None:
    assert result["status"] == "completed"
    assert result["top_observed_candidate"] == "EGFR"


def _assert_gwas_gene(result: JsonObject, _ctx: MatrixCaseContext) -> None:
    assert result["status"] == "completed"
    assert result["top_observed_candidate"] == "PCSK9"


def _assert_nutrigenomics_context(result: JsonObject, _ctx: MatrixCaseContext) -> None:
    assert result["coverage_state"] == "data_returned"
    assert "folate_metabolism" in result["declared_domains"]


def _assert_nutrigenomics_domains(result: JsonObject, _ctx: MatrixCaseContext) -> None:
    assert result["coverage_state"] == "data_returned"
    assert any(domain["domain_id"] == "folate_metabolism" for domain in result["domains"])


def _assert_nutrigenomics_domain(result: JsonObject, _ctx: MatrixCaseContext) -> None:
    assert result["coverage_state"] == "data_returned"
    assert result["markers"][0]["variant"]["rsid"] == "rs1801133"


def _assert_nutrigenomics_variant(result: JsonObject, _ctx: MatrixCaseContext) -> None:
    assert result["coverage_state"] == "data_returned"
    assert result["variant"]["rsid"] == "rs1801133"


def _assert_disease_compare(result: JsonObject, _ctx: MatrixCaseContext) -> None:
    assert result["status"] == "direct_source_supported"
    assert result["top_observed_candidate"] == "Gordon syndrome"


def _assert_drug_target(result: JsonObject, _ctx: MatrixCaseContext) -> None:
    assert result["status"] == "direct_source_supported"
    assert result["top_observed_candidate"] == "ADRB2"


def _assert_gene_hpo(result: JsonObject, _ctx: MatrixCaseContext) -> None:
    assert result["status"] == "direct_source_supported"
    assert result["top_observed_candidate"] == "PNKP"


def _assert_phenotype_normalize(result: JsonObject, _ctx: MatrixCaseContext) -> None:
    assert result["status"] == "completed"
    assert "HP:0001250" in result["hpo_ids"]
    assert "microcephaly" in {item["normalized"] for item in result["normalized_phenotypes"]}


def _assert_risk_plan(result: JsonObject, _ctx: MatrixCaseContext) -> None:
    assert result["status"] == "completed"
    assert result["evidence_envelope"]["operation"] == "phenotype.plan_risk_investigation"


def _assert_gene_disease(result: JsonObject, _ctx: MatrixCaseContext) -> None:
    assert result["status"] == "completed"
    assert result["associations"][0]["gene"] == "GENE1"


def _assert_sequence_analyze(result: JsonObject, _ctx: MatrixCaseContext) -> None:
    assert result["status"] == "completed"
    assert result["analyses"]["translation"]["translation"]["amino_acids"] == "MK*"
    assert result["analyses"]["reference_matches"]["identity_chain"]["matched_record_ids"] == ["NM_0001"]


def _assert_primers(result: JsonObject, _ctx: MatrixCaseContext) -> None:
    assert result["status"] == "completed"
    assert result["summary"]["amplicon_count"] == 1


def _assert_kozak(result: JsonObject, _ctx: MatrixCaseContext) -> None:
    assert result["status"] == "completed"
    assert result["starts"][0]["strength"] == "strong"


def _assert_orfs(result: JsonObject, _ctx: MatrixCaseContext) -> None:
    assert result["status"] == "completed"
    assert result["orfs"][0]["translation"] == "MK*"


def _assert_restriction(result: JsonObject, _ctx: MatrixCaseContext) -> None:
    assert result["status"] == "completed"
    assert {item["name"] for item in result["enzymes"]} == {"ECORI", "BAMHI"}


def _assert_sequence_match(result: JsonObject, _ctx: MatrixCaseContext) -> None:
    assert result["status"] == "matched"
    assert result["identity_chain"]["matched_record_ids"] == ["NM_0001"]


def _assert_translate(result: JsonObject, _ctx: MatrixCaseContext) -> None:
    assert result["status"] == "completed"
    assert result["translation"]["amino_acids"] == "M*"


PUBLIC_DETERMINISTIC_OPERATION_CASES = (
    OperationCase("pathway.retrieve_members", "public_deterministic", _pathway_params, _assert_pathway),
    OperationCase("cell_type.retrieve_markers", "public_deterministic", _cell_marker_params, _assert_cell_markers),
    OperationCase("region.retrieve_features", "public_deterministic", _region_params, _assert_region),
    OperationCase("functional_genomics.import_perturbation_table", "public_deterministic", _screen_import_params, _assert_screen_import),
    OperationCase("functional_genomics.compare_gene_perturbation", "public_deterministic", _screen_compare_params, _assert_screen_compare),
    OperationCase("nutrigenomics.build_source_context", "public_deterministic", _empty_params, _assert_nutrigenomics_context),
    OperationCase("nutrigenomics.list_domains", "public_deterministic", _empty_params, _assert_nutrigenomics_domains),
    OperationCase("nutrigenomics.retrieve_domain_markers", "public_deterministic", _nutrigenomics_domain_params, _assert_nutrigenomics_domain),
    OperationCase("nutrigenomics.retrieve_variant_records", "public_deterministic", _nutrigenomics_variant_params, _assert_nutrigenomics_variant),
    OperationCase("phenotype.compare_disease_evidence", "public_deterministic", _disease_compare_params, _assert_disease_compare),
    OperationCase("phenotype.compare_drug_target_evidence", "public_deterministic", _drug_target_params, _assert_drug_target),
    OperationCase("phenotype.compare_gene_hpo_evidence", "public_deterministic", _gene_hpo_params, _assert_gene_hpo),
    OperationCase("phenotype.normalize_terms", "public_deterministic", _phenotype_normalize_params, _assert_phenotype_normalize),
    OperationCase("phenotype.plan_risk_investigation", "public_deterministic", _risk_plan_params, _assert_risk_plan),
    OperationCase("phenotype.retrieve_gene_disease_associations", "public_deterministic", _gene_disease_params, _assert_gene_disease),
    OperationCase("sequence.analyze", "public_deterministic", _sequence_analyze_params, _assert_sequence_analyze),
    OperationCase("sequence.check_primers", "public_deterministic", _primer_params, _assert_primers),
    OperationCase("sequence.classify_kozak", "public_deterministic", _kozak_params, _assert_kozak),
    OperationCase("sequence.find_orfs", "public_deterministic", _orf_params, _assert_orfs),
    OperationCase("sequence.find_restriction_sites", "public_deterministic", _restriction_params, _assert_restriction),
    OperationCase("sequence.match_reference", "public_deterministic", _sequence_match_params, _assert_sequence_match),
    OperationCase("sequence.translate", "public_deterministic", _translate_params, _assert_translate),
)
PUBLIC_DETERMINISTIC_OPERATIONS = frozenset(case.operation for case in PUBLIC_DETERMINISTIC_OPERATION_CASES)

SOURCE_FORMAT_MATRIX_CELLS = frozenset(
    (source_format, operation)
    for source_format in SOURCE_FORMAT_MATRIX_SOURCE_FORMATS
    for operation in SOURCE_FORMAT_MATRIX_OPERATIONS
)
PUBLIC_DETERMINISTIC_SOURCE_INVARIANT_CELLS = frozenset(
    (source_format, operation)
    for source_format in SOURCE_FORMAT_MATRIX_SOURCE_FORMATS
    for operation in PUBLIC_DETERMINISTIC_OPERATIONS
)
SOURCE_FORMAT_SUPPORT_EXECUTABLE_CELLS = frozenset(
    (source_format, operation)
    for source_format in SOURCE_FORMAT_MATRIX_SOURCE_FORMATS
    for operation in SOURCE_FORMAT_SUPPORT_EXECUTABLE_OPERATIONS
)
EXTERNAL_SOURCE_EXECUTABLE_CELLS = frozenset(
    (source_format, operation)
    for source_format in SOURCE_FORMAT_MATRIX_SOURCE_FORMATS
    for operation in EXTERNAL_SOURCE_EXECUTABLE_OPERATIONS
)
STATEFUL_RUNTIME_EXECUTABLE_CELLS = frozenset(
    (source_format, operation)
    for source_format in SOURCE_FORMAT_MATRIX_SOURCE_FORMATS
    for operation in STATEFUL_RUNTIME_EXECUTABLE_OPERATIONS
)

COVERAGE_OPERATION_CLASSES = (
    SOURCE_FORMAT_MATRIX_OPERATIONS,
    SOURCE_FORMAT_SUPPORT_OPERATIONS,
    PUBLIC_DETERMINISTIC_OPERATIONS,
    EXTERNAL_SOURCE_OPERATIONS,
    STATEFUL_RUNTIME_OPERATIONS,
)
