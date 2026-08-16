from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from unittest import mock

from genomi.interfaces.cli import build_parser
from genomi.interfaces.mcp import handle_request
from genomi.operations import OperationError, all_operations, call_operation, get_operation
from genomi.runtime import background_jobs

from tests.support.runtime.genomi import (
    DEFAULT_TASK_ENTRY_TOOLS,
    GenomiRuntimeTestCase,
)


class GenomiRuntimeMcpTests(GenomiRuntimeTestCase):
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
        self.assertEqual(set(payload), {"context_policy", "host_response_profiles", "local_runtime", "resource_groups", "source_catalog", "toolset_disclosure"})
        self.assertIn("resource_groups", payload)

    def test_cli_call_returns_presented_shape(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["call", "genomi.list_resources"])
        payload = args.func(args)

        self.assertEqual(set(payload), {"context_policy", "host_response_profiles", "local_runtime", "resource_groups", "source_catalog", "toolset_disclosure"})
        self.assertIn("resource_groups", payload)

    def test_cli_call_debug_raw_returns_raw_dict(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["call", "genomi.list_resources", "--debug-raw"])
        payload = args.func(args)

        self.assertEqual(set(payload), {"context_policy", "host_response_profiles", "local_runtime", "resource_groups", "source_catalog", "toolset_disclosure"})
        self.assertIn("resource_groups", payload)
        # debug-raw bypasses present_result entirely.
        self.assertNotIn("disclosure", payload)

    def test_cli_serve_app_uses_http_workspace_and_opens_browser(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["serve", "--app", "--port", "9876"])

        with mock.patch("genomi.interfaces.cli.mcp.serve_http", return_value=0) as serve_http:
            with self.assertRaises(SystemExit) as raised:
                args.func(args)

        self.assertEqual(raised.exception.code, 0)
        serve_http.assert_called_once_with(host="127.0.0.1", port=9876, open_browser=True)

    def test_cli_serve_auto_opens_workspace_from_terminal(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["serve"])

        with mock.patch("genomi.interfaces.cli._serve_auto_opens_app", return_value=True), mock.patch(
            "genomi.interfaces.cli.mcp.serve_http",
            return_value=0,
        ) as serve_http:
            with self.assertRaises(SystemExit) as raised:
                args.func(args)

        self.assertEqual(raised.exception.code, 0)
        serve_http.assert_called_once_with(host="127.0.0.1", port=8768, open_browser=True)

    def test_cli_serve_auto_keeps_stdio_for_host_agent_pipes(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["serve"])

        with mock.patch("genomi.interfaces.cli._serve_auto_opens_app", return_value=False), mock.patch(
            "genomi.interfaces.cli.mcp.serve_stdio",
            return_value=0,
        ) as serve_stdio:
            with self.assertRaises(SystemExit) as raised:
                args.func(args)

        self.assertEqual(raised.exception.code, 0)
        serve_stdio.assert_called_once_with()

    def test_cli_serve_auto_no_browser_keeps_workspace_headless(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["serve", "--no-browser"])

        with mock.patch("genomi.interfaces.cli._serve_auto_opens_app", return_value=True), mock.patch(
            "genomi.interfaces.cli.mcp.serve_http",
            return_value=0,
        ) as serve_http:
            with self.assertRaises(SystemExit) as raised:
                args.func(args)

        self.assertEqual(raised.exception.code, 0)
        serve_http.assert_called_once_with(host="127.0.0.1", port=8768, open_browser=False)

    def test_cli_serve_app_no_browser_keeps_http_workspace_headless(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["serve", "--app", "--no-browser"])

        with mock.patch("genomi.interfaces.cli.mcp.serve_http", return_value=0) as serve_http:
            with self.assertRaises(SystemExit) as raised:
                args.func(args)

        self.assertEqual(raised.exception.code, 0)
        serve_http.assert_called_once_with(host="127.0.0.1", port=8768, open_browser=False)

    def test_cli_serve_transport_http_preserves_non_browser_mcp_mode(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["serve", "--transport", "http"])

        with mock.patch("genomi.interfaces.cli.mcp.serve_http", return_value=0) as serve_http:
            with self.assertRaises(SystemExit) as raised:
                args.func(args)

        self.assertEqual(raised.exception.code, 0)
        serve_http.assert_called_once_with(host="127.0.0.1", port=8768, open_browser=False)

    def test_mcp_tool_call_returns_in_progress_background_job_after_timeout(self) -> None:
        running_job = {
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
        self.assertEqual(payload["evidence_envelope"]["operation"], "genomi.list_resources")
        self.assertEqual(payload["evidence_envelope"]["finding_state"], "materialization_incomplete")
        self.assertIn("in_progress:poll_runtime_check_background_job", payload["evidence_envelope"]["guidance"])
        self.assertEqual(payload["evidence_envelope"]["next_actions"][0]["operation"], "genomi.check_background_job")

    def test_mcp_lab_capture_operation_executes_inline_when_background_enabled(self) -> None:
        arguments = {
            "investigation_id": "investigation-1",
            "cycle_id": "cycle-1",
            "result_receipt_id": "receipt-1",
            "purpose": "bind clinvar evidence to the current cycle",
            "command_id": "command-1",
            "expected_revision": 3,
        }
        inline_result = {
            "status": "ready",
            "investigation_evidence_record": {"evidence_record_id": "evidence-1"},
        }
        with (
            mock.patch.dict(os.environ, {"GENOMI_MCP_BACKGROUND": "1"}),
            mock.patch("genomi.interfaces.mcp.background_jobs.start_operation_job") as start_job,
            mock.patch("genomi.interfaces.mcp.call_operation", return_value=inline_result) as call_inline,
        ):
            response = handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 56,
                    "method": "tools/call",
                    "params": {"name": "lab.capture_evidence_result", "arguments": arguments},
                }
            )

        start_job.assert_not_called()
        call_inline.assert_called_once_with("lab.capture_evidence_result", arguments)
        self.assertIsNotNone(response)
        assert response is not None
        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["investigation_evidence_record"]["evidence_record_id"], "evidence-1")

    def test_every_lab_operation_is_inline_only(self) -> None:
        lab_tools = [
            tool
            for tool in all_operations()
            if tool["name"].startswith("lab.")
        ]
        self.assertTrue(lab_tools)
        for tool in lab_tools:
            with self.subTest(operation=tool["name"]):
                # Lab state carries patient facts; background execution would
                # spool operation params to the plaintext job file.
                self.assertEqual(tool["annotations"]["mcpExecution"], "inline_only")
                self.assertFalse(get_operation(tool["name"]).mcp_background_eligible)

    def test_operation_error_json_uses_evidence_envelope_contract(self) -> None:
        payload = OperationError("invalid_params", "missing required input").to_json(operation="genomi.list_resources")

        self.assertEqual(payload["status"], "invalid_params")
        self.assertEqual(payload["evidence_envelope"]["operation"], "genomi.list_resources")
        self.assertEqual(payload["evidence_envelope"]["finding_state"], "not_assessed")
        self.assertIn("invalid_input:fix_params_before_retry", payload["evidence_envelope"]["guidance"])

    def test_mcp_failed_background_job_uses_evidence_envelope_contract(self) -> None:
        failed_job = {
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
        self.assertEqual(payload["evidence_envelope"]["operation"], "genomi.list_resources")
        self.assertIn("operation_failed:inspect_error_before_retry", payload["evidence_envelope"]["guidance"])

    def test_mcp_tool_call_presents_background_result_when_completed_quickly(self) -> None:
        raw_result = call_operation("genomi.list_resources")
        completed_job = {
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
        self.assertEqual(set(payload), {"context_policy", "host_response_profiles", "local_runtime", "resource_groups", "source_catalog", "toolset_disclosure"})
        self.assertIn("resource_groups", payload)

    def test_runtime_check_background_job_returns_presented_result(self) -> None:
        job_id = "runtime-list-resources-completed"
        raw_result = call_operation("genomi.list_resources")
        job_path = background_jobs.jobs_dir() / f"{job_id}.json"
        background_jobs.write_job(
            job_path,
            {
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
        self.assertEqual(set(result["operation_result"]), {"context_policy", "host_response_profiles", "local_runtime", "resource_groups", "source_catalog", "toolset_disclosure"})
        self.assertIn("resource_groups", result["operation_result"])

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
        self.assertEqual(set(payload["operation_result"]), {"context_policy", "host_response_profiles", "local_runtime", "resource_groups", "source_catalog", "toolset_disclosure"})

    def test_background_job_reuses_active_same_operation_and_params(self) -> None:
        digest = background_jobs.operation_params_digest("genomi.list_resources", {})
        job_id = "runtime-list-resources-active"
        background_jobs.write_job(
            background_jobs.jobs_dir() / f"{job_id}.json",
            {
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

    def test_forked_pool_child_signal_does_not_falsely_fail_the_job(self) -> None:
        # The handler is inherited by an operation's multiprocessing Pool
        # workers; when that Pool tears down (SIGTERM to workers, even on
        # success) a forked child must die quietly, not stamp the shared job
        # file failed while the real worker is still merging.
        from genomi.runtime import job_worker

        job_path = self._write_running_job("signal-child")
        registered: dict[int, object] = {}
        with (
            mock.patch("genomi.runtime.job_worker.signal.signal", side_effect=lambda sig, fn: registered.__setitem__(sig, fn)),
            mock.patch("genomi.runtime.job_worker.os.getpid", return_value=11111),
        ):
            job_worker._install_termination_handlers(job_path, threading.Event())

        handler = registered[job_worker.signal.SIGTERM]
        sigterm = int(job_worker.signal.SIGTERM)
        with (
            mock.patch("genomi.runtime.job_worker.os.getpid", return_value=22222),  # a forked child
            mock.patch("genomi.runtime.job_worker.os._exit") as exit_mock,
        ):
            handler(sigterm, None)  # type: ignore[operator]

        exit_mock.assert_called_once_with(128 + sigterm)
        # Job left untouched — still running, not falsely failed.
        self.assertEqual(background_jobs._read_job_file(job_path)["status"], "running")
