from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from genomi.active_genome_index.active_genome_index import create_active_genome_index
from genomi.capabilities.decode import evidence_builder
from genomi.evidence import init_evidence_db
from genomi.interfaces.presentation import present_result
from genomi.operations import OPERATIONS, TOOL_CATALOG, call_operation
from genomi.operations.registry import handlers_screen_journal
from genomi.runtime import context as runtime_context

_DECODE_BUILDER_PATCH = (
    "genomi.operations.registry.handlers_screen_journal."
    "decode_evidence_builder.build_dashboard_evidence"
)


def _extract_evidence(html: str) -> dict:
    marker = "window.__GENOMI_DASHBOARD__"
    assignment_index = html.find(marker)
    assert assignment_index >= 0, "no __GENOMI_DASHBOARD__ block in HTML"
    json_start = html.find("{", assignment_index)
    assert json_start >= 0, "no __GENOMI_DASHBOARD__ object in HTML"
    parsed, _end = json.JSONDecoder().raw_decode(html[json_start:].replace("<\\/", "</"))
    assert isinstance(parsed, dict), "__GENOMI_DASHBOARD__ is not an object"
    return parsed


class DecodeDashboardEvidenceBuilderTests(unittest.TestCase):
    def test_builds_render_params_from_existing_operations(self) -> None:
        calls: list[tuple[str, dict]] = []

        def run(operation: str, params: dict) -> dict:
            calls.append((operation, params))
            if operation == "active_genome_index.summarize":
                return {
                    "active_genome_index": {
                        "metadata": {"header": {"samples": ["BUILT"]}},
                        "stats": {"variant_records": 100},
                    },
                }
            if operation == "clinvar.scan_candidates":
                return {
                    "status": "completed",
                    "input": "/tmp/clinvar.matches.jsonl",
                    "candidate_inventory": [
                        {
                            "variant": {"id": "rs1", "chrom": "1", "pos": 10, "ref": "A", "alt": "G"},
                            "clinvar": {"clinical_significance_counts": [["Pathogenic", 1]]},
                            "genes": ["GENE1"],
                        }
                    ],
                }
            if operation == "pharmacogenomics.run_pharmcat":
                return {"status": "requires_library_install", "missing_library": {"library": "pharmcat"}}
            if operation == "prs.list_imported_scores":
                return {"status": "completed", "scores": [{"pgs_id": "PGS000001"}]}
            if operation == "prs.calculate_score":
                return {
                    "status": "completed",
                    "polygenic_score": {"pgs_id": params["pgs_id"], "reported_trait": "LDL cholesterol"},
                    "sample_qc": {"matched_variant_count": 2, "score_variant_count": 4},
                    "score_result": {"raw_weighted_score": 1.5},
                }
            if operation == "ancestry.estimate_population_context":
                return {"nearest_reference_groups": [{"group": "EUR", "score": 0.9}]}
            if operation == "nutrigenomics.list_domains":
                return {"domains": [{"domain_id": "folate_metabolism"}]}
            if operation == "nutrigenomics.retrieve_domain_markers":
                return {
                    "coverage_state": "data_returned",
                    "markers": [
                        {
                            "domain": "folate_metabolism",
                            "gene": {"symbol": "MTHFR"},
                            "variant": {"rsid": "rs1801133"},
                        }
                    ],
                }
            raise AssertionError(f"unexpected operation {operation}")

        result = evidence_builder.build_dashboard_evidence(
            params={"risk_score_limit": 1},
            run_operation=run,
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["render_params"]["variants_all_source"], "/tmp/clinvar.matches.jsonl")
        self.assertIn("overview", result["panels_ready"])
        self.assertIn("variants_all", result["panels_ready"])
        self.assertIn("pgx", result["panels_empty"])
        self.assertIn("pgx", result["panels_blocked"])
        self.assertEqual(result["render_params"]["evidence"]["risk"][0]["polygenic_score"]["pgs_id"], "PGS000001")
        self.assertIn(("pharmacogenomics.run_pharmcat", {}), calls)
        self.assertIn(("prs.calculate_score", {"pgs_id": "PGS000001"}), calls)

    def test_overview_prefers_active_intake_format_over_derived_vcf_metadata(self) -> None:
        def run(operation: str, params: dict) -> dict:
            if operation == "active_genome_index.summarize":
                return {
                    "active_genome_index": {
                        "metadata": {"source_format": "vcf"},
                        "stats": {"variant_records": 2},
                    }
                }
            raise AssertionError(f"unexpected operation {operation}")

        result = evidence_builder.build_dashboard_evidence(
            params={"panels": ["overview"]},
            run_operation=run,
            active_genome_index_context={
                "agi_source_format": "bam",
                "agi_source_kind": "alignment_reads",
                "sample_slug": "bam-fixture",
                "genome_build": "GRCh37",
                "agi_path": "/tmp/private.active-genome-index.sqlite",
            },
        )

        overview = result["render_params"]["evidence"]["overview"]
        self.assertEqual(overview["agi_source_format"], "bam")
        self.assertEqual(overview["agi_source_kind"], "alignment_reads")
        self.assertEqual(overview["sample_slug"], "bam-fixture")
        self.assertNotIn("agi_path", overview)

    def test_blocked_pgx_pharmcat_result_is_not_panel_ready(self) -> None:
        calls: list[tuple[str, dict]] = []

        def run(operation: str, params: dict) -> dict:
            calls.append((operation, params))
            if operation == "pharmacogenomics.run_pharmcat":
                return {
                    "status": "position_aware_pharmcat_export_required",
                    "pharmcat_input": {"status": "position_aware_pharmcat_export_required"},
                    "input_preflight": {"status": "completed"},
                    "evidence_envelope": {
                        "finding_state": "not_assessed",
                        "answer_readiness": "cannot_answer_yet",
                    },
                }
            raise AssertionError(f"unexpected operation {operation}")

        result = evidence_builder.build_dashboard_evidence(
            params={"panels": ["pgx"]},
            run_operation=run,
        )

        self.assertNotIn("pgx", result["panels_ready"])
        self.assertIn("pgx", result["panels_empty"])
        self.assertIn("pgx", result["panels_blocked"])
        self.assertEqual(result["panel_states"][0]["status"], "position_aware_pharmcat_export_required")
        self.assertEqual(calls, [("pharmacogenomics.run_pharmcat", {})])

    def test_pgx_runs_as_background_panel_when_runtime_background_enabled(self) -> None:
        calls: list[tuple[str, dict]] = []

        def run(operation: str, params: dict) -> dict:
            calls.append((operation, params))
            raise AssertionError(f"unexpected inline operation {operation}")

        started = {
            "job_id": "pharmacogenomics-run-pharmcat-1",
            "operation": "pharmacogenomics.run_pharmcat",
            "status": "running",
        }
        public_status = {
            "status": "in_progress",
            "job_id": "pharmacogenomics-run-pharmcat-1",
            "operation": "pharmacogenomics.run_pharmcat",
            "heartbeat_at": "2026-06-07T00:00:00+00:00",
            "check": {
                "operation": "genomi.check_background_job",
                "params": {"job_id": "pharmacogenomics-run-pharmcat-1"},
            },
            "message": "pharmacogenomics.run_pharmcat is still running in the background.",
        }
        with (
            mock.patch.object(evidence_builder.background_jobs, "background_enabled", return_value=True),
            mock.patch.object(evidence_builder.background_jobs, "operation_params_digest", return_value="pgx-digest"),
            mock.patch.object(evidence_builder.background_jobs, "find_latest_job", return_value=None),
            mock.patch.object(evidence_builder.background_jobs, "start_operation_job", return_value=started) as start_job,
            mock.patch.object(evidence_builder.background_jobs, "wait_for_job", return_value=started) as wait_job,
            mock.patch.object(evidence_builder.background_jobs, "public_job_status", return_value=public_status),
        ):
            result = evidence_builder.build_dashboard_evidence(
                params={"panels": ["pgx"]},
                run_operation=run,
                active_genome_index_context={"agi_id": "agi-target"},
            )

        self.assertEqual(calls, [])
        start_job.assert_called_once_with("pharmacogenomics.run_pharmcat", {"agi_id": "agi-target"})
        wait_job.assert_called_once_with("pharmacogenomics-run-pharmcat-1", timeout_seconds=0.0)
        self.assertNotIn("pgx", result["panels_ready"])
        self.assertIn("pgx", result["panels_empty"])
        self.assertEqual(result["panels_running"], ["pgx"])
        self.assertEqual(result["panels_blocked"], [])
        self.assertEqual(result["panel_states"][0]["status"], "in_progress")
        self.assertEqual(result["panel_states"][0]["job_id"], "pharmacogenomics-run-pharmcat-1")
        self.assertEqual(
            result["panel_states"][0]["check"],
            {"operation": "genomi.check_background_job", "params": {"job_id": "pharmacogenomics-run-pharmcat-1"}},
        )

    def test_pgx_reuses_completed_background_job_as_panel_evidence(self) -> None:
        def run(operation: str, params: dict) -> dict:
            raise AssertionError(f"unexpected inline operation {operation}")

        completed_job = {
            "job_id": "pharmacogenomics-run-pharmcat-done",
            "operation": "pharmacogenomics.run_pharmcat",
            "status": "completed",
            "result": {
                "status": "completed",
                "record_research_payloads": [
                    {
                        "gene": "CYP2C19",
                        "diplotype": "*1/*2",
                        "phenotype": "intermediate metabolizer",
                    }
                ],
            },
        }

        with (
            mock.patch.object(evidence_builder.background_jobs, "background_enabled", return_value=True),
            mock.patch.object(evidence_builder.background_jobs, "operation_params_digest", return_value="pgx-digest"),
            mock.patch.object(evidence_builder.background_jobs, "find_latest_job", return_value=completed_job) as find_job,
            mock.patch.object(evidence_builder.background_jobs, "start_operation_job") as start_job,
            mock.patch.object(evidence_builder.background_jobs, "wait_for_job", return_value=completed_job),
        ):
            result = evidence_builder.build_dashboard_evidence(
                params={"panels": ["pgx"]},
                run_operation=run,
                active_genome_index_context={"agi_id": "agi-target"},
            )

        find_job.assert_called_once_with(
            "pharmacogenomics.run_pharmcat",
            "pgx-digest",
            statuses={"completed"},
        )
        start_job.assert_not_called()
        self.assertEqual(result["panels_ready"], ["pgx"])
        self.assertEqual(result["panels_empty"], [])
        self.assertEqual(result["panels_running"], [])
        self.assertEqual(result["render_params"]["evidence"]["pgx"]["status"], "completed")

    def test_decode_panel_runner_threads_target_agi_to_private_panels(self) -> None:
        seen: list[tuple[str, dict]] = []

        def fake_run(operation: str, params: dict | None = None) -> dict:
            seen.append((operation, dict(params or {})))
            return {"status": "completed"}

        with mock.patch.object(handlers_screen_journal, "_run_decode_panel_operation", side_effect=fake_run):
            run = handlers_screen_journal._decode_panel_runner_for_target("agi-target")
            run("active_genome_index.summarize")
            run("clinvar.scan_candidates", {"force": True})
            run("prs.list_imported_scores", {"limit": 1})

        self.assertEqual(seen[0], ("active_genome_index.summarize", {"agi_id": "agi-target"}))
        self.assertEqual(seen[1], ("clinvar.scan_candidates", {"force": True, "agi_id": "agi-target"}))
        self.assertEqual(seen[2], ("prs.list_imported_scores", {"limit": 1}))

    def test_decode_builder_does_not_forward_panel_refresh_knobs(self) -> None:
        calls: list[tuple[str, dict]] = []

        def run(operation: str, params: dict | None = None) -> dict:
            calls.append((operation, dict(params or {})))
            return {"status": "completed", "candidate_inventory": []}

        evidence_builder.build_dashboard_evidence(
            params={"panels": ["variants"], "force": True},
            run_operation=run,
        )

        self.assertEqual(calls, [("clinvar.scan_candidates", {})])

    def test_catalog_exposes_builder(self) -> None:
        names = {op.name for op in OPERATIONS}
        self.assertIn("decode.build_dashboard_evidence", names)
        decode_capability = TOOL_CATALOG["capabilities"]["decode"]
        self.assertEqual(decode_capability["entry_operations"], ["decode.render_dashboard"])
        self.assertIn("decode.build_dashboard_evidence", decode_capability["operations"])

    def test_presented_build_result_reports_panel_state_only(self) -> None:
        raw = {
            "status": "completed",
            "panels_requested": ["overview", "variants_all"],
            "panels_ready": ["overview", "variants_all"],
            "panels_empty": ["pgx"],
            "panels_blocked": ["pgx"],
            "panel_states": [{"panel": "pgx", "status": "position_aware_pharmcat_export_required"}],
            "render_params": {
                "evidence": {
                    "overview": {
                        "active_genome_index": {
                            "metadata": {"header": {"samples": ["HG"]}},
                            "stats": {"variant_records": 1},
                        }
                    }
                },
                "variants_all_source": "/tmp/clinvar.matches.jsonl",
            },
        }

        presented = present_result("decode.build_dashboard_evidence", raw)

        self.assertEqual(
            set(presented),
            {"status", "panels_requested", "panels_ready", "panels_empty", "panels_blocked", "panel_states"},
        )
        self.assertEqual(presented["panels_ready"], ["overview", "variants_all"])


