from __future__ import annotations

import unittest

from genomi.capabilities.pharmacogenomics.pgx_requirements import (
    pharmacogene_requirements,
)
from genomi.operations import call_operation, list_operations


class PGxGeneRequirementTests(unittest.TestCase):
    def test_cyp2d6_requires_outside_sv_cnv_aware_calling(self) -> None:
        result = pharmacogene_requirements(gene="CYP2D6")
        record = result["records"][0]

        self.assertEqual(result["status"], "completed")
        self.assertEqual(record["gene"], "CYP2D6")
        self.assertEqual(record["category"], "outside_call_recommended")
        self.assertIn("SV/CNV-aware CYP2D6 caller output", record["preferred_evidence"])
        self.assertIn("StellarPGx", record["candidate_callers"])
        self.assertIn("pharmacogenomics.prepare_outside_call_tsv", record["candidate_tools"])
        self.assertIn("pharmacogenomics.validate_outside_call_tsv", record["candidate_tools"])
        self.assertIn("pharmacogenomics.run_pharmcat", record["candidate_tools"])
        self.assertTrue(any("Calling-CYP2D6" in url for url in record["source_urls"]))

    def test_g6pd_reports_chr_x_representation_requirements(self) -> None:
        result = pharmacogene_requirements(gene="g6pd")
        record = result["records"][0]

        self.assertEqual(record["gene"], "G6PD")
        self.assertEqual(record["category"], "sex_chromosome_representation_sensitive")
        self.assertTrue(any("chrX" in item for item in record["sample_evidence_requirements"]))
        self.assertTrue(any("faqs" in url for url in record["source_urls"]))

    def test_catalog_lists_matcher_and_outside_call_genes(self) -> None:
        result = pharmacogene_requirements()
        categories = {record["category"] for record in result["records"]}

        self.assertIn("pharmcat_named_allele_matcher", categories)
        self.assertIn("outside_call_required", categories)
        self.assertGreaterEqual(result["summary"]["named_allele_matcher_gene_count"], 20)
        self.assertEqual(result["summary"]["outside_call_gene_count"], 4)

    def test_unknown_gene_asks_for_source_context(self) -> None:
        result = pharmacogene_requirements(gene="GENELESS")

        self.assertEqual(result["records"][0]["category"], "not_in_catalog")

    def test_gene_requirements_is_agent_operation(self) -> None:
        tools = {tool["name"]: tool for tool in list_operations(capability="pharmacogenomics")}

        self.assertIn("pharmacogenomics.describe_gene_requirements", tools)
        tool = tools["pharmacogenomics.describe_gene_requirements"]
        annotations = tool["annotations"]
        properties = tool["inputSchema"]["properties"]

        self.assertEqual(annotations["operationScope"], "read")
        self.assertFalse(annotations["mutating"])
        self.assertEqual(annotations["privacyScope"], "metadata_only")
        self.assertIn("pharmacogene_requirement_catalog", annotations["produces"])
        self.assertEqual(set(properties), {"gene", "semantic_context"})

    def test_call_operation_uses_gene_requirements(self) -> None:
        result = call_operation("pharmacogenomics.describe_gene_requirements", {"gene": "HLA-B"})

        self.assertEqual(result["records"][0]["gene"], "HLA-B")
        self.assertEqual(result["records"][0]["category"], "outside_call_required")
        self.assertEqual(result["query"], {"gene": "HLA-B"})
        self.assertEqual(
            set(result),
            {"evidence_envelope", "status", "query", "records", "summary", "source_documents"},
        )
        self.assertEqual(result["evidence_envelope"]["operation"], "pharmacogenomics.describe_gene_requirements")


if __name__ == "__main__":
    unittest.main()
