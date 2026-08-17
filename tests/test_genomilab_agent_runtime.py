from __future__ import annotations

import json
import unittest
from unittest import mock

from genomi.interfaces.mcp import handle_request
from genomi.lab import agent_runtime
from genomi.lab.workspace_application import WorkspaceApplication, genome_metadata


class _FakeAgentRuntime:
    def __init__(self, host: agent_runtime.AgentHostContext) -> None:
        self.host = host
        self.closed = False
        self.service = self
        self.authorization_handoff: dict[str, object] | None = None

    def open_workspace(self, *, open_portal: bool = True) -> dict[str, object]:
        return {
            "status": "ready",
            "execution": {"owner": "underlying_agent"},
            "agent_host": self.host.to_dict(),
            "portal": {"status": "ready" if open_portal else "not_started"},
        }

    def close(self) -> None:
        self.closed = True

    def prepare_agent_authorization(
        self,
        investigation_id: str,
        *,
        observation_revision_ids: list[str] | None = None,
        purpose: str | None = None,
    ) -> dict[str, object]:
        assert investigation_id == "investigation-acde1234"
        assert observation_revision_ids is None
        assert purpose is None
        return {
            "status": "authorization_required",
            "candidate": {
                "investigation_id": investigation_id,
                "purpose": "Private generic-client purpose",
                "authorization_scope": {"agent_session": {}},
                "authorization_candidate_receipt": "private-generic-receipt",
            },
            "next_action": {
                "owner": "patient_portal",
                "action": "review_and_approve_exact_context",
            },
        }

    def open_portal(
        self, *, authorization_handoff: dict[str, object] | None = None
    ) -> dict[str, object]:
        self.authorization_handoff = authorization_handoff
        return {
            "status": "ready",
            "role": "patient_onboarding_approval_and_monitoring",
            "launch_url": "http://127.0.0.1:48123/#token=opaque-launch",
        }


