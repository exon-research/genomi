from __future__ import annotations

import json
import re
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

from genomi.active_genome_index.source_intake import (
    SUPPORTED_CONSUMER_ARRAY_FORMATS,
    SUPPORTED_SOURCE_FORMATS,
)

from _active_genome_index_contract_fixtures import ActiveGenomeIndexContractFixtureMixin


MANIFEST_PATH = Path(__file__).parent / "data" / "pgp_hms_public_genetic_data_manifest.json"
PUBLIC_IDENTIFIER_PATTERNS = {
    "full_name_23andme_filename": re.compile(r"genome_[A-Z][a-z]+_[A-Z][a-z]+_v\d+_Full_"),
    "named_raw_dna_archive": re.compile(r"(?:^|[/_])[A-Z][a-z]{2,}_raw_dna_data"),
    "public_hu_id": re.compile(r"hu[A-Fa-f0-9]{6}"),
    "public_kit_id": re.compile(r"AM\d+"),
    "public_livingdna_id": re.compile(r"LD\d+[A-Z]"),
    "public_run_id": re.compile(r"\d{14}(?:_SA_L\d{3}_R[12]|_lcWGS|\.(?:cnv|snp|indel)\.vcf)"),
    "public_hash_member": re.compile(r"[a-f0-9]{32}\.vcf"),
    "provider_run_slug": re.compile(r"[A-Z0-9]{10}\.mm2"),
}


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
        case_to_format.update(self._sequencing_source_case_formats())

        manifest_cases = {
            case_id: source_format
            for source_format, spec in supported.items()
            for case_id in spec["contract_fixture_cases"]
        }
        self.assertEqual(case_to_format, manifest_cases)
        self.assertEqual(set(case_to_format.values()), set(supported))

    def test_public_sample_shape_observations_cover_supported_formats(self) -> None:
        manifest = self._manifest()
        supported = manifest["supported_intake_formats"]
        observations = manifest["public_sample_shape_observations"]

        self.assertEqual(set(observations), set(supported))
        for source_format, spec in supported.items():
            observation = observations[source_format]
            if spec["public_pgp_hms_examples_observed"]:
                self.assertIn(
                    observation["sample_access_kind"],
                    {"downloaded_content", "public_listing_large_file"},
                )
            else:
                self.assertEqual(observation["sample_access_kind"], "no_public_example_observed")
            self.assertEqual(observation["content_rows_committed"], False)
            self.assertTrue(observation["anonymized_fixture_names"], source_format)
        self.assertEqual(
            observations["gvcf"]["sample_access_kind"],
            "public_listing_large_file",
        )
        self.assertTrue(observations["gvcf"]["download_size_limit_reason"])

    def test_public_shape_observations_are_sanitized(self) -> None:
        observations = self._manifest()["public_sample_shape_observations"]
        observation_text = json.dumps(observations, sort_keys=True)
        self.assertEqual(_identifier_leaks([observation_text]), [])

    def test_contract_fixture_names_are_anonymized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            observed_names: list[str] = []
            for case_id, _source_format, writer in self._source_cases():
                source_path = writer(root / case_id)
                observed_names.extend(self._archive_and_file_names(source_path))
            for case_id, writer in (
                ("bam", self._write_bam_source),
                ("bam_zip", self._write_bam_zip_source),
                ("bam_tar", self._write_bam_tar_source),
                ("fastq_zip", self._write_fastq_zip_sources),
                ("fastq_tar", self._write_fastq_tar_sources),
            ):
                source_path = writer(root / case_id)
                observed_names.extend(self._archive_and_file_names(source_path))
            source_path = self._write_fastq_sources(root / "PGP_PUBLIC_SA_L001_R1_001.fastq.gz")
            observed_names.extend(self._archive_and_file_names(source_path))
            observed_names.extend(path.name for path in root.glob("PGP_PUBLIC_SA_L001_R2_001.fastq.gz"))
            self.assertEqual(_identifier_leaks(observed_names), [])

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

    def test_runtime_supported_formats_and_manifest_cannot_drift(self) -> None:
        manifest = self._manifest()
        self.assertEqual(set(manifest["supported_intake_formats"]), set(SUPPORTED_SOURCE_FORMATS))

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

    def _archive_and_file_names(self, path: Path) -> list[str]:
        names = [path.name]
        if path.suffix == ".zip":
            with zipfile.ZipFile(path) as archive:
                names.extend(archive.namelist())
        elif path.name.endswith(".tar.gz"):
            with tarfile.open(path) as archive:
                names.extend(archive.getnames())
        return names


def _identifier_leaks(values: list[str]) -> list[str]:
    leaks = []
    for label, pattern in sorted(PUBLIC_IDENTIFIER_PATTERNS.items()):
        for value in values:
            if pattern.search(value):
                leaks.append(f"{label}:{value}")
    return leaks


if __name__ == "__main__":
    unittest.main()
