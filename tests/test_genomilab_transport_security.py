from __future__ import annotations

import unittest

from genomi.lab.artifact_payload import safe_json_value


class GenomiLabArtifactBoundarySecurityTests(unittest.TestCase):
    def test_artifact_boundary_rejects_genomi_owned_source_material_aliases(self) -> None:
        unsafe_payloads = (
            {"genomePath": "/private/patient.genome"},
            {"genome_bundle": "/private/patient.genome"},
            {"bamPath": "/private/patient.bam"},
            {"cram_path": "/private/patient.cram"},
            {"consumerGenotypeFile": "/private/patient-23andme.txt"},
            {"agiFile": "/private/active-genome-index.sqlite"},
            {"activeGenomeIndexRows": [{"chrom": "1", "position": 101}]},
        )

        for payload in unsafe_payloads:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                safe_json_value({"approved_context": {"nested": payload}})

    def test_artifact_boundary_allows_immutable_genome_reference_identity(self) -> None:
        value = safe_json_value(
            {
                "agi_id": "agi-synthetic",
                "agi_snapshot_id": "agi-snapshot-synthetic",
                "genome_build": "GRCh38",
                "sequence": 17,
            }
        )

        self.assertEqual(value["agi_snapshot_id"], "agi-snapshot-synthetic")
        self.assertEqual(value["genome_build"], "GRCh38")


if __name__ == "__main__":
    unittest.main()