class GenomiLabAgentRuntimeTests(unittest.TestCase):
    def tearDown(self) -> None:
        agent_runtime.close_agent_runtime()

    @staticmethod
    def _initialize(name: str) -> dict[str, object]:
        response = handle_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "clientInfo": {"name": name, "version": "test"},
                },
            },
            transport="stdio",
        )
        assert response is not None
        return response

    def test_claude_codex_and_generic_mcp_clients_share_the_host_owned_path(
        self,
    ) -> None:
        for client_name in ("Claude Code", "Codex", "Research Workbench"):
            with self.subTest(client_name=client_name):
                agent_runtime.reset_agent_runtime_for_tests()
                initialized = self._initialize(client_name)
                self.assertEqual(initialized["result"]["serverInfo"]["name"], "genomi")
                with (
                    mock.patch(
                        "genomi.lab.agent_runtime.GenomiLabAgentRuntime",
                        _FakeAgentRuntime,
                    ),
                    mock.patch(
                        "genomi.interfaces.mcp.background_jobs.start_operation_job"
                    ) as background,
                ):
                    response = handle_request(
                        {
                            "jsonrpc": "2.0",
                            "id": 2,
                            "method": "tools/call",
                            "params": {
                                "name": "genomilab.open_workspace",
                                "arguments": {"open_portal": False},
                            },
                        },
                        transport="stdio",
                    )
                assert response is not None
                background.assert_not_called()
                payload = json.loads(response["result"]["content"][0]["text"])
                self.assertEqual(payload["status"], "ready")
                self.assertEqual(payload["execution"]["owner"], "underlying_agent")
                self.assertEqual(payload["agent_host"]["name"], client_name)
                self.assertEqual(payload["agent_host"]["transport"], "stdio")
                self.assertIn(
                    client_name,
                    payload["agent_host"]["processing_destination"],
                )

    def test_same_client_reinitialize_closes_prior_patient_session(self) -> None:
        agent_runtime.reset_agent_runtime_for_tests()
        with mock.patch(
            "genomi.lab.agent_runtime.GenomiLabAgentRuntime",
            _FakeAgentRuntime,
        ):
            self._initialize("Codex")
            first = agent_runtime.current_agent_runtime()
            first_session_id = first.host.agent_session_id

            self._initialize("Codex")
            second = agent_runtime.current_agent_runtime()

        self.assertTrue(first.closed)
        self.assertIsNot(first, second)
        self.assertNotEqual(first_session_id, second.host.agent_session_id)
        self.assertFalse(second.closed)

    def test_http_initialize_does_not_replace_active_stdio_session(self) -> None:
        agent_runtime.reset_agent_runtime_for_tests()
        with mock.patch(
            "genomi.lab.agent_runtime.GenomiLabAgentRuntime",
            _FakeAgentRuntime,
        ):
            self._initialize("Codex")
            runtime = agent_runtime.current_agent_runtime()

            initialized = handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "initialize",
                    "params": {
                        "clientInfo": {"name": "Remote client", "version": "1"}
                    },
                },
                transport="http",
            )
            assert initialized is not None
            remote_call = handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": "genomilab.open_workspace",
                        "arguments": {"open_portal": False},
                    },
                },
                transport="http",
            )

            self.assertEqual(initialized["result"]["serverInfo"]["name"], "genomi")
            self.assertIs(agent_runtime.current_agent_runtime(), runtime)
            self.assertFalse(runtime.closed)
            self.assertEqual(runtime.host.name, "Codex")
            self.assertEqual(agent_runtime._HOST.name, "Codex")

        assert remote_call is not None
        self.assertTrue(remote_call["result"]["isError"])
        payload = json.loads(remote_call["result"]["content"][0]["text"])
        self.assertEqual(payload["status"], "genomilab_unavailable")
        self.assertIn("local stdio MCP session", payload["message"])

    def test_generic_mcp_authorization_handoff_stays_private(
        self,
    ) -> None:
        agent_runtime.reset_agent_runtime_for_tests()
        with mock.patch(
            "genomi.lab.agent_runtime.GenomiLabAgentRuntime",
            _FakeAgentRuntime,
        ):
            self._initialize("Research Workbench")
            runtime = agent_runtime.current_agent_runtime()
            response = handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "genomilab.prepare_authorization",
                        "arguments": {
                            "investigation_id": "investigation-acde1234"
                        },
                    },
                },
                transport="stdio",
            )

        assert response is not None
        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(payload["status"], "authorization_required")
        self.assertEqual(payload["portal"]["status"], "ready")
        self.assertNotIn("candidate", payload)
        self.assertNotIn("Private generic-client purpose", json.dumps(payload))
        self.assertNotIn("private-generic-receipt", json.dumps(payload))
        self.assertEqual(runtime.host.name, "Research Workbench")
        assert isinstance(runtime.authorization_handoff, dict)
        self.assertEqual(
            runtime.authorization_handoff["authorization_candidate"][
                "authorization_candidate_receipt"
            ],
            "private-generic-receipt",
        )

    def test_patient_operations_fail_closed_over_http_mcp(self) -> None:
        agent_runtime.reset_agent_runtime_for_tests()
        initialized = handle_request(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "initialize",
                "params": {"clientInfo": {"name": "Remote client", "version": "1"}},
            },
            transport="http",
        )
        assert initialized is not None
        response = handle_request(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "genomilab.open_workspace",
                    "arguments": {"open_portal": False},
                },
            },
            transport="http",
        )
        assert response is not None
        self.assertTrue(response["result"]["isError"])
        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(payload["status"], "genomilab_unavailable")
        self.assertIn("local stdio MCP session", payload["message"])

    def test_setup_guidance_covers_existing_agi_and_vcf_intake_paths(
        self,
    ) -> None:
        def bootstrap(context: dict[str, object]) -> dict[str, object]:
            application = WorkspaceApplication(
                store=object(),
                session_id="setup-guidance-session",
                describe_context=lambda: context,
                current_context=lambda: ({}, ""),
                bind_user=lambda _user_id: None,
                unbind_user=lambda: None,
                genome_metadata=genome_metadata,
                active_context_receipt=lambda _investigation, _snapshot: {},
                agent_manifest=lambda: {},
                evidence_manifest=lambda: {},
                integration_manifest=lambda: {},
            )
            return application.bootstrap()

        no_user = bootstrap({})
        self.assertEqual(no_user["code"], "genomi_user_required")
        self.assertIn("VCF", no_user["setup"]["action"])
        self.assertIn("query-ready Active Genome Index", no_user["setup"]["action"])

        unfinished = bootstrap(
            {
                "active_user_id": "user-acde1234",
                "active_user": {"nickname": "Synthetic user"},
                "active_agi_id": "agi-acde1234",
                "active_genome_index": {
                    "agi_snapshot_id": "agi-snapshot-acde1234",
                    "active_genome_index_readiness": {"status": "incomplete"},
                },
            }
        )
        self.assertEqual(unfinished["code"], "active_genome_index_required")
        self.assertIn("select or finish", unfinished["setup"]["action"])
        self.assertIn("VCF", unfinished["setup"]["action"])
        self.assertIn("query-ready", unfinished["setup"]["action"])


if __name__ == "__main__":
    unittest.main()
