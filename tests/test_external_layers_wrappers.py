from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests._external_layers_helpers import (
    TINY_FASTA,
    TINY_NORMALIZE_FASTA,
    TINY_NORMALIZE_VCF,
    TINY_VCF,
    annotate_vcf,
    build_bam_variant_call_commands,
    build_bcftools_norm_command,
    build_vep_command,
    build_vep_docker_command,
    dependency_report,
    infer_genome_build_from_bam_header,
    normalize_vcf,
)


class ExternalWrapperTests(unittest.TestCase):
    def test_dependency_report_names_expected_tools(self) -> None:
        report = dependency_report()

        self.assertEqual(
            [tool["name"] for tool in report["tools"]],
            ["bcftools", "bgzip", "tabix", "samtools", "vep", "docker", "docker image ensemblorg/ensembl-vep:latest"],
        )

    def test_bam_variant_call_commands_are_deterministic(self) -> None:
        commands = build_bam_variant_call_commands("sample.bam", "hg38.fa", "derived.vcf")

        self.assertEqual(
            commands,
            [
                [
                    "bcftools",
                    "mpileup",
                    "--fasta-ref",
                    "hg38.fa",
                    "--output-type",
                    "u",
                    "sample.bam",
                ],
                [
                    "bcftools",
                    "call",
                    "--multiallelic-caller",
                    "--variants-only",
                    "--output-type",
                    "v",
                    "--output",
                    "derived.vcf",
                ],
            ],
        )

    def test_bam_header_genome_build_inference_uses_reference_lengths(self) -> None:
        self.assertEqual(infer_genome_build_from_bam_header("@SQ\tSN:chr1\tLN:248956422\n"), "GRCh38")
        self.assertEqual(infer_genome_build_from_bam_header("@SQ\tSN:1\tLN:249250621\n"), "GRCh37")

    def test_bcftools_norm_command_is_deterministic(self) -> None:
        command = build_bcftools_norm_command(TINY_VCF, TINY_FASTA, "out.vcf.gz")

        self.assertEqual(
            command,
            [
                "bcftools",
                "norm",
                "--fasta-ref",
                str(TINY_FASTA),
                "--check-ref",
                "s",
                "--output-type",
                "z",
                "--output",
                "out.vcf.gz",
                "--multiallelics",
                "-any",
                str(TINY_VCF),
            ],
        )

    def test_normalize_dry_run_does_not_require_bcftools(self) -> None:
        result = normalize_vcf(TINY_VCF, TINY_FASTA, "out.vcf.gz", dry_run=True)

        self.assertEqual(result["status"], "planned")
        self.assertEqual(result["output"], "out.vcf.gz")
        self.assertEqual(result["commands"][0][0:2], ["bcftools", "norm"])

    def test_normalize_fixture_command_can_target_valid_fixture(self) -> None:
        result = normalize_vcf(TINY_NORMALIZE_VCF, TINY_NORMALIZE_FASTA, "out.vcf.gz", dry_run=True)

        self.assertIn(str(TINY_NORMALIZE_FASTA), result["commands"][0])
        self.assertIn(str(TINY_NORMALIZE_VCF), result["commands"][0])

    def test_bcftools_norm_command_can_allow_malformed_tags(self) -> None:
        command = build_bcftools_norm_command(
            TINY_VCF,
            TINY_FASTA,
            "out.vcf.gz",
            allow_malformed_tags=True,
        )

        self.assertIn("--force", command)
        self.assertLess(command.index("--force"), command.index(str(TINY_VCF)))

    def test_vep_command_is_deterministic(self) -> None:
        command = build_vep_command(TINY_VCF, "annotated.vcf", cache_dir="/cache", force_overwrite=True)

        self.assertIn("--offline", command)
        self.assertIn("--dir_cache", command)
        self.assertIn("/cache", command)
        self.assertIn("--force_overwrite", command)

    def test_annotate_dry_run_does_not_require_vep(self) -> None:
        result = annotate_vcf(TINY_VCF, "annotated.vcf", dry_run=True)

        self.assertEqual(result["status"], "planned")
        self.assertEqual(result["output"], "annotated.vcf")
        self.assertEqual(result["commands"][0][0], "vep")

    def test_vep_docker_command_mounts_input_output_and_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "annotated.vcf"
            cache = Path(tmp) / "vep-cache"
            command = build_vep_docker_command(TINY_VCF, output, cache_dir=cache, force_overwrite=True)

        self.assertEqual(command[:3], ["docker", "run", "--rm"])
        self.assertIn("ensemblorg/ensembl-vep:latest", command)
        self.assertIn("--dir_cache", command)
        self.assertIn("/cache", command)
        self.assertIn("--force_overwrite", command)

    def test_annotate_docker_dry_run_uses_docker_command(self) -> None:
        result = annotate_vcf(TINY_VCF, "annotated.vcf", runner="docker", dry_run=True)

        self.assertEqual(result["status"], "planned")
        self.assertEqual(result["manifest"]["runner"], "docker")
        self.assertEqual(result["commands"][0][0:3], ["docker", "run", "--rm"])


if __name__ == "__main__":
    unittest.main()
