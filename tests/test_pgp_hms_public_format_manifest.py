from __future__ import annotations

import json
import unittest
from pathlib import Path

from genomi.active_genome_index.source_intake.arrays import SUPPORTED_CONSUMER_ARRAY_FORMATS

from _active_genome_index_contract_fixtures import ActiveGenomeIndexContractFixtureMixin


MANIFEST_PATH = Path(__file__).parent / "data" / "pgp_hms_public_genetic_data_manifest.json"


class PGPHMSPublicFormatManifestTests(ActiveGenomeIndexContractFixtureMixin, unittest.TestCase):
    def _manifest(self) -> dict[str, object]:
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    def test_manifest_records_public_pgp_hms_data_type_inventory(self) -> None:
        manifest = self._manifest()
        self.assertEqual(manifest["source_url"], "https://my.pgp-hms.org/public_genetic_data")
        self.assertEqual(manifest["observed_public_row_count"], 3964)
        self.assertEqual(manifest["observed_data_type_label_count"], 259)
        selector_types = set(manifest["selector_data_types"])
        self.assertIn("genetic data - 23andMe (e.g., exome or genotyping data)", selector_types)
        self.assertIn("genetic data - Family Tree DNA", selector_types)
        self.assertIn("genetic data - Gencove low-pass (e.g. Nebula Genomics)", selector_types)
        self.assertIn("genetic data - Illumina (e.g., Understand Your Genome data)", selector_types)
        self.assertIn("genetic data - Veritas Genetics", selector_types)
        self.assertIn("genetic data - Complete Genomics", selector_types)
        self.assertIn("health records - PDF or text", selector_types)
        observed_counts = manifest["observed_data_type_label_counts"]
        self.assertEqual(observed_counts["23andMe"], 1017)
        self.assertEqual(observed_counts["Complete Genomics"], 538)
        self.assertEqual(observed_counts["Family Tree DNA"], 247)
        self.assertEqual(observed_counts["Veritas Genetics"], 1055)
        self.assertIn("AncestryDNA", observed_counts)
        self.assertIn("MyHeritage", observed_counts)
        self.assertIn("FASTQ data", observed_counts)
        self.assertIn("Nebula Genomics VCF file", observed_counts)

    def test_every_supported_contract_fixture_is_traced_to_manifest_format(self) -> None:
        manifest = self._manifest()
        supported = manifest["supported_intake_formats"]
        case_to_format = {
            case_id: source_format
            for case_id, source_format, _writer in self._source_cases()
        }
        case_to_format["bam"] = "bam"
        case_to_format["bam_zip"] = "bam"
        case_to_format["fastq"] = "fastq"
        case_to_format["fastq_zip"] = "fastq"

        manifest_cases = {
            case_id: source_format
            for source_format, spec in supported.items()
            for case_id in spec["contract_fixture_cases"]
        }
        self.assertEqual(case_to_format, manifest_cases)

    def test_manifest_distinguishes_supported_formats_without_public_pgp_examples(self) -> None:
        manifest = self._manifest()
        supported = manifest["supported_intake_formats"]
        formats_without_public_pgp_examples = {
            source_format
            for source_format, spec in supported.items()
            if not spec["public_pgp_hms_examples_observed"]
        }
        self.assertEqual(formats_without_public_pgp_examples, {"livingdna"})
        for source_format, spec in supported.items():
            evidence = spec["pgp_public_evidence"]
            if source_format in formats_without_public_pgp_examples:
                self.assertEqual(len(evidence), 1)
                self.assertIn("No Living DNA examples were present", evidence[0])
            else:
                self.assertTrue(evidence, source_format)

    def test_consumer_array_code_and_manifest_cannot_drift(self) -> None:
        manifest = self._manifest()
        manifest_arrays = {
            source_format
            for source_format in manifest["supported_intake_formats"]
            if source_format in SUPPORTED_CONSUMER_ARRAY_FORMATS
        }
        self.assertEqual(manifest_arrays, set(SUPPORTED_CONSUMER_ARRAY_FORMATS))

    def test_unsupported_pgp_genetic_providers_are_explicitly_not_fixture_gaps(self) -> None:
        manifest = self._manifest()
        unsupported = manifest["recognized_unsupported_genetic_formats"]
        self.assertIn("complete_genomics", unsupported)
        self.assertIn("counsyl", unsupported)
        self.assertIn("decode", unsupported)
        self.assertIn("knome", unsupported)
        self.assertIn("navigenics", unsupported)
        self.assertIn("pathway_genomics", unsupported)
        unsupported_overlap = set(unsupported) & set(manifest["supported_intake_formats"])
        self.assertEqual(unsupported_overlap, set())


if __name__ == "__main__":
    unittest.main()
