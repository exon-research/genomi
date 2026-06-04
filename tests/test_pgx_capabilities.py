from __future__ import annotations

import unittest
from unittest.mock import patch

from genomi.capabilities.pharmacogenomics.review import capability_inventory
from genomi.operations import list_operations


class PGxCapabilityInventoryTests(unittest.TestCase):
    def test_capability_inventory_lists_pgx_evidence_paths(self) -> None:
        result = capability_inventory()

        self.assertEqual(result["status"], "completed")
        self.assertIn("public_source_evidence", result["capability_axes"])
        self.assertIn("targeted_sample_evidence", result["capability_axes"])
        self.assertIn("implemented_marker_definition_sets", result["capability_axes"])
        self.assertIn("pharmacogene_requirement_catalog", result["capability_axes"])
        self.assertIn("broad_vcf_pgx_calling", result["capability_axes"])
        marker_axis = result["capability_axes"]["implemented_marker_definition_sets"]
        self.assertIn("CYP2C19", marker_axis["implemented_marker_definition_genes"])
        self.assertIn("pharmacogenomics.review_medication", marker_axis["operations"])
        self.assertIn("pharmacogenomics.describe_gene_requirements", result["capability_axes"]["pharmacogene_requirement_catalog"]["operations"])
        self.assertIn("pharmacogenomics.prepare_outside_call_tsv", result["capability_axes"]["pharmacogene_requirement_catalog"]["operations"])
        self.assertIn("pharmacogenomics.validate_outside_call_tsv", result["capability_axes"]["pharmacogene_requirement_catalog"]["operations"])
        self.assertIn("pharmacogenomics.preflight_pharmcat", result["capability_axes"]["broad_vcf_pgx_calling"]["operations"])
        self.assertIn("pharmacogenomics.import_pharmcat_artifacts", result["capability_axes"]["broad_vcf_pgx_calling"]["operations"])
        self.assertIn("pharmacogenomics.prepare_outside_call_tsv", result["capability_axes"]["broad_vcf_pgx_calling"]["operations"])
        self.assertIn("pharmacogenomics.validate_outside_call_tsv", result["capability_axes"]["broad_vcf_pgx_calling"]["operations"])
        sample_frame = next(item for item in result["evidence_frames"] if item["intent"] == "does my Active Genome Index affect this medication")
        self.assertIn("PharmCAT report JSON", sample_frame["sample_evidence_artifact_types"])
        self.assertEqual(result["capability_axes"]["broad_vcf_pgx_calling"]["runtime_status"]["status"], "not_checked")
        self.assertEqual(result["clinical_boundary"]["status"], "informational_evidence_review_requires_clinical_confirmation")

    def test_capability_inventory_can_check_pharmcat(self) -> None:
        with patch(
            "genomi.capabilities.pharmacogenomics.pharmcat.pharmcat_status",
            return_value={"status": "available", "ok": True},
        ) as status:
            result = capability_inventory(check_pharmcat=True, pharmcat_timeout_seconds=3)

        self.assertTrue(result["capability_axes"]["broad_vcf_pgx_calling"]["runtime_status"]["ok"])
        status.assert_called_once_with(timeout_seconds=3)

    def test_pgx_expanded_operations_include_runtime_tools(self) -> None:
        tools = {tool["name"]: tool for tool in list_operations(capability="pharmacogenomics")}

        self.assertIn("pharmacogenomics.check_pharmcat", tools)
        self.assertIn("pharmacogenomics.describe_gene_requirements", tools)


if __name__ == "__main__":
    unittest.main()
