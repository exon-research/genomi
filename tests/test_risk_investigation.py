from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from genomi.capabilities.phenotype.risk import prepare_risk_investigation
from genomi.evidence import (
    import_clinvar_vcf,
    match_clinvar_variants,
    record_research_findings,
)
from genomi.evidence.sources import evidence_source_catalog

DATA_DIR = Path(__file__).parent / "data"
TINY_VCF = DATA_DIR / "tiny.gvcf.vcf"
TINY_CLINVAR = DATA_DIR / "tiny.clinvar.vcf"


class RiskInvestigationTests(unittest.TestCase):
    def test_public_cancer_question_plans_genecards_review_without_sample_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"
            record_research_findings(
                db,
                {
                    "target": {"type": "gene", "gene": "BRCA1"},
                    "source": {
                        "title": "Example Hereditary Cancer Source",
                        "url": "https://example.test/brca1",
                        "accessed_at": "2026-05-16T00:00:00+00:00",
                    },
                    "finding": {
                        "type": "hereditary_cancer_context",
                        "text": "BRCA1 is used here as a source-backed hereditary cancer review target.",
                    },
                },
            )

            result = prepare_risk_investigation(
                db,
                question="BRCA1 hereditary breast cancer risk",
                gene="BRCA1",
                investigation_type="cancer_risk",
            )

        self.assertEqual(result["schema"], "genomi-risk-investigation-v1")
        self.assertEqual(result["context_scope"], "public_only")
        self.assertEqual(result["target"]["investigation_type"], "cancer_risk")
        self.assertEqual(result["active_genome_index_evidence"]["status"], "not_selected")
        source_ids = [source["source_id"] for source in result["source_plan"]["source_order"]]
        self.assertIn("genecards", source_ids)
        self.assertIn("malacards", source_ids)
        self.assertIn("nci_cancer_genetics", source_ids)
        self.assertIn("cosmic_cancer_gene_census", source_ids)
        self.assertIn("BRCA1", result["source_plan"]["safe_external_targets"]["genes"])
        self.assertEqual(result["evidence_view"]["schema"], "genomi-candidate-evidence-view-v1")
        self.assertEqual(result["evidence_view"]["task_profile"]["profile_id"], "rare_disease_cancer_risk_investigation")
        self.assertTrue(result["evidence_view"]["agent_decision_required"])
        self.assertEqual(result["top_observed_candidate"], "gene:BRCA1")
        self.assertEqual(result["candidate_matrix"][0]["candidate_id"], "gene:BRCA1")
        self.assertEqual(result["candidate_matrix"][0]["best_evidence_lane"], "direct_source_match")

    def test_active_index_rare_disease_investigation_summarizes_matching_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"
            matches = Path(tmp) / "matches.jsonl"
            import_clinvar_vcf(TINY_CLINVAR, db, source_version="fixture")
            match_clinvar_variants(TINY_VCF, db, matches)

            result = prepare_risk_investigation(
                db,
                question="rare disease review for GENE2",
                gene="GENE2",
                matches=matches,
                investigation_type="rare_disease",
            )

        self.assertEqual(result["context_scope"], "active_genome_index_selected")
        self.assertEqual(result["active_genome_index_evidence"]["status"], "available")
        self.assertEqual(result["active_genome_index_evidence"]["summary"]["candidate_count"], 1)
        self.assertEqual(result["active_genome_index_evidence"]["result_state"], "candidate_inventory_hits_present")
        candidate = result["active_genome_index_evidence"]["candidate_summaries"][0]
        self.assertEqual(candidate["candidate_id"], "variant:1-10257-A-C")
        self.assertIn("GENE2", candidate["genes"])
        self.assertEqual(candidate["target_match_status"], "requested_gene_match")
        self.assertEqual(result["candidate_matrix"][0]["candidate_id"], "gene:GENE2")
        self.assertTrue(
            any(row["candidate_id"] == "variant:1-10257-A-C" for row in result["candidate_matrix"])
        )
        self.assertTrue(result["evidence_view"]["agent_decision_required"])

    def test_broad_active_index_zero_candidates_emits_scoped_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evidence.sqlite"
            matches = Path(tmp) / "matches.jsonl"
            import_clinvar_vcf(TINY_CLINVAR, db, source_version="fixture")
            matches.write_text("", encoding="utf-8")

            result = prepare_risk_investigation(
                db,
                question="any inherited genetic disease or cancer-risk findings worth worrying about?",
                matches=matches,
                investigation_type="cancer_risk",
            )

        active = result["active_genome_index_evidence"]
        self.assertEqual(active["status"], "available")
        self.assertEqual(active["summary"]["candidate_count"], 0)
        self.assertEqual(active["result_state"], "no_candidate_inventory_hits_in_selected_evidence_groups")
        # The unified envelope encodes the scoped-result and disallowed-negative.
        env = result["evidence_envelope"]
        self.assertEqual(env["schema"], "genomi-evidence-envelope-v1")
        self.assertEqual(env["operation"], "phenotype.plan_risk_investigation")
        self.assertEqual(env["finding_state"], "not_observed_in_consulted_scope")
        self.assertEqual(env["answer_readiness"], "scoped_answer_only")
        self.assertFalse(env["negative_inference"]["allowed"])
        self.assertIn("library_coverage", env["negative_inference"]["requires"])
        self.assertTrue(env["personal_context"]["uses_personal_dna"])
        # Guidance is centrally rendered.
        self.assertIn("not_observed_in_consulted_scope:do_not_imply_clinical_negative", env["guidance"])
        self.assertIn("negative_inference_disallowed:do_not_state_clinical_negative", env["guidance"])

    def test_source_catalog_includes_gene_cards_suite_for_risk_review(self) -> None:
        catalog = evidence_source_catalog(target_type="gene")
        source_ids = {source["source_id"] for source in catalog["sources"]}

        self.assertIn("genecards", source_ids)
        self.assertIn("malacards", source_ids)
        genecards = next(source for source in catalog["sources"] if source["source_id"] == "genecards")
        self.assertEqual(genecards["agent_contract"]["query_mode"], "focused_source_review")
        self.assertIn("phenotype.plan_risk_investigation", genecards["agent_contract"]["available_operations"])


if __name__ == "__main__":
    unittest.main()
