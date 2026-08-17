from __future__ import annotations

import json
import unittest
from unittest import mock

from genomi.interfaces.mcp import handle_request
from genomi.interfaces.presentation import present_result


class _FakeService:
    def __init__(self, inspection: dict[str, object] | None = None) -> None:
        self.inspection = inspection or {}

    def inspect_agent_investigation(
        self, investigation_id: str
    ) -> dict[str, object]:
        assert investigation_id == "investigation-a"
        return self.inspection

    def prepare_agent_authorization(
        self,
        investigation_id: str,
        *,
        observation_revision_ids: list[str] | None = None,
        purpose: str | None = None,
    ) -> dict[str, object]:
        assert investigation_id == "investigation-a"
        assert observation_revision_ids is None
        assert purpose is None
        return {
            "status": "authorization_required",
            "candidate": {
                "investigation_id": "investigation-a",
                "purpose": "Private patient purpose",
                "observation_revision_ids": ["observation-private-a"],
                "observations": [
                    {"label": "Private patient phenotype", "gene": "PRIVATE1"}
                ],
                "authorization_candidate_receipt": "private-candidate-receipt",
                "authorization_scope": {"agent_session": {}, "providers": []},
            },
            "next_action": {
                "owner": "patient_portal",
                "action": "review_and_approve_exact_context",
            },
        }


class _FakeRuntime:
    def __init__(
        self,
        *,
        workspace: dict[str, object] | None = None,
        inspection: dict[str, object] | None = None,
    ) -> None:
        self.workspace = workspace or {}
        self.service = _FakeService(inspection)
        self.authorization_handoffs: list[dict[str, object] | None] = []

    def open_workspace(self, *, open_portal: bool = True) -> dict[str, object]:
        assert open_portal is False
        return self.workspace

    def open_portal(
        self, *, authorization_handoff: dict[str, object] | None = None
    ) -> dict[str, object]:
        self.authorization_handoffs.append(authorization_handoff)
        return {
            "status": "ready",
            "role": "patient_onboarding_approval_and_monitoring",
            "base_url": "http://127.0.0.1:8123",
            "launch_url": "http://127.0.0.1:8123/launch?token=portal-token",
        }


