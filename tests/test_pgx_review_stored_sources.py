from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from genomi.capabilities.pharmacogenomics.pharmcat import import_pharmcat_artifacts
from genomi.capabilities.pharmacogenomics.review import review_medication_interaction
from genomi.capabilities.research.intent_research import record_reviewed_research
from genomi.operations import call_operation, list_operations

from tests._pgx_review_helpers import PGxMedicationReviewTestBase


class PGxMedicationReviewStoredSourcesTests(PGxMedicationReviewTestBase):
    def test_medication_review_includes_stored_pgx_research(self) -> None:
        clinpgx_result = {
            "source": {"source_id": "clinpgx"},
            "summary": {"guideline_annotation_count": 1, "clinical_annotation_count": 0, "label_annotation_count": 0},
            "sample_follow_up_targets": {"rsids": [], "genes": []},
            "clinical_verification": {"requires_before_personal_actionability": []},
            "raw_calls": [],
            "record_research_payloads": [],
        }
        pgxdb_result = {
            "source": {"source_id": "pgxdb"},
            "summary": {"pgx_record_count": 0},
            "pgx_records": [],
            "raw_calls": [],
            "record_research_payloads": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            private_db = Path(tmp) / "private.sqlite"
            shared_db = Path(tmp) / "shared.sqlite"
            record_reviewed_research(
                private_db,
                {
                    "target": {"type": "drug", "drug": "clopidogrel"},
                    "source": {"title": "PharmCAT sample recommendation", "url": "https://pharmcat.clinpgx.org/", "type": "sample_pharmacogenomic_recommendation"},
                    "finding": {
                        "type": "pharmcat_sample_pgx_recommendation",
                        "text": "PharmCAT recommendation for clopidogrel; genes CYP2C19; recommendation consider an alternative antiplatelet therapy.",
                    },
                    "captured_by": "genomi call pharmacogenomics.run_pharmcat",
                },
                scope="private",
                sync_shared=False,
            )
            record_reviewed_research(
                private_db,
                {
                    "target": {"type": "drug", "drug": "clopidogrel"},
                    "source": {"title": "CPIC clopidogrel guideline", "url": "https://cpicpgx.org/guidelines/", "type": "guideline"},
                    "finding": {
                        "type": "clinpgx_guideline_annotation",
                        "text": "CPIC source-backed clopidogrel and CYP2C19 recommendation context.",
                    },
                    "captured_by": "genomi call pharmacogenomics.fetch_clinpgx",
                },
                scope="shared",
                shared_evidence_db=shared_db,
            )

            with (
                patch("genomi.capabilities.pharmacogenomics.review.clinpgx.lookup_clinpgx", return_value=clinpgx_result),
                patch("genomi.capabilities.pharmacogenomics.review.pgxdb.lookup_pgxdb", return_value=pgxdb_result),
            ):
                result = review_medication_interaction(
                    drug="clopidogrel",
                    gene="CYP2C19",
                    db=private_db,
                    shared_db=shared_db,
                )

        stored = result["public_evidence"]["stored_research"]
        self.assertEqual(stored["status"], "completed")
        self.assertGreaterEqual(stored["record_count"], 2)
        self.assertIn("private", {record["store"] for record in stored["records"]})
        self.assertIn("shared", {record["store"] for record in stored["records"]})
        self.assertTrue(any(record["finding"]["type"] == "pharmcat_sample_pgx_recommendation" for record in stored["records"]))
        self.assertNotIn(str(private_db), json.dumps(stored))
        self.assertNotIn(str(shared_db), json.dumps(stored))

    def test_stored_research_contributes_to_readiness_and_answer_support(self) -> None:
        clinpgx_result = {
            "source": {"source_id": "clinpgx"},
            "summary": {"guideline_annotation_count": 0, "clinical_annotation_count": 0, "label_annotation_count": 0},
            "sample_follow_up_targets": {"rsids": [], "genes": []},
            "clinical_verification": {"requires_before_personal_actionability": []},
            "raw_calls": [],
            "record_research_payloads": [],
        }
        pgxdb_result = {
            "source": {"source_id": "pgxdb"},
            "summary": {"pgx_record_count": 0},
            "pgx_records": [],
            "raw_calls": [],
            "record_research_payloads": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            private_db = Path(tmp) / "private.sqlite"
            shared_db = Path(tmp) / "shared.sqlite"
            record_reviewed_research(
                private_db,
                {
                    "target": {"type": "drug", "drug": "clopidogrel"},
                    "source": {
                        "title": "PharmCAT sample recommendation",
                        "url": "https://pharmcat.clinpgx.org/",
                        "type": "sample_pharmacogenomic_recommendation",
                    },
                    "finding": {
                        "type": "pharmcat_sample_pgx_recommendation",
                        "text": "PharmCAT recommendation for clopidogrel; genes CYP2C19; recommendation consider an alternative antiplatelet therapy.",
                    },
                    "captured_by": "genomi call pharmacogenomics.run_pharmcat",
                },
                scope="private",
                sync_shared=False,
            )
            record_reviewed_research(
                private_db,
                {
                    "target": {"type": "drug", "drug": "clopidogrel"},
                    "source": {"title": "CPIC clopidogrel guideline", "url": "https://cpicpgx.org/guidelines/", "type": "guideline"},
                    "finding": {
                        "type": "clinpgx_guideline_annotation",
                        "text": "CPIC source-backed clopidogrel and CYP2C19 recommendation context.",
                    },
                    "captured_by": "genomi call pharmacogenomics.fetch_clinpgx",
                },
                scope="shared",
                shared_evidence_db=shared_db,
            )

            with (
                patch("genomi.capabilities.pharmacogenomics.review.clinpgx.lookup_clinpgx", return_value=clinpgx_result),
                patch("genomi.capabilities.pharmacogenomics.review.pgxdb.lookup_pgxdb", return_value=pgxdb_result),
                patch("genomi.capabilities.pharmacogenomics.review.pgx_star.call_star_alleles") as star_lookup,
            ):
                result = review_medication_interaction(
                    drug="clopidogrel",
                    gene="CYP2C19",
                    db=private_db,
                    shared_db=shared_db,
                )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["public_evidence"]["live_public_evidence_count"], 0)
        self.assertGreaterEqual(result["public_evidence"]["stored_source_evidence_count"], 1)
        self.assertEqual(result["sample_evidence"]["stored_sample_evidence_count"], 1)
        self.assertEqual(result["interpretation_readiness"]["personal_statement_support"], "source_and_sample_evidence_present")
        self.assertEqual(result["answer_support"]["status"], "source_and_sample_evidence_present")
        self.assertEqual(
            result["answer_support"]["technical_sample_support"]["status"],
            "stored_sample_pgx_evidence_available",
        )
        self.assertTrue(result["answer_support"]["stored_sample_pgx_summaries"])
        components = {item["id"]: item for item in result["evidence_components"]["items"]}
        self.assertEqual(components["public_pgx_evidence"]["state"], "present")
        self.assertEqual(components["sample_variant_or_marker_evidence"]["state"], "present")
        star_lookup.assert_called_once()

    def test_drug_only_review_uses_stored_sample_evidence_for_discovered_gene(self) -> None:
        clinpgx_result = {
            "source": {"source_id": "clinpgx"},
            "summary": {"guideline_annotation_count": 1, "clinical_annotation_count": 0, "label_annotation_count": 0},
            "guideline_annotations": [
                {
                    "guideline_source": "CPIC",
                    "evidence_class": "guideline",
                    "name": "Clopidogrel and CYP2C19",
                    "summary": "CPIC clopidogrel and CYP2C19 source context.",
                    "source_url": "https://cpicpgx.org/guidelines/",
                }
            ],
            "sample_follow_up_targets": {"rsids": [], "genes": [{"symbol": "CYP2C19"}]},
            "clinical_verification": {"requires_before_personal_actionability": []},
            "raw_calls": [],
            "record_research_payloads": [],
        }
        pgxdb_result = {
            "source": {"source_id": "pgxdb"},
            "summary": {"pgx_record_count": 0, "medication_scoped_gene_drug_record_count": 0},
            "pgx_records": [],
            "medication_scoped_gene_drug_records": [],
            "raw_calls": [],
            "record_research_payloads": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            private_db = Path(tmp) / "private.sqlite"
            record_reviewed_research(
                private_db,
                {
                    "target": {"type": "gene", "gene": "CYP2C19"},
                    "source": {"title": "PharmCAT phenotyper JSON artifact", "url": "https://pharmcat.clinpgx.org/", "type": "sample_pharmacogenomic_call"},
                    "finding": {
                        "type": "pharmcat_sample_pgx_phenotype",
                        "text": "PharmCAT phenotype for CYP2C19; source diplotypes *1/*2 phenotype Intermediate Metabolizer.",
                    },
                    "captured_by": "genomi call pharmacogenomics.import_pharmcat_artifacts",
                },
                scope="private",
                sync_shared=False,
            )

            with (
                patch("genomi.capabilities.pharmacogenomics.review.clinpgx.lookup_clinpgx", return_value=clinpgx_result),
                patch("genomi.capabilities.pharmacogenomics.review.pgxdb.lookup_pgxdb", return_value=pgxdb_result),
                patch("genomi.capabilities.pharmacogenomics.review.pgx_star.call_star_alleles", return_value={"status": "completed", "marker_calls": [], "diplotype": {}}),
            ):
                result = review_medication_interaction(
                    drug="clopidogrel",
                    db=private_db,
                )

        self.assertEqual(result["query"]["gene"], None)
        self.assertEqual(result["sample_evidence"]["star_gene_targets"], ["CYP2C19"])
        self.assertEqual(result["sample_evidence"]["stored_sample_evidence_count"], 1)
        self.assertEqual(result["answer_support"]["status"], "source_and_sample_evidence_present")
        stored_targets = result["public_evidence"]["stored_research"]["traceability"]["targets"]
        self.assertIn({"target_type": "gene", "gene": "CYP2C19", "genome_build": "GRCh38"}, stored_targets)

    def test_imported_pharmcat_payloads_are_reused_by_medication_review(self) -> None:
        clinpgx_result = {
            "source": {"source_id": "clinpgx"},
            "summary": {"guideline_annotation_count": 1, "clinical_annotation_count": 0, "label_annotation_count": 0},
            "guideline_annotations": [
                {
                    "guideline_source": "CPIC",
                    "evidence_class": "guideline",
                    "name": "Clopidogrel and CYP2C19",
                    "summary": "CPIC clopidogrel and CYP2C19 source context.",
                    "source_url": "https://cpicpgx.org/guidelines/",
                }
            ],
            "sample_follow_up_targets": {"rsids": [], "genes": []},
            "clinical_verification": {"requires_before_personal_actionability": []},
            "raw_calls": [],
            "record_research_payloads": [],
        }
        pgxdb_result = {
            "source": {"source_id": "pgxdb"},
            "summary": {"pgx_record_count": 0, "medication_scoped_gene_drug_record_count": 0},
            "pgx_records": [],
            "medication_scoped_gene_drug_records": [],
            "raw_calls": [],
            "record_research_payloads": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            private_db = tmp_path / "private.sqlite"
            report = tmp_path / "sample.report.json"
            report.write_text(
                json.dumps(
                    {
                        "pharmcatVersion": "3.2.0",
                        "matcherMetadata": {"genomeBuild": "GRCh38", "sampleId": "sample"},
                        "drugs": {
                            "CPIC Guideline Annotation": {
                                "clopidogrel": {
                                    "name": "clopidogrel",
                                    "source": "CPIC",
                                    "urls": ["https://cpicpgx.org/guidelines/"],
                                    "guidelines": [
                                        {
                                            "source": "CPIC",
                                            "annotations": [
                                                {
                                                    "drugRecommendation": "Consider an alternative antiplatelet therapy.",
                                                    "genotypes": [
                                                        {
                                                            "diplotypes": [
                                                                {
                                                                    "gene": "CYP2C19",
                                                                    "allele1": {"name": "*1"},
                                                                    "allele2": {"name": "*2"},
                                                                    "phenotypes": ["Intermediate Metabolizer"],
                                                                }
                                                            ]
                                                        }
                                                    ],
                                                }
                                            ],
                                        }
                                    ],
                                }
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            imported = import_pharmcat_artifacts(report_json=report)
            self.assertTrue(imported["ok"])
            self.assertEqual(imported["record_research_payloads"][0]["captured_by"], "genomi call pharmacogenomics.import_pharmcat_artifacts")
            artifact_hash = imported["record_research_payloads"][0]["source"]["artifact"]["content_sha256"]
            record_reviewed_research(
                private_db,
                imported["record_research_payloads"],
                scope="private",
                sync_shared=False,
            )

            with (
                patch("genomi.capabilities.pharmacogenomics.review.clinpgx.lookup_clinpgx", return_value=clinpgx_result),
                patch("genomi.capabilities.pharmacogenomics.review.pgxdb.lookup_pgxdb", return_value=pgxdb_result),
            ):
                result = review_medication_interaction(
                    drug="clopidogrel",
                    gene="CYP2C19",
                    db=private_db,
                )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["sample_evidence"]["stored_sample_evidence_count"], 1)
        self.assertEqual(result["answer_support"]["status"], "source_and_sample_evidence_present")
        self.assertEqual(
            result["answer_support"]["technical_sample_support"]["status"],
            "stored_sample_pgx_evidence_available",
        )
        stored_sample = result["answer_support"]["stored_sample_pgx_summaries"][0]
        self.assertEqual(stored_sample["evidence_class"], "pharmcat_sample_pgx_recommendation")
        self.assertIn("alternative antiplatelet", stored_sample["summary"])
        self.assertEqual(stored_sample["source_artifact"]["content_sha256"], artifact_hash)
        matrix_item = next(
            item
            for item in result["evidence_matrix"]["items"]
            if item["evidence_class"] == "pharmcat_sample_pgx_recommendation"
        )
        self.assertEqual(matrix_item["source"]["artifact"]["content_sha256"], artifact_hash)
        self.assertIn(matrix_item["source"]["artifact"]["artifact_id"], result["evidence_matrix"]["traceability"]["artifact_ids"])
        self.assertEqual(result["evidence_matrix"]["traceability"]["artifact_item_count"], 1)

    def test_medication_review_can_include_full_record_research_payloads(self) -> None:
        clinpgx_result = {
            "source": {"source_id": "clinpgx"},
            "summary": {"guideline_annotation_count": 1, "clinical_annotation_count": 0, "label_annotation_count": 0},
            "sample_follow_up_targets": {"rsids": [], "genes": []},
            "clinical_verification": {"requires_before_personal_actionability": []},
            "raw_calls": [],
            "record_research_payloads": [
                {
                    "target": {"type": "drug", "drug": "clopidogrel"},
                    "finding": {"type": "clinpgx_guideline_annotation", "summary": "CPIC clopidogrel guidance."},
                }
            ],
        }
        pgxdb_result = {
            "source": {"source_id": "pgxdb"},
            "summary": {"pgx_record_count": 0},
            "pgx_records": [],
            "raw_calls": [],
            "record_research_payloads": [
                {
                    "target": {"type": "topic", "topic": "clopidogrel CYP2C19"},
                    "finding": {"type": "pgxdb_variant_context", "summary": "Context-only PGxDB row."},
                }
            ],
        }

        with (
            patch("genomi.capabilities.pharmacogenomics.review.clinpgx.lookup_clinpgx", return_value=clinpgx_result),
            patch("genomi.capabilities.pharmacogenomics.review.pgxdb.lookup_pgxdb", return_value=pgxdb_result),
        ):
            result = review_medication_interaction(
                drug="clopidogrel",
                include_record_research_payloads=True,
            )

        self.assertEqual(result["traceability"]["record_research_payload_count"], 2)
        self.assertEqual(
            result["traceability"]["record_research_payload_role_counts"],
            {"medication_source_evidence": 1, "context_only": 1},
        )
        self.assertEqual(len(result["traceability"]["record_research_payloads"]), 2)
        summaries = result["traceability"]["record_research_payload_summaries"]
        self.assertEqual([item["evidence_role"] for item in summaries], ["medication_source_evidence", "context_only"])

    def test_pgxdb_medication_scoped_gene_drug_rows_count_as_public_source_evidence(self) -> None:
        clinpgx_result = {
            "source": {"source_id": "clinpgx"},
            "summary": {"guideline_annotation_count": 0, "clinical_annotation_count": 0, "label_annotation_count": 0},
            "sample_follow_up_targets": {"rsids": [], "genes": []},
            "clinical_verification": {"requires_before_personal_actionability": []},
            "raw_calls": [],
            "record_research_payloads": [],
        }
        pgxdb_result = {
            "source": {"source_id": "pgxdb"},
            "summary": {
                "pgx_record_count": 0,
                "gene_drug_record_count": 1,
                "medication_scoped_gene_drug_record_count": 1,
                "variant_context_record_count": 0,
            },
            "pgx_records": [],
            "gene_drug_records": [
                {
                    "gene": "CYP2C19",
                    "drugbank_id": "DB00758",
                    "actions": "metabolizer",
                    "known_action": "yes",
                    "interaction_type": "drug-gene",
                }
            ],
            "medication_scoped_gene_drug_records": [
                {
                    "gene": "CYP2C19",
                    "drugbank_id": "DB00758",
                    "actions": "metabolizer",
                    "known_action": "yes",
                    "interaction_type": "drug-gene",
                    "target_scope": "selected_medication",
                }
            ],
            "variant_context_records": [],
            "raw_calls": [],
            "record_research_payloads": [],
        }

        with (
            patch("genomi.capabilities.pharmacogenomics.review.clinpgx.lookup_clinpgx", return_value=clinpgx_result),
            patch("genomi.capabilities.pharmacogenomics.review.pgxdb.lookup_pgxdb", return_value=pgxdb_result),
        ):
            result = review_medication_interaction(drug="clopidogrel", gene="CYP2C19")

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["public_evidence"]["source_evidence_count"], 1)
        components = {item["id"]: item for item in result["evidence_components"]["items"]}
        self.assertIn("pgxdb_gene_drug_context", components["public_pgx_evidence"]["evidence"]["classes"])
        summary_classes = {item["evidence_class"] for item in result["answer_support"]["source_recommendation_summaries"]}
        self.assertIn("pgxdb_gene_drug_context", summary_classes)

    def test_pgxdb_variant_context_rows_do_not_count_as_medication_evidence(self) -> None:
        clinpgx_result = {
            "source": {"source_id": "clinpgx"},
            "status": "no_matching_clinpgx_records",
            "summary": {"guideline_annotation_count": 0, "clinical_annotation_count": 0, "label_annotation_count": 0},
            "sample_follow_up_targets": {"rsids": [], "genes": []},
            "clinical_verification": {"requires_before_personal_actionability": []},
            "raw_calls": [],
            "record_research_payloads": [],
        }
        pgxdb_result = {
            "source": {"source_id": "pgxdb"},
            "status": "completed",
            "summary": {
                "pgx_record_count": 0,
                "gene_drug_record_count": 0,
                "medication_scoped_gene_drug_record_count": 0,
                "variant_context_record_count": 1,
            },
            "pgx_records": [],
            "gene_drug_records": [],
            "medication_scoped_gene_drug_records": [],
            "variant_context_records": [{"type": "association_statistics", "variant_marker": "rs4244285"}],
            "raw_calls": [],
            "record_research_payloads": [{"target": {"type": "topic", "topic": "rs4244285 PGxDB association_statistics"}}],
        }

        with (
            patch("genomi.capabilities.pharmacogenomics.review.clinpgx.lookup_clinpgx", return_value=clinpgx_result),
            patch("genomi.capabilities.pharmacogenomics.review.pgxdb.lookup_pgxdb", return_value=pgxdb_result),
        ):
            result = review_medication_interaction(drug="clopidogrel", gene="CYP2C19")

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "no_public_pgx_evidence")
        self.assertEqual(result["public_evidence"]["source_evidence_count"], 0)
        components = {item["id"]: item for item in result["evidence_components"]["items"]}
        self.assertNotIn("pgxdb_variant_context", components["public_pgx_evidence"]["evidence"]["classes"])
        summary_classes = {item["evidence_class"] for item in result["answer_support"]["source_recommendation_summaries"]}
        self.assertNotIn("pgxdb_variant_context", summary_classes)

    def test_stored_context_only_research_does_not_count_as_source_evidence(self) -> None:
        clinpgx_result = {
            "source": {"source_id": "clinpgx"},
            "status": "no_matching_clinpgx_records",
            "summary": {"guideline_annotation_count": 0, "clinical_annotation_count": 0, "label_annotation_count": 0},
            "sample_follow_up_targets": {"rsids": [], "genes": []},
            "clinical_verification": {"requires_before_personal_actionability": []},
            "raw_calls": [],
            "record_research_payloads": [],
        }
        pgxdb_result = {
            "source": {"source_id": "pgxdb"},
            "status": "no_matching_pgxdb_records",
            "summary": {"pgx_record_count": 0, "medication_scoped_gene_drug_record_count": 0},
            "pgx_records": [],
            "medication_scoped_gene_drug_records": [],
            "raw_calls": [],
            "record_research_payloads": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            private_db = Path(tmp) / "private.sqlite"
            record_reviewed_research(
                private_db,
                {
                    "target": {"type": "drug", "drug": "clopidogrel"},
                    "source": {"title": "PGxDB context", "url": "https://pgx-db.org/rest-api", "type": "variant_context"},
                    "finding": {
                        "type": "pgxdb_variant_context",
                        "text": "Context-only PGxDB row for clopidogrel; not a drug response recommendation.",
                    },
                    "captured_by": "genomi call pharmacogenomics.fetch_pgxdb",
                },
                scope="shared",
            )

            with (
                patch("genomi.capabilities.pharmacogenomics.review.clinpgx.lookup_clinpgx", return_value=clinpgx_result),
                patch("genomi.capabilities.pharmacogenomics.review.pgxdb.lookup_pgxdb", return_value=pgxdb_result),
            ):
                result = review_medication_interaction(drug="clopidogrel", db=private_db)

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "no_public_pgx_evidence")
        self.assertEqual(result["public_evidence"]["stored_research"]["record_count"], 1)
        self.assertEqual(result["public_evidence"]["stored_source_evidence_count"], 0)
        self.assertEqual(result["public_evidence"]["source_evidence_count"], 0)
        summary_classes = {item["evidence_class"] for item in result["answer_support"]["source_recommendation_summaries"]}
        self.assertNotIn("pgxdb_variant_context", summary_classes)
        matrix_classes = {item["evidence_class"] for item in result["evidence_matrix"]["items"]}
        self.assertNotIn("pgxdb_variant_context", matrix_classes)
        self.assertEqual(result["evidence_matrix"]["traceability"]["stored_reviewed_evidence_item_count"], 0)

    def test_record_research_initializes_missing_shared_db_parent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            private_db = tmp_path / "private.sqlite"
            genomi_home = tmp_path / "missing" / "genomi-home"

            with patch.dict(os.environ, {"GENOMI_HOME": str(genomi_home)}, clear=False):
                result = record_reviewed_research(
                    private_db,
                    {
                        "target": {"type": "drug", "drug": "clopidogrel"},
                        "source": {"title": "CPIC", "url": "https://cpicpgx.org/guidelines/", "type": "guideline"},
                        "finding": {"text": "Reviewed clopidogrel source context.", "type": "clinical_guideline"},
                        "captured_by": "test",
                    },
                    scope="shared",
                )

            shared_db = genomi_home / "shared-evidence.sqlite"
            self.assertEqual(result["shared_sync"]["status"], "completed")
            self.assertTrue(shared_db.exists())

    def test_unscoped_pgxdb_gene_drug_rows_do_not_count_as_medication_evidence(self) -> None:
        clinpgx_result = {
            "source": {"source_id": "clinpgx"},
            "status": "no_matching_clinpgx_records",
            "summary": {"guideline_annotation_count": 0, "clinical_annotation_count": 0, "label_annotation_count": 0},
            "sample_follow_up_targets": {"rsids": [], "genes": []},
            "clinical_verification": {"requires_before_personal_actionability": []},
            "raw_calls": [],
            "record_research_payloads": [],
        }
        pgxdb_result = {
            "source": {"source_id": "pgxdb"},
            "status": "completed",
            "summary": {
                "pgx_record_count": 0,
                "gene_drug_record_count": 1,
                "medication_scoped_gene_drug_record_count": 0,
                "variant_context_record_count": 0,
            },
            "pgx_records": [],
            "gene_drug_records": [
                {
                    "gene": "CYP2C19",
                    "drugbank_id": "DB00000",
                    "actions": "substrate",
                    "known_action": "unknown",
                    "interaction_type": "drug-gene",
                    "target_scope": "other_drug_for_gene",
                }
            ],
            "medication_scoped_gene_drug_records": [],
            "variant_context_records": [],
            "raw_calls": [],
            "record_research_payloads": [],
        }

        with (
            patch("genomi.capabilities.pharmacogenomics.review.clinpgx.lookup_clinpgx", return_value=clinpgx_result),
            patch("genomi.capabilities.pharmacogenomics.review.pgxdb.lookup_pgxdb", return_value=pgxdb_result),
        ):
            result = review_medication_interaction(drug="clopidogrel", gene="CYP2C19")

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "no_public_pgx_evidence")
        self.assertEqual(result["public_evidence"]["source_evidence_count"], 0)
        components = {item["id"]: item for item in result["evidence_components"]["items"]}
        self.assertNotIn("pgxdb_gene_drug_context", components["public_pgx_evidence"]["evidence"]["classes"])
        summary_classes = {item["evidence_class"] for item in result["answer_support"]["source_recommendation_summaries"]}
        self.assertNotIn("pgxdb_gene_drug_context", summary_classes)

    def test_fda_pgx_rows_count_as_public_source_evidence(self) -> None:
        clinpgx_result = {
            "source": {"source_id": "clinpgx"},
            "summary": {"guideline_annotation_count": 0, "clinical_annotation_count": 0, "label_annotation_count": 0},
            "sample_follow_up_targets": {"rsids": [], "genes": []},
            "clinical_verification": {"public_evidence_classes": [], "requires_before_personal_actionability": []},
            "raw_calls": [],
            "record_research_payloads": [],
        }
        pgxdb_result = {
            "source": {"source_id": "pgxdb"},
            "summary": {"pgx_record_count": 0, "gene_drug_record_count": 0, "variant_context_record_count": 0},
            "pgx_records": [],
            "gene_drug_records": [],
            "variant_context_records": [],
            "raw_calls": [],
            "record_research_payloads": [],
        }
        fda_result = {
            "source": {"source_id": "fda_pgx"},
            "status": "completed",
            "summary": {"biomarker_labeling_count": 1, "association_count": 1, "record_research_payload_count": 2},
            "rows": [
                {
                    "drug": "Clopidogrel",
                    "gene_or_biomarker": "CYP2C19",
                    "evidence_class": "fda_pharmacogenomic_biomarker_labeling",
                    "labeling_sections": "Boxed Warning",
                    "source_url": "https://www.fda.gov/drugs/science-and-research-drugs/table-pharmacogenomic-biomarkers-drug-labeling",
                },
                {
                    "drug": "Clopidogrel",
                    "gene_or_biomarker": "CYP2C19",
                    "evidence_class": "fda_pharmacogenetic_association",
                    "description": "Consider use of another platelet P2Y12 inhibitor.",
                    "source_url": "https://www.fda.gov/medical-devices/precision-medicine/table-pharmacogenetic-associations",
                },
            ],
            "raw_calls": [],
            "record_research_payloads": [{"target": {"type": "drug", "drug": "clopidogrel"}}],
        }

        with (
            patch("genomi.capabilities.pharmacogenomics.review.clinpgx.lookup_clinpgx", return_value=clinpgx_result),
            patch("genomi.capabilities.pharmacogenomics.review.pgxdb.lookup_pgxdb", return_value=pgxdb_result),
            patch("genomi.capabilities.pharmacogenomics.review.fda_pgx.lookup_fda_pgx", return_value=fda_result),
        ):
            result = review_medication_interaction(drug="clopidogrel", gene="CYP2C19")

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["public_evidence"]["source_evidence_count"], 2)
        components = {item["id"]: item for item in result["evidence_components"]["items"]}
        self.assertEqual(components["public_pgx_evidence"]["evidence"]["fda_pgx_summary"]["association_count"], 1)
        self.assertIn("fda_pharmacogenomic_biomarker_labeling", components["public_pgx_evidence"]["evidence"]["classes"])
        self.assertIn("fda_pharmacogenetic_association", components["public_pgx_evidence"]["evidence"]["classes"])
        summary_classes = {item["evidence_class"] for item in result["answer_support"]["source_recommendation_summaries"]}
        self.assertIn("fda_pharmacogenomic_biomarker_labeling", summary_classes)
        self.assertIn("fda_pharmacogenetic_association", summary_classes)

    def test_source_availability_reports_unavailable_sources(self) -> None:
        clinpgx_result = {
            "source": {"source_id": "clinpgx"},
            "status": "source_unavailable",
            "summary": {"guideline_annotation_count": 0, "clinical_annotation_count": 0, "label_annotation_count": 0},
            "sample_follow_up_targets": {"rsids": [], "genes": []},
            "clinical_verification": {"requires_before_personal_actionability": []},
            "raw_calls": [{"url": "https://api.pharmgkb.org/v1/data/chemical", "status": None, "error": "timeout"}],
            "warnings": [{"url": "https://api.pharmgkb.org/v1/data/chemical", "status": None, "error": "timeout"}],
            "record_research_payloads": [],
        }
        pgxdb_result = {
            "source": {"source_id": "pgxdb"},
            "status": "source_unavailable",
            "summary": {"pgx_record_count": 0, "gene_drug_record_count": 0, "variant_context_record_count": 0},
            "pgx_records": [],
            "gene_drug_records": [],
            "variant_context_records": [],
            "raw_calls": [{"url": "https://pgx-db.org/rest-api/atc/atc_code/CS/", "status": None, "error": "timeout"}],
            "warnings": [{"url": "https://pgx-db.org/rest-api/atc/atc_code/CS/", "status": None, "error": "timeout"}],
            "record_research_payloads": [],
        }

        with (
            patch("genomi.capabilities.pharmacogenomics.review.clinpgx.lookup_clinpgx", return_value=clinpgx_result),
            patch("genomi.capabilities.pharmacogenomics.review.pgxdb.lookup_pgxdb", return_value=pgxdb_result),
        ):
            result = review_medication_interaction(drug="clopidogrel")

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "source_unavailable")
        availability = result["public_evidence"]["source_availability"]
        self.assertEqual(availability["status"], "source_unavailable_no_evidence")
        self.assertEqual(availability["unavailable_source_count"], 2)
        self.assertEqual(result["pgx_evidence_scope"]["status"], "source_unavailable")
        self.assertEqual(result["pgx_evidence_scope"]["checked"]["source_unavailable_count"], 2)
        self.assertEqual(result["traceability"]["source_availability"], availability)
        unanswered = {item["component"]: item for item in result["unanswered_answer_components"]}
        self.assertIn("public_pgx_evidence", unanswered)

    def test_source_availability_keeps_evidence_with_warnings_usable(self) -> None:
        clinpgx_result = {
            "source": {"source_id": "clinpgx"},
            "status": "completed",
            "summary": {"guideline_annotation_count": 1, "clinical_annotation_count": 0, "label_annotation_count": 0},
            "sample_follow_up_targets": {"rsids": [], "genes": []},
            "clinical_verification": {"requires_before_personal_actionability": []},
            "raw_calls": [{"url": "https://api.pharmgkb.org/v1/data/guidelineAnnotation", "status": 200}],
            "record_research_payloads": [],
        }
        pgxdb_result = {
            "source": {"source_id": "pgxdb"},
            "status": "completed",
            "summary": {"pgx_record_count": 1, "gene_drug_record_count": 0, "variant_context_record_count": 0},
            "pgx_records": [{"drug": "clopidogrel", "sentence": "A PGxDB association row.", "atc_code": "B01AC04"}],
            "gene_drug_records": [],
            "variant_context_records": [],
            "raw_calls": [{"url": "https://pgx-db.org/rest-api/atc/pgx/B01AC04/", "status": 200}],
            "warnings": [{"url": "https://pgx-db.org/rest-api/gene/drug/", "status": None, "error": "timeout"}],
            "record_research_payloads": [],
        }

        with (
            patch("genomi.capabilities.pharmacogenomics.review.clinpgx.lookup_clinpgx", return_value=clinpgx_result),
            patch("genomi.capabilities.pharmacogenomics.review.pgxdb.lookup_pgxdb", return_value=pgxdb_result),
        ):
            result = review_medication_interaction(drug="clopidogrel")

        availability = result["public_evidence"]["source_availability"]
        self.assertEqual(result["status"], "completed")
        self.assertEqual(availability["status"], "source_evidence_available_with_warnings")
        self.assertEqual(availability["unavailable_source_count"], 0)
        self.assertEqual(availability["warning_source_count"], 1)
        self.assertEqual(result["pgx_evidence_scope"]["status"], "bounded_evidence_with_source_warnings")
        self.assertEqual(result["pgx_evidence_scope"]["checked"]["source_availability_status"], "source_evidence_available_with_warnings")
        self.assertEqual(result["pgx_evidence_scope"]["checked"]["source_warning_count"], 1)
        by_source = {source["source_id"]: source for source in availability["sources"]}
        self.assertEqual(by_source["pgxdb"]["availability"], "evidence_available_with_warnings")

    def test_medication_review_is_agent_tool(self) -> None:
        tools = {tool["name"]: tool for tool in list_operations(capability="pharmacogenomics")}
        self.assertIn("pharmacogenomics.review_medication", tools)
        self.assertEqual(tools["pharmacogenomics.review_medication"]["annotations"]["externalIO"], ["clinpgx_api", "pgxdb_api", "fda_web"])
        self.assertEqual(tools["pharmacogenomics.review_medication"]["annotations"]["privacyScope"], "target_scoped")
        self.assertEqual(tools["pharmacogenomics.review_medication"]["annotations"]["discoveryRole"], "entry_tool")

    def test_call_operation_uses_medication_review(self) -> None:
        with patch(
            "genomi.operations.pgx.review_medication_interaction",
            return_value={"schema": "genomi-pgx-medication-review-v1", "status": "completed"},
        ) as review:
            result = call_operation(
                "pharmacogenomics.review_medication",
                {
                    "drug": "clopidogrel",
                    "gene": "CYP2C19",
                    "indication": "post-PCI antiplatelet therapy",
                    "dose": "75 mg daily",
                    "current_medications": "aspirin",
                    "allergies_or_contraindications": "none known",
                    "include_record_research_payloads": True,
                    "fda_biomarkers_url": "https://example.test/biomarkers",
                    "fda_associations_url": "https://example.test/associations",
                },
            )

        self.assertEqual(result["status"], "completed")
        review.assert_called_once()
        self.assertEqual(review.call_args.kwargs["drug"], "clopidogrel")
        self.assertEqual(review.call_args.kwargs["gene"], "CYP2C19")
        self.assertEqual(review.call_args.kwargs["indication"], "post-PCI antiplatelet therapy")
        self.assertEqual(review.call_args.kwargs["dose"], "75 mg daily")
        self.assertEqual(review.call_args.kwargs["current_medications"], "aspirin")
        self.assertEqual(review.call_args.kwargs["allergies_or_contraindications"], "none known")
        self.assertTrue(review.call_args.kwargs["include_record_research_payloads"])
        self.assertEqual(review.call_args.kwargs["fda_biomarkers_url"], "https://example.test/biomarkers")
        self.assertEqual(review.call_args.kwargs["fda_associations_url"], "https://example.test/associations")
        self.assertFalse(review.call_args.kwargs["include_active_genome_index"])


if __name__ == "__main__":
    import unittest

    unittest.main()
