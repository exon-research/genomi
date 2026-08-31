from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest import mock

from genomi.operations import call_operation
from genomi.active_genome_index.active_genome_index import active_genome_index_readiness, active_genome_index_summary

from tests.support.runtime.genomi import GenomiRuntimeTestCase


def _hidden_path_leaks(payload: object, *paths: Path) -> list[str]:
    hidden = {
        value
        for path in paths
        for value in (str(path), str(path.expanduser().resolve(strict=False)))
    }
    leaks: list[str] = []

    def visit(value: object, location: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                visit(item, f"{location}.{key}")
            return
        if isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, f"{location}[{index}]")
            return
        if isinstance(value, str) and any(path in value for path in hidden):
            leaks.append(location)

    visit(payload, "$")
    return leaks


class GenomiRuntimeVcfIntakeTests(GenomiRuntimeTestCase):
    def test_gvcf_parse_default_persists_installed_reference_for_genotype_support(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                reference = Path("hg38.fa")
                reference.write_text(">chr1\n" + "A" * 250 + "\n", encoding="utf-8")
                gvcf = Path("sample.g.vcf")
                gvcf.write_text(
                    "##fileformat=VCFv4.2\n"
                    '##INFO=<ID=END,Number=1,Type=Integer,Description="End">\n'
                    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tsample\n"
                    "1\t100\t.\tA\t<NON_REF>\t.\tPASS\tEND=200\tGT:DP:GQ\t0/0:30:0\n",
                    encoding="utf-8",
                )
                installed = {
                    "installed": True,
                    "required_paths": [str(reference), str(Path(f"{reference}.fai"))],
                }

                with mock.patch(
                    "genomi.active_genome_index.source_intake.reference.library_manager.status",
                    return_value=installed,
                ):
                    parsed = call_operation(
                        "genomi.parse_source",
                        {"source": str(gvcf), "genome_build": "GRCh38"},
                    )

                self.assertEqual(parsed["status"], "completed")
                support = call_operation(
                    "active_genome_index.classify_genotype_support",
                    {"chrom": "1", "pos": 150, "ref": "A", "alt": "G"},
                )
                self.assertEqual(support["support_status"], "not_observed")
                self.assertEqual(support["sample_observation"]["observed_genotype"], "A/A")
                self.assertEqual(support["site_observation"]["reference_base_source"], "reference_fasta")
            finally:
                os.chdir(previous)

    def test_active_genome_index_parse_materializes_vcf_index_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                vcf = Path("targeted.vcf")
                vcf.write_text(
                    "##fileformat=VCFv4.2\n"
                    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tsample\n"
                    "10\t94761900\trs4244285\tG\tA\t50\tPASS\t.\tGT:DP:GQ\t0/1:31:99\n",
                    encoding="utf-8",
                )

                self.approve_access()
                parsed = call_operation(
                    "genomi.parse_source",
                    {"source": str(vcf), "genome_build": "GRCh38"},
                )

                self.assertEqual(parsed["status"], "completed")
                self.assertEqual(parsed["source_format"], "vcf")
                self.assertEqual(parsed["annotation_scope"], "active_genome_index")
                self.assertTrue(parsed["active_genome_index"]["digitized"])
                self.assertEqual([step["name"] for step in parsed["steps"]], ["build-active-genome-index"])
                self.assertEqual(parsed["warnings"], [])
                self.assertEqual(set(parsed["outputs"]), {"agi_path"})
                agi_summary = active_genome_index_summary(parsed["outputs"]["agi_path"])
                self.assertEqual(agi_summary["metadata"]["source_format"], "vcf")
                self.assertIsNone(parsed.get("static_profile"))
                self.assertIsNone(parsed.get("long_running_steps_deferred"))
                self.assertEqual(_hidden_path_leaks(parsed, vcf), [])

                lookup = call_operation("variant.resolve", {"rsid": "rs4244285"})
                self.assertEqual(lookup["sample_context"]["count"], 1)
                match = lookup["sample_context"]["matches"][0]
                self.assertEqual(match["genotype"], "0/1")
                self.assertEqual(match["agi_source_format"], "vcf")
                self.assertEqual(_hidden_path_leaks(lookup, vcf), [])
            finally:
                os.chdir(previous)

    def test_gvcf_parse_completes_through_unified_two_phase(self) -> None:
        # Regression: parse_source used to delete the canonical it had just
        # adopted as the index's source of record, so the reference pass (Phase B)
        # crashed with needs_file and the index sat at variants_ready forever.
        # With background disabled (the test default) Phase B runs inline, so a
        # correct flow reaches `complete` and the gVCF's reference blocks land.
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                gvcf = Path("sample.g.vcf")
                with gvcf.open("w", encoding="utf-8") as handle:
                    handle.write("##fileformat=VCFv4.2\n")
                    handle.write('##INFO=<ID=END,Number=1,Type=Integer,Description="End">\n')
                    handle.write("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n")
                    for pos in range(1, 4001):
                        if pos % 400 == 0:
                            handle.write(f"1\t{pos}\trs{pos}\tA\tG\t.\tPASS\t.\tGT:DP:GQ\t0/1:42:99\n")
                        else:
                            handle.write(f"1\t{pos}\t.\tA\t<NON_REF>\t.\tPASS\tEND={pos}\tGT:DP:GQ\t0/0:35:50\n")

                self.approve_access()
                parsed = call_operation(
                    "genomi.parse_source",
                    {"source": str(gvcf), "genome_build": "GRCh38"},
                )
                self.assertEqual(parsed["status"], "completed")
                self.assertEqual(parsed["source_format"], "gvcf")

                agi_path = parsed["outputs"]["agi_path"]
                readiness = active_genome_index_readiness(agi_path)
                agi_summary = active_genome_index_summary(agi_path)
                self.assertEqual(agi_summary["metadata"]["source_format"], "gvcf")
                # Inline Phase B finished, so the index is complete and not stuck.
                self.assertTrue(readiness["complete"])
                self.assertFalse(readiness.get("reference_pending", False))

                lookup = call_operation("variant.resolve", {"rsid": "rs400"})
                self.assertEqual(lookup["sample_context"]["count"], 1)
            finally:
                os.chdir(previous)

    def test_active_genome_index_parse_defaults_to_vcf_index_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                vcf = Path("targeted.vcf")
                vcf.write_text(
                    "##fileformat=VCFv4.2\n"
                    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tsample\n"
                    "10\t94761900\trs4244285\tG\tA\t50\tPASS\t.\tGT:DP:GQ\t0/1:31:99\n",
                    encoding="utf-8",
                )

                self.approve_access()
                parsed = call_operation(
                    "genomi.parse_source",
                    {"source": str(vcf), "genome_build": "GRCh38"},
                )

                self.assertEqual(parsed["status"], "completed")
                self.assertEqual(parsed["annotation_scope"], "active_genome_index")
                self.assertEqual([step["name"] for step in parsed["steps"]], ["build-active-genome-index"])
                lookup = call_operation("variant.resolve", {"rsid": "rs4244285"})
                self.assertEqual(lookup["sample_context"]["count"], 1)
            finally:
                os.chdir(previous)

    def test_active_genome_index_parse_omits_static_materialization_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                vcf = Path("targeted.vcf")
                vcf.write_text(
                    "##fileformat=VCFv4.2\n"
                    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tsample\n"
                    "10\t94761900\trs4244285\tG\tA\t50\tPASS\t.\tGT:DP:GQ\t0/1:31:99\n",
                    encoding="utf-8",
                )

                self.approve_access()
                parsed = call_operation(
                    "genomi.parse_source",
                    {"source": str(vcf), "genome_build": "GRCh38"},
                )

                self.assertEqual(parsed["status"], "completed")
                self.assertEqual(parsed["annotation_scope"], "active_genome_index")
                self.assertEqual(parsed["warnings"], [])
                self.assertIsNone(parsed.get("static_profile"))
                self.assertIsNone(parsed.get("long_running_steps_deferred"))
                self.assertIsNone(parsed.get("evidence_summary"))
                self.assertEqual(set(parsed["outputs"]), {"agi_path"})
                lookup = call_operation("variant.resolve", {"rsid": "rs4244285"})
                self.assertEqual(lookup["sample_context"]["count"], 1)
            finally:
                os.chdir(previous)

    def test_parse_source_rebuilds_capped_vcf_index_for_later_full_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                vcf = Path("sample.vcf")
                vcf.write_text(
                    "##fileformat=VCFv4.2\n"
                    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tsample\n"
                    "1\t100\trs1\tA\tG\t50\tPASS\t.\tGT:DP:GQ\t0/1:31:99\n"
                    "1\t200\trs2\tC\tT\t50\tPASS\t.\tGT:DP:GQ\t0/1:29:80\n",
                    encoding="utf-8",
                )

                self.approve_access()
                capped = call_operation(
                    "genomi.parse_source",
                    {"source": str(vcf), "genome_build": "GRCh38", "max_records": 1},
                )
                self.assertEqual(capped["steps"][0]["result"]["stats"]["total_records"], 1)

                full = call_operation(
                    "genomi.parse_source",
                    {"source": str(vcf), "genome_build": "GRCh38"},
                )
                self.assertIn(full["steps"][0]["result"]["status"], {"variants_ready", "completed"})
                self.assertEqual(full["steps"][0]["result"]["stats"]["total_records"], 2)

                lookup = call_operation("variant.resolve", {"rsid": "rs2"})
                self.assertEqual(lookup["sample_context"]["count"], 1)
            finally:
                os.chdir(previous)
