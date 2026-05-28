from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _candidate_helper import compare_candidate_payload

from genomi.capabilities.phenotype.phenotype import (
    compare_disease_phenotype_evidence,
    compare_gene_hpo_evidence,
    normalize_phenotypes,
    retrieve_primary_gene_disease_associations,
)
from genomi.evidence import record_research_findings
from genomi.operations import call_operation


class PhenotypePrioritizationTests(unittest.TestCase):
    def test_normalize_phenotypes_extracts_hpo_ids_and_terms(self) -> None:
        result = normalize_phenotypes(text="Ataxia; seizures; HP:0001250", terms=["microcephaly"])

        self.assertEqual(result["schema"], "genomi-phenotype-normalization-v1")
        self.assertEqual(result["status"], "completed")
        self.assertIn("HP:0001250", result["hpo_ids"])
        normalized = [item["normalized"] for item in result["normalized_phenotypes"]]
        self.assertIn("ataxia", normalized)
        self.assertIn("seizures", normalized)
        self.assertIn("microcephaly", normalized)

    def test_normalize_phenotypes_reports_host_term_misses(self) -> None:
        result = call_operation(
            "phenotype.normalize_terms",
            {
                "text": "seizures and a small head",
                "semantic_context": {
                    "raw_query": "seizures and a small head",
                    "host_expansions": ["epileptic seizure", "microcephaly"],
                    "host_entities": [
                        {"text": "seizures", "type": "phenotype"},
                        {"text": "microcephaly", "type": "phenotype"},
                    ],
                },
            },
        )

        normalized = {item["normalized"] for item in result["normalized_phenotypes"]}
        self.assertIn("epileptic seizure", normalized)
        self.assertIn("microcephaly", normalized)
        self.assertEqual(result["semantic_context"]["term_matches"], [])
        self.assertIn("microcephaly", {item["text"] for item in result["semantic_context"]["term_misses"]})

    def test_semantic_context_ignores_malformed_hints(self) -> None:
        result = call_operation(
            "phenotype.normalize_terms",
            {
                "text": "ataxia",
                "semantic_context": {
                    "raw_query": "ataxia",
                    "host_expansions": "not an array",
                    "host_entities": ["not an object"],
                },
            },
        )

        ignored = result["semantic_context"]["ignored_hints"]
        self.assertTrue(any(item["field"] == "host_expansions" for item in ignored))
        self.assertTrue(any(item["field"] == "host_entities" for item in ignored))

    def test_disease_prioritization_prefers_source_verified_phenotype_match(self) -> None:
        result = compare_disease_phenotype_evidence(
            phenotype_text="hypertension; hyperkalemia; HP:0000822",
            candidate_diseases=["Gordon syndrome", "Distal arthrogryposis"],
            search_stored_research=False,
            source_records=[
                {
                    "record_id": "orphanet-gordon",
                    "source_id": "orphanet",
                    "source_type": "rare disease phenotype source",
                    "source_title": "Orphanet Gordon syndrome",
                    "source_url": "https://example.test/gordon",
                    "finding": "Gordon syndrome is described with hypertension and hyperkalemia.",
                    "verified_fields": {
                        "diseases": ["Gordon syndrome"],
                        "phenotypes": ["hypertension", "hyperkalemia"],
                        "hpo_ids": ["HP:0000822"],
                    },
                    "support_spans": [
                        {
                            "field": "disease",
                            "value": "Gordon syndrome",
                            "source_text": "Gordon syndrome is described with hypertension and hyperkalemia.",
                        },
                        {
                            "field": "phenotype",
                            "value": "hypertension",
                            "source_text": "Gordon syndrome is described with hypertension and hyperkalemia.",
                        },
                    ],
                },
                {
                    "record_id": "generic-da",
                    "source_type": "literature",
                    "source_title": "Distal arthrogryposis review",
                    "source_url": "https://example.test/da",
                    "finding": "Distal arthrogryposis is a congenital contracture condition.",
                    "disease": "Distal arthrogryposis",
                },
            ],
            use_hpo_annotations=False,
        )

        self.assertEqual(result["status"], "direct_source_supported")
        self.assertEqual(result["top_observed"]["candidate_id"], "Gordon syndrome")
        self.assertEqual(result["top_observed"]["best_evidence_lane"], "direct_source_match")

    def test_disease_prioritization_derives_gene_diseases_and_ranks_hpo_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gencc_file = _write_gencc_file(
                Path(tmp),
                [
                    ("SGC-1", "PIEZO2", "MONDO:0000001", "Gordon syndrome", "OMIM:114300", "Definitive", "Autosomal dominant"),
                    ("SGC-2", "PIEZO2", "MONDO:0000002", "Distal arthrogryposis type 5", "OMIM:108145", "Strong", "Autosomal dominant"),
                ],
            )
            disease_file = Path(tmp) / "phenotype.hpoa"
            disease_file.write_text(
                "\n".join(
                    [
                        "database_id\tdisease_name\tqualifier\thpo_id\treference\tevidence",
                        "OMIM:114300\tGordon syndrome\t\tHP:0000822\tPMID:1\tPCS",
                        "OMIM:114300\tGordon syndrome\t\tHP:0001965\tPMID:1\tPCS",
                        "OMIM:108145\tDistal arthrogryposis type 5\t\tHP:0000822\tPMID:2\tPCS",
                        "OMIM:108145\tDistal arthrogryposis type 5\t\tHP:0002804\tPMID:2\tPCS",
                        "OMIM:108145\tDistal arthrogryposis type 5\t\tHP:0000006\tPMID:2\tPCS",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            result = compare_disease_phenotype_evidence(
                hpo_ids=["HP:0000822", "HP:0001965"],
                genes=["PIEZO2"],
                search_stored_research=False,
                hpo_disease_file=disease_file,
                gencc_file=gencc_file,
                download_primary_gene_disease=False,
            )

        self.assertEqual(result["status"], "direct_source_supported")
        self.assertEqual(result["top_observed"]["candidate_id"], "Gordon syndrome")
        self.assertEqual(result["top_observed"]["candidate_identifiers"], ["OMIM:114300"])
        self.assertEqual(result["top_observed"]["phenotype_overlap_count"], 2)
        self.assertEqual(result["top_observed"]["phenotype_profile_hpo_count"], 2)
        self.assertEqual(result["top_observed"]["phenotype_overlap_density"], 1.0)
        distal = next(row for row in result["candidate_matrix"] if row["candidate_id"] == "Distal arthrogryposis type 5")
        self.assertEqual(distal["candidate_identifiers"], ["OMIM:108145"])
        self.assertEqual(distal["phenotype_overlap_count"], 1)
        self.assertEqual(distal["phenotype_profile_hpo_count"], 3)
        self.assertEqual(result["hpo_disease_annotation_evidence"]["matched_record_count"], 2)
        self.assertIn("disease_ids", result["top_observed"]["supporting_evidence"][0]["source_verified_fields"])

    def test_disease_prioritization_prefers_dense_hpo_match_over_broad_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gencc_file = _write_gencc_file(
                Path(tmp),
                [
                    ("SGC-1", "GENE1", "MONDO:0000001", "Broad disease", "OMIM:1", "Definitive", "Autosomal dominant"),
                    ("SGC-2", "GENE1", "MONDO:0000002", "Narrow disease", "OMIM:2", "Strong", "Autosomal dominant"),
                ],
            )
            disease_file = Path(tmp) / "phenotype.hpoa"
            rows = ["database_id\tdisease_name\tqualifier\thpo_id\treference\tevidence"]
            rows.extend(f"OMIM:1\tBroad disease\t\tHP:{index:07d}\tPMID:1\tPCS" for index in range(1, 51))
            rows.extend(f"OMIM:2\tNarrow disease\t\tHP:{index:07d}\tPMID:2\tPCS" for index in range(1, 4))
            disease_file.write_text("\n".join(rows) + "\n", encoding="utf-8")

            result = compare_disease_phenotype_evidence(
                hpo_ids=[f"HP:{index:07d}" for index in range(1, 5)],
                genes=["GENE1"],
                search_stored_research=False,
                hpo_disease_file=disease_file,
                gencc_file=gencc_file,
                download_primary_gene_disease=False,
                limit=10,
            )

        self.assertEqual(result["top_observed"]["candidate_id"], "Narrow disease")
        self.assertEqual(result["top_observed"]["phenotype_overlap_count"], 3)
        self.assertEqual(result["top_observed"]["phenotype_profile_hpo_count"], 3)
        self.assertEqual(result["top_observed"]["phenotype_overlap_density"], 1.0)
        broad = next(row for row in result["candidate_matrix"] if row["candidate_id"] == "Broad disease")
        self.assertEqual(broad["phenotype_overlap_count"], 4)
        self.assertEqual(broad["phenotype_profile_hpo_count"], 50)
        self.assertEqual(broad["phenotype_overlap_density"], 0.08)

    def test_primary_gene_disease_retriever_filters_to_declared_gencc_validity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gencc_file = _write_gencc_file(
                Path(tmp),
                [
                    ("SGC-1", "GENE1", "MONDO:0000001", "Primary disease", "OMIM:1", "Definitive", "Autosomal dominant"),
                    ("SGC-2", "GENE1", "MONDO:0000002", "Moderate disease", "OMIM:2", "Moderate", "Autosomal dominant"),
                ],
            )

            result = retrieve_primary_gene_disease_associations(
                genes=["GENE1"],
                gencc_file=gencc_file,
                download_gencc=False,
            )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["coverage_state"], "data_returned")
        self.assertEqual([row["disease_name"] for row in result["associations"]], ["Primary disease"])
        self.assertEqual(result["associations"][0]["disease_identifiers"], ["MONDO:0000001", "OMIM:1"])

    def test_gene_disease_retriever_accepts_typed_gene_entity_hint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gencc_file = _write_gencc_file(
                Path(tmp),
                [
                    ("SGC-1", "GENE1", "MONDO:0000001", "Primary disease", "OMIM:1", "Definitive", "Autosomal dominant"),
                ],
            )

            result = call_operation(
                "phenotype.retrieve_gene_disease_associations",
                {
                    "gencc_file": str(gencc_file),
                    "download_gencc": False,
                    "semantic_context": {
                        "raw_query": "what diseases are linked to gene one",
                        "host_entities": [{"text": "GENE1", "type": "gene"}],
                    },
                },
            )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["associations"][0]["gene"], "GENE1")
        self.assertEqual(result["semantic_context"]["term_matches"][0]["text"], "GENE1")

    def test_primary_gene_disease_retriever_reports_missing_gencc_install_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict("os.environ", {"GENOMI_HOME": tmp}):
            result = retrieve_primary_gene_disease_associations(
                genes=["GENE1"],
                download_gencc=False,
            )

        self.assertEqual(result["status"], "requires_library_install")
        self.assertFalse(result["tool_will_work"])
        self.assertEqual(result["missing_library"]["library"], "gencc")
        self.assertIn("--libraries gencc", result["ask_user"]["install_command"])

    def test_disease_prioritization_enumerates_primary_gene_disease_associations_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gencc_file = _write_gencc_file(
                Path(tmp),
                [
                    ("SGC-1", "GENE1", "MONDO:0000001", "Primary disease", "OMIM:1", "Definitive", "Autosomal dominant"),
                ],
            )
            disease_file = Path(tmp) / "phenotype.hpoa"
            disease_file.write_text(
                "\n".join(
                    [
                        "database_id\tdisease_name\tqualifier\thpo_id\treference\tevidence",
                        "OMIM:1\tPrimary disease\t\tHP:0000001\tPMID:1\tPCS",
                        "OMIM:2\tAuxiliary disease\t\tHP:0000001\tPMID:2\tPCS",
                        "OMIM:2\tAuxiliary disease\t\tHP:0000002\tPMID:2\tPCS",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            result = compare_disease_phenotype_evidence(
                hpo_ids=["HP:0000001", "HP:0000002"],
                genes=["GENE1"],
                search_stored_research=False,
                hpo_disease_file=disease_file,
                gencc_file=gencc_file,
                download_primary_gene_disease=False,
                limit=10,
            )

        self.assertEqual([row["candidate_id"] for row in result["candidate_matrix"]], ["Primary disease"])
        self.assertEqual(
            result["top_observed"]["supporting_evidence"][0]["hpo_annotation_profile"]["enumeration_scope"],
            "primary_gene_disease_index",
        )

    def test_disease_prioritization_does_not_require_gencc_when_candidate_diseases_are_supplied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            disease_file = Path(tmp) / "phenotype.hpoa"
            disease_file.write_text(
                "\n".join(
                    [
                        "database_id\tdisease_name\tqualifier\thpo_id\treference\tevidence",
                        "OMIM:1\tSupplied disease\t\tHP:0000001\tPMID:1\tPCS",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            result = compare_disease_phenotype_evidence(
                hpo_ids=["HP:0000001"],
                genes=["GENE1"],
                candidate_diseases=["Supplied disease"],
                search_stored_research=False,
                hpo_disease_file=disease_file,
                download_primary_gene_disease=False,
            )

        self.assertEqual(result["top_observed"]["candidate_id"], "Supplied disease")
        self.assertEqual(result["hpo_disease_annotation_evidence"]["status"], "searched")
        self.assertEqual(
            result["hpo_disease_annotation_evidence"]["primary_gene_disease_evidence"]["status"],
            "not_applicable_supplied_candidates",
        )

    def test_gene_prioritization_withholds_answer_for_partial_manual_research_coverage(self) -> None:
        result = compare_gene_hpo_evidence(
            phenotype_text="ataxia; microcephaly; seizures",
            condition="ataxia with oculomotor apraxia",
            genes=["SPG7", "PNKP"],
            search_stored_research=False,
            use_hpo_annotations=False,
            source_records=[
                {
                    "record_id": "orphanet-pnkp",
                    "source_id": "orphanet",
                    "source_type": "rare disease gene phenotype source",
                    "source_title": "Orphanet PNKP disorder",
                    "source_url": "https://example.test/pnkp",
                    "finding": "PNKP is associated with ataxia, microcephaly, and seizures.",
                    "verified_fields": {
                        "genes": ["PNKP"],
                        "diseases": ["ataxia with oculomotor apraxia"],
                        "phenotypes": ["ataxia", "microcephaly", "seizures"],
                    },
                    "support_spans": [
                        {
                            "field": "gene",
                            "value": "PNKP",
                            "source_text": "PNKP is associated with ataxia, microcephaly, and seizures.",
                        },
                        {
                            "field": "phenotype",
                            "value": "ataxia",
                            "source_text": "PNKP is associated with ataxia, microcephaly, and seizures.",
                        },
                    ],
                },
                {
                    "record_id": "generic-spg7",
                    "source_id": "opentargets",
                    "source_type": "target disease association",
                    "source_title": "Open Targets SPG7 association",
                    "source_url": "https://example.test/spg7",
                    "finding": "SPG7 has broad ataxia association context.",
                    "genes": ["SPG7"],
                },
            ],
        )

        self.assertIsNone(result["top_observed"])
        self.assertFalse(result["summary"]["comparable_candidate_evidence"])
        self.assertIn("Candidate evidence coverage is incomplete", " ".join(result["warnings"]))
        spg7 = next(row for row in result["candidate_matrix"] if row["candidate_id"] == "SPG7")
        self.assertNotEqual(spg7["answerability"], "direct_source_supported")

    def test_gene_prioritization_uses_hpo_annotation_overlap_across_all_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            hpo_file = Path(tmp) / "phenotype_to_genes.txt"
            hpo_file.write_text(
                "\n".join(
                    [
                        "HP:0001251\tAtaxia\t1\tPNKP",
                        "HP:0000752\tHyperactivity\t1\tPNKP",
                        "HP:0001251\tAtaxia\t2\tSPG7",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            result = compare_gene_hpo_evidence(
                hpo_ids=["HP:0001251", "HP:0000752"],
                genes=["SPG7", "PNKP"],
                search_stored_research=False,
                hpo_gene_file=hpo_file,
            )

        self.assertEqual(result["top_observed"]["candidate_id"], "PNKP")
        self.assertEqual(result["top_observed"]["phenotype_overlap_count"], 2)
        self.assertEqual(result["top_observed"]["phenotype_match_detail"]["matched_hpo_ids"], ["HP:0001251", "HP:0000752"])
        self.assertEqual(result["top_observed"]["phenotype_match_detail"]["unmatched_hpo_ids"], [])
        top_support = result["top_observed"]["supporting_evidence"][0]
        self.assertEqual(top_support["source_verified_fields"]["hpo_ids"], ["HP:0001251"])
        self.assertEqual(top_support["query_context_support"]["hpo:HP:0001251"], "verified_hpo")
        self.assertTrue(result["summary"]["comparable_candidate_evidence"])
        spg7 = next(row for row in result["candidate_matrix"] if row["candidate_id"] == "SPG7")
        self.assertEqual(spg7["phenotype_overlap_count"], 1)
        self.assertEqual(spg7["phenotype_match_detail"]["unmatched_hpo_ids"], ["HP:0000752"])

    def test_gene_compare_operation_reads_stored_research_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"
            record_research_findings(
                db,
                {
                    "target": {"type": "gene", "gene": "PNKP"},
                    "source": {
                        "title": "Example rare disease source",
                        "url": "https://example.test/pnkp",
                        "type": "orphanet",
                    },
                    "finding": {
                        "type": "phenotype_association",
                        "text": "PNKP is associated with ataxia and microcephaly.",
                    },
                    "verified_fields": {"genes": ["PNKP"], "phenotypes": ["ataxia", "microcephaly"]},
                    "support_spans": [
                        {
                            "field": "gene",
                            "value": "PNKP",
                            "source_text": "PNKP is associated with ataxia and microcephaly.",
                        }
                    ],
                },
            )
            result = compare_candidate_payload({
                    "db": str(db),
                    "phenotypes": ["ataxia", "microcephaly"],
                    "genes": ["PNKP"],
                    "search_stored_research": True,
                })

        self.assertNotIn("answer", result)
        panel = result["evidence_panels"]["expert_phenotype_annotation"]
        self.assertEqual(panel["ranking"][0]["candidate"], "PNKP")
        self.assertEqual(
            panel["ranking"][0]["evidence_discriminators"]["phenotype_match_detail"]["matched_phenotypes"],
            ["ataxia", "microcephaly"],
        )
        self.assertEqual(panel["evidence_records"][0]["candidate"], "PNKP")
        self.assertIn("candidate_evidence_matrix", result)

    def test_phenotype_gene_operation_returns_source_specific_answer_and_evidence(self) -> None:
        result = call_operation(
            "phenotype.compare_gene_hpo_evidence",
            {
                "phenotypes": ["ataxia", "microcephaly"],
                "genes": ["PNKP"],
                "search_stored_research": False,
                "use_hpo_annotations": False,
                "source_records": [
                    {
                        "record_id": "orphanet-pnkp",
                        "source_id": "orphanet",
                        "source_type": "rare disease gene phenotype source",
                        "source_title": "Orphanet PNKP disorder",
                        "source_url": "https://example.test/pnkp",
                        "finding": "PNKP is associated with ataxia and microcephaly.",
                        "verified_fields": {"genes": ["PNKP"], "phenotypes": ["ataxia", "microcephaly"]},
                        "support_spans": [
                            {
                                "field": "gene",
                                "value": "PNKP",
                                "source_text": "PNKP is associated with ataxia and microcephaly.",
                            }
                        ],
                    }
                ],
            },
        )

        self.assertNotIn("answer", result)
        self.assertEqual(result["top_observed_candidate"], "PNKP")
        self.assertEqual(result["source_prior"], "expert_phenotype_annotation")
        self.assertEqual(result["ranking"][0]["candidate"], "PNKP")
        self.assertEqual(result["evidence_records"][0]["candidate"], "PNKP")

    def test_phenotype_gene_operation_reports_missing_hpo_install_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict("os.environ", {"GENOMI_HOME": tmp}):
            result = call_operation(
                "phenotype.compare_gene_hpo_evidence",
                {
                    "hpo_ids": ["HP:0001250"],
                    "genes": ["PNKP"],
                    "search_stored_research": False,
                },
            )

        hpo = result["details"]["source_result"]["hpo_annotation_evidence"]
        self.assertEqual(hpo["status"], "requires_library_install")
        self.assertFalse(hpo["tool_will_work"])
        self.assertEqual(hpo["missing_library"]["library"], "hpo")
        self.assertIn("--libraries hpo", hpo["ask_user"]["install_command"])


def _write_gencc_file(
    root: Path,
    rows: list[tuple[str, str, str, str, str, str, str]],
) -> Path:
    path = root / "gencc-submissions.tsv"
    header = [
        "sgc_id",
        "version_number",
        "gene_curie",
        "gene_symbol",
        "disease_curie",
        "disease_title",
        "disease_original_curie",
        "disease_original_title",
        "classification_curie",
        "classification_title",
        "moi_curie",
        "moi_title",
        "submitter_curie",
        "submitter_title",
        "submitted_as_hgnc_id",
        "submitted_as_hgnc_symbol",
        "submitted_as_disease_id",
        "submitted_as_disease_name",
        "submitted_as_moi_id",
        "submitted_as_moi_name",
        "submitted_as_submitter_id",
        "submitted_as_submitter_name",
        "submitted_as_classification_id",
        "submitted_as_classification_name",
        "submitted_as_date",
        "submitted_as_public_report_url",
        "submitted_as_notes",
        "submitted_as_pmids",
        "submitted_as_assertion_criteria_url",
        "submitted_as_submission_id",
        "submitted_run_date",
    ]
    lines = ["\t".join(header)]
    for index, (sgc_id, gene, mondo_id, disease_name, original_id, classification, inheritance) in enumerate(rows, start=1):
        hgnc_id = f"HGNC:{1000 + index}"
        lines.append(
            "\t".join(
                [
                    sgc_id,
                    "1",
                    hgnc_id,
                    gene,
                    mondo_id,
                    disease_name,
                    original_id,
                    disease_name,
                    f"GENCC:{2000 + index}",
                    classification,
                    f"HP:{index:07d}",
                    inheritance,
                    "GENCC:000101",
                    "Test submitter",
                    hgnc_id,
                    gene,
                    original_id,
                    disease_name,
                    f"HP:{index:07d}",
                    inheritance,
                    "GENCC:000101",
                    "Test submitter",
                    f"GENCC:{2000 + index}",
                    classification,
                    "2024-01-01",
                    "https://example.test/gencc",
                    "",
                    "PMID: 12345678",
                    "",
                    sgc_id,
                    "2024-01-01",
                ]
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    unittest.main()
