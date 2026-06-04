from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from genomi.capabilities.pharmacogenomics.pharmcat import (
    import_pharmcat_artifacts,
    pharmcat_preflight,
    pharmcat_status,
    run_pharmcat,
)
from genomi.operations import call_operation, list_operations


class PharmCATIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._home_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._home_tmp.cleanup)
        self._env = patch.dict(
            os.environ,
            {"GENOMI_HOME": str(Path(self._home_tmp.name) / "genomi-home"), "GENOMI_CONTEXT": "", "GENOMI_SESSION_ID": ""},
        )
        self._env.start()
        self.addCleanup(self._env.stop)

    def _build_agi(self, vcf: Path) -> Path:
        """Genomi contract: capability tools require an Active Genome Index.
        Build one from the test VCF before invoking PharmCAT.
        """
        parsed = call_operation("genomi.parse_source", {"source": str(vcf)})
        return Path(parsed["outputs"]["agi_path"])

    def test_plans_when_dry_run_with_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vcf = Path(tmp) / "sample.vcf"
            vcf.write_text(
                "##fileformat=VCFv4.2\n"
                "##reference=GRCh38\n"
                "##contig=<ID=chr1,length=248956422>\n"
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE\n"
                "chr1\t1\t.\tA\tG\t.\tPASS\t.\tGT\t0/1\n",
                encoding="utf-8",
            )
            agi_path = self._build_agi(vcf)

            with patch("genomi.capabilities.pharmacogenomics.pharmcat.shutil.which", return_value="/usr/local/bin/pharmcat_pipeline"):
                result = run_pharmcat(agi_path=agi_path, dry_run=True, base_filename="sample")

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "planned")
        self.assertEqual(result["execution"]["mode"], "pipeline")
        self.assertIn("[derived_pharmcat_input]", result["execution"]["command"])
        self.assertIn("version_probe", result["execution"])
        self.assertEqual(result["input_preflight"]["status"], "completed")
        self.assertTrue(result["input_preflight"]["input"]["hidden_agi_path"])
        self.assertEqual(result["input_preflight"]["header"]["sample_count"], 1)
        self.assertEqual(result["input_preflight"]["header"]["contig_style"], "chr_prefixed")
        self.assertEqual(result["input_preflight"]["scan_summary"]["records_with_gt"], 1)
        self.assertEqual(result["pharmcat_input"]["method"], "active_genome_index_export")
        self.assertEqual(result["pharmcat_input"]["input_path"], "[derived_pharmcat_input]")
        checks = {item["id"]: item for item in result["input_preflight"]["pharmcat_requirement_checks"]}
        self.assertEqual(checks["grch38_assembly"]["status"], "ready")
        self.assertEqual(checks["required_columns_and_gt"]["status"], "ready")
        self.assertEqual(checks["chromosome_prefix"]["status"], "ready")
        self.assertEqual(checks["required_pgx_positions"]["status"], "requires_missing_pgx_position_review")

    def test_default_pharmcat_plan_hides_intake_filename_and_private_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vcf = Path(tmp) / "Jane Doe genome.vcf"
            sample_file = Path(tmp) / "Jane sample ids.txt"
            sample_metadata = Path(tmp) / "Jane sample metadata.json"
            vcf.write_text(
                "##fileformat=VCFv4.2\n"
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE\n"
                "chr10\t94761900\trs4244285\tG\tA\t.\tPASS\t.\tGT\t0/1\n",
                encoding="utf-8",
            )
            sample_file.write_text("SAMPLE\n", encoding="utf-8")
            sample_metadata.write_text("{}", encoding="utf-8")
            agi_path = self._build_agi(vcf)

            with patch("genomi.capabilities.pharmacogenomics.pharmcat.shutil.which", return_value="/usr/local/bin/pharmcat_pipeline"):
                result = run_pharmcat(
                    agi_path=agi_path,
                    sample_file=sample_file,
                    sample_metadata=sample_metadata,
                    dry_run=True,
                )

        self.assertTrue(result["ok"])
        self.assertRegex(result["base_filename"], r"^active-genome-index-[0-9a-f]{12}$")
        self.assertIn("[derived_pharmcat_input]", result["execution"]["command"])
        self.assertEqual(result["execution"]["command"].count("[hidden_private_path]"), 2)

    def test_pipeline_run_summarizes_report_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vcf = Path(tmp) / "sample.vcf"
            vcf.write_text(
                "##fileformat=VCFv4.2\n"
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE\n"
                "chr10\t94761900\trs4244285\tG\tA\t.\tPASS\t.\tGT\t0/1\n",
                encoding="utf-8",
            )
            agi_path = self._build_agi(vcf)
            output = Path(tmp) / "pharmcat"

            def fake_run(command, **_kwargs):
                if "--version" in command:
                    return subprocess.CompletedProcess(command, 0, "PharmCAT 3.2.0", "")
                out_dir = Path(command[command.index("-o") + 1])
                base = command[command.index("-bf") + 1]
                out_dir.mkdir(parents=True, exist_ok=True)
                (out_dir / f"{base}.report.tsv").write_text(
                    "Gene\tSource Diplotype\tPhenotype\tActivity Score\n"
                    "CYP2C19\t*1/*2\tIntermediate Metabolizer\t\n",
                    encoding="utf-8",
                )
                report_json = {
                    "title": "PharmCAT Report",
                    "timestamp": "2026-05-14T00:00:00Z",
                    "pharmcatVersion": "3.2.0",
                    "dataVersion": "2026.01",
                    "matcherMetadata": {
                        "genomeBuild": "GRCh38",
                        "sampleId": "sample",
                    },
                    "drugs": {
                        "CPIC Guideline Annotation": {
                            "clopidogrel": {
                                "name": "clopidogrel",
                                "id": "PA449053",
                                "source": "CPIC",
                                "urls": ["https://cpicpgx.org/guidelines/"],
                                "citations": [
                                    {"pmid": "23698643", "title": "CPIC CYP2C19 clopidogrel guideline", "year": 2013}
                                ],
                                "guidelines": [
                                    {
                                        "id": "CPIC:CYP2C19-clopidogrel",
                                        "name": "CYP2C19 and clopidogrel",
                                        "source": "CPIC",
                                        "url": "https://cpicpgx.org/guidelines/",
                                        "annotations": [
                                            {
                                                "classification": "Strong",
                                                "population": "ACS/PCI",
                                                "drugRecommendation": "Consider an alternative antiplatelet therapy.",
                                                "implications": ["Reduced active metabolite formation and antiplatelet response."],
                                                "genotypes": [
                                                    {
                                                        "diplotypes": [
                                                            {
                                                                "gene": "CYP2C19",
                                                                "allele1": {"name": "*1"},
                                                                "allele2": {"name": "*2"},
                                                                "phenotypes": ["Intermediate Metabolizer"],
                                                            }
                                                        ]
                                                    }
                                                ],
                                            }
                                        ],
                                    }
                                ],
                            }
                        }
                    },
                }
                (out_dir / f"{base}.report.json").write_text(json.dumps(report_json), encoding="utf-8")
                (out_dir / f"{base}.report.html").write_text("<html></html>\n", encoding="utf-8")
                (out_dir / f"{base}.missing_pgx_positions.vcf").write_text(
                    "##fileformat=VCFv4.2\n"
                    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
                    "10\t94761900\trs4244285\tG\tA\t.\t.\t.\n",
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(command, 0, "saved report", "")

            with (
                patch("genomi.capabilities.pharmacogenomics.pharmcat.shutil.which", return_value="/usr/local/bin/pharmcat_pipeline"),
                patch("genomi.capabilities.pharmacogenomics.pharmcat.subprocess.run", side_effect=fake_run) as runner,
            ):
                result = run_pharmcat(agi_path=agi_path, output_dir=output, base_filename="sample", timeout_seconds=30)

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["execution"]["version_probe"]["version_text"], "PharmCAT 3.2.0")
        self.assertEqual(result["artifacts"]["calls_only"]["genes"], ["CYP2C19"])
        calls_hash = result["artifacts"]["calls_only"]["artifact"]["content_sha256"]
        report_hash = result["artifacts"]["report_json"]["artifact"]["content_sha256"]
        self.assertEqual(len(calls_hash), 64)
        self.assertEqual(len(report_hash), 64)
        self.assertEqual(result["artifacts"]["calls_only"]["artifact"]["content_sha256"], calls_hash)
        self.assertEqual(result["artifacts"]["calls_only"]["artifact"]["artifact_id"], f"pharmcat_artifact_sha256:{calls_hash}")
        report_descriptor = next(item for item in result["artifacts"]["files"] if item["artifact_type"] == "report_json")
        self.assertEqual(report_descriptor["content_sha256"], report_hash)
        self.assertEqual(result["artifacts"]["calls_only"]["rows"][0]["Source Diplotype"], "*1/*2")
        self.assertEqual(result["artifacts"]["report_json"]["metadata"]["pharmcat_version"], "3.2.0")
        self.assertEqual(result["artifacts"]["report_json"]["artifact"]["content_sha256"], report_hash)
        self.assertEqual(result["artifacts"]["report_json"]["metadata"]["genome_build"], "GRCh38")
        recommendations = result["artifacts"]["report_json"]["recommendations"]
        self.assertEqual(recommendations["record_count"], 1)
        self.assertEqual(recommendations["records"][0]["drug"], "clopidogrel")
        self.assertEqual(recommendations["records"][0]["genes"], ["CYP2C19"])
        self.assertEqual(recommendations["records"][0]["phenotypes"], ["Intermediate Metabolizer"])
        self.assertEqual(recommendations["records"][0]["diplotypes"], ["CYP2C19 *1/*2"])
        self.assertEqual(recommendations["records"][0]["classification"], "Strong")
        self.assertIn("alternative antiplatelet", recommendations["records"][0]["recommendation"])
        self.assertEqual(result["artifacts"]["missing_pgx_positions"]["record_count"], 1)
        self.assertEqual(result["artifacts"]["missing_pgx_positions"]["records"][0]["id"], "rs4244285")
        self.assertEqual(result["record_research_payloads"][0]["target"]["gene"], "CYP2C19")
        self.assertIn("Intermediate Metabolizer", result["record_research_payloads"][0]["finding"]["text"])
        self.assertEqual(result["record_research_payloads"][0]["source"]["artifact"]["content_sha256"], calls_hash)
        self.assertEqual(result["record_research_payloads"][1]["finding"]["type"], "pharmcat_sample_pgx_recommendation")
        self.assertEqual(result["record_research_payloads"][1]["target"]["drug"], "clopidogrel")
        self.assertIn("alternative antiplatelet", result["record_research_payloads"][1]["finding"]["text"])
        self.assertEqual(result["record_research_payloads"][1]["source"]["artifact"]["content_sha256"], report_hash)
        self.assertEqual(result["record_research_payloads"][1]["source"]["artifact_metadata"]["pharmcat_version"], "3.2.0")
        self.assertTrue(result["interpretation_readiness"]["has_report_artifact"])
        self.assertEqual(result["interpretation_readiness"]["missing_pgx_position_count"], 1)
        self.assertIn("missing PGx positions", result["interpretation_readiness"]["requires_before_personal_actionability"][1])
        self.assertEqual(result["interpretation_readiness"]["personal_statement_support"], "pharmcat_report_available")
        self.assertEqual(runner.call_count, 2)

    def test_preflight_is_read_only_and_hides_source_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vcf = Path(tmp) / "sample.vcf"
            vcf.write_text(
                "##fileformat=VCFv4.2\n"
                "##reference=GRCh38\n"
                "##contig=<ID=10,length=133797422>\n"
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE\n"
                "10\t94761900\trs4244285\tG\tA\t.\tPASS\t.\tGT:DP:GQ\t0/1:38:99\n",
                encoding="utf-8",
            )
            agi_path = self._build_agi(vcf)

        result = pharmcat_preflight(agi_path=agi_path)

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["input_preflight"]["header"]["sample_count"], 1)
        self.assertEqual(result["input_preflight"]["header"]["contig_style"], "bare")
        self.assertEqual(result["input_preflight"]["scan_summary"]["records_with_gt"], 1)
        self.assertEqual(result["input_preflight"]["scan_summary"]["records_with_dp"], 1)
        self.assertEqual(result["input_preflight"]["scan_summary"]["records_with_gq"], 1)
        checks = {item["id"]: item for item in result["input_preflight"]["pharmcat_requirement_checks"]}
        self.assertEqual(checks["chromosome_prefix"]["status"], "needs_chr_prefixed_chromosomes")
        self.assertEqual(checks["grch38_assembly"]["status"], "ready")
        self.assertTrue(result["input_preflight"]["input"]["hidden_agi_path"])

    def test_preflight_reports_pharmcat_normalization_and_filter_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vcf = Path(tmp) / "sample.vcf"
            vcf.write_text(
                "##fileformat=VCFv4.2\n"
                "##reference=GRCh38\n"
                "##contig=<ID=chr10,length=133797422>\n"
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE\n"
                "chr10\t94942212\t.\tAAGAAATGGAA\tA\t.\tLowQual\t.\tGT\t0/1\n",
                encoding="utf-8",
            )
            agi_path = self._build_agi(vcf)

            result = pharmcat_preflight(agi_path=agi_path)

        checks = {item["id"]: item for item in result["input_preflight"]["pharmcat_requirement_checks"]}
        self.assertEqual(checks["variant_representation"]["status"], "requires_normalization_review")
        self.assertEqual(checks["quality_filter_review"]["status"], "review_filtered_records")
        self.assertEqual(result["input_preflight"]["scan_summary"]["indel_records"], 1)
        self.assertEqual(result["input_preflight"]["scan_summary"]["non_pass_filter_records"], 1)
        self.assertTrue(any("FILTER" in warning for warning in result["input_preflight"]["warnings"]))

    def test_imports_existing_pharmcat_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            calls = Path(tmp) / "sample.report.tsv"
            report = Path(tmp) / "sample.report.json"
            match = Path(tmp) / "sample.match.json"
            phenotype = Path(tmp) / "sample.phenotype.json"
            missing = Path(tmp) / "sample.missing_pgx_positions.vcf"
            calls.write_text(
                "Gene\tSource Diplotype\tPhenotype\tActivity Score\n"
                "CYP2C19\t*1/*2\tIntermediate Metabolizer\t\n",
                encoding="utf-8",
            )
            report.write_text(
                json.dumps(
                    {
                        "pharmcatVersion": "3.2.0",
                        "matcherMetadata": {"genomeBuild": "GRCh38", "sampleId": "sample"},
                        "drugs": {
                            "CPIC Guideline Annotation": {
                                "clopidogrel": {
                                    "name": "clopidogrel",
                                    "source": "CPIC",
                                    "urls": ["https://cpicpgx.org/guidelines/"],
                                    "guidelines": [
                                        {
                                            "source": "CPIC",
                                            "annotations": [
                                                {
                                                    "drugRecommendation": "Consider an alternative antiplatelet therapy.",
                                                    "genotypes": [
                                                        {
                                                            "diplotypes": [
                                                                {
                                                                    "gene": "CYP2C19",
                                                                    "allele1": {"name": "*1"},
                                                                    "allele2": {"name": "*2"},
                                                                    "phenotypes": ["Intermediate Metabolizer"],
                                                                }
                                                            ]
                                                        }
                                                    ],
                                                }
                                            ],
                                        }
                                    ],
                                }
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            match.write_text(
                json.dumps(
                    {
                        "metadata": {"namedAlleleMatcherVersion": "2.15.0", "genomeBuild": "GRCh38", "sampleId": "sample"},
                        "results": [
                            {
                                "source": "CLINPGX",
                                "version": "2026-02-09",
                                "chromosome": "10",
                                "gene": "CYP2C19",
                                "diplotypes": [{"name": "*1/*2", "score": 7}],
                                "phased": False,
                                "variants": [{"position": 94761900}],
                                "variantsOfInterest": [{"position": 94761900}],
                                "uncallableHaplotypes": [],
                                "warnings": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            phenotype.write_text(
                json.dumps(
                    {
                        "matcherMetadata": {"namedAlleleMatcherVersion": "2.15.0", "genomeBuild": "GRCh38", "sampleId": "sample"},
                        "geneReports": {
                            "CYP2C19": {
                                "geneSymbol": "CYP2C19",
                                "callSource": "MATCHER",
                                "phased": False,
                                "effectivelyPhased": False,
                                "sourceDiplotypes": [
                                    {"label": "*1/*2", "phenotypes": ["Intermediate Metabolizer"], "matchScore": 7}
                                ],
                                "recommendationDiplotypes": [
                                    {"label": "*1/*2", "phenotypes": ["Intermediate Metabolizer"], "matchScore": 7}
                                ],
                                "messages": [],
                                "uncalledHaplotypes": [],
                                "relatedDrugs": [],
                            },
                            "CYP2D6": {
                                "geneSymbol": "CYP2D6",
                                "callSource": "NONE",
                                "sourceDiplotypes": [
                                    {"label": "Unknown/Unknown", "phenotypes": ["No Result"], "activityScore": "No Result"}
                                ],
                                "recommendationDiplotypes": [
                                    {"label": "Unknown/Unknown", "phenotypes": ["No Result"], "activityScore": "No Result"}
                                ],
                                "messages": [],
                                "uncalledHaplotypes": [],
                                "relatedDrugs": [],
                            },
                        },
                        "unannotatedGeneCalls": [],
                    }
                ),
                encoding="utf-8",
            )
            missing.write_text(
                "##fileformat=VCFv4.2\n"
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
                "10\t94761900\trs4244285\tG\tA\t.\t.\t.\n",
                encoding="utf-8",
            )

            result = import_pharmcat_artifacts(
                report_json=report,
                calls_only_tsv=calls,
                match_json=match,
                phenotype_json=phenotype,
                missing_pgx_positions_vcf=missing,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["artifacts"]["calls_only"]["genes"], ["CYP2C19"])
        calls_hash = result["artifacts"]["calls_only"]["artifact"]["content_sha256"]
        match_hash = result["artifacts"]["named_allele_match_json"]["artifact"]["content_sha256"]
        phenotype_hash = result["artifacts"]["phenotype_json"]["artifact"]["content_sha256"]
        report_hash = result["artifacts"]["report_json"]["artifact"]["content_sha256"]
        self.assertEqual(len(calls_hash), 64)
        self.assertEqual(len(match_hash), 64)
        self.assertEqual(len(phenotype_hash), 64)
        self.assertEqual(len(report_hash), 64)
        self.assertEqual(result["artifacts"]["calls_only"]["artifact"]["content_sha256"], calls_hash)
        self.assertEqual(result["artifacts"]["named_allele_match_json"]["artifact"]["content_sha256"], match_hash)
        self.assertEqual(result["artifacts"]["phenotype_json"]["artifact"]["content_sha256"], phenotype_hash)
        self.assertEqual(result["artifacts"]["report_json"]["artifact"]["content_sha256"], report_hash)
        self.assertEqual(result["artifacts"]["named_allele_match_json"]["records"][0]["diplotypes"][0]["name"], "*1/*2")
        self.assertEqual(result["artifacts"]["phenotype_json"]["records"][0]["source_diplotypes"][0]["phenotypes"], ["Intermediate Metabolizer"])
        self.assertEqual(result["artifacts"]["report_json"]["metadata"]["pharmcat_version"], "3.2.0")
        payloads_by_type = {item["finding"]["type"]: item for item in result["record_research_payloads"]}
        self.assertIn("pharmcat_sample_pgx_call", payloads_by_type)
        self.assertIn("pharmcat_sample_pgx_match", payloads_by_type)
        self.assertIn("pharmcat_sample_pgx_phenotype", payloads_by_type)
        self.assertIn("pharmcat_sample_pgx_recommendation", payloads_by_type)
        self.assertEqual(payloads_by_type["pharmcat_sample_pgx_call"]["source"]["artifact"]["content_sha256"], calls_hash)
        self.assertEqual(payloads_by_type["pharmcat_sample_pgx_match"]["source"]["artifact"]["content_sha256"], match_hash)
        self.assertEqual(payloads_by_type["pharmcat_sample_pgx_phenotype"]["source"]["artifact"]["content_sha256"], phenotype_hash)
        self.assertEqual(payloads_by_type["pharmcat_sample_pgx_recommendation"]["source"]["artifact"]["content_sha256"], report_hash)
        self.assertTrue(all(item["captured_by"] == "genomi call pharmacogenomics.import_pharmcat_artifacts" for item in result["record_research_payloads"]))
        self.assertEqual(sorted(payloads_by_type), [
            "pharmcat_sample_pgx_call",
            "pharmcat_sample_pgx_match",
            "pharmcat_sample_pgx_phenotype",
            "pharmcat_sample_pgx_recommendation",
        ])
        self.assertTrue(result["interpretation_readiness"]["has_parsed_match_records"])
        self.assertTrue(result["interpretation_readiness"]["has_parsed_phenotype_records"])

    def test_import_asks_for_existing_artifact_when_none_found(self) -> None:
        result = import_pharmcat_artifacts()

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "no_pharmcat_artifacts")

    def test_pipeline_mode_blocks_explicit_outside_call_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vcf = Path(tmp) / "sample.vcf"
            outside = Path(tmp) / "sample.outside.tsv"
            vcf.write_text(
                "##fileformat=VCFv4.2\n"
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE\n"
                "chr10\t94761900\trs4244285\tG\tA\t.\tPASS\t.\tGT\t0/1\n",
                encoding="utf-8",
            )
            outside.write_text("CYP2C19\t*1/*2\n", encoding="utf-8")
            agi_path = self._build_agi(vcf)

            with patch("genomi.capabilities.pharmacogenomics.pharmcat.shutil.which", return_value="/usr/local/bin/pharmcat_pipeline"):
                result = run_pharmcat(agi_path=agi_path, outside_call_file=outside, dry_run=True)

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "outside_call_file_not_supported_in_pipeline_mode")
        self.assertEqual(result["availability"]["mode"], "pipeline")
        self.assertEqual(result["outside_call_validation"]["status"], "completed")

    def test_jar_mode_redacts_explicit_outside_call_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vcf = Path(tmp) / "sample.vcf"
            jar = Path(tmp) / "pharmcat.jar"
            outside = Path(tmp) / "sample.outside.tsv"
            vcf.write_text(
                "##fileformat=VCFv4.2\n"
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE\n"
                "chr10\t94761900\trs4244285\tG\tA\t.\tPASS\t.\tGT\t0/1\n",
                encoding="utf-8",
            )
            jar.write_text("jar", encoding="utf-8")
            outside.write_text("CYP2D6\t*1/*4\tIntermediate Metabolizer\t1.0\n", encoding="utf-8")
            agi_path = self._build_agi(vcf)

            with patch("genomi.capabilities.pharmacogenomics.pharmcat.shutil.which", return_value="/usr/bin/java"):
                result = run_pharmcat(agi_path=agi_path, pharmcat_jar=jar, outside_call_file=outside, mode="jar", dry_run=True)

        self.assertEqual(result["execution"]["mode"], "jar")
        self.assertIn("-po", result["execution"]["command"])
        self.assertIn("[derived_pharmcat_input]", result["execution"]["command"])
        self.assertEqual(result["execution"]["command"][result["execution"]["command"].index("-po") + 1], "[hidden_private_path]")
        self.assertEqual(result["outside_call_validation"]["summary"]["genes"], ["CYP2D6"])

    def test_invalid_outside_call_file_blocks_pharmcat_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vcf = Path(tmp) / "sample.vcf"
            outside = Path(tmp) / "sample.outside.tsv"
            vcf.write_text(
                "##fileformat=VCFv4.2\n"
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE\n"
                "chr10\t94761900\trs4244285\tG\tA\t.\tPASS\t.\tGT\t0/1\n",
                encoding="utf-8",
            )
            outside.write_text("CYP2D6\n", encoding="utf-8")
            agi_path = self._build_agi(vcf)

            with patch("genomi.capabilities.pharmacogenomics.pharmcat.shutil.which", return_value="/usr/local/bin/pharmcat_pipeline"):
                result = run_pharmcat(agi_path=agi_path, outside_call_file=outside, dry_run=True)

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "invalid_outside_call_file")
        self.assertEqual(result["outside_call_validation"]["invalid_rows"][0]["reason"], "missing_diplotype_phenotype_or_activity_score")

    def test_missing_managed_pharmcat_requests_library_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vcf = Path(tmp) / "sample.vcf"
            sample_file = Path(tmp) / "private-samples.txt"
            sample_metadata = Path(tmp) / "private-metadata.json"
            vcf.write_text(
                "##fileformat=VCFv4.2\n"
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE\n"
                "chr10\t94761900\trs4244285\tG\tA\t.\tPASS\t.\tGT\t0/1\n",
                encoding="utf-8",
            )
            sample_file.write_text("SAMPLE\n", encoding="utf-8")
            sample_metadata.write_text("{}", encoding="utf-8")
            agi_path = self._build_agi(vcf)

            with patch("genomi.capabilities.pharmacogenomics.pharmcat.shutil.which", return_value=None):
                result = run_pharmcat(agi_path=agi_path, sample_file=sample_file, sample_metadata=sample_metadata)

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "requires_library_install")
        self.assertEqual(result["missing_library"]["library"], "pharmcat")
        self.assertIn("install_command", result["ask_user"])
        self.assertEqual(result["execution"]["version_probe"]["status"], "skipped")
        self.assertEqual(result["input_preflight"]["status"], "skipped_missing_library")

    def test_explicit_pipeline_mode_reports_unavailable_executable_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vcf = Path(tmp) / "sample.vcf"
            vcf.write_text(
                "##fileformat=VCFv4.2\n"
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE\n"
                "chr10\t94761900\trs4244285\tG\tA\t.\tPASS\t.\tGT\t0/1\n",
                encoding="utf-8",
            )
            agi_path = self._build_agi(vcf)

            with patch("genomi.capabilities.pharmacogenomics.pharmcat.shutil.which", return_value=None):
                result = run_pharmcat(agi_path=agi_path, mode="pipeline")

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "explicit_pharmcat_executable_unavailable")
        self.assertEqual(result["availability"]["mode"], "unavailable")
        self.assertEqual(result["execution"]["version_probe"]["status"], "skipped")

    def test_status_asks_for_install_path_when_unavailable(self) -> None:
        with patch("genomi.capabilities.pharmacogenomics.pharmcat.shutil.which", return_value=None):
            result = pharmcat_status()

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "requires_library_install")
        self.assertEqual(result["missing_library"]["library"], "pharmcat")
        self.assertIn("install_command", result["ask_user"])

    def test_status_reports_version_probe(self) -> None:
        def fake_run(command, **_kwargs):
            return subprocess.CompletedProcess(command, 0, "PharmCAT 3.2.0", "")

        with (
            patch("genomi.capabilities.pharmacogenomics.pharmcat.shutil.which", return_value="/usr/local/bin/pharmcat_pipeline"),
            patch("genomi.capabilities.pharmacogenomics.pharmcat.subprocess.run", side_effect=fake_run) as runner,
        ):
            result = pharmcat_status()

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["version_probe"]["version_text"], "PharmCAT 3.2.0")
        runner.assert_called_once()
        # PharmCAT's CLI rejects the short `-V`; the probe must use `--version`
        # so a working install is not reported as failed.
        probe_command = result["version_probe"]["command"]
        self.assertEqual(probe_command, ["/usr/local/bin/pharmcat_pipeline", "--version"])

    def test_pharmcat_is_agent_operation(self) -> None:
        tools = {tool["name"]: tool for tool in list_operations(capability="pharmacogenomics")}

        self.assertIn("pharmacogenomics.run_pharmcat", tools)
        self.assertIn("pharmacogenomics.preflight_pharmcat", tools)
        self.assertIn("pharmacogenomics.check_pharmcat", tools)
        self.assertIn("pharmacogenomics.import_pharmcat_artifacts", tools)
        self.assertEqual(tools["pharmacogenomics.preflight_pharmcat"]["annotations"]["operationScope"], "read")
        self.assertFalse(tools["pharmacogenomics.preflight_pharmcat"]["annotations"]["mutating"])
        self.assertEqual(tools["pharmacogenomics.preflight_pharmcat"]["annotations"]["privacyScope"], "local_private")
        self.assertEqual(tools["pharmacogenomics.import_pharmcat_artifacts"]["annotations"]["operationScope"], "read")
        self.assertFalse(tools["pharmacogenomics.import_pharmcat_artifacts"]["annotations"]["mutating"])
        import_properties = tools["pharmacogenomics.import_pharmcat_artifacts"]["inputSchema"]["properties"]
        self.assertIn("match_json", import_properties)
        self.assertIn("phenotype_json", import_properties)
        self.assertEqual(tools["pharmacogenomics.run_pharmcat"]["annotations"]["operationScope"], "write")
        self.assertTrue(tools["pharmacogenomics.run_pharmcat"]["annotations"]["mutating"])
        self.assertEqual(tools["pharmacogenomics.run_pharmcat"]["annotations"]["privacyScope"], "local_private")
        self.assertEqual(tools["pharmacogenomics.check_pharmcat"]["annotations"]["operationScope"], "read")
        self.assertFalse(tools["pharmacogenomics.check_pharmcat"]["annotations"]["mutating"])
        self.assertEqual(tools["pharmacogenomics.check_pharmcat"]["annotations"]["privacyScope"], "metadata_only")

    def test_preflight_operation_uses_active_genome_index_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vcf = Path(tmp) / "sample.vcf"
            vcf.write_text(
                "##fileformat=VCFv4.2\n"
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE\n"
                "10\t94761900\trs4244285\tG\tA\t.\tPASS\t.\tGT\t0/1\n",
                encoding="utf-8",
            )
            parsed = call_operation("genomi.parse_source", {"source": str(vcf), "force": True})
            call_operation(
                "active_genome_index.assign_user_genome",
                {
                    "nickname": "Test user",
                    "source": str(vcf),
                    "agi_path": parsed["outputs"]["agi_path"],
                },
            )

            result = call_operation("pharmacogenomics.preflight_pharmcat")

        self.assertEqual(result["status"], "completed")
        self.assertIn("evidence_envelope", result)
        self.assertTrue(result["input_preflight"]["input"]["hidden_agi_path"])

    def test_call_operation_uses_active_genome_index_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vcf = Path(tmp) / "sample.vcf"
            vcf.write_text(
                "##fileformat=VCFv4.2\n"
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE\n"
                "10\t94761900\trs4244285\tG\tA\t.\tPASS\t.\tGT\t0/1\n",
                encoding="utf-8",
            )
            parsed = call_operation("genomi.parse_source", {"source": str(vcf), "force": True})
            call_operation(
                "active_genome_index.assign_user_genome",
                {
                    "nickname": "Test user",
                    "source": str(vcf),
                    "agi_path": parsed["outputs"]["agi_path"],
                },
            )

            with patch(
                "genomi.operations.pharmcat.run_pharmcat",
                return_value={"status": "planned"},
            ) as runner:
                result = call_operation("pharmacogenomics.run_pharmcat", {"dry_run": True})

        self.assertEqual(result["status"], "planned")
        runner.assert_called_once()
        self.assertEqual(
            Path(runner.call_args.kwargs["agi_path"]).resolve(strict=False),
            Path(parsed["outputs"]["agi_path"]).resolve(strict=False),
        )
        self.assertTrue(runner.call_args.kwargs["dry_run"])

    def test_run_pharmcat_accepts_agi_path_without_original_vcf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vcf = Path(tmp) / "sample.vcf"
            vcf.write_text(
                "##fileformat=VCFv4.2\n"
                "##reference=GRCh38\n"
                "##contig=<ID=chr1,length=248956422>\n"
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE\n"
                "chr1\t1\t.\tA\tG\t.\tPASS\t.\tGT\t0/1\n",
                encoding="utf-8",
            )
            agi_path = self._build_agi(vcf)
            vcf.unlink()

            with patch("genomi.capabilities.pharmacogenomics.pharmcat.shutil.which", return_value="/usr/local/bin/pharmcat_pipeline"):
                result = run_pharmcat(agi_path=agi_path, dry_run=True)

        self.assertEqual(result["status"], "planned", result)
        self.assertEqual(result["pharmcat_input"]["method"], "active_genome_index_export")
        self.assertTrue(result["input"]["hidden_agi_path"])

    def test_run_pharmcat_blocks_variant_only_export_when_agi_has_reference_or_no_call_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vcf = Path(tmp) / "sample.g.vcf"
            vcf.write_text(
                "##fileformat=VCFv4.2\n"
                "##reference=GRCh38\n"
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE\n"
                "1\t1\t.\tA\t.\t.\tPASS\tEND=1\tGT\t0/0\n",
                encoding="utf-8",
            )
            agi_path = self._build_agi(vcf)

            with patch("genomi.capabilities.pharmacogenomics.pharmcat.shutil.which", return_value="/usr/local/bin/pharmcat_pipeline"):
                result = run_pharmcat(agi_path=agi_path, dry_run=True)

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "position_aware_pharmcat_export_required")
        self.assertEqual(result["pharmcat_input"]["status"], "position_aware_pharmcat_export_required")
        self.assertGreater(result["pharmcat_input"]["reference_records"], 0)

    def test_run_pharmcat_blocks_variant_only_export_when_agi_has_no_call_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vcf = Path(tmp) / "sample.vcf"
            vcf.write_text(
                "##fileformat=VCFv4.2\n"
                "##reference=GRCh38\n"
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE\n"
                "1\t1\trs1\tA\tG\t.\tPASS\t.\tGT\t0/1\n"
                "1\t2\trs2\tC\tT\t.\tPASS\t.\tGT\t./.\n",
                encoding="utf-8",
            )
            agi_path = self._build_agi(vcf)

            with patch("genomi.capabilities.pharmacogenomics.pharmcat.shutil.which", return_value="/usr/local/bin/pharmcat_pipeline"):
                result = run_pharmcat(agi_path=agi_path, dry_run=True)

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "position_aware_pharmcat_export_required")
        self.assertEqual(result["pharmcat_input"]["reference_records"], 0)
        self.assertEqual(result["pharmcat_input"]["no_call_records"], 1)

    def test_run_pharmcat_preflights_explicit_agi_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vcf = Path(tmp) / "sample.vcf"
            index = Path(tmp) / "selected.sqlite"
            output = Path(tmp) / "out"
            vcf.write_text(
                "##fileformat=VCFv4.2\n"
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE\n"
                "10\t94761900\trs4244285\tG\tA\t.\tPASS\t.\tGT\t0/1\n",
                encoding="utf-8",
            )
            index.write_text("placeholder agi file for patched preflight\n", encoding="utf-8")
            with (
                patch("genomi.capabilities.pharmacogenomics.pharmcat.execution.shutil.which", return_value="/usr/local/bin/pharmcat_pipeline"),
                patch(
                    "genomi.capabilities.pharmacogenomics.pharmcat.execution._input_preflight",
                    return_value={"status": "completed"},
                ) as preflight,
                patch(
                    "genomi.capabilities.pharmacogenomics.pharmcat.execution._prepare_pharmcat_input",
                    return_value={"status": "active_genome_index_input_unavailable", "remediated": False},
                ),
            ):
                result = run_pharmcat(
                    agi_path=index,
                    output_dir=output,
                    dry_run=True,
                )

        self.assertEqual(result["status"], "active_genome_index_input_unavailable")
        self.assertEqual(Path(preflight.call_args.args[0]), index)


if __name__ == "__main__":
    unittest.main()
