from __future__ import annotations

import json
import unittest

from _gwas_helpers import _association

from genomi.capabilities.gwas.gwas import (
    compare_gwas_variant_evidence,
)


class GwasCatalogVariantTests(unittest.TestCase):
    def test_compare_gwas_variant_evidence_ranks_candidate_by_trait_and_pvalue(self) -> None:
        def fake_fetch(url: str) -> dict:
            if "rs3738934" in url:
                return {
                    "_embedded": {
                        "associations": [
                            _association(
                                "rs3738934",
                                "bradykinin level",
                                1e-8,
                                "rs3738934-C",
                                "KLKB1",
                                "GCST1",
                                "101",
                            ),
                            _association(
                                "rs3738934",
                                "white blood cell count",
                                1e-20,
                                "rs3738934-T",
                                "KLKB1",
                                "GCST2",
                                "102",
                            ),
                        ]
                    }
                }
            if "rs7700133" in url:
                return {
                    "_embedded": {
                        "associations": [
                            _association(
                                "rs7700133",
                                "bradykinin level",
                                5e-7,
                                "rs7700133-A",
                                "GENE1",
                                "GCST3",
                                "103",
                            )
                        ]
                    }
                }
            return {"_embedded": {"associations": []}}

        result = compare_gwas_variant_evidence(
            "Bradykinin",
            ["rs7700133", "rs3738934", "rs1280"],
            fetch_json=fake_fetch,
        )

        self.assertEqual(result["summary"]["variant_count"], 3)
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["summary"]["matched_association_count"], 2)
        self.assertEqual(result["summary"]["top_variant"], "rs3738934")
        self.assertEqual(result["summary"]["top_observed_candidate"], "rs3738934")
        self.assertEqual(result["top_observed"]["candidate_id"], "rs3738934")
        self.assertEqual(result["top_observed"]["answerability"], "direct_source_supported")
        self.assertEqual(result["top_observed"]["best_evidence_lane"], "exact_trait_match")
        self.assertEqual([row["candidate_id"] for row in result["candidate_matrix"]], ["rs3738934", "rs7700133", "rs1280"])
        view = result["evidence_view"]
        self.assertEqual(view["schema"], "genomi-candidate-evidence-view-v1")
        self.assertEqual(view["task_profile"]["profile_id"], "gwas_variant_prioritization")
        self.assertNotIn("same_gene_or_locus", view["task_profile"]["preferred_evidence_lanes"])
        self.assertNotIn("pathway_plausibility", view["task_profile"]["preferred_evidence_lanes"])
        self.assertNotIn("literature_plausibility", view["task_profile"]["ranking_weights"])
        self.assertEqual(view["top_observed"]["candidate_id"], result["top_observed"]["candidate_id"])
        self.assertEqual(view["coverage"]["top_observed_candidate"], "rs3738934")
        self.assertEqual(view["candidate_matrix"], result["candidate_matrix"])
        self.assertEqual(result["unmatched_candidates"], ["rs1280"])
        self.assertEqual(result["top_association"]["study"]["disease_trait"], "bradykinin level")
        self.assertEqual(result["top_association"]["risk_alleles"], ["rs3738934-C"])
        self.assertEqual(result["top_association"]["reported_genes"], ["KLKB1"])
        self.assertEqual(result["top_record_research_payload"]["finding"]["type"], "gwas_association")
        self.assertIn("rs3738934", result["top_record_research_payload"]["target"]["topic"])
        self.assertEqual(result["evidence_context"]["skill_contract"]["path"], "SKILL.md")

    def test_compare_gwas_variant_evidence_returns_structured_source_failure(self) -> None:
        def fake_fetch(_url: str) -> dict:
            raise json.JSONDecodeError("bad", "not json", 0)

        result = compare_gwas_variant_evidence(
            "erythritol",
            ["rs2000999", "rs6687813"],
            fetch_json=fake_fetch,
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "source_unavailable")
        self.assertEqual(result["summary"]["matched_association_count"], 0)
        self.assertEqual(len(result["errors"]), 2)

    def test_compare_gwas_variant_evidence_no_match_is_successful_empty_lookup(self) -> None:
        result = compare_gwas_variant_evidence(
            "erythritol",
            ["rs2000999"],
            fetch_json=lambda _url: {"_embedded": {"associations": []}},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "no_matching_gwas_associations")
        self.assertEqual(result["summary"]["matched_association_count"], 0)
        self.assertIsNone(result["top_observed"])
        self.assertEqual(result["candidate_matrix"], [])
        self.assertEqual(result["evidence_view"]["coverage"]["candidate_count"], 1)
        self.assertIsNone(result["evidence_view"]["coverage"]["top_observed_candidate"])
        self.assertEqual(result["evidence_view"]["unmatched_candidates"], ["rs2000999"])

    def test_compare_gwas_variant_evidence_ignores_low_information_numeric_token_overlap(self) -> None:
        def fake_fetch(url: str) -> dict:
            if "rs4921914" in url:
                return {
                    "_embedded": {
                        "associations": [
                            _association(
                                "rs4921914",
                                "5-acetylamino-6-formylamino-3-methyluracil levels",
                                2e-54,
                                "rs4921914-A",
                                "NAT2",
                                "GCST4",
                                "104",
                            )
                        ]
                    }
                }
            return {"_embedded": {"associations": []}}

        result = compare_gwas_variant_evidence(
            "5-Hydroxy-L-tryptophan",
            ["rs2160860", "rs4921914"],
            fetch_json=fake_fetch,
        )

        self.assertEqual(result["status"], "no_matching_gwas_associations")
        self.assertEqual(result["summary"]["matched_association_count"], 0)
        self.assertIsNone(result["top_observed"])
        self.assertEqual(result["unmatched_candidates"], ["rs2160860", "rs4921914"])

    def test_compare_gwas_variant_evidence_exact_trait_match_beats_lower_pvalue_nearby_trait(self) -> None:
        def fake_fetch(url: str) -> dict:
            if "rsExact" in url:
                return {
                    "_embedded": {
                        "associations": [
                            _association(
                                "rsExact",
                                "D-glucose levels",
                                1e-8,
                                "rsExact-A",
                                "GENE1",
                                "GCST5",
                                "105",
                            )
                        ]
                    }
                }
            if "rsNearby" in url:
                return {
                    "_embedded": {
                        "associations": [
                            _association(
                                "rsNearby",
                                "fasting insulin and glucose metabolism",
                                1e-100,
                                "rsNearby-G",
                                "GENE2",
                                "GCST6",
                                "106",
                            )
                        ]
                    }
                }
            return {"_embedded": {"associations": []}}

        result = compare_gwas_variant_evidence(
            "D-glucose",
            ["rsNearby", "rsExact"],
            fetch_json=fake_fetch,
        )

        self.assertEqual(result["top_observed"]["candidate_id"], "rsExact")
        self.assertEqual(result["top_observed"]["best_evidence_lane"], "exact_trait_match")
        nearby = next(row for row in result["candidate_matrix"] if row["candidate_id"] == "rsNearby")
        self.assertIn("weaker than selected lane", nearby["why_not_selected"][0])

    def test_compare_gwas_variant_evidence_matches_hyphenated_metabolite_terms(self) -> None:
        def fake_fetch(url: str) -> dict:
            if "rs2160860" in url:
                return {
                    "_embedded": {
                        "associations": [
                            _association(
                                "rs2160860",
                                "X-12100--hydroxytryptophan levels",
                                7e-11,
                                "rs2160860-T",
                                "GENE1",
                                "GCST7",
                                "107",
                            )
                        ]
                    }
                }
            if "rs4921914" in url:
                return {
                    "_embedded": {
                        "associations": [
                            _association(
                                "rs4921914",
                                "5-acetylamino-6-formylamino-3-methyluracil levels",
                                2e-54,
                                "rs4921914-A",
                                "NAT2",
                                "GCST8",
                                "108",
                            )
                        ]
                    }
                }
            return {"_embedded": {"associations": []}}

        result = compare_gwas_variant_evidence(
            "5-Hydroxy-L-tryptophan",
            ["rs4921914", "rs2160860"],
            fetch_json=fake_fetch,
        )

        self.assertEqual(result["top_observed"]["candidate_id"], "rs2160860")
        self.assertEqual(result["top_observed"]["best_evidence_lane"], "exact_trait_match")

    def test_compare_gwas_variant_evidence_treats_measurement_and_levels_as_trait_qualifiers(self) -> None:
        def fake_fetch(url: str) -> dict:
            if "rsTransformed" in url:
                return {
                    "_embedded": {
                        "associations": [
                            _association(
                                "rsTransformed",
                                "high density lipoprotein cholesterol (HDLC, mean, inv-norm transformed)",
                                3e-43,
                                "rsTransformed-A",
                                "GENE1",
                                "GCST9",
                                "109",
                            )
                        ]
                    }
                }
            if "rsLevels" in url:
                return {
                    "_embedded": {
                        "associations": [
                            _association(
                                "rsLevels",
                                "high density lipoprotein cholesterol levels",
                                2e-9,
                                "rsLevels-C",
                                "GENE2",
                                "GCST10",
                                "110",
                            )
                        ]
                    }
                }
            return {"_embedded": {"associations": []}}

        result = compare_gwas_variant_evidence(
            "high density lipoprotein cholesterol measurement",
            ["rsTransformed", "rsLevels"],
            fetch_json=fake_fetch,
        )

        self.assertEqual(result["top_observed"]["candidate_id"], "rsLevels")
        self.assertEqual(result["top_observed"]["best_evidence_lane"], "exact_trait_match")
        transformed = next(row for row in result["candidate_matrix"] if row["candidate_id"] == "rsTransformed")
        self.assertEqual(transformed["best_evidence_lane"], "nearby_trait_match")

    def test_compare_gwas_variant_evidence_uses_host_semantic_trait_hint(self) -> None:
        def fake_fetch(url: str) -> dict:
            if "rs429358" in url:
                return {
                    "_embedded": {
                        "associations": [
                            _association("rs429358", "Alzheimer disease", 1e-10, "rs429358-C", "APOE", "GCSTAD", "201")
                        ]
                    }
                }
            return {"_embedded": {"associations": []}}

        result = compare_gwas_variant_evidence(
            "memory risk",
            ["rs429358"],
            fetch_json=fake_fetch,
            semantic_context={
                "raw_query": "What does my DNA say about Alzheimer's risk?",
                "host_expansions": ["Alzheimer disease"],
                "host_entities": [{"text": "Alzheimer disease", "type": "trait_or_condition"}],
            },
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["top_observed"]["candidate_id"], "rs429358")
        accepted = {item["text"] for item in result["semantic_context"]["term_matches"]}
        self.assertIn("Alzheimer disease", accepted)


if __name__ == "__main__":
    unittest.main()
