from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from unittest import mock

from genomi.interfaces.cli import build_parser
from genomi.interfaces.mcp import handle_request
from genomi.interfaces.presentation import present_result
from genomi.operations import OperationError, call_operation
from genomi.runtime import background_jobs
from genomi.runtime import context as runtime_context

from _genomi_runtime_helpers import (
    DEFAULT_TASK_ENTRY_TOOLS,
    GenomiRuntimeTestCase,
)


class GenomiRuntimeContextTests(GenomiRuntimeTestCase):
    def test_gwas_compare_variants_is_direct_tool_not_runtime_plan(self) -> None:
        with mock.patch(
            "genomi.operations.intent_research.compare_gwas_variant_context",
            return_value={
                "query": {"phenotype": "erythritol", "variants": ["rs2000999", "rs6687813"]},
                "rankings": [],
            },
        ):
            result = call_operation(
                "gwas.compare_variant_associations",
                {"phenotype": "erythritol", "variants": ["rs2000999", "rs6687813"]},
            )

        self.assertEqual(result["query"]["phenotype"], "erythritol")
        self.assertEqual(result["query"]["variants"], ["rs2000999", "rs6687813"])
        self.assertIn("rankings", result)

    def test_screen_compare_gene_is_direct_tool_not_runtime_plan(self) -> None:
        with mock.patch(
            "genomi.operations.intent_research.compare_screen_gene_context",
            return_value={
                "query": {"context": "A549 resistance screen", "genes": ["EGFR", "MYC"]},
                "candidate_matrix": [],
            },
        ):
            result = call_operation(
                "functional_genomics.compare_gene_perturbation",
                {"context": "A549 resistance screen", "genes": ["EGFR", "MYC"], "source_records": []},
            )

        self.assertEqual(result["query"]["context"], "A549 resistance screen")
        self.assertEqual(result["query"]["genes"], ["EGFR", "MYC"])
        self.assertIn("candidate_matrix", result)

    def test_standard_presentation_preserves_decision_evidence_scalars(self) -> None:
        result = call_operation(
            "functional_genomics.compare_gene_perturbation",
            {
                "context": "CRISPR knockout phagocytosis screen",
                "genes": ["NHLRC2", "KPNA2"],
                "source_records": [
                    {
                        "record_id": "screen-1",
                        "title": "Genome-wide CRISPR screen identifies NHLRC2",
                        "text": "NHLRC2 was a top hit in a CRISPR knockout screen measuring phagocytosis.",
                        "source_type": "CRISPR screen",
                        "genes": ["NHLRC2"],
                        "verified_fields": {
                            "genes": ["NHLRC2"],
                            "assays": ["phagocytosis"],
                            "perturbations": ["CRISPR knockout"],
                        },
                    }
                ],
            },
        )

        presented = present_result("functional_genomics.compare_gene_perturbation", result)
        self.assertIsNone(presented["decision_evidence"]["top_observed_evidence"])
        top_evidence = presented["decision_evidence"]["ranked_candidate_evidence"][0]

        self.assertEqual(top_evidence["evidence_trace"]["supporting_record_ids"], ["screen-1"])
        self.assertEqual(top_evidence["evidence_trace"]["supporting_evidence_count"], 1)

    # NOTE: test_panel_tools_are_agent_native_and_hide_intake_source was
    # removed when nutrition_core/common_risk_core panels were deleted (their
    # content moved into the nutrigenomics capability). Re-add when a new
    # built-in panel is added; until then, the marker_panel machinery has
    # no built-in fixtures to exercise.

    def test_context_can_be_empty_or_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                empty = call_operation("genomi.describe_context")
                self.assertFalse(empty["has_active_genome_index"])

                vcf = Path("sample.vcf")
                vcf.write_text(
                    "##fileformat=VCFv4.2\n"
                    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tNA12878\n",
                    encoding="utf-8",
                )
                set_result = call_operation("genomi.parse_source", {"source": str(vcf)})
                self.assertEqual(set_result["status"], "completed")
                self.assertTrue(set_result["active_genome_index"]["sample_slug"].startswith("vcf-sha256-"))

                current = call_operation("genomi.describe_context")
                self.assertTrue(current["has_active_genome_index"])
                self.assertEqual(current["active_genome_index"]["sample_slug"], set_result["active_genome_index"]["sample_slug"])

                summary = call_operation("active_genome_index.summarize")
                self.assertIn("outputs", summary)
            finally:
                os.chdir(previous)


    def test_existing_personal_dna_artifacts_require_session_approval_after_revoke(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                vcf = Path("sample.vcf")
                vcf.write_text(
                    "##fileformat=VCFv4.2\n"
                    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tNA12878\n",
                    encoding="utf-8",
                )
                call_operation("genomi.parse_source", {"source": str(vcf)})
                current = call_operation("genomi.describe_context")
                self.assertTrue(current["has_active_genome_index"])
                self.assertTrue(current["active_genome_index_access"]["approved"])

                call_operation("genomi.revoke_agi_access")
                current_after_revoke = call_operation("genomi.describe_context")
                self.assertTrue(current_after_revoke["has_active_genome_index"])
                self.assertFalse(current_after_revoke["active_genome_index_access"]["approved"])

                with self.assertRaises(OperationError) as raised:
                    call_operation("active_genome_index.summarize")
                self.assertEqual(raised.exception.code, "active_genome_index_approval_required")

                self.approve_agi_access()
                summary = call_operation("active_genome_index.summarize")
                self.assertIn("outputs", summary)
            finally:
                os.chdir(previous)

    def test_known_agis_do_not_auto_activate_without_default_in_another_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as cwd_one, tempfile.TemporaryDirectory() as cwd_two:
            previous = os.getcwd()
            try:
                os.chdir(cwd_one)
                vcf = Path("sample.vcf")
                vcf.write_text(
                    "##fileformat=VCFv4.2\n"
                    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tNA12878\n",
                    encoding="utf-8",
                )
                set_result = call_operation("genomi.parse_source", {"source": str(vcf), "user_nickname": "Alex"})
                agi_id = set_result["active_genome_index"]["agi_id"]
                listed = call_operation("genomi.list_users")
                self.assertEqual(listed["users"][0]["nickname"], "Alex")
                renamed = call_operation("genomi.rename_user", {"nickname": "Alex", "new_nickname": "Alex Renamed"})
                self.assertEqual(renamed["user"]["nickname"], "Alex Renamed")
                self.assertTrue(call_operation("genomi.describe_context")["has_active_genome_index"])

                os.chdir(cwd_two)
                current = call_operation("genomi.describe_context")
                self.assertFalse(current["has_active_genome_index"])
                self.assertEqual(current["active_genome_index_registry"]["known_agi_count"], 1)

                resumed = call_operation("genomi.approve_agi_access", {"approved_by_user": True, "agi_id": agi_id})
                self.assertEqual(resumed["active_agi_id"], agi_id)
                by_nickname = call_operation("genomi.select_user", {"nickname": "Alex Renamed"})
                self.assertEqual(by_nickname["context"]["active_agi_id"], agi_id)
                self.assertTrue(call_operation("genomi.describe_context")["has_active_genome_index"])
            finally:
                os.chdir(previous)

    def test_context_current_follows_agent_chat_session_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as cwd_one, tempfile.TemporaryDirectory() as cwd_two:
            previous = os.getcwd()
            try:
                with mock.patch.dict(os.environ, {"CODEX_THREAD_ID": "chat-one"}):
                    os.chdir(cwd_one)
                    vcf = Path("sample.vcf")
                    vcf.write_text(
                        "##fileformat=VCFv4.2\n"
                        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tNA12878\n",
                        encoding="utf-8",
                    )
                    set_result = call_operation("genomi.parse_source", {"source": str(vcf)})
                    agi_id = set_result["active_genome_index"]["agi_id"]
                    self.assertTrue(call_operation("genomi.describe_context")["has_active_genome_index"])

                    os.chdir(cwd_two)
                    same_chat = call_operation("genomi.describe_context")
                    self.assertTrue(same_chat["has_active_genome_index"])
                    self.assertEqual(same_chat["active_agi_id"], agi_id)

                with mock.patch.dict(os.environ, {"CODEX_THREAD_ID": "chat-two"}):
                    other_chat = call_operation("genomi.describe_context")
                    self.assertFalse(other_chat["has_active_genome_index"])
                    self.assertEqual(other_chat["active_genome_index_registry"]["known_agi_count"], 1)
            finally:
                os.chdir(previous)

    def test_default_user_auto_selects_active_genome_index_across_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as cwd_one, tempfile.TemporaryDirectory() as cwd_two:
            previous = os.getcwd()
            try:
                os.chdir(cwd_one)
                vcf = Path("sample.vcf")
                vcf.write_text(
                    "##fileformat=VCFv4.2\n"
                    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tNA12878\n",
                    encoding="utf-8",
                )
                selected = call_operation("genomi.parse_source", {"source": str(vcf), "user_nickname": "Default user", "set_default_user": True})
                agi_id = selected["active_genome_index"]["agi_id"]

                os.chdir(cwd_two)
                current = call_operation("genomi.describe_context")
                self.assertTrue(current["has_active_genome_index"])
                self.assertEqual(current["active_agi_id"], agi_id)
                self.assertTrue(current["default_auto_selected"])
                self.assertEqual(current["active_genome_index_access"]["scope"], "persistent_default")
                cleared = call_operation("genomi.clear_default_user")
                self.assertTrue(cleared["cleared_default"])
                self.assertFalse(call_operation("genomi.describe_context")["has_active_genome_index"])
            finally:
                os.chdir(previous)

    def test_vcf_tool_without_context_fails_actionably(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                with self.assertRaises(OperationError) as raised:
                    call_operation("active_genome_index.summarize")
                self.assertEqual(raised.exception.code, "missing_context")
            finally:
                os.chdir(previous)

    def test_non_vcf_evidence_tools_can_use_shared_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                result = call_operation("research.search", {"query": "brca"})
                self.assertEqual(result["query"]["source"], "research_findings")
                self.assertEqual(result["count"], 0)
                self.assertTrue((self.genomi_home / "shared-evidence.sqlite").exists())
            finally:
                os.chdir(previous)

    def test_search_indexes_does_not_search_active_metadata_without_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sample.vcf"
            source.write_text(
                "##fileformat=VCFv4.2\n"
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE\n",
                encoding="utf-8",
            )
            runtime_context.set_active_genome_index(
                source,
                status="parsed",
                active_genome_index_path=source.with_suffix(".sqlite"),
                genome_build="GRCh38",
            )

            blocked = call_operation(
                "genomi.search_indexes",
                {"query": "GRCh38", "include_private_metadata": True},
            )
            self.assertEqual(blocked["private_metadata"]["status"], "active_genome_index_approval_required")

            runtime_context.approve_agi_access(reason="test approved Active Genome Index metadata access")
            allowed = call_operation(
                "genomi.search_indexes",
                {"query": "GRCh38", "include_private_metadata": True},
            )
            self.assertEqual(allowed["private_metadata"]["status"], "included")
            self.assertEqual(allowed["search_results"][-1]["source"], "active_genome_index_metadata")
            self.assertEqual(allowed["search_results"][-1]["hits"][0]["metadata"]["genome_build"], "GRCh38")

    def test_record_research_accepts_inline_payload_for_shared_evidence(self) -> None:
        payload = {
            "target": {"type": "drug", "drug": "clopidogrel"},
            "source": {
                "title": "CPIC clopidogrel guideline",
                "url": "https://cpicpgx.org/guidelines/",
                "type": "pharmacogenomic_guideline",
            },
            "finding": {
                "type": "clinpgx_guideline_annotation",
                "text": "CPIC clopidogrel and CYP2C19 source context.",
                "summary": "CPIC clopidogrel guidance.",
            },
            "captured_by": "test",
        }

        result = call_operation("research.record", {"payload": payload, "scope": "shared"})
        queried = call_operation("research.query", {"target_type": "drug", "drug": "clopidogrel"})

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["scope"], "shared")
        self.assertEqual(result["shared_sync"]["status"], "same_db")
        self.assertEqual(Path(result["evidence_db"]), self.genomi_home / "shared-evidence.sqlite")
        self.assertEqual(queried["count"], 1)
        self.assertEqual(queried["records"][0]["scope"], "shared")
        self.assertEqual(queried["records"][0]["finding"]["type"], "clinpgx_guideline_annotation")

    def test_private_inline_research_requires_private_evidence_db(self) -> None:
        payload = {
            "target": {"type": "gene", "gene": "CYP2C19"},
            "source": {
                "title": "PharmCAT sample PGx call artifact",
                "url": "https://pharmcat.clinpgx.org/",
                "type": "sample_pharmacogenomic_call",
            },
            "finding": {
                "type": "pharmcat_sample_pgx_call",
                "text": "PharmCAT call for CYP2C19; diplotype *1/*2.",
                "summary": "CYP2C19 *1/*2.",
            },
            "captured_by": "test",
        }

        with self.assertRaises(OperationError) as raised:
            call_operation("research.record", {"payload": payload, "scope": "private"})
        self.assertEqual(raised.exception.code, "missing_context")

        with tempfile.TemporaryDirectory() as tmp:
            private_db = Path(tmp) / "private.sqlite"
            result = call_operation(
                "research.record",
                {"db": str(private_db), "payload": payload, "scope": "private", "sync_shared": False},
            )
            queried = call_operation(
                "research.query",
                {"db": str(private_db), "target_type": "gene", "gene": "CYP2C19", "scope": "private"},
            )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["scope"], "private")
        self.assertEqual(result["shared_sync"]["status"], "disabled")
        self.assertEqual(queried["count"], 1)
        self.assertEqual(queried["records"][0]["scope"], "private")

    def test_mcp_lists_genomi_tools(self) -> None:
        response = handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})

        self.assertIsNotNone(response)
        assert response is not None
        tools = response["result"]["tools"]
        names = {tool["name"] for tool in tools}
        # Default tools/list returns only the base set (genomi.* + journal.*
        # + research.*) plus the genomi.invoke dispatcher.
        self.assertEqual(names, DEFAULT_TASK_ENTRY_TOOLS)
        self.assertIn("genomi.parse_source", names)
        self.assertIn("genomi.invoke", names)
        self.assertTrue(all(tool["annotations"]["discoveryRole"] in {"entry_tool", "capability_index", "focused_tool"} for tool in tools))

        # Explicit capability filter still works for CLI debug / direct browsing.
        expanded = handle_request(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"capability": "pharmacogenomics"}}
        )
        assert expanded is not None
        expanded_tools = expanded["result"]["tools"]
        expanded_names = {tool["name"] for tool in expanded["result"]["tools"]}
        self.assertIn("pharmacogenomics.run_pharmcat", expanded_names)
        self.assertTrue(all(tool["annotations"]["toolCapability"] == "pharmacogenomics" for tool in expanded_tools))

        ns_response = handle_request(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"namespace": "active_genome_index"}}
        )
        assert ns_response is not None
        ns_names = {tool["name"] for tool in ns_response["result"]["tools"]}
        self.assertIn("active_genome_index.summarize", ns_names)
        self.assertIn("active_genome_index.classify_callset_qc", ns_names)

    def test_mcp_rejects_unknown_capability_or_namespace(self) -> None:
        unknown_namespace = handle_request(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"namespace": "everything"}}
        )
        self.assertIsNotNone(unknown_namespace)
        assert unknown_namespace is not None
        self.assertEqual(unknown_namespace["error"]["code"], -32602)
        self.assertIn("namespace must be one of", unknown_namespace["error"]["message"])

        unknown_capability = handle_request(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"capability": "everything"}}
        )
        self.assertIsNotNone(unknown_capability)
        assert unknown_capability is not None
        self.assertEqual(unknown_capability["error"]["code"], -32602)
        self.assertIn("capability must be one of", unknown_capability["error"]["message"])

    def test_mcp_tool_call_returns_json_text(self) -> None:
        response = handle_request(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "genomi.list_resources", "arguments": {}},
            }
        )

        self.assertIsNotNone(response)
        assert response is not None
        content = response["result"]["content"][0]
        self.assertEqual(content["type"], "text")
        payload = json.loads(content["text"])
        self.assertEqual(payload["schema"], "genomi-resource-catalog-v1")
        self.assertIn("resource_groups", payload)
        # disclosure block was removed; single shape now.
        self.assertNotIn("disclosure", payload)

    def test_cli_call_returns_presented_shape(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["call", "genomi.list_resources"])
        payload = args.func(args)

        self.assertEqual(payload["schema"], "genomi-resource-catalog-v1")
        self.assertIn("resource_groups", payload)
        self.assertNotIn("disclosure", payload)

    def test_cli_call_debug_raw_returns_raw_dict(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["call", "genomi.list_resources", "--debug-raw"])
        payload = args.func(args)

        self.assertEqual(payload["schema"], "genomi-resource-catalog-v1")
        self.assertIn("resource_groups", payload)
        # debug-raw bypasses present_result entirely.
        self.assertNotIn("disclosure", payload)

    def test_mcp_tool_call_returns_in_progress_background_job_after_timeout(self) -> None:
        running_job = {
            "schema": background_jobs.JOB_SCHEMA,
            "job_id": "runtime-list-resources-test",
            "operation": "genomi.list_resources",
            "status": "running",
            "created_at": "2026-05-20T00:00:00+00:00",
            "started_at": "2026-05-20T00:00:00+00:00",
            "pid": 123,
        }
        with (
            mock.patch.dict(os.environ, {"GENOMI_MCP_BACKGROUND": "1", "GENOMI_MCP_BACKGROUND_TIMEOUT_SECONDS": "0.01"}),
            mock.patch("genomi.interfaces.mcp.background_jobs.start_operation_job", return_value=running_job) as start_job,
            mock.patch("genomi.interfaces.mcp.background_jobs.wait_for_job", return_value=running_job) as wait_job,
        ):
            response = handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 5,
                    "method": "tools/call",
                    "params": {"name": "genomi.list_resources", "arguments": {}},
                }
            )

        self.assertIsNotNone(response)
        assert response is not None
        start_job.assert_called_once_with("genomi.list_resources", {})
        wait_job.assert_called_once_with("runtime-list-resources-test", timeout_seconds=0.01)
        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(payload["status"], "in_progress")
        self.assertEqual(payload["job_id"], "runtime-list-resources-test")
        self.assertEqual(payload["check"]["operation"], "genomi.check_background_job")
        self.assertEqual(payload["evidence_envelope"]["schema"], "genomi-evidence-envelope-v1")
        self.assertEqual(payload["evidence_envelope"]["finding_state"], "materialization_incomplete")
        self.assertIn("in_progress:poll_runtime_check_background_job", payload["evidence_envelope"]["guidance"])
        self.assertEqual(payload["evidence_envelope"]["next_actions"][0]["operation"], "genomi.check_background_job")

    def test_operation_error_json_uses_evidence_envelope_schema(self) -> None:
        payload = OperationError("invalid_params", "missing required input").to_json(operation="genomi.list_resources")

        self.assertEqual(payload["status"], "invalid_params")
        self.assertEqual(payload["evidence_envelope"]["schema"], "genomi-evidence-envelope-v1")
        self.assertEqual(payload["evidence_envelope"]["operation"], "genomi.list_resources")
        self.assertEqual(payload["evidence_envelope"]["finding_state"], "not_assessed")
        self.assertIn("invalid_input:fix_params_before_retry", payload["evidence_envelope"]["guidance"])

    def test_mcp_failed_background_job_uses_evidence_envelope_schema(self) -> None:
        failed_job = {
            "schema": background_jobs.JOB_SCHEMA,
            "job_id": "runtime-list-resources-failed",
            "operation": "genomi.list_resources",
            "status": "failed",
            "error": {"code": "background_job_failed", "message": "worker stopped"},
        }
        with (
            mock.patch.dict(os.environ, {"GENOMI_MCP_BACKGROUND": "1"}),
            mock.patch("genomi.interfaces.mcp.background_jobs.start_operation_job", return_value=failed_job),
            mock.patch("genomi.interfaces.mcp.background_jobs.wait_for_job", return_value=failed_job),
        ):
            response = handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 55,
                    "method": "tools/call",
                    "params": {"name": "genomi.list_resources", "arguments": {}},
                }
            )

        self.assertIsNotNone(response)
        assert response is not None
        self.assertTrue(response["result"]["isError"])
        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(payload["status"], "background_job_failed")
        self.assertEqual(payload["evidence_envelope"]["schema"], "genomi-evidence-envelope-v1")
        self.assertEqual(payload["evidence_envelope"]["operation"], "genomi.list_resources")
        self.assertIn("operation_failed:inspect_error_before_retry", payload["evidence_envelope"]["guidance"])

    def test_mcp_tool_call_presents_background_result_when_completed_quickly(self) -> None:
        raw_result = call_operation("genomi.list_resources")
        completed_job = {
            "schema": background_jobs.JOB_SCHEMA,
            "job_id": "runtime-list-resources-done",
            "operation": "genomi.list_resources",
            "status": "completed",
            "result": raw_result,
        }
        with (
            mock.patch.dict(os.environ, {"GENOMI_MCP_BACKGROUND": "1"}),
            mock.patch("genomi.interfaces.mcp.background_jobs.start_operation_job", return_value=completed_job),
            mock.patch("genomi.interfaces.mcp.background_jobs.wait_for_job", return_value=completed_job),
        ):
            response = handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 6,
                    "method": "tools/call",
                    "params": {"name": "genomi.list_resources", "arguments": {}},
                }
            )

        self.assertIsNotNone(response)
        assert response is not None
        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(payload["schema"], "genomi-resource-catalog-v1")
        self.assertIn("resource_groups", payload)
        self.assertNotIn("disclosure", payload)

    def test_runtime_check_background_job_returns_presented_result(self) -> None:
        job_id = "runtime-list-resources-completed"
        raw_result = call_operation("genomi.list_resources")
        job_path = background_jobs.jobs_dir() / f"{job_id}.json"
        background_jobs.write_job(
            job_path,
            {
                "schema": background_jobs.JOB_SCHEMA,
                "job_id": job_id,
                "operation": "genomi.list_resources",
                "params": {},
                "params_digest": background_jobs.operation_params_digest("genomi.list_resources", {}),
                "status": "completed",
                "created_at": "2026-05-20T00:00:00+00:00",
                "started_at": "2026-05-20T00:00:00+00:00",
                "finished_at": "2026-05-20T00:00:01+00:00",
                "pid": 123,
                "result": raw_result,
            },
        )

        result = call_operation("genomi.check_background_job", {"job_id": job_id})

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["job_id"], job_id)
        self.assertEqual(result["operation_result"]["schema"], "genomi-resource-catalog-v1")
        self.assertIn("resource_groups", result["operation_result"])
        self.assertNotIn("disclosure", result["operation_result"])

        response = handle_request(
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {"name": "genomi.check_background_job", "arguments": {"job_id": job_id}},
            }
        )
        assert response is not None
        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertNotIn("disclosure", payload)

    def test_background_job_reuses_active_same_operation_and_params(self) -> None:
        digest = background_jobs.operation_params_digest("genomi.list_resources", {})
        job_id = "runtime-list-resources-active"
        background_jobs.write_job(
            background_jobs.jobs_dir() / f"{job_id}.json",
            {
                "schema": background_jobs.JOB_SCHEMA,
                "job_id": job_id,
                "operation": "genomi.list_resources",
                "params": {},
                "params_digest": digest,
                "status": "queued",
                "created_at": "2026-05-20T00:00:00+00:00",
            },
        )

        with mock.patch("genomi.runtime.background_jobs.subprocess.Popen") as popen:
            job = background_jobs.start_operation_job("genomi.list_resources", {})

        popen.assert_not_called()
        self.assertEqual(job["job_id"], job_id)
        self.assertTrue(job["reused_existing"])

    def _write_running_job(self, job_id: str, **overrides: object) -> Path:
        job_path = background_jobs.jobs_dir() / f"{job_id}.json"
        # A live pid (this process) so the pid probe alone never marks it dead;
        # the staleness path is what these tests exercise.
        job = {
            "schema": background_jobs.JOB_SCHEMA,
            "job_id": job_id,
            "operation": "genomi.list_resources",
            "params": {},
            "params_digest": background_jobs.operation_params_digest("genomi.list_resources", {}),
            "status": "running",
            "pid": os.getpid(),
            "created_at": "2026-05-20T00:00:00+00:00",
            "started_at": background_jobs.utc_now(),
            "heartbeat_at": background_jobs.utc_now(),
        }
        job.update(overrides)
        background_jobs.write_job(job_path, job)
        return job_path

    def test_running_job_with_fresh_heartbeat_stays_active(self) -> None:
        job_path = self._write_running_job("hb-fresh")
        job = background_jobs.read_job(job_path=job_path)
        self.assertEqual(job["status"], "running")
        status = background_jobs.public_job_status(job)
        self.assertEqual(status["status"], "in_progress")
        self.assertIn("seconds_since_heartbeat", status)

    def test_running_job_with_stale_heartbeat_is_marked_failed(self) -> None:
        # A zombie/defunct worker still answers os.kill(pid, 0); the stale
        # heartbeat is what flips it to failed instead of "running" forever.
        stale = "2026-05-20T00:00:00+00:00"
        job_path = self._write_running_job("hb-stale", heartbeat_at=stale, started_at=stale)
        job = background_jobs.read_job(job_path=job_path)
        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["error"]["code"], "background_job_stalled")
        # Persisted, so a second read sees the terminal status.
        self.assertEqual(background_jobs.read_job(job_path=job_path)["status"], "failed")

    def test_record_heartbeat_advances_running_job_and_skips_terminal(self) -> None:
        job_path = self._write_running_job("hb-advance", heartbeat_at="2026-05-20T00:00:00+00:00")
        background_jobs.record_heartbeat(job_path)
        bumped = background_jobs._read_job_file(job_path)
        self.assertNotEqual(bumped["heartbeat_at"], "2026-05-20T00:00:00+00:00")

        background_jobs.write_job(job_path, {**bumped, "status": "completed"})
        background_jobs.record_heartbeat(job_path)
        after = background_jobs._read_job_file(job_path)
        self.assertEqual(after["status"], "completed")

    def test_worker_termination_handler_records_failed_status(self) -> None:
        from genomi.runtime import job_worker

        job_path = self._write_running_job("signal-term")
        registered: dict[int, object] = {}
        with mock.patch("genomi.runtime.job_worker.signal.signal", side_effect=lambda sig, fn: registered.__setitem__(sig, fn)):
            job_worker._install_termination_handlers(job_path, threading.Event())

        handler = registered[job_worker.signal.SIGTERM]
        with mock.patch("genomi.runtime.job_worker.os._exit") as exit_mock:
            handler(int(job_worker.signal.SIGTERM), None)  # type: ignore[operator]
        exit_mock.assert_called_once_with(1)

        job = background_jobs._read_job_file(job_path)
        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["error"]["code"], "background_job_signal")

    def test_mcp_parse_default_disclosure_hides_artifact_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vcf = Path(tmp) / "sample.vcf"
            vcf.write_text(
                "##fileformat=VCFv4.2\n"
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tsample\n"
                "10\t94761900\trs4244285\tG\tA\t50\tPASS\t.\tGT:DP:GQ\t0/1:31:99\n",
                encoding="utf-8",
            )
            response = handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {
                        "name": "genomi.parse_source",
                        "arguments": {"source": str(vcf), "genome_build": "GRCh38"},
                    },
                }
            )

        self.assertIsNotNone(response)
        assert response is not None
        text = response["result"]["content"][0]["text"]
        payload = json.loads(text)
        self.assertNotIn("disclosure", payload)
        self.assertEqual(payload["steps"][0]["result"]["stats"]["total_records"], 1)
        self.assertNotIn("outputs", payload)
        self.assertNotIn("project_dir", payload)
        self.assertNotIn(str(vcf.resolve(strict=False)), text)

    def test_mcp_pgx_review_default_disclosure_summarizes_evidence(self) -> None:
        large_result = {
            "schema": "genomi-pgx-medication-review-v1",
            "ok": True,
            "status": "completed",
            "query": {"drug": "clopidogrel", "rsid": "rs4244285"},
            "evidence_state": {"status": "source_and_sample_evidence_present"},
            "interpretation_readiness": {"status": "ready_for_agent_synthesis"},
            "public_evidence": {
                "source_evidence_count": 1,
                "source_availability": {
                    "status": "source_evidence_available",
                    "sources": [{"source_id": "clinpgx", "status": "available", "evidence_count": 1}],
                },
                "clinpgx": {
                    "status": "completed",
                    "guideline_annotations": [{"summary": "Use alternate therapy.", "raw_json": {"large": "payload"}}],
                },
            },
            "sample_evidence": {
                "sample_context_requested": True,
                "sample_match_count": 1,
                "variant_lookups": [
                    {
                        "sample_context": {
                            "matches": [
                                {
                                    "rsid": "rs4244285",
                                    "chrom": "10",
                                    "pos": 94761900,
                                    "ref": "G",
                                    "alt": "A",
                                    "genotype": "0/1",
                                }
                            ]
                        }
                    }
                ],
            },
            "answer_support": {
                "status": "source_and_sample_evidence_present",
                "public_signal_count": 1,
                "sample_signal_count": 1,
                "source_recommendation_summaries": [{"summary": "Use alternate therapy.", "raw_json": {"large": "payload"}}],
            },
            "evidence_matrix": {"items": [{"raw_json": {"large": "payload"}}]},
        }
        with mock.patch("genomi.operations.pgx.review_medication_interaction", return_value=large_result):
            response = handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 5,
                    "method": "tools/call",
                    "params": {"name": "pharmacogenomics.review_medication", "arguments": {"drug": "clopidogrel", "rsid": "rs4244285"}},
                }
            )

        self.assertIsNotNone(response)
        assert response is not None
        text = response["result"]["content"][0]["text"]
        payload = json.loads(text)
        self.assertNotIn("disclosure", payload)
        self.assertEqual(payload["sample_evidence"]["variant_matches"][0]["genotype"], "0/1")
        self.assertNotIn("variant_lookups", payload["sample_evidence"])
        self.assertNotIn("evidence_matrix", payload)
        self.assertNotIn("raw_json", text)


    def test_describe_context_surfaces_active_response_profile_default(self) -> None:
        context = call_operation("genomi.describe_context")
        profile = context.get("active_response_profile")
        self.assertIsInstance(profile, dict)
        self.assertEqual(profile["id"], "eli5")
        self.assertEqual(profile["source"], "default")
        self.assertTrue(profile["guidance"].strip())
        self.assertTrue(profile["label"].strip())

    def test_set_response_profile_persists_and_surfaces(self) -> None:
        from genomi.runtime.host_response import host_response_profiles

        result = call_operation("genomi.set_response_profile", {"profile": "literate"})
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["active_response_profile"]["id"], "literate")
        self.assertEqual(result["active_response_profile"]["source"], "explicit")

        catalog = host_response_profiles()
        literate_entry = next(
            profile
            for profile in catalog["profiles"]
            if isinstance(profile, dict) and profile.get("id") == "literate"
        )

        context = call_operation("genomi.describe_context")
        profile = context["active_response_profile"]
        self.assertEqual(profile["id"], "literate")
        self.assertEqual(profile["source"], "explicit")
        self.assertEqual(profile["guidance"], literate_entry["guidance"])
        self.assertEqual(profile["label"], literate_entry["label"])

    def test_set_response_profile_rejects_invalid_id(self) -> None:
        with self.assertRaises(OperationError) as raised:
            call_operation("genomi.set_response_profile", {"profile": "nope"})
        self.assertEqual(raised.exception.code, "invalid_response_profile")
if __name__ == "__main__":
    import unittest

    unittest.main()
