from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from genomi.active_genome_index.active_genome_index import create_active_genome_index
from genomi.capabilities.pharmacogenomics.review import review_medication_interaction
from genomi.operations import call_operation

from tests._pgx_review_helpers import PGxMedicationReviewTestBase


class PGxMedicationReviewSampleTests(PGxMedicationReviewTestBase):
    def test_review_uses_user_provided_known_sample_pgx_facts(self) -> None:
        clinpgx_result = {
            "source": {"source_id": "clinpgx"},
            "summary": {"guideline_annotation_count": 1, "clinical_annotation_count": 0, "label_annotation_count": 0},
            "sample_follow_up_targets": {"rsids": [], "genes": [{"symbol": "CYP2C19"}]},
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

        with (
            patch("genomi.capabilities.pharmacogenomics.review.clinpgx.lookup_clinpgx", return_value=clinpgx_result),
            patch("genomi.capabilities.pharmacogenomics.review.pgxdb.lookup_pgxdb", return_value=pgxdb_result),
            patch("genomi.capabilities.pharmacogenomics.review.pgx_star.call_star_alleles") as star_lookup,
        ):
            result = review_medication_interaction(
                drug="clopidogrel",
                known_diplotype="*1/*2",
                known_phenotype="Intermediate Metabolizer",
                known_pgx_source="outside PGx report",
            )

        self.assertEqual(result["sample_evidence"]["user_provided_sample_evidence_count"], 1)
        user_evidence = result["sample_evidence"]["user_provided_sample_evidence"][0]
        self.assertEqual(user_evidence["gene"], "CYP2C19")
        self.assertEqual(user_evidence["known_diplotype"], "*1/*2")
        self.assertEqual(user_evidence["known_phenotype"], "Intermediate Metabolizer")
        self.assertEqual(result["interpretation_readiness"]["personal_statement_support"], "source_and_sample_evidence_present")
        self.assertEqual(result["answer_support"]["status"], "source_and_sample_evidence_present")
        self.assertEqual(
            result["answer_support"]["technical_sample_support"]["status"],
            "user_provided_sample_pgx_evidence_available",
        )
        self.assertTrue(result["evidence_state"]["has_user_provided_sample_evidence"])
        self.assertTrue(result["evidence_state"]["has_sample_evidence"])
        self.assertEqual(
            result["answer_support"]["user_provided_sample_pgx_summaries"][0]["known_pgx_source"],
            "outside PGx report",
        )
        user_matrix_item = next(
            item
            for item in result["evidence_matrix"]["items"]
            if item["evidence_class"] == "user_provided_sample_pgx_evidence"
        )
        self.assertEqual(user_matrix_item["target"]["gene"], "CYP2C19")
        self.assertEqual(user_matrix_item["finding"]["known_diplotype"], "*1/*2")
        self.assertEqual(user_matrix_item["verification"]["status"], "user_provided_unverified")
        self.assertEqual(result["evidence_matrix"]["traceability"]["user_provided_unverified_item_count"], 1)
        self.assertEqual(result["pgx_evidence_scope"]["traceability"]["user_provided_unverified_item_count"], 1)
        components = {item["id"]: item for item in result["evidence_components"]["items"]}
        self.assertEqual(components["sample_variant_or_marker_evidence"]["state"], "present")
        self.assertEqual(components["technical_sample_support"]["state"], "user_provided")
        star_lookup.assert_called_once()

    def test_review_asks_for_target_when_known_sample_pgx_fact_is_ambiguous(self) -> None:
        clinpgx_result = {
            "source": {"source_id": "clinpgx"},
            "status": "completed",
            "summary": {"guideline_annotation_count": 1, "clinical_annotation_count": 0, "label_annotation_count": 0},
            "sample_follow_up_targets": {"rsids": [], "genes": []},
            "clinical_verification": {"requires_before_personal_actionability": []},
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

        with (
            patch("genomi.capabilities.pharmacogenomics.review.clinpgx.lookup_clinpgx", return_value=clinpgx_result),
            patch("genomi.capabilities.pharmacogenomics.review.pgxdb.lookup_pgxdb", return_value=pgxdb_result),
        ):
            result = review_medication_interaction(
                drug="clopidogrel",
                known_phenotype="Intermediate Metabolizer",
            )

        self.assertEqual(result["sample_evidence"]["user_provided_sample_evidence_count"], 0)
        self.assertTrue(result["evidence_state"]["has_public_pgx_evidence"])
        self.assertFalse(result["evidence_state"]["has_sample_evidence"])
        unanswered = {item["component"]: item for item in result["unanswered_answer_components"]}
        self.assertIn("sample_target_selection", unanswered)
        self.assertIn("pharmacogene", unanswered["sample_target_selection"]["missing_inputs"])

    def test_review_asks_for_refinement_when_public_sources_have_no_answer(self) -> None:
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
            "summary": {"pgx_record_count": 0, "gene_drug_record_count": 0, "variant_context_record_count": 0},
            "pgx_records": [],
            "gene_drug_records": [],
            "variant_context_records": [],
            "raw_calls": [],
            "record_research_payloads": [],
        }

        with (
            patch("genomi.capabilities.pharmacogenomics.review.clinpgx.lookup_clinpgx", return_value=clinpgx_result),
            patch("genomi.capabilities.pharmacogenomics.review.pgxdb.lookup_pgxdb", return_value=pgxdb_result),
        ):
            result = review_medication_interaction(drug="mysterymed", include_active_genome_index=True)

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "no_public_pgx_evidence")
        unanswered = {item["component"]: item for item in result["unanswered_answer_components"]}
        self.assertIn("public_pgx_evidence", unanswered)
        self.assertIn("broad_pgx_call_artifact", unanswered)
        self.assertIn("reviewed_public_pgx_source_evidence", unanswered["public_pgx_evidence"]["missing_inputs"])

    def test_review_asks_for_sample_target_when_source_evidence_has_no_sample_target(self) -> None:
        clinpgx_result = {
            "source": {"source_id": "clinpgx"},
            "status": "completed",
            "summary": {"guideline_annotation_count": 1, "clinical_annotation_count": 0, "label_annotation_count": 0},
            "sample_follow_up_targets": {"rsids": [], "genes": []},
            "clinical_verification": {"requires_before_personal_actionability": []},
            "raw_calls": [],
            "record_research_payloads": [],
        }
        pgxdb_result = {
            "source": {"source_id": "pgxdb"},
            "status": "no_matching_pgxdb_records",
            "summary": {"pgx_record_count": 0, "gene_drug_record_count": 0, "variant_context_record_count": 0},
            "pgx_records": [],
            "gene_drug_records": [],
            "variant_context_records": [],
            "raw_calls": [],
            "record_research_payloads": [],
        }

        with (
            patch("genomi.capabilities.pharmacogenomics.review.clinpgx.lookup_clinpgx", return_value=clinpgx_result),
            patch("genomi.capabilities.pharmacogenomics.review.pgxdb.lookup_pgxdb", return_value=pgxdb_result),
        ):
            result = review_medication_interaction(drug="clopidogrel", include_active_genome_index=True)

        unanswered = {item["component"]: item for item in result["unanswered_answer_components"]}
        self.assertIn("sample_target_selection", unanswered)
        components = {item["id"]: item for item in result["evidence_components"]["items"]}
        self.assertEqual(components["sample_target_selection"]["state"], "absent")

    def test_review_uses_supported_star_marker_coverage_for_gene_only_sample_support(self) -> None:
        clinpgx_result = {
            "source": {"source_id": "clinpgx"},
            "summary": {"guideline_annotation_count": 1, "clinical_annotation_count": 0, "label_annotation_count": 0},
            "sample_follow_up_targets": {"rsids": [], "genes": [{"symbol": "CYP2C19"}]},
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
        star_result = {
            "schema": "genomi-pgx-star-allele-call-v1",
            "ok": True,
            "status": "completed",
            "gene": "CYP2C19",
            "marker_calls": [{"evidence_status": "observed_reference_or_other_allele"}],
            "called_star_alleles": [],
            "diplotype": {"marker_support_status": "common_marker_subset_observed", "possible_diplotype": "*1/*1"},
        }

        with (
            patch("genomi.capabilities.pharmacogenomics.review.clinpgx.lookup_clinpgx", return_value=clinpgx_result),
            patch("genomi.capabilities.pharmacogenomics.review.pgxdb.lookup_pgxdb", return_value=pgxdb_result),
            patch("genomi.capabilities.pharmacogenomics.review.variant_lookup.lookup_variant") as variant_lookup,
            patch("genomi.capabilities.pharmacogenomics.review.pgx_star.call_star_alleles", return_value=star_result) as star_lookup,
        ):
            result = review_medication_interaction(drug="clopidogrel", gene="CYP2C19", has_active_genome_index_context=True)

        self.assertEqual(result["sample_evidence"]["rsid_targets"], [])
        self.assertEqual(result["sample_evidence"]["star_allele_call_count"], 1)
        self.assertTrue(result["interpretation_readiness"]["supported_star_marker_coverage"])
        self.assertEqual(result["interpretation_readiness"]["personal_statement_support"], "source_and_sample_evidence_present")
        self.assertTrue(result["target_inventory"]["pharmcat_context"]["active_genome_index_context_available"])
        self.assertEqual(result["target_inventory"]["implemented_marker_definition_genes"], ["CYP2C19"])
        variant_lookup.assert_not_called()
        star_lookup.assert_called_once()

    def test_star_marker_vcf_calls_produce_genotype_support_followups(self) -> None:
        clinpgx_result = {
            "source": {"source_id": "clinpgx"},
            "summary": {"guideline_annotation_count": 1, "clinical_annotation_count": 0, "label_annotation_count": 0},
            "sample_follow_up_targets": {"rsids": [], "genes": [{"symbol": "CYP2C19"}]},
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
        star_result = {
            "schema": "genomi-pgx-star-allele-call-v1",
            "ok": True,
            "status": "completed",
            "gene": "CYP2C19",
            "genome_build": "GRCh38",
            "marker_calls": [
                {
                    "rsid": "rs4244285",
                    "evidence_status": "observed_effect_allele",
                    "sample_calls": [
                        {
                            "agi_source_format": "vcf",
                            "chrom": "10",
                            "pos": 94761900,
                            "ref": "G",
                            "alt": "A",
                            "genotype": "0/1",
                        }
                    ],
                }
            ],
            "called_star_alleles": [{"star_allele": "*2", "function": "no_function", "rsid": "rs4244285"}],
            "diplotype": {"marker_support_status": "common_marker_subset_observed", "possible_diplotype": "*1/*2"},
        }

        with (
            patch("genomi.capabilities.pharmacogenomics.review.clinpgx.lookup_clinpgx", return_value=clinpgx_result),
            patch("genomi.capabilities.pharmacogenomics.review.pgxdb.lookup_pgxdb", return_value=pgxdb_result),
            patch("genomi.capabilities.pharmacogenomics.review.variant_lookup.lookup_variant") as variant_lookup,
            patch("genomi.capabilities.pharmacogenomics.review.pgx_star.call_star_alleles", return_value=star_result),
        ):
            result = review_medication_interaction(drug="clopidogrel", gene="CYP2C19", has_active_genome_index_context=True)

        self.assertEqual(
            result["target_inventory"]["genotype_support_loci"][0],
            {"chrom": "10", "pos": 94761900, "ref": "G", "alt": "A", "genome_build": "GRCh38"},
        )
        self.assertEqual(result["answer_support"]["technical_sample_support"]["status"], "needs_genotype_support")
        variant_lookup.assert_not_called()

    def test_star_marker_array_target_inventory_produces_genotype_support_followups(self) -> None:
        clinpgx_result = {
            "source": {"source_id": "clinpgx"},
            "summary": {"guideline_annotation_count": 1, "clinical_annotation_count": 0, "label_annotation_count": 0},
            "sample_follow_up_targets": {"rsids": [], "genes": [{"symbol": "CYP2C19"}]},
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
        star_result = {
            "schema": "genomi-pgx-star-allele-call-v1",
            "ok": True,
            "status": "completed",
            "gene": "CYP2C19",
            "genome_build": "GRCh37",
            "marker_calls": [
                {
                    "rsid": "rs4244285",
                    "evidence_status": "observed_effect_allele",
                    "sample_calls": [{"agi_source_format": "23andme", "genotype": "GA", "ref": "N", "alt": "GA"}],
                    "target_inventory": {
                        "genotype_support_loci": [
                            {"chrom": "10", "pos": 96541616, "ref": "G", "alt": "A", "genome_build": "GRCh37"}
                        ]
                    },
                }
            ],
            "called_star_alleles": [{"star_allele": "*2", "function": "no_function", "rsid": "rs4244285"}],
            "diplotype": {"marker_support_status": "common_marker_subset_observed", "possible_diplotype": "*1/*2"},
        }

        with (
            patch("genomi.capabilities.pharmacogenomics.review.clinpgx.lookup_clinpgx", return_value=clinpgx_result),
            patch("genomi.capabilities.pharmacogenomics.review.pgxdb.lookup_pgxdb", return_value=pgxdb_result),
            patch("genomi.capabilities.pharmacogenomics.review.variant_lookup.lookup_variant") as variant_lookup,
            patch("genomi.capabilities.pharmacogenomics.review.pgx_star.call_star_alleles", return_value=star_result),
        ):
            result = review_medication_interaction(drug="clopidogrel", gene="CYP2C19", has_active_genome_index_context=True)

        self.assertEqual(
            result["target_inventory"]["genotype_support_loci"],
            [{"chrom": "10", "pos": 96541616, "ref": "G", "alt": "A", "genome_build": "GRCh37"}],
        )
        variant_lookup.assert_not_called()

    def test_medication_review_uses_active_genome_index_without_source_path_leak(self) -> None:
        clinpgx_result = {
            "source": {"source_id": "clinpgx"},
            "summary": {"guideline_annotation_count": 1, "clinical_annotation_count": 0, "label_annotation_count": 0},
            "sample_follow_up_targets": {"rsids": ["rs4244285"], "genes": []},
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
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {"GENOMI_HOME": str(Path(tmp) / "genomi-home"), "GENOMI_CONTEXT": "", "GENOMI_SESSION_ID": ""},
        ):
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                vcf = Path("sample.vcf")
                vcf.write_text(
                    "##fileformat=VCFv4.2\n"
                    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE\n"
                    "10\t94761900\trs4244285\tG\tA\t.\tPASS\t.\tGT:DP:GQ\t0/1:38:99\n",
                    encoding="utf-8",
                )
                index = Path("active-genome-index.sqlite")
                create_active_genome_index(vcf, index, reuse_existing=False)
                call_operation(
                    "active_genome_index.assign_user_genome",
                    {
                        "nickname": "Test user",
                        "source": str(vcf),
                        "agi_path": str(index),
                        "genome_build": "GRCh38",
                    },
                )

                with (
                    patch("genomi.capabilities.pharmacogenomics.review.clinpgx.lookup_clinpgx", return_value=clinpgx_result),
                    patch("genomi.capabilities.pharmacogenomics.review.pgxdb.lookup_pgxdb", return_value=pgxdb_result),
                ):
                    result = call_operation("pharmacogenomics.review_medication", {"drug": "clopidogrel", "rsid": "rs4244285"})

                self.assertEqual(result["sample_evidence"]["sample_match_count"], 1)
                self.assertEqual(result["sample_evidence"]["variant_lookups"][0]["sample_context"]["matches"][0]["genotype"], "0/1")
                components = {item["id"]: item for item in result["evidence_components"]["items"]}
                self.assertEqual(components["sample_variant_or_marker_evidence"]["state"], "present")
                self.assertEqual(components["technical_sample_support"]["state"], "sample_signal_without_genotype_support")
                genotype_loci = result["target_inventory"]["genotype_support_loci"]
                self.assertEqual(len(genotype_loci), 1)
                self.assertEqual(
                    genotype_loci[0],
                    {"chrom": "10", "pos": 94761900, "ref": "G", "alt": "A", "genome_build": "GRCh38"},
                )
                self.assertEqual(
                    len({json.dumps(item, sort_keys=True) for item in genotype_loci}),
                    len(genotype_loci),
                )
                self.assertNotIn(str(vcf.resolve(strict=False)), json.dumps(result))
            finally:
                os.chdir(previous)

    def test_answer_support_marks_vcf_sample_evidence_as_technical_pending(self) -> None:
        clinpgx_result = {
            "source": {"source_id": "clinpgx"},
            "summary": {"guideline_annotation_count": 1, "clinical_annotation_count": 0, "label_annotation_count": 0},
            "sample_follow_up_targets": {"rsids": ["rs4244285"], "genes": []},
            "clinical_verification": {"requires_before_personal_actionability": []},
            "raw_calls": [],
            "record_research_payloads": [],
        }
        pgxdb_result = {
            "source": {"source_id": "pgxdb"},
            "summary": {"pgx_record_count": 1},
            "pgx_records": [
                {
                    "rsid": "rs4244285",
                    "variant_or_haplotype": "rs4244285",
                    "drug": "clopidogrel",
                    "alleles": "AA + AG",
                    "sentence": "Genotypes AA + AG are associated with decreased response to clopidogrel.",
                }
            ],
            "raw_calls": [],
            "record_research_payloads": [],
        }
        variant_result = {
            "query": {"rsid": "rs4244285", "genome_build": "GRCh38"},
            "sample_context": {
                "count": 1,
                "matches": [
                    {
                        "rsid": "rs4244285",
                        "genotype": "0/1",
                        "ref": "G",
                        "alt": "A",
                        "observed_alleles": ["G", "A"],
                        "agi_source_format": "vcf",
                        "chrom": "10",
                        "pos": 94761900,
                    }
                ],
            },
            "support_context": {"genotype_support": []},
        }

        with (
            patch("genomi.capabilities.pharmacogenomics.review.clinpgx.lookup_clinpgx", return_value=clinpgx_result),
            patch("genomi.capabilities.pharmacogenomics.review.pgxdb.lookup_pgxdb", return_value=pgxdb_result),
            patch("genomi.capabilities.pharmacogenomics.review.variant_lookup.lookup_variant", return_value=variant_result),
        ):
            result = review_medication_interaction(drug="clopidogrel", rsid="rs4244285", has_active_genome_index_context=True)

        self.assertEqual(result["answer_support"]["status"], "source_and_sample_evidence_present_technical_support_pending")
        self.assertEqual(result["answer_support"]["technical_sample_support"]["status"], "needs_genotype_support")
        self.assertTrue(result["evidence_state"]["has_sequencing_sample_signal"])
        self.assertFalse(result["evidence_state"]["has_genotype_support"])
        self.assertEqual(
            result["target_inventory"]["genotype_support_loci"],
            [{"chrom": "10", "pos": 94761900, "ref": "G", "alt": "A", "genome_build": "GRCh38"}],
        )
        self.assertEqual(result["answer_support"]["matched_variant_associations"][0]["match_status"], "reported_genotype_matches_sample")

    def test_array_sample_evidence_uses_resolved_target_inventory_for_genotype_support_followup(self) -> None:
        clinpgx_result = {
            "source": {"source_id": "clinpgx"},
            "summary": {"guideline_annotation_count": 1, "clinical_annotation_count": 0, "label_annotation_count": 0},
            "sample_follow_up_targets": {"rsids": ["rs4244285"], "genes": []},
            "clinical_verification": {"requires_before_personal_actionability": []},
            "raw_calls": [],
            "record_research_payloads": [],
        }
        pgxdb_result = {
            "source": {"source_id": "pgxdb"},
            "summary": {"pgx_record_count": 1},
            "pgx_records": [
                {
                    "rsid": "rs4244285",
                    "variant_or_haplotype": "rs4244285",
                    "drug": "clopidogrel",
                    "alleles": "GG",
                    "sentence": "Genotype GG is listed for clopidogrel response context.",
                }
            ],
            "raw_calls": [],
            "record_research_payloads": [],
        }
        variant_result = {
            "query": {"rsid": "rs4244285", "genome_build": "GRCh37"},
            "sample_context": {
                "count": 1,
                "matches": [
                    {
                        "rsid": "rs4244285",
                        "genotype": "GG",
                        "ref": "N",
                        "alt": "GG",
                        "agi_source_format": "23andme",
                        "chrom": "10",
                        "pos": 96541616,
                    }
                ],
            },
            "support_context": {"genotype_support": []},
            "target_inventory": {
                "genotype_support_loci": [
                    {"chrom": "10", "pos": 96541616, "ref": "G", "alt": "A", "genome_build": "GRCh37"}
                ]
            },
        }

        with (
            patch("genomi.capabilities.pharmacogenomics.review.clinpgx.lookup_clinpgx", return_value=clinpgx_result),
            patch("genomi.capabilities.pharmacogenomics.review.pgxdb.lookup_pgxdb", return_value=pgxdb_result),
            patch("genomi.capabilities.pharmacogenomics.review.variant_lookup.lookup_variant", return_value=variant_result),
        ):
            result = review_medication_interaction(drug="clopidogrel", rsid="rs4244285", has_active_genome_index_context=True)

        self.assertEqual(result["answer_support"]["technical_sample_support"]["status"], "observed_genotype_available")
        components = {item["id"]: item for item in result["evidence_components"]["items"]}
        self.assertEqual(components["technical_sample_support"]["state"], "observed")
        self.assertEqual(
            result["target_inventory"]["genotype_support_loci"],
            [{"chrom": "10", "pos": 96541616, "ref": "G", "alt": "A", "genome_build": "GRCh37"}],
        )

    def test_no_call_genotype_support_does_not_suppress_followup_loci(self) -> None:
        clinpgx_result = {
            "source": {"source_id": "clinpgx"},
            "summary": {"guideline_annotation_count": 1, "clinical_annotation_count": 0, "label_annotation_count": 0},
            "sample_follow_up_targets": {"rsids": ["rs4244285"], "genes": []},
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
        variant_result = {
            "query": {"rsid": "rs4244285", "genome_build": "GRCh37"},
            "sample_context": {
                "count": 1,
                "searched_active_genome_indexes": [{"agi_source_format": "23andme"}],
                "matches": [{"agi_source_format": "23andme", "genotype": "--"}],
            },
            "support_context": {"genotype_support": [{"support_status": "no_call"}]},
            "target_inventory": {
                "genotype_support_loci": [
                    {"chrom": "10", "pos": 96541616, "ref": "G", "alt": "A", "genome_build": "GRCh37"}
                ]
            },
        }

        with (
            patch("genomi.capabilities.pharmacogenomics.review.clinpgx.lookup_clinpgx", return_value=clinpgx_result),
            patch("genomi.capabilities.pharmacogenomics.review.pgxdb.lookup_pgxdb", return_value=pgxdb_result),
            patch("genomi.capabilities.pharmacogenomics.review.variant_lookup.lookup_variant", return_value=variant_result),
        ):
            result = review_medication_interaction(drug="clopidogrel", rsid="rs4244285", include_active_genome_index=True)

        self.assertFalse(result["evidence_state"]["has_genotype_support"])
        self.assertTrue(result["target_inventory"]["pharmcat_context"]["active_genome_index_context_available"])
        self.assertEqual(
            result["target_inventory"]["genotype_support_loci"],
            [{"chrom": "10", "pos": 96541616, "ref": "G", "alt": "A", "genome_build": "GRCh37"}],
        )

    def test_supported_pgx_locus_does_not_suppress_unresolved_followup_loci(self) -> None:
        clinpgx_result = {
            "source": {"source_id": "clinpgx"},
            "summary": {"guideline_annotation_count": 1, "clinical_annotation_count": 0, "label_annotation_count": 0},
            "sample_follow_up_targets": {"rsids": ["rs111111111", "rs222222222"], "genes": []},
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

        def fake_variant_lookup(*, rsid: str, genome_build: str, **_: object) -> dict[str, object]:
            if rsid == "rs111111111":
                return {
                    "query": {"rsid": rsid, "genome_build": genome_build},
                    "sample_context": {"count": 1, "matches": [{"rsid": rsid, "agi_source_format": "vcf", "genotype": "0/1"}]},
                    "support_context": {"genotype_support": [{"support_status": "supported"}]},
                    "target_inventory": {
                        "genotype_support_loci": [
                            {"chrom": "1", "pos": 111, "ref": "A", "alt": "G", "genome_build": genome_build}
                        ]
                    },
                }
            return {
                "query": {"rsid": rsid, "genome_build": genome_build},
                "sample_context": {"count": 1, "matches": [{"rsid": rsid, "agi_source_format": "vcf", "genotype": "0/1"}]},
                "support_context": {"genotype_support": []},
                "target_inventory": {
                    "genotype_support_loci": [
                        {"chrom": "2", "pos": 222, "ref": "C", "alt": "T", "genome_build": genome_build}
                    ]
                },
            }

        with (
            patch("genomi.capabilities.pharmacogenomics.review.clinpgx.lookup_clinpgx", return_value=clinpgx_result),
            patch("genomi.capabilities.pharmacogenomics.review.pgxdb.lookup_pgxdb", return_value=pgxdb_result),
            patch("genomi.capabilities.pharmacogenomics.review.variant_lookup.lookup_variant", side_effect=fake_variant_lookup),
        ):
            result = review_medication_interaction(drug="clopidogrel", include_active_genome_index=True)

        self.assertEqual(result["sample_evidence"]["technical_support_count"], 1)
        self.assertEqual(
            result["target_inventory"]["genotype_support_loci"],
            [{"chrom": "2", "pos": 222, "ref": "C", "alt": "T", "genome_build": "GRCh38"}],
        )

    def test_answer_support_matches_separator_genotype_expressions(self) -> None:
        clinpgx_result = {
            "source": {"source_id": "clinpgx"},
            "summary": {"guideline_annotation_count": 1, "clinical_annotation_count": 0, "label_annotation_count": 0},
            "sample_follow_up_targets": {"rsids": ["rs4244285"], "genes": []},
            "clinical_verification": {"requires_before_personal_actionability": []},
            "raw_calls": [],
            "record_research_payloads": [],
        }
        pgxdb_result = {
            "source": {"source_id": "pgxdb"},
            "summary": {"pgx_record_count": 1},
            "pgx_records": [
                {
                    "rsid": "rs4244285",
                    "variant_or_haplotype": "rs4244285",
                    "drug": "clopidogrel",
                    "alleles": "A/G",
                    "sentence": "Genotype A/G is associated with decreased response to clopidogrel.",
                }
            ],
            "raw_calls": [],
            "record_research_payloads": [],
        }
        variant_result = {
            "query": {"rsid": "rs4244285", "genome_build": "GRCh38"},
            "sample_context": {
                "count": 1,
                "matches": [
                    {
                        "rsid": "rs4244285",
                        "genotype": "0/1",
                        "ref": "G",
                        "alt": "A",
                        "observed_alleles": ["G", "A"],
                        "agi_source_format": "vcf",
                    }
                ],
            },
            "support_context": {"genotype_support": []},
        }

        with (
            patch("genomi.capabilities.pharmacogenomics.review.clinpgx.lookup_clinpgx", return_value=clinpgx_result),
            patch("genomi.capabilities.pharmacogenomics.review.pgxdb.lookup_pgxdb", return_value=pgxdb_result),
            patch("genomi.capabilities.pharmacogenomics.review.variant_lookup.lookup_variant", return_value=variant_result),
        ):
            result = review_medication_interaction(drug="clopidogrel", rsid="rs4244285", has_active_genome_index_context=True)

        match = result["answer_support"]["matched_variant_associations"][0]
        self.assertEqual(match["sample"]["canonical_genotype"], "AG")
        self.assertEqual(match["match_status"], "reported_genotype_matches_sample")
        self.assertIn("AG", match["match_evidence"]["reported_tokens"])



if __name__ == "__main__":
    import unittest

    unittest.main()