class GenomiLabMcpPresentationTests(unittest.TestCase):
    @staticmethod
    def _call(
        operation: str,
        arguments: dict[str, object],
        runtime: _FakeRuntime,
    ) -> dict[str, object]:
        with mock.patch(
            "genomi.operations.registry.handlers_genomilab.current_agent_runtime",
            return_value=runtime,
        ):
            response = handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": operation, "arguments": arguments},
                },
                transport="stdio",
            )
        assert response is not None
        assert response["result"].get("isError") is not True
        return json.loads(response["result"]["content"][0]["text"])

    def test_open_workspace_presents_navigation_and_counts_without_patient_data(
        self,
    ) -> None:
        runtime = _FakeRuntime(
            workspace={
                "status": "ready",
                "product": "GenomiLab",
                "workspace": {
                    "workspace_id": "workspace-a",
                    "user_id": "private-user-a",
                    "display_name": "Private Patient Name",
                    "active_genome_index": {
                        "readiness": "completed",
                        "agi_id": "agi-private-a",
                    },
                    "profile_onboarding": {
                        "observation_count": 1,
                        "source_artifact_count": 1,
                        "specimen_count": 1,
                        "assay_count": 1,
                        "private_label": "Private onboarding label",
                    },
                    "profile": {
                        "user_id": "private-user-a",
                        "observations": [
                            {
                                "observation_revision_id": "observation-private-a",
                                "label": "Private patient phenotype",
                            }
                        ],
                        "observation_history": [
                            {"label": "Private historical phenotype"}
                        ],
                        "source_artifacts": [{"title": "Private report"}],
                        "specimens": [{"body_site": "Private body site"}],
                        "assays": [{"laboratory": "Private laboratory"}],
                        "genome": {
                            "agi_id": "agi-private-a",
                            "agi_snapshot_id": "agi-snapshot-private-a",
                            "readiness": "completed",
                        },
                    },
                    "investigations": [
                        {
                            "investigation_id": "investigation-a",
                            "question": "Private investigation question",
                            "disease_scope": "Private disease scope",
                            "status": "running",
                            "private_context_status": "approved_for_session",
                            "state_visibility": "authorized_for_current_agent_session",
                            "domain_revision": 4,
                            "current_plan_version": {"review_status": "accepted"},
                            "current_brief_version": {"version": 1},
                            "current_evidence_records": [
                                {"evidence": "Private evidence"}
                            ],
                            "investigation_events": [{"sequence": 1}],
                            "refresh_lifecycle": {"state": "current"},
                        }
                    ],
                    "evidence_library": [{"evidence": "Private evidence"}],
                    "privacy_activity": {
                        "context_approvals": [{"purpose": "Private purpose"}],
                        "investigation_authorizations": [{}],
                        "outbound_disclosures": [{"destination": "Private place"}],
                        "plan_acceptances": [{}],
                    },
                    "attention": {
                        "plan_reviews": 0,
                        "provider_approvals": 1,
                        "running_jobs": 0,
                        "completed_briefs": 1,
                        "new_evidence_records": 1,
                    },
                },
                "capabilities": {
                    "underlying_agent": {
                        "execution_owner": "underlying_agent",
                        "authorized_intents": ["plan", "execute_accepted_plan"],
                    }
                },
                "execution": {"owner": "underlying_agent"},
                "portal": {
                    "status": "not_started",
                    "role": "patient_onboarding_approval_and_monitoring",
                },
                "diagnostic_path": "/Users/private/genomilab.sqlite3",
            }
        )

        payload = self._call(
            "genomilab.open_workspace", {"open_portal": False}, runtime
        )

        self.assertEqual(payload["workspace"]["workspace_id"], "workspace-a")
        self.assertEqual(
            payload["workspace"]["profile_onboarding"],
            {
                "observation_count": 1,
                "source_artifact_count": 1,
                "specimen_count": 1,
                "assay_count": 1,
            },
        )
        self.assertEqual(
            payload["workspace"]["active_genome_index"],
            {"readiness": "completed"},
        )
        self.assertEqual(
            payload["workspace"]["investigations"],
            [
                {
                    "investigation_id": "investigation-a",
                    "status": "running",
                    "private_context_status": "approved_for_session",
                    "state_visibility": "authorized_for_current_agent_session",
                }
            ],
        )
        self.assertEqual(
            payload["capabilities"]["underlying_agent"]["authorized_intents"],
            ["plan", "execute_accepted_plan"],
        )
        serialized = json.dumps(payload)
        for private_value in (
            "private-user-a",
            "Private Patient Name",
            "Private patient phenotype",
            "Private investigation question",
            "Private disease scope",
            "Private evidence",
            "Private onboarding label",
            "agi-private-a",
            "/Users/private/genomilab.sqlite3",
        ):
            self.assertNotIn(private_value, serialized)

    def test_submit_brief_tool_advertises_the_exact_canonical_wire_shape(
        self,
    ) -> None:
        response = handle_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {},
            },
            transport="stdio",
        )

        assert response is not None
        tool = next(
            item
            for item in response["result"]["tools"]
            if item["name"] == "genomilab.submit_brief"
        )
        brief_schema = tool["inputSchema"]["properties"]["brief"]
        self.assertFalse(brief_schema["additionalProperties"])
        self.assertEqual(
            set(brief_schema["required"]), set(brief_schema["properties"])
        )
        self.assertNotIn("modality_badges", brief_schema["properties"])
        self.assertIn("timeline", brief_schema["properties"])
        self.assertIn("clinician_questions", brief_schema["properties"])
        self.assertNotIn("professional_questions", brief_schema["properties"])
        self.assertFalse(
            brief_schema["properties"]["claims"]["items"][
                "additionalProperties"
            ]
        )
        self.assertFalse(
            brief_schema["properties"]["timeline"]["items"][
                "additionalProperties"
            ]
        )
        clinician_question = brief_schema["properties"]["clinician_questions"][
            "items"
        ]
        self.assertFalse(clinician_question["additionalProperties"])
        self.assertEqual(
            set(clinician_question["required"]),
            {
                "question",
                "evidence_record_ids",
                "profile_revision_ids",
                "hypothesis_ids",
                "gap_ids",
            },
        )

    def test_check_request_declares_only_conditional_external_job_resume(
        self,
    ) -> None:
        response = handle_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {},
            },
            transport="stdio",
        )

        assert response is not None
        tool = next(
            item
            for item in response["result"]["tools"]
            if item["name"] == "genomilab.check_request"
        )
        self.assertIn(
            "Only when that request is still in progress", tool["description"]
        )
        external_io = tool["annotations"]["externalIO"]
        self.assertEqual(
            external_io,
            [
                "direct_public_evidence_provider_when_resuming_in_progress_request",
                "paperclip_when_resuming_approved_in_progress_request",
            ],
        )
        self.assertEqual(
            tool["annotations"]["dependencyContract"]["externalNetwork"],
            external_io,
        )

    def test_execute_request_declares_each_approved_external_route(self) -> None:
        response = handle_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {},
            },
            transport="stdio",
        )

        assert response is not None
        tool = next(
            item
            for item in response["result"]["tools"]
            if item["name"] == "genomilab.execute_request"
        )
        external_io = tool["annotations"]["externalIO"]
        self.assertEqual(
            external_io,
            [
                "direct_public_evidence_provider_when_exact_request_is_approved",
                "paperclip_when_exact_request_is_approved",
            ],
        )
        self.assertEqual(
            tool["annotations"]["dependencyContract"]["externalNetwork"],
            external_io,
        )

    def test_authorized_inspection_preserves_complete_capability_contracts(
        self,
    ) -> None:
        strength = {
            "state": "not_reported",
            "scheme": None,
            "raw_label": None,
            "raw_value": None,
            "source_locator": None,
        }
        relation_template = {
            "disease_scope": "Approved disease scope",
            "profile_revision_ids": ["observation-approved-a"],
            "source_evidence_record_ids": ["evidence-approved-a"],
            "relation_kind": "variant_disease",
            "direction": "supports",
            "source_supplied_strength": strength,
            "population_context": {
                "state": "not_reported",
                "description": None,
                "source_locator": None,
            },
            "tissue_context": {
                "state": "not_reported",
                "description": None,
                "source_locator": None,
            },
            "specimen_context": {
                "state": "not_reported",
                "description": None,
                "source_locator": None,
            },
            "conflicts": [],
            "uncertainty": ["association_not_causation"],
        }
        request_contract = {
            "required_fields": ["profile_revision_ids", "query", "filters"],
            "optional_fields": [],
            "routes": [
                {
                    "route": "paperclip",
                    "operations": ["search", "lookup"],
                    "operation_contracts": {
                        "search": {
                            "query": {"type": "string", "maximum_length": 4000}
                        }
                    },
                }
            ],
            "fields": {
                "profile_revision_ids": {
                    "type": "unique_string_array",
                    "minimum_items": 1,
                    "allowed_values": ["observation-approved-a"],
                },
                "query": {"type": "public_biomedical_string"},
                "filters": {
                    "type": "public_string_map",
                    "reserved_fields": ["evidence_domain"],
                },
            },
            "cross_field_requirements": [
                {"at_least_one_non_empty": ["query", "filters"]}
            ],
        }
        inspection = {
            "status": "completed",
            "investigation": {
                "investigation_id": "investigation-a",
                "status": "running",
                "private_context_status": "approved_for_session",
                "state_visibility": "authorized_for_current_agent_session",
                "current_plan_version": {
                    "plan": {
                        "steps": [
                            {
                                "id": "relation-step",
                                "capabilities": [
                                    "investigation.register_disease_relation"
                                ],
                            }
                        ],
                        "capability_requests": [
                            {
                                "id": "relation-request",
                                "parameters": relation_template,
                            }
                        ],
                    }
                },
                "current_evidence_records": [
                    {
                        "evidence_record_id": "evidence-approved-a",
                        "evidence": {
                            "records": [
                                {
                                    "title": "Approved source record",
                                    "support": {"direction": "supports"},
                                }
                            ]
                        },
                        "evidence_envelope": {
                            "finding_state": "evidence_present",
                            "observations": {"observation_count": 1},
                        },
                    }
                ],
                "local_artifact_path": "/Users/private/evidence.json",
            },
            "capability_catalog": {
                "investigation.register_disease_relation": {
                    "available": True,
                    "exact_request_templates": [relation_template],
                },
                "public_evidence.retrieve_expression_qtl": {
                    "available": True,
                    "request_contract": request_contract,
                },
            },
            "next_actions": [],
        }
        runtime = _FakeRuntime(inspection=inspection)

        payload = self._call(
            "genomilab.inspect_investigation",
            {"investigation_id": "investigation-a"},
            runtime,
        )

        presented_template = payload["capability_catalog"][
            "investigation.register_disease_relation"
        ]["exact_request_templates"][0]
        self.assertEqual(presented_template, relation_template)
        self.assertEqual(presented_template["source_supplied_strength"], strength)
        presented_contract = payload["capability_catalog"][
            "public_evidence.retrieve_expression_qtl"
        ]["request_contract"]
        self.assertEqual(presented_contract, request_contract)
        self.assertEqual(
            payload["investigation"]["current_plan_version"]["plan"][
                "capability_requests"
            ][0]["parameters"]["source_supplied_strength"],
            strength,
        )
        self.assertEqual(
            payload["investigation"]["current_evidence_records"][0]["evidence"][
                "records"
            ][0]["support"]["direction"],
            "supports",
        )
        self.assertNotIn("local_artifact_path", payload["investigation"])
        self.assertNotIn("[omitted_nested_value]", json.dumps(payload))

    def test_unapproved_inspection_does_not_disclose_catalog_or_patient_state(
        self,
    ) -> None:
        inspection = {
            "status": "completed",
            "investigation": {
                "investigation_id": "investigation-a",
                "status": "awaiting_context_approval",
                "private_context_status": "not_approved",
                "question": "Private investigation question",
                "current_evidence_records": [{"title": "Private evidence"}],
            },
            "capability_catalog": {
                "private.capability": {
                    "exact_request_templates": [
                        {"query": "Private patient-derived query"}
                    ]
                }
            },
            "next_actions": [
                {
                    "operation": "genomilab.prepare_authorization",
                    "reason": "patient_context_approval_required",
                }
            ],
        }

        payload = self._call(
            "genomilab.inspect_investigation",
            {"investigation_id": "investigation-a"},
            _FakeRuntime(inspection=inspection),
        )

        self.assertNotIn("capability_catalog", payload)
        self.assertEqual(
            payload["investigation"],
            {
                "investigation_id": "investigation-a",
                "status": "awaiting_context_approval",
                "private_context_status": "not_approved",
            },
        )
        serialized = json.dumps(payload)
        self.assertNotIn("Private investigation question", serialized)
        self.assertNotIn("Private evidence", serialized)
        self.assertNotIn("Private patient-derived query", serialized)

    def test_prepare_authorization_only_returns_status_and_portal_launch(self) -> None:
        runtime = _FakeRuntime()
        payload = self._call(
            "genomilab.prepare_authorization",
            {"investigation_id": "investigation-a"},
            runtime,
        )

        self.assertEqual(payload["status"], "authorization_required")
        self.assertEqual(payload["portal"]["status"], "ready")
        self.assertIn("launch_url", payload["portal"])
        self.assertNotIn("candidate", payload)
        serialized = json.dumps(payload)
        self.assertNotIn("Private patient purpose", serialized)
        self.assertNotIn("Private patient phenotype", serialized)
        self.assertNotIn("private-candidate-receipt", serialized)
        self.assertEqual(len(runtime.authorization_handoffs), 1)
        handoff = runtime.authorization_handoffs[0]
        self.assertIsInstance(handoff, dict)
        assert isinstance(handoff, dict)
        self.assertEqual(handoff["kind"], "investigation_authorization")
        self.assertEqual(handoff["investigation_id"], "investigation-a")
        self.assertEqual(
            handoff["authorization_candidate"][
                "authorization_candidate_receipt"
            ],
            "private-candidate-receipt",
        )
        self.assertNotIn("private-candidate-receipt", payload["portal"]["launch_url"])

    def test_non_genomilab_generic_redaction_is_unchanged(self) -> None:
        payload = present_result(
            "example.operation",
            {
                "workspace": {"domain_value": "still omitted generically"},
                "nested": {"a": {"b": {"c": {"d": {"e": "too deep"}}}}},
                "artifact_path": "/Users/private/artifact.json",
            },
        )

        self.assertNotIn("workspace", payload)
        self.assertNotIn("artifact_path", payload)
        self.assertIn("[omitted_nested_value]", json.dumps(payload))


if __name__ == "__main__":
    unittest.main()
