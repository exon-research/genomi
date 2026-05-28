from __future__ import annotations

import gzip
import tempfile
import unittest
from unittest import mock

from genomi.capabilities.functional_genomics.evidence_acquisition import (
    acquire_perturbation_source_records,
    extract_screen_table_evidence_records,
)
from genomi.capabilities.functional_genomics.geo import query_geo_datasets
from genomi.capabilities.functional_genomics.screen import (
    compare_screen_experiment_evidence,
    retrieve_public_screen_records,
)
from genomi.evidence.sources import evidence_source_catalog
from genomi.operations import call_operation


class ScreenGeneTests(unittest.TestCase):
    def test_compare_screen_experiment_evidence_prefers_direct_perturbation_context(self) -> None:
        result = compare_screen_experiment_evidence(
            context="Which gene is most promising in an A549 resistance screen after DMSO perturbation?",
            genes=["EGFR", "MYC", "PTEN"],
            cell_line="A549",
            perturbation="DMSO",
            phenotype="resistance",
            source_records=[
                {
                    "record_id": "screen-1",
                    "genes": ["EGFR"],
                    "source_type": "CRISPR screen supplementary table",
                    "source_title": "A549 DMSO resistance screen",
                    "source_url": "https://example.test/screen",
                    "cell_line": "A549",
                    "perturbation": "DMSO",
                    "phenotype": "resistance",
                    "finding": "EGFR was a top hit in the A549 DMSO resistance screen.",
                    "verified_fields": {
                        "genes": ["EGFR"],
                        "cell_line": "A549",
                        "perturbation": "DMSO",
                        "phenotype": "resistance",
                    },
                    "support_spans": [
                        {
                            "field": "genes",
                            "value": "EGFR",
                            "source_text": "EGFR was a top hit in the A549 DMSO resistance screen.",
                        },
                        {
                            "field": "cell_line",
                            "value": "A549",
                            "source_text": "EGFR was a top hit in the A549 DMSO resistance screen.",
                        },
                    ],
                },
                {
                    "record_id": "lit-1",
                    "genes": ["MYC"],
                    "source_type": "literature",
                    "source_title": "MYC signaling review",
                    "pmid": "123",
                    "finding": "MYC has been discussed in colorectal cancer signaling.",
                },
            ],
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["top_observed"]["candidate_id"], "EGFR")
        self.assertEqual(result["top_observed"]["best_evidence_lane"], "direct_source_match")
        view = result["evidence_view"]
        self.assertEqual(view["schema"], "genomi-candidate-evidence-view-v1")
        self.assertEqual(view["task_profile"]["profile_id"], "functional_genomics_perturbation_evidence")
        self.assertEqual(view["top_observed"]["candidate_id"], "EGFR")
        self.assertEqual(result["decision_evidence"]["top_observed_candidate"], "EGFR")
        self.assertEqual(result["decision_evidence"]["top_observed_evidence"]["supporting_evidence"][0]["record_id"], "screen-1")
        self.assertEqual(view["candidate_matrix"], result["candidate_matrix"])
        self.assertEqual(result["direct_match_candidates"], ["EGFR"])
        self.assertEqual(result["plausibility_only_candidates"], ["MYC"])
        gpr55 = next(row for row in result["candidate_matrix"] if row["candidate_id"] == "MYC")
        self.assertEqual(gpr55["best_evidence_lane"], "literature_plausibility")
        self.assertIn("weaker than selected lane", gpr55["why_not_selected"][0])

    def test_compare_screen_experiment_evidence_uses_host_semantic_context_fields(self) -> None:
        result = compare_screen_experiment_evidence(
            context="gene effect in lung cells",
            genes=["EGFR", "MYC"],
            semantic_context={
                "raw_query": "Which gene matters in a lung cancer dependency screen?",
                "host_expansions": ["A549", "CRISPR knockout", "dependency"],
                "host_entities": [
                    {"text": "A549", "type": "cell_line"},
                    {"text": "CRISPR knockout", "type": "perturbation"},
                    {"text": "dependency", "type": "phenotype"},
                ],
            },
            source_records=[
                {
                    "record_id": "depmap-egfr",
                    "genes": ["EGFR"],
                    "source_type": "DepMap CRISPR screen",
                    "source_title": "DepMap public CRISPR gene effect",
                    "cell_line": "A549",
                    "perturbation": "CRISPR knockout",
                    "phenotype": "dependency",
                    "finding": "EGFR has DepMap CRISPR gene effect in A549.",
                    "verified_fields": {
                        "genes": ["EGFR"],
                        "cell_line": "A549",
                        "perturbation": "CRISPR knockout",
                        "phenotype": "dependency",
                    },
                }
            ],
        )

        self.assertEqual(result["top_observed"]["candidate_id"], "EGFR")
        accepted = {item["text"] for item in result["semantic_context"]["term_matches"]}
        self.assertIn("CRISPR knockout", accepted)

    def test_compare_screen_experiment_evidence_requires_source_records_for_ranking(self) -> None:
        result = compare_screen_experiment_evidence(
            context="A549 resistance screen",
            genes=["EGFR", "MYC"],
            source_records=[],
        )

        self.assertEqual(result["status"], "no_source_records")
        self.assertEqual(result["coverage_state"], "out_of_scope_for_input")
        env = result["evidence_envelope"]
        self.assertIn(env["finding_state"], ("not_observed_in_consulted_scope", "not_assessed"))
        self.assertFalse(env["negative_inference"]["allowed"])
        self.assertIsNone(result["top_observed"])
        self.assertEqual(result["unmatched_candidates"], ["EGFR", "MYC"])
        self.assertEqual(result["evidence_view"]["coverage"]["candidate_count"], 2)
        self.assertIsNone(result["evidence_view"]["coverage"]["top_observed_candidate"])

    def test_retrieve_public_screen_records_from_biogrid_orcs(self) -> None:
        def fake_fetch_json(url: str):
            if "/screens/" in url:
                return [
                    {
                        "SCREEN_ID": "178",
                        "SCREEN_TITLE": "A549 DMSO resistance screen",
                        "CELL_LINE": "A549",
                        "LIBRARY_METHODOLOGY": "knockout",
                        "PHENOTYPE": "resistance",
                    }
                ]
            if "/screen/178" in url:
                return [
                    {"OFFICIAL_SYMBOL": "EGFR", "SCORE.1": "9.2"},
                    {"OFFICIAL_SYMBOL": "MYC", "SCORE.1": "1.1"},
                ]
            return []

        result = retrieve_public_screen_records(
            context="A549 DMSO resistance screen",
            genes=["EGFR", "MYC"],
            cell_line="A549",
            perturbation="CRISPR knockout",
            phenotype="resistance",
            sources=["biogrid_orcs"],
            biogrid_orcs_access_key="A" * 32,
            fetch_json=fake_fetch_json,
        )

        self.assertEqual(result["coverage_state"], "data_returned")
        self.assertEqual(result["source_records"][0]["source_type"], "BioGRID ORCS CRISPR screen")
        self.assertEqual(result["records_by_gene"]["EGFR"][0]["screen_id"], "178")

    def test_retrieve_public_screen_records_from_depmap_gene_effect_table(self) -> None:
        def fake_fetch_text(url: str) -> str:
            if "model" in url:
                return "ModelID,CellLineName,CCLEName\nACH-000001,A549,A549_LUNG\n"
            return "ModelID,EGFR (1234),MYC (9290)\nACH-000001,-1.25,-0.18\n"

        result = retrieve_public_screen_records(
            context="A549 CRISPR dependency",
            genes=["EGFR", "MYC"],
            cell_line="A549",
            perturbation="CRISPR knockout",
            phenotype="dependency",
            sources=["depmap"],
            depmap_gene_effect_url="https://depmap.example/CRISPRGeneEffect.csv",
            depmap_model_url="https://depmap.example/model.csv",
            fetch_text=fake_fetch_text,
        )

        self.assertEqual(result["coverage_state"], "data_returned")
        self.assertEqual(result["source_records"][0]["genes"], ["EGFR"])
        self.assertEqual(result["source_records"][0]["source_type"], "DepMap CRISPR screen")

    def test_query_geo_parses_accession_metadata_and_table_records(self) -> None:
        seen_urls: list[str] = []

        def fake_fetch_json(url: str):
            seen_urls.append(url)
            if "esearch.fcgi" in url:
                return {"esearchresult": {"idlist": ["20012345"]}}
            return {
                "result": {
                    "uids": ["20012345"],
                    "20012345": {
                        "uid": "20012345",
                        "accession": "GSE12345",
                        "title": "A549 CRISPR dependency screen",
                        "summary": "Genome-wide CRISPR knockout dependency screen in A549 cells.",
                        "taxon": "Homo sapiens",
                    },
                }
            }

        def fake_fetch_text(url: str) -> str:
            return ""

        def fake_fetch_bytes(url: str) -> bytes:
            table = (
                "gene\tcell_line\tperturbation\tphenotype\tscore\n"
                "EGFR\tA549\tCRISPR knockout\tdependency\t-1.25\n"
                "MYC\tA549\tCRISPR knockout\tdependency\t-0.18\n"
            )
            return gzip.compress(table.encode("utf-8"))

        result = query_geo_datasets(
            context="GSE12345 A549 CRISPR dependency",
            accession="GSE12345",
            genes=["EGFR", "MYC"],
            cell_line="A549",
            perturbation="CRISPR knockout",
            phenotype="dependency",
            fetch_json=fake_fetch_json,
            fetch_text=fake_fetch_text,
            fetch_bytes=fake_fetch_bytes,
        )

        self.assertIn("GSE12345%5BACCN%5D", seen_urls[0])
        self.assertEqual(result["status"], "geo_source_records_found")
        self.assertEqual(result["geo_hits"][0]["accession"], "GSE12345")
        self.assertEqual(result["coverage_state"], "data_returned")
        self.assertEqual(result["records_by_gene"]["EGFR"][0]["geo_accession"], "GSE12345")
        self.assertEqual(result["direct_perturbation_source_records"][0]["verification"]["status"], "verified")

    def test_query_geo_reports_skipped_download_candidates(self) -> None:
        def fake_fetch_json(url: str):
            if "esearch.fcgi" in url:
                return {"esearchresult": {"idlist": ["20012345"]}}
            return {
                "result": {
                    "uids": ["20012345"],
                    "20012345": {
                        "uid": "20012345",
                        "accession": "GSE12345",
                        "title": "A549 CRISPR dependency screen",
                        "supplementary_file": [
                            "https://ftp.ncbi.nlm.nih.gov/geo/series/GSE12nnn/GSE12345/suppl/GSE12345_RAW.tar",
                            "https://ftp.ncbi.nlm.nih.gov/geo/series/GSE12nnn/GSE12345/suppl/big.tsv.gz",
                            "https://ftp.ncbi.nlm.nih.gov/geo/series/GSE12nnn/GSE12345/suppl/bad.txt",
                        ],
                    },
                }
            }

        def fake_fetch_text(url: str) -> str:
            return ""

        def fake_fetch_bytes(url: str) -> bytes:
            if "big.tsv.gz" in url:
                return b"x" * 20
            return b"\0\0not text"

        result = query_geo_datasets(
            context="GSE12345 A549 CRISPR dependency",
            accession="GSE12345",
            genes=["EGFR"],
            cell_line="A549",
            perturbation="CRISPR knockout",
            phenotype="dependency",
            fetch_json=fake_fetch_json,
            fetch_text=fake_fetch_text,
            fetch_bytes=fake_fetch_bytes,
            max_download_bytes=10,
        )

        reasons = {candidate.get("skip_reason") for candidate in result["download_candidates"]}
        self.assertIn("raw_archive_or_binary_file", reasons)
        self.assertIn("oversized_compressed_file", reasons)
        self.assertIn("binary_file", reasons)
        self.assertEqual(result["status"], "geo_metadata_found")
        self.assertEqual(result["source_records"], [])

    def test_query_geo_operation_dispatches(self) -> None:
        with mock.patch(
            "genomi.operations.registry.geo.query_geo_datasets",
            return_value={
                "schema": "genomi-functional-genomics-geo-query-v1",
                "ok": True,
                "status": "geo_metadata_found",
                "coverage_state": "metadata_only",
                "geo_hits": [{"accession": "GSE12345"}],
                "download_candidates": [],
                "source_records": [],
                "direct_perturbation_source_records": [],
                "records_by_gene": {},
            },
        ) as query_geo:
            result = call_operation(
                "functional_genomics.query_geo",
                {"context": "GSE12345 A549 CRISPR dependency", "accession": "GSE12345"},
            )

        self.assertEqual(result["status"], "geo_metadata_found")
        query_geo.assert_called_once()

    def test_compare_operation_uses_native_depmap_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            model_path = f"{tmpdir}/model.csv"
            effect_path = f"{tmpdir}/effect.csv"
            with open(model_path, "w", encoding="utf-8") as handle:
                handle.write("ModelID,CellLineName,CCLEName\nACH-000001,A549,A549_LUNG\n")
            with open(effect_path, "w", encoding="utf-8") as handle:
                handle.write("ModelID,EGFR (1234),MYC (9290)\nACH-000001,-1.25,-0.18\n")

            result = call_operation(
                "functional_genomics.compare_gene_perturbation",
                {
                    "context": "A549 CRISPR dependency",
                    "genes": ["EGFR", "MYC"],
                    "cell_line": "A549",
                    "perturbation": "CRISPR knockout",
                    "phenotype": "dependency",
                    "perturbation_sources": ["depmap"],
                    "depmap_gene_effect_url": effect_path,
                    "depmap_model_url": model_path,
                },
            )

        self.assertEqual(result["coverage_state"], "data_returned")
        self.assertEqual(result["native_retrieval"]["coverage_state"], "data_returned")
        self.assertEqual(result["top_observed_candidate"], "EGFR")
        self.assertEqual(result["top_observed"]["best_evidence_lane"], "direct_source_match")

    def test_compare_operation_uses_geo_fallback_for_public_dataset_discovery(self) -> None:
        with mock.patch(
            "genomi.capabilities.research.intent_research.query_geo_datasets",
            return_value={
                "status": "geo_source_records_found",
                "coverage_state": "data_returned",
                "source_coverage": {"coverage_state": "data_returned", "sources_consulted": ["NCBI GEO"]},
                "source_records": [
                    {
                        "record_id": "geo:GSE12345:table:1:EGFR",
                        "genes": ["EGFR"],
                        "source_type": "NCBI GEO perturbation screen table",
                        "source_title": "A549 CRISPR dependency screen",
                        "source_url": "https://ftp.ncbi.nlm.nih.gov/geo/example.tsv",
                        "cell_line": "A549",
                        "perturbation": "CRISPR knockout",
                        "phenotype": "dependency",
                        "finding": "EGFR appears in A549 CRISPR knockout dependency screen.",
                        "verified_fields": {
                            "genes": ["EGFR"],
                            "cell_line": "A549",
                            "perturbation": "CRISPR knockout",
                            "phenotype": "dependency",
                        },
                    }
                ],
                "direct_perturbation_source_records": [],
            },
        ) as query_geo:
            result = call_operation(
                "functional_genomics.compare_gene_perturbation",
                {
                    "context": "published public A549 CRISPR dependency screen dataset table",
                    "genes": ["EGFR", "MYC"],
                    "cell_line": "A549",
                    "perturbation": "CRISPR knockout",
                    "phenotype": "dependency",
                    "search_stored_research": False,
                },
            )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["top_observed_candidate"], "EGFR")
        self.assertIn("geo_retrieval", result)
        query_geo.assert_called_once()

    def test_compare_operation_respects_non_geo_source_filter(self) -> None:
        with mock.patch("genomi.capabilities.research.intent_research.query_geo_datasets") as query_geo:
            result = call_operation(
                "functional_genomics.compare_gene_perturbation",
                {
                    "context": "GEO GSE12345 A549 CRISPR dependency",
                    "genes": ["EGFR", "MYC"],
                    "cell_line": "A549",
                    "perturbation": "CRISPR knockout",
                    "phenotype": "dependency",
                    "perturbation_sources": ["depmap"],
                    "search_stored_research": False,
                },
            )

        self.assertEqual(result["status"], "no_source_records")
        query_geo.assert_not_called()

    def test_compare_screen_experiment_evidence_does_not_treat_unverified_generic_literature_as_direct(self) -> None:
        result = compare_screen_experiment_evidence(
            context="A549 DMSO resistance screen",
            genes=["EGFR", "MYC"],
            cell_line="A549",
            perturbation="DMSO",
            phenotype="resistance",
            source_records=[
                {
                    "record_id": "generic-lit",
                    "genes": ["MYC"],
                    "source_type": "literature",
                    "source_title": "MYC chemoresistance review",
                    "source_url": "https://example.test/gpr55",
                    "finding": "MYC has been discussed in chemoresistance mechanisms.",
                    "cell_line": "A549",
                    "phenotype": "resistance",
                }
            ],
        )

        self.assertEqual(result["status"], "insufficient_source_evidence")
        self.assertIsNone(result["top_observed"])
        gpr55 = next(row for row in result["candidate_matrix"] if row["candidate_id"] == "MYC")
        self.assertEqual(gpr55["best_evidence_lane"], "literature_plausibility")
        self.assertEqual(result["direct_match_candidates"], [])

    def test_acquire_perturbation_source_records_separates_verified_from_unverified(self) -> None:
        acquisition = acquire_perturbation_source_records(
            context="NCI-H1373 RBN-2397 drug resistance CRISPR screen",
            genes=["MAU2", "GNAQ"],
            cell_line="NCI-H1373",
            perturbation="RBN-2397",
            phenotype="drug resistance",
            source_records=[
                {
                    "record_id": "screen",
                    "genes": ["MAU2"],
                    "source_type": "CRISPR screen",
                    "source_title": "PARP7 resistance screen",
                    "source_url": "https://example.test/parp7",
                    "finding": "MAU2 was enriched in NCI-H1373 cells treated with RBN-2397.",
                    "verified_fields": {
                        "genes": ["MAU2"],
                        "cell_line": "NCI-H1373",
                        "perturbation": "RBN-2397",
                        "phenotype": "drug resistance",
                    },
                    "support_spans": [
                        {
                            "field": "genes",
                            "value": "MAU2",
                            "source_text": "MAU2 was enriched in NCI-H1373 cells treated with RBN-2397.",
                        }
                    ],
                },
                {
                    "record_id": "generic",
                    "genes": ["GNAQ"],
                    "source_type": "literature",
                    "source_title": "Generic signaling review",
                    "source_url": "https://example.test/gnaq",
                    "finding": "GNAQ is a signaling gene.",
                },
            ],
        )

        self.assertEqual(acquisition["status"], "direct_source_records_found")
        self.assertEqual(acquisition["summary"]["source_record_count"], 2)
        self.assertEqual(acquisition["summary"]["direct_perturbation_source_record_count"], 1)
        self.assertEqual(acquisition["direct_perturbation_source_records"][0]["record_id"], "screen")
        self.assertEqual(acquisition["rejected_or_limited_records"][0]["record_id"], "generic")

    def test_extract_screen_table_evidence_records_verifies_local_table_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            table = f"{tmp}/screen.tsv"
            with open(table, "w", encoding="utf-8") as handle:
                handle.write("gene\tcell_line\tperturbation\tphenotype\tscore\n")
                handle.write("EGFR\tA549\tDMSO\tresistance\t9.2\n")
                handle.write("MYC\tA549\tDMSO\tresistance\t1.1\n")

            extracted = extract_screen_table_evidence_records(
                table,
                context="A549 DMSO resistance screen",
                genes=["EGFR", "MYC", "PTEN"],
                cell_line="A549",
                perturbation="DMSO",
                phenotype="resistance",
                source_title="A549 DMSO resistance supplementary table",
            )

        self.assertEqual(extracted["status"], "direct_source_records_found")
        self.assertEqual(extracted["table"]["emitted_source_record_count"], 2)
        self.assertEqual(extracted["summary"]["direct_perturbation_source_record_count"], 2)
        self.assertEqual(extracted["direct_perturbation_source_records"][0]["verification"]["status"], "verified")
        self.assertEqual(extracted["direct_perturbation_source_records"][0]["genes"], ["EGFR"])

    def test_screen_table_extract_operation_feeds_compare_operation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            table = f"{tmp}/screen.tsv"
            with open(table, "w", encoding="utf-8") as handle:
                handle.write("symbol\tcell line\ttreatment\treadout\tscore\n")
                handle.write("EGFR\tA549\tDMSO\tresistance\t9.2\n")
                handle.write("MYC\tA549\tDMSO\tresistance\t1.1\n")

            extracted = call_operation(
                "functional_genomics.import_perturbation_table",
                {
                    "table": table,
                    "context": "A549 DMSO resistance screen",
                    "genes": ["EGFR", "MYC"],
                    "cell_line": "A549",
                    "perturbation": "DMSO",
                    "phenotype": "resistance",
                    "source_title": "A549 DMSO resistance supplementary table",
                },
            )
            compared = call_operation(
                "functional_genomics.compare_gene_perturbation",
                {
                    "context": "A549 DMSO resistance screen",
                    "genes": ["EGFR", "MYC"],
                    "cell_line": "A549",
                    "perturbation": "DMSO",
                    "phenotype": "resistance",
                    "source_records": extracted["direct_perturbation_source_records"],
                },
            )

        self.assertEqual(compared["status"], "completed")
        self.assertEqual(compared["top_observed_candidate"], "EGFR")
        self.assertEqual(compared["decision_evidence"]["top_observed_evidence"]["supporting_evidence"][0]["record_id"], "table:screen.tsv:1:EGFR")

    def test_screen_answer_gene_uses_verified_records_and_abstains_without_direct_support(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict("os.environ", {"GENOMI_HOME": tmp}):
            direct = call_operation(
                "functional_genomics.compare_gene_perturbation",
                {
                    "context": "NCI-H1373 RBN-2397 resistance screen",
                    "genes": ["MAU2", "GNAQ"],
                    "cell_line": "NCI-H1373",
                    "perturbation": "RBN-2397",
                    "phenotype": "resistance",
                    "search_stored_research": False,
                    "source_records": [
                        {
                            "record_id": "screen",
                            "genes": ["MAU2"],
                            "source_type": "CRISPR screen",
                            "source_title": "PARP7 resistance screen",
                            "source_url": "https://example.test/parp7",
                            "finding": "MAU2 was enriched in NCI-H1373 cells treated with RBN-2397.",
                            "verified_fields": {
                                "genes": ["MAU2"],
                                "cell_line": "NCI-H1373",
                                "perturbation": "RBN-2397",
                                "phenotype": "resistance",
                            },
                        }
                    ],
                },
            )

            unverified = call_operation(
                "functional_genomics.compare_gene_perturbation",
                {
                    "context": "A549 DMSO resistance screen",
                    "genes": ["EGFR", "MYC"],
                    "cell_line": "A549",
                    "perturbation": "DMSO",
                    "phenotype": "resistance",
                    "search_stored_research": False,
                    "source_records": [
                        {
                            "record_id": "generic",
                            "genes": ["MYC"],
                            "source_type": "literature",
                            "source_title": "Generic chemoresistance paper",
                            "source_url": "https://example.test/gpr55",
                            "finding": "MYC has been discussed in chemoresistance.",
                        }
                    ],
                },
            )

        self.assertEqual(direct["status"], "completed")
        self.assertEqual(direct["top_observed_candidate"], "MAU2")
        self.assertEqual(direct["source_acquisition"]["status"], "direct_source_records_found")

        self.assertEqual(unverified["status"], "insufficient_source_evidence")
        self.assertIsNone(unverified["top_observed_candidate"])
        self.assertEqual(unverified["source_acquisition"]["status"], "unverified_source_records_only")

    def test_screen_source_catalog_entry_points_to_compare_tool(self) -> None:
        catalog = evidence_source_catalog(source_id="functional_genomics_perturbation_source")
        self.assertEqual(catalog["summary"]["source_count"], 1)
        source = catalog["sources"][0]
        self.assertEqual(source["adapter_status"], "implemented_native_retrieval_and_record_verification")
        self.assertIn("functional_genomics.retrieve_perturbation_records", source["genomi_operations"])
        self.assertIn("functional_genomics.query_geo", source["genomi_operations"])
        self.assertIn("functional_genomics.import_perturbation_table", source["genomi_operations"])
        self.assertIn("functional_genomics.compare_gene_perturbation", source["genomi_operations"])


if __name__ == "__main__":
    unittest.main()
