from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from genomi.capabilities.pharmacogenomics.pgx_star import call_star_alleles


class PGxStarAlleleTests(unittest.TestCase):
    def setUp(self) -> None:
        # Isolate from any pre-existing ~/.genomi state so tests that assert
        # "no Active Genome Index selected" behavior are not polluted by an
        # active run left over from real Genomi parses in this account.
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self._env_patch = patch.dict(
            os.environ,
            {
                "GENOMI_HOME": self._tmpdir.name,
                "GENOMI_CONTEXT": "",
                "GENOMI_SESSION_ID": "",
                "GENOMI_CONTEXT_POLICY": "explicit",
            },
        )
        self._env_patch.start()
        self.addCleanup(self._env_patch.stop)

    def test_cyp2c19_common_markers_infer_intermediate_metabolizer(self) -> None:
        def fake_lookup(*, rsid, **_kwargs):
            records = {
                "rs4244285": {"genotype": "0/1", "ref": "G", "alt": "A"},
                "rs4986893": {"genotype": "GG", "ref": "G", "alt": "A"},
                "rs12248560": {"genotype": "CC", "ref": "C", "alt": "T"},
            }
            return {
                "sample_context": {
                    "count": 1,
                    "matches": [
                        {
                            "rsid": rsid,
                            "filter": "PASS",
                            "source_format": "vcf",
                            "agi_id": "genome-1",
                            **records[rsid],
                        }
                    ],
                },
                "public_context": {},
                "warnings": [],
            }

        with patch("genomi.capabilities.pharmacogenomics.pgx_star.variant_lookup.lookup_variant", side_effect=fake_lookup) as lookup:
            result = call_star_alleles(gene="CYP2C19")

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["genome_build"], "GRCh38")
        self.assertEqual(result["called_star_alleles"][0]["star_allele"], "*2")
        self.assertEqual(result["marker_calls"][0]["effect_allele_count"], 1)
        self.assertEqual(result["marker_calls"][0]["sample_calls"][0]["chrom"], None)
        self.assertEqual(result["marker_calls"][1]["evidence_status"], "observed_reference_or_other_allele")
        self.assertEqual(result["diplotype"]["possible_diplotype"], "*2/*1")
        self.assertEqual(result["diplotype"]["predicted_phenotype"], "intermediate_metabolizer")
        self.assertEqual(result["diplotype"]["marker_support_status"], "common_marker_subset_observed")
        self.assertEqual(lookup.call_count, 3)

    def test_letter_genotype_calls_effect_allele(self) -> None:
        def fake_lookup(*, rsid, **_kwargs):
            if rsid == "rs4244285":
                matches = [{"genotype": "AG", "ref": "G", "alt": "A"}]
            else:
                matches = [{"genotype": "GG" if rsid == "rs4986893" else "CC", "ref": "G", "alt": "A"}]
            return {"sample_context": {"count": 1, "matches": matches}, "public_context": {}, "warnings": []}

        with patch("genomi.capabilities.pharmacogenomics.pgx_star.variant_lookup.lookup_variant", side_effect=fake_lookup):
            result = call_star_alleles(gene="cyp2c19")

        self.assertEqual(result["marker_calls"][0]["effect_allele_count"], 1)
        self.assertEqual(result["called_star_alleles"][0]["star_allele"], "*2")

    def test_unsupported_gene_is_explicit(self) -> None:
        result = call_star_alleles(gene="CYP2D6")

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "unsupported_gene")
        self.assertIn("CYP2C19", result["implemented_marker_definition_genes"])

    def test_internal_helper_without_active_index_does_not_report_not_observed(self) -> None:
        with patch("genomi.capabilities.pharmacogenomics.pgx_star.variant_lookup.lookup_variant") as lookup:
            result = call_star_alleles(gene="CYP2C19", include_active_genome_index=False)

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "no_sample_context")
        self.assertEqual(result["marker_calls"][0]["evidence_status"], "no_active_genome_index_selected")
        self.assertEqual(result["diplotype"]["possible_diplotype"], None)
        self.assertEqual(result["diplotype"]["predicted_phenotype"], None)
        self.assertEqual(result["diplotype"]["marker_support_status"], "no_sample_context")
        self.assertIn("active_genome_index", result["missing_inputs"])
        lookup.assert_not_called()


if __name__ == "__main__":
    unittest.main()