class DecodeRenderAutoBuildTests(unittest.TestCase):
    def setUp(self) -> None:
        self._home_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._home_tmp.cleanup)
        self.genomi_home = Path(self._home_tmp.name) / "genomi-home"
        self._env = mock.patch.dict(
            os.environ,
            {
                "GENOMI_HOME": str(self.genomi_home),
                "GENOMI_CONTEXT": "",
                "GENOMI_SESSION_ID": "",
                "GENOMI_MCP_BACKGROUND": "0",
                **{name: "" for name in runtime_context.AGENT_SESSION_ENVS},
            },
        )
        self._env.start()
        self.addCleanup(self._env.stop)

    def test_render_uses_code_owned_builder(self) -> None:
        with tempfile.TemporaryDirectory() as wd:
            wd_path = Path(wd)
            previous = os.getcwd()
            os.chdir(wd_path)
            try:
                vcf = wd_path / "sample.vcf"
                vcf.write_text(
                    "##fileformat=VCFv4.2\n"
                    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tsample\n"
                    "10\t94761900\trs4244285\tG\tA\t50\tPASS\t.\tGT:DP:GQ\t0/1:31:99\n",
                    encoding="utf-8",
                )
                agi_path = wd_path / "sample.active-genome-index.sqlite"
                evidence_db = wd_path / "evidence.sqlite"
                create_active_genome_index(vcf, agi_path)
                init_evidence_db(evidence_db)
                runtime_context.set_active_agi_from_source(
                    vcf,
                    status="parsed",
                    operation_result={
                        "sample_slug": "sample",
                        "agi_intake_source_path": str(vcf),
                        "evidence_db": str(evidence_db),
                        "work_dir": str(wd_path),
                        "outputs": {"agi_path": str(agi_path)},
                    },
                )
                call_operation("active_genome_index.approve_access", {"approved_by_user": True, "reason": "test"})
                out = wd_path / "dash.html"
                built = {
                    "status": "completed",
                    "render_params": {"evidence": {"overview": {"sampleId": "BUILT", "variantCount": 1}}},
                    "panels_ready": ["overview"],
                    "panels_empty": ["variants"],
                    "panels_blocked": [],
                    "panels_running": [],
                    "panels_failed": ["pgx"],
                    "panels_requested": ["overview", "pgx"],
                    "panel_states": [
                        {"panel": "overview", "status": "data_returned"},
                        {
                            "panel": "pgx",
                            "status": "failed",
                            "source_operation": "pharmacogenomics.run_pharmcat",
                            "error": {"code": "pharmcat_vcf_parse_failed", "message": "invalid INFO field"},
                        },
                    ],
                    "evidence_envelope": {
                        "operation": "decode.build_dashboard_evidence",
                        "headline": "decode.build_dashboard_evidence: evidence_present · scoped_answer_only",
                        "finding_state": "evidence_present",
                        "answer_readiness": "scoped_answer_only",
                        "guidance": [],
                        "negative_inference": {"allowed": False, "requires": []},
                        "observations": {
                            "panels_ready": ["overview"],
                            "panels_failed": ["pgx"],
                        },
                    },
                }
                with mock.patch(_DECODE_BUILDER_PATCH, return_value=built) as build:
                    result = call_operation(
                        "decode.render_dashboard",
                        {"output": str(out), "panels": ["overview"]},
                    )

                self.assertEqual(result["status"], "completed")
                self.assertEqual(result["evidence_build"]["panels_ready"], ["overview"])
                self.assertEqual(result["evidence_build"]["panels_failed"], ["pgx"])
                self.assertEqual(result["evidence_envelope"]["operation"], "decode.render_dashboard")
                self.assertEqual(result["evidence_envelope"]["observations"]["panels_failed"], ["pgx"])
                parsed = _extract_evidence(out.read_text(encoding="utf-8"))
                self.assertEqual(parsed["overview"]["sampleId"], "BUILT")
                self.assertEqual(parsed["__dashboard"]["panelStates"][1]["panel"], "pgx")
                self.assertEqual(parsed["__dashboard"]["panelsRequested"], ["overview", "pgx"])
                build.assert_called_once()
                self.assertEqual(build.call_args.kwargs["params"], {"output": str(out), "panels": ["overview"]})
            finally:
                os.chdir(previous)


if __name__ == "__main__":
    unittest.main()
